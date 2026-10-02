# STATE.md — Beru

## Current State

- **Last updated:** 2026-10-02
- **Current commit:** `7188b47`
- **Current branch:** master

## Overall Project Status

Personal Alpha phase. Telegram bot is live and functional. Core intelligence pipeline (LLM → tool dispatch → deterministic backend) is wired. Presentation Layer with decoupled ResponseStyleLayer, deterministic domain renderers, and ResponseRendererRegistry is operational. Complete Attendance Intelligence Suite with deterministic safe bunk calculation, full-day leave simulations, attendance extremes, 100% target recovery boundary handling, and verified target mutation is operational. Action Integrity Invariant strictly prevents hallucinated mutations when no authorized mutation tool executes. Encyclopedic timetable querying, database room/faculty legend enrichment, and semantic-invariance testing are fully operational. Briefing scheduler is operational. Live Doctus portal integration with zero-leak credential onboarding, 4-hour freshness attendance sync, timetable-inferred semester resolution, unauthenticated redirect detection, concurrency locking, and provenance presentation is implemented and verified.

## IMPLEMENTED

- Complete Attendance Intelligence Suite & Action Integrity Invariant (`app/intelligence/services/attendance_service.py`, `app/intelligence/tools/attendance_tools.py`, `app/intelligence/rendering/attendance_renderer.py`, `app/intelligence/services/conversation.py`):
  - Action Integrity Invariant: Beru may only claim a state-changing action was completed when an authorized backend mutation tool executes successfully and returns a verified committed result. Text generation alone is never evidence of state mutation. Unsupported or un-executed mutation intents trigger graceful capability refusal (`GRACEFUL_CAPABILITY_REFUSAL`) instead of hallucinating success.
  - Attendance Target Mutation (`set_attendance_target`): Validates target percentage between 1.0% and 100.0%, enforces authorization, checks idempotency, commits to PostgreSQL, verifies committed state via fresh DB re-read, records `AuditEventType.STUDENT_UPDATED` in `audit_events`, and returns verified post-mutation progress and metrics.
  - Safe Bunk Calculation (`calculate_bunk_allowance`): Deterministic calculation of maximum classes that can be safely missed without dropping below target: $B_{\max} = \max(0, \lfloor \frac{A - t \cdot C}{t} \rfloor)$. Supports zero-conducted guards ($C=0 \implies 0$), below-target detection ($A/C < t \implies 0$), single-subject querying, and overall summary with per-subject breakdown.
  - Full-Day Absence Simulation (`simulate_day_absence`): Date-aware leave simulation enforcing confirmed timetable presence (`TIMETABLE_REVIEW_PENDING` / `NO_TIMETABLE` errors if unconfirmed/missing), filtering by student lab batch, aggregating multiple periods of the same course on a given day, and computing a 3-tier safety status (`overall_safe`, `subjects_safe`, `is_safe`).
  - Attendance Extremes Querying (`get_attendance_extremes`): Identifies highest and lowest attendance subjects with graceful multi-subject tie grouping, showing percentage, classes conducted/attended, and distance from target.
  - Recovery Calculations & 100% Boundary Handling (`calculate_recovery`, `calculate_classes_needed`): Computes classes needed to reach target percentage overall or per-subject; handles $T=100.0\%$ target boundary correctly (returns `achievable=False` with descriptive explanation if any class was ever missed; returns `0` classes if attendance is already 100.0%); eliminates floating-point precision ceil artifacts via rounded division.
  - Taxonomy & Structured Renderers: Formally separates tools into `MUTATION_TOOLS`, `SIMULATION_TOOLS`, and `READ_TOOLS` (`ATOMIC_QUERY_TOOLS`), with specialized deterministic renderers in `AttendanceRenderer` (`render_set_target`, `render_bunk_allowance`, `render_day_absence`, `render_extremes`) wired into `ResponseRendererRegistry`.
- FastAPI application with lifespan management
- PostgreSQL database with SQLAlchemy 2.x async ORM
- Alembic migrations (11 migrations, chain verified)
- Student model with profile fields (name, attendance_target, briefing_time, timezone, lab_batch, graduation_year)
- Live Doctus Portal Integration & 4-Hour Freshness Sync (`app/integrations/portal/` & `app/core/concurrency.py`):
  - ASP.NET Core Two-Step Authentication & Session Continuity: Modern EduPrime portal (`automation.vnrvjiet.ac.in`) uses ASP.NET Core anti-forgery tokens and authentication cookies. Implemented pre-flight `GET /Login` with robust `_extract_antiforgery_token`, URL-encoded form `POST /Login` with `xUsername`, `UserName`, `xPassword`, `__RequestVerificationToken`, and `RequestVerificationToken` headers. Authoritative session built directly from `self._client.cookies` with safe logging of established cookie keys (no secret values).
  - Verified App Workspace & In-Memory STDINFO Discovery: Replaced disproven `/Student/Dashboard` assumption with verified `/App` workspace. Discovers protected student ID dynamically from `popAtt()` in `/Shared/Widget/STDINFO`, storing it strictly in-memory in `DoctusSession` for the sync lifecycle without database persistence or roll-number leakage.
  - Unified Attendance Retrieval & Dynamic Semester Discovery: Initial call to `/Academic/Shared/GetStdAttPer?studentId=<id>&semId=undefined` simultaneously returns `#StdSemPop` semester options and the complete attendance dataset for the portal's active `selected` semester. If a non-default semester is explicitly requested, issues secondary parameterized request. Returns frozen `PortalAttendance` DTO directly consumed by `sync_service.py` without mutation or tuple branching.
  - Request-Specific Redirect Defense: Downstream authenticated GET requests (`/App`, `Shared/Widget/STDINFO`, `GetStdAttPer`) enforce `follow_redirects=False`. If any authenticated request returns a redirect (301/302/303/307/308) pointing to `/` or `/Login`, execution halts immediately with `DoctusSessionError`, preventing the public homepage from expiring the session cookie (`relic_VNRVJIET=; expires=Thu, 01 Jan 1970`).
  - Lenient Parser Resilience: `DoctusParser.parse_attendance` dynamically derives the active semester ID from the HTML `#StdSemPop` `selected` attribute when omitted or `undefined`, extracts overall metrics (attended, conducted, percentage across multiple formats), and parses valid subject rows gracefully without failing if individual HTML table rows vary.
  - Zero-Retry & Account Lockout Safeguards: Single-attempt login policy without background retry loops, immediate safe extraction of portal error messages (`Status == 0`, `BlockedUntil`, CAPTCHA), and safe non-sensitive exception handling preventing credential leakage.
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
- Dual Attendance Reporting (Overall Cumulative & Monthly):
  - Doctus HTML Parser (`DoctusParser._parse_overall_and_monthly`): Independently extracts monthly and cumulative metrics from EduPrime total rows (e.g., `Total | 6 / 6 (100) | 178 / 306 (58.17)`), disambiguating Fraction-First (`X / Y (P%)`) and Percentage-First (`P% (X / Y)`) forms, capturing current monthly period (e.g. `October, 2026`), and reconciling subject sums without overwriting portal-calculated aggregates.
  - Domain Model & Renderer: `OverallAttendanceResult` and `PortalAttendance` DTO carry `monthly_attended`, `monthly_conducted`, `monthly_percentage`, and `monthly_period`. `AttendanceRenderer` renders both Overall Attendance (cumulative) and Current Month Attendance with badge indicators.
- Async Greenlet Safety in Portal Sync (`PortalSyncService.sync_attendance`):
  - Pre-commit extraction of `snapshot_id`, `captured_at`, `overall_percentage`, and in-memory DTO `len(attendance.subjects)` before `await self.session.commit()`. Eliminates `MissingGreenlet` exceptions triggered by async lazy-loading of expired relationship attributes post-commit.
- Read-Time Legacy Snapshot Reconciliation (`AttendanceService._reconcile_snapshot_overall`):
  - Non-mutating read-time compatibility fallback: For legacy snapshots stored prior to parser fix where overall aggregates were truncated (e.g. `6/6` instead of `178/306`), validates `0 <= sum_att <= sum_cond`, `sum_cond > 0`, and `snapshot.overall_conducted < sum_cond`. Reconciles authoritative totals from verified subject rows at read time, logs a diagnostic warning, and sets `legacy_snapshot_reconciled=True`. When `overall_conducted >= sum_cond`, portal aggregates remain strictly authoritative.
- Deterministic Target Metrics & Plain Natural Language Reporting (`AttendanceService` & `AttendanceRenderer`):
  - Single backend source of truth for target arithmetic: calculates `target_percentage`, `target_difference` (`percentage - target`), `target_status` (`below`, `at_target`, `above`), and `target_gap_percentage` (`abs(target_difference)`).
  - Clean natural language formatting: Completely removed confusing jargon ("margin", "deficit", "cushion"). Formatted as `• Status: ⚠️ {gap:.1f}% more needed to reach {target:.0f}%` (when below), `• Status: ✅ At {target:.0f}% target` (when at target), and `• Status: ✅ {diff:.1f}% above {target:.0f}% target` (when above).
  - LLM guidance in `ContextBuilder` and `ConversationalResponsePolicy`: Instructs LLM to rely strictly on verified tool results for target progress without performing LLM-side arithmetic or hardcoded persona matching.
- Dynamic Course Mapping & Friendly Name Resolution (`app/intelligence/tools/timetable_tools.py` & `TimetableService`):
  - `get_course_mapping`: Reads confirmed timetable entries to correlate course codes (e.g. `25PC1CS201`) with friendly names (`OOPJ`) dynamically. Flags conflicting names with `status="conflict"` and alternatives rather than guessing.
  - Atomic Query Synthesis: Added `get_course_mapping` to `ATOMIC_QUERY_TOOLS` for natural-language synthesis answering "What does 25PC1CS201 stand for?". Removed `get_subject_codes` from tool definitions to prevent raw code dumps.
- Natural Multi-Turn Dialogue State Tracking (`app/intelligence/models/context.py` & `ConversationService`):
  - Bounded Dialogue Metadata: Tracks `last_domain`, `last_intent`, `last_tool`, `last_entity`, and `last_semester` on `ConversationContext`.
  - Contextual System Prompt Injection: Injects recent turn metadata into LLM system prompt so follow-up queries (e.g. "Per subject?") resolve omitted subjects and parameters via natural language reasoning without keyword matching.
- Defense-in-Depth Raw Output Prevention & Sanitization:
  - `sanitize_result_summary`: Strips HTML tags and redacts sensitive keys/values (passwords, tokens, cookies, raw HTML) before storing in conversation history.
  - Conversation Interceptor: Catch-all check in `ConversationService` catches any raw dictionary or list strings starting and ending with `{}`/`[]` and forces fallback through deterministic renderers.
- Tool registry (automatic registration of all 22 timetable and 8 attendance tools)
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

- 428 tests pass (3 warnings related to unawaited test mocks in telegram message handler)
- Test coverage: attendance, auth, briefing, briefing delivery, briefing scheduler, health, intelligence (real LLM provider, aliases, tool execution, multi-turn dialogue state, raw output prevention), models, portal, student profile, telegram isolation, telegram message handler (media download, photo through extractor, multi-turn context), telegram startup, timetable, whatsapp isolation, timetable end-to-end onboarding suite (`test_timetable_onboarding_e2e.py`: 19 tests), golden output test suite (`test_golden_outputs.py`: 14 tests), semantic-invariance and analytics suite (`test_semantic_invariance.py`: 13 tests), conversational synthesis suite (`test_conversational_synthesis.py`: 6 tests), conversational multi-turn suite (`test_conversational_multi_turn.py`: 3 tests), raw output prevention suite (`test_raw_output_prevention.py`: 3 tests), and the live portal integration & freshness test suites (17 tests in `test_portal_sync_and_freshness.py` verifying keyed locks, 4-hr TTL, redirect notices, post-commit greenlet safety, plain target status rendering, and non-mutating read-time legacy snapshot reconciliation, plus 48 tests in `test_portal.py` and portal security/onboarding suites)
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
| `e33cac9` | Allow null for optional tool arguments preventing Groq 400 validation error |
| `e043673` | Dual overall/monthly attendance, multi-turn dialogue state & course mapping |
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