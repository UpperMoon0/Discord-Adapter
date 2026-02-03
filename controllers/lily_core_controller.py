"""
Lily Core Controller
Handles messages received from Lily-Core
"""

import json
import logging
import asyncio
from typing import Dict

from services.session_service import SessionService

logger = logging.getLogger("lily-discord-adapter")


class LilyCoreController:
    """Controller for handling messages from Lily-Core"""
    
    def __init__(self, session_service: SessionService):
        """
        Initialize the Lily-Core controller.
        
        Args:
            session_service: Session service for managing user sessions
        """
        self.session_service = session_service
        self._user_sessions = {}  # Track channel for responses
    
    async def handle_message(self, message: str, lily_core_available: bool = None):
        """
        Handle incoming messages from Lily-Core.
        
        Args:
            message: Raw message string from Lily-Core
            lily_core_available: Whether Lily-Core is available (for logging)
        """
        try:
            data = json.loads(message)
            logger.info(f"Received from Lily-Core: {data}")
            
            # Extract relevant information
            response_type = data.get("type", "")
            user_id = data.get("user_id")
            text = data.get("text", "")
            
            if response_type == "response":
                await self._handle_response(user_id, text)
            elif response_type == "session_start":
                await self._handle_session_start(user_id, text)
            elif response_type == "session_end":
                await self._handle_session_end(user_id, text)
            elif response_type == "session_no_active":
                await self._handle_session_no_active(user_id, text)
                
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON from Lily-Core: {message}")
        except Exception as e:
            logger.error(f"Error handling Lily-Core message: {e}")
    
    async def _handle_response(self, user_id: str, text: str):
        """Handle regular chat response"""
        if user_id and user_id in self._user_sessions:
            channel = self._user_sessions[user_id].get("channel")
            if channel:
                await channel.send(f"**Lily:** {text}")
    
    async def _handle_session_start(self, user_id: str, text: str):
        """Handle session start response (greeting from LLM)"""
        if user_id and user_id in self._user_sessions:
            channel = self._user_sessions[user_id].get("channel")
            if channel:
                # Ensure session is active
                session = self.session_service.get_session(user_id)
                if session:
                    session.start_session()
                await channel.send(f"**Lily:** {text}")
    
    async def _handle_session_end(self, user_id: str, text: str):
        """Handle session end response (farewell from LLM)"""
        if user_id and user_id in self._user_sessions:
            channel = self._user_sessions[user_id].get("channel")
            if channel:
                # End active session
                self.session_service.end_session(user_id)
                await channel.send(f"**Lily:** {text}")
    
    async def _handle_session_no_active(self, user_id: str, text: str):
        """Handle when user says goodbye but no active session"""
        if user_id and user_id in self._user_sessions:
            channel = self._user_sessions[user_id].get("channel")
            if channel:
                await channel.send(f"**Lily:** {text}")
    
    def update_user_channel(self, user_id: str, channel):
        """Update the channel for a user's session"""
        self._user_sessions[user_id] = {
            "channel": channel,
            "session": self.session_service.get_session(user_id)
        }
    
    def get_channel_for_user(self, user_id: str):
        """Get the channel for a user's session"""
        if user_id in self._user_sessions:
            return self._user_sessions[user_id].get("channel")
        return None
