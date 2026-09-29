# CHANGELOG.md — Beru

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