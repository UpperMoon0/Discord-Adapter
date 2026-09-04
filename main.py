"""Lily Discord Adapter.

Public HTTP exposure is intentionally limited to health/readiness, OAuth, and
OAuth-protected MCP. Legacy bot-control and cookie-management routers are not
mounted on the internet-facing application.
"""

import asyncio
import logging
import os
import sys
import time
from contextlib import asynccontextmanager

import discord
import uvicorn
from discord.ext import commands
from fastapi import FastAPI

sys.path.insert(0, "/app/Lily-Discord-Adapter")

from controllers.command_controller import CommandController
from controllers.message_controller import MessageController
from mcp_server import build_mcp_asgi_app, mcp_server
from services.access_policy_service import access_policy_service
from services.addon_manager import AddonManager
from services.bot_service import bot_service
from services.concurrency_manager import ConcurrencyManager, RateLimitConfig, UserRateLimiter
from services.lily_core_service import LilyCoreService
from services.music_service import MusicService
from services.session_service import SessionService
from utils.mcp_oauth_server import MCPAuth, MCPOAuthManager
from utils.message_utils import send_message
from utils.service_discovery import ServiceDiscovery

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("lily-discord-adapter")

sd = None
lily_core_available = False
bot_enabled = True
bot_startup_attempted = False
session_service = None
lily_core_service = None
music_service = None
message_controller = None
command_controller = None
concurrency_manager = None
user_rate_limiter = None
BOT = None


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def get_lily_core_http_url():
    if sd:
        return sd.get_service_url("lily-core", "http")
    return None


def get_addon_status() -> dict:
    manager = getattr(BOT, "addon_manager", None) if BOT else None
    if manager:
        return manager.status()
    return {
        "entrypoint_group": "discord_adapter.addons",
        "enabled": [],
        "strict": env_flag("DISCORD_ADDON_STRICT", False),
        "load_attempted": False,
        "loaded": [],
        "failed": {},
    }


async def process_message_task(message_data: dict):
    """Process messages already admitted by MessageController's trust policy."""
    user_id = message_data.get("user_id")
    content = message_data.get("text")
    username = message_data.get("username")
    channel = message_data.get("channel")
    attachments = message_data.get("attachments", [])

    response_text = await lily_core_service.send_chat_message(
        user_id=user_id,
        username=username,
        text=content,
        attachments=attachments,
    )

    if response_text:
        await send_message(channel, response_text)
    else:
        logger.error("Failed to get response from lily-core for scoped user %s", user_id)
        await channel.send("I'm having trouble connecting to my brain right now. Please try again later.")


async def initialize_services():
    global sd
    global session_service
    global lily_core_service
    global music_service
    global concurrency_manager
    global user_rate_limiter
    global lily_core_available

    port = int(os.getenv("PORT", "8004"))
    sd = ServiceDiscovery(
        service_name="lily-discord-adapter",
        port=port,
        tags=["discord", "adapter", "mcp"],
    )
    sd.start()

    rate_config = RateLimitConfig(
        max_requests_per_second=int(os.getenv("RATE_LIMIT_RPS", "10")),
        max_concurrent_requests=int(os.getenv("MAX_CONCURRENT_REQUESTS", "5")),
        burst_limit=int(os.getenv("BURST_LIMIT", "20")),
    )

    max_concurrent = int(os.getenv("MAX_CONCURRENT_MESSAGES", "10"))
    queue_size = int(os.getenv("MESSAGE_QUEUE_SIZE", "1000"))
    concurrency_manager = ConcurrencyManager(
        max_concurrent=max_concurrent,
        queue_size=queue_size,
        rate_limit_config=rate_config,
    )
    user_rate_limiter = UserRateLimiter(rate_config)

    num_workers = int(os.getenv("NUM_WORKERS", "4"))
    await concurrency_manager.start_workers(
        num_workers=num_workers,
        worker_func=process_message_task,
    )

    lily_core_service = LilyCoreService(get_lily_core_http_url)
    http_url = await lily_core_service.get_http_url()
    ws_url = None
    if http_url:
        lily_core_available = True
        if sd:
            ws_url = sd.get_service_url("lily-core", "ws")
    else:
        lily_core_available = False
        logger.warning("lily-core not found in Consul; trusted Discord chat will be unavailable")

    bot_service.set_lily_core_status(lily_core_available, http_url, ws_url)
    session_service = SessionService()
    music_service = MusicService()

    trusted_guild_count = len(
        [value for value in os.getenv("DISCORD_CHAT_GUILD_IDS", "").split(",") if value.strip()]
    )
    logger.info(
        "Concurrency config: max_concurrent=%s queue_size=%s workers=%s trusted_chat_guilds=%s",
        max_concurrent,
        queue_size,
        num_workers,
        trusted_guild_count,
    )


class DiscordAdapterBot(commands.Bot):
    """Discord bot host with a stable out-of-tree addon lifecycle."""

    def __init__(self, *args, addon_manager: AddonManager, **kwargs):
        super().__init__(*args, **kwargs)
        self.addon_manager = addon_manager

    async def setup_hook(self) -> None:
        await self.addon_manager.load(self)


def create_discord_bot():
    global message_controller, command_controller

    intents = discord.Intents.default()
    intents.message_content = True
    intents.voice_states = True
    intents.members = env_flag("DISCORD_MEMBERS_INTENT", False)

    addon_manager = AddonManager.from_env()
    bot = DiscordAdapterBot(
        command_prefix="!",
        intents=intents,
        description="Lily Discord Adapter - Connects Discord to Lily-Core",
        addon_manager=addon_manager,
    )

    # This bridge uses DISCORD_CHAT_GUILD_IDS, which is separate from MCP's
    # Redis policy. Full MCP administration remains available for every MCP-
    # allowed guild even when that guild cannot send chat into Lily-Core.
    message_controller = MessageController(
        bot,
        session_service,
        lily_core_service,
        concurrency_manager,
        user_rate_limiter,
    )
    command_controller = CommandController(
        bot,
        session_service,
        lily_core_service,
        music_service,
    )

    @bot.event
    async def on_ready():
        logger.info("Bot logged in as %s (%s)", bot.user.name, bot.user.id)
        try:
            synced = await bot.tree.sync()
            logger.info("Synced %s command(s)", len(synced))
        except Exception as exc:
            logger.error("Failed to sync commands: %s", exc)

        bot_service.set_bot_references(
            bot,
            bot_enabled,
            bot_startup_attempted,
            asyncio.get_running_loop(),
        )
        logger.info("Discord addons: %s", addon_manager.status())
        logger.info("Lily-Discord-Adapter is ready")

    return bot


@asynccontextmanager
async def api_lifespan(_app: FastAPI):
    await access_policy_service.initialize()
    try:
        async with mcp_server.session_manager.run():
            yield
    finally:
        await access_policy_service.close()


app = FastAPI(
    title="Lily-Discord-Adapter",
    description="Health endpoints and authenticated guild-scoped MCP administration",
    lifespan=api_lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# Legacy /api/bot, /api/cookies, and /ws/cookies are deliberately not mounted.
# Discord administration belongs to authenticated MCP; cookies are host-managed
# secrets rather than an HTTP API.

mcp_oauth_manager = MCPOAuthManager.from_env()
if mcp_oauth_manager:
    app.include_router(mcp_oauth_manager.router)

mcp_asgi_app = MCPAuth(build_mcp_asgi_app(), mcp_oauth_manager)
app.mount("/mcp", mcp_asgi_app)


@app.get("/health")
async def health_check():
    """Public liveness without guild IDs, internal URLs, or secret state."""
    global bot_enabled, bot_startup_attempted
    stats = concurrency_manager.stats if concurrency_manager else {}
    health_info = bot_service.get_health_info(concurrency_manager)
    policy = access_policy_service.status()

    bot_ready = bool(BOT and not BOT.is_closed() and BOT.is_ready())
    return {
        "status": "healthy" if policy["store_ready"] else "degraded",
        "service": "lily-discord-adapter",
        "bot_ready": bot_ready,
        "bot_enabled": health_info.get("bot_enabled", bot_enabled),
        "bot_startup_attempted": health_info.get("bot_startup_attempted", bot_startup_attempted),
        "discord_addons": get_addon_status(),
        "mcp_enabled": True,
        "mcp_auth_mode": mcp_asgi_app.mode,
        "mcp_guild_policy_configured": policy["configured"],
        "mcp_policy_store_ready": policy["store_ready"],
        "mcp_policy_revision": policy["revision"],
        "concurrency": health_info.get("concurrency", stats),
    }


@app.get("/ready")
async def readiness_check():
    global bot_enabled, bot_startup_attempted
    stats = concurrency_manager.stats if concurrency_manager else {}
    health_info = bot_service.get_health_info(concurrency_manager)
    policy = access_policy_service.status()
    bot_ready = bool(BOT and not BOT.is_closed() and BOT.is_ready())

    return {
        "status": "ready" if policy["store_ready"] else "degraded",
        "bot_ready": bot_ready,
        "bot_enabled": health_info.get("bot_enabled", bot_enabled),
        "bot_startup_attempted": health_info.get("bot_startup_attempted", bot_startup_attempted),
        "discord_addons": get_addon_status(),
        "mcp_auth_mode": mcp_asgi_app.mode,
        "mcp_policy_store_ready": policy["store_ready"],
        "mcp_guild_policy_configured": policy["configured"],
        "concurrency": health_info.get("concurrency", stats),
    }


def run_health_server():
    port = int(os.getenv("PORT", "8004"))
    # 0.0.0.0 is required inside the container for Traefik. Production binds
    # the host port to loopback and uses a dedicated proxy network.
    uvicorn.run(app, host="0.0.0.0", port=port)


async def monitor_lily_core():
    global lily_core_available
    logger.info("Starting lily-core monitor task")
    while True:
        try:
            if lily_core_service:
                is_available = await lily_core_service.is_available()
                if is_available != lily_core_available:
                    lily_core_available = is_available
                    http_url = None
                    ws_url = None
                    if is_available and sd:
                        http_url = sd.get_service_url("lily-core", "http")
                        ws_url = sd.get_service_url("lily-core", "ws")
                    else:
                        logger.warning("lily-core lost connection or not found")
                    bot_service.set_lily_core_status(is_available, http_url, ws_url)
        except Exception as exc:
            logger.error("Error in monitor_lily_core: %s", type(exc).__name__)
        await asyncio.sleep(10)


async def _shutdown_bot_addons(bot) -> None:
    manager = getattr(bot, "addon_manager", None) if bot else None
    if manager:
        await manager.shutdown()


async def shutdown():
    global concurrency_manager, session_service, BOT
    if concurrency_manager:
        await concurrency_manager.shutdown()
    if session_service:
        session_service._sessions.clear()
    if lily_core_service:
        await lily_core_service.close()
    if BOT:
        await _shutdown_bot_addons(BOT)
    if BOT and not BOT.is_closed():
        await BOT.close()


async def main():
    global bot_enabled, bot_startup_attempted, BOT

    bot_token = os.getenv("DISCORD_BOT_TOKEN")
    loop = asyncio.get_running_loop()

    await initialize_services()
    asyncio.create_task(monitor_lily_core())

    bot_service.set_bot_references(None, bot_enabled, bot_startup_attempted, loop)

    import threading

    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()

    if not os.getenv("REDIS_URL", "").strip():
        logger.warning("REDIS_URL is not configured; Discord MCP policy will fail closed")

    if mcp_asgi_app.mode == "unconfigured":
        logger.warning("MCP authentication is not configured; /mcp/ will fail closed with HTTP 503")
    elif mcp_asgi_app.mode == "bearer":
        logger.warning("MCP is using legacy static bearer authentication; OAuth is recommended")
    else:
        logger.info("MCP OAuth authentication enabled")

    if not bot_token:
        logger.warning("DISCORD_BOT_TOKEN not set - Discord bot features disabled")
        bot_enabled = False
        bot_service.set_bot_references(None, bot_enabled, bot_startup_attempted, loop)
        while True:
            await asyncio.sleep(3600)

    logger.info("Starting Lily-Discord-Adapter")
    bot_startup_attempted = True

    while True:
        current_enabled = bot_service.get_status().get("bot_enabled", False)
        if current_enabled:
            try:
                BOT = create_discord_bot()
                bot_service.set_bot_references(BOT, True, True, loop)
                await BOT.start(bot_token)
            except Exception as exc:
                logger.error("Bot execution error: %s", type(exc).__name__)
                await asyncio.sleep(5)
            finally:
                if BOT:
                    try:
                        await _shutdown_bot_addons(BOT)
                    except Exception:
                        logger.exception("Failed to stop Discord addons")
                if BOT and not BOT.is_closed():
                    try:
                        await BOT.close()
                    except Exception:
                        logger.exception("Failed to close Discord bot")
                BOT = None
        else:
            if int(time.time()) % 60 == 0:
                logger.info("Bot is disabled")
            await asyncio.sleep(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
