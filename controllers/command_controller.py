"""Discord-native slash commands.

These commands are intentionally separate from the Lily-Core conversational
bridge and do not inherit MCP privileges.
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from services.lily_core_service import LilyCoreService
from services.music_service import MusicService, validate_youtube_url
from services.session_service import SessionService

logger = logging.getLogger("lily-discord-adapter")


class CommandController:
    def __init__(
        self,
        bot: commands.Bot,
        session_service: SessionService,
        lily_core_service: LilyCoreService,
        music_service: MusicService,
    ):
        self.bot = bot
        self.session_service = session_service
        self.lily_core_service = lily_core_service
        self.music_service = music_service
        self._user_sessions = {}
        self._register_commands()

    def get_channel_for_user(self, user_id: str):
        return self._user_sessions.get(user_id)

    def _register_commands(self):
        @self.bot.tree.command(name="join", description="Joins your voice channel")
        @app_commands.guild_only()
        async def join(interaction: discord.Interaction):
            ctx = await self.bot.get_context(interaction)
            if await self.music_service.join_channel(ctx):
                await interaction.response.send_message("Joined voice channel!", ephemeral=True)
            elif not interaction.response.is_done():
                await interaction.response.send_message("Failed to join voice channel.", ephemeral=True)

        @self.bot.tree.command(name="play", description="Plays a YouTube video in voice")
        @app_commands.describe(url="Direct HTTPS YouTube video URL")
        @app_commands.guild_only()
        @app_commands.checks.cooldown(
            2,
            30.0,
            key=lambda interaction: (interaction.guild_id, interaction.user.id),
        )
        async def play(interaction: discord.Interaction, url: str):
            try:
                safe_url = validate_youtube_url(url)
            except ValueError as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)
                return

            await interaction.response.send_message("Adding validated YouTube video...", ephemeral=True)
            ctx = await self.bot.get_context(interaction)
            await self.music_service.add_to_queue(ctx, safe_url)

        @play.error
        async def play_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
            if isinstance(error, app_commands.CommandOnCooldown):
                message = f"Please wait {error.retry_after:.0f}s before adding more videos."
                if interaction.response.is_done():
                    await interaction.followup.send(message, ephemeral=True)
                else:
                    await interaction.response.send_message(message, ephemeral=True)
                return
            logger.warning("Discord /play command rejected: %s", type(error).__name__)
            if not interaction.response.is_done():
                await interaction.response.send_message("Could not process that request.", ephemeral=True)

        @self.bot.tree.command(name="skip", description="Skips the current song")
        @app_commands.guild_only()
        async def skip(interaction: discord.Interaction):
            await interaction.response.send_message("Skipping song...", ephemeral=True)
            ctx = await self.bot.get_context(interaction)
            await self.music_service.skip(ctx)
