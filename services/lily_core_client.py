"""Low-level HTTP client for Lily-Core."""

import logging
from typing import Optional

import httpx

logger = logging.getLogger("lily-discord-adapter")


class LilyCoreClient:
    """HTTP communication only; trust decisions belong at the Discord boundary."""

    def __init__(self, get_http_url_func):
        self.get_http_url_func = get_http_url_func
        self.http_url = None
        self.http_client = httpx.AsyncClient(timeout=120.0)

    async def get_base_url(self, force_refresh: bool = False) -> Optional[str]:
        if force_refresh or not self.http_url:
            self.http_url = self.get_http_url_func()
        return self.http_url

    async def send_chat_request(self, message: str, user_id: str, username: str) -> Optional[dict]:
        http_url = await self.get_base_url()
        if not http_url:
            logger.error("lily-core HTTP URL not found")
            return None

        payload = {
            "message": message,
            "user_id": user_id,
            "username": username,
        }
        # Never log user-controlled prompt text or Lily-Core response bodies.
        logger.info(
            "Sending scoped Discord chat request to lily-core for %s (%s chars)",
            user_id,
            len(message),
        )

        try:
            response = await self.http_client.post(
                f"{http_url}/chat",
                json=payload,
                timeout=120.0,
            )
            if response.status_code == 200:
                data = response.json()
                logger.info("Received lily-core response for %s", user_id)
                return data
            logger.error("lily-core request failed with status %s", response.status_code)
            return None
        except httpx.RequestError as exc:
            logger.error("lily-core HTTP request error: %s", type(exc).__name__)
            self.http_url = None
            return None
        except Exception as exc:
            logger.error("Unexpected lily-core response error: %s", type(exc).__name__)
            return None

    async def close(self):
        await self.http_client.aclose()

    async def health_check(self) -> bool:
        http_url = await self.get_base_url()
        if not http_url:
            return False
        try:
            response = await self.http_client.get(f"{http_url}/health", timeout=10.0)
            if response.status_code == 200:
                return True
            self.http_url = None
            return False
        except Exception:
            self.http_url = None
            return False
