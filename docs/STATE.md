# STATE.md — Beru

## Current State

- **Last updated:** 2026-09-29
- **Current commit:** `fe726e6`
- **Current branch:** master

## Overall Project Status

Personal Alpha phase. Telegram bot is live and functional. Core intelligence pipeline (LLM → tool dispatch → deterministic backend) is wired. Presentation Layer with deterministic domain renderers and RendererRegistry is operational. Briefing scheduler is operational. Portal integration (Doctus) is implemented but not runtime-verified against live portal.

## IMPLEMENTED

- FastAPI application with lifespan management
- PostgreSQL database with SQLAlchemy 2.x async ORM
- Alembic migrations (10 migrations, chain verified)
- Student model with profile fields (name, attendance_target, briefing_time, timezone, lab_batch)
- Telegram Bot API adapter (long polling, message normalization, pure transport bridge, drop pending updates, HTML formatting with plain-text fallback retry on 400 error)
- Telegram identity linking (challenge/verify flow with audit, HTML formatted token)
- Telegram message handler (idempotency, request-scoped DB sessions, identity resolution, request-scoped domain services, conversation pipeline, HTML parse mode default)
- LLM provider abstraction (OpenAI-compatible + Mock; aliases for OpenRouter, Groq, OpenAI, NVIDIA, Ollama)
- Real LLM provider integration (wired in lifespan, dict/object message support, safe tool argument parsing)
- Conversation service (intent interpretation → tool dispatch → decoupled RendererRegistry dispatch, strict anti-async-hallucination instruction)
- Tool registry (automatic registration of all timetable and attendance tools)
- Deterministic presentation layer (`app/intelligence/rendering/`):
  - `RendererRegistry` dispatches tool execution results cleanly to domain renderers (`conversation.py` free of presentation switches)
  - `ScheduleRenderer`: structural period merging based on entry topology (`11:00 – 13:00 CM LAB`, `14:40 – 16:40 CF LAB`), dynamic batch resolution against student profile, faithful ambiguity preservation when batch is unknown
  - `AttendanceRenderer`: attendance metrics with bold labels, code badges, status indicators (✅, ⚠️), and deficit projections
  - `BriefingRenderer`: morning briefing cards with greeting, merged schedule, and key metrics
  - `StyleContract`: global standard enforcing 'Sir' honorific, bold labels, minimal emojis, and stripping repetitive greetings ('Hey Harsh!')
- Timetable service (state machine, extraction, confirmation, queries; no auto-confirm — explicit student confirmation required)
- Hybrid timetable extractor (PDF vector table extraction + RapidOCR fallback for scanned/image PDFs and photos)
- Timetable review surface (weekday grid formatter, photo upload through hybrid extractor, pending timetable with entries fetch)
- Timetable correction tools (get_extracted_timetable, update/add/delete entry — REVIEW_REQUIRED only)
- Briefing time setup tool (set_briefing_time)
- Week/weekday/metadata query tools (get_week_schedule, get_schedule_for_weekday with resilient weekday argument normalization, get_timetable_metadata)
- Course metadata mapped onto entries during extraction (course_code, faculty)
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

- 341 tests pass (3 warnings related to unawaited test mocks in telegram message handler)
- Test coverage: attendance, auth, briefing, briefing delivery, briefing scheduler, health, intelligence (real LLM provider, aliases, tool execution), models, portal, student profile, telegram isolation, telegram message handler (media download, photo through extractor, multi-turn context), telegram startup, timetable, whatsapp isolation, timetable end-to-end onboarding suite (`test_timetable_onboarding_e2e.py`: 19 tests), and golden output test suite (`test_golden_outputs.py`: 10 tests covering Batch 1, Batch 2, Unknown Batch ambiguity, structural period merging, next class, attendance summary, daily briefing, style contract, and registry dispatch)
- Flaky bug fixed: `test_get_next_class` clock flakiness resolved with deterministic `from_time`
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
- **Timetable Onboarding & Natural Language Querying Live on Telegram (Phase 4):**
  - Live PDF timetable upload and hybrid extraction of 28 schedule entries with classroom, branch, semester metadata.
  - Formatted weekday review grid presentation via Telegram.
  - Conversational lab batch resolution ("Batch 1" cleanly disambiguating slash labs, e.g., CF LAB selected over CN LAB).
  - Explicit timetable confirmation and version activation.
  - Natural-language schedule queries ("What classes do I have on Tuesday?") executing deterministic backend tool dispatch and delivering accurate Tuesday classes with timing and course names directly to the student on Telegram, confirmed by the user ("working absolutely fine!!").

## PARTIALLY IMPLEMENTED

- **Portal sync automation:** Portal adapter and sync service exist, but automatic sync before attendance queries is not wired into the conversation flow.
- **Error recovery in scheduler:** Failed briefing deliveries are recorded but not automatically retried.
- **Telegram message idempotency:** In-memory `_processed_updates` set is not persistent across restarts.

## KNOWN BUGS

None.

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
| Telegram | ✅ Live & User Verified | Bot polling, /start linking, message handling, media ingestion, schedule queries |
| LLM | ✅ Wired & Verified | Groq real provider active, natural multi-turn conversation, anti-hallucination guard |
| Authentication/Linking | ✅ Working | Challenge/verify flow, audit logging |
| Conversation Context | ✅ Working | Multi-turn history persistent per student session |
| Timetable | ✅ Live & User Verified | State machine, PDF/photo extraction, review grid, confirmation tool, batch resolution, queries |
| Attendance | ✅ Working | Deterministic calculations, simulations |
| Doctus Portal | ✅ Implemented | Login, parsing, sync; not runtime-verified |
| Briefing/Scheduler | ✅ Working | Per-student timezone, idempotent delivery |
| Database | ✅ Working | PostgreSQL, 10 migrations, all models |
| Workers | ✅ Working | Briefing scheduler as asyncio task |

## RECENT IMPORTANT CHANGES

| Commit | Description |
|--------|-------------|
| `fdaea24` | Fix LLM async promise hallucination and normalize weekday tool arguments |
| `cdbfef3` | Fix duplicate slash-lab entries during timetable extraction |
| `77f9271` | Fix MultipleResultsFound on timetable queries with limit(1) |
| `c2833d0` | Phase 4C: Full E2E pipeline, briefing scheduler integration & natural-language paraphrase simulation |
| `5c0c5f2` | Phase 4B: Security, boundary, failure-path & duplicate-upload hardening |
| `fabf9d2` | Phase 4A: Enrich academic profile, college domain self-model, and semantic tool definitions |
| `054488e` | Phase 3: Briefing time, week/weekday/metadata tools, course_metadata mapping |
| `f765640` | Fix Groq 400 by stripping student_id from LLM tool schemas and add graceful error fallback |
| `de13925` | Implement hybrid timetable extractor with RapidOCR fallback for scanned/image PDFs and photos |
| `f9ed817` | Fix timetable extraction state machine transition to REVIEW_REQUIRED before auto-confirmation and auto-increment version |
| `ec4fad8` | Fill real-usage gaps: Telegram PDF/media ingestion, timetable proactive prompt, confirm_timetable tool, multi-turn conversation context |

## CURRENT NEXT ACTION

Phase 4 (Timetable Domain Complete) fully USER_VERIFIED. Timetable extraction, confirmation, lab batch resolution, correction tools, and natural-language schedule queries are operating live and verified on Telegram. Ready to proceed to next planned domain (Doctus portal live verification / attendance workflows).