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
    
    async def send_message_to_channel(self, channel_id: int, message: str) -> dict:
        """
        Send a message to a Discord channel as the bot.
        
        Args:
            channel_id: The Discord channel ID to send the message to
            message: The message content to send
            
        Returns:
            dict with success status and details
        """
        if not self.bot:
            return {"success": False, "message": "Bot not initialized"}
        
        if self.bot.is_closed():
            return {"success": False, "message": "Bot is not running"}
        
        if not self.bot.is_ready():
            return {"success": False, "message": "Bot is not ready"}
        
        try:
            # Get the channel from the bot
            channel = self.bot.get_channel(channel_id)
            
            if channel is None:
                return {"success": False, "message": f"Channel {channel_id} not found"}
            
            # Check if it's a valid text channel
            from discord import TextChannel, Thread
            if not isinstance(channel, (TextChannel, Thread)):
                return {"success": False, "message": f"Channel {channel_id} is not a text channel"}
            
            # Send the message
            sent_message = await channel.send(message)
            
            logger.info(f"Message sent to channel {channel_id} (message ID: {sent_message.id})")
            
            return {
                "success": True,
                "message": "Message sent successfully",
                "channel_id": channel_id,
                "channel_name": channel.name,
                "message_id": sent_message.id,
                "content": message
            }
            
        except Exception as e:
            logger.error(f"Failed to send message to channel {channel_id}: {e}")
            return {"success": False, "message": f"Failed to send message: {str(e)}"}
    
    async def get_channels(self, guild_id: Optional[int] = None) -> dict:
        """
        Get list of available text channels.
        
        Args:
            guild_id: Optional guild ID to filter channels by server
            
        Returns:
            dict with success status and list of channels
        """
        if not self.bot:
            return {"success": False, "message": "Bot not initialized", "channels": []}
        
        if self.bot.is_closed():
            return {"success": False, "message": "Bot is not running", "channels": []}
        
        if not self.bot.is_ready():
            return {"success": False, "message": "Bot is not ready", "channels": []}
        
        try:
            channels = []
            
            for guild in self.bot.guilds:
                # Filter by guild_id if specified
                if guild_id and guild.id != guild_id:
                    continue
                    
                for channel in guild.text_channels:
                    channels.append({
                        "id": channel.id,
                        "name": channel.name,
                        "guild_id": guild.id,
                        "guild_name": guild.name,
                        "category": channel.category.name if channel.category else None,
                        "position": channel.position,
                        "nsfw": channel.nsfw
                    })
            
            return {
                "success": True,
                "channels": channels,
                "count": len(channels)
            }
            
        except Exception as e:
            logger.error(f"Failed to get channels: {e}")
            return {"success": False, "message": f"Failed to get channels: {str(e)}", "channels": []}
    
    async def get_guilds(self) -> dict:
        """
        Get list of guilds (servers) the bot is in.
        
        Returns:
            dict with success status and list of guilds
        """
        if not self.bot:
            return {"success": False, "message": "Bot not initialized", "guilds": []}
        
        if self.bot.is_closed():
            return {"success": False, "message": "Bot is not running", "guilds": []}
        
        if not self.bot.is_ready():
            return {"success": False, "message": "Bot is not ready", "guilds": []}
        
        try:
            guilds = []
            
            for guild in self.bot.guilds:
                guilds.append({
                    "id": guild.id,
                    "name": guild.name,
                    "member_count": guild.member_count,
                    "text_channel_count": len(guild.text_channels),
                    "voice_channel_count": len(guild.voice_channels)
                })
            
            return {
                "success": True,
                "guilds": guilds,
                "count": len(guilds)
            }
            
        except Exception as e:
            logger.error(f"Failed to get guilds: {e}")
            return {"success": False, "message": f"Failed to get guilds: {str(e)}", "guilds": []}

# Create singleton instance
bot_service = BotService()
