"""
Cookies Controller
Handles cookies.txt file management
"""

import logging
from fastapi import APIRouter, UploadFile, File, HTTPException
from services.cookies_service import CookiesService

logger = logging.getLogger("lily-discord-adapter")

cookies_router = APIRouter(
    prefix="/api/cookies",
    tags=["Cookies"]
)

# Instantiate service
cookies_service = CookiesService()

@cookies_router.get("")
async def get_cookies():
    """Get the content of cookies.txt"""
    try:
        content, file_path = await cookies_service.get_cookies_content()
        return {
            "exists": content is not None, 
            "content": content, 
            "path": file_path
        }
    except Exception as e:
        logger.error(f"Error reading cookies file: {e}")
        raise HTTPException(status_code=500, detail=f"Error reading file: {str(e)}")

@cookies_router.post("")
async def upload_cookies(file: UploadFile = File(...)):
    """Upload and overwrite cookies.txt"""
    try:
        content = await file.read()
        file_path, file_size = await cookies_service.save_cookies(content)
            
        logger.info(f"Updated cookies file at {file_path}")
        
        return {
            "success": True, 
            "message": "Cookies file updated successfully", 
            "path": file_path,
            "size": file_size
        }
    except Exception as e:
        logger.error(f"Error writing cookies file: {e}")
        raise HTTPException(status_code=500, detail=f"Error writing file: {str(e)}")
