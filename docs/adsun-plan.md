# Adsun Rewarded Allowance — Implementation Plan

**Status:** Design record. Ad serving, reward credit granting and reward sessions (ad cooldown) are implemented behind `ADSUN_ENABLED=false`; see `docs/implementation-status.md` for the verified state.
**Date:** 2026-11-17
**Authority:** `backend_specs/` is the frozen baseline. This plan does not override an OPEN decision.
**Feature gate:** The reward feature must remain disabled (`ADSUN_ENABLED=false`) until the owner approves the open decisions in §9 and the provider-contract items in §10.

---

## 1. Goal and scope

Add Adsun sponsored bot ads as the "rewarded allowance": one verified Adsun reward callback grants exactly one additional download credit. The credit is consumed only after the user's included daily allowance is exhausted, and is recorded in an append-only reward ledger.

In scope:

- Adsun bot ad fetch and delivery through `apps/bot`.
- Adsun reward callback endpoint on the FastAPI service.
- Reward grant, balance, daily cap, cooldown, expiry and consumption.
- Idempotent callback handling and duplicate protection.
- Configuration, migration, tests and documentation.

Out of scope:

- Mini Apps, client-side reward granting, ads in channels, campaign billing or advertiser features.
- Sponsor placements after successful downloads (separate feature, OD-08).
- Telegram Stars billing.
- Arbitrary reward-provider integrations. The provider interface is the extension point.

---

## 2. Research findings — Adsun SDK and API

### 2.1 Sources inspected

| Source | What was read |
|---|---|
| PyPI `adsun` 1.0.0 sdist | The installable source. MIT, `requires-python >=3.8`, zero required runtime dependencies. Optional extras: `aiogram`, `ptb`, `async` (the async extra adds `aiohttp`). |
| `adsun/client.py` | `AdsunBot.get_ad`, `AsyncAdsunBot.get_ad`, `block_number`, request/response handling. |
| `adsun/models.py` | `BotAd` dataclass and `BotAd.from_dict`. |
| `adsun/reward.py` | `verify_secret`, `RewardCallback`, `parse_reward_callback`. |
| `adsun/integrations/ptb.py` | `send_ad` helper for python-telegram-bot. |
| `adsun/errors.py` | `AdsunError`, `BadRequest` (400), `InvalidToken` (401), `BlockNotActive` (404), `error_for`. |
| `https://adsun.io/documentation/publisher/telegram-bot` | Bot ad request, response shape and sending rules. |
| `https://adsun.io/documentation/publisher/reward-url` | Reward URL setup, placeholders and callback behavior. |
| `https://adsun.io/documentation/publisher/rewarded` | Rewarded ad behavior and the server-side grant rule. |
| `https://adsun.io/documentation/publisher/api-reference` | SDK events, timings and result types. |
| `https://adsun.io/llms-full.txt`, `https://adsun.io/docs` | General contract and operational notes. |

Repository note: the current `github.com/adsun-io/adsun-sdk` `main` branch (commit `4358aa9`) contains only repository documentation (`README.md`, `llms.txt`, policies, etc.); the Python package source is in the PyPI sdist. The package metadata and source agree with the public docs.

### 2.2 Ad-fetch contract

Bot ads are fetched over HTTPS:

```http
GET https://api.adsun.io/advbot
    ?tgid=<telegram user id>
    &blockid=<numeric block id>
    &language=<language code>
    &token=<account token>
```

- `200` returns one ad as JSON.
- `204` means no eligible ad right now.
- `401` `InvalidToken`, `404` `BlockNotActive`, `400` `BadRequest`; network failures become `AdsunError` with `status=0`.
- `blockid` must be the numeric part only. The SDK's `block_number()` strips `bot-` and `tw-` prefixes and rejects non-numeric values.
- The account token is sent in the query string. It must never be logged, and `httpx`/`httpcore` request-URL logging must stay at `WARNING` or higher.

`200` response fields (the SDK's `BotAd` model):

| Field | Type / nullability | Meaning |
|---|---|---|
| `text_html` | `str` | Ad text containing HTML. Must be sent with `parse_mode=HTML`. |
| `click_url` | `str` | Advertiser destination for the primary button. Adsun short link in practice. |
| `button_name` | `str` | Primary button label. SDK defaults to `"Open"` if missing. |
| `image_url` | `str` or empty/null | Optional image. SDK converts empty string to `None`. |
| `button_reward_name` | `str` or null | Optional reward button label, e.g. `"Claim reward!"`. |
| `reward_url` | `str` or null | Optional reward button destination (Adsun short link). |

`BotAd.buttons()` returns:

```python
[[(button_name, click_url)]]
# plus, only when both are present:
[[(button_reward_name, reward_url)]]
```

Delivery rules from the SDK and docs:

- Use `parse_mode=HTML`.
- Use `protect_content=True`; ad messages must not be forwardable.
- Use `sendPhoto` when `image_url` is present, otherwise `sendMessage`.
- The bot message is a normal sponsored message with an advertiser button and, when present, a reward button.
- The `/advbot` response contains **no event ID, impression ID, click ID or transaction ID**. The `reward_url` is an Adsun short link, not our callback URL.

### 2.3 Reward-callback contract

The Reward URL is configured per block in the Adsun panel. Adsun calls it with an HTTP `GET` after it has server-verified a full rewarded view or task completion. Adsun retries on 5xx and network errors, so the handler must be idempotent.

Documented placeholders:

| Placeholder | Also accepted as | Replaced with |
|---|---|---|
| `[userId]` | `{userId}` | Telegram user ID |
| `[blockId]` | `{blockId}` | Block ID |
| `[timestamp]` | `{timestamp}` | Time of the reward in Unix seconds. The docs say to use it to reject duplicates. |

Adsun also adds `user` and `block` query parameters automatically.

Recommended Reward URL:

```text
https://<api-host>/api/v1/rewards/adsun/callback
    ?userid=[userId]
    &block=[blockId]
    &ts=[timestamp]
    &secret=<long-random-secret>
```

Observed / documented callback parameters:

| Parameter | Required by us | Meaning |
|---|---|---|
| `userid` (aliases: `userId`, `user`, `user_id`) | Yes | Telegram user ID. Must be numeric. |
| `block` (aliases: `blockId`, `blockid`, `block_id`) | Yes | Block ID. Must match the configured block. |
| `ts` or `timestamp` | Yes | Unix seconds. Our chosen param name is `ts`; we also accept `timestamp`. |
| `secret` | Yes | Static shared secret we put in the Reward URL. |
| `user` | No | Adsun auto-adds it; alias for `userid`. |
| Any unique event/impression/transaction ID | — | **Not provided.** |

### 2.4 What `adsun.parse_reward_callback` actually validates

`parse_reward_callback(query, secret=None, secret_param="secret")`:

1. If `secret` is provided, calls `verify_secret(received, expected)`.
   - `verify_secret` returns `False` if either value is empty.
   - Comparison uses `hmac.compare_digest` on UTF-8 bytes (constant time).
2. Reads the first non-empty user value from `userid`, `userId`, `user`, `user_id`.
   - If the value is a sequence (e.g. `parse_qs` output), takes the first item.
   - Requires `str.isdigit()`; otherwise returns `None`.
3. Reads the block value from `block`, `blockId`, `blockid`, `block_id`.
   - Does not require it. Missing block returns `""`.
4. Returns `RewardCallback(user_id: str, block_id: str)`.

It does **not** validate:

- the timestamp;
- callback freshness or replay windows;
- that the block is the publisher's configured block;
- a signature or HMAC over the event parameters;
- that the user exists, is not blocked, or is eligible;
- that a reward was not already granted;
- the daily cap or cooldown.

Additional subtlety verified from the source: `str.isdigit()` accepts non-ASCII Unicode digits. `parse_reward_callback({"userid": "٧٧٧"}, ...)` returns `RewardCallback(user_id="٧٧٧", ...)`. Our wrapper must additionally require ASCII digits and a sane Telegram ID range.

### 2.5 Is there a unique event/impression ID for idempotency?

**No.** This is the most important finding.

- `/advbot` returns no event ID.
- The reward callback has only the Telegram user ID, block ID, optional Unix-seconds timestamp and our static secret.
- The SDK does not parse or expose a timestamp.
- The docs tell implementers to "store each completion's unique identifier", but the documented callback does not supply one. The only candidate is the optional `[timestamp]`, which is second-resolution and whose stability across Adsun retries is **not documented**.

Consequences:

- A robust idempotency key must be synthesized, for example:
  `adsun:{telegram_user_id}:{block_id}:{timestamp}`.
- If Adsun retries with the **same** timestamp, the key is stable and duplicates are rejected.
- If Adsun retries with a **new** timestamp, the key changes and a retry could double-grant. This must be confirmed with Adsun before production.
- Two legitimate rewards completed in the same second for the same user and block would collide. The safe behavior is to reject the second (false negative) rather than double-grant; support can issue a manual adjustment.
- The plan therefore adds a defensive minimum interval between grants and a daily cap, but neither replaces a provider event ID.

**Production gate:** obtain written confirmation from Adsun that `[timestamp]` is the reward completion time and is stable across retries, or obtain a real unique event/transaction ID. Until then, keep the feature disabled in production.

### 2.6 Provider-contract gap: bot message vs. Reward block

The Adsun Reward URL docs describe the callback as firing after a verified "Reward ad or Task". The bot-message page documents a reward button (`button_reward_name` / `reward_url`) but does not explicitly state that completing a bot-message reward invokes the block's Reward URL.

Before enabling, confirm with Adsun:

1. Does a bot-message block with `button_reward_name`/`reward_url` trigger the block's server-to-server Reward URL after a verified full watch?
2. Does that callback include `[timestamp]` for bot placements?
3. Is the timestamp stable across retries?
4. Are there documented source IP ranges for callback allowlisting?

If the answer to (1) is no, Adsun bot ads cannot back a rewarded allowance without a Mini App Reward block, which is outside the MVP. The provider interface still allows a different provider later.

---

## 3. Current implementation baseline

| Area | Current behavior | Relevant files |
|---|---|---|
| Quota reservation | Included allowance is reserved atomically under a per-user advisory lock. `reserve_quota` raises `QUOTA_EXHAUSTED` when the included limit is reached. | `backend/usage/service.py` |
| Commit/release | Commit appends one `usage_ledger` row after delivery; release appends a zero-quantity release row. | `backend/usage/service.py`, `backend/workers/tasks.py` |
| Entitlement | Free: 5 included/day, 480p, `sponsor_eligible=True`. Premium: 20/day, up to 2160p, `sponsor_eligible=False`. | `backend/entitlements/service.py` |
| Ledger | `usage_ledger` is append-only with a unique idempotency key. | `backend/database/models.py` |
| Reservation source | `included` or `premium_included`; `reward_credit` is specified but not implemented. | `backend/database/models.py`, `backend_specs/docs/02` |
| Bot | `/start`, `/help`, `/status`, URL intake. No `/reward`, no callback-query handler. | `apps/bot/main.py` |
| API | Health and platform routes only. No reward routes. | `backend/api/app.py`, `backend/api/routes/` |
| Config | Pydantic Settings, fail-fast production token check, no Adsun settings. | `backend/core/config.py`, `.env.example` |
| Workers | ARQ tasks for outbox dispatch, cache cleanup, stale-job reconciliation. | `backend/workers/tasks.py`, `backend/workers/settings.py` |
| Reward tables | Specified but not implemented. | `backend_specs/docs/02-database-specification.md` |

The current `reserve_quota` has no fallback path. The main integration change is to make it reserve a reward credit when the included allowance is exhausted.

---

## 4. Proposed design

### 4.1 Module layout

Keep reward policy independent from Adsun transport, matching the existing "platform adapter" pattern.

```text
backend/
  ads/
    __init__.py
    provider.py          # AdProvider protocol, AdOffer DTO, provider errors
    adsun.py             # Adsun HTTP client, callback parsing/verification
  rewards/
    __init__.py
    service.py           # grant, balance, cap, cooldown, reservation, expiry
    policy.py            # pure helpers: expiry instant, eligibility, keys
  api/routes/
    rewards.py           # GET /api/v1/rewards/adsun/callback
```

- `backend/ads/provider.py` defines `AdOffer` and `AdProvider`. The bot depends on the protocol, not on Adsun.
- `backend/ads/adsun.py` is the only module that knows the Adsun endpoint, token, block ID and callback parameter names.
- `backend/rewards/service.py` owns the ledger and quota interactions. It does not import Telegram or FastAPI.
- Models stay centralized in `backend/database/models.py`, consistent with the rest of the project.
- Extract `lock_user_quota` from `backend/usage/service.py` into `backend/usage/locking.py` to avoid a circular import between `usage` and `rewards`. Re-export it from `usage.service` for compatibility.

### 4.2 Data model

Three new tables plus one nullable column on `usage_reservations`. The design preserves the frozen spec's `reward_sessions` / `reward_ledger` semantics and adds a durable callback-claim table because Adsun provides no unique event ID.

#### `reward_sessions` (ad-send audit)

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | UUID FK `users.id` RESTRICT, not null | |
| `provider` | `varchar(32)` not null | `adsun` initially. |
| `provider_session_ref` | `text` null | Locally generated UUID token; Adsun does not echo it. |
| `block_id` | `varchar(32)` null | Normalized numeric block ID. |
| `status` | `varchar(32)` not null | `created`, `served`, `rejected`, `expired`. Do not use `verified` until a real provider event ID exists. |
| `reason_code` | `varchar(64)` null | e.g. `NO_FILL`, `SEND_FAILED`, `COOLDOWN`. |
| `created_at` | `timestamptz` not null | |
| `expires_at` | `timestamptz` not null | Ad session TTL. |
| `verified_at` | `timestamptz` null | Reserved for a future correlated provider event. |

Indexes: `(user_id, provider, status, created_at)`, `(expires_at, status)`.

#### `reward_claims` (durable callback event / idempotency guard)

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `provider` | `varchar(32)` not null | |
| `provider_transaction_id` | `text` not null | Synthesized from user + block + timestamp. Unique with `provider`. |
| `user_id` | UUID FK `users.id` RESTRICT, null | Null for unknown users. |
| `block_id` | `varchar(32)` null | Callback block, for audit. |
| `provider_event_at` | `timestamptz` null | Adsun `[timestamp]`, for audit/freshness. |
| `status` | `varchar(32)` not null | `pending`, `accepted`, `capped`, `unknown_user`, `blocked`, `premium_ineligible`, `no_session`, `rejected`. |
| `reason_code` | `varchar(64)` null | Stable code for support and metrics. |
| `reward_session_id` | UUID FK `reward_sessions.id` SET NULL, null | Optional audit link; not proof of correlation. |
| `received_at` | `timestamptz` not null | Server receive time. |
| `processed_at` | `timestamptz` null | |

Constraints/indexes:

- Unique `(provider, provider_transaction_id)`.
- Index `(user_id, received_at)`.
- Check `status` against the allowed set.

The unique constraint is the primary replay defense: the first callback inserts the claim and grants; a retry conflicts and returns 200 without another grant. The claim is inserted and updated in the same transaction as the grant, so a rollback leaves no claim and a retry can succeed.

#### `reward_ledger` (append-only)

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | UUID FK `users.id` RESTRICT, not null | |
| `reward_session_id` | UUID FK `reward_sessions.id` SET NULL, null | Grant audit. |
| `reward_claim_id` | UUID FK `reward_claims.id` SET NULL, null | Grant provenance. |
| `reward_grant_id` | UUID FK `reward_ledger.id` RESTRICT, null | For `consume`/`expire` rows: which grant they terminate. |
| `provider` | `varchar(32)` not null | |
| `provider_transaction_id` | `text` null | Set on grants; null on terminal rows. |
| `entry_type` | `varchar(32)` not null | `grant`, `consume`, `expire` (keep `adjustment` reserved but unused in MVP). |
| `quantity` | `integer` not null | Always `1` for grant/consume/expire; check `> 0`. |
| `quota_period_start` | `timestamptz` null | Lagos day of the grant or consumption. |
| `expires_at` | `timestamptz` null | Grant expiry; null means no expiry. |
| `download_job_id` | UUID FK `download_jobs.id` RESTRICT, null | Set on `consume`. |
| `idempotency_key` | `text` not null, unique | `reward:{provider}:{tx}:grant`, `reward:{job_id}:consume`, `reward:{grant_id}:expire`. |
| `created_at` | `timestamptz` not null | |

Partial unique indexes:

- `(provider, provider_transaction_id)` where `entry_type = 'grant'` — one grant per provider event.
- `(reward_grant_id)` where `entry_type in ('consume','expire')` and `reward_grant_id is not null` — a grant can be terminated by exactly one consume or expire row, never both.

Other indexes: `(user_id, quota_period_start, entry_type)`, `(user_id, expires_at)`, `(user_id, entry_type, created_at)`, `(reward_grant_id)`, `(download_job_id)`.

Checks:

- `quantity > 0`.
- `entry_type in ('grant','consume','expire','adjustment')`.
- A `grant` row has `provider_transaction_id` and `entry_type='grant'`.
- A `consume`/`expire` row has `reward_grant_id`.
- A `consume` row has `download_job_id`.

Append-only rule: no updates or deletes. Corrections are compensating entries.

#### `usage_reservations.reward_grant_id`

Add a nullable `reward_grant_id UUID FK reward_ledger.id RESTRICT`.

- Set only when `source = 'reward_credit'`.
- Check: `source <> 'reward_credit' OR reward_grant_id IS NOT NULL`.
- Partial unique index `(reward_grant_id)` where `reward_grant_id is not null and status = 'reserved'` — one active reservation per credit.
- Existing rows remain valid with `NULL`.

### 4.3 Ledger semantics

| Event | Row | `entry_type` | `source` | Quantity / key |
|---|---|---|---|---|
| Verified ad callback | `reward_ledger` | `grant` | provider = `adsun` | `1`; key `reward:adsun:{tx}:grant` |
| Successful delivery using a reward credit | `reward_ledger` | `consume` | provider = `adsun` | `1`; key `reward:{job_id}:consume` |
| Successful delivery using a reward credit | `usage_ledger` | `download_committed` | `reward_credit` | `1`; key `download:{job_id}:commit` |
| Credit expiry | `reward_ledger` | `expire` | provider = `adsun` | `1`; key `reward:{grant_id}:expire` |
| Failed delivery using a reward credit | `usage_ledger` | `reservation_released` | `reward_credit` | `0`; key `download:{job_id}:release` |

There is no new `usage_ledger` entry type for grants. Grants live in `reward_ledger`; `usage_ledger` remains the download-count ledger. This preserves the separation in `backend_specs/docs/02`.

Available balance is derived, never stored as a mutable counter:

```text
available =
  grants for the user
  where expires_at is null or expires_at > now
  and no consume/expire row references the grant
  and no active (status = 'reserved') usage reservation references the grant
```

"Earned today" is the count of `grant` rows with `quota_period_start = quota_period_start(now)`.

### 4.4 Quota reservation and consumption

Modify `backend/usage/service.py`:

1. Acquire the per-user advisory lock (existing behavior).
2. Return an existing reservation for the job if present (existing behavior).
3. Compute included usage for the current Lagos period.
4. If included usage is below the entitlement limit, reserve `entitlement.quota_source` (existing behavior).
5. Otherwise, try `rewards.service.reserve_reward_grant`:
   - select the oldest-expiring, oldest-created available grant;
   - lock it;
   - create a `usage_reservations` row with `source='reward_credit'` and `reward_grant_id`;
   - if no grant is available, raise `QUOTA_EXHAUSTED`.
6. If the plan's included limit is `NULL`, fail closed with `INTERNAL_ERROR` as today; do not silently fall back to ad credits.

`commit_quota`:

- If the reservation source is `reward_credit`, append the `reward_ledger` consume row with the job ID and the grant ID in the same transaction as the `usage_ledger` commit.
- The consume row uses the `reward:{job_id}:consume` key, so repeated commits are idempotent.
- A reservation made while the credit was valid is honored even if delivery finishes after the credit's `expires_at`; this is intentional. The expiry job skips grants with active reservations, so the consume/expire race is closed by both that rule and the terminal-row unique index.

`release_quota`:

- Mark the reservation released. Do not write a reward consume row. The grant becomes available again unless it is already past `expires_at` or has an expire row.
- No new `reward_ledger` entry is needed for a release; the reservation state change is the audit.

`included_usage` remains unchanged: it filters by `source = entitlement.quota_source`, so reward reservations do not consume included allowance.

### 4.5 Callback processing

New route: `GET /api/v1/rewards/adsun/callback`.

The same handlers are also mounted under neutral aliases, `GET /api/v1/hooks/r1/cb` (callback) and `GET /api/v1/hooks/r1/probe` (temporary capture route). Adsun's panel switches a block to "Use Adsun Rewards URL" whenever the Reward URL path contains `rewards/adsun`, which would bypass the shared-secret check, so the neutral paths are the ones to paste into the panel. The aliases reuse the same handler functions, stay hidden from OpenAPI, and keep every guard identical. The original `/api/v1/rewards/adsun/*` paths remain available for compatibility.

This is a deliberate deviation from the generic `POST /api/v1/rewards/callback` in `backend_specs/docs/03`: Adsun uses GET and the route is provider-specific. The generic route can be added later if another provider needs POST.

Processing order:

1. If `ADSUN_ENABLED=false` or no callback secret is configured, return `404` without detail.
2. Read the query parameters. Do not log the query string.
3. Verify `secret` with `hmac.compare_digest` (use `adsun.verify_secret` or an equivalent local helper). Invalid → `403`.
3a. If `test=1` or `test=true`, log `reward_callback_test` with parameter names only and return `200` with `{"status":"test"}`. Do not parse the payload, insert a claim, redeem a session or grant credit.
4. Parse with `adsun.parse_reward_callback` (secret already verified) and apply our stricter checks:
   - `userid`/`user` must be ASCII digits and a positive 64-bit integer.
   - `block` must be present and equal the configured normalized block ID.
   - `ts`/`timestamp` must be present, integer Unix seconds, and within:
     `now - ADSUN_CALLBACK_MAX_AGE_SECONDS <= ts <= now + ADSUN_CALLBACK_FUTURE_SKEW_SECONDS`.
   - Failures → `400`.
5. Synthesize the provider transaction ID:
   `adsun:{telegram_user_id}:{block_id}:{timestamp}`.
6. Open a DB transaction and call `rewards.service.grant_reward`:
   - Insert `reward_claims` with `ON CONFLICT DO NOTHING` on `(provider, provider_transaction_id)`.
   - If the claim already exists, return `duplicate` (HTTP 200) without granting again.
   - Resolve the user by Telegram ID. Unknown → claim `unknown_user` (200).
   - Reject blocked users → `blocked` (200).
   - Resolve entitlement. Premium and not reward-eligible → `premium_ineligible` (200).
   - Check the daily cap using the count of grants for the current Lagos period. At/above cap → `capped` (200).
   - Check the minimum grant interval. Too soon → `cooldown` (200).
   - Insert the reward grant with `expires_at` from the configured expiry policy.
   - Update the claim to `accepted` with `processed_at`.
   - Insert an outbox `reward.granted` event in the same transaction.
7. Return `200` with a plain-text body for accepted/duplicate/capped/cooldown/unknown/blocked/premium. Return `500` only for unexpected/DB failures, so Adsun retries.
8. The worker sends the user notification from the outbox event; the callback route does not call Telegram.

Why 200 for business rejections: Adsun retries 5xx and network errors. A capped or ineligible user will not become eligible by retrying the same event. Returning 200 stops retry storms. The claim row preserves the decision for audit.

Why the claim is inserted before the checks: two concurrent callbacks with the same transaction ID must serialize on the unique key. The per-user advisory lock also serializes cap/cooldown checks for different events belonging to the same user.

### 4.6 Bot flow

Add a `/reward` command and an inline button from `/status`.

1. Handler checks `ADSUN_ENABLED`. Disabled → "Rewarded downloads are not available right now."
2. Upsert the Telegram user and run the same advisory eligibility pre-check as `grant_reward`:
   - not blocked;
   - Premium eligibility per `REWARD_PREMIUM_ELIGIBLE`;
   - the Lagos-day grant cap (all grants count, including credits whose reservation was later released).
   If ineligible, reply with a short reason (the cap message names the Africa/Lagos midnight reset) and stop. No session row, no provider call. The callback re-checks everything and remains authoritative.
3. Open or reuse the pending `reward_sessions` row (the ad cooldown). If one is already pending, tell the user to finish the current ad and stop.
4. Fetch an ad through `AdProvider.fetch_ad`.
   - `None` (Adsun 204) → "No ad is available right now. Please try again later."
   - Provider error → generic failure message; log the provider status, never the token or URL.
   - Either outcome expires the session so the user can retry.
5. Send the ad using the documented pattern:
   - `sendPhoto` if `image_url` is present, otherwise `sendMessage`;
   - `caption`/`text = text_html`, `parse_mode=HTML`, `protect_content=True`;
   - primary button `(button_name, click_url)`; reward button `(button_reward_name, reward_url)` only when both are present.
6. Leave the session `pending` after a successful send. Expire it on Telegram delivery failure so the user can retry.
7. Tell the user that the extra download is added after Adsun confirms completion. Do not grant anything in the handler.

The handler is a thin transport adapter. It does not write the reward ledger; only the callback route does.

`/status` additions (only when the feature is enabled):

```text
Plan: Free
Today: 5/5 used (0 remaining).
Reward credits: 2 available (3/10 earned today).
Credits expire at midnight Africa/Lagos.
Maximum quality: 480p
```

`/help` and `/start` mention `/reward` only when enabled.

### 4.7 Configuration

Add to `backend/core/config.py` and `.env.example`. Defaults are proposed values, not approved product values.

| Setting | Default | Purpose |
|---|---|---|
| `ADSUN_ENABLED` | `false` | Master feature flag. Keep false until §9/§10 are approved. |
| `ADSUN_ACCOUNT_TOKEN` | empty | Publisher account token. Bot process only. Never log. |
| `ADSUN_BLOCK_ID` | empty | Numeric block ID; accept `50001`, `bot-50001`, `tw-50001`. |
| `ADSUN_REWARD_SECRET` | empty | Static callback secret. API process only. Require at least 32 characters when set. |
| `ADSUN_API_URL` | `https://api.adsun.io` | Must be HTTPS. |
| `ADSUN_TIMEOUT_SECONDS` | `10` | Ad fetch timeout. |
| `ADSUN_REWARD_REQUIRE_TIMESTAMP` | `true` | Fail closed when `[timestamp]` is missing. Do not disable in production. |
| `ADSUN_CALLBACK_MAX_AGE_SECONDS` | `900` | Reject stale callbacks. |
| `ADSUN_CALLBACK_FUTURE_SKEW_SECONDS` | `60` | Tolerate small clock skew. |
| `REWARD_DAILY_CAP` | `10` | Proposed cap per user per Lagos day. |
| `REWARD_CREDIT_EXPIRY` | `end_of_quota_day` | `end_of_quota_day` or `ttl`. |
| `REWARD_CREDIT_TTL_SECONDS` | empty | Required only when expiry is `ttl`. |
| `REWARD_PREMIUM_ELIGIBLE` | `false` | Whether Premium users may earn rewards. |
| `REWARD_OFFER_ONLY_WHEN_EXHAUSTED` | `true` | Only offer ads after included allowance is used. |
| `REWARD_AD_REQUEST_COOLDOWN_SECONDS` | `10` | Minimum interval between ad requests. |
| `REWARD_MIN_GRANT_INTERVAL_SECONDS` | `30` | Defensive minimum interval between accepted grants. |
| `REWARD_SESSION_TTL_SECONDS` | `900` | Ad-session audit TTL. |
| `REWARD_NOTIFICATIONS_ENABLED` | `true` | Send a bot message after a grant via the outbox. |

Validation rules:

- If `ADSUN_ENABLED` is false, do not require Adsun secrets; local development and tests must run without them.
- Do not add a single global validator that requires both the account token and the callback secret, because the API and bot run as separate services with least-privilege env vars. Validate at the use site:
  - bot startup: if enabled but no token/block, log an error and do not construct the provider;
  - API startup: if enabled but no callback secret, log an error and return 404 from the route.
- If `ADSUN_BLOCK_ID` is non-empty, it must normalize to ASCII digits after stripping `bot-`/`tw-`.
- If `ADSUN_REWARD_SECRET` is non-empty, require at least 32 characters.
- `ADSUN_API_URL` must start with `https://`.
- If `REWARD_CREDIT_EXPIRY=ttl`, require `REWARD_CREDIT_TTL_SECONDS`.
- `REWARD_DAILY_CAP`, cooldowns and TTLs must be positive (allow 0 only for cooldowns explicitly).

### 4.8 API route

Add `backend/api/routes/rewards.py` and include it in `create_app`.

```python
router = APIRouter(prefix="/api/v1/rewards", tags=["rewards"])


@router.get("/adsun/callback")
async def adsun_reward_callback(request: Request) -> PlainTextResponse: ...
```

- Use `PlainTextResponse` with generic bodies (`ok`, `forbidden`, `bad request`, `unavailable`).
- Do not return stack traces, exception strings, user IDs or query parameters.
- Use `request.app.state.session_factory` and `session_scope` so the claim, grant and outbox event commit atomically.
- Log a structured event with internal user UUID (when known), provider, status, reason code and `claim_id`; never the callback query, secret, token or synthesized transaction ID.
- Return 404 when the feature or callback secret is not configured, 403 for an invalid secret, 400 for malformed/stale parameters, 200 for accepted/duplicate/business rejections, 500 for unexpected DB failures.

### 4.9 Expiry and notifications

Add a worker cron `expire_reward_credits` (every 15 minutes, or at least around Lagos midnight):

1. Select grants where `expires_at <= now`, no terminal row, and no active reservation.
2. Insert `expire` rows with `on_conflict_do_nothing`.
3. Mark stale `reward_sessions` (`created`/`served` with `expires_at <= now`) as `expired`.

The balance query already filters `expires_at > now`, so a credit is unusable even before the expiry row is written. The expiry row is for audit and to make the terminal state explicit.

Notifications:

- The callback inserts `outbox_events.event_type = "reward.granted"` with `aggregate_type = "reward_ledger"`, `aggregate_id = grant_id`, payload `{grant_id, user_id, expires_at}`.
- Extend `dispatch_outbox` to enqueue `notify_reward_granted` for this event type instead of marking it published without action.
- Add `notify_reward_granted` to `WorkerSettings.functions`. It loads the user and grant, sends a short text via the existing `Delivery` abstraction, and logs failures without failing the grant.
- If `REWARD_NOTIFICATIONS_ENABLED=false`, skip the outbox event entirely.

---

## 5. Alembic migration plan

Create one revision after the current head `4270b8fe5cc0`:

```bash
uv run alembic revision --autogenerate -m "add adsun rewarded credits"
```

Review and adjust the generated migration manually. Upgrade order:

1. Create `reward_sessions`.
2. Create `reward_claims` (FK to `reward_sessions`).
3. Create `reward_ledger` (FKs to `users`, `reward_sessions`, `reward_claims`, self, `download_jobs`).
4. Add `usage_reservations.reward_grant_id` with FK and the check constraint.
5. Create all indexes and partial unique indexes.
6. Add check constraints for statuses, quantities and terminal rows.

Downgrade in reverse order: drop the reservation index/column, then `reward_ledger`, `reward_claims`, `reward_sessions`.

Use the project's naming convention (`op.f(...)`) and explicit index names. Do not seed reward rows. Verify `uv run alembic upgrade head` from an empty database and `downgrade` back.

---

## 6. Files to change

### New

| File | Purpose |
|---|---|
| `backend/ads/__init__.py` | Package marker and public exports. |
| `backend/ads/provider.py` | `AdProvider` protocol, `AdOffer` DTO, `AdProviderError`. |
| `backend/ads/adsun.py` | Adsun `/advbot` client, block normalization, callback parsing and strict validation. |
| `backend/rewards/__init__.py` | Package marker. |
| `backend/rewards/policy.py` | Pure helpers: expiry instant, transaction ID, cap/cooldown decisions. |
| `backend/rewards/service.py` | Claim/grant, balance, reserve, consume, expire. |
| `backend/usage/locking.py` | Extracted `lock_user_quota`. |
| `backend/api/routes/rewards.py` | Adsun callback route. |
| `migrations/versions/<rev>_add_adsun_rewarded_credits.py` | Schema migration. |
| `tests/unit/test_adsun_provider.py` | Ad fetch mapping/errors. |
| `tests/unit/test_adsun_callback.py` | Callback validation and idempotency key. |
| `tests/unit/test_reward_policy.py` | Cap, cooldown, expiry, eligibility. |
| `tests/integration/test_reward_ledger.py` | Claim/grant/balance/expiry. |
| `tests/integration/test_reward_quota.py` | Reservation/commit/release with reward credits. |
| `tests/unit/test_bot_reward_handler.py` | `/reward` handler behavior. |
| `tests/unit/test_api_rewards.py` | Callback HTTP status mapping and log redaction. |

### Modified

| File | Change |
|---|---|
| `backend/database/models.py` | Add `RewardSession`, `RewardClaim`, `RewardLedger`; add `UsageReservation.reward_grant_id`. |
| `backend/usage/service.py` | Reward fallback, consume on commit, re-export lock. |
| `backend/entitlements/service.py` | Add `reward_eligible` to `Entitlement`; set it for Free/Premium. |
| `backend/core/config.py` | Adsun and reward settings/validation. |
| `backend/core/errors.py` | Reward-specific stable error codes. |
| `backend/core/logging.py` | Access-log query redaction or explicit access-log disable for the API. |
| `backend/api/app.py` | Include the rewards router; set callback-enabled state. |
| `backend/api/main.py` | Ensure callback secrets cannot appear in uvicorn access logs. |
| `apps/bot/main.py` | Wire provider, `/reward`, `/status`, help text, callback-query button. |
| `backend/workers/tasks.py` | Expiry cron, reward notification task, outbox branch. |
| `backend/workers/settings.py` | Register new tasks/cron. |
| `backend/downloads/outbox.py` | Add `reward.granted` event helper/constant. |
| `.env.example` | New variables with safe placeholders. |
| `pyproject.toml` | Add `adsun` (if the official SDK is used for parsing/model). |
| `docs/implementation-status.md` | Update the rewarded-ads row and verification log after implementation. |
| `docs/architecture/database-design.md` | Document the new tables and reservation column. |
| `docs/product/freemium-and-entitlements.md` | Record the Adsun mechanism and open decisions. |
| `docs/project/unresolved-decisions.md` | Update D-05/D-06/D-07; add callback-id/content-policy decision records. |
| `docs/architecture/security-architecture.md` | Callback secret, replay and log-redaction controls. |
| `docs/operations/deployment-and-operations.md` | Env vars, callback URL, secret rotation, monitoring. |
| `docs/operations/railway-dev-environment.md` | Dev deployment steps for Adsun, if enabled. |
| `README.md` | Repository map and product snapshot, once implemented. |

Do not modify `backend_specs/` without owner approval as an erratum.

---

## 7. Tests

### Unit

- `AdsunProvider.fetch_ad`:
  - 200 maps all six fields; `image_url=""` becomes `None`; missing `button_name` defaults to `"Open"`.
  - 204 returns `None`.
  - 400/401/404 map to `AdProviderError` with safe codes.
  - Timeout/network error maps to `AdProviderError`.
  - Token and request URL never appear in captured logs.
  - Non-HTTPS `click_url`/`reward_url`/`image_url` is rejected/dropped.
- Callback parsing:
  - Valid secret + user + block + timestamp.
  - Missing/wrong secret → 403 path.
  - Missing user, non-ASCII digits, zero/negative/overflow user → 400.
  - Missing/mismatched block → 400.
  - Missing timestamp when required → 400.
  - Non-integer, stale, future-skew timestamp → 400.
  - Transaction ID is deterministic for the same user/block/timestamp.
  - `parse_reward_callback` alone is shown to accept a missing block and Unicode digits; the wrapper rejects both.
- Reward policy:
  - Expiry is the next Lagos midnight for `end_of_quota_day`.
  - TTL expiry when configured.
  - Cap counting, cooldown, premium eligibility, only-after-exhausted.
- Bot handler:
  - Disabled feature.
  - Premium not eligible.
  - Included quota not exhausted.
  - Cap reached / cooldown.
  - No fill.
  - Successful send uses HTML + `protect_content=True` and the right buttons.
  - Telegram send failure marks the session rejected and replies safely.
  - `/status` shows credits and expiry only when enabled.
- API:
  - Disabled → 404.
  - Invalid secret → 403.
  - Bad/missing timestamp or block → 400.
  - Accepted → 200.
  - Duplicate → 200 and one grant.
  - Capped/cooldown/unknown/blocked/premium → 200 and no grant.
  - Unexpected DB error → 500.
  - Access-log redaction / no secret in logs.

### Integration (PostgreSQL)

- Grant idempotency: two identical callbacks produce one `reward_claims` row and one `reward_ledger` grant.
- Concurrent identical callbacks: one accepted, one duplicate.
- Concurrent different callbacks at the cap boundary: one accepted, one capped.
- Daily cap: 10 grants accepted; 11th rejected and recorded as capped.
- Cooldown: a second grant inside the interval is rejected.
- Unknown user and blocked user do not create grants.
- Premium user with `REWARD_PREMIUM_ELIGIBLE=false` does not earn.
- Balance: grants minus consumed/expired/reserved.
- Reservation preference: included allowance is used before reward credits.
- Successful delivery: usage ledger commit + reward consume, balance decreases, repeated commit is idempotent.
- Failed delivery: reservation released, no consume row, credit available again.
- Cache-hit delivery: same commit/consume behavior as a fresh job.
- Expired credit is not reserved; expiry cron writes exactly one `expire` row.
- A grant with an active reservation is not expired by the cron.
- Concurrent submissions with one credit: one reservation, one `QUOTA_EXHAUSTED`.
- Migration applies from an empty database and downgrades cleanly.

### Provider contract / live verification (gated)

A live test requires Adsun publisher credentials and a configured block. Gate it behind an environment flag such as `SVDB_LIVE_ADSUN=1`; do not make it part of the default suite. Verify:

1. `/advbot` returns a real ad and Telegram accepts the HTML/protected send.
2. Completing the reward flow calls the configured callback URL.
3. The callback includes `ts` and `block`.
4. A retry/duplicate does not double-grant.
5. The grant notification arrives.

---

## 8. Security and privacy

- **No client trust.** The bot only sends ads. Only the authenticated server-to-server callback can grant a credit.
- **Shared secret only.** Adsun does not document an HMAC signature. Use a long random secret (32+ chars), HTTPS, constant-time comparison, and rotation. Treat the secret as a credential.
- **Secret leakage.** The secret is necessarily in the callback query string. Do not log the query. Disable uvicorn access logs for the API or install a filter that redacts `secret`/`ts`/`userid`; configure the reverse proxy to redact query strings. Rotate immediately if logs are exposed.
- **Replay.** Unique `(provider, provider_transaction_id)` claim, timestamp freshness, minimum grant interval and daily cap. The missing provider event ID remains a residual risk (§2.5).
- **Callback abuse.** A valid secret holder can forge callbacks for arbitrary user IDs. The daily cap limits impact. Add an IP allowlist only if Adsun publishes stable callback ranges; do not trust spoofable `X-Forwarded-For`.
- **Ad content.** Adsun may serve 18+, gambling, crypto or other restricted categories. The bot is general-audience. Owner approval and Adsun category/block filtering are required before enabling. `text_html` is sent with Telegram HTML parse mode; it is not executed as web HTML, but it can contain links and unsupported tags. Catch Telegram parse errors and never log the full ad body.
- **SSRF.** We do not fetch `click_url`, `reward_url` or `image_url` ourselves. Telegram fetches the image. Validate HTTPS and non-empty fields; never pass user-controlled URLs into our network stack.
- **Token leakage.** The Adsun account token is in the `/advbot` query. Keep `httpx`/`httpcore` at `WARNING`, never log the request URL, and never include the token in exceptions.
- **Database integrity.** Append-only reward ledger, check constraints, partial unique indexes, per-user advisory lock for earn/spend decisions, and terminal-row uniqueness for consume/expire.
- **Privacy.** Store only the Telegram user ID already held by `users`, internal UUIDs, block ID, timestamps and status. Do not store the raw callback query, secret or ad HTML. Define retention for `reward_claims`/`reward_sessions` before production; reward/payment records must not be deleted with media cleanup.

---

## 9. Open decisions and proposed defaults

These require owner approval. The feature stays disabled until they are resolved.

| ID / topic | Proposed default | Why it is open / notes |
|---|---|---|
| D-05 Daily reward cap | **10 rewarded downloads per user per Lagos day** (`REWARD_DAILY_CAP=10`) | Frozen spec proposes 10 but does not approve it. Count accepted grants, including later expired/consumed credits. |
| D-06 Credit expiry | **End of the Lagos quota day the credit was earned** (`REWARD_CREDIT_EXPIRY=end_of_quota_day`) | Frozen spec proposes this. A credit earned at 23:59 has almost no usable time; decide whether a grace period is needed. |
| D-07 Premium users see/earn ads | **No** (`REWARD_PREMIUM_ELIGIBLE=false`) | Premium excludes sponsor placements (locked OD-08). Existing credits earned as Free remain usable until expiry under this proposal. |
| Ad cooldown / frequency | **30s between accepted grants; 10s between ad requests** | Adsun's block has a ~5s gap, but that is not an abuse control. Prevents rapid `/reward` spam and retry double-grants. |
| When rewards are offered | **Only after the included allowance is exhausted** (`REWARD_OFFER_ONLY_WHEN_EXHAUSTED=true`) | Frozen spec says credits may be earned after the included allowance is exhausted. Configurable if the owner wants pre-earning. |
| Maximum credit balance | **No separate cap; bounded by the daily cap and expiry** | With end-of-day expiry, stockpiling is limited. If expiry changes, add a balance cap. |
| Credit treatment on Premium upgrade | **Existing credits usable until expiry; no new earning** | Avoids forfeiting legitimately earned credits while respecting Premium's no-sponsor policy. |
| Grant notification | **Yes, via `reward.granted` outbox event** (`REWARD_NOTIFICATIONS_ENABLED=true`) | Users need feedback after the server callback. Best-effort; the grant is authoritative. |
| Expiry grace period | **None initially** | Consider a 10–15 minute grace if late-night grants are a real UX problem. |
| Ad content policy | **Pending owner approval** | Adsun serves 18+/gambling/crypto; the bot is general-audience. Needs category controls and a takedown process. |
| Callback unique ID / timestamp stability | **Blocked pending Adsun confirmation** | No unique event ID. If `[timestamp]` is not stable across retries, do not enable production; require a provider event ID or change provider. |
| Callback authentication hardening | **Shared secret + timestamp + cap; IP allowlist only if Adsun publishes ranges** | No HMAC signature is documented. Owner must accept the residual risk. |
| Retention of reward claims/sessions | **Keep for audit; define a production retention period** | Reward records must not be removed by media cleanup. Align with the future data-retention policy. |

Add these to `docs/project/unresolved-decisions.md` when implementation starts. Do not silently mark them resolved.

---

## 10. Provider-contract verification and blockers

Before enabling `ADSUN_ENABLED=true` in production, obtain answers from Adsun support:

1. **Bot reward callback:** Does a bot-message reward button invoke the block's Reward URL after a verified full watch?
2. **Timestamp:** Is `[timestamp]` the reward completion time? Is it stable across retries? What is its precision?
3. **Event ID:** Can Adsun add a unique completion/transaction ID to the callback? This is the preferred fix.
4. **Retry policy:** How many retries, with what schedule? Does a retry reuse the same query parameters?
5. **Source IPs:** Are there stable callback source ranges for allowlisting?
6. **Signature:** Is an HMAC/signature over the callback parameters available?
7. **Ad categories:** Can the block exclude 18+, gambling, crypto and other restricted categories?
8. **Debug/test mode:** Confirm that debug ads never call the production Reward URL (the docs say they do not).

If (1) or (2) is not satisfied, the Adsun bot-ad path cannot safely back a rewarded allowance in this MVP. Options: use a Reward block in a Mini App (out of MVP), use another provider with authenticated postbacks and a transaction ID, or keep rewards disabled.

---

## 11. Implementation sequence

1. **Schema and domain:** Add models, migration, `reward_claims`/`reward_ledger` service, balance/cap/cooldown/expiry helpers and unit/integration tests. No API or bot yet.
2. **Adsun adapter and callback parser:** `AdProvider`, `AdsunProvider`, strict callback validation, provider tests. Keep the feature flag off.
3. **Quota integration:** Reward fallback in `reserve_quota`, consume in `commit_quota`, release behavior, concurrent and failure-path tests.
4. **Callback API:** Route, secret verification, claim/grant transaction, outbox event, HTTP status tests, log-redaction test.
5. **Bot UI:** `/reward`, `/status`, `/help`, ad send, session audit, handler tests.
6. **Expiry and notifications:** Worker cron, outbox dispatch branch, notification task, tests.
7. **Docs and operations:** Update the status tracker, database design, entitlement policy, security, deployment/runbook and decision register.
8. **Live verification:** With owner-approved test credentials and a test block, verify ad delivery and callback once; confirm duplicate behavior; then decide whether to enable for a limited cohort.

Each slice must pass:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy backend apps
uv run pytest
uv run alembic upgrade head
```

Integration tests require PostgreSQL; they skip when unavailable, as today.

---

## 12. Acceptance criteria

- A verified Adsun callback grants exactly one credit; duplicate/replayed callbacks grant nothing extra.
- A credit is consumed only after successful Telegram delivery, and only after the included allowance is exhausted.
- Failed delivery releases the reservation and does not consume or charge a credit.
- The daily cap, cooldown, Premium eligibility and expiry behave as configured.
- The callback endpoint rejects bad secrets, bad blocks, missing/stale timestamps and malformed user IDs without leaking details.
- Secrets, tokens and callback query strings never appear in logs.
- The feature is off by default and cannot be enabled accidentally without the required Adsun configuration.
- Migration applies from empty and downgrades cleanly.
- Documentation records the remaining open decisions and the provider-contract risk; no production-readiness claim is made.

---

## 13. Conflicts and deviations to record

| Item | Existing text | Proposed handling |
|---|---|---|
| Callback method/path | `backend_specs/docs/03` lists `POST /api/v1/rewards/callback`. | Adsun requires `GET`; use `GET /api/v1/rewards/adsun/callback`. Provider-specific route. |
| Unique provider transaction ID | `backend_specs/docs/02` requires a unique provider reward transaction ID; `docs/05` says one provider transaction ID grants once. | Adsun provides none. Synthesize from user+block+timestamp and flag the stability risk. Owner approval/erratum required if this is acceptable. |
| Reward tables | Spec has `reward_sessions` and `reward_ledger`. | Add `reward_claims` for durable callback idempotency and add `usage_reservations.reward_grant_id`. Preserve spec semantics; document the extension. |
| Daily cap/expiry | Spec calls them proposed, not approved. | Implement as configuration with the proposed defaults; keep `ADSUN_ENABLED=false`. |
| Premium rewards | Spec says Premium excludes sponsor placements. | Default `REWARD_PREMIUM_ELIGIBLE=false`; existing credits usable until expiry; owner decision required. |
| Bot-message reward callback | Bot docs show a reward button but do not explicitly promise the Reward URL callback. | Treat as a provider-contract blocker (§10); do not enable until confirmed. |
| Ad content | Product docs do not define allowed ad categories. | Pending owner approval; do not enable general-audience ads without category controls. |

---

## 14. Summary of the critical answer

Adsun's Python SDK and public docs provide:

- a clean bot ad fetch (`/advbot`) returning `text_html`, `click_url`, `button_name`, `image_url`, `button_reward_name`, `reward_url`;
- a server-to-server reward callback carrying `userid`, `block`, an optional Unix-seconds `timestamp`, and a static `secret`;
- `parse_reward_callback` validating only the shared secret, a numeric user ID and an optional block;
- **no unique event, impression, click or transaction ID**, and no documented timestamp stability across retries.

Therefore the implementation can be built and tested behind a disabled feature flag, but production enablement requires owner approval of the cap/expiry/Premium/cooldown decisions and Adsun confirmation that the bot reward callback exists and that `[timestamp]` is a stable deduplication key (or that a real transaction ID will be provided).
