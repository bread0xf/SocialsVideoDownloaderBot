# Database Design

PostgreSQL is the durable source of truth. This is a logical schema proposal; agents should convert it into normalized SQLAlchemy models and Alembic migrations.

## Core tables

### `users`
- `id` UUID primary key
- `telegram_user_id` BIGINT unique, indexed
- `created_at`, `updated_at`
- `status` (active/limited/blocked)
- Minimal profile fields only when required

### `plans`
- `id`, `code` unique, `name`
- `daily_download_limit`
- `max_height`
- `processing_priority`
- `sponsor_free`
- `reward_eligible`
- `active`

### `subscriptions`
- `id`, `user_id`, `plan_id`
- `status` (pending/active/past_due/cancelled/expired/refunded)
- `provider`, `provider_subscription_ref`
- `started_at`, `current_period_start`, `current_period_end`, `cancelled_at`
- Unique provider reference where applicable

### `payments`
- `id`, `user_id`, `subscription_id`
- `provider`, `provider_payment_ref` unique
- `amount`, `currency`, `status`
- `raw_payload_redacted` or safely retained provider reference; avoid unnecessary raw payload retention
- `received_at`, `verified_at`

### `download_jobs`
- `id` UUID
- `user_id`, `chat_id`
- `platform`, `normalized_source_id`
- `status`, `requested_at`, `started_at`, `completed_at`
- `attempt_count`, `max_attempts`, `deadline_at`
- `output_profile`, `failure_code`, `failure_detail_safe`
- `idempotency_key` unique
- `telegram_file_id`, `telegram_message_id` nullable

### `usage_ledger`
- `id`, `user_id`, `job_id`
- `entry_type` (reservation/commit/release/adjustment)
- `quantity` integer
- `quota_window_start`, `quota_window_end`
- `idempotency_key` unique
- `created_at`

### `reward_sessions`
- `id`, `user_id`, `provider`
- `provider_session_ref` unique
- `status`, `created_at`, `expires_at`, `verified_at`

### `reward_transactions`
- `id`, `user_id`, `reward_session_id`
- `provider_event_ref` unique
- `credit_quantity`, `status`, `expires_at`, `created_at`

### `sponsor_campaigns`
- `id`, `name`, `status`
- `starts_at`, `ends_at`
- `placement`, `targeting_config`
- `created_at`

### `ad_impressions`
- `id`, `campaign_id`, `user_id`
- `placement`, `impression_ref`, `created_at`
- Avoid storing more user data than needed for campaign reporting.

### `media_cache`
- `id`, `cache_key` unique
- `platform`, `normalized_source_id`
- `output_profile`, `pipeline_version`
- `storage_key`, `size_bytes`, `content_hash`
- `telegram_file_id` nullable
- `created_at`, `last_accessed_at`, `expires_at`

### `outbox_events`
- `id` UUID
- `aggregate_type`, `aggregate_id`
- `event_type`, `payload`
- `created_at`, `published_at`, `attempt_count`
- Index unpublished events by `created_at`.

## Constraints and indexes

- Unique `telegram_user_id`.
- Unique job `idempotency_key`.
- Unique provider payment and reward event references.
- Unique ledger idempotency key.
- Index jobs by status/requested_at and user_id/requested_at.
- Index ledger by user_id/quota_window_start.
- Index subscriptions by user_id/status/current_period_end.
- Index cache by expires_at and last_accessed_at.
- Use foreign keys and explicit deletion/retention policies.
- Use database transactions and row-level locking or atomic conditional updates for quota reservations.

## Quota accounting

Do not derive quota from a mutable counter alone. Use an append-only ledger with idempotent entries. A transaction should ensure:
1. The user has enough remaining allowance in the active quota window.
2. A reservation is inserted once for the job.
3. Concurrent requests cannot overspend.
4. Commit/release transitions are applied once.

Define whether reward credits are separate from base plan quota or represented as a distinct credit bucket. This remains an implementation decision to document and test.

## Data lifecycle

- Define retention for completed jobs, payment records, reward events, cache metadata and logs.
- Keep billing/audit records for the legally required period.
- Delete expired media artifacts and associated metadata according to policy.
- Provide a user-data deletion workflow where legally and operationally appropriate, while preserving legally required billing records.
- Avoid storing original full URLs unless necessary; redact sensitive query parameters.
