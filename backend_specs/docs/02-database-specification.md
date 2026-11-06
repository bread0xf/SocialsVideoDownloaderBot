# 02 — Database Specification

## 1. Database rules

PostgreSQL is authoritative. Use SQLAlchemy 2.x async with `asyncpg`; Alembic owns schema evolution. UUID primary keys for internal entities. Telegram IDs are signed `BIGINT`. Store instants as timezone-aware UTC timestamps (`TIMESTAMPTZ`). Compute quota periods using `ZoneInfo("Africa/Lagos")`.

Never use Redis as the authoritative store for quota, reward balances, payments or subscriptions.

## 2. Core tables

The following is the logical baseline. Names may be adapted consistently during implementation; preserve semantics, constraints and auditability.

### `users`
- `id UUID PK`
- `telegram_user_id BIGINT NOT NULL UNIQUE`
- `username TEXT NULL`
- `first_name TEXT NULL`
- `last_name TEXT NULL`
- `language_code TEXT NULL`
- `is_blocked BOOLEAN NOT NULL DEFAULT FALSE`
- `created_at`, `updated_at TIMESTAMPTZ NOT NULL`
- `last_seen_at TIMESTAMPTZ NULL`

Telegram identity is the only MVP identity. Do not add email/password or social-platform account credentials.

### `plans`
- `id UUID PK`
- `code TEXT UNIQUE NOT NULL` (`free`, `premium`)
- `name TEXT NOT NULL`
- `max_resolution_p INTEGER NOT NULL`
- `daily_included_downloads INTEGER NULL`
- `priority INTEGER NOT NULL`
- `is_active BOOLEAN NOT NULL`
- `created_at`, `updated_at`

Free plan values: `max_resolution_p=480`, `daily_included_downloads=5`. Premium max resolution is 2160; Premium allowance remains unresolved and must be configuration/data-driven, not guessed.

### `subscriptions`
- `id UUID PK`
- `user_id UUID FK users`
- `plan_id UUID FK plans`
- `provider TEXT NOT NULL` (initial provider: `telegram_stars`)
- `provider_subscription_ref TEXT NULL`
- `status TEXT NOT NULL` (`pending`, `active`, `cancelled`, `expired`, `refunded`, `past_due` as applicable)
- `started_at TIMESTAMPTZ NULL`
- `paid_through TIMESTAMPTZ NULL`
- `cancelled_at TIMESTAMPTZ NULL`
- `created_at`, `updated_at`
- Index `(user_id, status, paid_through)`.
Access is active while status permits access and `now_utc <= paid_through`; expiry is after `paid_through`. Define and test exact inclusive boundary once implementation chooses precision.

### `payments`
- `id UUID PK`
- `user_id UUID FK users`
- `subscription_id UUID NULL FK subscriptions`
- `provider TEXT NOT NULL`
- `provider_payment_id TEXT NOT NULL`
- `currency TEXT NOT NULL`
- `amount_minor BIGINT NOT NULL CHECK amount_minor >= 0`
- `status TEXT NOT NULL`
- `payload_hash TEXT NULL`
- `paid_at TIMESTAMPTZ NULL`
- `created_at TIMESTAMPTZ NOT NULL`
- Unique `(provider, provider_payment_id)`.
Store immutable provider event/payment facts. Do not store raw sensitive payload unless necessary and protected.

### `download_jobs`
- `id UUID PK`
- `user_id UUID FK users`
- `platform TEXT NOT NULL`
- `submitted_url TEXT NOT NULL` (consider encrypted/redacted storage policy; logs must not expose it)
- `canonical_url TEXT NULL`
- `media_key TEXT NULL`
- `status TEXT NOT NULL`
- `stage TEXT NULL`
- `requested_at`, `started_at`, `completed_at`, `failed_at TIMESTAMPTZ NULL`
- `attempt_count INTEGER NOT NULL DEFAULT 0`
- `idempotency_key TEXT NULL`
- `error_code TEXT NULL`
- `error_detail_safe TEXT NULL`
- `selected_resolution_p INTEGER NULL`
- `output_bytes BIGINT NULL`
- `cache_entry_id UUID NULL`
- Unique `(user_id, idempotency_key)` where key is not null.
Statuses: `received`, `validating`, `authorizing`, `queued`, `extracting`, `selecting_format`, `processing`, `delivering`, `completed`, `rejected`, `failed`, `cancelled`.

### `usage_reservations`
- `id UUID PK`
- `user_id UUID FK users`
- `download_job_id UUID FK download_jobs UNIQUE`
- `quota_period_start TIMESTAMPTZ NOT NULL`
- `source TEXT NOT NULL` (`included`, `reward_credit`, later `premium_included`)
- `status TEXT NOT NULL` (`reserved`, `committed`, `released`)
- `reserved_at`, `committed_at`, `released_at TIMESTAMPTZ NULL`
- `created_at TIMESTAMPTZ NOT NULL`

### `usage_ledger`
Append-only:
- `id UUID PK`
- `user_id UUID FK users`
- `download_job_id UUID NULL FK download_jobs`
- `entry_type TEXT NOT NULL` (`download_committed`, `reservation_released`, `adjustment`)
- `source TEXT NOT NULL` (`included`, `reward_credit`, `premium_included`, `admin_adjustment`)
- `quantity INTEGER NOT NULL` (signed adjustments allowed)
- `quota_period_start TIMESTAMPTZ NULL`
- `idempotency_key TEXT UNIQUE NOT NULL`
- `created_at TIMESTAMPTZ NOT NULL`
Do not update/delete ledger entries. Correct with compensating entries.

### `reward_sessions`
- `id UUID PK`
- `user_id UUID FK users`
- `provider TEXT NOT NULL`
- `provider_session_ref TEXT NULL`
- `status TEXT NOT NULL` (`created`, `started`, `verified`, `rejected`, `expired`)
- `created_at`, `expires_at TIMESTAMPTZ NOT NULL`
- `verified_at TIMESTAMPTZ NULL`

### `reward_ledger`
Append-only:
- `id UUID PK`
- `user_id UUID FK users`
- `reward_session_id UUID NULL FK reward_sessions`
- `provider TEXT NOT NULL`
- `provider_transaction_id TEXT NOT NULL`
- `quantity INTEGER NOT NULL CHECK quantity > 0`
- `entry_type TEXT NOT NULL` (`grant`, `consume`, `expire`, `adjustment`)
- `expires_at TIMESTAMPTZ NULL` (expiry policy unresolved)
- `idempotency_key TEXT UNIQUE NOT NULL`
- `created_at TIMESTAMPTZ NOT NULL`
- Unique `(provider, provider_transaction_id)` for grant events.

### `media_cache`
- `id UUID PK`
- `media_key TEXT UNIQUE NOT NULL`
- `platform TEXT NOT NULL`
- `source_identity_hash TEXT NOT NULL`
- `output_profile TEXT NOT NULL`
- `processing_version TEXT NOT NULL`
- `storage_path TEXT NOT NULL`
- `file_size_bytes BIGINT NOT NULL`
- `mime_type TEXT NULL`
- `telegram_file_id TEXT NULL`
- `created_at`, `expires_at TIMESTAMPTZ NOT NULL`
- `last_accessed_at TIMESTAMPTZ NULL`
- `status TEXT NOT NULL` (`ready`, `deleting`, `deleted`, `invalid`)
Enforce a maximum retention of 24 hours from creation. File existence must be reconciled with DB state.

### `outbox_events`
- `id UUID PK`
- `event_type TEXT NOT NULL`
- `aggregate_type TEXT NOT NULL`
- `aggregate_id UUID NOT NULL`
- `payload JSONB NOT NULL`
- `created_at TIMESTAMPTZ NOT NULL`
- `available_at TIMESTAMPTZ NOT NULL`
- `published_at TIMESTAMPTZ NULL`
- `attempt_count INTEGER NOT NULL DEFAULT 0`
- `last_error_code TEXT NULL`
Index unpublished rows by `(published_at, available_at)`.

### `platform_registry`
- `id UUID PK`
- `platform_key TEXT UNIQUE NOT NULL`
- `display_name TEXT NOT NULL`
- `status TEXT NOT NULL`
- `supported_content_types JSONB NOT NULL`
- `last_verified_at TIMESTAMPTZ NULL`
- `created_at`, `updated_at`

### `sponsor_placements` (later phase)
- `id UUID PK`
- `name TEXT NOT NULL`
- `content TEXT NOT NULL`
- `targeting JSONB NULL`
- `starts_at`, `ends_at TIMESTAMPTZ NULL`
- `is_active BOOLEAN NOT NULL`
Do not build campaign billing/analytics until separately specified.

## 3. Indexes and constraints

At minimum:
- Unique Telegram user ID.
- Unique provider payment ID per provider.
- Unique provider reward transaction ID per provider.
- Unique idempotency keys for ledger and callback operations.
- Unique reservation per download job.
- Index jobs by `(status, requested_at)` and `(user_id, requested_at DESC)`.
- Index cache by `expires_at` and status.
- Index subscriptions by user/status/paid-through.
- Foreign keys with deliberate deletion policy. Prefer soft deactivation or restricted deletion where ledger/audit references exist.
- CHECK constraints for nonnegative byte counts, valid quantities and supported enum-like values where appropriate.

## 4. Atomic quota reservation

Reservation must be transactionally safe under concurrent requests.

Algorithm:
1. Begin transaction and lock the user's quota/account row or acquire a transaction-scoped advisory lock keyed by user UUID.
2. Calculate current quota period using `Africa/Lagos`: local midnight at start of current day converted to UTC.
3. Resolve entitlement from verified subscription state.
4. Count committed included usage and active reservations for that period.
5. If included allowance remains, reserve included allowance.
6. Otherwise, if valid reward balance remains, reserve one reward credit (oldest-expiring-first if expiry is enabled).
7. Otherwise reject with `QUOTA_EXHAUSTED`.
8. Insert reservation and corresponding durable state atomically.
9. Commit before queue dispatch; outbox event is written in the same transaction.

A reservation must not count as a successful download in the immutable usage ledger until delivery succeeds. A separate reservation record tracks in-flight capacity. Avoid double-counting committed reservations and ledger entries in balance queries.

## 5. Commit/release semantics

- On successful Telegram delivery: atomically mark reservation committed and append exactly one usage ledger entry; consume reward ledger credit if source was rewarded credit.
- On definitive failure/rejection: mark reservation released; no successful-download charge.
- On transient failure: retain reservation while retrying, within bounded job lifetime; release on terminal failure.
- Idempotency key should be derived from the job and operation (`download:{job_id}:commit`, `download:{job_id}:release`).
- Reconciliation job detects stale reservations and jobs; do not release active work prematurely.

## 6. Lagos quota period

`quota_period_start` is local midnight in `Africa/Lagos` converted to UTC. Compute the next boundary independently. Do not use server-local timezone or fixed UTC midnight. All persisted timestamps remain UTC.

## 7. Retention

A scheduled cleanup process deletes cache files whose `expires_at <= now_utc`, then updates cache state. Also reconcile orphan files and missing files. Per-job temporary workspaces are removed after completion/definitive failure. Never delete ledger/payment records as part of media cleanup.
