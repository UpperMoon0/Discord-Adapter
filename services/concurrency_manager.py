"""Concurrency and rate-limiting primitives for Discord message processing."""

import asyncio
import logging
import time
from dataclasses import dataclass

logger = logging.getLogger("lily-discord-adapter")


@dataclass(frozen=True)
class RateLimitConfig:
    """Token-bucket configuration."""

    max_requests_per_second: int = 10
    max_concurrent_requests: int = 5
    burst_limit: int = 20


class RateLimiter:
    """A reusable token bucket.

    A limiter must be kept alive between calls. Recreating it for each request
    refills the bucket and silently disables rate limiting.
    """

    def __init__(self, config: RateLimitConfig | None = None):
        self.config = config or RateLimitConfig()
        self.tokens = float(self.config.burst_limit)
        self.last_update = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, user_id: str = "global") -> bool:
        del user_id  # Kept for compatibility with existing callers.
        async with self._lock:
            now = time.monotonic()
            elapsed = max(0.0, now - self.last_update)
            self.tokens = min(
                float(self.config.burst_limit),
                self.tokens + elapsed * self.config.max_requests_per_second,
            )
            self.last_update = now
            if self.tokens < 1.0:
                return False
            self.tokens -= 1.0
            return True

    async def wait_for_token(self, user_id: str = "global", timeout: float = 10.0):
        start_time = time.monotonic()
        while time.monotonic() - start_time < timeout:
            if await self.acquire(user_id):
                return True
            await asyncio.sleep(0.1)
        raise TimeoutError(f"Rate limit timeout for user {user_id}")


class MessageQueue:
    """Bounded async message queue."""

    def __init__(self, max_size: int = 1000):
        self._queue = asyncio.Queue(maxsize=max_size)
        self._processing = 0
        self._lock = asyncio.Lock()
        self._errors = 0

    async def put(self, item, priority: int = 0):
        try:
            await asyncio.wait_for(self._queue.put((priority, item)), timeout=1.0)
        except asyncio.TimeoutError:
            logger.warning("Message queue full, dropping message")
            return False
        return True

    async def get(self):
        priority, item = await self._queue.get()
        del priority
        return item

    def qsize(self) -> int:
        return self._queue.qsize()

    def empty(self) -> bool:
        return self._queue.empty()

    @property
    def processing(self) -> int:
        return self._processing

    async def start_processing(self):
        async with self._lock:
            self._processing += 1

    async def stop_processing(self):
        async with self._lock:
            self._processing -= 1

    @property
    def error_count(self) -> int:
        return self._errors

    async def record_error(self):
        async with self._lock:
            self._errors += 1


class ConcurrencyManager:
    """Bound globally queued work before it reaches Lily-Core."""

    def __init__(
        self,
        max_concurrent: int = 10,
        queue_size: int = 1000,
        rate_limit_config: RateLimitConfig | None = None,
    ):
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.message_queue = MessageQueue(queue_size)
        self.rate_limiter = RateLimiter(rate_limit_config)
        self._workers = []
        self._running = False

    async def start_workers(self, num_workers: int = 4, worker_func=None):
        self._running = True
        for index in range(num_workers):
            task = asyncio.create_task(self._worker(f"worker-{index}", worker_func))
            self._workers.append(task)
        logger.info("Started %s workers", num_workers)

    async def _worker(self, name, func=None):
        del name
        while self._running or not self.message_queue.empty():
            try:
                try:
                    item = await asyncio.wait_for(self.message_queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue

                await self.message_queue.start_processing()
                try:
                    if func:
                        result = func(item)
                        if asyncio.iscoroutine(result):
                            await result
                except Exception as exc:
                    logger.error("Error processing message: %s", exc)
                    await self.message_queue.record_error()
                finally:
                    await self.message_queue.stop_processing()
            except asyncio.CancelledError:
                break

    async def submit_message(self, message, priority: int = 0) -> bool:
        if not await self.rate_limiter.acquire():
            logger.warning("Global message rate limit exceeded")
            return False
        return await self.message_queue.put(message, priority)

    async def process_with_limit(self, coro):
        async with self.semaphore:
            return await coro

    async def shutdown(self):
        self._running = False
        for task in self._workers:
            task.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        logger.info("Concurrency manager shutdown complete")

    @property
    def stats(self) -> dict:
        return {
            "queue_size": self.message_queue.qsize(),
            "processing": self.message_queue.processing,
            "errors": self.message_queue.error_count,
            "workers": len(self._workers),
            "running": self._running,
        }


class UserRateLimiter:
    """Per-user token buckets that persist across requests."""

    def __init__(self, default_config: RateLimitConfig | None = None):
        self.default_config = default_config or RateLimitConfig()
        self._user_configs: dict[str, RateLimitConfig] = {}
        self._limiters: dict[str, RateLimiter] = {}
        self._lock = asyncio.Lock()

    def get_config_for_user(self, user_id: str) -> RateLimitConfig:
        return self._user_configs.get(user_id, self.default_config)

    async def _limiter_for(self, user_id: str) -> RateLimiter:
        async with self._lock:
            limiter = self._limiters.get(user_id)
            if limiter is None:
                limiter = RateLimiter(self.get_config_for_user(user_id))
                self._limiters[user_id] = limiter
            return limiter

    async def acquire(self, user_id: str) -> bool:
        limiter = await self._limiter_for(user_id)
        return await limiter.acquire(user_id)

    async def set_custom_limit(self, user_id: str, config: RateLimitConfig):
        async with self._lock:
            self._user_configs[user_id] = config
            self._limiters[user_id] = RateLimiter(config)
