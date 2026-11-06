import shutil
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class JobWorkspace:
    path: Path


@contextmanager
def job_workspace(media_root: Path, job_id: uuid.UUID) -> Iterator[JobWorkspace]:
    root = media_root.resolve()
    workspaces = root / "workspaces"
    workspaces.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = workspaces / str(job_id)
    path.mkdir(mode=0o700, parents=False, exist_ok=False)
    try:
        yield JobWorkspace(path=path)
    finally:
        shutil.rmtree(path, ignore_errors=True)


def cleanup_stale_workspaces(media_root: Path, *, older_than_seconds: int) -> int:
    workspaces = media_root.resolve() / "workspaces"
    if not workspaces.is_dir():
        return 0
    cutoff = time.time() - older_than_seconds
    removed = 0
    for child in workspaces.iterdir():
        try:
            if child.is_dir() and child.stat().st_mtime < cutoff:
                shutil.rmtree(child, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    return removed
