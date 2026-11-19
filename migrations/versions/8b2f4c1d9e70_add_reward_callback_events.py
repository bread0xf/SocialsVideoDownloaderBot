"""add Adsun reward callback events and credit reservations

Revision ID: 8b2f4c1d9e70
Revises: 4270b8fe5cc0
Create Date: 2026-11-17 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8b2f4c1d9e70"
down_revision: str | None = "4270b8fe5cc0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "usage_ledger",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_usage_ledger_user_entry_type_created_at",
        "usage_ledger",
        ["user_id", "entry_type", "created_at"],
        unique=False,
    )

    op.add_column(
        "usage_reservations",
        sa.Column("reward_ledger_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_usage_reservations_reward_ledger_id_usage_ledger"),
        "usage_reservations",
        "usage_ledger",
        ["reward_ledger_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "uq_usage_reservations_reward_ledger_active",
        "usage_reservations",
        ["reward_ledger_id"],
        unique=True,
        postgresql_where=sa.text("reward_ledger_id IS NOT NULL AND status <> 'released'"),
    )
    op.create_check_constraint(
        op.f("ck_usage_reservations_usage_reservations_reward_credit_link"),
        "usage_reservations",
        "source <> 'reward_credit' OR reward_ledger_id IS NOT NULL",
    )

    op.create_table(
        "reward_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_transaction_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("block_id", sa.String(length=32), nullable=True),
        sa.Column("provider_event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=True),
        sa.Column("credits_granted", sa.Integer(), server_default="0", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_reward_events_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reward_events")),
        sa.CheckConstraint(
            "credits_granted >= 0",
            name=op.f("ck_reward_events_reward_events_credits_nonnegative"),
        ),
        sa.CheckConstraint(
            "status IN ("
            "'pending', 'accepted', 'capped', 'unknown_user', 'blocked', "
            "'premium_ineligible', 'rejected'"
            ")",
            name=op.f("ck_reward_events_reward_events_status_valid"),
        ),
    )
    op.create_index(
        "uq_reward_events_provider_transaction",
        "reward_events",
        ["provider", "provider_transaction_id"],
        unique=True,
    )
    op.create_index(
        "ix_reward_events_telegram_user_received",
        "reward_events",
        ["telegram_user_id", "received_at"],
        unique=False,
    )
    op.create_index(
        "ix_reward_events_user_received",
        "reward_events",
        ["user_id", "received_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_reward_events_user_received", table_name="reward_events")
    op.drop_index("ix_reward_events_telegram_user_received", table_name="reward_events")
    op.drop_index("uq_reward_events_provider_transaction", table_name="reward_events")
    op.drop_table("reward_events")

    op.drop_constraint(
        op.f("ck_usage_reservations_usage_reservations_reward_credit_link"),
        "usage_reservations",
        type_="check",
    )
    op.drop_index("uq_usage_reservations_reward_ledger_active", table_name="usage_reservations")
    op.drop_constraint(
        op.f("fk_usage_reservations_reward_ledger_id_usage_ledger"),
        "usage_reservations",
        type_="foreignkey",
    )
    op.drop_column("usage_reservations", "reward_ledger_id")

    op.drop_index("ix_usage_ledger_user_entry_type_created_at", table_name="usage_ledger")
    op.drop_column("usage_ledger", "expires_at")
