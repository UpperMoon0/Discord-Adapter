"""
Lily Core Service
Handles communication with Lily-Core via WebSocket
"""

import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any
import websockets

logger = logging.getLogger("lily-discord-adapter")


class LilyCoreService:
    """Service for communicating with Lily-Core"""
    
    def __init__(self, get_url_func):
        """
        Initialize the Lily-Core service.
        
        Args:
            get_url_func: Function that returns the Lily-Core WebSocket URL
        """
        self.get_url_func = get_url_func
        self.uri = None
        self.websocket = None
        self.reconnect_delay = 5
    
    async def connect(self) -> bool:
        """Establish WebSocket connection to Lily-Core"""
        while True:
            try:
                # Update URI from Consul
                if not self.uri:
                    self.uri = self.get_url_func()
                
                if not self.uri:
                    logger.warning("Lily-Core not found in Consul. Chat features will be disabled.")
                    await asyncio.sleep(30)
                    continue
                    
                self.websocket = await websockets.connect(self.uri)
                logger.info(f"Connected to Lily-Core at {self.uri}")
                return True
            except Exception as e:
                logger.error(f"Failed to connect to Lily-Core: {e}")
                self.uri = None
                logger.info(f"Reconnecting in {self.reconnect_delay} seconds...")
                await asyncio.sleep(self.reconnect_delay)
    
    async def listen(self, message_handler):
        """Listen for messages from Lily-Core"""
        try:
            async for message in self.websocket:
                await message_handler(message)
        except websockets.ConnectionClosed:
            logger.warning("Lily-Core WebSocket connection closed")
        except Exception as e:
            logger.error(f"Error listening to Lily-Core: {e}")
    
    async def send_message(self, message: dict) -> bool:
        """Send message to Lily-Core"""
        if self.websocket:
            try:
                await self.websocket.send(json.dumps(message))
                logger.info(f"Sent to Lily-Core: {message}")
                return True
            except Exception as e:
                logger.error(f"Error sending to Lily-Core: {e}")
        return False
    
    def create_session_start_message(self, user_id: str, username: str, text: str = "") -> Dict[str, Any]:
        """Create a session start message"""
        return {
            "type": "session_start",
            "user_id": user_id,
            "username": username,
            "text": text,
            "source": "discord",
            "timestamp": datetime.now().isoformat()
        }
    
    def create_session_end_message(self, user_id: str, username: str) -> Dict[str, Any]:
        """Create a session end message"""
        return {
            "type": "session_end",
            "user_id": user_id,
            "username": username,
            "text": "",
            "source": "discord",
            "timestamp": datetime.now().isoformat()
        }
    
    def create_session_no_active_message(self, user_id: str, username: str) -> Dict[str, Any]:
        """Create a session no active message"""
        return {
            "type": "session_no_active",
            "user_id": user_id,
            "username": username,
            "text": "",
            "source": "discord",
            "timestamp": datetime.now().isoformat()
        }
    
    def create_chat_message(self, user_id: str, username: str, text: str, attachments: list = None) -> Dict[str, Any]:
        """Create a chat message"""
        return {
            "type": "message",
            "user_id": user_id,
            "username": username,
            "text": text,
            "attachments": attachments or [],
            "source": "discord",
            "timestamp": datetime.now().isoformat()
        }
    
    async def close(self):
        """Close WebSocket connection"""
        if self.websocket:
            await self.websocket.close()


# Import asyncio at module level
import asyncio
