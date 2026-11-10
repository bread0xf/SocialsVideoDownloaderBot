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
- `reserved_at`, `committed_at`, `released_at`, `created_at`
- Index: `(user_id, quota_period_start, status)`
- One reservation per job; commit only after successful delivery, release on terminal failure.

### `usage_ledger`
- `id` UUID primary key
- `user_id` → `users.id` (RESTRICT), `download_job_id` → `download_jobs.id` (RESTRICT, nullable)
- `entry_type` varchar(32), `source` varchar(32), `quantity` integer
- `quota_period_start` nullable, `idempotency_key` text unique, `created_at`
- Indexes: `(user_id, quota_period_start, source)`, `(user_id, created_at)`
- Append-only audit trail for reservations, commits and releases.

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

Idempotency keys make repeated update, payment and reward handling safe; see `backend/usage/service.py` and `backend/downloads/service.py`.

## Future target, not implemented

The frozen specification also proposes billing and monetization tables that have no models or migrations today: `payments`, `reward_sessions`, `reward_transactions`, `sponsor_campaigns`, `ad_impressions`. Do not assume they exist. Add migrations together with the corresponding feature and tests.

## Data lifecycle

- Media cache expires after 24 hours from creation (locked maximum) and is also bounded by `MEDIA_CACHE_MAX_BYTES`.
- Job workspaces are temporary and deleted after processing.
- Full source URLs are stored on the job for support and debugging; do not add them to logs.
- Retention for completed jobs, billing records and logs must be defined before production launch.
- A user-data deletion workflow is required before production; see `docs/architecture/security-architecture.md`.
