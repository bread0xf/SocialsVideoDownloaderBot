import pytest

from backend.core.errors import AppError, ErrorCode
from backend.downloads.state import JobStatus, is_active, is_terminal, transition


def test_valid_transition_returns_target_status() -> None:
    assert transition("queued", "extracting") is JobStatus.EXTRACTING


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("queued", "delivering"),
        ("processing", "extracting"),
        ("completed", "failed"),
        ("failed", "queued"),
        ("unknown", "queued"),
    ],
)
def test_invalid_transition_is_rejected(current: str, target: str) -> None:
    with pytest.raises(AppError) as exc_info:
        transition(current, target)

    assert exc_info.value.code == ErrorCode.INTERNAL_ERROR


def test_terminal_and_active_helpers() -> None:
    assert is_terminal("completed")
    assert not is_terminal("queued")
    assert is_active("delivering")
    assert not is_active("failed")
