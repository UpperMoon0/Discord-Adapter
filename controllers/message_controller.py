"""
Message Controller
Handles Discord message events with concurrency support
"""

import logging
import json
from typing import Dict, Optional

import discord
from discord.ext import commands

from services.session_service import SessionService
from services.lily_core_service import LilyCoreService
from services.concurrency_manager import ConcurrencyManager, UserRateLimiter
from utils.message_utils import send_message

logger = logging.getLogger("lily-discord-adapter")


class MessageController:
    """Controller for handling Discord message events"""
    
    def __init__(self, 
                 bot: commands.Bot, 
                 session_service: SessionService, 
                 lily_core_service: LilyCoreService,
                 concurrency_manager: ConcurrencyManager = None,
                 user_rate_limiter: UserRateLimiter = None):
        """
        Initialize the message controller.
        
        Args:
            bot: Discord bot instance
            session_service: Session service for managing user sessions
            lily_core_service: Service for communicating with Lily-Core
            concurrency_manager: Manager for concurrent message processing
            user_rate_limiter: Per-user rate limiter
        """
        self.bot = bot
        self.session_service = session_service
        self.lily_core_service = lily_core_service
        self.concurrency_manager = concurrency_manager
        self.user_rate_limiter = user_rate_limiter
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
        
        # Check for rate limiting per user
        if self.user_rate_limiter:
            if not await self.user_rate_limiter.acquire(user_id):
                logger.warning(f"Rate limit exceeded for user {username}")
                await channel.send("You're sending messages too fast! Please slow down.")
                return
        
        # Check if this is a wake-up phrase
        if self.session_service.is_wake_phrase(content):
            await self._handle_wake_phrase(user_id, username, content, channel, message)
            return
        
        # Check if this is a goodbye phrase
        if self.session_service.is_goodbye_phrase(content):
            await self._handle_goodbye_phrase(user_id, username, content, channel)
            return
        
        # Only process messages if user has an active session
        if not self.session_service.is_session_active(user_id):
            # User is not in an active session
            if content.lower().startswith("hey"):
                await channel.send("Hi! Say **'Hey Lily'** to wake me up and start a conversation.")
            return
        
        # Process regular message in active session
        await self._handle_chat_message(user_id, username, content, channel, message)
    
    async def _handle_wake_phrase(self, user_id: str, username: str, content: str, channel, message: discord.Message):
        """Handle wake-up phrase - create session and send user's message to Lily-Core"""
        # Create session
        self.session_service.create_session(user_id, username, channel)
        
        # Extract message after wake phrase - treat as regular message
        actual_message = self.session_service.extract_message_after_wake(content)
        
        # Send the actual message to Lily-Core (empty if just wake phrase)
        if self.concurrency_manager:
            message_data = {
                "user_id": user_id,
                "username": username,
                "text": actual_message,
                "channel": channel,
                "attachments": []
            }
            success = await self.concurrency_manager.submit_message(message_data)
            if not success:
                await channel.send("Message queue is full. Please try again.")
                logger.warning(f"Wake message dropped for user {username} due to queue overflow")
        else:
            # Send to Lily-Core as regular chat message
            response_text = await self.lily_core_service.send_chat_message(user_id, username, actual_message)
            if response_text:
                await send_message(channel, response_text, prefix="")
        
        logger.info(f"User {username} woke up Lily")
    
    async def _handle_goodbye_phrase(self, user_id: str, username: str, content: str, channel):
        """Handle goodbye phrase - end session and send goodbye to Lily-Core"""
        # Check if user has an active session
        if self.session_service.is_session_active(user_id):
            # End the session first
            self.session_service.end_session(user_id)
            
            # Send goodbye to Lily-Core like a regular message
            if self.concurrency_manager:
                message_data = {
                    "user_id": user_id,
                    "username": username,
                    "text": content,
                    "channel": channel,
                    "attachments": []
                }
                success = await self.concurrency_manager.submit_message(message_data)
                if not success:
                    logger.warning(f"Goodbye message dropped for user {username} due to queue overflow")
            else:
                # Send to Lily-Core as regular chat message
                response_text = await self.lily_core_service.send_chat_message(user_id, username, content)
                if response_text:
                    await send_message(channel, response_text, prefix="")
            
            logger.info(f"User {username} said goodbye to Lily")
        else:
            # User is not in an active session - no response needed
            logger.info(f"User {username} said goodbye but had no active session")
    
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
        
        # If concurrency manager is available, use it for message processing
        if self.concurrency_manager:
            message_data = {
                "user_id": user_id,
                "username": username,
                "text": content,
                "channel": channel,
                "attachments": attachments
            }
            success = await self.concurrency_manager.submit_message(message_data)
            if not success:
                await channel.send("Message queue is full. Please try again.")
                logger.warning(f"Message dropped for user {username} due to queue overflow")
        else:
            # Direct processing without queue
            response_text = await self.lily_core_service.send_chat_message(user_id, username, content, attachments)
            if response_text:
                await send_message(channel, response_text, prefix="")
        
        logger.info(f"User {username} ({user_id}): {content}")
    
    def get_channel_for_user(self, user_id: str):
        """Get the channel for a user's session"""
        return self._user_sessions.get(user_id)
    
    def update_user_channel(self, user_id: str, channel):
        """Update the channel for a user's session"""
        self._user_sessions[user_id] = channel
