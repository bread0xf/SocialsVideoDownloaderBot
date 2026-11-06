from typing import cast

from arq import cron
from arq.connections import RedisSettings
from arq.typing import StartupShutdown, WorkerSettingsBase

from backend.core.config import get_settings
from backend.workers.tasks import (
    cleanup_cache,
    dispatch_outbox,
    process_download,
    reconcile_stale_jobs,
    worker_shutdown,
    worker_startup,
)

_settings = get_settings()


async def health_check(ctx: dict[str, object]) -> str:
    return "ok"


def _seconds_set(interval_seconds: int) -> set[int]:
    return set(range(0, 60, max(1, min(interval_seconds, 59))))


def _minutes_set(interval_seconds: int) -> set[int]:
    minutes = max(1, interval_seconds // 60)
    return set(range(0, 60, min(minutes, 60)))


if _settings.outbox_poll_interval_seconds < 60:
    _outbox_cron = cron(
        dispatch_outbox,
        second=_seconds_set(_settings.outbox_poll_interval_seconds),
        run_at_startup=True,
        timeout=30,
    )
else:
    _outbox_cron = cron(
        dispatch_outbox,
        minute=_minutes_set(_settings.outbox_poll_interval_seconds),
        second=0,
        run_at_startup=True,
        timeout=30,
    )


class WorkerSettings(WorkerSettingsBase):
    functions = [
        health_check,
        process_download,
        dispatch_outbox,
        cleanup_cache,
        reconcile_stale_jobs,
    ]
    cron_jobs = [
        _outbox_cron,
        cron(
            cleanup_cache,
            minute=_minutes_set(_settings.cache_cleanup_interval_seconds),
            second=0,
            run_at_startup=True,
            timeout=300,
        ),
        cron(
            reconcile_stale_jobs,
            minute=_minutes_set(300),
            second=0,
            run_at_startup=True,
            timeout=120,
        ),
    ]
    on_startup = cast(StartupShutdown, worker_startup)
    on_shutdown = cast(StartupShutdown, worker_shutdown)
    redis_settings = RedisSettings.from_dsn(_settings.redis_url)
    max_jobs = _settings.worker_concurrency
    job_timeout = max(
        _settings.job_timeout_seconds,
        _settings.extractor_timeout_seconds + _settings.ffmpeg_timeout_seconds + 120,
    )
    max_tries = 1
    keep_result = 0
