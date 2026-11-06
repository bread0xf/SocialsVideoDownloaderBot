from arq.connections import RedisSettings
from arq.typing import WorkerSettingsBase

from backend.core.config import get_settings

_settings = get_settings()


async def health_check(ctx: dict[str, object]) -> str:
    return "ok"


class WorkerSettings(WorkerSettingsBase):
    functions = [health_check]
    redis_settings = RedisSettings.from_dsn(_settings.redis_url)
    max_jobs = _settings.worker_concurrency
    job_timeout = _settings.job_timeout_seconds
