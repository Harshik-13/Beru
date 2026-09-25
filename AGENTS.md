# AGENTS.md — Beru

## Project Identity

- **Name:** Beru (College Copilot)
- **Purpose:** Personal AI-powered college assistant. WhatsApp-first.
- **Stack:** Python 3.13+, FastAPI, SQLAlchemy 2.x, Alembic, Pydantic v2, PostgreSQL, pytest
- **Architecture:** Modular monolith. Provider integrations behind abstraction interfaces.

## Non-Negotiable Security Rules

1. **Backend is the security boundary.** LLM is NOT.
2. LLM must never directly access the database or execute arbitrary SQL.
3. LLM tool calls require typed schemas and backend authorization.
4. Resource ownership is derived from authenticated identity. Never trust client-supplied owner IDs.
5. Every resource access requires authorization.
6. External content (WhatsApp, portal, OCR, LLM output) is untrusted. Validate before use.
7. Never commit or log secrets, keys, or credentials.
8. Inbound events must be idempotent. Prevent duplicate outbound jobs.
9. State transitions must be enforced server-side.
10. Multi-user data isolation exists from day one.
11. Security-sensitive operations must be auditable.

## Attendance Rules

- Attendance calculations are **deterministic** and live in `backend/app/domain/`.
- LLM provides structured intent; backend performs the calculation.
- Simulations must never mutate actual attendance records.

## Timetable State Machine

States: `UPLOADED → EXTRACTING → REVIEW_REQUIRED → CONFIRMED → ARCHIVED` (FAILED also possible).
Only `CONFIRMED` timetables may be used for attendance projections.

## Provider Abstraction

These must remain replaceable behind interfaces:
- WhatsApp provider/bridge (`backend/app/whatsapp/`)
- LLM provider (`backend/app/llm/`)
- College portal integration (`backend/app/integrations/`)
- OCR/vision provider

Do not hard-code the core around any single provider.

## Workflow for Agents

1. **Inspect before modifying.** Read surrounding code and existing patterns.
2. Do not make architectural assumptions silently.
3. Add tests for security-sensitive behavior.
4. Run tests after changes: `pytest backend/tests/ -v`
5. Run linting after changes: `ruff check backend/` and `mypy backend/`
6. Report exactly what changed.
7. Do not claim a feature is implemented if only scaffolded.
8. Do not introduce new dependencies without justification.
9. Do not introduce microservices without a documented reason.
10. Keep integrations replaceable — never couple core logic to a specific provider.

## Project Structure

```
backend/app/
  api/          — FastAPI routes/endpoints
  core/         — Configuration, settings
  domain/       — Deterministic business logic (attendance engine, timetable state machine)
  models/       — SQLAlchemy ORM models
  repositories/ — Database access layer
  schemas/      — Pydantic request/response schemas
  services/     — Application services (orchestrate domain + repos)
  integrations/ — External service adapters (portal, etc.)
  workers/      — Background job definitions
  security/     — Auth, authorization, audit
  llm/          — LLM abstraction layer
  whatsapp/     — WhatsApp abstraction layer
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
