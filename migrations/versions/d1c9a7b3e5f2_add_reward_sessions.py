"""add reward sessions for Adsun ad cooldown

Revision ID: d1c9a7b3e5f2
Revises: 8b2f4c1d9e70
Create Date: 2026-11-18 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d1c9a7b3e5f2"
down_revision: str | None = "8b2f4c1d9e70"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_STATUSES = (
    "status IN ("
    "'pending', 'accepted', 'capped', 'unknown_user', 'blocked', "
    "'premium_ineligible', 'rejected'"
    ")"
)
_NEW_STATUSES = (
    "status IN ("
    "'pending', 'accepted', 'capped', 'unknown_user', 'blocked', "
    "'premium_ineligible', 'no_session', 'rejected'"
    ")"
)


def upgrade() -> None:
    op.create_table(
        "reward_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("block", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("redeemed_event_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_reward_sessions_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["redeemed_event_id"],
            ["reward_events.id"],
            name=op.f("fk_reward_sessions_redeemed_event_id_reward_events"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reward_sessions")),
        sa.CheckConstraint(
            "status IN ('pending', 'redeemed', 'expired')",
            name=op.f("ck_reward_sessions_reward_sessions_status_valid"),
        ),
    )
    op.create_index(
        "uq_reward_sessions_pending",
        "reward_sessions",
        ["user_id", "provider", "block"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_reward_sessions_status_expires_at",
        "reward_sessions",
        ["status", "expires_at"],
        unique=False,
    )

    op.drop_constraint(
        op.f("ck_reward_events_reward_events_status_valid"),
        "reward_events",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_reward_events_reward_events_status_valid"),
        "reward_events",
        _NEW_STATUSES,
    )


def downgrade() -> None:
    # The old constraint cannot represent no_session claims.
    op.execute("UPDATE reward_events SET status = 'rejected' WHERE status = 'no_session'")
    op.drop_constraint(
        op.f("ck_reward_events_reward_events_status_valid"),
        "reward_events",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_reward_events_reward_events_status_valid"),
        "reward_events",
        _OLD_STATUSES,
    )

    op.drop_index("ix_reward_sessions_status_expires_at", table_name="reward_sessions")
    op.drop_index("uq_reward_sessions_pending", table_name="reward_sessions")
    op.drop_table("reward_sessions")
