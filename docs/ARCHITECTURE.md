# ARCHITECTURE.md — Beru

## CURRENT IMPLEMENTATION

### High-Level Architecture

Beru is a modular monolith FastAPI application. All background workers run as asyncio tasks within the same process. The application is Telegram-first (Personal Alpha), with WhatsApp as a replaceable future adapter.

```
Telegram Bot API ←→ TelegramBotAdapter ←→ TelegramMessageHandler ←→ ConversationService ←→ LLM Provider
                                                                    ↓
                                                              ToolRegistry
                                                                    ↓
                                                    TimetableService / AttendanceService
                                                                    ↓
                                                              PostgreSQL (SQLAlchemy)
```

### Application Entry Point

- `backend/app/main.py` — FastAPI app with lifespan management
- Lifespan initializes: rate limiter, Telegram adapter, LLM provider, message handler, briefing scheduler
- Shutdown stops: briefing scheduler, message handler, Telegram adapter, LLM provider

### Module Boundaries

| Module | Purpose | Key Files |
|--------|---------|-----------|
| `app/api/` | HTTP endpoints | `health.py`, `dependencies.py` |
| `app/core/` | Configuration, database | `config.py`, `database.py` |
| `app/models/` | SQLAlchemy ORM models | `student.py`, `telegram_identity.py`, `telegram_linking_challenge.py`, `timetable.py`, `attendance.py`, `briefing_delivery.py`, `audit_event.py`, `whatsapp_identity.py`, `portal_credential.py` |
| `app/repositories/` | Database access layer | One repo per model |
| `app/schemas/` | Pydantic schemas | `student.py`, `whatsapp_identity.py` |
| `app/security/` | Auth, authorization, audit | `context.py`, `authentication.py`, `authorization.py`, `authorization_service.py`, `student_resolver.py`, `audit.py` |
| `app/intelligence/` | LLM + conversation + tools | `models/`, `providers/`, `services/`, `tools/` |
| `app/telegram/` | Telegram adapter + linking | `bot_adapter.py`, `message_handler.py`, `linking_service.py`, `auth.py`, `models.py`, `provider.py` |
| `app/whatsapp/` | WhatsApp abstraction (future) | `provider.py`, `models.py`, `auth.py`, `spike.py`, `baileys_adapter.py` |
| `app/integrations/portal/` | Doctus portal adapter | `doctus.py`, `parser.py`, `sync_service.py`, `credential_store.py`, `credentials.py`, `dto.py` |
| `app/workers/` | Background workers | `briefing_scheduler.py` |
| `app/llm/` | LLM abstraction (empty, providers in intelligence/) | `__init__.py` |

### Telegram Adapter

- `TelegramBotAdapter` — Long polling via Bot API (`getUpdates`/`sendMessage`)
- Normalizes updates to `IncomingTelegramMessage` / `OutgoingTelegramMessage`
- Handles `/start` command for identity linking (challenge creation)
- Challenge repository injected at startup (session-factory pattern)
- Idempotency: in-memory `_processed_updates` set (last 10K IDs)

### Identity/Authentication Flow

```
Telegram user sends message
  → TelegramBotAdapter._process_update → _handle_message
  → If /start: _handle_start_command (creates challenge, sends onboarding)
  → Else: queued to _message_queue
  → TelegramMessageHandler._process_messages consumes queue
  → TelegramIdentityResolver.resolve(incoming_identity)
  → DatabaseStudentResolver looks up TelegramIdentity by (provider, provider_user_id)
  → If ACTIVE → AuthenticatedIdentity(student_id)
  → If not found/inactive → UnauthenticatedIdentity
```

### Authorization/Ownership Boundary

- `Student` is the ownership root
- `TelegramIdentity` links external identity to Student
- `DatabaseStudentResolver` resolves external identity → Student
- Every resource access scoped to authenticated `student_id`
- Client-supplied owner IDs never trusted

### Conversation/Intelligence Flow

```
TelegramMessageHandler._handle_message(message)
  → Identity resolution (TelegramIdentityResolver)
  → StudentRepository.get_or_create(student_id)
  → StudentProfile built from persisted Student fields
  → StudentContext created
  → ConversationService.process_message(context, text)
    → _interpret_intent (LLM or mock)
    → If tool_request: _execute_tool
      → ToolRegistry.get(tool_name)
      → execute_timetable_tool / execute_attendance_tool
      → Deterministic backend execution
      → LLM generates natural response from tool result
    → If clarification: _handle_clarification
    → Else: direct LLM response
  → Response sent via TelegramBotAdapter.send_message
```

### LLM Provider Abstraction

- `LLMProvider` ABC in `app/intelligence/providers/base.py`
- `LLMProviderRegistry` — global registry, providers self-register on import
- `OpenAICompatibleLLMProvider` — works with OpenRouter, NVIDIA, OpenCode Zen, local models
- `MockLLMProvider` — deterministic test double
- `create_llm_provider()` factory in `app/intelligence/providers/__init__.py` — creates provider from settings
- Provider/model configurable via `.env` (`LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_BASE_URL`)
- Rate limiting per student via `RateLimiter`

### Tool Registry/Dispatch

- `ToolRegistry` in `app/intelligence/tools/registry.py`
- Tools: `get_today_schedule`, `get_tomorrow_schedule`, `get_next_class`, `get_first_class_tomorrow`, `get_timetable_status`, `needs_lab_batch`, `set_lab_batch`, `simulate_absence`
- LLM selects tool via function calling; backend validates and executes
- Tool results are deterministic; LLM only formats natural language response

### Domain Services

**TimetableService** (`app/intelligence/services/timetable_service.py`):
- State machine: `UPLOADED → EXTRACTING → REVIEW_REQUIRED → CONFIRMED → ARCHIVED` (FAILED possible)
- Only CONFIRMED timetables used for queries
- Slash labs resolved at confirm time based on student's `lab_batch`
- Deterministic schedule queries: today, tomorrow, next class, first class

**AttendanceService** (`app/intelligence/services/attendance_service.py`):
- Deterministic calculations: percentage, simulation, recovery
- Simulation formula: `((x + (N - m)) / (y + N)) * 100`
- No LLM involvement in arithmetic
- Snapshots with provenance (source, captured_at, semester_id)

**BriefingService** (`app/intelligence/services/briefing.py`):
- Transport-agnostic; no Telegram/WhatsApp imports
- Uses TimetableService + AttendanceService for facts
- Deterministic rendering (no LLM)
- Staleness detection (>7 days)

### Database/Persistence

- PostgreSQL via SQLAlchemy 2.x async
- `async_session_factory` in `app/core/database.py`
- Alembic migrations in `migrations/versions/`
- Models: Student, TelegramIdentity, TelegramLinkingChallenge, Timetable, TimetableEntry, AttendanceSnapshot, SubjectAttendance, BriefingDelivery, AuditEvent, WhatsAppIdentity, PortalCredential
- Repository pattern: one repo per model, session injected

### Background Workers

**BriefingScheduler** (`app/workers/briefing_scheduler.py`):
- Runs every 60 seconds (configurable)
- Finds active students with active Telegram identities
- Checks if briefing time has passed in student's local timezone
- Creates BriefingDelivery record (idempotent via unique constraint on student_id + delivery_date)
- Generates briefing via BriefingService
- Sends via TelegramBotAdapter
- Marks delivery as sent/failed

### Configuration

- Pydantic Settings in `app/core/config.py`
- `.env` file (gitignored)
- Key settings: `DATABASE_URL`, `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_BASE_URL`, `TELEGRAM_ENABLED`, `TELEGRAM_BOT_TOKEN`, `BRIEFING_SCHEDULER_INTERVAL_SECONDS`

### External Integrations

- **Telegram Bot API** — Long polling, sendMessage
- **Doctus Portal** — Login, semester retrieval, attendance HTML parsing
- **OpenAI-compatible APIs** — Chat completions with function calling

### Test Architecture

- pytest with `asyncio_mode = "auto"`
- `conftest.py` provides `client` fixture (AsyncClient for FastAPI app)
- Test files: `test_attendance.py`, `test_auth.py`, `test_briefing.py`, `test_briefing_delivery.py`, `test_briefing_scheduler.py`, `test_health.py`, `test_intelligence.py`, `test_models.py`, `test_portal.py`, `test_student_profile.py`, `test_telegram_isolation.py`, `test_telegram_startup.py`, `test_timetable.py`, `test_whatsapp_isolation.py`
- Mock-based unit tests; no live DB required for most tests
- `MockLLMProvider` for testing without real LLM calls

### Important Security Boundaries

- Backend is the security boundary; LLM is NOT
- LLM can only request allowlisted, typed tools
- External content (Telegram, portal, LLM output) is always untrusted
- Student ownership derived from authenticated identity, never from client input
- Audit logging for security-sensitive operations
- No credentials in logs or responses

### Important Data Flows

1. **Telegram message → Response:**
   Telegram → BotAdapter → MessageQueue → MessageHandler → IdentityResolver → ConversationService → LLM → ToolRegistry → DomainService → DB → LLM (response formatting) → BotAdapter → Telegram

2. **Briefing delivery:**
   Scheduler → StudentRepository → TelegramIdentityRepository → BriefingDeliveryRepository → BriefingService → TimetableService + AttendanceService → BotAdapter → Telegram

3. **Identity linking:**
   /start → Challenge creation → Student enters challenge → LinkingService.verify → TelegramIdentity creation → Audit log

---

## FUTURE/PLANNED ARCHITECTURE

### WhatsApp as Primary Interface

- WhatsApp provider abstraction already exists (`app/whatsapp/provider.py`)
- Baileys adapter spike complete (`app/whatsapp/baileys_adapter.py`)
- Future: WhatsApp becomes primary interface; Telegram remains as alternative

### Broader Platform

- Multi-college tenancy
- Controlled pilot with selected students
- Broader college-wide deployment

### Potential Future Enhancements

- Webhook-based Telegram updates (instead of long polling)
- Message queue for background jobs (currently in-process asyncio tasks)
- Caching layer for frequently accessed data
- More sophisticated conversation context persistence