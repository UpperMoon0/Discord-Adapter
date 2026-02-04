"""
Lily-Discord-Adapter
Discord bot adapter for Lily-Core
Handles Discord messages and communicates with Lily-Core via WebSocket
"""

import os
import sys
import asyncio
import logging
import json
from datetime import datetime

import discord
from discord.ext import commands
import websockets
import requests

sys.path.insert(0, '/app/Lily-Discord-Adapter')

from utils.service_discovery import ServiceDiscovery
from services.session_service import SessionService
from services.lily_core_service import LilyCoreService
from services.concurrency_manager import (
    ConcurrencyManager,
    RateLimitConfig,
    UserRateLimiter
)
from controllers.message_controller import MessageController
from controllers.command_controller import CommandController
from controllers.lily_core_controller import LilyCoreController
from controllers.bot_controller import bot_controller, bot_app

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("lily-discord-adapter")

# Bot configuration
INTENTS = discord.Intents.default()
INTENTS.message_content = True
INTENTS.voice_states = True

BOT = commands.Bot(
    command_prefix='!',
    intents=INTENTS,
    description='Lily Discord Adapter - Connects Discord to Lily-Core'
)

# Service Discovery
sd = None

# Global availability tracking
lily_core_available = False

# Bot enabled state - bot starts enabled but can be toggled via API
bot_enabled = True
bot_startup_attempted = False

# Services
session_service = None
lily_core_service = None
message_controller = None
command_controller = None
lily_core_controller = None
concurrency_manager = None
user_rate_limiter = None


def get_lily_core_url():
    """Get Lily-Core WebSocket URL from Consul.
    
    Returns None if Consul is unavailable or Lily-Core is not registered.
    Consul is the single source of truth - no fallback to environment variables.
    """
    if sd:
        return sd.get_lily_core_ws_url()
    return None


async def handle_lily_core_message(message: str):
    """Handle incoming messages from Lily-Core"""
    global lily_core_available
    try:
        data = json.loads(message)
        if data.get("type") in ["response", "session_start", "session_end", "session_no_active", "session_expired"]:
            await lily_core_controller.handle_message(message)
    except json.JSONDecodeError:
        logger.error(f"Invalid JSON from Lily-Core: {message}")


async def listen_lily_core():
    """Listen for messages from Lily-Core"""
    global lily_core_available
    try:
        async for message in lily_core_service.websocket:
            await handle_lily_core_message(message)
    except websockets.ConnectionClosed:
        logger.warning("Lily-Core WebSocket connection closed")
    except Exception as e:
        logger.error(f"Error listening to Lily-Core: {e}")
    finally:
        lily_core_available = False


async def process_message_task(message_data: dict):
    """Worker task to process messages from queue"""
    user_id = message_data.get("user_id")
    content = message_data.get("text")
    username = message_data.get("username")
    channel = message_data.get("channel")
    attachments = message_data.get("attachments", [])
    
    # Create and send message to Lily-Core
    message = lily_core_service.create_chat_message(user_id, username, content, attachments)
    await lily_core_service.send_message(message)


@BOT.event
async def on_ready():
    """Bot is ready and connected to Discord"""
    global session_service, lily_core_service, message_controller, command_controller
    global lily_core_controller, concurrency_manager, user_rate_limiter, lily_core_available
    
    logger.info(f"Bot logged in as {BOT.user.name} ({BOT.user.id})")
    
    # Register with Consul for service discovery
    global sd
    port = int(os.getenv("PORT", "8004"))
    sd = ServiceDiscovery(service_name="lily-discord-adapter", port=port, tags=["discord", "adapter"])
    sd.start()
    
    # Initialize services
    
    # Configure rate limiting
    rate_config = RateLimitConfig(
        max_requests_per_second=int(os.getenv("RATE_LIMIT_RPS", "10")),
        max_concurrent_requests=int(os.getenv("MAX_CONCURRENT_REQUESTS", "5")),
        burst_limit=int(os.getenv("BURST_LIMIT", "20"))
    )
    
    # Initialize concurrency manager with configurable limits
    max_concurrent = int(os.getenv("MAX_CONCURRENT_MESSAGES", "10"))
    queue_size = int(os.getenv("MESSAGE_QUEUE_SIZE", "1000"))
    concurrency_manager = ConcurrencyManager(
        max_concurrent=max_concurrent,
        queue_size=queue_size,
        rate_limit_config=rate_config
    )
    user_rate_limiter = UserRateLimiter(rate_config)
    
    # Start worker tasks
    await concurrency_manager.start_workers(
        num_workers=int(os.getenv("NUM_WORKERS", "4")),
        worker_func=process_message_task
    )
    
    lily_core_service = LilyCoreService(get_lily_core_url)
    lily_core_controller = LilyCoreController(session_service)
    
    # Connect to Lily-Core WebSocket
    lily_core_available = await lily_core_service.connect()
    
    if lily_core_available:
        # Start listening for messages from Lily-Core
        asyncio.create_task(listen_lily_core())
    
    # Initialize controllers
    message_controller = MessageController(BOT, session_service, lily_core_service)
    command_controller = CommandController(BOT, session_service, lily_core_service)
    
    # Update bot controller with current references
    bot_controller.set_bot_references(BOT, bot_enabled, bot_startup_attempted)
    
    logger.info("Lily-Discord-Adapter is ready!")
    
    # Log concurrency configuration
    logger.info(f"Concurrency config: max_concurrent={max_concurrent}, queue_size={queue_size}, workers=4")


# Health check endpoint for Docker
from fastapi import FastAPI
import uvicorn

app = FastAPI(
    title="Lily-Discord-Adapter Health",
    description="Health check endpoint for the Discord adapter"
)

# Include bot control router
app.include_router(bot_app)


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    global bot_enabled, bot_startup_attempted
    stats = concurrency_manager.stats if concurrency_manager else {}
    health_info = bot_controller.get_health_info(concurrency_manager)
    return {
        "status": "healthy",
        "service": "lily-discord-adapter",
        "bot_ready": BOT.is_ready(),
        "bot_enabled": health_info.get("bot_enabled", bot_enabled),
        "bot_startup_attempted": health_info.get("bot_startup_attempted", bot_startup_attempted),
        "lily_core_available": lily_core_available,
        "discord_enabled": bool(os.getenv("DISCORD_BOT_TOKEN")),
        "concurrency": health_info.get("concurrency", stats)
    }


@app.get("/ready")
async def readiness_check():
    """Readiness check endpoint - HTTP server is always ready"""
    global bot_enabled, bot_startup_attempted
    stats = concurrency_manager.stats if concurrency_manager else {}
    health_info = bot_controller.get_health_info(concurrency_manager)
    return {
        "status": "ready",
        "bot_ready": BOT.is_ready(),
        "bot_enabled": health_info.get("bot_enabled", bot_enabled),
        "bot_startup_attempted": health_info.get("bot_startup_attempted", bot_startup_attempted),
        "lily_core_available": lily_core_available,
        "concurrency": health_info.get("concurrency", stats)
    }


def run_health_server():
    """Run the health check server on a separate thread"""
    port = int(os.getenv("PORT", "8004"))
    uvicorn.run(app, host="0.0.0.0", port=port)


async def start_bot(token: str):
    """Start the Discord bot"""
    try:
        await BOT.start(token)
    except Exception as e:
        logger.error(f"Error starting bot: {e}")


async def shutdown():
    """Graceful shutdown"""
    global concurrency_manager, session_service
    if concurrency_manager:
        await concurrency_manager.shutdown()
    if session_service:
        # SessionService doesn't have stop(), just clear sessions
        session_service._sessions.clear()
    if lily_core_service:
        await lily_core_service.close()


def main():
    """Main entry point"""
    global bot_enabled, bot_startup_attempted
    
    port = int(os.getenv("PORT", "8004"))
    bot_token = os.getenv("DISCORD_BOT_TOKEN")
    
    # Initialize bot controller references
    bot_controller.set_bot_references(BOT, bot_enabled, bot_startup_attempted)
    
    # Start health check server in a separate thread
    import threading
    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()
    
    if not bot_token:
        logger.warning("DISCORD_BOT_TOKEN not set - Discord bot features disabled")
        bot_enabled = False
        bot_controller.set_bot_references(BOT, bot_enabled, bot_startup_attempted)
        logger.info("Lily-Discord-Adapter running in HTTP mode (health endpoints active)")
        # Keep the HTTP server running - Discord features are disabled
        import time
        while True:
            time.sleep(3600)
    
    # Run the Discord bot
    logger.info("Starting Lily-Discord-Adapter...")
    bot_startup_attempted = True
    bot_controller.set_bot_references(BOT, bot_enabled, bot_startup_attempted)
    if bot_enabled:
        BOT.run(bot_token)
    else:
        logger.info("Bot is disabled, waiting for API to enable...")
        # Keep the HTTP server running and wait for bot to be enabled
        import time
        while not bot_enabled:
            time.sleep(1)
        # Bot was enabled via API, start it now
        BOT.run(bot_token)


if __name__ == "__main__":
    main()
