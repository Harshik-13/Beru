# STATE.md — Beru

## Current State

- **Last updated:** 2026-09-29
- **Current commit:** `f765640`
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
- Timetable service (state machine, extraction, confirmation, queries; no auto-confirm — explicit student confirmation required)
- Hybrid timetable extractor (PDF vector table extraction + RapidOCR fallback for scanned/image PDFs and photos)
- Timetable review surface (weekday grid formatter, photo upload through hybrid extractor, pending timetable with entries fetch)
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

- 312 tests pass (1 pre-existing flaky: `test_get_next_class`, time-dependent)
- Test coverage: attendance, auth, briefing, briefing delivery, briefing scheduler, health, intelligence (real LLM provider, aliases, tool execution), models, portal, student profile, telegram isolation, telegram message handler (media download, multi-turn context), telegram startup, timetable (including confirm_timetable tool, extraction state machine transitions, and hybrid/OCR timetable extraction), whatsapp isolation
- Ruff: clean on all source files
- Mypy: clean on all source files

## RUNTIME VERIFIED

- Telegram bot initializes and connects (getMe succeeds)
- Telegram long polling is active (getUpdates loop running)
- Telegram /start flow creates challenge and sends onboarding message
- Telegram message handler processes messages through conversation pipeline with request-scoped database sessions
- Standard output logging configured via basicConfig with log_level from settings
- Real Groq LLM provider operational with tool calls (student_id stripped from LLM-facing schemas)
- Graceful error fallback: Telegram conversation errors send user-friendly message instead of silent drop
- Briefing scheduler queries active students and checks briefing time
- Database queries execute successfully (PostgreSQL)
- TelegramLinkingChallengeRepository session factory pattern works correctly
- Enum casting for PostgreSQL enum types works correctly
- Multi-turn conversation context maintains chat turns in memory
- Timetable awareness injected into LLM prompt
- TelegramBotAdapter download_file retrieves binary documents from Telegram Bot API

## USER VERIFIED

- User confirmed live conversational response on Telegram ("the response was good for testing, i spoke to it...").

## PARTIALLY IMPLEMENTED

- **Portal sync automation:** Portal adapter and sync service exist, but automatic sync before attendance queries is not wired into the conversation flow.
- **Error recovery in scheduler:** Failed briefing deliveries are recorded but not automatically retried.
- **Telegram message idempotency:** In-memory `_processed_updates` set is not persistent across restarts.

## KNOWN BUGS

- `test_get_next_class` is flaky (time-dependent; fails when test runs near end of day)

## KNOWN LIMITATIONS

- **In-memory conversation context:** Conversation context persists in-memory per student; restart resets conversation history.
- **In-memory idempotency:** Telegram update deduplication is in-memory only; restart loses state.
- **No automatic portal sync:** Attendance data must be manually synced; conversation flow doesn't trigger sync.
- **Single active Telegram identity:** Student can only have one active Telegram identity at a time.
- **No retry mechanism for failed briefings:** Failed deliveries are logged but not retried.
- **No webhook support:** Telegram uses long polling only; no webhook infrastructure.
- **Briefing scheduler is in-process:** Runs as asyncio task; not a separate worker process.

## CURRENT BLOCKERS

None.

## CURRENT INTEGRATION STATE

| Integration | Status | Notes |
|-------------|--------|-------|
| Telegram | ✅ Live | Bot polling, /start linking, message handling, media ingestion |
| LLM | ✅ Wired & Verified | Groq real provider active, natural multi-turn conversation |
| Authentication/Linking | ✅ Working | Challenge/verify flow, audit logging |
| Conversation Context | ✅ Working | Multi-turn history persistent per student session |
| Timetable | ✅ Working | State machine, PDF/photo extraction, review grid, confirmation tool, batch resolution |
| Attendance | ✅ Working | Deterministic calculations, simulations |
| Doctus Portal | ✅ Implemented | Login, parsing, sync; not runtime-verified |
| Briefing/Scheduler | ✅ Working | Per-student timezone, idempotent delivery |
| Database | ✅ Working | PostgreSQL, 10 migrations, all models |
| Workers | ✅ Working | Briefing scheduler as asyncio task |

## RECENT IMPORTANT CHANGES

| Commit | Description |
|--------|-------------|
| `HEAD` | Fix Groq 400 by stripping student_id from LLM tool schemas and add graceful error fallback |
| `de13925` | Implement hybrid timetable extractor with RapidOCR fallback for scanned/image PDFs and photos |
| `f9ed817` | Fix timetable extraction state machine transition to REVIEW_REQUIRED before auto-confirmation and auto-increment version |
| `ec4fad8` | Fill real-usage gaps: Telegram PDF/media ingestion, timetable proactive prompt, confirm_timetable tool, multi-turn conversation context |
| `f256662` | Fix LLM tool parameter schema conversion in OpenAI-compatible provider |
| `3d11e42` | Fix PostgreSQL native enum casting for Telegram identity and challenge models |
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

Server is running with the fix applied. User can now send "Batch 1" or similar messages and Beru will correctly call `set_lab_batch` and respond with confirmation.