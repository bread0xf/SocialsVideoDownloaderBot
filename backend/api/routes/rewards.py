from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

import structlog
from adsun import parse_reward_callback, verify_secret
from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

from backend.ads.block import normalise_block_id
from backend.core.config import Settings
from backend.database.session import session_scope
from backend.rewards.service import grant_reward

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/rewards", tags=["rewards"])

# Telegram user IDs are signed 64-bit integers.
_MAX_TELEGRAM_USER_ID = 2**63 - 1
# Unix seconds stay 10 digits until 2286. Freshness, not an arbitrary 2038 cap,
# decides whether a timestamp is acceptable.
_MAX_TIMESTAMP_DIGITS = 10

_TIMESTAMP_PARAMS = ("ts", "timestamp")


def _first_value(query: Mapping[str, str], *names: str) -> str:
    """Return the first non-empty value for any accepted parameter name."""
    for name in names:
        value = query.get(name)
        if value:
            return value
    return ""


def _parse_timestamp(query: Mapping[str, str]) -> int | None:
    raw = _first_value(query, *_TIMESTAMP_PARAMS)
    if not raw or not raw.isascii() or not raw.isdigit():
        return None
    if len(raw) > _MAX_TIMESTAMP_DIGITS:
        return None
    value = int(raw)
    if value <= 0:
        return None
    return value


def _plain(body: str, *, status_code: int) -> PlainTextResponse:
    # The URL carries the shared secret; a cached error or success body could
    # replay a decision outside the freshness window.
    return PlainTextResponse(
        body,
        status_code=status_code,
        headers={"Cache-Control": "no-store"},
    )


def _reject(reason: str, *, status_code: int, body: str) -> PlainTextResponse:
    # Only the stable reason code is logged. Never the query string or URL: it
    # carries the shared secret. An unconfigured endpoint is not an incident, so
    # do not let unauthenticated probes flood the warning stream.
    if reason in {"not_configured", "capture_disabled"}:
        logger.debug("reward_callback_rejected", provider="adsun", reason=reason)
    else:
        logger.warning("reward_callback_rejected", provider="adsun", reason=reason)
    return _plain(body, status_code=status_code)


# TEMPORARY staging capture state. In-process only: the first authenticated
# request per (userid, block) fails with 500 and later ones succeed, so Adsun's
# retry cadence can be observed. Remove this route before production.
_CAPTURED_KEYS: set[tuple[str, str]] = set()
_CAPTURE_SECRET_PARAMS = frozenset({"secret", "token", "api_key", "apikey", "authorization"})


def _is_secret_param(name: str) -> bool:
    lowered = name.lower()
    return lowered in _CAPTURE_SECRET_PARAMS or "secret" in lowered or "token" in lowered


def _reset_capture_state() -> None:
    """Test helper for the process-local capture state."""
    _CAPTURED_KEYS.clear()


@router.get("/adsun/capture", response_class=PlainTextResponse, include_in_schema=False)
async def adsun_capture(request: Request) -> PlainTextResponse:
    """TEMPORARY staging-only probe: log parameter names and retry behaviour.

    Must be removed before production. The query string carries the shared
    secret, so only parameter names and non-secret values are logged.
    """
    settings: Settings = request.app.state.settings
    if (
        not settings.adsun_capture_enabled
        or settings.app_env == "production"
        or not settings.adsun_callback_configured
    ):
        return _reject("capture_disabled", status_code=404, body="Not found")

    query = request.query_params
    received_secret = query.get("secret", "")
    if not verify_secret(received_secret, settings.adsun_reward_secret_value):
        return _reject("bad_secret", status_code=403, body="Forbidden")

    received_at = datetime.now(UTC)
    user_id = query.get("userid") or query.get("user") or ""
    block = query.get("block") or ""
    key = (user_id, block)
    first_call = key not in _CAPTURED_KEYS
    if first_call:
        _CAPTURED_KEYS.add(key)

    logger.info(
        "adsun_capture",
        provider="adsun",
        params=list(query.keys()),
        values={name: value for name, value in query.items() if not _is_secret_param(name)},
        received_at=received_at.isoformat(),
        first_call=first_call,
    )

    # Fail the first attempt per key so the provider retries, then succeed.
    if first_call:
        return _plain("Internal error", status_code=500)
    return _plain("ok", status_code=200)


@router.get("/adsun/callback", response_class=PlainTextResponse)
async def adsun_reward_callback(request: Request) -> PlainTextResponse:
    """Process an Adsun server-verified reward callback.

    Adsun retries 5xx and network failures, so every business rejection returns
    200 with a status body. Only a malformed, unauthenticated or unexpected
    request gets a non-2xx response.
    """
    settings: Settings = request.app.state.settings
    if not settings.adsun_callback_configured:
        return _reject("not_configured", status_code=404, body="Not found")

    query = request.query_params
    received_secret = query.get("secret", "")
    if not verify_secret(received_secret, settings.adsun_reward_secret_value):
        return _reject("bad_secret", status_code=403, body="Forbidden")

    parsed = parse_reward_callback(query)
    if parsed is None:
        return _reject("malformed", status_code=400, body="Bad request")

    if not parsed.user_id.isascii() or not parsed.user_id.isdigit():
        return _reject("malformed_user", status_code=400, body="Bad request")
    telegram_user_id = int(parsed.user_id)
    if not 0 < telegram_user_id <= _MAX_TELEGRAM_USER_ID:
        return _reject("malformed_user", status_code=400, body="Bad request")

    try:
        block_id = normalise_block_id(parsed.block_id)
    except ValueError:
        return _reject("malformed_block", status_code=400, body="Bad request")
    if not block_id or block_id != settings.adsun_block_id:
        return _reject("block_mismatch", status_code=400, body="Bad request")

    timestamp = _parse_timestamp(query)
    if timestamp is None:
        return _reject("missing_timestamp", status_code=400, body="Bad request")

    now = datetime.now(UTC)
    event_at = datetime.fromtimestamp(timestamp, tz=UTC)
    earliest = now - timedelta(seconds=settings.adsun_callback_max_age_seconds)
    latest = now + timedelta(seconds=settings.adsun_callback_future_skew_seconds)
    if not earliest <= event_at <= latest:
        return _reject("stale_timestamp", status_code=400, body="Bad request")

    try:
        async with session_scope(request.app.state.session_factory) as session:
            result = await grant_reward(
                session,
                telegram_user_id=telegram_user_id,
                block_id=block_id,
                event_at=event_at,
                now=now,
                settings=settings,
            )
    except Exception as exc:
        # Let Adsun retry: the unique claim key makes a retry safe. Logging the
        # exception object (or a traceback) risks echoing locals/headers that
        # contain the callback secret, so record only the error class.
        logger.error(
            "reward_callback_failed",
            provider="adsun",
            error_type=type(exc).__name__,
        )
        return _plain("Internal error", status_code=500)

    logger.info("reward_callback_processed", provider="adsun", status=result.status)
    return _plain(result.status, status_code=200)
