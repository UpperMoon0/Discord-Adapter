"""
Lily-Discord-Adapter
Discord bot adapter for Lily-Core
Handles Discord messages and communicates with Lily-Core via WebSocket
"""

import os
import sys
import asyncio
import logging
import json
from datetime import datetime

import discord
from discord.ext import commands
import websockets
import requests

sys.path.insert(0, '/app/Lily-Discord-Adapter')

from utils.service_discovery import ServiceDiscovery

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("lily-discord-adapter")

# Bot configuration
INTENTS = discord.Intents.default()
INTENTS.message_content = True
INTENTS.voice_states = True

BOT = commands.Bot(
    command_prefix='!',
    intents=INTENTS,
    description='Lily Discord Adapter - Connects Discord to Lily-Core'
)

# Service Discovery
sd = None

# Lily-Core availability tracking
lily_client = None
lily_core_available = False

# User sessions tracking
user_sessions = {}

class LilyCoreClient:
    """Client to communicate with Lily-Core via WebSocket"""
    
    def __init__(self, get_url_func):
        """
        Initialize the Lily-Core client.
        
        Args:
            get_url_func: Function that returns the Lily-Core WebSocket URL
        """
        self.get_url_func = get_url_func
        self.uri = None
        self.websocket = None
        self.loop = None
        self.reconnect_delay = 5
    
    def update_uri(self):
        """Update the URI from Consul discovery"""
        self.uri = self.get_url_func()
        if self.uri:
            logger.info(f"Discovered Lily-Core at {self.uri}")
        return self.uri
    
    async def connect(self):
        """Establish WebSocket connection to Lily-Core"""
        global lily_core_available
        
        while True:
            try:
                # Update URI from Consul
                if not self.uri:
                    self.update_uri()
                
                if not self.uri:
                    logger.warning("Lily-Core not found in Consul. Chat features will be disabled.")
                    lily_core_available = False
                    # Retry less frequently when Lily-Core is not available
                    await asyncio.sleep(30)
                    continue
                    
                self.websocket = await websockets.connect(self.uri)
                logger.info(f"Connected to Lily-Core at {self.uri}")
                lily_core_available = True
                
                # Start listening for messages
                asyncio.create_task(self.listen())
                return True
            except Exception as e:
                logger.error(f"Failed to connect to Lily-Core: {e}")
                self.uri = None  # Force re-discovery on next attempt
                lily_core_available = False
                logger.info(f"Reconnecting in {self.reconnect_delay} seconds...")
                await asyncio.sleep(self.reconnect_delay)
    
    async def listen(self):
        """Listen for messages from Lily-Core"""
        global lily_core_available
        
        try:
            async for message in self.websocket:
                await self.handle_message(message)
        except websockets.ConnectionClosed:
            logger.warning("Lily-Core WebSocket connection closed")
        except Exception as e:
            logger.error(f"Error listening to Lily-Core: {e}")
        finally:
            lily_core_available = False
    
    async def handle_message(self, message: str):
        """Handle incoming messages from Lily-Core"""
        try:
            data = json.loads(message)
            logger.info(f"Received from Lily-Core: {data}")
            
            # Extract relevant information
            response_type = data.get("type", "")
            
            if response_type == "response":
                # Handle response to user query
                user_id = data.get("user_id")
                text = data.get("text", "")
                
                if user_id and user_id in user_sessions:
                    channel = user_sessions[user_id].get("channel")
                    if channel:
                        await channel.send(f"**Lily:** {text}")
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON from Lily-Core: {message}")
    
    async def send_message(self, message: dict):
        """Send message to Lily-Core"""
        if self.websocket:
            try:
                await self.websocket.send(json.dumps(message))
                logger.info(f"Sent to Lily-Core: {message}")
            except Exception as e:
                logger.error(f"Error sending to Lily-Core: {e}")
    
    async def close(self):
        """Close WebSocket connection"""
        if self.websocket:
            await self.websocket.close()


# Lily-Core client - will be initialized after sd is set
lily_client = None
lily_core_available = False  # Track if Lily-Core is available

def get_lily_core_url():
    """Get Lily-Core WebSocket URL from Consul.
    
    Returns None if Consul is unavailable or Lily-Core is not registered.
    Consul is the single source of truth - no fallback to environment variables.
    """
    if sd:
        return sd.get_lily_core_ws_url()
    return None


@BOT.event
async def on_ready():
    """Bot is ready and connected to Discord"""
    global lily_client
    
    logger.info(f"Bot logged in as {BOT.user.name} ({BOT.user.id})")
    
    # Register with Consul for service discovery
    global sd
    port = int(os.getenv("PORT", "8004"))
    sd = ServiceDiscovery(service_name="lily-discord-adapter", port=port, tags=["discord", "adapter"])
    sd.start()
    
    # Initialize Lily-Core client with Consul discovery
    lily_client = LilyCoreClient(get_lily_core_url)
    
    # Connect to Lily-Core WebSocket
    await lily_client.connect()
    
    logger.info("Lily-Discord-Adapter is ready!")


@BOT.event
async def on_message(message: discord.Message):
    """Handle incoming Discord messages"""
    # Ignore messages from the bot itself
    if message.author == BOT.user:
        return
    
    # Process commands
    await BOT.process_commands(message)
    
    # Handle regular messages (not commands)
    if not message.content.startswith(BOT.command_prefix):
        await handle_user_message(message)


async def handle_user_message(message: discord.Message):
    """Process a user message and send to Lily-Core"""
    global lily_core_available
    
    # Check if Lily-Core is available
    if not lily_core_available:
        await message.channel.send("⚠️ Lily-Core is currently unavailable. Please try again later.")
        return
    
    user_id = str(message.author.id)
    username = message.author.name
    content = message.content
    channel = message.channel
    
    # Store channel for response
    user_sessions[user_id] = {
        "username": username,
        "channel": channel,
        "started_at": datetime.now()
    }
    
    # Handle voice messages if any
    attachments = []
    for attachment in message.attachments:
        if attachment.filename.endswith(('.wav', '.mp3', '.m4a', '.flac', '.ogg')):
            attachments.append({
                "type": "audio",
                "url": attachment.url,
                "filename": attachment.filename
            })
    
    # Send message to Lily-Core
    message_data = {
        "type": "message",
        "user_id": user_id,
        "username": username,
        "text": content,
        "attachments": attachments,
        "source": "discord",
        "timestamp": datetime.now().isoformat()
    }
    
    await lily_client.send_message(message_data)
    
    # Log the message
    logger.info(f"User {username} ({user_id}): {content}")


@BOT.command(name="ping")
async def ping(ctx):
    """Check if the bot is alive"""
    await ctx.send("Pong! Lily-Discord-Adapter is alive.")


@BOT.command(name="lily")
async def lily_chat(ctx, *, message: str = ""):
    """Send a message to Lily-Core"""
    global lily_core_available
    
    if not message:
        await ctx.send("Please provide a message. Usage: `!lily <message>`")
        return
    
    # Check if Lily-Core is available
    if not lily_core_available:
        await ctx.send("⚠️ Lily-Core is currently unavailable. Please try again later.")
        return
    
    user_id = str(ctx.author.id)
    user_sessions[user_id] = {
        "username": ctx.author.name,
        "channel": ctx.channel,
        "started_at": datetime.now()
    }
    
    message_data = {
        "type": "message",
        "user_id": user_id,
        "username": ctx.author.name,
        "text": message,
        "source": "discord",
        "timestamp": datetime.now().isoformat()
    }
    
    await lily_client.send_message(message_data)
    await ctx.send(f"Sent to Lily: {message}")


@BOT.command(name="join")
async def join_voice(ctx):
    """Join the user's voice channel"""
    if ctx.author.voice:
        channel = ctx.author.voice.channel
        await channel.connect()
        await ctx.send(f"Joined voice channel: {channel.name}")
    else:
        await ctx.send("You are not in a voice channel.")


@BOT.command(name="leave")
async def leave_voice(ctx):
    """Leave the current voice channel"""
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.send("Left voice channel")
    else:
        await ctx.send("I'm not in a voice channel.")


@BOT.event
async def on_voice_state_update(member, before, after):
    """Handle voice state updates (for voice message processing)"""
    # This can be extended for voice message handling
    pass


@BOT.event
async def on_command_error(ctx, error):
    """Handle command errors"""
    logger.error(f"Command error: {error}")
    await ctx.send(f"An error occurred: {error}")


# Health check endpoint for Docker
from fastapi import FastAPI
import uvicorn

app = FastAPI(
    title="Lily-Discord-Adapter Health",
    description="Health check endpoint for the Discord adapter"
)

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "lily-discord-adapter",
        "bot_ready": BOT.is_ready(),
        "lily_core_available": lily_core_available,
        "discord_enabled": bool(os.getenv("DISCORD_BOT_TOKEN"))
    }

@app.get("/ready")
async def readiness_check():
    """Readiness check endpoint - HTTP server is always ready"""
    return {
        "status": "ready",
        "bot_ready": BOT.is_ready(),
        "lily_core_available": lily_core_available
    }


def run_health_server():
    """Run the health check server on a separate thread"""
    port = int(os.getenv("PORT", "8004"))
    uvicorn.run(app, host="0.0.0.0", port=port)


def main():
    """Main entry point"""
    port = int(os.getenv("PORT", "8004"))
    bot_token = os.getenv("DISCORD_BOT_TOKEN")
    
    # Start health check server in a separate thread
    import threading
    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()
    
    if not bot_token:
        logger.warning("DISCORD_BOT_TOKEN not set - Discord bot features disabled")
        logger.info("Lily-Discord-Adapter running in HTTP mode (health endpoints active)")
        # Keep the HTTP server running - Discord features are disabled
        import time
        while True:
            time.sleep(3600)
    
    # Run the Discord bot
    logger.info("Starting Lily-Discord-Adapter...")
    BOT.run(bot_token)


if __name__ == "__main__":
    main()
