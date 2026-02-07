import asyncio
import logging
import os
from collections import deque
from typing import Dict, Optional
import discord
from discord.ext import commands
import json
import subprocess
import sys

logger = logging.getLogger("lily-discord-adapter")

# FFmpeg options
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}

from services.bot_service import bot_service

async def run_yt_dlp(url):
    """Run yt-dlp binary with options for streaming"""
    # Path to yt-dlp binary (assumed to be in the project root or accessible)
    # We try to locate it relative to the project root
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    binary_path = os.path.join(base_dir, 'yt-dlp')
    
    if not os.path.exists(binary_path):
        binary_path = 'yt-dlp'
        
    cmd = [sys.executable, binary_path]
    
    # Common options
    cmd.append('--no-playlist')
    cmd.append('--no-check-certificate')
    cmd.append('--quiet')
    cmd.append('--no-warnings')
    cmd.extend(['--default-search', 'auto'])
    cmd.extend(['--source-address', '0.0.0.0'])
    cmd.extend(['--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'])
    
    # Fix for n-token challenges
    cmd.extend(['--js-runtimes', 'node'])
    cmd.extend(['--remote-components', 'ejs:github'])
    
    # Cookies
    cookies_file = '/app/data/cookies.txt'
    local_cookies = os.path.join(base_dir, 'cookies.txt')

    if os.path.exists(cookies_file):
        cmd.extend(['--cookies', cookies_file])
        logger.info(f"Using cookies from {cookies_file}")
    elif os.path.exists(local_cookies):
         cmd.extend(['--cookies', local_cookies])
         logger.info(f"Using cookies from local file: {local_cookies}")
    else:
        logger.info("Cookies file not found. Using visitor/guest mode.")

    # Streaming mode: get JSON metadata without downloading
    cmd.append('--dump-single-json')
    cmd.extend(['-f', 'bestaudio/best'])
    cmd.append(url)
    
    # logger.info(f"Running command: {' '.join(cmd)}")

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        error_msg = stderr.decode().strip()
        logger.error(f"yt-dlp error: {error_msg}")
        raise Exception(f"yt-dlp failed: {error_msg}")

    output = stdout.decode().strip()
    
    try:
        data = json.loads(output)
        return data
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse yt-dlp output: {output}")
        raise e


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None):
        loop = loop or asyncio.get_event_loop()
        
        try:
            data = await run_yt_dlp(url)
        except Exception as e:
            logger.error(f"yt-dlp streaming error: {e}")
            raise e

        if 'entries' in data:
            # take first item from a playlist
            data = data['entries'][0]

        stream_url = data['url']
        return cls(discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTIONS), data=data)


class MusicService:
    def __init__(self):
        # Dictionary to store queues per guild
        # Key: Guild ID, Value: deque of (url, context)
        self.queues: Dict[int, deque] = {}
        # Dictionary to track if music is currently playing per guild
        self.is_playing: Dict[int, bool] = {}

    def get_queue(self, guild_id: int) -> deque:
        if guild_id not in self.queues:
            self.queues[guild_id] = deque()
        return self.queues[guild_id]

    async def join_channel(self, ctx: commands.Context) -> bool:
        """Joins the user's voice channel"""
        if not ctx.author.voice:
            await ctx.send("You are not connected to a voice channel.")
            return False

        channel = ctx.author.voice.channel
        if ctx.voice_client is not None:
            await ctx.voice_client.move_to(channel)
        else:
            await channel.connect()
        return True

    async def add_to_queue(self, ctx: commands.Context, url: str):
        """Adds a song to the queue and starts playing if idle"""
        queue = self.get_queue(ctx.guild.id)
        queue.append((url, ctx))
        
        await ctx.send(f"Added to queue: {url}")

        if not self.is_playing.get(ctx.guild.id, False):
            await self.play_next(ctx.guild.id)

    async def play_next(self, guild_id: int):
        """Plays the next song in the queue for a guild"""
        queue = self.get_queue(guild_id)
        
        if not queue:
            self.is_playing[guild_id] = False
            return

        self.is_playing[guild_id] = True
        url, ctx = queue.popleft()

        # Ensure we are joined
        if not ctx.voice_client:
             if not await self.join_channel(ctx):
                 self.is_playing[guild_id] = False
                 return

        async with ctx.typing():
            try:
                player = await YTDLSource.from_url(url, loop=ctx.bot.loop)
                ctx.voice_client.play(
                    player, 
                    after=lambda e: self._play_next_callback(guild_id, e, ctx.bot.loop)
                )
                await ctx.send(f"Now playing: **{player.title}**")
            except Exception as e:
                error_msg = str(e)
                if "Sign in to confirm" in error_msg:
                    await ctx.send("I couldn't play that song because YouTube requires sign-in. Please try a different song or check bot configuration.")
                else:
                    await ctx.send(f"An error occurred playing this song.")
                
                logger.error(f"Error playing audio in guild {guild_id}: {e}")
                # Try next song if this one failed
                await self.play_next(guild_id)

    def _play_next_callback(self, guild_id: int, error, loop):
        """Callback for when audio finishes playing"""
        if error:
            logger.error(f"Player error: {error}")
        
        # Schedule the next song on the event loop
        asyncio.run_coroutine_threadsafe(self.play_next(guild_id), loop)

    async def skip(self, ctx: commands.Context):
        """Skips the current song"""
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            await ctx.send("Skipped current song.")
        else:
            await ctx.send("Nothing is currently playing.")
            
    async def stop(self, ctx: commands.Context):
        """Stops playing and clears the queue"""
        queue = self.get_queue(ctx.guild.id)
        queue.clear()
        
        if ctx.voice_client:
            ctx.voice_client.stop()
            await ctx.voice_client.disconnect()
            await ctx.send("Stopped playing and disconnected.")

