from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from backend.api import main as api_main
from backend.api.app import create_app
from backend.api.routes import rewards as rewards_route
from backend.core.config import Settings
from backend.rewards.service import RewardGrantResult

SECRET = "s" * 40
BLOCK = "50001"
PATH = "/api/v1/rewards/adsun/callback"


@pytest.fixture(autouse=True)
def _do_not_reconfigure_global_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("backend.api.app.configure_logging", lambda *args, **kwargs: None)


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "test",
        "adsun_enabled": True,
        "adsun_block_id": BLOCK,
        "adsun_reward_secret": SECRET,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _client(settings: Settings) -> httpx.AsyncClient:
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def _app_client(settings: Settings) -> httpx.AsyncClient:
    """Build a client whose app has the session factory the route needs.

    ``httpx.ASGITransport`` does not run the FastAPI lifespan, so the route's
    ``session_scope`` is replaced in the tests that reach the database call.
    """
    app = create_app(settings)
    app.state.session_factory = object()
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@asynccontextmanager
async def _fake_scope(_factory: object) -> AsyncIterator[object]:
    yield object()


def _url(**params: str | int) -> str:
    defaults: dict[str, str | int] = {
        "userid": 12345,
        "block": BLOCK,
        "secret": SECRET,
        "ts": int(datetime.now(UTC).timestamp()),
    }
    defaults.update(params)
    query = "&".join(f"{key}={value}" for key, value in defaults.items())
    return f"{PATH}?{query}"


class _RecordingLogger:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def debug(self, event: str, **kwargs: Any) -> None:
        self.calls.append(("debug", event, kwargs))

    def warning(self, event: str, **kwargs: Any) -> None:
        self.calls.append(("warning", event, kwargs))

    def info(self, event: str, **kwargs: Any) -> None:
        self.calls.append(("info", event, kwargs))

    def error(self, event: str, **kwargs: Any) -> None:
        self.calls.append(("error", event, kwargs))

    def exception(self, event: str, **kwargs: Any) -> None:
        self.calls.append(("exception", event, kwargs))


async def test_disabled_feature_returns_404() -> None:
    async with _client(_settings(adsun_enabled=False)) as client:
        response = await client.get(_url())

    assert response.status_code == 404
    assert response.text == "Not found"


async def test_missing_secret_configuration_returns_404() -> None:
    async with _client(_settings(adsun_reward_secret="")) as client:
        response = await client.get(_url())

    assert response.status_code == 404


async def test_unconfigured_probe_is_logged_at_debug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recording = _RecordingLogger()
    monkeypatch.setattr(rewards_route, "logger", recording)

    async with _client(_settings(adsun_enabled=False)) as client:
        response = await client.get(_url())

    assert response.status_code == 404
    assert [call[0] for call in recording.calls] == ["debug"]


async def test_bad_secret_returns_403() -> None:
    async with _client(_settings()) as client:
        response = await client.get(_url(secret="wrong"))

    assert response.status_code == 403
    assert response.text == "Forbidden"


async def test_rejections_are_not_cacheable() -> None:
    async with _client(_settings()) as client:
        response = await client.get(_url(secret="wrong"))

    assert response.headers["cache-control"] == "no-store"


async def test_missing_user_returns_400() -> None:
    async with _client(_settings()) as client:
        response = await client.get(f"{PATH}?block={BLOCK}&secret={SECRET}&ts=1")

    assert response.status_code == 400


async def test_non_ascii_digits_are_rejected() -> None:
    async with _client(_settings()) as client:
        response = await client.get(_url(userid="٥٠٠٠١"))

    assert response.status_code == 400


async def test_block_mismatch_returns_400() -> None:
    async with _client(_settings()) as client:
        response = await client.get(_url(block="99999"))

    assert response.status_code == 400


async def test_prefixed_callback_block_is_normalised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _accepted(*args: Any, **kwargs: Any) -> RewardGrantResult:
        return RewardGrantResult(status="accepted", credits_granted=1)

    monkeypatch.setattr(rewards_route, "session_scope", _fake_scope)
    monkeypatch.setattr(rewards_route, "grant_reward", _accepted)

    async with _app_client(_settings()) as client:
        response = await client.get(_url(block="bot-50001"))

    assert response.status_code == 200
    assert response.text == "accepted"
    assert response.headers["cache-control"] == "no-store"


async def test_malformed_block_is_rejected() -> None:
    async with _client(_settings()) as client:
        response = await client.get(_url(block="bot-abc"))

    assert response.status_code == 400


async def test_missing_timestamp_returns_400() -> None:
    async with _client(_settings()) as client:
        response = await client.get(f"{PATH}?userid=123&block={BLOCK}&secret={SECRET}")

    assert response.status_code == 400


async def test_stale_timestamp_returns_400() -> None:
    stale = int((datetime.now(UTC) - timedelta(seconds=901)).timestamp())

    async with _client(_settings()) as client:
        response = await client.get(_url(ts=stale))

    assert response.status_code == 400


async def test_future_timestamp_beyond_skew_returns_400() -> None:
    future = int((datetime.now(UTC) + timedelta(seconds=61)).timestamp())

    async with _client(_settings()) as client:
        response = await client.get(_url(ts=future))

    assert response.status_code == 400


async def test_oversized_timestamp_is_rejected_without_overflow() -> None:
    async with _client(_settings()) as client:
        response = await client.get(_url(ts="9" * 11))

    assert response.status_code == 400


async def test_far_future_timestamp_is_rejected_as_stale_not_as_a_server_error() -> None:
    # Older code capped timestamps at 2**31-1 (January 2038) and reported the
    # oversized value as missing. Freshness, not the cap, must decide.
    async with _client(_settings()) as client:
        response = await client.get(_url(ts=2**31))

    assert response.status_code == 400
    assert response.text == "Bad request"


async def test_database_failure_returns_500_without_leaking_the_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recording = _RecordingLogger()
    monkeypatch.setattr(rewards_route, "logger", recording)
    monkeypatch.setattr(rewards_route, "session_scope", _fake_scope)

    async def _explode(*args: Any, **kwargs: Any) -> RewardGrantResult:
        raise RuntimeError(f"connect failed while using secret={SECRET}")

    monkeypatch.setattr(rewards_route, "grant_reward", _explode)

    async with _app_client(_settings()) as client:
        response = await client.get(_url())

    assert response.status_code == 500
    assert response.text == "Internal error"
    assert response.headers["cache-control"] == "no-store"
    errors = [call for call in recording.calls if call[0] == "error"]
    assert errors == [
        (
            "error",
            "reward_callback_failed",
            {"provider": "adsun", "error_type": "RuntimeError"},
        )
    ]
    assert all(call[0] != "exception" for call in recording.calls)
    assert all(SECRET not in repr(call) for call in recording.calls)


async def test_route_never_logs_the_callback_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recording = _RecordingLogger()
    monkeypatch.setattr(rewards_route, "logger", recording)

    async with _client(_settings()) as client:
        await client.get(_url(secret="leaked-secret-value"))

    assert recording.calls
    assert all("leaked-secret-value" not in repr(call) for call in recording.calls)
    assert all(SECRET not in repr(call) for call in recording.calls)


def test_uvicorn_access_log_is_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: dict[str, Any] = {}

    def _run(*args: Any, **kwargs: Any) -> None:
        recorded["args"] = args
        recorded["kwargs"] = kwargs

    monkeypatch.setattr(api_main.uvicorn, "run", _run)
    monkeypatch.setattr(api_main, "get_settings", lambda: _settings())

    api_main.main()

    assert recorded["kwargs"]["access_log"] is False
