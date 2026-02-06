"""
Cookies Service
Handles file operations for cookies.txt
"""

import os
import logging
import aiofiles

logger = logging.getLogger("lily-discord-adapter")

class CookiesService:
    def __init__(self):
        # Always use the persistent data volume path
        self.file_path = "/app/data/cookies.txt"

    def get_file_path(self) -> str:
        """Get the configured file path"""
        return self.file_path

    async def get_cookies_content(self, offset: int = 0, limit: int = None):
        """Read cookies file content"""
        if not os.path.exists(self.file_path):
            return None, self.file_path, 0
        
        try:
            async with aiofiles.open(self.file_path, mode='r') as f:
                content = await f.read()
            
            total_size = len(content)
            
            if limit is not None:
                content = content[offset:offset+limit]
                
            return content, self.file_path, total_size
        except Exception as e:
            logger.error(f"Error reading cookies file: {e}")
            raise e

    def get_cookies_status(self):
        """Check if cookies file exists"""
        return os.path.exists(self.file_path), self.file_path

    async def stream_cookies_content(self, chunk_size: int = 8192):
        """Yield chunks of cookies file content"""
        if not os.path.exists(self.file_path):
            return
            
        try:
            async with aiofiles.open(self.file_path, mode='r') as f:
                while True:
                    chunk = await f.read(chunk_size)
                    if not chunk:
                        break
                    yield chunk
        except Exception as e:
            logger.error(f"Error streaming cookies file: {e}")
            raise e

    async def save_cookies(self, content_bytes: bytes):
        """Save content to cookies file"""
        directory = os.path.dirname(self.file_path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)
            
        try:
            async with aiofiles.open(self.file_path, mode='wb') as f:
                await f.write(content_bytes)
            
            return self.file_path, os.path.getsize(self.file_path)
        except Exception as e:
            logger.error(f"Error writing cookies file: {e}")
            raise e
