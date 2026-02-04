"""
Lily Core Service
Service layer for Lily-Core integration - handles business logic
Uses LilyCoreClient for HTTP communication
"""

import logging
from datetime import datetime
from typing import Optional, Dict, Any

from services.lily_core_client import LilyCoreClient

logger = logging.getLogger("lily-discord-adapter")


class LilyCoreService:
    """Service for Lily-Core integration - business logic layer"""
    
    def __init__(self, get_http_url_func):
        """
        Initialize the Lily-Core service.
        
        Args:
            get_http_url_func: Function that returns the Lily-Core HTTP URL
        """
        self._client = LilyCoreClient(get_http_url_func)
    
    async def send_chat_message(
        self, 
        user_id: str, 
        username: str, 
        text: str, 
        attachments: list = None
    ) -> Optional[str]:
        """
        Send a chat message to Lily-Core and get the response.
        
        Args:
            user_id: The user's ID
            username: The user's username
            text: The message text
            attachments: Optional list of attachments
        
        Returns:
            The response text from Lily-Core, or None on error
        """
        # Create the message payload
        message = self._create_chat_message(user_id, username, text, attachments)
        
        # Send via client
        result = await self._client.send_chat_request(
            message=message.get("text", ""),
            user_id=user_id,
            username=username
        )
        
        if result and result.get("response"):
            return result.get("response")
        
        return None
    
    async def is_available(self) -> bool:
        """Check if Lily-Core is available"""
        return await self._client.health_check()
    
    async def get_http_url(self) -> Optional[str]:
        """Get the Lily-Core HTTP URL"""
        return await self._client.get_base_url()

    async def close(self):
        """Close the service and underlying client"""
        await self._client.close()
    
    # ==================== Message Builders (Business Logic) ====================
    
    def _create_chat_message(
        self, 
        user_id: str, 
        username: str, 
        text: str, 
        attachments: list = None
    ) -> Dict[str, Any]:
        """Create a chat message payload"""
        return {
            "type": "message",
            "user_id": user_id,
            "username": username,
            "text": text,
            "attachments": attachments or [],
            "source": "discord",
            "timestamp": datetime.now().isoformat()
        }
    
    def create_session_start_message(
        self, 
        user_id: str, 
        username: str, 
        text: str = ""
    ) -> Dict[str, Any]:
        """Create a session start message payload"""
        return {
            "type": "session_start",
            "user_id": user_id,
            "username": username,
            "text": text,
            "source": "discord",
            "timestamp": datetime.now().isoformat()
        }
    
    def create_session_end_message(
        self, 
        user_id: str, 
        username: str
    ) -> Dict[str, Any]:
        """Create a session end message payload"""
        return {
            "type": "session_end",
            "user_id": user_id,
            "username": username,
            "text": "",
            "source": "discord",
            "timestamp": datetime.now().isoformat()
        }
    
    def create_session_no_active_message(
        self, 
        user_id: str, 
        username: str
    ) -> Dict[str, Any]:
        """Create a session no active message payload"""
        return {
            "type": "session_no_active",
            "user_id": user_id,
            "username": username,
            "text": "",
            "source": "discord",
            "timestamp": datetime.now().isoformat()
        }
