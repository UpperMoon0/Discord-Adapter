from unittest.mock import AsyncMock, MagicMock

import pytest

from services.music_service import MusicService, _validate_stream_url, validate_youtube_url


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://youtube.com/shorts/dQw4w9WgXcQ",
        "https://music.youtube.com/watch?v=dQw4w9WgXcQ",
    ],
)
def test_validate_youtube_url_accepts_direct_video_urls(url):
    assert validate_youtube_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "http://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://127.0.0.1/watch?v=dQw4w9WgXcQ",
        "https://localhost/watch?v=dQw4w9WgXcQ",
        "https://youtube.com@127.0.0.1/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com:8443/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/redirect?q=http://redis:6379",
        "https://www.youtube.com/watch?v=",
        "https://evil.youtube.com/watch?v=dQw4w9WgXcQ",
    ],
)
def test_validate_youtube_url_rejects_generic_or_internal_targets(url):
    with pytest.raises(ValueError):
        validate_youtube_url(url)


def test_stream_url_accepts_only_https_googlevideo():
    safe = "https://rr1---sn.example.googlevideo.com/videoplayback?id=abc"
    assert _validate_stream_url(safe) == safe

    for unsafe in (
        "http://rr1---sn.example.googlevideo.com/videoplayback?id=abc",
        "https://redis:6379/",
        "https://127.0.0.1/",
        "https://googlevideo.com@127.0.0.1/",
        "https://googlevideo.com:8443/videoplayback",
    ):
        with pytest.raises(ValueError):
            _validate_stream_url(unsafe)


@pytest.mark.asyncio
async def test_music_queue_has_hard_per_guild_cap(monkeypatch):
    monkeypatch.setenv("MUSIC_QUEUE_MAX_PER_GUILD", "2")
    service = MusicService()
    service.is_playing[123] = True

    ctx = MagicMock()
    ctx.guild.id = 123
    ctx.send = AsyncMock()
    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    assert await service.add_to_queue(ctx, url) is True
    assert await service.add_to_queue(ctx, url) is True
    assert await service.add_to_queue(ctx, url) is False
    assert len(service.get_queue(123)) == 2
    assert "queue is full" in ctx.send.await_args_list[-1].args[0].lower()
