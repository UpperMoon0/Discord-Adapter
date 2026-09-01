"""
Lily-Discord-Adapter
Discord bot adapter for Lily-Core
Handles Discord messages and communicates with Lily-Core via HTTP
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

sys.path.insert(0, '/app/Lily-Discord-Adapter')

from controllers.bot_controller import bot_router
from controllers.command_controller import CommandController
from controllers.cookies_controller import cookies_router, ws_cookies_router
from controllers.message_controller import MessageController
from mcp_server import build_mcp_asgi_app, mcp_server
from services.bot_service import bot_service
from services.concurrency_manager import (
    ConcurrencyManager,
    RateLimitConfig,
    UserRateLimiter,
)
from services.lily_core_service import LilyCoreService
from services.music_service import MusicService
from services.session_service import SessionService
from utils.mcp_auth import OptionalBearerAuth
from utils.message_utils import send_message
from utils.service_discovery import ServiceDiscovery

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
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
    """Parse a conventional boolean environment variable."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def get_lily_core_http_url():
    """Get Lily-Core HTTP URL from Consul."""
    if sd:
        return sd.get_service_url("lily-core", "http")
    return None


async def process_message_task(message_data: dict):
    """Worker task to process messages from queue."""
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
        logger.error("Failed to get response from lily-core for user %s", user_id)
        await channel.send("I'm having trouble connecting to my brain right now. Please try again later.")


async def initialize_services():
    """Initialize all services once."""
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
        logger.info("lily-core HTTP URL: %s", http_url)
        if sd:
            ws_url = sd.get_service_url("lily-core", "ws")
            logger.info("lily-core WS URL: %s", ws_url)
    else:
        lily_core_available = False
        logger.warning("lily-core not found in Consul. Chat features will be disabled.")

    bot_service.set_lily_core_status(lily_core_available, http_url, ws_url)

    session_service = SessionService()
    music_service = MusicService()

    logger.info(
        "Concurrency config: max_concurrent=%s, queue_size=%s, workers=%s",
        max_concurrent,
        queue_size,
        num_workers,
    )
    logger.info("lily-core available: %s", lily_core_available)


def create_discord_bot():
    """Create and configure a new Discord bot instance."""
    intents = discord.Intents.default()
    intents.message_content = True
    intents.voice_states = True
    # Member name search requires the privileged Server Members Intent. Keep it
    # opt-in so an existing deployment is not rejected by the Discord gateway.
    intents.members = env_flag("DISCORD_MEMBERS_INTENT", False)

    bot = commands.Bot(
        command_prefix='!',
        intents=intents,
        description='Lily Discord Adapter - Connects Discord to Lily-Core',
    )

    @bot.event
    async def on_ready():
        """Bot is ready and connected to Discord."""
        global message_controller, command_controller

        logger.info("Bot logged in as %s (%s)", bot.user.name, bot.user.id)

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

        logger.info("Lily-Discord-Adapter is ready!")

    return bot


@asynccontextmanager
async def api_lifespan(_app: FastAPI):
    """
    Run the MCP Streamable HTTP session manager in the parent FastAPI lifespan.

    Starlette does not automatically run the lifespan of a mounted ASGI app.
    """
    async with mcp_server.session_manager.run():
        yield


app = FastAPI(
    title="Lily-Discord-Adapter",
    description="Discord adapter, health endpoints, and guild-scoped MCP administration",
    lifespan=api_lifespan,
)

app.include_router(bot_router)
app.include_router(cookies_router)
app.include_router(ws_cookies_router)

# Streamable HTTP MCP endpoint. Use /mcp/ (with the trailing slash).
mcp_asgi_app = OptionalBearerAuth(build_mcp_asgi_app())
app.mount("/mcp", mcp_asgi_app)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    global bot_enabled, bot_startup_attempted
    stats = concurrency_manager.stats if concurrency_manager else {}
    health_info = bot_service.get_health_info(concurrency_manager)

    bot_ready = False
    if BOT and not BOT.is_closed():
        bot_ready = BOT.is_ready()

    return {
        "status": "healthy",
        "service": "lily-discord-adapter",
        "bot_ready": bot_ready,
        "bot_enabled": health_info.get("bot_enabled", bot_enabled),
        "bot_startup_attempted": health_info.get(
            "bot_startup_attempted",
            bot_startup_attempted,
        ),
        "lily_core_available": lily_core_available,
        "discord_enabled": bool(os.getenv("DISCORD_BOT_TOKEN")),
        "mcp_enabled": True,
        "mcp_guild_policy_configured": bool(
            os.getenv("DISCORD_ADMIN_GUILD_IDS", "").strip()
        ),
        "concurrency": health_info.get("concurrency", stats),
    }


@app.get("/ready")
async def readiness_check():
    """Readiness check endpoint - HTTP server is always ready."""
    global bot_enabled, bot_startup_attempted
    stats = concurrency_manager.stats if concurrency_manager else {}
    health_info = bot_service.get_health_info(concurrency_manager)

    bot_ready = False
    if BOT and not BOT.is_closed():
        bot_ready = BOT.is_ready()

    return {
        "status": "ready",
        "bot_ready": bot_ready,
        "bot_enabled": health_info.get("bot_enabled", bot_enabled),
        "bot_startup_attempted": health_info.get(
            "bot_startup_attempted",
            bot_startup_attempted,
        ),
        "lily_core_available": lily_core_available,
        "concurrency": health_info.get("concurrency", stats),
    }


def run_health_server():
    """Run FastAPI + MCP on a separate thread."""
    port = int(os.getenv("PORT", "8004"))
    uvicorn.run(app, host="0.0.0.0", port=port)


async def monitor_lily_core():
    """Background task to monitor Lily-Core availability."""
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
                        logger.info(
                            "lily-core discovered/connected at: %s (WS: %s)",
                            http_url,
                            ws_url,
                        )
                    else:
                        logger.warning("lily-core lost connection or not found.")

                    bot_service.set_lily_core_status(is_available, http_url, ws_url)

        except Exception as exc:
            logger.error("Error in monitor_lily_core: %s", exc)

        await asyncio.sleep(10)


async def shutdown():
    """Graceful shutdown."""
    global concurrency_manager, session_service, BOT
    if concurrency_manager:
        await concurrency_manager.shutdown()
    if session_service:
        session_service._sessions.clear()
    if lily_core_service:
        await lily_core_service.close()
    if BOT and not BOT.is_closed():
        await BOT.close()


async def main():
    """Main entry point."""
    global bot_enabled, bot_startup_attempted, BOT

    bot_token = os.getenv("DISCORD_BOT_TOKEN")

    loop = asyncio.get_running_loop()

    await initialize_services()
    asyncio.create_task(monitor_lily_core())

    bot_service.set_bot_references(
        None,
        bot_enabled,
        bot_startup_attempted,
        loop,
    )

    import threading

    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()

    if not os.getenv("DISCORD_ADMIN_GUILD_IDS", "").strip():
        logger.warning(
            "DISCORD_ADMIN_GUILD_IDS is not configured; MCP Discord tools will "
            "not expose or mutate any guilds."
        )

    if not os.getenv("MCP_BEARER_TOKEN"):
        logger.warning(
            "MCP_BEARER_TOKEN is not configured. Only expose /mcp/ through a "
            "ChatGPT secure tunnel, private network, or authenticating reverse proxy."
        )

    if not bot_token:
        logger.warning("DISCORD_BOT_TOKEN not set - Discord bot features disabled")
        bot_enabled = False
        bot_service.set_bot_references(None, bot_enabled, bot_startup_attempted, loop)
        logger.info("Lily-Discord-Adapter running in HTTP mode (health/MCP endpoints active)")
        while True:
            await asyncio.sleep(3600)

    logger.info("Starting Lily-Discord-Adapter...")
    bot_startup_attempted = True

    while True:
        status = bot_service.get_status()
        current_enabled = status.get("bot_enabled", False)

        if current_enabled:
            try:
                logger.info("Bot enabled. Starting execution...")

                BOT = create_discord_bot()
                bot_service.set_bot_references(BOT, True, True, loop)

                await BOT.start(bot_token)
                logger.info("Bot execution finished (stopped).")
            except Exception as exc:
                logger.error("Bot execution error: %s", exc)
                await asyncio.sleep(5)
            finally:
                if BOT and not BOT.is_closed():
                    try:
                        await BOT.close()
                    except Exception:
                        logger.exception("Failed to close Discord bot")
                BOT = None
        else:
            if int(time.time()) % 60 == 0:
                logger.info("Bot is disabled. Waiting for enable signal...")
            await asyncio.sleep(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
