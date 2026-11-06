import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.models import OutboxEvent

EVENT_DOWNLOAD_REQUESTED = "download.requested"


def enqueue_download_requested(
    session: AsyncSession,
    job_id: uuid.UUID,
    *,
    now: datetime | None = None,
    available_at: datetime | None = None,
) -> OutboxEvent:
    now = now or datetime.now(UTC)
    event = OutboxEvent(
        id=uuid.uuid4(),
        event_type=EVENT_DOWNLOAD_REQUESTED,
        aggregate_type="download_job",
        aggregate_id=job_id,
        payload={"job_id": str(job_id)},
        created_at=now,
        available_at=available_at or now,
    )
    session.add(event)
    return event
