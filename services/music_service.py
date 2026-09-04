"""Discord voice playback with a deliberately narrow YouTube network surface."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
from collections import deque
from typing import Dict
from urllib.parse import parse_qs, urlsplit

import discord
from discord.ext import commands

logger = logging.getLogger("lily-discord-adapter")

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

_YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
}
_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,64}$")


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _valid_video_id(value: str | None) -> bool:
    return bool(value and _VIDEO_ID_RE.fullmatch(value))


def validate_youtube_url(url: str) -> str:
    """Accept only direct HTTPS YouTube video URLs."""
    value = url.strip()
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid YouTube URL") from exc

    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or host not in _YOUTUBE_HOSTS:
        raise ValueError("Only HTTPS YouTube video URLs are allowed")
    if parsed.username or parsed.password or port not in (None, 443):
        raise ValueError("YouTube URL must not contain credentials or a custom port")

    path = parsed.path.rstrip("/")
    if host == "youtu.be":
        video_id = path.lstrip("/")
        if "/" in video_id or not _valid_video_id(video_id):
            raise ValueError("Invalid youtu.be video URL")
        return value

    if path == "/watch":
        video_ids = parse_qs(parsed.query, keep_blank_values=False).get("v", [])
        if len(video_ids) != 1 or not _valid_video_id(video_ids[0]):
            raise ValueError("YouTube watch URL must contain one valid video ID")
        return value

    for prefix in ("/shorts/", "/live/", "/embed/"):
        if path.startswith(prefix):
            video_id = path[len(prefix):]
            if "/" not in video_id and _valid_video_id(video_id):
                return value

    raise ValueError("Only direct YouTube video URLs are allowed")


def _validate_stream_url(url: str) -> str:
    """Reject unexpected extractor output before handing it to FFmpeg."""
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("yt-dlp returned an invalid media URL") from exc

    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not (
        host == "googlevideo.com" or host.endswith(".googlevideo.com")
    ):
        raise ValueError("yt-dlp returned an unexpected media host")
    if parsed.username or parsed.password or port not in (None, 443):
        raise ValueError("yt-dlp returned an unsafe media URL")
    return url


async def run_yt_dlp(url: str):
    safe_url = validate_youtube_url(url)
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    binary_path = os.path.join(base_dir, "yt-dlp")
    if not os.path.exists(binary_path):
        binary_path = "yt-dlp"

    cmd = [
        sys.executable,
        binary_path,
        "--no-playlist",
        "--quiet",
        "--no-warnings",
        "--socket-timeout",
        "10",
        "--retries",
        "2",
        "--js-runtimes",
        "node",
        "--remote-components",
        "ejs:github",
    ]

    cookies_file = "/app/data/cookies.txt"
    local_cookies = os.path.join(base_dir, "cookies.txt")
    if os.path.exists(cookies_file):
        cmd.extend(["--cookies", cookies_file])
    elif os.path.exists(local_cookies):
        cmd.extend(["--cookies", local_cookies])

    cmd.extend(["--dump-single-json", "-f", "bestaudio/best", safe_url])

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.communicate()
        raise ValueError("YouTube lookup timed out") from exc

    if process.returncode != 0:
        logger.warning(
            "yt-dlp rejected a validated YouTube URL: %s",
            stderr.decode(errors="replace")[-500:],
        )
        raise ValueError("YouTube lookup failed")

    if len(stdout) > 4 * 1024 * 1024:
        raise ValueError("YouTube metadata response was unexpectedly large")

    try:
        data = json.loads(stdout.decode())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Could not parse YouTube metadata") from exc
    if not isinstance(data, dict):
        raise ValueError("Unexpected YouTube metadata")
    return data


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get("title")
        self.url = data.get("url")

    @classmethod
    async def from_url(cls, url, *, loop=None):
        del loop
        data = await run_yt_dlp(url)
        if "entries" in data:
            entries = data.get("entries") or []
            if not entries:
                raise ValueError("YouTube result did not contain a playable entry")
            data = entries[0]
        stream_url = _validate_stream_url(str(data.get("url", "")))
        return cls(discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTIONS), data=data)


class MusicService:
    def __init__(self):
        self.queues: Dict[int, deque] = {}
        self.is_playing: Dict[int, bool] = {}
        self.max_queue_per_guild = _positive_int_env("MUSIC_QUEUE_MAX_PER_GUILD", 25)

    def get_queue(self, guild_id: int) -> deque:
        if guild_id not in self.queues:
            self.queues[guild_id] = deque()
        return self.queues[guild_id]

    async def join_channel(self, ctx: commands.Context) -> bool:
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
        try:
            safe_url = validate_youtube_url(url)
        except ValueError as exc:
            await ctx.send(str(exc))
            return False

        queue = self.get_queue(ctx.guild.id)
        if len(queue) >= self.max_queue_per_guild:
            await ctx.send("The music queue is full. Please wait for a slot to open.")
            return False

        queue.append((safe_url, ctx))
        await ctx.send("Added YouTube video to queue.")
        if not self.is_playing.get(ctx.guild.id, False):
            await self.play_next(ctx.guild.id)
        return True

    async def play_next(self, guild_id: int):
        queue = self.get_queue(guild_id)
        if not queue:
            self.is_playing[guild_id] = False
            return

        self.is_playing[guild_id] = True
        url, ctx = queue.popleft()
        if not ctx.voice_client and not await self.join_channel(ctx):
            self.is_playing[guild_id] = False
            return

        async with ctx.typing():
            try:
                player = await YTDLSource.from_url(url, loop=ctx.bot.loop)
                ctx.voice_client.play(
                    player,
                    after=lambda error: self._play_next_callback(guild_id, error, ctx.bot.loop),
                )
                await ctx.send(f"Now playing: **{player.title}**")
            except Exception as exc:
                logger.warning("Validated YouTube playback failed: %s", exc)
                await ctx.send("I couldn't safely play that YouTube video.")
                await self.play_next(guild_id)

    def _play_next_callback(self, guild_id: int, error, loop):
        if error:
            logger.error("Player error: %s", error)
        asyncio.run_coroutine_threadsafe(self.play_next(guild_id), loop)

    async def skip(self, ctx: commands.Context):
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            await ctx.send("Skipped current song.")
        else:
            await ctx.send("Nothing is currently playing.")

    async def stop(self, ctx: commands.Context):
        queue = self.get_queue(ctx.guild.id)
        queue.clear()
        if ctx.voice_client:
            ctx.voice_client.stop()
            await ctx.voice_client.disconnect()
            await ctx.send("Stopped playing and disconnected.")
