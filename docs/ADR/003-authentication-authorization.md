# ADR-003: WhatsApp-First Authentication and Authorization

## Status

Accepted

## Context

Beru is a WhatsApp-first college assistant. The student-facing interface is WhatsApp, not a web or mobile app. This fundamentally changes the authentication model:

- No username/password registration or login
- No OAuth flows for students
- No browser sessions or cookies for students
- Identity is derived from the WhatsApp provider/bridge
- The backend must resolve WhatsApp identity → Student before any authorization

## Decision

### 1. No Traditional Student Authentication

- **No passwords** — students never create or use passwords
- **No signup/login APIs** — onboarding is a separate, explicit process (future milestone)
- **No session management for students** — authentication is per-request via WhatsApp bridge

### 2. Provider-Neutral Identity Abstraction

```
WhatsApp Bridge
    ↓
IncomingIdentity (provider, external_identity_id)
    ↓
AuthenticationResolver (interface)
    ↓
StudentResolver implementation (DatabaseStudentResolver)
    ↓
WhatsAppIdentity lookup
    ↓
If ACTIVE → AuthenticatedIdentity (student_id, provider, method)
    ↓
AuthorizationService (context-based)
```

- **AuthenticationResolver** — abstract interface for plugging in different WhatsApp providers
- **StudentResolver** — abstract interface for resolving Student from external identity
- **DatabaseStudentResolver** — concrete implementation using WhatsAppIdentity table
- **AuthenticatedIdentity** — immutable dataclass carrying verified identity context

### 3. WhatsAppIdentity as the Link Table

- Separate entity from Student (not embedded)
- **Unique constraint** on `(provider, provider_user_id)` — prevents identity collision
- **Status enum** — `active`, `disabled`, `revoked` — only `active` grants access
- **Cascade delete** — deleting Student removes their WhatsAppIdentity records
- **Provider enum** — `unknown`, `whatsapp_web_js`, `baileys`, `meta_cloud_api` — extensible

### 4. Authorization Model

- **Service-layer enforcement** — repositories have no auth logic
- **AuthorizationService** — composable, used by domain services
- **Core primitives:**
  - `require_authenticated_identity()` — guard for authenticated context
  - `require_student()` — extract student_id from identity
  - `authorize_student_resource(auth_student_id, resource_owner_id)` — ownership check
  - `authorize_student_access(auth_student_id, target_student_id)` — cross-student access (currently self-only)
- **Never trust client-supplied IDs** — authenticated_student_id always from context

### 5. Audit Logging Foundation

- **AuditEvent** model — immutable, append-only
- **Event types** — authentication_success/failure, identity_disabled/revoked, unauthorized_access, authorization_failure, student_created, whatsapp_identity_created/updated
- **No sensitive data** — no secrets, tokens, raw message contents
- **Append-only** — no UPDATE/DELETE paths in application code
- **Indexes** — on (student_id, created_at) and (event_type, created_at)

## Consequences

### Positive

- **Security by design** — ownership enforcement at service layer, not repository
- **Provider flexibility** — swap WhatsApp bridge without changing core auth logic
- **Audit trail** — all security-relevant events recorded from day one
- **Testable** — abstract interfaces allow mocking for unit tests
- **No credential management** — no password hashing, reset flows, or session storage

### Negative

- **Bridge dependency** — requires a working WhatsApp bridge for any student interaction
- **No web fallback** — cannot test student features without WhatsApp bridge (mitigated by mock resolver in tests)
- **Onboarding complexity** — student creation requires explicit admin/operator action (future: invite flow)

## Alternatives Considered

### Traditional username/password with WhatsApp as secondary

- **Rejected** — contradicts WhatsApp-first architecture; adds credential management burden

### JWT tokens issued by WhatsApp bridge

- **Rejected** — adds complexity; bridge would need signing keys; not needed for internal service calls

### Embedding WhatsApp fields in Student table

- **Rejected** — doesn't support multiple identities per student or provider migration

## Migration

- New table: `audit_events` with indexes
- No changes to existing `students` or `whatsapp_identities` tables