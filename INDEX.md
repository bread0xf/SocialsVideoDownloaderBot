# Documentation Index — SocialsVideoDownloaderBot

## Layering

- `backend_specs/` — **frozen approved baseline**. It wins every conflict with `docs/`. Do not edit it without owner approval as an erratum.
- `docs/` — **living documentation**. Describes implemented behavior, operations and open decisions. `docs/implementation-status.md` is the only status tracker.

## Documents

| Document | Purpose |
|---|---|
| `README.md` | Project overview, status, local and hosted development instructions |
| `AGENTS.md` | Instructions and implementation guardrails for coding agents |
| `backend_specs/` | Approved implementation baseline (wins over `docs/` on conflict) |
| `docs/implementation-status.md` | Single requirement-to-code/test status tracker |
| `docs/product/product-requirements.md` | Product scope, stories and acceptance criteria |
| `docs/product/platform-support.md` | Supported platforms, URL handling and adapter contract |
| `docs/product/freemium-and-entitlements.md` | Quotas, Premium, rewards and billing rules |
| `docs/architecture/architecture-decisions.md` | Architecture decision records |
| `docs/architecture/system-architecture.md` | Processes, modules, job flow, cache and failure handling |
| `docs/architecture/database-design.md` | Implemented PostgreSQL schema and integrity rules |
| `docs/architecture/security-architecture.md` | Threat model, controls and implementation status |
| `docs/engineering/development-standards.md` | Code organization, tooling and testing |
| `docs/operations/deployment-and-operations.md` | Deployment topology, observability and release checklist |
| `docs/operations/railway-dev-environment.md` | Railway development environment runbook |
| `docs/project/unresolved-decisions.md` | Owner decisions required before features or launch |
| `workbench/README.md` | Engine CLI for inspect/download without Telegram or the database |
