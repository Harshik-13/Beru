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
- Pure transport bridge: captures incoming updates, translates to domain models, queues to `_message_queue`
- Decoupled from database, persistence, and domain linking logic
- Supports `parse_mode` (HTML/Markdown) on outgoing messages
- On startup, drops/acknowledges pending updates so stale bot messages do not cause unexpected processing
- Idempotency: in-memory `_processed_updates` set (last 10K IDs)

### Identity/Authentication Flow

```
Telegram user sends message
  → TelegramBotAdapter._process_update queues to _message_queue
  → TelegramMessageHandler._process_messages consumes queue
  → If /start: TelegramLinkingService creates challenge, sends onboarding message with formatted HTML token
  → Else:
      → DatabaseStudentResolver (request-scoped session) looks up TelegramIdentity by (provider, provider_user_id)
      → If ACTIVE → AuthenticatedIdentity(student_id)
      → If not found/inactive → UnauthenticatedIdentity (polite rejection sent)
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
  → Identity resolution (DatabaseStudentResolver in request-scoped session)
  → If authenticated:
      → StudentRepository.get_or_create(student_id)
      → StudentProfile built from persisted Student fields
      → StudentContext created
      → Fresh request-scoped TimetableService, AttendanceService, ConversationService instantiated
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
- `OpenAICompatibleLLMProvider` — works with OpenRouter, Groq, OpenAI, NVIDIA, Ollama, OpenCode Zen, and any OpenAI-compatible API
- `MockLLMProvider` — deterministic test double
- `create_llm_provider()` factory in `app/intelligence/providers/__init__.py` — resolves provider aliases and default endpoints (`openrouter`, `groq`, `openai`, `nvidia`, `ollama`, `opencode_zen`, `openai_compatible`)
- Provider/model configurable via `.env` (`LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_BASE_URL`)
- Supports message lists as either `LLMMessage` objects or raw dicts with tool-call roundtripping
- Rate limiting per student via `RateLimiter`

### Tool Registry/Dispatch

- `ToolRegistry` in `app/intelligence/tools/registry.py`
- All confirmed timetable tools and verified attendance tools auto-registered at startup via `register_builtin_tools()`
- Tools: `confirm_timetable`, `get_today_schedule`, `get_tomorrow_schedule`, `get_next_class`, `get_first_class_tomorrow`, `get_timetable_status`, `needs_lab_batch`, `set_lab_batch`, `get_extracted_timetable`, `update_timetable_entry`, `add_timetable_entry`, `delete_timetable_entry`, `get_overall_attendance`, `get_subject_attendance`, `get_attendance_summary`, `get_subjects_below_target`, `simulate_absence`, `calculate_classes_needed`, `get_attendance_snapshot_info`, `get_subject_codes`, `sync_attendance`
- Phase 1: Photo uploads routed through existing `HybridTimetableExtractor` (no new OCR/vision provider)
- Phase 2: Review tools (`get_extracted_timetable`, `update/add/delete_timetable_entry`) for corrections during REVIEW_REQUIRED; context builder blocks schedule queries from pending timetables
- Phase 3: `set_briefing_time`, `get_week_schedule`, `get_schedule_for_weekday`, `get_timetable_metadata` tools; course_metadata mapped onto entries during extraction
- LLM selects tool via standard OpenAI function calling schemas; backend validates and executes deterministically

### Presentation Layer, Conversational Synthesis & Renderer Registry

Beru uses a hybrid response generation architecture balancing conversational naturalness with mathematical and topological determinism:
```
Verified Tool Result
       │
       ├── Atomic Query (find_activity_details, find_faculty_details, find_room_details)
       │     └── Conversational Synthesis (ConversationalResponsePolicy) ──► Natural Response
       │
       └── Structured Collection (schedules, attendance math, analytics, briefings)
             └── Deterministic Domain Renderer (ScheduleRenderer, AttendanceRenderer, BriefingRenderer)
       │
       ▼
ResponseStyleLayer (Telegram HTML Sanitization & Entity Escaping) ──► Telegram Delivery
```

- **Conversational Synthesis & Persona Ownership** (`app/intelligence/conversation/policy.py` & `app/intelligence/models/identity.py`):
  - *Persona Ownership*: `"Sir"` is permanently anchored in Beru's self-model (`honorific: str = "Sir"` in `BeruIdentity`) and behavioral principle `respectful_persona`. It is not mechanically injected by renderers or regex post-processors.
  - *ConversationalResponsePolicy*: Governs natural-language synthesis for atomic queries. Enforces leading with the requested attribute first (room/location, professor, or timing), utilizing only relevant verified facts without database dumps, maintaining multi-turn continuity (resolving pronouns like "it"), and preserving ambiguity.
  - *Resilient Fallback*: If conversational synthesis fails (timeout or provider rate limit), the pipeline automatically falls back to the deterministic domain renderer.
- **RendererRegistry** (`app/intelligence/rendering/registry.py`): Central dispatch point routing structured tool execution results to dedicated domain renderers (`ScheduleRenderer`, `AttendanceRenderer`, `BriefingRenderer`). Fallback to `DefaultRenderer` for generic tools.
- **ScheduleRenderer** (`app/intelligence/rendering/schedule_renderer.py`):
  - *Structural Period Merging*: Algorithmically merges consecutive period entries (`e1.end_time == e2.start_time` for same subject, lab batch, and room) based on underlying entry topology into single cohesive spans (e.g. `11:00 – 13:00 CM LAB`, `14:40 – 16:40 CF LAB`).
  - *Dynamic Batch Resolution & Ambiguity Preservation*: Formats lab sessions according to the authenticated student's stored `lab_batch`. If unknown or unset, explicitly preserves slash ambiguity (`CF LAB / CN LAB [Batch 1 / Batch 2]`) and prompts for resolution rather than assuming Batch 1.
  - *Deterministic Missing-Field Omission*: Omits room and faculty labels when not specified in verified data.
- **AttendanceRenderer** (`app/intelligence/rendering/attendance_renderer.py`): Formats deterministic attendance summaries, subject breakdowns, deficit indicators (`⚠️`), met targets (`✅`), and simulation projections.
- **BriefingRenderer** (`app/intelligence/rendering/briefing_renderer.py`): Formats structured morning briefings with greeting, merged schedule, room codes, and key metrics.
- **ResponseStyleLayer & Telegram HTML Sanitization** (`app/intelligence/rendering/style_layer.py`):
  - Responsible for Telegram HTML validation and safety: safely escapes stray `<` and `>` into `&lt;` and `&gt;` while preserving valid Telegram HTML tags (`<b>`, `<i>`, `<code>`, `<pre>`, `<a>`). Normalizes layout spacing and strips repetitive greetings (`Hey Harsh!`). Does not alter sentence structures or mechanically inject honorifics.

### Domain Services

**TimetableService** (`app/intelligence/services/timetable_service.py`):
- State machine: `UPLOADED → EXTRACTING → REVIEW_REQUIRED → CONFIRMED → ARCHIVED` (FAILED possible)
- No auto-confirm — explicit student confirmation required
- Only CONFIRMED timetables used for queries
- Slash labs resolved at confirm time based on student's `lab_batch`
- Deterministic schedule queries: today, tomorrow, next class, first class
- `format_week_schedule()` — deterministic weekday grid formatter for review display
- `get_pending_timetable_with_entries()` — fetches pending timetable + entries for review

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