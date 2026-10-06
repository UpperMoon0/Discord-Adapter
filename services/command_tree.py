"""Guild-scoped publication and execution of every bot application command."""

import asyncio
import logging

import discord
from discord import app_commands

from services.access_policy_service import access_policy_service

logger = logging.getLogger("lily-discord-adapter")


class WhitelistedCommandTree(app_commands.CommandTree):
    """Keep global commands as local templates; never publish them globally."""

    def __init__(self, client, **kwargs):
        super().__init__(client, **kwargs)
        self._sync_lock = asyncio.Lock()
        self._published = {}
        self._globals_cleared = False

    def guild_allowed(self, guild_id):
        return guild_id is not None and access_policy_service.is_guild_commands_allowed(guild_id)

    async def interaction_check(self, interaction):
        if self.guild_allowed(interaction.guild_id):
            return True
        if not interaction.response.is_done():
            if interaction.type == discord.InteractionType.autocomplete:
                await interaction.response.autocomplete([])
            else:
                await interaction.response.send_message(
                    "This server has not been approved to use bot commands.", ephemeral=True
                )
        return False

    async def prefix_check(self, ctx):
        return self.guild_allowed(ctx.guild.id if ctx.guild else None)

    def _commands_for_guild(self, guild):
        # Guild-specific addon definitions take precedence over global templates.
        commands = {}
        for command in self.get_commands() + self.get_commands(guild=guild):
            command_type = getattr(command, "type", discord.AppCommandType.chat_input)
            commands[(command_type.value, command.name)] = command
        return list(commands.values())

    async def _payload(self, guild):
        commands = self._commands_for_guild(guild) if self.guild_allowed(guild.id) else []
        if self.translator:
            return [await command.get_translated_payload(self, self.translator) for command in commands]
        return [command.to_dict(self) for command in commands]

    async def sync(self, *, guild=None):
        """Even addon calls to sync cannot publish outside the active policy."""
        if self.client.application_id is None:
            raise app_commands.MissingApplicationID
        async with self._sync_lock:
            if guild is None:
                data = await self._http.bulk_upsert_global_commands(
                    self.client.application_id, payload=[]
                )
                self._globals_cleared = True
            else:
                payload = await self._payload(guild)
                data = await self._http.bulk_upsert_guild_commands(
                    self.client.application_id, guild.id, payload=payload
                )
                self._published[guild.id] = payload
        return [app_commands.AppCommand(data=item, state=self._state) for item in data]

    async def reconcile(self):
        if not self._globals_cleared:
            try:
                await self.sync()
            except Exception:
                # Global cleanup must not block guild cleanup or publication.
                # sync marks success only after Discord accepts the request.
                logger.exception("Failed to clear global commands; will retry")
        # Visit every connected guild, including denied ones, to delete old registrations.
        guilds = sorted(self.client.guilds, key=lambda guild: self.guild_allowed(guild.id))
        for guild in guilds:
            try:
                payload = await self._payload(guild)
                if self._published.get(guild.id) != payload:
                    await self.sync(guild=guild)
            except Exception:
                # Leave the previous fingerprint intact so the next pass retries.
                logger.exception("Failed to reconcile commands for guild %s", guild.id)
