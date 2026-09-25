# Threat Model — Beru

## Trust Boundaries

1. **External → Backend:** All inbound data (WhatsApp, portal, OCR, LLM) is untrusted.
2. **LLM → Backend:** LLM output is treated as untrusted input. Backend validates and authorizes.
3. **Backend → Database:** Backend is the security boundary. Authorization enforced here.
4. **Client → Backend:** Never trust client-supplied owner IDs or roles.

## Key Threats

| Threat | Mitigation |
|---|---|
| LLM manipulation (prompt injection) | LLM only selects from allowlisted typed tools. Backend authorizes every call. |
| Unauthorized resource access | Every resource access requires authorization against authenticated owner_id. |
| Data leakage between users | Multi-user isolation via owner_id on all resources. |
| Credential exposure | Never commit or log secrets. Use environment variables. |
| Duplicate message processing | Idempotent inbound event processing. |
| Attendance tampering via simulation | Simulations never mutate actual attendance records. |
| Portal scraping abuse | Read-only integration. No credential storage. No bypass of access controls. |
| WhatsApp account compromise | Bridge is replaceable. Core does not depend on single provider. |
| **External identity collision** | Unique constraint on (provider, provider_user_id) prevents same WhatsApp identity linking to multiple students. |
| **Ownership bypass via client input** | Student.id derived from authenticated session, never from client request. Repository layer does not enforce auth — service layer does. |
| **Database credential leakage** | DATABASE_URL from environment only. No hardcoded credentials. Migrations contain no secrets. |
| **Authentication bypass via identity spoofing** | WhatsAppIdentity status must be ACTIVE; disabled/revoked identities rejected. |
| **Disabled/revoked identity reuse** | StudentResolver checks status before returning AuthenticatedIdentity. |
| **Audit log tampering** | AuditEvent is append-only; no UPDATE/DELETE methods exposed. No public API for audit modification. |
| **Sensitive data in audit logs** | AuditEvent stores only metadata; no secrets, tokens, or raw message contents. |
| **Client-controlled student_id in authz** | AuthorizationService uses authenticated_student_id from context, never from request body/params. |

## Database-Specific Threats

| Threat | Mitigation |
|---|---|
| SQL injection | SQLAlchemy ORM with parameterized queries. No raw SQL in application code. |
| Connection string exposure | Environment variables only. `.env.example` contains no real credentials. |
| Migration tampering | Migrations are version-controlled. Review required for schema changes. |
| Enum value injection | Native enums disabled (`native_enum=False`); values validated at application layer. |

## Authentication-Specific Threats

| Threat | Mitigation |
|---|---|
| WhatsApp identity spoofing | Provider-neutral identity resolution; bridge must verify identity before calling resolver. |
| Replay attacks | Future: WhatsApp bridge provides message IDs; idempotency keys stored in audit. |
| Bridge compromise | AuthenticationResolver interface allows swapping providers; core not tied to single bridge. |
| Unknown identity enumeration | `get_identity_status` returns "unknown" for non-existent identities — no enumeration. |
| Privilege escalation via authz bypass | AuthorizationService enforces ownership at service layer; repository layer has no auth. |

## WhatsApp-Specific Threats

| Threat | Mitigation |
|---|---|
| **WhatsApp identity spoofing** | Provider-neutral identity resolution; bridge must verify identity before calling resolver. |
| **Replay attacks** | Idempotency keys stored in database with unique constraint; duplicate messages rejected at ingestion. |
| **Bridge compromise** | AuthenticationResolver interface allows swapping providers; core not tied to single bridge. |
| **Unknown identity enumeration** | `get_identity_status` returns "unknown" for non-existent identities — no enumeration. |
| **Privilege escalation via authz bypass** | AuthorizationService enforces ownership at service layer; repository layer has no auth. |
| **Session hijacking** | Session state (creds + Signal keys) encrypted at rest; keys rotated on each message; `creds.update` persisted immediately. |
| **QR code interception** | QR codes displayed only in secure terminal; never logged; pairing code alternative available. |
| **Provider-specific data leakage** | Provider abstraction boundary; core never receives raw Baileys/Meta objects. |
| **Idempotency key collision** | Keys include provider prefix; database unique constraint prevents collisions. |
| **Message content in logs** | Raw provider data never logged; only normalized event metadata in audit. |
| **Session credential theft** | Session credentials encrypted at rest; database access controlled; no plaintext in logs. |
| **WhatsApp Web protocol changes** | Provider abstraction allows swap; spike validates abstraction completeness. |
| **Baileys key management failure** | `creds.update` event handler mandatory; `useMultiFileAuthState` handles automatically; custom DB implementation must save on every `keys.set()`. |

## Future Threats (Post-Implementation)

- WhatsApp webhook signature validation (Meta Cloud API)
- LLM tool call schema validation
- Portal session hijacking prevention
- Rate limiting on API endpoints