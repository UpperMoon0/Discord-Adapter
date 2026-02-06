"""
Command Controller
Handles Discord bot commands
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from services.session_service import SessionService
from services.lily_core_service import LilyCoreService
from services.music_service import MusicService

logger = logging.getLogger("lily-discord-adapter")


class CommandController:
    """Controller for handling Discord bot commands"""
    
    def __init__(self, bot: commands.Bot, session_service: SessionService, lily_core_service: LilyCoreService, music_service: MusicService):
        """
        Initialize the command controller.
        
        Args:
            bot: Discord bot instance
            session_service: Session service for managing user sessions
            lily_core_service: Service for communicating with Lily-Core
            music_service: Service for handling music playback
        """
        self.bot = bot
        self.session_service = session_service
        self.lily_core_service = lily_core_service
        self.music_service = music_service
        self._user_sessions = {}  # Track channel for responses

        self._register_commands()
    
    def get_channel_for_user(self, user_id: str):
        """Get the channel for a user's session"""
        return self._user_sessions.get(user_id)

    def _register_commands(self):
        """Register application commands"""
        
        @self.bot.tree.command(name="join", description="Joins your voice channel")
        async def join(interaction: discord.Interaction):
            # We need to create a context-like object or modify MusicService to accept interaction
            # For now, let's adapt interaction to context for simplicity or update MusicService.
            # However, MusicService is written for commands.Context.
            # It's better to get the context from the interaction.
            ctx = await self.bot.get_context(interaction)
            # Since get_context on interaction returns a Context that might not have all attributes exactly as a text command,
            # but usually sufficient. However, for app_commands, we should ideally use the interaction directly.
            # But to reuse the service logic which takes `ctx`:
            # We can construct a mock context or update service.
            # Updating service is cleaner but `commands.Context` is convenient for `ctx.send`.
            # Let's see if we can just pass the interaction with a wrapper or update the service later.
            # Actually, `Context` is from `ext.commands`. Slash commands use `Interaction`.
            # Let's patch MusicService to support Interaction or Context, or convert here.
            
            # The simplest way is to fetch the context from the interaction
            ctx = await self.bot.get_context(interaction)
            if await self.music_service.join_channel(ctx):
                 await interaction.response.send_message("Joined voice channel!", ephemeral=True)
            else:
                 if not interaction.response.is_done():
                    await interaction.response.send_message("Failed to join voice channel.", ephemeral=True)

        @self.bot.tree.command(name="play", description="Plays a song from YouTube")
        @app_commands.describe(url="The YouTube URL to play")
        async def play(interaction: discord.Interaction, url: str):
            await interaction.response.send_message(f"Processing request for: {url}...", ephemeral=True)
            ctx = await self.bot.get_context(interaction)
            await self.music_service.add_to_queue(ctx, url)

        @self.bot.tree.command(name="skip", description="Skips the current song")
        async def skip(interaction: discord.Interaction):
            await interaction.response.send_message("Skipping song...", ephemeral=True)
            ctx = await self.bot.get_context(interaction)
            await self.music_service.skip(ctx)

