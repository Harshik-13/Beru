# AGENTS.md — Beru

## SOURCE OF TRUTH

The current repository is the source of truth. Historical chat context is supplementary. If documentation and implementation disagree: inspect the implementation and update documentation accordingly.

## DOCUMENTATION HIERARCHY

**Canonical current guidance (in order):**
1. `AGENTS.md` — Agent rules and conventions
2. `docs/PROJECT.md` — Project identity and scope
3. `docs/ARCHITECTURE.md` — Current system architecture
4. `docs/REQUIREMENTS.md` — Locked requirements
5. `docs/STATE.md` — Current live state
6. `docs/CHANGELOG.md` — Engineering history
7. `docs/COMMITS.md` — Git commit index
8. `docs/DOCUMENTATION_INDEX.md` — Documentation map

**Historical only:**
- `docs/ADR/*` — Architecture Decision Records
- `docs/archive/*` — Archived documents

**Reference (non-authoritative):**
- `docs/CONNECTION_LIFECYCLE.md`
- `docs/DATA_MODEL.md`
- `docs/IDEMPOTENCY.md`
- `docs/INTEGRATIONS.md`
- `docs/TESTING.md`
- `docs/THREAT_MODEL.md`

If another Markdown file conflicts with canonical documentation or current code, current code wins and the conflict must be resolved.

## BEFORE EVERY TASK

Read:
- `AGENTS.md` (this file)
- `docs/PROJECT.md`
- `docs/ARCHITECTURE.md`
- `docs/REQUIREMENTS.md`
- `docs/STATE.md`

Read `CHANGELOG.md` and `COMMITS.md` when historical context matters.

## AFTER EVERY TASK

Every implementation task must reconcile project documentation.

**MANDATORY:**
- Update `docs/STATE.md`

**CONDITIONAL:**
- Update `docs/ARCHITECTURE.md` if architecture changed
- Update `docs/REQUIREMENTS.md` if requirements changed
- Update `docs/PROJECT.md` if project goal/scope changed
- Update `docs/COMMITS.md` when a commit is created
- Append/update `docs/CHANGELOG.md` for meaningful changes

Do not modify documentation unnecessarily when its information has not changed.

## Project Identity

- **Name:** Beru (College Copilot)
- **Purpose:** Personal AI-powered college assistant. Telegram-first (Personal Alpha); WhatsApp-ready (future).
- **Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.x, Alembic, Pydantic v2, PostgreSQL, pytest
- **Architecture:** Modular monolith. Provider integrations behind abstraction interfaces.

## Non-Negotiable Security Rules

1. **Backend is the security boundary.** LLM is NOT.
2. LLM must never directly access the database or execute arbitrary SQL.
3. LLM tool calls require typed schemas and backend authorization.
4. Resource ownership is derived from authenticated identity. Never trust client-supplied owner IDs.
5. Every resource access requires authorization.
6. External content (Telegram, portal, OCR, LLM output) is untrusted. Validate before use.
7. Never commit or log secrets, keys, or credentials.
8. Inbound events must be idempotent. Prevent duplicate outbound jobs.
9. State transitions must be enforced server-side.
10. Multi-user data isolation exists from day one.
11. Security-sensitive operations must be auditable.

## Attendance Rules

- Attendance calculations are **deterministic** and live in `backend/app/intelligence/services/attendance_service.py`.
- LLM provides structured intent; backend performs the calculation.
- Simulations must never mutate actual attendance records.

## Timetable State Machine

States: `UPLOADED → EXTRACTING → REVIEW_REQUIRED → CONFIRMED → ARCHIVED` (FAILED also possible).
Only `CONFIRMED` timetables may be used for attendance projections.

## Provider Abstraction

These must remain replaceable behind interfaces:
- Telegram provider/adapter (`backend/app/telegram/`)
- WhatsApp provider/bridge (`backend/app/whatsapp/`)
- LLM provider (`backend/app/intelligence/providers/`)
- College portal integration (`backend/app/integrations/`)
- OCR/vision provider

Do not hard-code the core around any single provider.

## STATUS VOCABULARY

Agents must distinguish:
- **IMPLEMENTED** — code exists and is wired
- **TESTED** — tests exist and pass
- **RUNTIME_VERIFIED** — actually executed and observed
- **USER_VERIFIED** — explicitly confirmed by user

Never upgrade one status into another without evidence.

## SECURITY

Never weaken:
- Authentication
- Authorization
- Ownership
- Tenant isolation
- Credential protection
- LLM/tool boundaries
- Input validation
- Idempotency

## ARCHITECTURE

Do not redesign Beru unless explicitly instructed. Prefer the smallest coherent change that fits the existing architecture.

## NO SPECULATION

Do not claim:
- A feature works because code exists
- Runtime verification without running it
- User verification without user confirmation
- External integration works without actual verification

## TESTING

Do not weaken tests merely to make them pass.

## COMMITTING

Every completed implementation task should produce a meaningful commit unless the user explicitly requests otherwise. Documentation changes required by the task belong in the same coherent commit.

## Project Structure

```
backend/app/
  api/          — FastAPI routes/endpoints
  core/         — Configuration, settings
  intelligence/ — LLM providers, conversation, tools, domain services
  integrations/ — External service adapters (portal, etc.)
  models/       — SQLAlchemy ORM models
  repositories/ — Database access layer
  schemas/      — Pydantic request/response schemas
  security/     — Auth, authorization, audit
  telegram/     — Telegram adapter + linking
  whatsapp/     — WhatsApp abstraction layer (future)
  workers/      — Background job definitions
  main.py       — FastAPI application entry point
backend/tests/  — Test suite
migrations/     — Alembic migrations
docs/           — Architecture and design documentation
```

## What NOT to Do

- Do not bypass CAPTCHA/MFA/access controls on the college portal.
- Do not use real credentials anywhere.
- Do not send WhatsApp messages during development.
- Do not implement database models/migrations until the domain is clear.
- Do not add microservices without documented justification.
- Do not let LLM perform attendance arithmetic as the trusted result.
