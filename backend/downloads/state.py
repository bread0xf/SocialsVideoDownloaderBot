from enum import StrEnum

from backend.core.errors import AppError, ErrorCode

TERMINAL_STATUSES = frozenset({"completed", "rejected", "failed", "cancelled"})
ACTIVE_STATUSES = frozenset(
    {
        "received",
        "validating",
        "authorizing",
        "queued",
        "extracting",
        "selecting_format",
        "processing",
        "delivering",
    }
)


class JobStatus(StrEnum):
    RECEIVED = "received"
    VALIDATING = "validating"
    AUTHORIZING = "authorizing"
    QUEUED = "queued"
    EXTRACTING = "extracting"
    SELECTING_FORMAT = "selecting_format"
    PROCESSING = "processing"
    DELIVERING = "delivering"
    COMPLETED = "completed"
    REJECTED = "rejected"
    FAILED = "failed"
    CANCELLED = "cancelled"


_ALLOWED_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.RECEIVED: frozenset({JobStatus.VALIDATING, JobStatus.REJECTED, JobStatus.FAILED}),
    JobStatus.VALIDATING: frozenset({JobStatus.AUTHORIZING, JobStatus.REJECTED, JobStatus.FAILED}),
    JobStatus.AUTHORIZING: frozenset({JobStatus.QUEUED, JobStatus.REJECTED, JobStatus.FAILED}),
    JobStatus.QUEUED: frozenset({JobStatus.EXTRACTING, JobStatus.CANCELLED, JobStatus.FAILED}),
    JobStatus.EXTRACTING: frozenset(
        {JobStatus.SELECTING_FORMAT, JobStatus.QUEUED, JobStatus.FAILED, JobStatus.CANCELLED}
    ),
    JobStatus.SELECTING_FORMAT: frozenset(
        {JobStatus.PROCESSING, JobStatus.QUEUED, JobStatus.FAILED, JobStatus.CANCELLED}
    ),
    JobStatus.PROCESSING: frozenset(
        {JobStatus.DELIVERING, JobStatus.QUEUED, JobStatus.FAILED, JobStatus.CANCELLED}
    ),
    JobStatus.DELIVERING: frozenset(
        {JobStatus.COMPLETED, JobStatus.QUEUED, JobStatus.FAILED, JobStatus.CANCELLED}
    ),
    JobStatus.COMPLETED: frozenset(),
    JobStatus.REJECTED: frozenset(),
    JobStatus.FAILED: frozenset(),
    JobStatus.CANCELLED: frozenset(),
}


def is_terminal(status: str) -> bool:
    return status in TERMINAL_STATUSES


def is_active(status: str) -> bool:
    return status in ACTIVE_STATUSES


def transition(current: str, new: str) -> JobStatus:
    try:
        current_status = JobStatus(current)
        new_status = JobStatus(new)
    except ValueError as exc:
        raise AppError(ErrorCode.INTERNAL_ERROR, "Invalid job state.") from exc
    if new_status not in _ALLOWED_TRANSITIONS[current_status]:
        raise AppError(ErrorCode.INTERNAL_ERROR, "Invalid job state transition.")
    return new_status
