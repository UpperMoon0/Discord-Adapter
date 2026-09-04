from types import SimpleNamespace

import pytest

from main import app
from services.concurrency_manager import RateLimitConfig, UserRateLimiter
from services.session_service import SessionConfig, SessionLimitExceeded, SessionService


def test_public_app_does_not_mount_legacy_admin_or_cookie_routes():
    paths = {route.path for route in app.routes}
    assert "/api/bot" not in paths
    assert not any(path.startswith("/api/bot") for path in paths)
    assert not any(path.startswith("/api/cookies") for path in paths)
    assert not any(path.startswith("/ws/cookies") for path in paths)
    assert "/docs" not in paths
    assert "/openapi.json" not in paths
    assert "/mcp" in paths
    assert "/health" in paths


@pytest.mark.asyncio
async def test_per_user_rate_limit_bucket_persists_between_calls():
    limiter = UserRateLimiter(
        RateLimitConfig(max_requests_per_second=0, max_concurrent_requests=1, burst_limit=1)
    )
    assert await limiter.acquire("user-a") is True
    assert await limiter.acquire("user-a") is False
    # A separate user has an independent bucket.
    assert await limiter.acquire("user-b") is True


def test_session_limit_is_enforced_and_existing_scope_can_be_replaced():
    service = SessionService(SessionConfig(max_sessions=1))
    channel = SimpleNamespace(id=1)

    first = service.create_session("discord:1:10:100", "one", channel)
    replacement = service.create_session("discord:1:10:100", "one", channel)
    assert replacement is not first
    assert first.active is False

    with pytest.raises(SessionLimitExceeded):
        service.create_session("discord:1:10:101", "two", channel)


def test_wake_phrase_extraction_removes_entire_phrase():
    service = SessionService()
    assert service.extract_message_after_wake("Hey Lily hello world") == "hello world"
    assert service.extract_message_after_wake("hey lily") == ""
