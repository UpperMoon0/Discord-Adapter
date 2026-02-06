"""
Cookies Controller
Handles cookies.txt file management
"""

import logging
import os
import aiofiles
from fastapi import APIRouter, UploadFile, File, HTTPException
from typing import Optional

logger = logging.getLogger("lily-discord-adapter")

cookies_router = APIRouter(
    prefix="/api/cookies",
    tags=["Cookies"]
)

def get_cookies_path() -> str:
    """Get the path to cookies.txt from environment variable"""
    # Default to /app/data/cookies.txt if not set, to ensure it's in the persistent volume
    return os.getenv("YOUTUBE_COOKIES_FILE", "/app/data/cookies.txt")

@cookies_router.get("")
async def get_cookies():
    """Get the content of cookies.txt"""
    file_path = get_cookies_path()
    
    if not os.path.exists(file_path):
        return {"exists": False, "content": None, "path": file_path}
    
    try:
        async with aiofiles.open(file_path, mode='r') as f:
            content = await f.read()
        return {"exists": True, "content": content, "path": file_path}
    except Exception as e:
        logger.error(f"Error reading cookies file: {e}")
        raise HTTPException(status_code=500, detail=f"Error reading file: {str(e)}")

@cookies_router.post("")
async def upload_cookies(file: UploadFile = File(...)):
    """Upload and overwrite cookies.txt"""
    file_path = get_cookies_path()
    
    # Ensure directory exists
    directory = os.path.dirname(file_path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)
    
    try:
        content = await file.read()
        # Write bytes directly
        async with aiofiles.open(file_path, mode='wb') as f:
            await f.write(content)
            
        logger.info(f"Updated cookies file at {file_path}")
        
        # Verify it was written
        file_size = os.path.getsize(file_path)
        
        return {
            "success": True, 
            "message": "Cookies file updated successfully", 
            "path": file_path,
            "size": file_size
        }
    except Exception as e:
        logger.error(f"Error writing cookies file: {e}")
        raise HTTPException(status_code=500, detail=f"Error writing file: {str(e)}")
