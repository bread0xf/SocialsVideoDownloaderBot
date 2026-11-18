# Database Design

PostgreSQL is the durable source of truth. This document describes the **implemented** schema. `backend/database/models.py` and the initial Alembic migration are authoritative; `backend_specs/docs/02-database-specification.md` remains the frozen target specification.

## Implemented tables

### `users`
- `id` UUID primary key
- `telegram_user_id` BIGINT, unique and indexed
- `username`, `first_name`, `last_name`, `language_code` (nullable text)
- `is_blocked` boolean, default false
- `created_at`, `updated_at`, `last_seen_at`

### `plans`
- `id` UUID primary key
- `code` varchar(32), unique
- `name`, `max_resolution_p`, `daily_included_downloads` (nullable), `priority`
- `is_active`, `created_at`, `updated_at`
- Check: `max_resolution_p > 0`
- Seeded rows: `free`, `premium`

### `subscriptions`
- `id` UUID primary key
- `user_id` → `users.id` (RESTRICT), `plan_id` → `plans.id` (RESTRICT)
- `provider` varchar(64), `provider_subscription_ref` text, `status` varchar(32)
- `started_at`, `paid_through`, `cancelled_at`, `created_at`, `updated_at`
- Index: `(user_id, status, paid_through)`
- Entitlement uses `paid_through`; an expired subscription falls back to the Free plan.

### `download_jobs`
- `id` UUID primary key
- `user_id` → `users.id` (RESTRICT)
- `platform` varchar(32), `submitted_url`, `canonical_url`, `media_key`
- `status` varchar(32), `stage` varchar(32) nullable
- `requested_at`, `started_at`, `completed_at`, `failed_at`
- `attempt_count` (≥ 0), `idempotency_key`, `error_code`, `error_detail_safe`
- `selected_resolution_p`, `output_bytes`
- `cache_entry_id` → `media_cache.id` (SET NULL)
- Unique partial index: `(user_id, idempotency_key)` where `idempotency_key IS NOT NULL`
- Indexes: `(status, requested_at)`, `(user_id, requested_at)`

### `usage_reservations`
- `id` UUID primary key
- `user_id` → `users.id` (RESTRICT)
- `download_job_id` → `download_jobs.id` (RESTRICT), unique
- `quota_period_start`, `source` varchar(32), `status` varchar(32)
- `reward_ledger_id` → `usage_ledger.id` (RESTRICT, nullable); set only for `source = 'reward_credit'`
- `reserved_at`, `committed_at`, `released_at`, `created_at`
- Index: `(user_id, quota_period_start, status)`
- Partial unique index: `(reward_ledger_id)` where `reward_ledger_id IS NOT NULL AND status <> 'released'` — one live reservation per credit
- Check: `source <> 'reward_credit' OR reward_ledger_id IS NOT NULL`
- One reservation per job; commit only after successful delivery, release on terminal failure.

### `usage_ledger`
- `id` UUID primary key
- `user_id` → `users.id` (RESTRICT), `download_job_id` → `download_jobs.id` (RESTRICT, nullable)
- `entry_type` varchar(32), `source` varchar(32), `quantity` integer
- `quota_period_start` nullable, `expires_at` nullable, `idempotency_key` text unique, `created_at`
- Indexes: `(user_id, quota_period_start, source)`, `(user_id, created_at)`, `(user_id, entry_type, created_at)`
- Append-only audit trail for reservations, commits, releases and reward grants.
- Reward credits are `entry_type = 'reward_granted'`, `source = 'reward_credit'`, `quantity = 1`, with `expires_at` from `REWARD_CREDIT_EXPIRY`. This folds the proposed `reward_ledger` into the existing ledger rather than adding a second table; the frozen `backend_specs/` allows consistent name adaptation while preserving semantics.

### `reward_events`
- `id` UUID primary key
- `provider` varchar(32), `provider_transaction_id` text
- `user_id` → `users.id` (RESTRICT, nullable when the Telegram account is unknown)
- `telegram_user_id` BIGINT, `block_id` varchar(32) nullable, `provider_event_at` nullable
- `status` varchar(32): `pending`, `accepted`, `capped`, `unknown_user`, `blocked`, `premium_ineligible`, `no_session`, `rejected`
- `reason_code` varchar(64) nullable, `credits_granted` integer (≥ 0), `expires_at` nullable
- `received_at`, `processed_at` nullable
- Unique index: `(provider, provider_transaction_id)` — the replay guard for provider retries
- Indexes: `(telegram_user_id, received_at)`, `(user_id, received_at)`
- Written in the same transaction as the credit grant, so a rollback leaves no claim and a retry can succeed.

### `reward_sessions`
- `id` UUID primary key
- `user_id` → `users.id` (RESTRICT)
- `provider` varchar(32), `block` varchar(32), `status` varchar(32): `pending`, `redeemed`, `expired`
- `created_at`, `expires_at` timestamptz
- `redeemed_event_id` → `reward_events.id` (SET NULL, nullable)
- Partial unique index: `(user_id, provider, block)` where `status = 'pending'` — at most one live ad session per user, provider and block
- Index: `(status, expires_at)` for TTL cleanup
- The pending row is the ad cooldown. A callback redeems it in the same transaction as the credit grant; a callback with no pending row returns `no_session` and grants nothing. `REWARD_SESSION_TTL_SECONDS` bounds how long a user can be blocked.

### `media_cache`
- `id` UUID primary key
- `media_key` text unique
- `platform` varchar(32), `source_identity_hash`, `title`, `uploader`, `output_profile`, `processing_version`
- `storage_path`, `file_size_bytes` (≥ 0), `mime_type`, `telegram_file_id`
- `created_at`, `expires_at`, `last_accessed_at`, `status`
- Index: `(expires_at, status)`

### `outbox_events`
- `id` UUID primary key
- `event_type` varchar(64), `aggregate_type` varchar(64), `aggregate_id` UUID
- `payload` JSONB
- `created_at`, `available_at`, `published_at`, `attempt_count`, `last_error_code`
- Index: `(published_at, available_at)`
- Written in the same transaction as the job; the ARQ worker dispatches unpublished rows.

### `platform_registry`
- `id` UUID primary key
- `platform_key` varchar(32) unique, `display_name`, `status` varchar(32)
- `supported_content_types` JSONB array
- `last_verified_at`, `created_at`, `updated_at`
- Seeded rows: `tiktok`, `instagram`, `youtube`, `facebook`

## Quota accounting

Quota is derived from the append-only ledger under a per-user PostgreSQL advisory lock, not from a mutable counter. Within one transaction the service:

1. Locks the user's quota scope.
2. Counts committed and reserved entries for the active `Africa/Lagos` quota period.
3. Inserts a reservation once per job.
4. Rejects the request if the allowance is exhausted, preventing concurrent overspend.
5. Commits the reservation after confirmed delivery or releases it on terminal failure.

When the included allowance is exhausted, `reserve_quota` first tries to reserve the oldest expiring usable reward credit (`entry_type = 'reward_granted'`, unexpired, not held by a live reservation). Reward reservations use `source = 'reward_credit'`; a released reservation makes the credit usable again, a committed one consumes it. Reward grants do not count towards included usage, which filters on the entitlement's `quota_source`.

Idempotency keys make repeated update, payment and reward handling safe; see `backend/usage/service.py`, `backend/rewards/service.py` and `backend/downloads/service.py`.

## Future target, not implemented

The frozen specification also proposes billing and monetization tables that have no models or migrations today: `payments`, `reward_transactions`, `sponsor_campaigns`, `ad_impressions`. Do not assume they exist. Add migrations together with the corresponding feature and tests. The Adsun slice implements `reward_events` as the callback replay guard, `reward_sessions` as the ad cooldown/redeem binding, and folds reward credits into `usage_ledger`; the proposed `reward_ledger` and `reward_claims` names therefore do not exist as separate tables.

## Data lifecycle

- Media cache expires after 24 hours from creation (locked maximum) and is also bounded by `MEDIA_CACHE_MAX_BYTES`.
- Job workspaces are temporary and deleted after processing.
- Full source URLs are stored on the job for support and debugging; do not add them to logs.
- Retention for completed jobs, billing records and logs must be defined before production launch.
- A user-data deletion workflow is required before production; see `docs/architecture/security-architecture.md`.
