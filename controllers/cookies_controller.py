"""
Cookies Controller
Handles cookies.txt file management
"""

import logging
from fastapi import APIRouter, UploadFile, File, HTTPException, WebSocket
from fastapi.responses import FileResponse
from services.cookies_service import CookiesService

logger = logging.getLogger("lily-discord-adapter")

cookies_router = APIRouter(
    prefix="/api/cookies",
    tags=["Cookies"]
)

ws_cookies_router = APIRouter(
    prefix="/ws/cookies",
    tags=["Cookies WebSocket"]
)

# Instantiate service
cookies_service = CookiesService()

@ws_cookies_router.websocket("/")
async def websocket_cookies(websocket: WebSocket):
    await websocket.accept()
    try:
        data = await websocket.receive_text()
        if data == "get":
            async for chunk in cookies_service.stream_cookies_content():
                await websocket.send_text(chunk)
            await websocket.close()
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await websocket.close(code=1011)
        except:
            pass

@cookies_router.get("")
async def get_cookies(include_content: bool = False, offset: int = 0, limit: int = 50000):
    """Get the content of cookies.txt"""
    try:
        if include_content:
            content, file_path, total_size = await cookies_service.get_cookies_content(offset, limit)
            
            return {
                "exists": content is not None,
                "content": content,
                "path": file_path,
                "total_size": total_size,
                "offset": offset,
                "limit": limit
            }
        else:
            exists, file_path = cookies_service.get_cookies_status()
            return {
                "exists": exists,
                "content": None,
                "path": file_path
            }
    except Exception as e:
        logger.error(f"Error reading cookies file: {e}")
        raise HTTPException(status_code=500, detail=f"Error reading file: {str(e)}")

@cookies_router.get("/download")
async def download_cookies():
    """Download cookies.txt"""
    exists, file_path = cookies_service.get_cookies_status()
    if not exists:
        raise HTTPException(status_code=404, detail="Cookies file not found")
    return FileResponse(file_path, media_type="text/plain", filename="cookies.txt")

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
