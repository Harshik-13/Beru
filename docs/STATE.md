# STATE.md — Beru

## Current State

- **Last updated:** 2026-10-01
- **Current commit:** `b1f9644`
- **Current branch:** master

## Overall Project Status

Personal Alpha phase. Telegram bot is live and functional. Core intelligence pipeline (LLM → tool dispatch → deterministic backend) is wired. Presentation Layer with decoupled ResponseStyleLayer, deterministic domain renderers, and ResponseRendererRegistry is operational. Encyclopedic timetable querying (courses, labs, rooms, professors, schedule analytics), database room/faculty legend enrichment, and semantic-invariance testing are fully operational. Briefing scheduler is operational. Live Doctus portal integration with zero-leak credential onboarding, 4-hour freshness attendance sync, concurrency locking, and provenance presentation is implemented and verified.

## IMPLEMENTED

- FastAPI application with lifespan management
- PostgreSQL database with SQLAlchemy 2.x async ORM
- Alembic migrations (11 migrations, chain verified)
- Student model with profile fields (name, attendance_target, briefing_time, timezone, lab_batch, graduation_year)
- Live Doctus Portal Integration & 4-Hour Freshness Sync (`app/integrations/portal/` & `app/core/concurrency.py`):
  - Zero-Leak Credential Boundary: Interactive Telegram flow (`/connect_portal` or natural language 'connect my portal') steps student through `AWAITING_ROLL_NUMBER` → `AWAITING_PASSWORD`. Transport filter marks chat sensitive in `TelegramBotAdapter`, redacting `raw_provider_data` and log records, and calls Telegram Bot API `delete_message` immediately upon receiving password.
  - Auth-First Verification: Credentials verified against live Doctus before being encrypted with Fernet and saved to PostgreSQL. Failed authentication leaves existing working credentials untainted.
  - Lifecycle Tracking: Portal credentials track status (`CONNECTED`, `RECONNECT_REQUIRED`), `last_successful_auth_at`, `last_auth_failure_at`, and `last_sync_at`.
  - 4-Hour Freshness Engine: Attendance snapshots are considered fresh for 4 hours. Stale queries automatically trigger background Doctus sync.
  - Concurrency Locking: In-memory `KeyedLockManager` serializes concurrent portal requests per student, preventing duplicate Doctus requests and thundering herds.
  - Resilient Fallback & Zero Fabrication: If Doctus is unreachable (503, network drop, timeout), system falls back gracefully to the latest verified snapshot with `PORTAL_SNAPSHOT_STALE` provenance and a warning notice. If no cached snapshot exists, returns empty/unavailable without fabricating any attendance.
  - Attendance Provenance Presentation: `AttendanceRenderer` renders clean cards with provenance metadata badges (`📅 Synced live from Doctus just now`, `📅 Sourced from Doctus snapshot (time)`, `⚠️ Cached snapshot (Live refresh unavailable)`).
- Telegram Bot API adapter (long polling, message normalization, pure transport bridge, drop pending updates, HTML formatting with plain-text fallback retry on 400 error, sensitive chat redaction, message deletion)
- Telegram identity linking (challenge/verify flow with audit, HTML formatted token)
- Telegram message handler (idempotency, request-scoped DB sessions, identity resolution, request-scoped domain services, conversation pipeline, HTML parse mode default, credential onboarding flow interception)
- LLM provider abstraction (OpenAI-compatible + Mock; aliases for OpenRouter, Groq, OpenAI, NVIDIA, Ollama)
- Real LLM provider integration (wired in lifespan, dict/object message support, safe tool argument parsing, adaptive HTTP 429 backoff with Retry-After header parsing and non-crashing logger)
- Conversation service (intent interpretation → tool dispatch → hybrid presentation pipeline: conversational synthesis for atomic queries via ConversationalResponsePolicy; decoupled ResponseRendererRegistry dispatch for structured collections; strict anti-async-hallucination instruction)
- Tool registry (automatic registration of all 21 timetable and 8 attendance tools)
- Conversational Synthesis & Persona Architecture (`app/intelligence/conversation/` & `app/intelligence/models/`):
  - Self-Model Persona Ownership: Permanently moved `"Sir"` into Beru's self-model (`honorific: str = "Sir"` in `BeruIdentity`), with dedicated `respectful_persona` behavioral principle.
  - `ConversationalResponsePolicy`: Codified 7 conversational rules (answer actual question first, use only relevant verified details, avoid database card dumps, address student naturally as Sir, maintain multi-turn continuity, preserve ambiguity, eliminate premature promises).
  - Hybrid Execution Routing in `ConversationService`: Atomic queries (`find_activity_details`, `find_faculty_details`, `find_room_details`) synthesize direct natural-language answers over verified backend data; structured collections (schedules, attendance math, analytics, briefings) retain 100% deterministic renderers.
  - Resilient Fallback: Any failure during LLM synthesis seamlessly falls back to the deterministic domain renderer.
  - Pure Sanitization & Telegram Formatting Layer (`ResponseStyleLayer`): Strictly handles Telegram HTML safety, unescaped `<`/`>` escaping, greeting cleanup, and whitespace normalization without mechanical "Sir" injection or sentence alteration.
- Decoupled Presentation Layer (`app/intelligence/rendering/`):
  - `ResponseRendererRegistry`: Dispatches tool execution results cleanly to domain renderers, supporting both result types and tool names.
  - `ScheduleRenderer`: Pure data formatting without hardcoded personality; structural period merging based on entry topology (`11:00 – 13:00 CM LAB`, `14:40 – 16:40 CF LAB`), dynamic batch resolution against student profile, faithful ambiguity preservation when batch is unknown, deterministic missing-field omission (omits room and faculty when not specified). Renderers for activity details, faculty details, room details, and schedule analytics.
  - `AttendanceRenderer`: Pure data formatting for attendance metrics with bold labels, code badges, status indicators (✅, ⚠️), and deficit projections.
  - `BriefingRenderer`: Pure data formatting for morning briefing cards with schedule highlights and key metrics.
  - `StyleContract`: Global standard enforcing bold labels, minimal emojis, and stripping repetitive greetings ('Hey Harsh!').
- Encyclopedic Timetable Query Tools & Backend Logic (`app/intelligence/tools/timetable_tools.py`):
  - `find_activity_details`: Looks up courses/labs across the timetable or specific days; merges contiguous lab blocks; resolves student lab batch (`Batch 1`/`Batch 2`); reports room and faculty faithfully with automatic fallback to timetable `default_classroom` when specific room is not set.
  - `find_faculty_details`: Supports faculty directory mode, course/subject instructor lookup, and professor teaching schedules without unrelated room leakage.
  - `find_room_details`: Looks up classroom and lab schedules; checks against student's `default_classroom`.
  - `query_schedule_analytics`: Calculates deterministic timetable metrics:
    - `subject_count`: Course frequency per week and remaining sessions from current weekday forward.
    - `classes_vs_labs`: Lecture counts/hours vs practical lab counts/hours and total workload.
    - `daily_workload`: Hours and session count distribution per day (Mon–Sat) with busiest and lightest days.
    - `free_slots`: Calculates break periods and free intervals between scheduled classes.
  - Clarified semantic tool capabilities: `get_timetable_status` for document lifecycle state, `query_schedule_analytics` for quantitative calculations and counting.
- Database Room & Faculty Enrichment:
  - Confirmed timetable entries enriched with verified room, faculty, and course codes from the timetable PDF legend (`5_6185777998969446650.pdf`).
- Timetable service (state machine, extraction, confirmation, queries; no auto-confirm — explicit student confirmation required)
- Hybrid timetable extractor (PDF vector table extraction + RapidOCR fallback for scanned/image PDFs and photos)
- Timetable review surface (weekday grid formatter, photo upload through hybrid extractor, pending timetable with entries fetch)
- Timetable correction tools (get_extracted_timetable, update/add/delete entry — REVIEW_REQUIRED only)
- Briefing time setup tool (set_briefing_time)
- Week/weekday/metadata query tools (get_week_schedule with week/days dictionary key resolution, get_schedule_for_weekday with resilient weekday argument normalization, get_timetable_metadata)
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

- 385 tests pass (3 warnings related to unawaited test mocks in telegram message handler)
- Test coverage: attendance, auth, briefing, briefing delivery, briefing scheduler, health, intelligence (real LLM provider, aliases, tool execution), models, portal, student profile, telegram isolation, telegram message handler (media download, photo through extractor, multi-turn context), telegram startup, timetable, whatsapp isolation, timetable end-to-end onboarding suite (`test_timetable_onboarding_e2e.py`: 19 tests), golden output test suite (`test_golden_outputs.py`: 14 tests), semantic-invariance and analytics suite (`test_semantic_invariance.py`: 13 tests), conversational synthesis suite (`test_conversational_synthesis.py`: 6 tests), and the live portal integration & freshness test suites (21 tests across `test_portal_security.py`, `test_portal_onboarding.py`, `test_portal_semantic_routing.py`, and `test_portal_sync_and_freshness.py`)
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