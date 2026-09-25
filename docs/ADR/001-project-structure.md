# ADR-001: Project Structure

## Status

Accepted

## Context

Beru is a greenfield project. We need a starting structure that supports modular monolith architecture, clear separation of concerns, and provider abstraction.

## Decision

Use a flat package structure under `backend/app/` with module-level directories:

- `api/` — HTTP routes
- `core/` — Configuration
- `domain/` — Deterministic business logic
- `models/` — SQLAlchemy ORM models
- `repositories/` — Database access
- `schemas/` — Pydantic schemas
- `services/` — Application services
- `integrations/` — External service adapters
- `workers/` — Background jobs
- `security/` — Auth and authorization
- `llm/` — LLM abstraction
- `whatsapp/` — WhatsApp abstraction

## Consequences

- Clear module boundaries make it harder to accidentally couple domain logic to providers.
- Each module can be developed and tested independently.
- Provider abstractions in separate modules make replacement straightforward.
- Alembic migrations live at `migrations/` (project root level).
- Tests mirror the source structure under `backend/tests/`.
