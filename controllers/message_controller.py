"""
Message Controller
Handles Discord message events
"""

import logging
import json
from typing import Dict

import discord
from discord.ext import commands

from services.session_service import SessionService
from services.lily_core_service import LilyCoreService

logger = logging.getLogger("lily-discord-adapter")


class MessageController:
    """Controller for handling Discord message events"""
    
    def __init__(self, bot: commands.Bot, session_service: SessionService, lily_core_service: LilyCoreService):
        """
        Initialize the message controller.
        
        Args:
            bot: Discord bot instance
            session_service: Session service for managing user sessions
            lily_core_service: Service for communicating with Lily-Core
        """
        self.bot = bot
        self.session_service = session_service
        self.lily_core_service = lily_core_service
        self._user_sessions = {}  # Track channel for responses
        
        # Register event handler
        bot.event(self.on_message)
    
    async def on_message(self, message: discord.Message):
        """Handle incoming Discord messages"""
        # Ignore messages from the bot itself
        if message.author == self.bot.user:
            return
        
        # Process commands
        await self.bot.process_commands(message)
        
        # Handle regular messages (not commands)
        if not message.content.startswith(self.bot.command_prefix):
            await self.handle_user_message(message)
    
    async def handle_user_message(self, message: discord.Message):
        """Process a user message and send to Lily-Core"""
        user_id = str(message.author.id)
        username = message.author.name
        content = message.content.strip()
        channel = message.channel
        
        # Check if this is a wake-up phrase
        if self.session_service.is_wake_phrase(content):
            await self._handle_wake_phrase(user_id, username, content, channel, message)
            return
        
        # Check if this is a goodbye phrase
        if self.session_service.is_goodbye_phrase(content):
            await self._handle_goodbye_phrase(user_id, username, channel)
            return
        
        # Only process messages if user has an active session
        if not self.session_service.is_session_active(user_id):
            # User is not in an active session
            if content.lower().startswith("hey"):
                await channel.send("**Lily:** Hi! Say **'Hey Lily'** to wake me up and start a conversation.")
            return
        
        # Process regular message in active session
        await self._handle_chat_message(user_id, username, content, channel, message)
    
    async def _handle_wake_phrase(self, user_id: str, username: str, content: str, channel, message: discord.Message):
        """Handle wake-up phrase"""
        # Create session
        self.session_service.create_session(user_id, username, channel)
        
        # Extract message after wake phrase
        actual_message = self.session_service.extract_message_after_wake(content)
        
        # Send session_start event to Lily-Core
        session_start_data = self.lily_core_service.create_session_start_message(
            user_id, username, actual_message
        )
        await self.lily_core_service.send_message(session_start_data)
        
        logger.info(f"User {username} woke up Lily")
    
    async def _handle_goodbye_phrase(self, user_id: str, username: str, channel):
        """Handle goodbye phrase"""
        if self.session_service.is_session_active(user_id):
            # Send session_end event to Lily-Core
            session_end_data = self.lily_core_service.create_session_end_message(user_id, username)
            await self.lily_core_service.send_message(session_end_data)
            
            # End the session
            self.session_service.end_session(user_id)
            logger.info(f"User {username} said goodbye to Lily")
        else:
            # User is not in an active session - ask Lily-Core for a response
            no_session_data = self.lily_core_service.create_session_no_active_message(user_id, username)
            await self.lily_core_service.send_message(no_session_data)
    
    async def _handle_chat_message(self, user_id: str, username: str, content: str, channel, message: discord.Message):
        """Handle regular chat message"""
        # Update channel for response
        self._user_sessions[user_id] = channel
        
        # Handle voice messages if any
        attachments = []
        for attachment in message.attachments:
            if attachment.filename.endswith(('.wav', '.mp3', '.m4a', '.flac', '.ogg')):
                attachments.append({
                    "type": "audio",
                    "url": attachment.url,
                    "filename": attachment.filename
                })
        
        # Send message to Lily-Core
        message_data = self.lily_core_service.create_chat_message(user_id, username, content, attachments)
        await self.lily_core_service.send_message(message_data)
        
        logger.info(f"User {username} ({user_id}): {content}")
    
    def get_channel_for_user(self, user_id: str):
        """Get the channel for a user's session"""
        return self._user_sessions.get(user_id)
    
    def update_user_channel(self, user_id: str, channel):
        """Update the channel for a user's session"""
        self._user_sessions[user_id] = channel
