"""
Lily Core HTTP Client
Low-level HTTP client for communicating with Lily-Core API
Handles all HTTP requests and responses - no business logic
"""

import logging
from typing import Optional, Dict, Any
import httpx

logger = logging.getLogger("lily-discord-adapter")


class LilyCoreClient:
    """HTTP client for Lily-Core API - pure communication layer"""
    
    def __init__(self, get_http_url_func):
        """
        Initialize the Lily-Core HTTP client.
        
        Args:
            get_http_url_func: Function that returns the Lily-Core HTTP URL
        """
        self.get_http_url_func = get_http_url_func
        self.http_url = None
        self.http_client = httpx.AsyncClient(timeout=120.0)
    
    async def get_base_url(self, force_refresh: bool = False) -> Optional[str]:
        """Get the Lily-Core base HTTP URL"""
        if force_refresh or not self.http_url:
            self.http_url = self.get_http_url_func()
        return self.http_url
    
    async def send_chat_request(self, message: str, user_id: str, username: str) -> Optional[dict]:
        """
        Send a chat request to Lily-Core.
        
        Args:
            message: The user's message text
            user_id: The user's ID
            username: The user's username
        
        Returns:
            Response data from Lily-Core or None on error
        """
        http_url = await self.get_base_url()
        
        if not http_url:
            logger.error("Lily-Core HTTP URL not found")
            return None
        
        payload = {
            "message": message,
            "user_id": user_id,
            "username": username
        }
        
        logger.info(f"Sending chat request to Lily-Core: {payload}")
        
        try:
            response = await self.http_client.post(
                f"{http_url}/chat",
                json=payload,
                timeout=120.0
            )
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"Received response from Lily-Core: {data}")
                return data
            else:
                logger.error(
                    f"HTTP request failed with status {response.status_code}: {response.text}"
                )
                return None
                
        except httpx.RequestError as e:
            logger.error(f"HTTP request error: {e}")
            self.http_url = None  # Invalidate cache on connection error
            return None
        except Exception as e:
            logger.error(f"Unexpected error in HTTP request: {e}")
            return None
    
    async def close(self):
        """Close the HTTP client"""
        await self.http_client.aclose()
    
    async def health_check(self) -> bool:
        """Check if Lily-Core is available"""
        http_url = await self.get_base_url()
        if not http_url:
            return False
        
        try:
            response = await self.http_client.get(f"{http_url}/health", timeout=10.0)
            if response.status_code == 200:
                return True
            else:
                self.http_url = None  # Invalidate cache
                return False
        except Exception:
            self.http_url = None  # Invalidate cache
            return False
