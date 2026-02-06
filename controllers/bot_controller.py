"""
Bot Controller
Handles Discord bot control APIs
"""

import logging
from fastapi import APIRouter
from services.bot_service import bot_service

logger = logging.getLogger("lily-discord-adapter")

# APIRouter for bot control endpoints
bot_router = APIRouter(
    prefix="/api/bot",
    tags=["Bot Control"]
)

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
