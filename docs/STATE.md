# STATE.md — Beru

## Current State

- **Last updated:** 2026-09-29
- **Current commit:** `f256662`
- **Current branch:** master

## Overall Project Status

Personal Alpha phase. Telegram bot is live and functional. Core intelligence pipeline (LLM → tool dispatch → deterministic backend) is wired. Briefing scheduler is operational. Portal integration (Doctus) is implemented but not runtime-verified against live portal.

## IMPLEMENTED

- FastAPI application with lifespan management
- PostgreSQL database with SQLAlchemy 2.x async ORM
- Alembic migrations (10 migrations, chain verified)
- Student model with profile fields (name, attendance_target, briefing_time, timezone, lab_batch)
- Telegram Bot API adapter (long polling, message normalization, pure transport bridge, drop pending updates)
- Telegram identity linking (challenge/verify flow with audit, HTML formatted token)
- Telegram message handler (idempotency, request-scoped DB sessions, identity resolution, request-scoped domain services, conversation pipeline)
- LLM provider abstraction (OpenAI-compatible + Mock; aliases for OpenRouter, Groq, OpenAI, NVIDIA, Ollama)
- Real LLM provider integration (wired in lifespan, dict/object message support, safe tool argument parsing)
- Conversation service (intent interpretation → tool dispatch → personalized natural language response generation)
- Tool registry (automatic registration of all timetable and attendance tools)
- Timetable service (state machine, extraction, confirmation, queries)
- Attendance service (deterministic calculations, simulations, recovery)
- Briefing service (deterministic facts + natural language rendering)
- Briefing scheduler (per-student timezone/time, idempotent delivery)
- Briefing delivery tracking (PostgreSQL, unique constraint on student_id + delivery_date)
- Portal adapter (Doctus login, semester retrieval, attendance parsing)
- Portal credential store (encrypted)
- Portal sync service
- Security: authentication context, authorization, audit logging
- Multi-user isolation (Student ownership root)
- Rate limiting (per student, in-memory)

## TESTED

- 303 tests pass (1 pre-existing flaky: `test_get_next_class`, time-dependent)
- Test coverage: attendance, auth, briefing, briefing delivery, briefing scheduler, health, intelligence (real LLM provider, aliases, tool execution), models, portal, student profile, telegram isolation, telegram message handler, telegram startup, timetable, whatsapp isolation
- Ruff: clean on all source files
- Mypy: clean on all source files

## RUNTIME VERIFIED

- Telegram bot initializes and connects (getMe succeeds)
- Telegram long polling is active (getUpdates loop running)
- Telegram /start flow creates challenge and sends onboarding message
- Telegram message handler processes messages through conversation pipeline with request-scoped database sessions
- Standard output logging configured via basicConfig with log_level from settings
- LLM provider factory returns None for mock mode (default)
- Briefing scheduler queries active students and checks briefing time
- Database queries execute successfully (PostgreSQL)
- TelegramLinkingChallengeRepository session factory pattern works correctly
- Enum casting for PostgreSQL enum types works correctly

## USER VERIFIED

None explicitly confirmed by user.

## PARTIALLY IMPLEMENTED

- **Conversation context persistence:** Current implementation creates fresh `ConversationContext` per message. Multi-turn context is not persisted across messages. The `ConversationContext` model supports message history (max 10) but it's not stored between requests.
- **Portal sync automation:** Portal adapter and sync service exist, but automatic sync before attendance queries is not wired into the conversation flow.
- **Error recovery in scheduler:** Failed briefing deliveries are recorded but not automatically retried.
- **Telegram message idempotency:** In-memory `_processed_updates` set is not persistent across restarts.

## KNOWN BUGS

- `test_get_next_class` is flaky (time-dependent; fails when test runs near end of day)

## KNOWN LIMITATIONS

- **No persistent conversation context:** Each Telegram message creates a fresh `ConversationContext`. Multi-turn conversations don't carry history between messages.
- **In-memory idempotency:** Telegram update deduplication is in-memory only; restart loses state.
- **No automatic portal sync:** Attendance data must be manually synced; conversation flow doesn't trigger sync.
- **Single active Telegram identity:** Student can only have one active Telegram identity at a time.
- **No retry mechanism for failed briefings:** Failed deliveries are logged but not retried.
- **LLM provider defaults to mock:** `.env` has `LLM_PROVIDER=mock`; real LLM requires configuration.
- **No webhook support:** Telegram uses long polling only; no webhook infrastructure.
- **Briefing scheduler is in-process:** Runs as asyncio task; not a separate worker process.

## CURRENT BLOCKERS

None.

## CURRENT INTEGRATION STATE

| Integration | Status | Notes |
|-------------|--------|-------|
| Telegram | ✅ Live | Bot polling, /start linking, message handling |
| LLM | ✅ Wired | Provider abstraction complete; mock by default |
| Authentication/Linking | ✅ Working | Challenge/verify flow, audit logging |
| Conversation Context | ⚠️ Partial | Fresh context per message; no persistence |
| Timetable | ✅ Working | State machine, extraction, queries |
| Attendance | ✅ Working | Deterministic calculations, simulations |
| Doctus Portal | ✅ Implemented | Login, parsing, sync; not runtime-verified |
| Briefing/Scheduler | ✅ Working | Per-student timezone, idempotent delivery |
| Database | ✅ Working | PostgreSQL, 10 migrations, all models |
| Workers | ✅ Working | Briefing scheduler as asyncio task |

## RECENT IMPORTANT CHANGES

| Commit | Description |
|--------|-------------|
| `008d890` | Fix real LLM provider message conversion, auto-register tools, add provider aliases, enrich conversational response |
| `cb61881` | Decouple TelegramBotAdapter, scope session per message in TelegramMessageHandler, fix startup logging |
| `055bb09` | Fix TelegramLinkingChallengeRepository session lifetime and enum casting |
| `635e5ff` | Integrate real LLM provider into Telegram conversation flow |
| `2570ae7` | Add BERU_STATE.md and update AGENTS.md with state-file workflow |
| `2c16e7d` | Align TelegramLinkingChallengeStatus enum with DB enum values |
| `00471e1` | Fix Telegram startup wiring — logging, error handling, enum fix |
| `7db7f76` | Repair alembic migration chain duplicate revision and enum creation |
| `512dadd` | Persist student profile name and attendance target |
| `b34f58a` | Add daily morning briefing scheduler with Telegram delivery |
| `5609fb9` | Implement Telegram conversation integration |
| `13eed5b` | Implement Telegram identity linking |
| `7fb5675` | Add Telegram Bot API startup verification and error handling |
| `c32e1ee` | Add Telegram Bot API adapter foundation |

## CURRENT NEXT ACTION

Implement persistent conversation context for Telegram multi-turn conversations. Current implementation creates fresh `ConversationContext` per message; need to persist context across messages scoped to authenticated student.