import os
import redis.asyncio as aioredis

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

_redis = None


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    return _redis


async def set_stock(product_id: int, quantity: int) -> None:
    try:
        r = await get_redis()
        await r.set(f"remaining:{product_id}", quantity)
    except Exception as e:
        print(f"[Redis] set_stock 실패 (product_id={product_id}): {e}")
