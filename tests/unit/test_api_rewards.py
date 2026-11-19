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
ALIAS_PATH = "/api/v1/hooks/r1/cb"
CAPTURE_PATH = "/api/v1/rewards/adsun/capture"
ALIAS_CAPTURE_PATH = "/api/v1/hooks/r1/probe"


@pytest.fixture(autouse=True)
def _do_not_reconfigure_global_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("backend.api.app.configure_logging", lambda *args, **kwargs: None)


@pytest.fixture(autouse=True)
def _reset_capture_state() -> None:
    rewards_route._reset_capture_state()


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


def _url(*, path: str = PATH, **params: str | int) -> str:
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


@pytest.mark.parametrize("value", ["1", "true", "TRUE"])
async def test_test_callback_returns_200_without_processing(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    recording = _RecordingLogger()
    monkeypatch.setattr(rewards_route, "logger", recording)

    async with _client(_settings()) as client:
        response = await client.get(_url(test=value))

    assert response.status_code == 200
    assert response.text == '{"status":"test"}'
    assert response.headers["cache-control"] == "no-store"

    events = [call[2] for call in recording.calls if call[1] == "reward_callback_test"]
    assert len(events) == 1
    assert set(events[0]["params"]) == {"userid", "block", "secret", "ts", "test"}
    assert "values" not in events[0]
    assert all(SECRET not in repr(call) for call in recording.calls)


async def test_test_callback_with_a_bad_secret_returns_403() -> None:
    async with _client(_settings()) as client:
        response = await client.get(_url(test="1", secret="wrong-secret-value"))

    assert response.status_code == 403
    assert response.text == "Forbidden"


async def test_normal_callback_is_unaffected_by_the_test_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rewards_route, "session_scope", _fake_scope)
    calls: list[dict[str, Any]] = []

    async def _grant(*args: Any, **kwargs: Any) -> RewardGrantResult:
        calls.append(kwargs)
        return RewardGrantResult(status="accepted", credits_granted=1)

    monkeypatch.setattr(rewards_route, "grant_reward", _grant)

    async with _app_client(_settings()) as client:
        response = await client.get(_url())

    assert response.status_code == 200
    assert response.text == "accepted"
    assert len(calls) == 1


def test_uvicorn_access_log_is_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: dict[str, Any] = {}

    def _run(*args: Any, **kwargs: Any) -> None:
        recorded["args"] = args
        recorded["kwargs"] = kwargs

    monkeypatch.setattr(api_main.uvicorn, "run", _run)
    monkeypatch.setattr(api_main, "get_settings", lambda: _settings())

    api_main.main()

    assert recorded["kwargs"]["access_log"] is False


def _capture_url(
    *,
    path: str = CAPTURE_PATH,
    user_id: int = 12345,
    block: str = BLOCK,
    secret: str = SECRET,
    ts: int = 1_700_000_000,
    **extra: str,
) -> str:
    params = {
        "userid": str(user_id),
        "block": block,
        "secret": secret,
        "ts": str(ts),
        **extra,
    }
    query = "&".join(f"{key}={value}" for key, value in params.items())
    return f"{CAPTURE_PATH}?{query}"


async def test_capture_is_disabled_by_default() -> None:
    assert _settings().adsun_capture_enabled is False

    async with _client(_settings()) as client:
        response = await client.get(_capture_url())

    assert response.status_code == 404
    assert response.text == "Not found"


async def test_capture_is_hidden_in_production_even_when_enabled() -> None:
    async with _client(
        _settings(
            app_env="production",
            adsun_capture_enabled=True,
            telegram_bot_token="123456:test-token",
        )
    ) as client:
        response = await client.get(_capture_url())

    assert response.status_code == 404


async def test_capture_rejects_a_bad_secret() -> None:
    async with _client(_settings(adsun_capture_enabled=True)) as client:
        response = await client.get(_capture_url(secret="wrong-secret-value"))

    assert response.status_code == 403
    assert response.text == "Forbidden"


async def test_capture_logs_names_and_non_secret_values_and_fails_once_per_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recording = _RecordingLogger()
    monkeypatch.setattr(rewards_route, "logger", recording)

    async with _client(_settings(adsun_capture_enabled=True)) as client:
        first = await client.get(_capture_url(extra="hello"))
        second = await client.get(_capture_url(extra="hello"))
        other_user = await client.get(_capture_url(user_id=67890))
        other_block = await client.get(_capture_url(user_id=67890, block="50002"))
        retry_other_block = await client.get(_capture_url(user_id=67890, block="50002"))

    assert [first.status_code, second.status_code] == [500, 200]
    assert [other_user.status_code, other_block.status_code, retry_other_block.status_code] == [
        500,
        500,
        200,
    ]

    events = [call[2] for call in recording.calls if call[1] == "adsun_capture"]
    assert len(events) == 5

    first_event = events[0]
    assert set(first_event["params"]) == {"userid", "block", "secret", "ts", "extra"}
    assert first_event["values"] == {
        "userid": "12345",
        "block": BLOCK,
        "ts": "1700000000",
        "extra": "hello",
    }
    assert "secret" not in first_event["values"]
    assert SECRET not in repr(first_event)
    assert "wrong-secret-value" not in repr(first_event)
    assert first_event["received_at"]
    assert first_event["first_call"] is True

    assert [event["first_call"] for event in events] == [
        True,
        False,
        True,
        True,
        False,
    ]
    assert all(event["received_at"] for event in events)


async def test_capture_test_callback_returns_200_and_does_not_consume_first_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recording = _RecordingLogger()
    monkeypatch.setattr(rewards_route, "logger", recording)

    async with _client(_settings(adsun_capture_enabled=True)) as client:
        test_response = await client.get(_capture_url(test="1"))
        first = await client.get(_capture_url())
        second = await client.get(_capture_url())

    assert test_response.status_code == 200
    assert test_response.text == '{"status":"test"}'
    assert test_response.headers["cache-control"] == "no-store"
    assert [first.status_code, second.status_code] == [500, 200]

    capture_events = [call[2] for call in recording.calls if call[1] == "adsun_capture"]
    assert len(capture_events) == 3
    assert capture_events[0]["values"]["test"] == "1"
    assert capture_events[0]["first_call"] is False
    assert capture_events[1]["first_call"] is True
    assert capture_events[2]["first_call"] is False

    test_events = [call[2] for call in recording.calls if call[1] == "reward_callback_test"]
    assert len(test_events) == 1
    assert "test" in test_events[0]["params"]
    assert all(SECRET not in repr(call) for call in recording.calls)


async def test_alias_callback_rejects_a_bad_secret() -> None:
    async with _client(_settings()) as client:
        response = await client.get(_url(path=ALIAS_PATH, secret="wrong-secret-value"))

    assert response.status_code == 403
    assert response.text == "Forbidden"
    assert response.headers["cache-control"] == "no-store"


async def test_alias_callback_is_404_when_the_feature_is_disabled() -> None:
    async with _client(_settings(adsun_enabled=False)) as client:
        response = await client.get(_url(path=ALIAS_PATH))

    assert response.status_code == 404
    assert response.text == "Not found"


@pytest.mark.parametrize("value", ["1", "true"])
async def test_alias_test_callback_returns_200_without_granting(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    recording = _RecordingLogger()
    monkeypatch.setattr(rewards_route, "logger", recording)

    async def _must_not_grant(*args: Any, **kwargs: Any) -> RewardGrantResult:
        raise AssertionError("test callbacks must not reach the grant path")

    monkeypatch.setattr(rewards_route, "grant_reward", _must_not_grant)

    async with _client(_settings()) as client:
        response = await client.get(_url(path=ALIAS_PATH, test=value))

    assert response.status_code == 200
    assert response.text == '{"status":"test"}'
    assert response.headers["cache-control"] == "no-store"

    events = [call[2] for call in recording.calls if call[1] == "reward_callback_test"]
    assert len(events) == 1
    assert set(events[0]["params"]) == {"userid", "block", "secret", "ts", "test"}
    assert "values" not in events[0]
    assert all(SECRET not in repr(call) for call in recording.calls)


async def test_alias_capture_is_disabled_by_default() -> None:
    async with _client(_settings()) as client:
        response = await client.get(_capture_url(path=ALIAS_CAPTURE_PATH))

    assert response.status_code == 404
    assert response.text == "Not found"


async def test_alias_capture_is_hidden_in_production_even_when_enabled() -> None:
    async with _client(
        _settings(
            app_env="production",
            adsun_capture_enabled=True,
            telegram_bot_token="123456:test-token",
        )
    ) as client:
        response = await client.get(_capture_url(path=ALIAS_CAPTURE_PATH))

    assert response.status_code == 404


async def test_alias_capture_rejects_a_bad_secret() -> None:
    async with _client(_settings(adsun_capture_enabled=True)) as client:
        response = await client.get(
            _capture_url(path=ALIAS_CAPTURE_PATH, secret="wrong-secret-value")
        )

    assert response.status_code == 403
    assert response.text == "Forbidden"


async def test_alias_capture_fails_once_per_pair_then_succeeds() -> None:
    async with _client(_settings(adsun_capture_enabled=True)) as client:
        first = await client.get(_capture_url(path=ALIAS_CAPTURE_PATH))
        second = await client.get(_capture_url(path=ALIAS_CAPTURE_PATH))
        other_pair = await client.get(_capture_url(path=ALIAS_CAPTURE_PATH, user_id=67890))

    assert [first.status_code, second.status_code] == [500, 200]
    assert first.headers["cache-control"] == "no-store"
    assert second.text == "ok"
    assert other_pair.status_code == 500


async def test_alias_capture_test_callback_does_not_consume_first_call() -> None:
    async with _client(_settings(adsun_capture_enabled=True)) as client:
        test_response = await client.get(_capture_url(path=ALIAS_CAPTURE_PATH, test="1"))
        first = await client.get(_capture_url(path=ALIAS_CAPTURE_PATH))
        second = await client.get(_capture_url(path=ALIAS_CAPTURE_PATH))

    assert test_response.status_code == 200
    assert test_response.text == '{"status":"test"}'
    assert test_response.headers["cache-control"] == "no-store"
    assert [first.status_code, second.status_code] == [500, 200]


def test_alias_routes_reuse_the_original_handler_functions() -> None:
    original = {route.path: route.endpoint for route in rewards_route.router.routes}
    aliases = {route.path: route.endpoint for route in rewards_route.alias_router.routes}

    assert aliases[ALIAS_PATH] is original[PATH]
    assert aliases[ALIAS_CAPTURE_PATH] is original[CAPTURE_PATH]


def test_alias_routes_are_hidden_from_the_openapi_schema() -> None:
    schema_paths = create_app(_settings()).openapi()["paths"]

    assert ALIAS_PATH not in schema_paths
    assert ALIAS_CAPTURE_PATH not in schema_paths
    assert PATH in schema_paths
    assert CAPTURE_PATH not in schema_paths
