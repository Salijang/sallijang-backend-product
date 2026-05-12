import os
import json
import redis.asyncio as aioredis

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

_redis = None


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
    return _redis


async def publish_product_update(product_id: int, remaining: int, action: str = "stock") -> None:
    try:
        r = await get_redis()
        await r.publish("sse:products", json.dumps({"product_id": product_id, "remaining": remaining, "action": action}))
    except Exception as e:
        print(f"[Redis] publish_product_update 실패 (product_id={product_id}): {e}")


async def set_stock(product_id: int, quantity: int, ttl: int = 86400) -> None:
    try:
        r = await get_redis()
        await r.set(f"remaining:{product_id}", quantity, ex=ttl)
    except Exception as e:
        print(f"[Redis] set_stock 실패 (product_id={product_id}): {e}")
