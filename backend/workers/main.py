from arq import run_worker

from backend.core.config import get_settings
from backend.core.logging import configure_logging
from backend.workers.settings import WorkerSettings


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    run_worker(WorkerSettings)
