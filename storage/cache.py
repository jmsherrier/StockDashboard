"""
Redis cache wrapper.

Used to avoid redundant API calls — fundamental data cached for 7 days,
EOD prices for 1 day, intraday quotes for 5 minutes.

Falls back to a simple in-memory dict if Redis is unavailable (dev mode).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from config.settings import settings

logger = logging.getLogger(__name__)

_redis_client = None
_fallback_cache: dict[str, Any] = {}


async def _get_redis():
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        import redis.asyncio as aioredis
        _redis_client = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
        )
        await _redis_client.ping()
        logger.info("Redis connected at %s", settings.redis_url)
        return _redis_client
    except Exception as e:
        logger.warning("Redis unavailable (%s), using in-memory fallback", e)
        return None


async def cache_get(key: str) -> Optional[Any]:
    """Get a value from cache. Returns None on miss."""
    r = await _get_redis()
    if r:
        try:
            val = await r.get(key)
            return json.loads(val) if val else None
        except Exception:
            return None
    else:
        return _fallback_cache.get(key)


async def cache_set(key: str, value: Any, ttl: int = 3600) -> None:
    """Set a value in cache with TTL in seconds."""
    r = await _get_redis()
    serialized = json.dumps(value, default=str)
    if r:
        try:
            await r.set(key, serialized, ex=ttl)
        except Exception as e:
            logger.warning("Redis set failed: %s", e)
    else:
        _fallback_cache[key] = value  # No TTL in fallback


async def cache_delete(key: str) -> None:
    r = await _get_redis()
    if r:
        try:
            await r.delete(key)
        except Exception:
            pass
    else:
        _fallback_cache.pop(key, None)


async def cache_get_many(keys: list[str]) -> dict[str, Any]:
    """Batch get. Returns {key: value} for hits only."""
    r = await _get_redis()
    if r:
        try:
            pipe = r.pipeline()
            for k in keys:
                pipe.get(k)
            values = await pipe.execute()
            result = {}
            for k, v in zip(keys, values):
                if v is not None:
                    result[k] = json.loads(v)
            return result
        except Exception:
            return {}
    else:
        return {k: _fallback_cache[k] for k in keys if k in _fallback_cache}


async def cache_set_many(items: dict[str, Any], ttl: int = 3600) -> None:
    """Batch set."""
    r = await _get_redis()
    if r:
        try:
            pipe = r.pipeline()
            for k, v in items.items():
                pipe.set(k, json.dumps(v, default=str), ex=ttl)
            await pipe.execute()
        except Exception as e:
            logger.warning("Redis batch set failed: %s", e)
    else:
        _fallback_cache.update(items)
