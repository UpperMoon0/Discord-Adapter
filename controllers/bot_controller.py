"""
Bot Controller
Handles Discord bot control APIs
"""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from services.bot_service import bot_service

logger = logging.getLogger("lily-discord-adapter")

# APIRouter for bot control endpoints
bot_router = APIRouter(
    prefix="/api/bot",
    tags=["Bot Control"]
)


# Request models
class SendMessageRequest(BaseModel):
    """Request model for sending a message to a channel"""
    channel_id: int = Field(..., description="Discord channel ID to send message to")
    message: str = Field(..., min_length=1, max_length=2000, description="Message content to send")


# Register API endpoints
@bot_router.post("/enable")
async def enable_bot():
    """Enable the Discord bot"""
    return await bot_service.enable_bot()


@bot_router.post("/disable")
async def disable_bot():
    """Disable the Discord bot"""
    return await bot_service.disable_bot()


@bot_router.get("/status")
async def get_bot_status():
    """Get the current bot status"""
    return bot_service.get_status()


@bot_router.post("/send-message")
async def send_message(request: SendMessageRequest):
    """
    Send a message to a Discord channel as the bot.
    
    Requires the bot to be running and have access to the specified channel.
    """
    result = await bot_service.send_message_to_channel(request.channel_id, request.message)
    
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message"))
    
    return result


@bot_router.get("/channels")
async def get_channels(guild_id: Optional[int] = None):
    """
    Get list of available text channels.
    
    Args:
        guild_id: Optional guild ID to filter channels by server
    """
    result = await bot_service.get_channels(guild_id)
    
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message"))
    
    return result


@bot_router.get("/guilds")
async def get_guilds():
    """Get list of guilds (servers) the bot is in"""
    result = await bot_service.get_guilds()
    
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message"))
    
    return result
