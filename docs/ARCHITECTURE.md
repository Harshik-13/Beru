# Architecture — Beru

## Current State (Implemented)

- FastAPI application with health endpoint
- Environment-based configuration via Pydantic Settings
- Project structure with module boundaries
- Linting (ruff) and type checking (mypy) configured
- **Async SQLAlchemy 2.x database layer with PostgreSQL**
- **Student and WhatsAppIdentity models with UUID primary keys**
- **Repository pattern for data access**
- **Pydantic schemas for internal data validation**
- **Alembic migration for initial schema**
- **Ownership isolation tests**

## Planned Architecture

### Modular Monolith

Beru is a single-deployment application with clear module boundaries. Background workers run as isolated processes within the same deployment. Microservices are not planned unless there is a documented, unavoidable reason.

### Trust Boundaries

```
WhatsApp ──→ [WhatsApp Adapter] ──→ [API Layer] ──→ [Security/Auth] ──→ [Service Layer] ──→ [Domain Logic]
                                                                               │
LLM ──→ [LLM Adapter] ──→ [Tool Dispatcher] ──→ [Backend Authorization] ──┘    │
                                                                               │
College Portal ──→ [Portal Adapter] ──→ [Validation] ──→ [Service Layer] ──────┘
                                                                               │
                                                                               ▼
                                                                      [Database (PostgreSQL)]
```

- **Backend** is the security boundary. All operations pass through authorization.
- **LLM** is NOT a security boundary. It can only request allowlisted, typed tools.
- **External content** (WhatsApp, portal, OCR, LLM) is always untrusted.

### Module Map

| Module | Purpose | Status |
|---|---|---|
| `app/api/` | HTTP endpoints, request routing | Scaffolded |
| `app/core/` | Configuration, environment, database | Implemented |
| `app/domain/` | Deterministic business logic | Empty (planned) |
| `app/models/` | SQLAlchemy ORM models | **Implemented (Student, WhatsAppIdentity)** |
| `app/repositories/` | Database access | **Implemented (StudentRepository, WhatsAppIdentityRepository)** |
| `app/schemas/` | Pydantic request/response schemas | **Implemented (internal schemas)** |
| `app/services/` | Application services | Empty (planned) |
| `app/integrations/` | External adapters (portal, etc.) | Empty (planned) |
| `app/workers/` | Background jobs | Empty (planned) |
| `app/security/` | Auth, authorization, audit | Empty (planned) |
| `app/llm/` | LLM abstraction layer | Empty (planned) |
| `app/whatsapp/` | WhatsApp abstraction layer | Empty (planned) |

### Data Ownership Model

- Every resource has an `owner_id` derived from the authenticated user.
- Client-supplied owner IDs are never trusted.
- Multi-user isolation exists from day one.
- **Student is the ownership root** — all student-owned resources resolve ownership through `Student.id`.
- **WhatsAppIdentity links external identities to Student** — provider-neutral design allows multiple identity providers.

### Provider Abstraction Strategy

External providers are behind Python abstract base classes (ABCs) or Protocols. The core application depends only on the interface, not the implementation. Concrete providers live in `integrations/`, `whatsapp/`, and `llm/`.

### Database Transaction Convention

- Services control transaction boundaries.
- Repositories receive an `AsyncSession` and perform operations within it.
- Repositories do not commit; they flush to generate IDs.
- Services commit or rollback the transaction.

### Future: WhatsApp Flow

```
Student sends WhatsApp message
  → WhatsApp bridge receives webhook
  → Adapter normalizes message to internal event
  → API layer validates and authenticates
  → LLM adapter extracts intent + entities
  → Tool dispatcher selects typed tool
  → Backend authorizes and executes
  → Response flows back through adapter to WhatsApp
```

### Future: LLM/Tool Flow

```
Natural language input
  → LLM extracts intent and entities
  → LLM selects typed tool from allowlist
  → Backend validates tool request
  → Backend authorizes against ownership
  → Application service executes
  → Domain logic computes deterministic result
  → Structured result returned
  → LLM generates natural language response
```

### Future: Attendance Domain

Attendance calculation lives entirely in `app/domain/`. It is deterministic — no randomness, no LLM involvement in computation. The LLM provides the user's question; the domain service returns the answer.

### Future: Timetable State Machine

```
UPLOADED → EXTRACTING → REVIEW_REQUIRED → CONFIRMED → ARCHIVED
                   ↓
                 FAILED
```

Only `CONFIRMED` timetables are used for attendance projections.

### Future: Background Workers

Workers run as isolated processes. They consume from a job queue (to be determined). Workers must be idempotent and handle duplicate execution gracefully.

## Rollout Phases

| Phase | Scope | Status |
|---|---|---|
| 1 | Foundation scaffolding | ✅ Complete |
| 2 | Database, auth, multi-user ownership | 🚧 **In Progress** (DB + ownership foundation) |
| 3 | WhatsApp abstraction, message processing | Not started |
| 4 | LLM abstraction, tool dispatch | Not started |
| 5 | Attendance domain engine | Not started |
| 6 | Timetable ingestion and state machine | Not started |
| 7 | Daily briefing worker | Not started |
| 8 | College portal integration | Not started |
| 9 | Invite-only pilot | Not started |
| 10 | Broader college platform | Not started |

## Open Questions

- WhatsApp bridge choice for personal alpha (whatsapp-web.js vs Baileys vs official API)
- LLM provider selection
- Background job queue technology
- Deployment target (VPS, Railway, Fly.io, local)