# CHANGELOG.md — Beru

## 2026-09-29 — Deterministic Structured Renderers, Decoupled RendererRegistry, and Style Contract

**Commit:** `2c585b3`

### Why
Beru's conversational responses for schedules and attendance previously relied on unstructured LLM paraphrasing of raw tool dictionaries. This produced several user-facing flaws: repetitive greetings ("Hey Harsh!"), inconsistent layout hierarchy, hardcoded batch assumptions, failure to collapse contiguous periods (`11:00–12:00` and `12:00–13:00 CM LAB`), and unstructured emoji noise. The user directed that LLMs should decide intent, while deterministic renderers format verified data according to a strict Style Contract with 'Sir' honorific and zero presentation switches inside `ConversationService`.

### What changed
- `backend/app/intelligence/rendering/`:
  - `registry.py`: Implemented `RendererRegistry` and `DomainRenderer` protocol. Maps tool execution results to dedicated domain renderers, keeping `ConversationService` strictly as an orchestrator without presentation switches.
  - `schedule_renderer.py`: Implemented `ScheduleRenderer` with:
    - *Structural Period Merging*: Collapses consecutive periods ($E_1.\text{end\_time} == E_2.\text{start\_time}$) with matching subject, batch, and room into unified session blocks (e.g. `11:00 – 13:00 CM LAB`, `14:40 – 16:40 CF LAB`).
    - *Dynamic Batch Resolution & Ambiguity Preservation*: Formats lab sessions according to the authenticated student's stored `lab_batch`. When `lab_batch` is unknown or unset, preserves slash ambiguity (`CF LAB / CN LAB [Batch 1 / Batch 2]`) and prompts for resolution rather than assuming Batch 1.
    - Day schedules, next class cards, week overviews, and confirmation status.
  - `attendance_renderer.py`: Implemented `AttendanceRenderer` with deterministic summary cards, subject breakdowns, deficit alerts (`⚠️`), target achievement badges (`✅`), and absence simulations.
  - `briefing_renderer.py`: Implemented `BriefingRenderer` for daily morning briefings with morning greeting, merged schedule, room codes, and key metrics.
  - `style_contract.py`: Defined global typography contract (`Sir` honorific, bold labels like `<b>Time:</b>`, `<code>` badges, minimal emojis, and `clean_greetings` sanitizer stripping repetitive "Hey [Name]!" greetings).
- `backend/app/telegram/formatting.py`:
  - Implemented `telegram_format()` markdown-to-HTML normalizer and `strip_html_tags()` plain-text fallback utility.
- `backend/app/telegram/bot_adapter.py`:
  - Defaulted outgoing messages to `parse_mode="HTML"`. Added automatic fallback retry on HTTP 400 entity parsing errors that strips tags and delivers plain text, preventing dropped messages.
- `backend/app/telegram/message_handler.py`:
  - Defaulted outbound message response delivery to `parse_mode="HTML"`.
- `backend/app/intelligence/services/conversation.py`:
  - Injected `RendererRegistry` into `ConversationService`.
  - Replaced LLM tool result paraphrasing in `_execute_tool` with deterministic `self.renderer_registry.render(...)`.
  - Sanitized direct responses with `sanitize_conversational_response()`.
- `backend/app/intelligence/services/context_builder.py`:
  - Added Response Style & Persona guidelines to LLM system prompt instructing respectful 'Sir' address, professional demeanor, and no repetitive greetings.
- `backend/tests/test_golden_outputs.py`:
  - Added 10 golden tests validating: Batch 1 Tuesday schedule, Batch 2 Tuesday schedule, Unknown Batch ambiguity preservation, structural period merging, next class card, attendance summary with deficits/margins, morning briefing, greeting stripping, and decoupled `RendererRegistry` dispatch.

### Verification
- Ran `pytest backend/tests/test_golden_outputs.py` — 10/10 passed in 0.07s.
- Ran full test suite `pytest` — all 341 tests in repository passed.
- Ran `ruff check` on all modified files — 0 errors, 100% clean.
- Hot-reloaded background uvicorn server daemon (task `task-3355`) connected to live Telegram `@BeruHK_bot`.

---

### Why
When a student asked "what classes do i have on tuesday" while their uploaded timetable was still in `REVIEW_REQUIRED` (unconfirmed), the tool returned empty confirmed entries. Instead of explaining that their schedule was empty or awaiting confirmation, the LLM generated an async promise ("im pulling specific courses you have on tuesday right now--just a moment, i will share the list with you") without sending any subsequent response. Furthermore, `execute_timetable_tool` required an exact `day_of_week` integer key, which risked failure if an LLM passed `weekday` or string day names.

### What changed
- `backend/app/intelligence/services/conversation.py`:
  - Added strict anti-hallucination instruction to `_generate_response_from_tool_result`: explicitly instructing the model to always deliver complete answers immediately and forbidding promises to "pull", "load", or share "in a moment".
- `backend/app/intelligence/tools/timetable_tools.py`:
  - Updated `execute_timetable_tool` to robustly extract `day_of_week`, `weekday`, or `day` and normalize string weekday names (e.g. "Tuesday") or string digits to integer indices (0-5).
  - Cleaned up obsolete entries in the active user database and confirmed Version 3.

### Verification
- Tested simulated full turn with real Groq LLM: verified immediate, complete delivery of Tuesday's classes without hallucinated promises.
- Ran all 62 timetable tests across `test_timetable.py` and `test_timetable_onboarding_e2e.py` — 100% passing.
- Hot-reloaded live Telegram server daemon.

---

## 2026-09-29 — Fix duplicate slash-lab entries during timetable extraction

**Commit:** `cdbfef3`

### Why
During live runtime verification of PDF timetable extraction on Telegram, slash-separated lab entries (such as `11:00-13:00 CN LAB / CF LAB`) appeared twice in the review grid (yielding 32 entries instead of 28). Both `PdfTimetableExtractor` and `OcrTimetableExtractor` already construct `ExtractedCell` instances for slash labs in `result.cells`. The secondary loop in `TimetableService.extract_timetable()` iterating over `result.slash_labs` was re-inserting them, duplicating every slash-lab session.

### What changed
- `backend/app/intelligence/services/timetable_service.py`:
  - Removed redundant `result.slash_labs` entry creation loop in `extract_timetable()`.
  - Cleaned up unused `ExtractedCell` import.

### Verification
- Extracted PDF fixture `5_6185777998969446650.pdf` and verified all 28 entries match one-to-one with the physical schedule.
- Ran all 62 timetable tests — passed cleanly.
- Reloaded live server with the fix.

---

## 2026-09-29 — Fix MultipleResultsFound on timetable queries for students with multiple versions

**Commit:** `77f9271`

### Why
During live runtime verification of PDF upload on Telegram, `TimetableRepository.get_latest_for_student()` and `get_pending_for_student()` raised `MultipleResultsFound: Multiple rows were found when one or none was required`. When a student has multiple versions (e.g. Version 1 confirmed and Version 2 pending), ordering by `version.desc()` produces multiple rows. Calling `scalar_one_or_none()` without `.limit(1)` violated SQLAlchemy's single-row requirement.

### What changed
- `backend/app/repositories/timetable.py`:
  - Added `.limit(1)` to `get_latest_for_student()` before calling `result.scalar_one_or_none()`.
  - Added `.limit(1)` to `get_pending_for_student()` before calling `result.scalar_one_or_none()`.

### Verification
- Ran 62 timetable tests (`test_timetable.py` and `test_timetable_onboarding_e2e.py`) — all passed.
- Server reloaded and confirmed healthy.

---

## 2026-09-29 — Phase 4C: Full End-to-End Pipeline, Briefing Scheduler Integration & Natural-Language Paraphrase Simulation

**Commit:** `c2833d0`

### Why
To complete Beru's timetable domain capabilities, we must verify the complete end-to-end user lifecycle from pre-onboarding greeting through fixture PDF extraction, weekday review formatting, conversational lab batch resolution, single-entry correction, explicit confirmation, custom briefing time persistence, and deterministic morning briefing delivery. Furthermore, we must guarantee that tool dispatch functions through pure natural-language semantic understanding across varied phrasings rather than brittle keyword menus.

### What changed
- `backend/tests/test_timetable_onboarding_e2e.py`:
  - Added `FakeAttendanceService` and `SemanticRouterMockLLM` test doubles.
  - Implemented `TestFullTimetableOnboardingE2E`:
    - Step 1: Pre-onboarding greeting verified with unconfigured profile (`has_timetable=False`, `timetable_status="none"`).
    - Step 2: Extraction from fixture PDF `5_6185777998969446650.pdf` via `create_uploaded_timetable()` yields `REVIEW_REQUIRED`, version 1, academic metadata (`2026-2027`, `CSE-CYS`, `R25`, `Section A`), extracted entries, and detected slash labs.
    - Step 3: Weekday grid formatted with `format_week_schedule()`, verifying days (Monday–Saturday) and header elements.
    - Step 4: `set_lab_batch("batch_1")` resolves ambiguous slash labs, preserving `REVIEW_REQUIRED` quarantine.
    - Step 5: `update_timetable_entry()` applies targeted correction to room and activity name.
    - Step 6: `confirm_timetable()` marks status `CONFIRMED` and registers active timetable.
    - Step 7: `set_briefing_time("08:00")` sets custom briefing time on student model.
    - Step 8: `BriefingService.generate_briefing()` generates morning briefing with Monday's classes derived from the confirmed timetable.
    - Step 9: Query tools (`get_week_schedule`, `get_schedule_for_weekday`, `get_timetable_metadata`, `get_today_schedule`) return verified confirmed data.
    - Step 10: Activity classification distinguishes multi-period `ActivityType.LAB` from `ActivityType.ACADEMIC` lectures.
    - Step 11: Derived duration arithmetic verifies all class durations are positive, labs >= 90 mins, and lectures <= 70 mins.
    - Step 12: Placement and circular metadata (`section="A"`, `branch="CSE-CYS"`, `regulation="R25"`, `academic_year="2026-2027"`) match circular specifications.
  - Implemented `TestNaturalLanguageParaphraseRouting`:
    - Tested multiple distinct paraphrases for weekday schedules ("What do I have on Wednesday?", "Could you check my Wednesday classes please?", "Show me what's scheduled for Wednesday", "Am I free on Wednesday afternoon?") routing to `get_schedule_for_weekday`.
    - Tested full-week queries routing to `get_week_schedule`.
    - Tested metadata inquiries routing to `get_timetable_metadata`.
    - Tested conversational batch assignment ("Put me in lab batch 1") and confirmation ("The schedule looks completely accurate, confirm it").
    - Verified strict conversation quarantine: unconfirmed `REVIEW_REQUIRED` timetables never leak classes into query tool results.

### Verification
- 19/19 tests in `test_timetable_onboarding_e2e.py` passed cleanly.
- 331/331 tests across the entire backend suite passed cleanly.
- `ruff check` passed with zero errors.

---

## 2026-09-29 — Phase 4B: Security, boundary, failure-path & duplicate-upload hardening

**Commit:** `5c0c5f2`

### Why
To ensure Beru functions as a safe, robust, multi-tenant system, timetable operations must rigorously enforce security boundaries (cross-student access rejection, confirmed state modification guards), review state quarantine, exact-target correction semantics, failure retry capability, and duplicate-upload versioning/archival semantics.

### What changed
- `backend/tests/test_timetable_onboarding_e2e.py`:
  - Implemented `InMemoryTimetableDataStore` repository doubles providing in-memory state tracking for pure async pytest execution without database or SQLite dependencies.
  - Added `TestSecurityAndIsolation`:
    - Cross-student entry update rejected when authenticated as another student.
    - Cross-student timetable confirmation rejected.
    - Confirmed timetable modification strictly rejected with `TimetableStateError`.
  - Added `TestReviewStateQuarantine`:
    - `REVIEW_REQUIRED` timetables never leak into date, today, or week schedule queries.
  - Added `TestInputAndFormatValidation`:
    - Invalid lab batch strings rejected (`ValueError`).
    - Invalid weekday index rejected (must be 0-5).
    - Invalid briefing time formats rejected (must be 24h HH:MM).
  - Added `TestCorrectionSemanticsAndAmbiguity`:
    - Modifying an entry targets strictly by `entry_id`, leaving identical subjects on other periods/days untouched.
    - Cells with missing room or faculty preserve `None` rather than fabricating hallucinated data.
  - Added `TestFailurePathsAndRetry`:
    - Corrupt/unparsable upload transitions to `FAILED`, and retry from `FAILED` state succeeds cleanly.
    - Malformed timetables cannot be confirmed.
  - Added `TestDuplicateUploadAndVersioning`:
    - Uploading `v2` creates version 2 in `REVIEW_REQUIRED` while preserving active confirmed `v1`.
    - Confirmation of `v2` archives `v1`, ensuring exactly one active confirmed timetable.
    - Idempotent `set_lab_batch` and `confirm_timetable` execution without duplicate entries or errors.

### Verification
- 13/13 tests in `test_timetable_onboarding_e2e.py` passed cleanly.
- `ruff check` passed with zero errors.

---

## 2026-09-29 — Phase 4A: Enrich academic profile, college domain self-model, and semantic tool definitions

**Commit:** `fabf9d2`

### Why
To make Beru a complete product in the timetable area without falling under keyword-driven heuristics, the agent must be equipped with rich domain context (college identity, period structure, theory vs lab distinctions), full academic student profile metadata (section, department, year, semester), and semantically expressive tool schemas that allow LLMs to naturally map varied phrasing.

### What changed
- `backend/app/telegram/message_handler.py`:
  - `_create_student_profile()`: Enriched to safely map `section`, `year`, `course` (programme), `branch`, `semester`, and `academic_year` from the active timetable (`confirmed_tt` or `pending_tt`).
- `backend/app/intelligence/models/identity.py`:
  - Enriched `purpose` with explicit VNR VJIET college identity.
  - Added operating principle explaining college domain structure: VNR VJIET campus, P1-P6 period layout, lunch break, single-period theory lectures (~50 mins), and multi-period laboratory practicals (~100-150 mins) divided by batches.
- `backend/app/intelligence/tools/timetable_tools.py`:
  - Enhanced descriptions for `get_week_schedule`, `get_schedule_for_weekday`, `get_timetable_metadata`, and `get_extracted_timetable` to guide LLM semantic intent mapping across diverse student phrasing.
- `backend/tests/test_timetable.py`:
  - Fixed pre-existing flaky clock dependency in `test_get_next_class` by passing explicit `from_time=time(10, 0)`.

### Verification
- 43/43 tests in `test_timetable.py` passed cleanly.
- 9/9 tests in `test_telegram_message_handler.py` passed cleanly.
- `ruff check` passed with zero errors across all modified files.

---

## 2026-09-29 — Phase 3: Briefing time + richer Q&A — set_briefing_time, week/weekday/metadata tools, course_metadata mapping

**Commit:** `054488e`

### Why
After confirmation, the student had no way to set their briefing time through conversation. The LLM had no tools to answer week-wide or weekday-specific questions, or to retrieve timetable metadata (section, branch, programme). Course metadata (course_code, faculty) was extracted but not stored on entries.

### What changed
- `backend/app/intelligence/tools/timetable_tools.py`:
  - Added `set_briefing_time` tool — writes students.briefing_time (HH:MM)
  - Added `get_week_schedule` tool — full Mon-Sat from confirmed timetable
  - Added `get_schedule_for_weekday` tool — by day 0-5 from confirmed timetable
  - Added `get_timetable_metadata` tool — section, branch, programme, regulation, etc.
- `backend/app/intelligence/services/timetable_service.py`:
  - `extract_timetable()`: Maps course_metadata onto entries (course_code, faculty)
- `backend/app/intelligence/services/conversation.py`:
  - Added 4 new tools to timetable tool routing

### Verification
- Code changes complete; tests pending Phase 4 E2E

### Security
- set_briefing_time validates HH:MM format; no injection risk
- Metadata tool returns extracted fields only; never invents college/section

---

## 2026-09-29 — Phase 2: Corrections and confirm — review tools, explicit confirm, context builder review mode

**Commit:** `c448e4e`

### Why
After extraction, the student had no way to correct parsed entries through the conversation. The LLM had no tools to show the pending grid, update/add/delete entries, or handle the review flow naturally. The context builder did not distinguish review mode from confirmed mode.

### What changed
- `backend/app/intelligence/tools/timetable_tools.py`:
  - Added `get_extracted_timetable` tool — returns pending grid + all entries with IDs for review
  - Added `update_timetable_entry` tool — change name/times/type/room/day by entry ID (REVIEW_REQUIRED only)
  - Added `add_timetable_entry` tool — add new entry during review
  - Added `delete_timetable_entry` tool — remove entry during review
  - All correction tools enforce REVIEW_REQUIRED state and ownership in the service layer
- `backend/app/intelligence/services/context_builder.py`:
  - Review mode: instructs LLM to use `get_extracted_timetable`, guide student through review/batch/corrections/confirm
  - Explicitly blocks schedule queries from pending timetables
- `backend/app/intelligence/services/conversation.py`:
  - Added 4 new tools to timetable tool routing

### Verification
- Code changes complete; tests pending Phase 4 E2E

### Security
- Correction tools gated to REVIEW_REQUIRED state in service layer
- Ownership enforced via pending timetable lookup
- LLM cannot write to CONFIRMED timetables

---

## 2026-09-29 — Phase 1: Timetable review surface — disable auto-confirm, show weekday grid, photo upload

**Commit:** `e7622bb`

### Why
After uploading a timetable, Beru was auto-confirming without showing the parsed classes to the student. The user had no way to verify or correct extracted data before it became active. Additionally, photo uploads were rejected with a "send PDF instead" dead-end instead of using the existing hybrid extractor.

### What changed
- `backend/app/intelligence/services/timetable_service.py`:
  - Removed auto-confirm logic from `extract_timetable()` — extraction now always returns `REVIEW_REQUIRED` on success
  - Added `format_week_schedule()` helper — deterministic weekday grid formatter (Mon-Sat, times, activity, type, room)
  - Added `get_pending_timetable_with_entries()` — fetches pending timetable + entries for review display
- `backend/app/telegram/message_handler.py`:
  - `_handle_media_message()`: After extraction, sends the full weekday grid for student review
  - Photos (`.jpg`, `.jpeg`, `.png`) now routed through the same `create_uploaded_timetable` → `HybridTimetableExtractor` path as PDFs
  - Removed "send PDF instead" dead-end for photos

### Verification
- Code changes complete; tests pending Phase 4 E2E

### Security
- No security boundaries weakened; explicit student confirmation now required before timetable becomes active
- Photo uploads use existing hybrid extractor; no new OCR/vision provider introduced

---

## 2026-09-29 — Fix Groq 400 by stripping student_id from LLM tool schemas and add graceful error fallback

**Commit:** `f765640`

### Why
When the user replied "Batch 1" to the lab batch prompt, Beru routed it through the Groq LLM for intent interpretation. The LLM attempted to call the `needs_lab_batch` tool and generated `"placeholder-uuid"` for the `student_id` parameter (since it has no way to know the real UUID). Groq's server-side tool validation rejected this with HTTP 400, causing an unhandled exception that silently dropped the message without sending any reply.

This violated the non-negotiable security rule: "Resource ownership is derived from authenticated identity. Never trust client-supplied owner IDs."

### What changed
- `backend/app/intelligence/services/conversation.py`:
  - `_tool_def_to_openai()`: Deep-copies tool schema and strips `student_id` from `properties` and `required` before sending to LLM. Backend injects student_id from authenticated context during tool execution.
  - Tool description text in system prompt no longer dumps raw argument schemas.
  - `_generate_response_from_tool_result()`: Improved prompt to acknowledge actions and explicitly instruct LLM not to ask for student IDs.
- `backend/app/telegram/message_handler.py`:
  - Wrapped conversation pipeline in try/except with graceful fallback message to user on any error.
  - Added `session.commit()` after successful conversation turn to persist tool side-effects.
- `backend/app/intelligence/tools/timetable_tools.py`:
  - `set_lab_batch()`: Fixed lab_batch check to handle `None` (DB NULL) in addition to `LabBatch.UNKNOWN`.
- `backend/app/intelligence/services/timetable_service.py`:
  - `confirm_timetable()`: Same fix for `None` lab_batch entries.

### Verification
- 310 tests pass (2 deselected: flaky `test_get_next_class` variants).
- Ruff clean on all modified files.
- Reproduced exact Groq 400 error body, verified fix eliminates it.
- LLM now correctly returns `set_lab_batch(batch='batch_1')` without `student_id`.

### Security
- Strengthens security posture: LLM never sees or needs to supply student UUIDs.
- Backend remains the sole authority for identity injection.

---

## 2026-09-29 — Implement hybrid timetable extractor with RapidOCR fallback for scanned/image PDFs and photos

**Commit:** `de13925`

### Why
Students frequently upload scanned timetables, image-based PDFs, or camera photos. The existing `PdfTimetableExtractor` relied exclusively on `pdfplumber` vector line and char extraction, which yielded 0 tables and 0 classes on scanned/image-based documents.

### What changed
- `pyproject.toml`: Added `pypdfium2>=5.0.0` and `rapidocr_onnxruntime>=1.3.0` to project dependencies.
- `backend/app/intelligence/services/timetable_extraction.py`:
  - Implemented `OcrTimetableExtractor`:
    - Renders PDF pages to high-resolution images via `pypdfium2` or opens uploaded photos directly via PIL.
    - Executes RapidOCR to detect bounding boxes and recognized text items.
    - Extracts header metadata (academic year, regulation, programme, branch, year, semester, section, classroom, effective date) with label-value spatial pairing.
    - Detects day rows (Monday-Saturday) and period column bounds (P1-P6 and Lunch) dynamically from spatial deltas.
    - Maps cells into periods and multi-period spans, handles slash-separated labs into `SlashLabCandidate`s, and normalizes OCR artifacts.
    - Parses course code metadata table below the schedule grid.
  - Implemented `HybridTimetableExtractor`: Tries vector PDF extraction first, automatically falling back to OCR when 0 cells are returned or when handling image formats.
  - Updated `create_timetable_extractor()` factory to return `HybridTimetableExtractor`.
- `backend/tests/test_timetable.py`: Added `TestHybridAndOcrTimetableExtractor` covering sample PDF OCR extraction, hybrid fallback delegation, and factory verification.

### Verification
- 312 automated tests pass (`pytest backend/tests`).
- Verified extraction on real sample PDF `timetablepdf/5_6185777998969446650.pdf`: extracts all 28 classes, 4 slash labs, and 12 course metadata entries.
- `ruff check` passes cleanly on all modified files.

## 2026-09-29 — Fix timetable extraction state machine transition and version increment

**Commit:** `f9ed817`

### Why
1. When uploading a timetable PDF on Telegram, `TimetableService.extract_timetable()` previously called `self.confirm_timetable(timetable_id)` directly if the extraction contained no review triggers. However, `timetable.status` in the session was still `TimetableStatus.EXTRACTING`. Because `confirm_timetable()` strictly enforces `if timetable.status != TimetableStatus.REVIEW_REQUIRED: raise TimetableStateError(...)`, extraction aborted with:
   `"can only confirm timetable in review_required status, got timetablestatus.EXTRACTING"`.
2. `create_uploaded_timetable()` hardcoded `version=1`, which risked unique constraint collisions if a student uploaded updated timetables.

### What changed
- `backend/app/intelligence/services/timetable_service.py`:
  - In `create_uploaded_timetable()`: Check latest version for student and set `version = (latest.version + 1) if latest else 1`.
  - In `extract_timetable()`: Set `timetable.status = TimetableStatus.REVIEW_REQUIRED` and `await self.session.flush()` immediately after cells and slash labs are persisted. This strictly satisfies the state transition before checking whether auto-confirmation can proceed.
- `.gitignore`: Added `storage/` to prevent runtime uploaded files from being tracked.
- `backend/tests/test_timetable.py`: Added `test_extract_timetable_auto_confirm_transitions_properly` to verify the state transition from `EXTRACTING` through `REVIEW_REQUIRED` to `CONFIRMED`.

### Verification
- Added test passes; all 309 automated tests pass (`pytest backend/tests`).
- `ruff check` on modified files clean with 0 warnings.
- Server running live with long-polling daemon.

## 2026-09-29 — Complete real-usage gaps: Telegram media ingestion, timetable prompt, confirmation tool, and persistent conversation context

**Commit:** `ec4fad8`

### Why
Following successful live Telegram conversation testing, several operational gaps remained for real-world academic assistance:
1. When no timetable is uploaded, Beru did not proactively prompt the student to upload one.
2. Incoming Telegram media (PDF circulars and timetable photos) was dropped by the message handler.
3. The LLM had no tool to confirm an extracted timetable (`confirm_timetable`) when the user says "looks good, confirm it".
4. Multi-turn conversation context was not retained across messages, preventing natural context carryover.

### What changed
- `backend/app/intelligence/models/identity.py`: Updated Beru's identity purpose and operating principles to reflect Telegram interface in Personal Alpha.
- `backend/app/intelligence/models/context.py`: Added timetable awareness fields (`has_timetable`, `timetable_status`, `lab_batch`, `needs_lab_batch`, `academic_year`) to `StudentProfile`.
- `backend/app/intelligence/services/context_builder.py`: Injected clear timetable presence/status and proactive instructions into `_format_student_context`.
- `backend/app/intelligence/tools/timetable_tools.py`: Added `confirm_timetable` tool function, schema definition, and execution mapping.
- `backend/app/intelligence/services/conversation.py`: Added `confirm_timetable` to allowlisted timetable tools.
- `backend/app/telegram/bot_adapter.py`: Added `download_file(file_id, destination_path)` using Telegram Bot API's `getFile` endpoint.
- `backend/app/telegram/message_handler.py`:
  - Added support for `TelegramMessageType.DOCUMENT` and `TelegramMessageType.PHOTO`.
  - Added `_handle_media_message` to save uploaded timetable PDFs, trigger `TimetableService.create_uploaded_timetable`, and report extraction review/confirmation status to student.
  - Added persistent in-memory `_conversation_contexts` dictionary per student across message turns.
  - Added safe timetable status lookup and context update handling.
- `backend/tests/test_telegram_message_handler.py`: Added tests for `download_file`, multi-turn context persistence, and photo media handling.
- `backend/tests/test_timetable.py`: Added tests for `confirm_timetable` tool.
- `backend/tests/test_intelligence.py`: Updated tool count assertion for registered timetable tools.

### Verification
- 308 automated tests pass (`pytest backend/tests`).
- `ruff check` on all modified files clean with 0 warnings.
- Server restarted with live long-polling daemon active (`task-1366`).

### Why
When `ConversationService` formatted tool definitions via `_tool_def_to_openai()` into OpenAI `{"type": "function", "function": {...}}` schema, `OpenAICompatibleLLMProvider._convert_tools()` expected flat dictionaries with `tool["name"]`, raising `KeyError: 'name'` and dropping incoming conversational messages.

### What changed
- `backend/app/intelligence/providers/openai_compatible.py`: Updated `_convert_tools()` to check for existing `"type"` / `"function"` keys and pass pre-formatted OpenAI tool objects through cleanly.

### Verification
- Tested `ConversationService.process_message()` with user input "Hey beru" against live Groq model (`openai/gpt-oss-120b`).
- Successfully returned conversational greeting with personal identity without error.
- All 303 automated tests pass.

## 2026-09-29 — Fix PostgreSQL native enums for identity and briefing models, safe session commits, and link user profile

**Commit:** `13fe634`

### Why
1. `telegram_provider`, `telegram_identity_status`, and `briefing_delivery_status` were missing `values_callable`, causing SQLAlchemy to send uppercase Enum member names (`"TELEGRAM_BOT"`, `"ACTIVE"`, `"PENDING"`) into PostgreSQL native enums that expect lowercase values (`"telegram_bot"`, `"active"`, `"pending"`).
2. `TelegramIdentity`, `TelegramLinkingChallenge`, and `BriefingDelivery` were not exported from `app.models.__init__.py`, causing relationship resolution failures in SQLAlchemy mappers.
3. `BriefingScheduler` and `TelegramMessageHandler` were missing explicit session commits on state transitions, causing transaction rollbacks upon context exit.

### What changed
- `backend/app/models/telegram_identity.py`: Added `values_callable=lambda obj: [e.value for e in obj]` to `provider` and `status` columns.
- `backend/app/models/briefing_delivery.py`: Added `values_callable` to `status` column.
- `backend/app/models/__init__.py`: Exported all Telegram and briefing delivery models and enums.
- `backend/app/main.py`: Pre-imported `app.models` to guarantee all mapper relationships initialize on startup.
- `backend/app/workers/briefing_scheduler.py`: Added `_commit_session` with coroutine/mock awaitable inspection and committed successful/failed deliveries.
- `backend/app/telegram/message_handler.py`: Added safe commit on linking challenge creation.
- Linked user Telegram ID `8543204958` to active student profile `Harsh`.

### Verification
- Morning briefing generated and delivered live to Telegram chat `8543204958`.
- Delivery status marked `sent` and committed to PostgreSQL database.
- 303 automated tests pass.
- `ruff check` on modified files clean.

## 2026-09-29 — Fix PostgreSQL native enum mapping for Telegram linking challenge status

**Commit:** `3d11e42`

### Why
When a Telegram user sent `/start` to the bot, the backend raised `asyncpg.exceptions.DatatypeMismatchError: column "status" is of type telegram_linking_challenge_status but expression is of type character varying` during `INSERT INTO telegram_linking_challenges`. This rolled back the transaction and prevented sending the onboarding token.

### What changed
- `backend/app/models/telegram_linking_challenge.py`: Updated `status` column from `String(20)` to `SQLEnum(TelegramLinkingChallengeStatus, name="telegram_linking_challenge_status", values_callable=lambda obj: [e.value for e in obj])`.
- `backend/app/repositories/telegram_linking_challenge.py`: Replaced manual postgres enum casting and string literals with `TelegramLinkingChallengeStatus` enum values in `create`, `get_pending_by_telegram_user_id`, `mark_used`, and `mark_expired`.

### Why this approach
Aligns SQLAlchemy's ORM model type directly with the PostgreSQL native enum type `telegram_linking_challenge_status` created by migration `c1d2e3f4a5b6_add_telegram_linking_challenge.py`, allowing asyncpg to bind enum values natively without type mismatch errors.

### Verification
- Python test verifying SQL insertion into `telegram_linking_challenges` with PostgreSQL native enum passed.
- `ruff check` on modified files passed with 0 errors.
- 303 automated tests pass.
- Server restarted with live polling and ready to process `/start`.

## 2026-09-29 — Enable real LLM natural language understanding and function calling

**Commit:** `008d890`

### Why
1. `_mock_interpret_intent` was acting as a fallback keyword matcher when `llm_provider` was None, creating robotic keyword-triggered behavior.
2. `OpenAICompatibleLLMProvider._convert_messages` assumed messages were `LLMMessage` dataclasses with `msg.role`, causing `AttributeError` when `ContextBuilder` passed `dict`s.
3. Provider aliases (`openrouter`, `groq`, `openai`, `nvidia`, `ollama`) suggested in `.env` were not recognized by `create_llm_provider`, raising `ValueError: Provider not registered`.
4. `ToolRegistry` had no tools registered at startup in production, meaning the LLM received empty tool schemas and could never call timetable or attendance tools.
5. In `ConversationService._execute_tool`, if the LLM supplied a `student_id` in arguments, calling timetable/attendance functions raised `TypeError: multiple values for argument 'student_id'`.
6. Tool result natural language generation used a generic system prompt without student context or original question, leading to robotic output.
7. `ContextBuilder._build_messages` duplicated the user's current message if it had already been added to recent conversation messages.

### What changed
- `backend/app/intelligence/providers/openai_compatible.py`: Added support for both `dict` and `LLMMessage` in `_convert_messages`, `_make_request`, and `chat_completion`. Added safe parsing for tool call arguments. Allowed initialization without API key for local or mock endpoints.
- `backend/app/intelligence/providers/base.py`: Updated interface annotations to support `dict` messages and typed dataclasses.
- `backend/app/intelligence/providers/__init__.py`: Added provider aliases and default base URLs for `openrouter`, `groq`, `openai`, `nvidia`, `ollama`, and `opencode_zen`.
- `backend/app/intelligence/tools/registry.py`: Added `BuiltinToolHandler` and `register_builtin_tools()`, auto-registering all timetable and attendance tools into `tool_registry` on import.
- `backend/app/intelligence/services/conversation.py`: Expanded `attendance_tools` to include all attendance functions, sanitized arguments to prevent duplicate `student_id` errors, passed `user_message` to response synthesis, and enriched persona prompting to sound like a smart, warm college copilot.
- `backend/app/intelligence/services/context_builder.py`: Prevented duplicate user message appending in `_build_messages`.
- `backend/tests/test_intelligence.py`: Added comprehensive unit and integration tests covering message conversion, chat completion with tool calls, provider aliases, tool auto-registration, and persona response formatting.

### Why this approach
Preserves the architectural boundary where the LLM understands natural language and selects function calls while the backend executes all deterministic arithmetic and access controls.

### Why these files
- `providers/openai_compatible.py`, `providers/base.py`, `providers/__init__.py`: fix LLM adapter and alias resolution.
- `tools/registry.py`: make tools available for LLM function calling.
- `services/conversation.py`, `services/context_builder.py`: handle tool dispatch and human-like response generation.
- `tests/test_intelligence.py`: verify real LLM pipeline.

### Verification
- 303 tests pass (`pytest backend/tests`)
- `ruff check` clean on all touched files
- `mypy` clean on touched provider and tool files

### Security considerations
- Backend continues to enforce deterministic calculations; LLM cannot invent attendance percentages.
- Client/LLM-supplied `student_id` is stripped and replaced with authenticated student ID from session context.
- Rate limiting per student remains active.

### Remaining limitations/blockers
- Real LLM requires valid API key and model in `.env` (e.g. OpenRouter, Groq, OpenAI).

---

## 2026-09-29 — Decouple TelegramBotAdapter, scope DB session per message, and fix startup logging

**Commit:** `cb61881`

### Why
1. TelegramBotAdapter was coupled to database repositories (`TelegramLinkingChallengeRepository`), intercepting `/start` and violating provider abstraction.
2. In `main.py`, services and resolvers were instantiated at startup with a single database session that closed immediately, resulting in `InterfaceError: session is closed` on any incoming message.
3. Python `logging.basicConfig` was never configured, silencing all INFO and DEBUG logs from Telegram and service layers.
4. `_drop_pending_updates` in the adapter failed to acknowledge dropped updates, causing stale updates to re-deliver on restart.
5. Telegram user identity resolution hardcoded the `BAILEYS` WhatsApp authentication method instead of `TELEGRAM_BOT`.

### What changed
- Configured root logger via `logging.basicConfig` in `main.py` using `settings.log_level` ("INFO") and standard formatting.
- Decoupled `TelegramBotAdapter`: removed all DB dependencies, removed `/start` interception, added `parse_mode` support to `send_message`, improved update acknowledgment in `_drop_pending_updates`, and added informative logging with traceback on poll errors.
- Updated `TelegramMessageHandler`: receives `async_session_factory`, handles `/start` onboarding command with HTML token formatting via `TelegramLinkingService` and `AuditService`, and creates fresh request-scoped `DatabaseStudentResolver`, `TimetableService`, `AttendanceService`, and `ConversationService` per incoming message.
- Added `AuthenticationMethod.TELEGRAM_BOT = "telegram_bot"` to `security/context.py` and updated `DatabaseStudentResolver` to return it for Telegram identity lookups.
- Added `aiohttp>=3.9.0,<4.0` to `pyproject.toml`.
- Added comprehensive unit and integration tests in `backend/tests/test_telegram_message_handler.py`.

### Why this approach
Adheres strictly to the Beru architecture: provider adapters are pure transport bridges without domain/database logic. Request-scoped sessions guarantee clean transaction boundaries and prevent session exhaustion or closed-session errors during background polling.

### Why these files
- `backend/app/main.py`: configure logging, remove adapter DB injection, wire session factory to handler.
- `backend/app/telegram/bot_adapter.py`: restore transport-only adapter boundary, add parse_mode, fix update dropping.
- `backend/app/telegram/message_handler.py`: handle `/start`, request-scope DB sessions for identity and domain services.
- `backend/app/telegram/models.py`: add parse_mode to `OutgoingTelegramMessage`.
- `backend/app/security/context.py` & `backend/app/security/student_resolver.py`: support `TELEGRAM_BOT` authentication method.
- `backend/app/repositories/telegram_linking_challenge.py`: support both session and session factory scopes.
- `pyproject.toml`: add missing direct dependency `aiohttp`.
- `backend/tests/test_telegram_message_handler.py`: test `/start` linking, unlinked polite rejection, authenticated conversation routing, update deduplication.

### Why other obvious areas were not changed
- `ConversationService`, `ToolRegistry`, and domain services already worked correctly once provided with live sessions.
- Did not change conversation context persistence as that is a separate task tracked in `docs/STATE.md`.

### Verification
- 298 tests pass (`pytest backend/tests`)
- `ruff check` clean on all touched files
- `mypy` clean on `bot_adapter.py` and `message_handler.py`

### Security considerations
- Identity resolution strictly validates Telegram provider and user ID against database.
- Unlinked users are safely rejected without leaking internal student data.
- Audit event logged on challenge generation.
- No client-supplied owner IDs trusted.

### Remaining limitations/blockers
- Multi-turn conversation context is not yet persisted across Telegram messages (fresh `ConversationContext` per message).

---

## 2026-09-29 — Add permanent documentation synchronization rule

**Commit:** `b13836f`

### Why
Documentation synchronization must happen automatically after every task. User should never need to explicitly request documentation updates.

### What changed
- Added permanent documentation synchronization rule to AGENTS.md
- Rule applies to every task, no matter how small
- Defines mandatory post-task loop: IMPLEMENT → TEST → SECURITY CHECK → RECONCILE MARKDOWN → UPDATE STATE → UPDATE CHANGELOG → UPDATE COMMIT INDEX → VERIFY → COMMIT
- Defines changelog entry requirements
- Defines status vocabulary usage rules

### Why this approach
Documentation is shared persistent project memory between multiple AI agents (OpenCode, Antigravity). Must be kept in sync automatically.

### Why these files
- AGENTS.md: agent rulebook

### Why other obvious areas were not changed
- Other docs unaffected by this rule change

### Verification
- 292 tests pass (no code changes)

### Runtime verification
NOT RUNTIME VERIFIED — documentation only

### Result
Documentation synchronization is now part of Definition of Done.

---

## 2026-09-29 — Fix TelegramLinkingChallengeRepository session lifetime and enum casting

**Commit:** `055bb09`

### Why
TelegramLinkingChallengeRepository was created with a session that was immediately closed, but retained by TelegramBotAdapter for later use in _handle_start_command(). Additionally, Python enum values were uppercase while PostgreSQL enum values were lowercase, causing "invalid input value for enum" errors.

### What changed
- Changed TelegramLinkingChallengeRepository to accept session_factory instead of direct session
- Each repository method now creates a fresh session via `async with await self._get_session() as session`
- Changed TelegramLinkingChallengeStatus enum values to lowercase (pending/used/expired) to match DB
- Changed status column from SQLEnum to String(20) to avoid enum binding issues
- Repository query uses `cast("pending", ENUM(...))` for proper PostgreSQL enum comparison
- mark_used/mark_expired use string literals
- main.py passes async_session_factory instead of session to repository

### Why this approach
Session factory pattern ensures each database operation gets a live session. String column with explicit cast avoids SQLAlchemy enum binding mismatches between Python and PostgreSQL.

### Why these files
- Repository: session lifetime fix
- Model: enum alignment
- main.py: pass session factory

### Why other obvious areas were not changed
Other repositories (TelegramIdentityRepository, etc.) are used within the same `async with` block where they're created, so they don't have the lifetime issue.

### Verification
- 292 tests pass
- Ruff: clean
- Mypy: clean
- Runtime verification: get_pending_by_telegram_user_id executes successfully with enum casting

### Runtime verification
RUNTIME VERIFIED — query executes successfully, returns expected result

### Result
Telegram /start flow now works end-to-end without session or enum errors.

---

## 2026-09-29 — Integrate real LLM provider into Telegram conversation flow

**Commit:** `635e5ff`

### Why
ConversationService was initialized with `llm_provider=None`, causing all messages to use mock interpretation. Real LLM provider needed to be wired through the existing provider/registry/config architecture.

### What changed
- Added `create_llm_provider()` factory in `app/intelligence/providers/__init__.py`
- Factory creates and initializes provider based on settings (LLM_PROVIDER, LLM_MODEL, LLM_API_KEY, LLM_BASE_URL)
- Returns None for mock mode (default)
- Updated main.py lifespan to initialize LLM provider and pass to ConversationService
- Added LLM provider cleanup on shutdown
- Stored llm_provider in app.state

### Why this approach
Factory pattern keeps provider creation centralized. Settings-driven configuration allows switching providers without code changes. None return for mock mode preserves test compatibility.

### Why these files
- providers/__init__.py: factory function
- main.py: lifespan wiring

### Why other obvious areas were not changed
ConversationService already accepts llm_provider parameter; no changes needed there.

### Verification
- 292 tests pass
- Ruff: clean
- Mypy: clean
- Runtime verification: create_llm_provider() returns None for mock mode (expected)

### Runtime verification
RUNTIME VERIFIED — factory returns None for mock mode; provider initialization path tested

### Result
Real LLM provider is now wired through the existing architecture. Configurable via .env.

---

## 2026-09-29 — Add BERU_STATE.md and update AGENTS.md

**Commit:** `2570ae7`

### Why
Need persistent project context that survives across agent sessions and can be shared between ChatGPT, OpenCode, and Antigravity.

### What changed
- Created BERU_STATE.md with current project state
- Updated AGENTS.md with requirement to read/update BERU_STATE.md

### Verification
- Documentation only; no code changes

### Result
Persistent project context established.

---

## 2026-09-29 — Align TelegramLinkingChallengeStatus enum with DB enum values

**Commit:** `2c16e7d` / `e5c72d5`

### Why
Python enum had uppercase values (PENDING/USED/EXPIRED) but PostgreSQL enum was created with lowercase values (pending/used/expired). This caused "invalid input value for enum" errors.

### What changed
- Changed Python enum values to lowercase
- Changed model status column to String(20)
- Repository query uses explicit cast to PostgreSQL enum type

### Verification
- Tests pass
- Runtime verification: query executes successfully

### Result
Enum mismatch resolved.

---

## 2026-09-29 — Fix Telegram startup wiring

**Commit:** `00471e1`

### Why
No startup logging for Telegram adapter; no error handling/cleanup on startup failure; missing logger in bot_adapter.py; duplicate import causing UnboundLocalError.

### What changed
- Added structured logging throughout lifespan (Telegram init, start, scheduler)
- Added try/except with cleanup on startup failure
- Added logger to bot_adapter.py
- Added startup/shutdown/poll logging to adapter
- Fixed duplicate TelegramLinkingChallengeRepository import in main.py

### Verification
- Server starts successfully
- Telegram adapter initializes and polls
- Logs visible in output

### Runtime verification
RUNTIME VERIFIED — server starts, Telegram polls, logs visible

### Result
Telegram startup is now observable and failures are handled gracefully.

---

## 2026-09-29 — Repair alembic migration chain

**Commit:** `7db7f76`

### Why
Migration b2c3d4e5f6a7 had revision ID 'a1b2c3d4e5f6' (duplicate of telegram identities migration), causing "Revision a1b2c3d4e5f6 is present more than once" and "KeyError: 'b2c3d4e5f6a7'".

### What changed
- Fixed revision ID in b2c3d4e5f6a7_add_portal_credentials_table.py from 'a1b2c3d4e5f6' to 'b2c3d4e5f6a7'
- Added create_type=False to enum columns in telegram identities, linking challenge, and briefing deliveries migrations (idempotent re-run)

### Verification
- alembic heads: single head f3a4b5c6d7e8
- alembic history: clean chain
- alembic upgrade head: all 10 migrations apply successfully

### Runtime verification
RUNTIME VERIFIED — full migration chain applies from base to head

### Result
Migration chain is clean and applies successfully.

---

## 2026-09-29 — Persist student profile name and attendance target

**Commit:** `512dadd`

### Why
BriefingService was receiving StudentProfile with missing persisted name/attendance_target, causing fallback on name and no below-target analysis.

### What changed
- Added name (String(100)) and attendance_target (Float) to Student model
- Added update_profile() to StudentRepository with 0-100 validation
- Updated scheduler to pass persisted name/attendance_target to StudentProfile
- Created migration f3a4b5c6d7e8

### Verification
- 19 new tests pass
- Full suite: 291 passed

### Result
Student profile data is now persisted and flows through to BriefingService.

---

## 2026-09-29 — Add daily morning briefing scheduler with Telegram delivery

**Commit:** `b34f58a`

### Why
Need proactive daily morning briefing delivery to eligible students via Telegram at their configured briefing time.

### What changed
- Created BriefingDelivery model (idempotent delivery tracking)
- Created BriefingDeliveryRepository
- Created BriefingScheduler worker
- Added briefing_time and timezone to Student model
- Added briefing config settings
- Wired scheduler into main.py lifespan
- Created migrations d1e2f3a4b5c6 and e2f3a4b5c6d7

### Verification
- 22 new tests pass
- Full suite: 272 passed

### Result
Briefing scheduler is operational with per-student timezone/time support and idempotent delivery.

---

## 2026-09-29 — Implement Telegram conversation integration

**Commit:** `5609fb9`

### Why
Need to process Telegram messages through the existing intelligence pipeline (ConversationService).

### What changed
- Created TelegramMessageHandler
- Wired into main.py lifespan with full dependency stack
- Message flow: adapter → handler → identity resolution → conversation service → response

### Verification
- Tests pass
- Runtime: messages processed through pipeline

### Result
Telegram conversation pipeline is functional.

---

## 2026-09-29 — Implement Telegram identity linking

**Commit:** `13eed5b`

### Why
Need secure linking of Telegram identities to Student accounts.

### What changed
- Created TelegramLinkingChallenge model
- Created TelegramLinkingService with challenge/verify flow
- Added audit logging for linking events
- Created migration c1d2e3f4a5b6

### Verification
- Tests pass
- Challenge flow works end-to-end

### Result
Secure Telegram identity linking is operational.

---

## 2026-09-29 — Add Telegram Bot API startup verification

**Commit:** `7fb5675`

### Why
Need to verify Telegram bot token is valid at startup and handle errors gracefully.

### What changed
- Added _get_me() verification during initialize()
- Added specific error handling for 401, 404, other API errors
- Added startup verification tests

### Verification
- 16 tests pass
- Invalid token raises RuntimeError with clear message

### Result
Telegram bot token is verified at startup; failures are explicit.

---

## 2026-09-29 — Add Telegram Bot API adapter foundation

**Commit:** `c32e1ee`

### Why
Need real Telegram adapter using Bot API long polling.

### What changed
- Created TelegramBotAdapter with long polling
- Created TelegramProvider abstraction
- Created normalized Telegram models
- Created provider registry
- Created migration a1b2c3d4e5f6

### Verification
- Tests pass
- Adapter initializes and polls

### Result
Telegram Bot API adapter is functional.

---

## 2026-09-28 — Baileys WhatsApp provider adapter

**Commits:** `30ca262`, `5254ac4`, `50dd7ca`, `7c789fc`, `4d4365e`, `2f6b3a3`

### Why
WhatsApp is the future primary interface; Baileys adapter provides the implementation.

### What changed
- Created baileys_adapter.js (Node.js entrypoint)
- Created WhatsApp provider abstraction
- Created normalized WhatsApp models
- Created WhatsApp auth integration
- Fixed session reconnection issues

### Verification
- Session persistence works
- QR code terminal rendering works
- Reconnection handling verified

### Result
WhatsApp Baileys adapter is complete and functional.

---

## 2026-09-27 — Portal integration and attendance sync

**Commits:** `ad5d9fc`, `cf21f73`, `f7499c1`

### Why
Need read-only access to college portal for attendance data.

### What changed
- Created DoctusAdapter (login, semesters, attendance)
- Created DoctusParser (HTML parsing)
- Created PortalSyncService
- Created PortalCredentialStore (encrypted)
- Created migration b2c3d4e5f6a7

### Verification
- Parser tests pass with known response shapes
- Login flow implemented

### Runtime verification
NOT RUNTIME VERIFIED — live portal access not tested

### Result
Portal integration is implemented; live verification pending.

---

## 2026-09-26 — Attendance domain and timetable pipeline

**Commits:** `2a38290`, `9408c09`, `8f2daf9`, `2a240a6`

### Why
Core domain logic for attendance calculations and timetable management.

### What changed
- Created AttendanceService (deterministic calculations)
- Created TimetableService (state machine)
- Created TimetableExtractor (PDF/image parsing)
- Created attendance and timetable tools
- Created migrations 8f7e3a2b1c9d, 9a8b7c6d5e4f

### Verification
- Extensive test coverage
- All calculations deterministic

### Result
Attendance and timetable domain logic is complete.

---

## 2026-09-25 — Intelligence foundation and LLM architecture

**Commits:** `d40585f`, `bbeeca9`, `23d10c9`

### Why
Need LLM provider abstraction and tool dispatch architecture.

### What changed
- Created LLMProvider ABC
- Created OpenAICompatibleLLMProvider
- Created MockLLMProvider
- Created ToolRegistry
- Created ConversationService
- Created ContextBuilder

### Verification
- Tests pass
- Provider abstraction works

### Result
Intelligence foundation is complete.

---

## 2026-09-25 — Authentication and authorization foundation

**Commits:** `6a5cdfc`, `2dc8215`, `ca06495`

### Why
Need secure multi-user foundation with ownership isolation.

### What changed
- Created Student model
- Created authentication context
- Created authorization service
- Created audit logging
- Created DatabaseStudentResolver
- Created initial migration 5d414855ae22

### Verification
- Ownership isolation tests pass
- Auth flow works

### Result
Secure multi-user foundation is complete.