from redis.asyncio import Redis

from backend.core.config import Settings


def build_redis(settings: Settings) -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=True)
