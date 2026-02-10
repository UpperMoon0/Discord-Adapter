"""
Bot Service
Handles Discord bot state and lifecycle management
"""

import logging
import os
import asyncio
from typing import Optional, Dict

logger = logging.getLogger("lily-discord-adapter")

class BotService:
    """Service for managing Discord bot state"""
    
    def __init__(self):
        self.bot = None
        self.bot_enabled = True
        self.bot_startup_attempted = False
        self.bot_loop = None  # Store reference to bot's event loop
        self.lily_core_available = False
        self.lily_core_http_url = None
        self.lily_core_ws_url = None
    
    def set_bot_references(self, bot, enabled, startup_attempted, loop=None):
        """Set global references to the bot and its state"""
        self.bot = bot
        self.bot_enabled = enabled
        self.bot_startup_attempted = startup_attempted
        self.bot_loop = loop
    
    def set_lily_core_status(self, available: bool, http_url: Optional[str] = None, ws_url: Optional[str] = None):
        """Set Lily-Core availability status and URLs"""
        self.lily_core_available = available
        self.lily_core_http_url = http_url
        self.lily_core_ws_url = ws_url
        
    async def enable_bot(self) -> dict:
        """Enable the Discord bot"""
        bot_token = os.getenv("DISCORD_BOT_TOKEN")
        
        if not bot_token:
            return {"success": False, "message": "DISCORD_BOT_TOKEN not configured"}
        
        if self.bot_enabled:
            return {"success": True, "message": "Bot is already enabled"}
        
        self.bot_enabled = True
        self.bot_startup_attempted = True
        logger.info("Bot enabled via API")
        
        # Bot startup is handled by main.py loop checking bot_enabled
        
        return {"success": True, "message": "Bot enabled successfully"}
    
    async def disable_bot(self) -> dict:
        """Disable the Discord bot"""
        if not self.bot_enabled:
            return {"success": True, "message": "Bot is already disabled"}
        
        self.bot_enabled = False
        logger.info("Bot disabled via API - shutting down bot")
        
        # Close the bot gracefully
        if self.bot and not self.bot.is_closed():
            try:
                # Schedule bot close in bot's event loop
                if self.bot_loop and self.bot_loop.is_running():
                    asyncio.run_coroutine_threadsafe(self.bot.close(), self.bot_loop)
                    logger.info("Bot close scheduled")
                else:
                    await self.bot.close()
                    logger.info("Bot closed directly")
            except Exception as e:
                logger.error(f"Error closing bot: {e}")
        
        return {"success": True, "message": "Bot disabled and closed successfully"}
    
    def get_status(self) -> dict:
        """Get the current bot status"""
        bot_token = os.getenv("DISCORD_BOT_TOKEN")
        
        return {
            "success": True,
            "bot_enabled": self.bot_enabled,
            "bot_running": not self.bot.is_closed() if self.bot else False,
            "bot_ready": self.bot.is_ready() if self.bot else False,
            "bot_startup_attempted": self.bot_startup_attempted,
            "discord_configured": bool(bot_token),
            "lily_core_available": self.lily_core_available,
            "lily_core_http_url": self.lily_core_http_url,
            "lily_core_ws_url": self.lily_core_ws_url
        }
    
    def get_health_info(self, concurrency_manager) -> dict:
        """Get health check information"""
        stats = concurrency_manager.stats if concurrency_manager else {}
        
        return {
            "bot_enabled": self.bot_enabled,
            "bot_startup_attempted": self.bot_startup_attempted,
            "lily_core_available": self.lily_core_available,
            "concurrency": stats
        }

# Create singleton instance
bot_service = BotService()
