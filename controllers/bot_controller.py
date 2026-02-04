"""
Bot Controller
Handles Discord bot control APIs
"""

import logging
import os
import asyncio
from typing import Optional

from fastapi import APIRouter

logger = logging.getLogger("lily-discord-adapter")

# Global references to be set by main.py
BOT = None
bot_enabled = True
bot_startup_attempted = False
bot_loop = None  # Store reference to bot's event loop

# APIRouter for bot control endpoints
bot_router = APIRouter(
    prefix="/api/bot",
    tags=["Bot Control"]
)


class BotController:
    """Controller for managing Discord bot state"""
    
    def __init__(self):
        pass
    
    def set_bot_references(self, bot, enabled, startup_attempted, loop=None):
        """Set global references to the bot and its state"""
        global BOT, bot_enabled, bot_startup_attempted, bot_loop
        BOT = bot
        bot_enabled = enabled
        bot_startup_attempted = startup_attempted
        bot_loop = loop
    
    async def enable_bot(self) -> dict:
        """Enable the Discord bot"""
        global bot_enabled, bot_startup_attempted
        bot_token = os.getenv("DISCORD_BOT_TOKEN")
        
        if not bot_token:
            return {"success": False, "message": "DISCORD_BOT_TOKEN not configured"}
        
        if bot_enabled:
            return {"success": True, "message": "Bot is already enabled"}
        
        bot_enabled = True
        bot_startup_attempted = True
        logger.info("Bot enabled via API")
        
        # Bot startup is handled by main.py loop
        
        return {"success": True, "message": "Bot enabled successfully"}
    
    async def disable_bot(self) -> dict:
        """Disable the Discord bot"""
        global BOT, bot_enabled
        
        if not bot_enabled:
            return {"success": True, "message": "Bot is already disabled"}
        
        bot_enabled = False
        logger.info("Bot disabled via API - shutting down bot")
        
        # Close the bot gracefully
        if BOT and not BOT.is_closed():
            try:
                # Schedule bot close in bot's event loop
                if bot_loop and bot_loop.is_running():
                    asyncio.run_coroutine_threadsafe(BOT.close(), bot_loop)
                    logger.info("Bot close scheduled")
                else:
                    await BOT.close()
                    logger.info("Bot closed directly")
            except Exception as e:
                logger.error(f"Error closing bot: {e}")
        
        return {"success": True, "message": "Bot disabled and closed successfully"}
    
    def get_status(self) -> dict:
        """Get the current bot status"""
        global bot_enabled, bot_startup_attempted
        bot_token = os.getenv("DISCORD_BOT_TOKEN")
        
        return {
            "success": True,
            "bot_enabled": bot_enabled,
            "bot_running": not BOT.is_closed() if BOT else False,
            "bot_ready": BOT.is_ready() if BOT else False,
            "bot_startup_attempted": bot_startup_attempted,
            "discord_configured": bool(bot_token)
        }
    
    def get_health_info(self, concurrency_manager) -> dict:
        """Get health check information"""
        global bot_enabled, bot_startup_attempted
        stats = concurrency_manager.stats if concurrency_manager else {}
        
        return {
            "bot_enabled": bot_enabled,
            "bot_startup_attempted": bot_startup_attempted,
            "concurrency": stats
        }


# Create bot controller instance
bot_controller = BotController()


# Register API endpoints
@bot_router.post("/enable")
async def enable_bot():
    """Enable the Discord bot"""
    return await bot_controller.enable_bot()


@bot_router.post("/disable")
async def disable_bot():
    """Disable the Discord bot"""
    return await bot_controller.disable_bot()


@bot_router.get("/status")
async def get_bot_status():
    """Get the current bot status"""
    return bot_controller.get_status()
