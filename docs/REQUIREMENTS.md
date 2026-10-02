# REQUIREMENTS.md — Beru

## LOCKED Requirements

### Product Requirements

1. **WhatsApp-first / Telegram-first interface** — No separate web/mobile app required for students. Telegram is the current Personal Alpha interface; WhatsApp is the future primary interface.
2. **Natural-language-first interaction** — No keyword routing. LLM interprets intent; backend executes typed tools.
3. **Secure authentication and authorization** — Identity derived from authenticated context; no username/password.
4. **Multi-user data isolation** — Student is ownership root; every resource access scoped to authenticated student.
5. **Auditability** — All security-sensitive operations logged immutably.
6. **Reliable background jobs** — Idempotent, handle duplicate execution gracefully.
7. **Daily briefing at student-configured time** — Per-student timezone and time preference.
8. **Attendance snapshots with provenance/timestamps** — Source, captured_at, semester_id tracked.
9. **Attendance simulations** — Non-mutating; deterministic calculations only.
10. **Timetable image upload/extraction/confirmation** — State machine enforced.

### Intelligence Requirements

1. **LLM is untrusted** — LLM output is never authoritative over backend data.
2. **Backend is the security boundary** — All operations pass through authorization.
3. **Typed tool dispatch** — LLM can only request allowlisted, typed tools with schemas.
4. **Deterministic attendance calculations** — All arithmetic in domain services; LLM never computes.
5. **Timetable vs actual attendance separation** — Planned classes ≠ actual attendance.
6. **No vector DB / embeddings / RAG** — Explicitly excluded.

### Authentication/Security Requirements

1. **Identity resolution** — External identity (Telegram/WhatsApp) → Identity model → Student.
2. **Authorization** — Every resource access validated against authenticated student.
3. **Audit logging** — All auth/authz events recorded immutably.
4. **No credential leakage** — Tokens, passwords, session cookies never logged or exposed.
5. **Challenge replay prevention** — Single-use, short-lived challenges.
6. **Ownership enforcement** — Server-side; client-supplied owner IDs never trusted.

### Telegram Requirements

1. **Telegram as Personal Alpha LIVE interface** — Bot API long polling.
2. **Identity linking** — /start → challenge → verify → link.
3. **Natural-language conversation** — LLM interprets intent; backend executes.
4. **Briefing delivery** — Per-student timezone/time; idempotent.
5. **Message idempotency** — Duplicate updates must not cause duplicate side effects.
6. **Graceful failure handling** — Background task exceptions logged; shutdown graceful.

### Attendance & Portal Requirements

1. **Deterministic calculations** — Percentage, simulation, recovery; no LLM arithmetic.
2. **Non-mutating simulations** — Simulations never modify actual attendance records.
3. **Stale/missing data handling** — Clearly distinguish: current verified, stale snapshot, unavailable portal, no synchronized data.
4. **Portal sync** — Read-only; credential security preserved.
5. **No fabrication** — Never fabricate attendance data. If the portal is down and no snapshot exists, return error/unavailable.
6. **Zero-Leak Credential Boundary** — Onboarding and reconnection happen through a multi-step interactive flow (`AWAITING_ROLL_NUMBER` → `AWAITING_PASSWORD`). Plaintext passwords must NEVER enter conversation context, LLM prompts, tool arguments, database logs, or normalized message payloads (`raw_provider_data` is redacted at the transport boundary). Password messages in Telegram must be deleted immediately after receipt.
7. **Auth-First Verification** — Credentials must be verified against live Doctus before being encrypted with Fernet and saved to the database. Failed authentication attempts must never overwrite or corrupt existing valid credentials.
8. **4-Hour Freshness Engine** — Attendance snapshots are fresh for 4 hours (`FRESHNESS_TTL = 4h`). Stale data triggers a background sync to Doctus. Concurrency is guarded per-student by `KeyedLockManager` to prevent duplicate portal requests.
9. **Provenance Tracking** — Every attendance query reports provenance (`PORTAL_LIVE_SYNC`, `PORTAL_SNAPSHOT_FRESH`, `PORTAL_SNAPSHOT_STALE`) and human-readable timestamp metadata.
10. **Resilient Fallback** — If live Doctus synchronization fails (network error, portal maintenance, session expiry), the system falls back to the latest verified cached snapshot with a warning note, rather than failing the user query.
11. **Dual Attendance Reporting** — Beru must report both overall (cumulative) attendance and current monthly attendance (e.g. October, 2026) when answering general attendance inquiries.
12. **Natural Conversational Continuity & Course Mapping** — Conversational follow-ups (e.g. "Per subject?") must resolve omitted entities from bounded dialogue state without brittle keyword matching; queries asking what course codes stand for must correlate codes to friendly names from confirmed timetables via `get_course_mapping` and report alternatives if conflicting entries exist.

### Timetable Requirements

1. **State machine** — UPLOADED → EXTRACTING → REVIEW_REQUIRED → CONFIRMED → ARCHIVED (FAILED possible).
2. **Only CONFIRMED timetables used** — For attendance projections and schedule queries.
3. **No auto-confirm** — Every successful extract stays in REVIEW_REQUIRED until the student explicitly confirms. Auto-confirm is disabled.
4. **Review surface** — After extraction, the parsed timetable is shown as a weekday grid (Mon-Sat) for student verification before confirmation. LLM tools `get_extracted_timetable`, `update_timetable_entry`, `add_timetable_entry`, `delete_timetable_entry` enable corrections during REVIEW_REQUIRED. After confirmation, `set_briefing_time` configures daily briefings, and `get_week_schedule`, `get_schedule_for_weekday`, `get_timetable_metadata` answer timetable questions from CONFIRMED data.
5. **Slash lab resolution** — Based on student's lab_batch; resolved at confirm time. `set_lab_batch` may resolve names for review display; confirm re-applies the same rule.
6. **Saturday has classes; Sunday has no classes.**

### LLM/Provider Requirements

1. **Provider abstraction** — Replaceable behind LLMProvider interface.
2. **Provider/model configurable** — Via environment/settings; no hardcoded credentials.
3. **No provider-specific logic in ConversationService** — Core depends only on interface.
4. **Retry/rate-limit behavior preserved** — Existing retry logic maintained.
5. **Explicit failure** — If real provider unavailable, fail explicitly; no silent fallback to mock in production path.

### Data/Ownership Requirements

1. **Student is ownership root** — All student-owned resources resolve through Student.id.
2. **Multi-user isolation from day one** — No cross-user data leakage.
3. **Resource ownership derived from authenticated identity** — Never from client input.
4. **Tenant isolation** — Context scoped to authenticated student and conversation.

### Deployment/Runtime Constraints

1. **Modular monolith** — Single deployment; no microservices without documented justification.
2. **PostgreSQL** — Primary datastore; no SQLite substitution.
3. **No unnecessary dependencies** — Each dependency must be justified.
4. **Configuration via environment** — .env file; no hardcoded secrets.

### Personal Alpha Requirements

1. **Harshik pilots personally** — Before controlled pilot.
2. **Telegram bot live** — @BeruHK_bot.
3. **Briefing scheduler operational** — Daily morning briefings delivered.
4. **Conversation pipeline functional** — LLM → tools → deterministic backend → response.

### Explicit Non-Goals / Deferred

- Web/mobile app (WhatsApp/Telegram is the interface)
- Vector DB / embeddings / RAG
- Multi-college tenancy
- Grade tracking / assignment submission
- Real-time collaboration features
- OCR fallback for timetable (image extraction is primary)
- Broader platform rollout (Personal Alpha → Controlled Pilot → Broader Platform)
- WhatsApp as primary interface (future; abstraction ready)
- Webhook-based Telegram updates (future; long polling current)
- Message queue for background jobs (future; in-process asyncio tasks current)
- Caching layer (future)
- Automatic portal sync before attendance queries (future; manual sync current)
- Retry mechanism for failed briefings (future; logged but not retried current)
- Persistent conversation context (future; fresh context per message current)