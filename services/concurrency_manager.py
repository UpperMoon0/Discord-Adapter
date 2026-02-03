"""
Concurrency Manager
Handles concurrent message processing with rate limiting and message queuing
"""

import asyncio
import logging
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict
import time

logger = logging.getLogger("lily-discord-adapter")


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting"""
    max_requests_per_second: int = 10
    max_concurrent_requests: int = 5
    burst_limit: int = 20


class RateLimiter:
    """Token bucket rate limiter"""
    
    def __init__(self, config: RateLimitConfig = None):
        self.config = config or RateLimitConfig()
        self.tokens = self.config.burst_limit
        self.last_update = time.monotonic()
        self._lock = asyncio.Lock()
    
    async def acquire(self, user_id: str = "global") -> bool:
        """Acquire a token from the rate limiter"""
        async with self._lock:
            now = time.monotonic()
            time_passed = now - self.last_update
            
            # Add tokens based on time passed
            tokens_to_add = time_passed * self.config.max_requests_per_second
            self.tokens = min(self.tokens + tokens_to_add, self.config.burst_limit)
            self.last_update = now
            
            if self.tokens >= 1:
                self.tokens -= 1
                return True
            return False
    
    async def wait_for_token(self, user_id: str = "global", timeout: float = 10.0):
        """Wait for a token to become available"""
        start_time = time.monotonic()
        while time.monotonic() - start_time < timeout:
            if await self.acquire(user_id):
                return True
            await asyncio.sleep(0.1)  # Wait 100ms before retrying
        raise TimeoutError(f"Rate limit timeout for user {user_id}")


class MessageQueue:
    """Thread-safe message queue for async processing"""
    
    def __init__(self, max_size: int = 1000):
        self._queue = asyncio.Queue(maxsize=max_size)
        self._processing = 0
        self._lock = asyncio.Lock()
        self._errors = 0
    
    async def put(self, item, priority: int = 0):
        """Add item to queue with optional priority"""
        try:
            await asyncio.wait_for(self._queue.put((priority, item)), timeout=1.0)
        except asyncio.TimeoutError:
            logger.warning("Message queue full, dropping message")
            return False
        return True
    
    async def get(self):
        """Get item from queue"""
        try:
            priority, item = await self._queue.get()
            return item
        except asyncio.CancelledError:
            raise
    
    def qsize(self) -> int:
        """Get current queue size"""
        return self._queue.qsize()
    
    def empty(self) -> bool:
        """Check if queue is empty"""
        return self._queue.empty()
    
    @property
    def processing(self) -> int:
        """Get number of items being processed"""
        return self._processing
    
    async def start_processing(self):
        """Mark item as being processed"""
        async with self._lock:
            self._processing += 1
    
    async def stop_processing(self):
        """Mark item as done processing"""
        async with self._lock:
            self._processing -= 1
    
    @property
    def error_count(self) -> int:
        """Get error count"""
        return self._errors
    
    async def record_error(self):
        """Record a processing error"""
        async with self._lock:
            self._errors += 1


class ConcurrencyManager:
    """Manager for concurrent message processing"""
    
    def __init__(self, 
                 max_concurrent: int = 10,
                 queue_size: int = 1000,
                 rate_limit_config: RateLimitConfig = None):
        """
        Initialize concurrency manager.
        
        Args:
            max_concurrent: Maximum concurrent tasks
            queue_size: Maximum queue size
            rate_limit_config: Rate limiting configuration
        """
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.message_queue = MessageQueue(queue_size)
        self.rate_limiter = RateLimiter(rate_limit_config)
        self._workers = []
        self._running = False
    
    async def start_workers(self, num_workers: int = 4, worker_func=None):
        """Start worker tasks for processing messages"""
        self._running = True
        for i in range(num_workers):
            task = asyncio.create_task(self._worker(f"worker-{i}", worker_func))
            self._workers.append(task)
        logger.info(f"Started {num_workers} workers")
    
    async def _worker(self, name: str, func=None):
        """Worker task that processes messages from queue"""
        while self._running or not self.message_queue.empty():
            try:
                item = await asyncio.wait_for(
                    self.message_queue.get(),
                    timeout=1.0
                )
                
                self.message_queue.start_processing()
                try:
                    if func:
                        await func(item)
                    else:
                        # Default processing - just log
                        logger.debug(f"Processing: {item}")
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
                    self.message_queue.record_error()
                finally:
                    self.message_queue.stop_processing()
                    
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
    
    async def submit_message(self, message, priority: int = 0) -> bool:
        """Submit a message for processing"""
        # Check rate limit
        if not await self.rate_limiter.acquire():
            logger.warning("Rate limit exceeded")
            return False
        
        # Add to queue
        return await self.message_queue.put(message, priority)
    
    async def process_with_limit(self, coro):
        """Process a coroutine with concurrency limits"""
        async with self.semaphore:
            return await coro
    
    async def shutdown(self):
        """Shutdown all workers"""
        self._running = False
        for task in self._workers:
            task.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        logger.info("Concurrency manager shutdown complete")
    
    @property
    def stats(self) -> dict:
        """Get concurrency manager stats"""
        return {
            "queue_size": self.message_queue.qsize(),
            "processing": self.message_queue.processing,
            "errors": self.message_queue.error_count,
            "workers": len(self._workers),
            "running": self._running
        }


# Per-user rate limiting
class UserRateLimiter:
    """Per-user rate limiter with configurable limits"""
    
    def __init__(self, default_config: RateLimitConfig = None):
        self.default_config = default_config or RateLimitConfig()
        self._user_limits = {}
        self._lock = asyncio.Lock()
    
    def get_config_for_user(self, user_id: str) -> RateLimitConfig:
        """Get rate limit config for a user"""
        return self._user_limits.get(user_id, self.default_config)
    
    async def acquire(self, user_id: str) -> bool:
        """Acquire token for user"""
        async with self._lock:
            if user_id not in self._user_limits:
                self._user_limits[user_id] = RateLimitConfig()
            
            limiter = RateLimiter(self._user_limits[user_id])
            return await limiter.acquire(user_id)
    
    async def set_custom_limit(self, user_id: str, config: RateLimitConfig):
        """Set custom rate limit for a user"""
        async with self._lock:
            self._user_limits[user_id] = config
