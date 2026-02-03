"""
Command Controller
Handles Discord bot commands
"""

import logging
from typing import Dict

import discord
from discord.ext import commands

from services.session_service import SessionService
from services.lily_core_service import LilyCoreService

logger = logging.getLogger("lily-discord-adapter")


class CommandController:
    """Controller for handling Discord bot commands"""
    
    def __init__(self, bot: commands.Bot, session_service: SessionService, lily_core_service: LilyCoreService):
        """
        Initialize the command controller.
        
        Args:
            bot: Discord bot instance
            session_service: Session service for managing user sessions
            lily_core_service: Service for communicating with Lily-Core
        """
        self.bot = bot
        self.session_service = session_service
        self.lily_core_service = lily_core_service
        self._user_sessions = {}  # Track channel for responses
        
        # Register commands
        self._register_commands()
    
    def _register_commands(self):
        """Register all bot commands"""
        @self.bot.command(name="ping")
        async def ping(ctx):
            await self.ping(ctx)
        
        @self.bot.command(name="lily")
        async def lily_chat(ctx, *, message: str = ""):
            await self.lily_chat(ctx, message)
        
        @self.bot.command(name="join")
        async def join_voice(ctx):
            await self.join_voice(ctx)
        
        @self.bot.command(name="leave")
        async def leave_voice(ctx):
            await self.leave_voice(ctx)
        
        @self.bot.event
        async def on_command_error(ctx, error):
            await self.on_command_error(ctx, error)
    
    async def ping(self, ctx):
        """Check if the bot is alive"""
        await ctx.send("Pong! Lily-Discord-Adapter is alive.")
    
    async def lily_chat(self, ctx, message: str):
        """Send a message to Lily-Core"""
        if not message:
            await ctx.send("Please provide a message. Usage: `!lily <message>`")
            return
        
        user_id = str(ctx.author.id)
        username = ctx.author.name
        
        # Store channel for response
        self._user_sessions[user_id] = ctx.channel
        self.session_service.create_session(user_id, username, ctx.channel)
        
        # Send message to Lily-Core
        message_data = self.lily_core_service.create_chat_message(user_id, username, message)
        await self.lily_core_service.send_message(message_data)
        
        await ctx.send(f"Sent to Lily: {message}")
        logger.info(f"User {username} ({user_id}): !lily {message}")
    
    async def join_voice(self, ctx):
        """Join the user's voice channel"""
        if ctx.author.voice:
            channel = ctx.author.voice.channel
            await channel.connect()
            await ctx.send(f"Joined voice channel: {channel.name}")
        else:
            await ctx.send("You are not in a voice channel.")
    
    async def leave_voice(self, ctx):
        """Leave the current voice channel"""
        if ctx.voice_client:
            await ctx.voice_client.disconnect()
            await ctx.send("Left voice channel")
        else:
            await ctx.send("I'm not in a voice channel.")
    
    async def on_command_error(self, ctx, error):
        """Handle command errors"""
        logger.error(f"Command error: {error}")
        await ctx.send(f"An error occurred: {error}")
    
    def get_channel_for_user(self, user_id: str):
        """Get the channel for a user's session"""
        return self._user_sessions.get(user_id)
