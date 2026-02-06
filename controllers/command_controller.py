"""
Command Controller
Handles Discord bot commands
"""

import logging

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
    
    def get_channel_for_user(self, user_id: str):
        """Get the channel for a user's session"""
        return self._user_sessions.get(user_id)
