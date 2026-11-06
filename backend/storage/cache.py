import asyncio
import os
import re
import uuid
from pathlib import Path

from backend.core.errors import AppError, ErrorCode

_CACHE_KEY = re.compile(r"^[a-f0-9]{64}$")


def _cache_root(media_root: Path) -> Path:
    root = media_root.resolve() / "cache"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


def cache_path(media_root: Path, media_key: str) -> Path:
    if not _CACHE_KEY.match(media_key):
        raise AppError(ErrorCode.INTERNAL_ERROR, "Invalid cache key.")
    return _cache_root(media_root) / f"{media_key}.mp4"


def _store(source: Path, media_root: Path, media_key: str) -> Path:
    destination = cache_path(media_root, media_key)
    if not source.resolve().is_file():
        raise AppError(ErrorCode.INTERNAL_ERROR, "Prepared media is missing.")
    temp = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        with source.open("rb") as source_file, temp.open("wb") as target_file:
            while chunk := source_file.read(1024 * 1024):
                target_file.write(chunk)
        temp.chmod(0o600)
        os.replace(temp, destination)
    finally:
        temp.unlink(missing_ok=True)
    return destination


async def store_cache_file(source: Path, media_root: Path, media_key: str) -> Path:
    return await asyncio.to_thread(_store, source, media_root, media_key)


def _remove(storage_path: str, media_root: Path) -> None:
    root = _cache_root(media_root)
    path = Path(storage_path).resolve()
    if path.is_relative_to(root):
        path.unlink(missing_ok=True)


async def remove_cache_file(storage_path: str, media_root: Path) -> None:
    await asyncio.to_thread(_remove, storage_path, media_root)


def cache_file_exists(storage_path: str, media_root: Path) -> bool:
    root = _cache_root(media_root)
    try:
        path = Path(storage_path).resolve()
    except OSError:
        return False
    return path.is_relative_to(root) and path.is_file()
