"""
Layer 7 -- Data & cache store.

Responsibilities
  1. Cache hot data: VLM analysis results keyed by PDF content fingerprint
     (MD5), plus arXiv search results keyed by keyword.
  2. Persist asynchronous job state: queued / running / completed / failed,
     together with real per-chart progress that a separate worker process
     can report across the process boundary.
  3. Degrade gracefully: when Redis is not installed or not reachable, fall
     back to an in-process memory store so the project runs out of the box.

Known limits (stated explicitly)
  - In memory mode, restarting the process loses cached results and job
    state. Redis persists both, so it is strongly recommended in production.
  - This layer does not own the worker model: without Redis, jobs still run
    inside the API process; the queue methods only coordinate a separate
    worker.py process. Scaling across machines requires a job queue framework
    such as arq or Celery.
"""

import json
import time
from typing import Any, Optional

from app.core.config import settings
from app.core.logging import logger

try:  # redis 是可选依赖：未安装不会让服务起不来
    import redis.asyncio as aioredis

    _REDIS_AVAILABLE = True
except Exception:  # pragma: no cover - 取决于本机环境
    aioredis = None
    _REDIS_AVAILABLE = False


class _MemoryKV:
    """Minimal TTL semantics: expiry recorded on write, purged lazily on read."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[float, str]] = {}

    def get(self, key: str) -> Optional[str]:
        item = self._data.get(key)
        if item is None:
            return None
        expire_at, value = item
        if expire_at and expire_at < time.time():
            self._data.pop(key, None)
            return None
        return value

    def set(self, key: str, value: str, ttl: int) -> None:
        self._data[key] = (time.time() + ttl if ttl > 0 else 0.0, value)

    def delete(self, key: str) -> None:
        self._data.pop(key, None)

    def size(self) -> int:
        return len(self._data)


class KVStore:
    """Key/value store that prefers Redis and falls back to process memory.

    All public methods are async so callers never block the event loop.
    """

    def __init__(self, url: str) -> None:
        self._url = url
        self._client = None
        self._tried = False
        self._mem = _MemoryKV()
        self.backend = "memory"

    async def _get_client(self):
        """Probe Redis once per process and memoize the result.

        Without the memoization every request would pay a connection
        attempt, which is unacceptable when Redis is simply not installed.
        """
        if self._tried:
            return self._client
        self._tried = True

        if not _REDIS_AVAILABLE:
            logger.warning(
                "ℹ️ 未安装 redis 库，缓存/任务状态走进程内存（pip install redis 可启用 Redis）"
            )
            return None

        try:
            # 连接超时收紧到 1.5s：本机没跑 Redis 时，首请求不该为探测等 4 秒
            client = aioredis.from_url(
                self._url,
                decode_responses=True,
                socket_connect_timeout=1.5,
                socket_timeout=3.0,
            )
            await client.ping()
            self._client = client
            self.backend = "redis"
            logger.info(f"✅ Redis 已连接: {self._url}")
        except Exception as exc:
            self._client = None
            logger.warning(
                f"⚠️ Redis 不可用（{type(exc).__name__}: {exc}），已降级为进程内存存储"
            )
        return self._client

    async def set_json(self, key: str, value: Any, ttl: int = 0) -> None:
        raw = json.dumps(value, ensure_ascii=False)
        client = await self._get_client()
        if client is not None:
            try:
                await client.set(key, raw, ex=ttl if ttl > 0 else None)
                return
            except Exception as exc:
                logger.warning(f"Redis set 失败，回落内存: {exc}")
        self._mem.set(key, raw, ttl)

    async def get_json(self, key: str) -> Optional[Any]:
        raw: Optional[str] = None
        client = await self._get_client()
        if client is not None:
            try:
                raw = await client.get(key)
            except Exception as exc:
                logger.warning(f"Redis get 失败，回落内存: {exc}")
                raw = None
        if raw is None:
            raw = self._mem.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None

    async def delete(self, key: str) -> None:
        client = await self._get_client()
        if client is not None:
            try:
                await client.delete(key)
            except Exception as exc:
                logger.warning(f"Redis delete 失败: {exc}")
        self._mem.delete(key)

    def info(self) -> dict:
        """Report the storage backend actually in effect, for /api/health."""
        payload = {"backend": self.backend, "url": self._url}
        if self.backend == "memory":
            payload["memory_keys"] = self._mem.size()
            payload["redis_lib_installed"] = _REDIS_AVAILABLE
        return payload

    # ------------------------------------------------------------------
    # Reliable queue (v2.1): LPUSH + BRPOPLPUSH + LREM.
    # Available only on a real Redis server; the memory backend has no
    # cross-process semantics, so every queue method returns a falsy value.
    # BRPOPLPUSH moves a payload into the processing list as it is popped, so
    # a crashed worker cannot lose jobs: they stay in the processing list and
    # reclaim_processing() requeues them on the next startup.
    # ------------------------------------------------------------------
    async def queue_available(self) -> bool:
        return (await self._get_client()) is not None

    async def queue_push(self, queue: str, payload: str) -> bool:
        client = await self._get_client()
        if client is None:
            return False
        await client.lpush(queue, payload)
        return True

    async def queue_pop(self, queue: str, processing: str, timeout: int = 5) -> Optional[str]:
        client = await self._get_client()
        if client is None:
            return None
        return await client.brpoplpush(queue, processing, timeout)

    async def queue_ack(self, processing: str, payload: str) -> None:
        client = await self._get_client()
        if client is None:
            return
        await client.lrem(processing, 1, payload)

    async def queue_len(self, queue: str) -> int:
        client = await self._get_client()
        if client is None:
            return 0
        return await client.llen(queue)

    async def reclaim_processing(self, queue: str, processing: str) -> int:
        """Move stranded processing-list entries back to the main queue.

        When a worker is killed or the machine loses power, its payloads stay
        in the processing list and never requeue themselves. Calling this at
        worker startup prevents jobs from hanging forever.
        """
        client = await self._get_client()
        if client is None:
            return 0
        moved = 0
        while True:
            item = await client.rpoplpush(processing, queue)
            if item is None:
                break
            moved += 1
        return moved


# ----------------------------------------------------------------------
# Global singleton + key namespace convention
# ----------------------------------------------------------------------
store = KVStore(settings.REDIS_URL)


def analyze_key(file_hash: str) -> str:
    """Cache slot for a PDF analysis result, keyed by content fingerprint."""
    return f"sv:analyze:{file_hash}"


def search_key(keyword: str) -> str:
    return f"sv:search:{keyword.strip().lower()}"


def job_key(job_id: str) -> str:
    return f"sv:job:{job_id}"
