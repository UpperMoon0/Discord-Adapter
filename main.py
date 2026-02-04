"""
Lily-Discord-Adapter
Discord bot adapter for Lily-Core
Handles Discord messages and communicates with Lily-Core via HTTP
"""

import os
import sys
import asyncio
import time
import logging
import json
from datetime import datetime

import discord
from discord.ext import commands

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
from controllers.bot_controller import bot_controller, bot_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("lily-discord-adapter")

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
concurrency_manager = None
user_rate_limiter = None
BOT = None


def get_lily_core_http_url():
    """Get Lily-Core HTTP URL from Consul.
    
    Returns None if Consul is unavailable or Lily-Core is not registered.
    Consul is the single source of truth - no fallback to environment variables.
    """
    if sd:
        return sd.get_lily_core_http_url()
    return None


async def process_message_task(message_data: dict):
    """Worker task to process messages from queue"""
    user_id = message_data.get("user_id")
    content = message_data.get("text")
    username = message_data.get("username")
    channel = message_data.get("channel")
    attachments = message_data.get("attachments", [])
    
    # Send message to Lily-Core via HTTP (service handles message creation)
    response_text = await lily_core_service.send_chat_message(
        user_id=user_id,
        username=username,
        text=content,
        attachments=attachments
    )
    
    if response_text:
        # Send Lily's response back to Discord
        await channel.send(f"**Lily:** {response_text}")
        
        # Add assistant response to history
        session_service.add_to_history(user_id, "assistant", response_text)
    else:
        logger.error(f"Failed to get response from Lily-Core for user {user_id}")
        await channel.send("**Lily:** I'm having trouble connecting to my brain right now. Please try again later.")


async def initialize_services():
    """Initialize all services once"""
    global sd, session_service, lily_core_service, concurrency_manager, user_rate_limiter, lily_core_available
    
    # Register with Consul for service discovery
    port = int(os.getenv("PORT", "8004"))
    sd = ServiceDiscovery(service_name="lily-discord-adapter", port=port, tags=["discord", "adapter"])
    sd.start()
    
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
    
    # Initialize Lily-Core service with HTTP
    lily_core_service = LilyCoreService(get_lily_core_http_url)
    
    # Check if Lily-Core is available
    http_url = await lily_core_service.get_http_url()
    if http_url:
        lily_core_available = True
        logger.info(f"Lily-Core HTTP URL: {http_url}")
    else:
        lily_core_available = False
        logger.warning("Lily-Core not found in Consul. Chat features will be disabled.")
    
    # Update controller status
    bot_controller.set_lily_core_status(lily_core_available)

    # Initialize session service
    session_service = SessionService()
    
    # Log concurrency configuration
    logger.info(f"Concurrency config: max_concurrent={max_concurrent}, queue_size={queue_size}, workers=4")
    logger.info(f"Lily-Core available: {lily_core_available}")


def create_discord_bot():
    """Create and configure a new Discord bot instance"""
    INTENTS = discord.Intents.default()
    INTENTS.message_content = True
    INTENTS.voice_states = True
    
    bot = commands.Bot(
        command_prefix='!',
        intents=INTENTS,
        description='Lily Discord Adapter - Connects Discord to Lily-Core'
    )
    
    @bot.event
    async def on_ready():
        """Bot is ready and connected to Discord"""
        global message_controller, command_controller
        
        logger.info(f"Bot logged in as {bot.user.name} ({bot.user.id})")
        
        # Initialize controllers with the current bot instance
        message_controller = MessageController(bot, session_service, lily_core_service)
        command_controller = CommandController(bot, session_service, lily_core_service)
        
        # Update bot controller with current references
        bot_controller.set_bot_references(bot, bot_enabled, bot_startup_attempted, asyncio.get_running_loop())
        
        logger.info("Lily-Discord-Adapter is ready!")

    return bot


# Health check endpoint for Docker
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI(
    title="Lily-Discord-Adapter Health",
    description="Health check endpoint for the Discord adapter"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include bot control router
app.include_router(bot_router)


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    global bot_enabled, bot_startup_attempted
    stats = concurrency_manager.stats if concurrency_manager else {}
    health_info = bot_controller.get_health_info(concurrency_manager)
    
    # Check bot ready state safely
    bot_ready = False
    if BOT and not BOT.is_closed():
        bot_ready = BOT.is_ready()
        
    return {
        "status": "healthy",
        "service": "lily-discord-adapter",
        "bot_ready": bot_ready,
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
    
    # Check bot ready state safely
    bot_ready = False
    if BOT and not BOT.is_closed():
        bot_ready = BOT.is_ready()

    return {
        "status": "ready",
        "bot_ready": bot_ready,
        "bot_enabled": health_info.get("bot_enabled", bot_enabled),
        "bot_startup_attempted": health_info.get("bot_startup_attempted", bot_startup_attempted),
        "lily_core_available": lily_core_available,
        "concurrency": health_info.get("concurrency", stats)
    }


def run_health_server():
    """Run the health check server on a separate thread"""
    port = int(os.getenv("PORT", "8004"))
    uvicorn.run(app, host="0.0.0.0", port=port)


async def monitor_lily_core():
    """Background task to monitor Lily-Core availability"""
    global lily_core_available
    while True:
        try:
            if not lily_core_available and lily_core_service:
                http_url = await lily_core_service.get_http_url()
                if http_url:
                    lily_core_available = True
                    bot_controller.set_lily_core_status(True)
                    logger.info(f"Lily-Core discovered at: {http_url}")
        except Exception:
            pass
        await asyncio.sleep(30)


async def shutdown():
    """Graceful shutdown"""
    global concurrency_manager, session_service, BOT
    if concurrency_manager:
        await concurrency_manager.shutdown()
    if session_service:
        # SessionService doesn't have stop(), just clear sessions
        session_service._sessions.clear()
    if lily_core_service:
        await lily_core_service.close()
    if BOT and not BOT.is_closed():
        await BOT.close()


async def main():
    """Main entry point"""
    global bot_enabled, bot_startup_attempted, BOT
    
    port = int(os.getenv("PORT", "8004"))
    bot_token = os.getenv("DISCORD_BOT_TOKEN")
    
    # Get the current event loop
    loop = asyncio.get_running_loop()
    
    # Initialize services
    await initialize_services()
    
    # Start background monitoring
    asyncio.create_task(monitor_lily_core())
    
    # Initialize bot controller references with the loop (no bot yet)
    bot_controller.set_bot_references(None, bot_enabled, bot_startup_attempted, loop)
    
    # Start health check server in a separate thread
    import threading
    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()
    
    if not bot_token:
        logger.warning("DISCORD_BOT_TOKEN not set - Discord bot features disabled")
        bot_enabled = False
        bot_controller.set_bot_references(None, bot_enabled, bot_startup_attempted, loop)
        logger.info("Lily-Discord-Adapter running in HTTP mode (health endpoints active)")
        # Keep the HTTP server running - Discord features are disabled
        while True:
            await asyncio.sleep(3600)
    
    # Run the Discord bot
    logger.info("Starting Lily-Discord-Adapter...")
    bot_startup_attempted = True
    
    # Main execution loop
    while True:
        # Check current status from controller (source of truth)
        status = bot_controller.get_status()
        current_enabled = status.get("bot_enabled", False)
        
        if current_enabled:
            try:
                logger.info("Bot enabled. Starting execution...")
                
                # Create a fresh Bot instance for each run
                BOT = create_discord_bot()
                
                # Update controller with new bot
                bot_controller.set_bot_references(BOT, True, True, loop)
                
                # Start the bot
                await BOT.start(bot_token)
                
                logger.info("Bot execution finished (stopped).")
            except Exception as e:
                logger.error(f"Bot execution error: {e}")
                # Prevent tight loop if it crashes immediately
                await asyncio.sleep(5)
            finally:
                # Ensure bot is cleaned up
                if BOT and not BOT.is_closed():
                    try:
                        await BOT.close()
                    except:
                        pass
                BOT = None
        else:
            # Bot is disabled, wait
            # Log periodically to show we are alive
            if int(time.time()) % 60 == 0:
                logger.info("Bot is disabled. Waiting for enable signal...")
            await asyncio.sleep(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
