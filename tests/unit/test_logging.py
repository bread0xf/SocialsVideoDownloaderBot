import logging

from backend.core.logging import configure_logging


def test_http_client_loggers_do_not_emit_token_bearing_urls_at_info() -> None:
    configure_logging("DEBUG")

    for name in ("httpx", "httpcore"):
        assert logging.getLogger(name).getEffectiveLevel() >= logging.WARNING
