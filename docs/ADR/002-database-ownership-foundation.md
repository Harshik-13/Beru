# ADR-002: Database and Ownership Foundation

## Status

Accepted

## Context

Beru needs a persistence layer that establishes multi-user ownership from day one. The database must support:
- Student as the ownership root
- Provider-neutral WhatsApp identity linking
- PostgreSQL as the target database
- Async SQLAlchemy 2.x for modern async patterns
- Alembic for migrations

## Decision

1. **Async SQLAlchemy 2.x** with `asyncpg` driver for PostgreSQL
2. **UUID primary keys** for all domain entities (`uuid_generate_v4()` via `gen_random_uuid()`)
3. **Timezone-aware timestamps** (`TIMESTAMP WITH TIME ZONE`) with server-side defaults
4. **Student** as the ownership root entity — minimal, no academic fields yet
5. **WhatsAppIdentity** as a separate entity linking external identities to Student
   - Unique constraint on `(provider, provider_user_id)`
   - Provider-neutral enum: `unknown`, `whatsapp_web_js`, `baileys`, `meta_cloud_api`
   - Cascade delete when Student is deleted
6. **Repository pattern** — repositories handle persistence, not authorization
7. **Service-layer transaction control** — services commit/rollback; repositories flush only
8. **Alembic** for deterministic, reversible migrations

## Consequences

- **Positive**: Clear ownership model from day one; provider-agnostic WhatsApp identity; proper async database access; migration history from start.
- **Negative**: PostgreSQL-specific types (UUID, TIMESTAMPTZ) — not SQLite-compatible. Requires PostgreSQL for local development or CI.
- **Migration**: Initial migration creates `students` and `whatsapp_identities` tables with constraints and indexes.

## Alternatives Considered

- **SQLite for dev, PostgreSQL for prod**: Rejected — different SQL dialects lead to production-only bugs.
- **Integer primary keys**: Rejected — UUIDs prevent enumeration attacks and work better in distributed systems.
- **Single User table with provider columns**: Rejected — doesn't support multiple identities per student or provider migration.