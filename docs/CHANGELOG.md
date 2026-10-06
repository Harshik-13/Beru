# CHANGELOG.md — Beru

## 2026-10-06 — Transient Portal Error Defense & Credential Status Isolation

### Task / Change
Distinguished genuine credential rejection (`is_credential_rejection=True`, e.g. invalid username/password or account locked) from transient college portal/network errors (HTTP 503 Service Unavailable, 502/504 Bad Gateway, timeouts, pre-flight token drops), preventing transient portal outages from falsely degrading student credentials to `RECONNECT_REQUIRED`.

### Why
1. During live interaction on Telegram, the college portal's IIS web server (`automation.vnrvjiet.ac.in`) experienced a transient 60-second `HTTP 503 Service Unavailable` spike while recycling its application pool.
2. `DoctusAdapter.login()` raised `DoctusLoginError` on the 503 response.
3. `PortalSyncService.sync_attendance()` previously caught all `DoctusLoginError` instances and unconditionally marked `status = RECONNECT_REQUIRED` in PostgreSQL, assuming any login failure was due to invalid credentials.
4. Once marked `RECONNECT_REQUIRED`, the backend refused to attempt automatic syncs, locking the connection until the user re-entered their password, even though their stored credentials were 100% valid.
5. In `OnboardingService`, transient pre-flight 503 errors previously told users their password was wrong rather than notifying them that the portal was temporarily busy/down.

### What Changed
- `backend/app/integrations/portal/doctus.py`:
  - Added `is_credential_rejection: bool | None = None` parameter to `DoctusLoginError`. Automatically classifies HTTP 5xx errors, timeouts, and pre-flight failures as `is_credential_rejection=False`. Explicitly sets `is_credential_rejection=True` only when the portal returns status 200 with `Status != 1` ("Invalid username or password" or "Account temporarily blocked").
- `backend/app/integrations/portal/sync_service.py`:
  - In `sync_attendance()`, updated the `DoctusLoginError` catch block to only update credential status to `PortalCredentialStatus.RECONNECT_REQUIRED` when `e.is_credential_rejection` is `True`.
  - Transient portal failures (503, timeouts, 502) now raise `PortalSyncError` and preserve the `CONNECTED` credential status in PostgreSQL.
  - In `get_or_sync_attendance()`, catches non-rejection login errors and returns the cached snapshot with `PORTAL_SNAPSHOT_STALE` provenance and a diagnostic notice (`Live portal refresh unavailable: {e}`) instead of claiming credentials failed.
- `backend/app/integrations/portal/onboarding_service.py`:
  - In `receive_password()`, checks `e.is_credential_rejection` to distinguish genuine auth failure from transient portal unavailability, advising the student to retry shortly rather than claiming their password was wrong.
- `backend/tests/test_portal_sync_and_freshness.py`:
  - Added `test_transient_portal_503_does_not_mark_reconnect_required` verifying that a 503 during sync falls back to cached data and leaves `update_status` uncalled.

### Files Changed
- `backend/app/integrations/portal/doctus.py` — `DoctusLoginError` rejection classification.
- `backend/app/integrations/portal/sync_service.py` — Conditional `RECONNECT_REQUIRED` update and friendly fallback notice.
- `backend/app/integrations/portal/onboarding_service.py` — Differentiated onboarding error messaging.
- `backend/tests/test_portal_sync_and_freshness.py` — Unit test for transient 503 defense.

### Tests & Verification
- Unit test suite: `backend/tests/test_portal_sync_and_freshness.py` passes 18/18 tests.
- Full regression suite: 473/473 tests passing across the entire repository.
- Live database check: Verified stored credentials for student against live Doctus with 200 OK.

### Security Considerations
- Security boundaries untouched: Authentic invalid credentials (`is_credential_rejection=True`) still strictly trigger `RECONNECT_REQUIRED`.
- Zero credential leakage: Error messages continue stripping sensitive payload details.

## 2026-10-06 — Two-Tier Tool Architecture, LLM Schema Pruning (62.1% Reduction) & Pipeline Defense

### Task / Change
Implemented a policy-level Two-Tier Tool Architecture pruning LLM function calling schemas from ~4,451 tokens down to ~1,687 tokens (62.1% reduction), isolated minimal OpenAI schemas while preserving internal `ToolDefinition` metadata, established a 5-stage defense pipeline in `_execute_tool()`, and instrumented zero-leak request token diagnostics.

### Why
1. In production and testing with Groq's free tier (8,000 TPM/ITPM limit), sending all 37 tool definitions in every LLM request consumed ~4,451 tokens. Combined with the system prompt (~2,363 tokens) and history, baseline requests approached ~7,800 tokens, leaving almost zero headroom for user input or model output and triggering HTTP 429 rate limit exceptions.
2. Tool availability is an intelligence-policy concern that belongs at the tool registry layer, not hardcoded inside `ConversationService`.
3. Extended tools retained for internal/backend dispatch must never be invocable by LLMs merely because they exist in the registry. `_execute_tool()` required a formal 5-stage validation pipeline verifying registration, authorization, confirmation, and argument schemas before dispatch.
4. Internal security and confirmation metadata (`requires_authorization`, `requires_confirmation`, `result_schema`) must not be stripped from internal definitions to satisfy provider schemas; an explicit converter (`tool_def_to_openai`) was needed to maintain clean separation.
5. Accurate serialization measurements and zero-leak token instrumentation were required to monitor request sizes without leaking sensitive student or portal data.

### What Changed
- `backend/app/intelligence/tools/registry.py`:
  - Added `CORE_TOOLS: frozenset[str]` policy defining the 12 core semantic tools for conversational LLM exposure:
    - Timetable (5): `get_today_schedule`, `get_tomorrow_schedule`, `get_schedule_for_weekday`, `find_activity_details`, `confirm_timetable`.
    - Attendance (7): `get_overall_attendance`, `get_attendance_summary`, `calculate_bunk_allowance`, `simulate_schedule_scenario`, `set_attendance_target`, `sync_attendance`, `start_portal_connection`.
  - Added `get_core_tools()` and `is_core_tool()` to `ToolRegistry`.
  - Added `tool_def_to_openai()` isolating the minimal OpenAI function calling schema, stripping backend-injected `student_id`, and configuring nullable optional parameter types for Groq compatibility.
  - Added `tool_def_to_dict()` preserving internal fields (`requires_authorization`, `requires_confirmation`, `result_schema`, `arguments_schema`, `enabled`).
  - Added `validate_tool_arguments()` validating required fields and parameter types against `ToolDefinition.arguments_schema`.
  - Added `.to_dict()` and `.to_openai_schema()` convenience methods to `ToolDefinition`.
- `backend/app/intelligence/tools/__init__.py`:
  - Exported `CORE_TOOLS`, `BuiltinToolHandler`, `tool_def_to_dict`, `tool_def_to_openai`, and `validate_tool_arguments`.
- `backend/app/intelligence/services/conversation.py`:
  - In `_interpret_intent()`, consumed `self.tool_registry.get_core_tools()` to format system prompt tool descriptions and populate OpenAI `tools` request parameters.
  - Added structured token diagnostics logging (`llm_request_diagnostics: tool_count=... est_input_tokens=...`) and provider usage logging (`llm_response_usage: prompt_tokens=...`) with zero sensitive content logged.
  - In `_execute_tool()`, implemented the 5-stage defense pipeline:
    1. Tool registered & enabled check.
    2. Student authorization check (validates `student_id`; strips client-supplied `student_id`).
    3. Confirmation check (`requires_confirmation`).
    4. Argument schema validation (`validate_tool_arguments`).
    5. Deterministic dispatch to service handlers.
- `backend/tests/test_intelligence.py`:
  - Added `TestToolSchemaPruningAndExecutionSafety` suite with 9 dedicated unit tests covering core tools membership, registry filtering, OpenAI schema isolation, internal metadata preservation, argument validation, unauthorized execution rejection, disabled tool rejection, and intent interpretation core-tool exposure.

### Files Changed
- `backend/app/intelligence/tools/registry.py` — Core tools policy, registry methods, OpenAI schema converter, argument validation.
- `backend/app/intelligence/tools/__init__.py` — Exported core tools policy and validation utilities.
- `backend/app/intelligence/services/conversation.py` — Core tools integration, token diagnostics logging, 5-stage execution pipeline defense.
- `backend/tests/test_intelligence.py` — 9 new unit tests verifying pruning, schema isolation, and pipeline safety.
- `docs/ARCHITECTURE.md`, `docs/STATE.md`, `docs/CHANGELOG.md` — Reconciled canonical documentation.

### Implementation Approach
Decoupled tool policy from conversation handling: `ConversationService` queries `ToolRegistry.get_core_tools()` without domain-specific tool lists. `_execute_tool()` enforces backend boundaries deterministically.

### Tests & Verification
- Unit test suite: `backend/tests/test_intelligence.py` passes 56/56 tests.
- Serialized payload measurement: Verified with `scratch/measure_token_payload.py`:
  - Tool schemas reduced from 17,805 chars (~4,451 tokens) to 6,751 chars (~1,687 tokens) — **62.1% reduction**.
  - Total baseline request payload: **~4,057 tokens** ($\le 5,000$ token target achieved).
- Full regression suite: 472/472 passing tests across the entire repository with 0 failures.
- Commit hash: `2568bfb`

### Security Considerations
- LLM is not a security boundary: LLM cannot invoke extended tools simply because they are registered in the backend.
- Resource ownership enforced: `student_id` is always injected from authenticated `student_context.student_id` and stripped from caller arguments.
- Zero-leak logging: Token diagnostics instrument character/token counts only; never log credentials, passwords, session tokens, or portal HTML.

## 2026-10-04 — Partial-Day Simulation, Pure Session Action Topology, MissingGreenlet Fix & Stored Monthly Breakdown

### Task / Change
Implemented canonical partial-day attendance simulation, pure session action calculation topology, strict period validation against scheduled sessions, explicit repository injection eliminating `MissingGreenlet`, and authoritative stored monthly attendance breakdown reporting.

### Why
1. During live testing of Beru on Telegram (`@BeruHK_bot`), the user asked to simulate skipping partial days (e.g., "skip first 3 classes on Monday") and to check monthly attendance breakdown.
2. In live execution, `simulate_schedule_scenario` failed with `sqlalchemy.exc.MissingGreenlet` because accessing lazy-loaded `.entries` on detached/un-eagerly loaded SQLAlchemy models attempted a synchronous query in an async context.
3. Partial-day requests previously lacked a unified canonical representation, creating ambiguity between whole-day and partial-day parameters.
4. If a student requested skipping more periods than exist on a day (e.g. "skip first 3 classes" on Sunday when Sunday only has 2 scheduled classes), the system must reject the request with clear clarification rather than silently truncating or guessing.
5. Monthly attendance queries were reporting cumulative figures or failing to present the dedicated monthly breakdown persisted from the college portal.

### What Changed
- `backend/app/intelligence/services/scenario_resolver.py`:
  - Added `InvalidSessionCountError`, `SessionConflictError`, `PartialDayRequest`, and `ResolvedSessionAction`.
  - Added single canonical parameter `partial_day_scenarios: tuple[PartialDayRequest, ...]`.
  - Strict partial-day session validation: verifies requested ordinal periods ($N > 0$) against actual timetable sessions on that day; raises `InvalidSessionCountError` if count exceeds available sessions; prevents same-session conflicts (`SessionConflictError`).
  - Converts all whole-day, relative, and partial-day scenarios into pure `ResolvedSessionAction` records.
  - Explicit repository injection: accepts `entry_repo: TimetableEntryRepository` in constructor; safely resolves confirmed timetables without touching lazy `.entries` properties.
- `backend/app/intelligence/services/simulation_service.py`:
  - Updated `AttendanceSimulationService` to drive deterministic calculations exclusively from `ResolvedSessionAction` inputs without string parsing or weekday inspection.
  - Added explicit repository injection and awaitable handling for `entry_repo`.
  - Made `simulate_subject_periods` accept both `subject_code` and `subject_query` seamlessly.
- `backend/app/intelligence/tools/attendance_tools.py`:
  - Standardized `simulate_schedule_scenario` tool schema to single canonical `partial_day_scenarios` parameter.
  - Explicitly instantiated and injected `TimetableEntryRepository(session)` into resolver and simulation service.
  - Added `view="monthly"` support to `get_attendance_summary`, capturing `monthly_period` from snapshot subjects.
- `backend/app/intelligence/rendering/attendance_renderer.py`:
  - Updated `render_summary` to render dedicated monthly breakdown cards (`<b>Monthly Attendance Breakdown (SEP 2026)</b>`) using stored monthly fields (`monthly_attended`, `monthly_conducted`, `monthly_percentage`, `monthly_period`). Made `student_context` optional.
- `backend/app/intelligence/services/context_builder.py`:
  - Added system prompt guidance for routing partial-day requests (`partial_day_scenarios`) and monthly stats queries (`view='monthly'`).
- `backend/tests/test_attendance_simulations.py`:
  - Added 5 new tests: `test_partial_day_request_exceeds_available_periods`, `test_same_session_cannot_be_attend_and_skip`, `test_partial_day_first_n_periods_simulation`, `test_render_monthly_subject_attendance_breakdown`, and `test_missing_greenlet_prevented_by_entry_repo`. Total suite expanded to 20 passing tests.

### Files Changed
- `backend/app/intelligence/services/scenario_resolver.py` — Canonical partial-day resolution, session bounds validation, and pure session action generation.
- `backend/app/intelligence/services/simulation_service.py` — Pure session action calculation engine and repository injection.
- `backend/app/intelligence/tools/attendance_tools.py` — Unified tool schemas, explicit repository wiring, and monthly summary fields.
- `backend/app/intelligence/rendering/attendance_renderer.py` — Authoritative monthly breakdown card renderer.
- `backend/app/intelligence/services/context_builder.py` — LLM system prompt instructions for partial-day and monthly inquiries.
- `backend/tests/test_attendance_simulations.py` — Dedicated validation suite for partial-day bounds, session conflicts, and greenlet safety.
- `docs/STATE.md`, `docs/ARCHITECTURE.md`, `docs/REQUIREMENTS.md`, `docs/CHANGELOG.md` — Reconciled canonical documentation.

### Implementation Approach
Constructed a clean, unidirectional pipeline:
`Natural Language -> LLM structured tool call -> ScenarioResolver -> ResolvedSessionAction[] -> AttendanceSimulationService -> SimulationResult -> AttendanceRenderer`.
All natural language and schedule topologies are resolved upfront into pure session actions, leaving the simulation service 100% deterministic and free of calendar/weekday string heuristics.

### Tests & Verification
- `backend/tests/test_attendance_simulations.py`: 20/20 passing tests.
- Full regression suite: 463/463 passing tests across the entire repository with 0 failures.
- Commit hash: `d8807cf`

### Security Considerations
- Backend remains the security boundary: all period bounds and session actions are validated server-side.
- Zero portal risk: simulations operate purely over local snapshot baselines and confirmed timetables with zero Doctus HTTP calls.
- Read-only guarantee: simulations never mutate database attendance records.

### Remaining Limitations / Blockers
- None. Ready for live student interaction on Telegram.

## 2026-10-04 — Comprehensive Multi-Day, Mixed, and Subject Attendance Simulations & Zero-Portal Isolation

### Task / Change
Implemented comprehensive multi-day, mixed schedule (attend some days, bunk others), and subject-level attendance simulations with strict date resolution, lab batch ambiguity defense, legacy baseline reconciliation, and zero-portal-risk architectural isolation.

### Why
1. Previously, Beru could only simulate single-day absences (`simulate_day_absence`) or general future absence counts (`simulate_absence`), leaving students unable to plan complex schedules (e.g. "What if I attend Monday and Tuesday but bunk Wednesday and Thursday?", "What happens to my attendance if I miss the next 3 days?").
2. Simulating future attendance must never risk locking out the student's college portal account. Any invocation of live portal synchronization during hypothetical what-if queries introduces unnecessary network exposure and authentication strain.
3. Natural-language dates, relative instructional day counts ("next 3 days"), and mixed actions require decoupled resolution to prevent conflicting user intents (e.g. attempting to both attend and skip the same calendar day) and avoid fragile hardcoded assumptions (such as assuming Sundays or Saturdays never have classes).
4. For timetables with divided lab batches (Batch 1 vs Batch 2), attempting to simulate attendance when the student's lab batch is unknown could compute inaccurate period counts; a proactive halt with clarification is required.
5. Legacy attendance snapshots exhibited portal corruption where overall attendance was recorded as single-digit totals (e.g. 6/6) instead of cumulative totals (178/306); simulations must reliably use the reconciled cumulative baseline.

### What Changed
- `backend/app/intelligence/services/scenario_resolver.py`:
  - Created `ScenarioResolver` service with typed models (`SimulationAction`, `ResolvedDayAction`, `ResolvedScenario`) and domain exceptions (`ScenarioConflictError`, `LabBatchAmbiguityError`, `SubjectNotFoundError`, `NoConfirmedTimetableError`).
  - Implemented conflict detection: allows mixed actions across distinct dates (e.g. attend Tuesday + skip Monday) while rejecting same-date conflicts (`ScenarioConflictError`).
  - Removed Sunday assumptions: instructional days are defined strictly by dates having confirmed scheduled timetable sessions (including Sundays/Saturdays if scheduled; sessionless days are skipped).
  - Implemented Lab Batch Ambiguity Defense: raises `LabBatchAmbiguityError` if a student with an `UNKNOWN` lab batch attempts to simulate a date containing divided lab batches (`Batch 1` vs `Batch 2`).
  - Implemented fuzzy subject resolution: resolves natural language subject names ("OS", "Operating Systems", "DAA") against confirmed timetable entries.
- `backend/app/intelligence/services/simulation_service.py`:
  - Created `AttendanceSimulationService` structurally isolated from `PortalSyncService` with zero Doctus HTTP calls, ensuring simulations can never lock out the student's portal account.
  - Implemented `simulate_schedule_scenario`: projects attendance across single-day or multi-day scenarios with mixed attend/skip actions, calculating aggregate delta, projected overall attendance, and per-subject impact breakdown.
  - Implemented `simulate_subject_periods`: projects attendance when attending or missing an arbitrary number of periods of a specific course, reporting subject delta and overall ripple effect.
  - Reused authoritative snapshot reconciliation (`reconcile_snapshot_overall`) to correct legacy corrupted snapshots (e.g. 6/6 -> 178/306) on read.
- `backend/app/intelligence/services/attendance_service.py`:
  - Exposed `reconcile_snapshot_overall` as a `@staticmethod` and module function for reuse across simulation services.
  - Ensured offline calculations operate safely without triggering portal sync.
- `backend/app/intelligence/services/timetable_service.py`:
  - Removed hardcoded `if day_of_week == 6: return []` in `get_schedule_for_date` and `get_next_class` so timetable queries and instructional day counts are strictly timetable-driven.
- `backend/app/intelligence/services/briefing.py`:
  - Updated `generate_briefing` to inspect `briefing_date = self._today()` using `get_schedule_for_date` with async inspect fallback to `get_today_schedule`, ensuring robust briefing generation regardless of calendar weekday.
- `backend/app/intelligence/tools/attendance_tools.py`:
  - Added `simulate_schedule_scenario` and `simulate_subject_periods` to `SIMULATION_TOOLS` and `ATTENDANCE_TOOL_DEFINITIONS`.
  - Wired into `execute_attendance_tool` dispatch.
- `backend/app/intelligence/rendering/attendance_renderer.py`:
  - Added `render_schedule_scenario` and `render_subject_periods` with 3-tier safety indicators, snapshot age, and subject breakdowns; made `student_context` optional.
- `backend/app/intelligence/rendering/registry.py`:
  - Registered simulation tools in default renderer registry set.
- `backend/app/intelligence/services/context_builder.py` & `backend/app/intelligence/services/conversation.py`:
  - Added prompt routing guidance, added tools to `ATOMIC_QUERY_TOOLS` and `attendance_tools` dispatch sets.
- `backend/tests/test_attendance_simulations.py`:
  - Added comprehensive test suite with 15 tests verifying single-day attend/skip, multi-day next N instructional days, mixed actions across distinct days, same-date conflict rejections, Sunday session inclusion, lab batch ambiguity halts, legacy 6/6 baseline reconciliation, and natural-language subject period simulations.

### Security Considerations
- Zero-portal-risk isolation: `AttendanceSimulationService` does not depend on or invoke `PortalSyncService`. All simulations are offline mathematical projections, eliminating portal account lockout risks.
- Tenant isolation: Multi-user data isolation is strictly preserved through authenticated `student_id`.
- Non-mutating invariant: Projections never mutate database attendance records.
- Deterministic calculation boundary: LLMs interpret structured intent; backend performs exact deterministic calculations.

### Verification
- 15/15 tests passing in `backend/tests/test_attendance_simulations.py`.
- 458/458 passing tests across the entire test suite.

## 2026-10-02 — Complete Attendance Intelligence Suite & Action Integrity Invariant

### Task / Change
Implemented the complete attendance intelligence suite (safe bunk calculation, full-day leave simulations, attendance extremes, 100% target recovery boundary handling, and verified target mutation) and established an enterprise-grade Action Integrity Invariant ensuring Beru only claims state mutation when an authorized backend mutation tool executes and returns a verified result.

### Why
1. Previously, when asked to change the attendance target or mutate state, Beru could hallucinate conversational confirmation ("I've updated your target to 80%") without executing a backend tool or verifying persistent DB state.
2. Students frequently ask diverse attendance questions ("How many classes can I bunk?", "What if I take leave today?", "Which subject has my lowest attendance?", "How many classes do I need to attend to hit 75%?"). Beru lacked dedicated tools for these scenarios, risking hallucinated LLM calculations or inability to serve student needs.
3. Edge cases in attendance recovery math (such as targeting 100% when classes have already been missed) caused divide-by-zero or infinite loop potentials unless handled mathematically with boundary checks.
4. Floating-point division precision artifacts (`4.0 / 0.2 = 20.000000000000004`) triggered off-by-one errors when wrapped directly in `ceil()`, requiring rounded division before applying `ceil()`.

### What Changed
- `backend/app/models/audit_event.py`:
  - Added `STUDENT_UPDATED = "student_updated"` to `AuditEventType` enum.
- `backend/app/security/audit.py`:
  - Implemented `log_student_updated(student_id, event_metadata)` with typed audit logging.
- `backend/app/intelligence/services/attendance_service.py`:
  - `set_attendance_target`: Implemented validation (1.0..100.0), authorization, idempotency check, DB mutation, commit, fresh DB re-read verification, and `STUDENT_UPDATED` audit event logging.
  - `calculate_bunk_allowance`: Implemented exact safe bunk formula $B_{\max} = \max(0, \lfloor \frac{A - t \cdot C}{t} \rfloor)$ with zero-conducted guards ($C=0$), zero-attended guards ($A=0$), below-target detection, single-subject and overall breakdowns.
  - `simulate_day_absence`: Implemented date/weekday semantics, confirmed timetable check (rejecting pending/missing with `TIMETABLE_REVIEW_PENDING` / `NO_TIMETABLE`), student lab batch filtering, repeated period aggregation, and 3-tier safety status (`overall_safe`, `subjects_safe`, `is_safe`).
  - `get_attendance_extremes`: Implemented lowest and highest attendance courses with multi-subject tie grouping.
  - `calculate_recovery`: Added $T=100.0\%$ boundary handling (`classes_needed: int | None`, `achievable: bool = False`, clean explanation when $A < C$; $0$ classes needed when $A == C$); eliminated floating-point division precision artifacts via rounded division before `ceil()`.
  - `calculate_classes_needed`: Updated to support overall recovery when `subject_code` is None.
- `backend/app/intelligence/tools/attendance_tools.py`:
  - Formalized tool taxonomy: `MUTATION_TOOLS`, `SIMULATION_TOOLS`, and `READ_TOOLS`.
  - Added tools: `set_attendance_target`, `calculate_bunk_allowance`, `simulate_day_absence`, and `get_attendance_extremes`.
  - Registered tool schemas in `ATTENDANCE_TOOL_DEFINITIONS` and wired into `execute_attendance_tool`.
- `backend/app/intelligence/rendering/attendance_renderer.py` & `registry.py`:
  - Added dedicated deterministic renderers: `render_set_target`, `render_bunk_allowance`, `render_day_absence`, and `render_extremes`.
  - Registered in `AttendanceRenderer.render` and `ResponseRendererRegistry`.
- `backend/app/intelligence/services/conversation.py`:
  - Defined `MUTATION_TOOLS`, `GRACEFUL_CAPABILITY_REFUSAL`, and `is_state_mutation_intent`.
  - Wired Action Integrity Invariant guard in `process_message`: if user message reflects state mutation intent and no tool execution occurred, returns `GRACEFUL_CAPABILITY_REFUSAL` instead of hallucinating success.
  - Wired new attendance tools into `attendance_tools` dispatch set and mock intent interpreter.
- `backend/app/intelligence/services/context_builder.py` & `backend/app/intelligence/conversation/policy.py`:
  - Injected Action Integrity Invariant and attendance intelligence instructions into system prompt and synthesis guidelines.
- `backend/tests/test_attendance_intelligence_suite.py`:
  - Added comprehensive test suite with 15 tests verifying target mutation, idempotency, validation bounds, safe bunk exact math, zero-data handling, recovery 100% boundary conditions, overall recovery, day absence period aggregation and lab batch filtering, extremes with multi-subject ties, and Action Integrity Invariant refusals/executions.

### Security Considerations
- Action Integrity Invariant enforces backend security boundary: LLM text generation is never trusted as evidence of a mutation.
- Target changes are validated, committed, re-read, and logged in `audit_events` table for auditability.
- Multi-user tenant isolation is strictly preserved via authenticated `student_id`.
- Deterministic backend calculations eliminate LLM arithmetic hallucinations.

### Verification
- 15/15 tests passing in `test_attendance_intelligence_suite.py`.
- 443/443 passing tests across the entire test suite.
- Uvicorn daemon running cleanly on `127.0.0.1:8000`.

---

### Task / Change
Resolved `MissingGreenlet` exception in live portal sync by capturing snapshot primitives and in-memory DTO subject counts before `session.commit()`; implemented non-mutating read-time compatibility fallback for legacy snapshots stored prior to parser fix; established single source of truth for attendance target arithmetic (`target_difference`, `target_status`, `target_gap_percentage`) in `AttendanceService`; and eliminated complicated jargon ("margin", "deficit", "cushion") in favor of clear natural language status indicators (`• Status: ⚠️ {gap}% more needed to reach {target}%`, `• Status: ✅ At {target}% target`, and `• Status: ✅ {diff}% above {target}% target`).

### Why
1. In live testing, after `DoctusParser` successfully parsed the student's real cumulative attendance (`178/306 = 58.17%`) into `AttendanceSnapshot(38f0aeb4)`, `PortalSyncService.sync_attendance` evaluated `len(snapshot.subjects)` *after* `await self.session.commit()`. Under SQLAlchemy 2.x async ORM, `commit()` expires all model instance attributes; accessing the un-loaded relationship post-commit triggered `MissingGreenlet: greenlet_spawn has not been called`.
2. As designed for resilience, `get_or_sync_attendance` caught the error and gracefully fell back to the most recent cached snapshot in PostgreSQL (`53e096a1`), which was captured before the parser fix when `overall_conducted = 6, overall_attended = 6` (`100.0%`).
3. Legacy snapshots created before the parser fix remain in the database with truncated overall aggregates (`6/6`) even though their subject rows accurately record cumulative counts (`178/306`).
4. Students and testers found the label `• Margin: ⚠️ -16.8%` and terms like "deficit" or "cushion" confusing and academic. Clarified requirement: replace with natural language indicating how much more percentage is needed to hit the target, while preserving backend deterministic math and avoiding hardcoded persona phrases.

### What Changed
- `backend/app/integrations/portal/sync_service.py`:
  - Captured `snapshot_id`, `captured_at`, `overall_percentage`, and `len(attendance.subjects)` (from in-memory `PortalAttendance` DTO) prior to `await self.session.commit()`.
- `backend/app/intelligence/services/attendance_service.py`:
  - Added `target_percentage`, `target_difference`, `target_status`, `target_gap_percentage`, and `legacy_snapshot_reconciled` to `OverallAttendanceResult` dataclass and its `to_dict()`.
  - Implemented `_reconcile_snapshot_overall(snapshot, target)`: checks if `sum_cond > 0 and 0 <= sum_att <= sum_cond and snapshot.overall_conducted < sum_cond`. If so, uses subject sums on read, logs a diagnostic warning, and sets `legacy_snapshot_reconciled=True` without mutating the database row. If `overall_conducted >= sum_cond`, preserves portal aggregates as authoritative.
  - Computes deterministic target fields: `target_difference = round(pct - target, 2)`, `target_gap_percentage = round(abs(diff), 2)`, `target_status` (`"below"`, `"at_target"`, `"above"`).
  - Integrated `_reconcile_snapshot_overall` into both `get_overall_attendance` and `get_attendance_summary`.
- `backend/app/intelligence/tools/attendance_tools.py`:
  - Forwarded `target_percentage`, `target_difference`, `target_status`, `target_gap_percentage`, and `legacy_snapshot_reconciled` in tool return dictionaries and registered schemas.
- `backend/app/intelligence/rendering/attendance_renderer.py`:
  - Rewrote `render_overall` and `render_summary` to format status as:
    - Below target: `• Status: ⚠️ {gap:.1f}% more needed to reach {target:.0f}%`
    - At target: `• Status: ✅ At {target:.0f}% target`
    - Above target: `• Status: ✅ {diff:.1f}% above {target:.0f}% target`
  - Completely eliminated bare `• Margin: ...` label and "deficit" jargon.
  - Rewrote `render_below_target` to format as `{idx}. {name}: {pct} — ⚠️ {deficit}% more needed to reach {target}%`.
- `backend/app/intelligence/services/context_builder.py` & `backend/app/intelligence/conversation/policy.py`:
  - Guided LLM to strictly report verified target progress differences from tool results without computing its own arithmetic or using rigid phrase matching.
- `backend/tests/test_golden_outputs.py`:
  - Updated golden summary test to assert the new plain status line.
- `backend/tests/test_portal_sync_and_freshness.py`:
  - Added unit tests for plain language status rendering across all three target boundaries (below, at_target, above).
  - Added unit tests verifying non-mutating read-time legacy snapshot reconciliation and authoritative aggregate preservation.

### Security Considerations
- Pre-commit value extraction prevents async greenlet crashes without expanding session scope or risking transaction leaks.
- Read-time legacy snapshot reconciliation strictly avoids mutating database records, ensuring database immutability rules remain intact.
- Target arithmetic remains 100% deterministic in the backend security boundary; the LLM is prohibited from computing attendance numbers.

### Verification
- Full test suite: 428 passing tests across the entire repository.
- Unit tests in `test_portal_sync_and_freshness.py` verify greenlet safety, legacy reconciliation, authoritative preservation, and renderer output.
- Commit: `b196cea`

---

## 2026-10-02 — Dual Overall & Monthly Attendance Reporting, Dialogue State Tracking & Dynamic Course Mapping

### Task / Change
Implemented independent extraction and dual reporting of cumulative overall attendance and current month attendance (e.g. October, 2026); resolved Doctus parser aggregate collision; added bounded dialogue state tracking (`last_domain`, `last_intent`, `last_tool`, `last_entity`, `last_semester`) for natural follow-up reasoning ("Per subject?") without keyword matching; implemented `get_course_mapping` dynamic timetable code correlation with conflict reporting; removed `get_subject_codes` from tool definitions; and established defense-in-depth raw output interception and secret redaction.

### Why
1. Live portal inspection established that EduPrime attendance widgets provide two aggregate fractions in the total row: monthly totals (e.g. `6 / 6 (100)`) and cumulative totals (e.g. `178 / 306 (58.17)`). The legacy parser grabbed the first fraction via regex, mistakenly reporting current monthly attendance as the student's overall attendance.
2. Natural conversational follow-up turns like "Per subject?" or "Break it down" were previously stateless, failing to infer the omitted subject/domain without brittle keyword matching.
3. Students asking what a course code stands for had no focused lookup tool, causing either full weekly schedule dumps or exposing raw subject code dictionaries.
4. Credential and portal security required robust secret redaction from conversation history and runtime interception against raw dict/JSON leaks to Telegram.

### What Changed
- `backend/app/integrations/portal/dto.py`:
  - Added `monthly_attended`, `monthly_conducted`, `monthly_percentage_from_portal`, and `monthly_period` to `PortalAttendance`.
- `backend/app/integrations/portal/parser.py`:
  - Implemented `_parse_overall_and_monthly` to parse monthly and cumulative attendance independently.
  - Added disambiguation for Fraction-First (`X / Y (P%)`) and Percentage-First (`P% (X / Y)`) totals.
  - Added extraction of monthly header period (e.g. `October, 2026`).
  - Preserved portal-computed aggregates while reconciling subject sums.
- `backend/app/integrations/portal/sync_service.py`:
  - Corrected credential repo argument order in `update_status` and `update_sync_timestamp`.
- `backend/app/intelligence/models/context.py`:
  - Added `last_domain`, `last_intent`, `last_tool`, `last_entity`, and `last_semester` to `ConversationContext`.
  - Added `update_dialogue_state()` method.
  - Implemented `sanitize_result_summary()` with HTML stripping and pattern redaction for sensitive keys and tokens.
- `backend/app/intelligence/services/attendance_service.py`:
  - Added `monthly_attended`, `monthly_conducted`, `monthly_percentage`, `monthly_period` to `OverallAttendanceResult`.
  - Added `classes_needed` to `SubjectAttendanceResult`.
  - Added `_get_confirmed_timetable_mapping` to correlate attendance subject codes with confirmed timetable names.
- `backend/app/intelligence/services/timetable_service.py`:
  - Implemented `get_course_mapping(student_id)`: correlates codes to friendly names from confirmed timetable entries; marks conflicting entries with `status="conflict"` and alternatives instead of guessing.
- `backend/app/intelligence/tools/timetable_tools.py`:
  - Added `get_course_mapping` function, registered in `TIMETABLE_TOOL_DEFINITIONS`, and wired in `execute_timetable_tool`.
- `backend/app/intelligence/tools/attendance_tools.py`:
  - Removed `get_subject_codes` from tool definitions.
  - Added `semester_id` support and forwarded monthly attendance fields.
- `backend/app/intelligence/rendering/attendance_renderer.py`:
  - Updated overall attendance card to render both Overall Attendance (cumulative) and Current Month Attendance with badge indicators.
  - Updated subject breakdown to display `Name (Code)`.
- `backend/app/intelligence/rendering/schedule_renderer.py`:
  - Added `render_course_mapping` for course code lookups and conflicts.
- `backend/app/intelligence/rendering/registry.py`:
  - Registered `get_course_mapping` in timetable tools.
- `backend/app/intelligence/services/context_builder.py`:
  - Injected dialogue state and multi-turn conversational reasoning guidelines into the system prompt.
- `backend/app/intelligence/services/conversation.py`:
  - Added `get_course_mapping` to `ATOMIC_QUERY_TOOLS` for natural conversational synthesis.
  - Automatically records dialogue state upon successful tool execution.
  - Added defense-in-depth interceptor catching raw dict/JSON output and forcing fallback rerendering.
- `backend/app/intelligence/providers/openai_compatible.py`:
  - Added logging of response body text when `HTTPStatusError` occurs so provider errors are transparently diagnosed.
- `backend/app/intelligence/services/conversation.py`:
  - Enhanced `_tool_def_to_openai` to automatically allow `"null"` for optional parameters, preventing provider schema validation rejections (HTTP 400) when models pass `null`.
  - Cleaned `_parse_intent_response` to strip `None` values from tool arguments.
- `backend/app/intelligence/tools/attendance_tools.py`:
  - Updated `semester_id` argument schema in `get_overall_attendance` and `get_attendance_summary` to explicitly permit `["string", "null"]`.

### Verification
- 423/423 full repository tests passing (`pytest backend/tests/ -q`).
- Zero regressions in existing timetable, briefing, portal, and security suites.

### Task / Change
Replaced hypothetical `/Student/Dashboard` route with verified `/App` workspace and `/Shared/Widget/STDINFO` widget extraction; stored protected student ID strictly in-memory within `DoctusSession` for the sync lifecycle without persistence or roll-number leakage; implemented unified attendance and semester discovery via `GET /Academic/Shared/GetStdAttPer?studentId=<id>&semId=undefined` (with secondary call only if caller explicitly requests a different semester); added request-specific redirect defense with `follow_redirects=False` halting any 301/302 redirects to `/` or `/Login` before the server can expire the session cookie; and updated the HTML parser to dynamically derive active semester selection and handle multiple attendance text/fraction formats.

### Why
Live portal investigation confirmed that:
1. Modern EduPrime lands at `https://automation.vnrvjiet.ac.in/App`, not `/Student/Dashboard`.
2. The protected internal student identifier required by `GetStdAttPer` is embedded in the `STDINFO` widget JavaScript (`function popAtt()`), and roll numbers are rejected with 401/302.
3. The initial browser attendance call intentionally uses `semId=undefined`, which EduPrime accepts, returning the `#StdSemPop` selector and full attendance data for the default selected semester.
4. Following an unexpected redirect to `/` causes the portal to send `Set-Cookie: relic_VNRVJIET=; expires=Thu, 01 Jan 1970`, expiring the authenticated session cookie.

### What Changed
- `backend/app/integrations/portal/doctus.py`:
  - Added route constants `APP_ENDPOINT = "/App"` and `STDINFO_WIDGET_ENDPOINT = "/Shared/Widget/STDINFO"`.
  - Added `_extract_protected_student_id_from_stdinfo()` regex parser.
  - Added `_check_redirect_and_raise()` for request-specific redirect interception halting redirects to root/login.
  - Added `get_app_workspace()` and `get_stdinfo_widget()` to discover protected student ID in-memory.
  - Implemented `get_attendance_and_semesters(target_semester_id)` supporting initial `sem_id = "undefined"`.
  - Updated `get_semesters()` and `get_attendance()` to delegate to `get_attendance_and_semesters()`.
- `backend/app/integrations/portal/parser.py`:
  - Updated `parse_semester_options()` to reliably detect boolean `selected` attribute.
  - Updated `parse_attendance()` to dynamically extract the active semester ID from `#StdSemPop` when omitted or `undefined`.
  - Enhanced `_parse_overall_attendance()` to extract fraction counts (`attended / conducted`) regardless of whether they precede or follow the percentage string.
- `backend/app/integrations/portal/sync_service.py`:
  - Streamlined `sync_attendance()` to call `adapter.get_attendance_and_semesters()` directly, saving round trips and eliminating invalid route redirects.
- `backend/tests/test_portal.py`:
  - Updated mocked suite to test `/App`, `/Shared/Widget/STDINFO`, and `semId=undefined`.
  - Added tests for `_extract_protected_student_id_from_stdinfo`, dynamic semester derivation, and explicit non-default semester queries.

### Verification
- 48/48 portal unit tests passed (`pytest backend/tests/test_portal.py -v`).
- 12/12 portal sync and freshness tests passed (`pytest backend/tests/test_portal_sync_and_freshness.py -v`).
- 416/416 full repository regression tests passed cleanly (`pytest backend/tests/ -q`).

---

## 2026-10-02 — Direct GetStdAttPer Attendance Alignment & Timetable Semester Resolution

### Task / Change
Implemented direct attendance retrieval via `/Academic/Shared/GetStdAttPer` with dynamic semester resolution from the student's confirmed timetable (`(year - 1) * 2 + semester`) falling back to `semId = "3"`; added unauthenticated 302 redirect detection with safe diagnostic `Location` logging in `DoctusAdapter.get_attendance`; added clear user-facing redirect status reporting in `PortalSyncService`; enhanced `DoctusParser.parse_attendance` for lenient subject table parsing; and expanded offline test suites to 48 portal unit tests and 12 sync tests.

### Why
During live Telegram testing, `POST /Login` succeeded (`Status: 1`), but `GET /Student/Dashboard` returned `HTTP 302 Found -> /`, redirecting to the root landing page and preventing dynamic semester dropdown parsing (`No semesters available from portal`). By inferring `semId` from the student's confirmed timetable profile (or defaulting to semester 3) and calling `GetStdAttPer` directly with authenticated cookies, Beru bypasses the dashboard redirect blocker, captures the real attendance data contract, and delivers clear diagnostic status if the session is challenged.

### What Changed
- `backend/app/integrations/portal/sync_service.py`:
  - Added `timetable_repo` property to `PortalSyncService`.
  - Updated `sync_attendance()` to infer `target_semester_id` from confirmed timetable (`(year - 1) * 2 + semester`) before falling back to `"3"`.
  - Made semester dropdown discovery opportunistic: if `get_semesters()` redirects or fails, logs and proceeds directly with `target_semester_id`.
  - Added clear user-facing messaging in `get_attendance_or_cached()` when a session redirect occurs: `"College portal session was redirected; checking authentication."`.
- `backend/app/integrations/portal/doctus.py`:
  - Added redirect detection in `get_attendance()`: inspects `response.history` and response status for 301/302/303/307/308, logging `Location` header and raising `DoctusSessionError` without credential leaks.
  - Added diagnostic logging of HTTP status, content-type, final URL, and top-level JSON response keys.
- `backend/app/integrations/portal/parser.py`:
  - Enhanced `parse_attendance()` to be lenient: extracts overall metrics (attended, conducted, percentage) first, then parses extractable subject rows without crashing if individual table rows vary.
- `backend/tests/test_portal.py`:
  - Added `test_get_attendance_redirect_raises_session_error`.
  - Verified all 48 portal unit tests pass.
- `backend/tests/test_portal_sync_and_freshness.py`:
  - Added `test_redirect_notice_in_get_or_sync_attendance`.
  - Verified all 12 sync and freshness tests pass.

### Verification
- 48/48 portal unit tests passed (`pytest backend/tests/test_portal.py -v`).
- 12/12 portal sync and freshness tests passed (`pytest backend/tests/test_portal_sync_and_freshness.py -v`).
- 416/416 full repository regression tests passed cleanly (`pytest backend/tests/ -q`).

---

## 2026-10-01 — Doctus Browser Document Navigation & Explicit Semester Validation

### Task / Change
Updated `DoctusAdapter` to reproduce standard browser document headers (`Accept: text/html...`, `Upgrade-Insecure-Requests: 1`, standard browser `User-Agent`, omitting `X-Requested-With`) on the `/Student/Dashboard` page request to test the 404 investigation hypothesis; added `is_selected` detection on `SemesterOption` in `DoctusParser.parse_semester_options`; implemented explicit semester validation and active default selection in `PortalSyncService.sync_attendance`; and added safe response status/content-type logging on `GetStdAttPer`.

### Why
During live testing, `POST /Login` succeeded live (`Status: 1`), but the subsequent `GET /Student/Dashboard` returned 404 while sending AJAX-style headers (`X-Requested-With: XMLHttpRequest`). In browser navigation, `window.location.href` executes a standard document GET without XMLHttpRequest. Furthermore, semester selection was made explicit and validated against the student's discovered semester options, and safe response inspection logging was added to observe the real `GetStdAttPer` response before finalizing any further parser changes.

### What Changed
- `backend/app/integrations/portal/dto.py`:
  - Added `is_selected: bool = False` to `SemesterOption`.
- `backend/app/integrations/portal/parser.py`:
  - Updated `parse_semester_options()`: sets `is_selected=True` when an option has the HTML `selected` attribute while preserving document order.
- `backend/app/integrations/portal/doctus.py`:
  - Added `BROWSER_USER_AGENT` and configured `__aenter__` with standard browser `User-Agent` and `Accept-Language`.
  - Updated `get_semesters()`: sends top-level document headers (`Accept: text/html...`, `Upgrade-Insecure-Requests: 1`, `Referer: {BASE_URL}/Login`), omitting `X-Requested-With`.
  - Updated `get_attendance()`: sends AJAX headers (`X-Requested-With: XMLHttpRequest`, `Accept: application/json, text/javascript...`, `Referer: {BASE_URL}/Student/Dashboard`) and logs response status and content-type safely.
  - Added module logger.
- `backend/app/integrations/portal/sync_service.py`:
  - Added explicit validation: verifies `target_semester_id` belongs to discovered semester options, using the active `is_selected` semester as the default.
- `backend/tests/test_portal.py`:
  - Updated tests to assert document headers (no `XMLHttpRequest`) on `get_semesters()` and AJAX headers with referer on `get_attendance()`.

### Verification
- 47/47 portal unit tests passed (`pytest backend/tests/test_portal.py -v`).
- 11/11 portal sync and freshness tests passed (`pytest backend/tests/test_portal_sync_and_freshness.py -v`).
- 414/414 full repository regression tests passed cleanly (`pytest backend/tests/ -q`).

---

## 2026-10-01 — Doctus Downstream Route Alignment & Frozen Dataclass Fix

### Task / Change
Aligned `DoctusAdapter.get_semesters` to request the authenticated landing route `/Student/Dashboard` (falling back to legacy `/Academic/Student/Attendance` on 404), added support for general navigation semester dropdowns in `DoctusParser.parse_semester_options`, included both `xUsername` and `UserName` in `POST /Login` form payload, verified the parameterized attendance endpoint `/Academic/Shared/GetStdAttPer?studentId={id}&semId={sem_id}`, fixed a `FrozenInstanceError` in `DoctusParser.parse_attendance`, and added comprehensive offline tests.

### Why
During the previous live test, authentication reached `Status: 1`, but the subsequent semester fetch requested `/Academic/Student/Attendance` which returned HTTP 404. In modern EduPrime, `/Student/Dashboard` is the post-login landing route where navigation and student data reside. Furthermore, offline testing revealed that `PortalAttendance` is an immutable frozen dataclass, which raised a `FrozenInstanceError` when `doctus.py` attempted to mutate `attendance.semester_id` after parsing.

### What Changed
- `backend/app/integrations/portal/doctus.py`:
  - Included `xUsername` alongside `UserName` in `POST /Login` payload.
  - Stored post-login landing route (`self._dashboard_path = data["Data"]`).
  - Updated `get_semesters()`: queries `/Student/Dashboard` (or `self._dashboard_path`) with fallback to `/Academic/Student/Attendance` if 404.
  - Removed frozen dataclass field mutation `attendance.semester_id = semester_id`.
  - Enriched internal `StdId` from dashboard HTML using `_extract_protected_student_id_from_html()` supporting both `name` and `id` attributes.
- `backend/app/integrations/portal/parser.py`:
  - Updated `parse_semester_options()`: checks `#StdSemPop` and falls back to any select with name/id containing `sem`.
  - Updated `parse_attendance()`: directly passes `semester_id` into the `PortalAttendance` constructor so the frozen instance is constructed with the correct value.
- `backend/tests/test_portal.py`:
  - Updated `test_authenticated_session_continuity` and `test_session_enriched_by_html_id_discovery` to test `/Student/Dashboard`.
  - Added `test_get_semesters_fallback_to_legacy_attendance_route` verifying fallback behavior.
  - Added `test_get_attendance_uses_verified_parameterized_endpoint` verifying parameterized URL `/Academic/Shared/GetStdAttPer?studentId={id}&semId={sem_id}`.
  - Asserted `xUsername` presence in login form payload.

### Verification
- 47/47 portal unit tests passed (`pytest backend/tests/test_portal.py -v`).
- 11/11 portal sync and freshness tests passed (`pytest backend/tests/test_portal_sync_and_freshness.py -v`).
- 414/414 full project tests passed cleanly (`pytest backend/tests/ -q`).

---

## 2026-10-01 — Doctus Session Identifier Fallback & Sync Pipeline Alignment

### Task / Change
Decoupled authentication success from student-ID discovery in `DoctusAdapter.login`, implemented internal HTML student-ID discovery (`_extract_protected_student_id_from_html`), established the canonical `PortalAttendance` contract across `sync_service.py` without runtime tuple branching, and added 7 new unit tests for redirect URL handling, HTML student ID parsing, and session enrichment.

### Why
During live Telegram verification, the ASP.NET Core authentication protocol succeeded (`POST /Login` returned HTTP 200 with `Status: 1`), but the session creation aborted because EduPrime returns `{"Status": 1, "Data": "/Student/Dashboard"}` rather than a dictionary containing `"UserId"`. Furthermore, an architectural audit revealed that `sync_service.py` expected a tuple from `get_attendance()` instead of consuming `PortalAttendance` directly, and `_extract_protected_student_id_from_html` was called in `get_semesters()` but not implemented on `DoctusAdapter`.

### What Changed
- `backend/app/integrations/portal/doctus.py`:
  - Updated `login()`: when `Status == 1`, extracts student ID from dictionary if available, otherwise safely falls back to the normalized roll number. Never treats redirect URLs as student IDs.
  - Implemented `_extract_protected_student_id_from_html(html)`: extracts internal `StdId`/`StudentId` from HTML inputs and JavaScript variables without generic numeric matching.
  - Updated `get_semesters()`: enriches the temporary fallback `protected_student_id` with discovered internal `StdId`.
- `backend/app/integrations/portal/sync_service.py`:
  - Updated line 327 to consume `PortalAttendance` directly: `attendance = await adapter.get_attendance(target_semester_id)`.
- `backend/tests/test_portal.py`:
  - Added `TestDoctusHtmlStudentIdExtraction` with 5 tests (standard input, reversed input, JS variable, missing returns empty, rejects URL values).
  - Added `test_login_success_with_redirect_url_data` verifying roll number fallback when `Data` is a redirect URL.
  - Added `test_session_enriched_by_html_id_discovery` verifying internal ID enrichment during downstream calls.

### Verification
- 45/45 portal unit tests passed (`pytest backend/tests/test_portal.py -v`).
- 11/11 portal sync and freshness tests passed (`pytest backend/tests/test_portal_sync_and_freshness.py -v`).
- 412/412 full repository regression tests passed cleanly (`pytest backend/tests/ -q`).

---

## 2026-10-01 — Doctus Live Authentication & Session Alignment (ASP.NET Core / Anti-CSRF)

### Task / Change
Aligned `DoctusAdapter.login` with the live VNRVJIET EduPrime portal's ASP.NET Core protocol: implemented pre-flight `GET /Login` anti-forgery token extraction, paired `OM5.Antiforgery` cookie preservation, application/x-www-form-urlencoded form POST with `xPassword`, required verification headers, authoritative `self._client.cookies` session continuity without legacy `relic_VNRVJIET` dependency, strict account lockout and zero-retry protection, and 15 isolated unit tests.

### Why
During initial live Telegram testing, the onboarding boundary and sensitive message deletion performed cleanly, but `POST /Login` was rejected with `HTTP 400 Bad Request`. Live DOM inspection revealed the portal uses ASP.NET Core which strictly requires:
1. Pre-flight `GET /Login` to acquire the anti-forgery cookie and hidden `__RequestVerificationToken`.
2. Password form field named `xPassword` (not legacy `Password`).
3. Outbound request headers `RequestVerificationToken` and `Referer`.
4. Storing the entire cookie jar (`self._client.cookies`) across requests rather than expecting a legacy `relic_VNRVJIET` cookie.
Furthermore, student accounts must be strictly safeguarded against automated retry loops or account lockout triggers.

### What Changed
- `backend/app/integrations/portal/doctus.py`:
  - Added `_extract_antiforgery_token(html)` supporting flexible HTML attribute ordering and casing without logging or leaking tokens.
  - Implemented two-step `login(roll_number, password)`:
    - Step 1: Pre-flight `GET /Login` to seed anti-forgery cookie in client cookie jar and extract `__RequestVerificationToken`.
    - Step 2: Form POST with `__RequestVerificationToken`, `UserName`, `xPassword` and headers (`Content-Type`, `X-Requested-With`, `RequestVerificationToken`, `Referer`).
  - Implemented categorized safe error handling for timeouts, missing CSRF token, HTTP 400, HTTP 5xx, `Status == 0` (extracting safe user message and `BlockedUntil`), and malformed JSON.
  - Replaced legacy `relic_VNRVJIET` cookie requirement with authoritative `self._client.cookies` session construction.
  - Required extraction of protected student ID from response (`UserId`), failing safely if missing.
  - Downstream methods (`get_semesters`, `get_attendance`) seamlessly reuse authenticated session cookies.
- `backend/tests/test_portal.py`:
  - Added `TestDoctusTokenExtraction` testing standard, reversed, and mixed-case attribute orderings.
  - Added `TestDoctusAdapterLogin` with 15 isolated offline tests covering:
    - Successful login, GET-before-POST ordering, `xPassword` field usage, antiforgery token transmission in body & header, referer header, cookie jar preservation, zero dependency on legacy relic cookie, missing token handling, invalid credentials handling, blocked/captcha message propagation, HTTP 400/500 safe handling, malformed JSON handling, and leak prevention for passwords, tokens, and cookies.
  - Added `TestAuthenticatedSessionContinuity` verifying downstream calls (`get_semesters`) transmit authenticated session cookies.

### Files Changed & Why
- `backend/app/integrations/portal/doctus.py`: Core portal adapter alignment with ASP.NET Core protocol and safe session handling.
- `backend/tests/test_portal.py`: Unit and integration test coverage for authentication, error cases, leak prevention, and session continuity.
- `docs/STATE.md`: Documented implementation status and security invariants.
- `docs/CHANGELOG.md`: Detailed engineering history of the change.

### Verification
- 38/38 portal integration tests passed in 0.19s (`pytest backend/tests/test_portal.py -v`).
- 21/21 portal security and sync tests passed in 0.36s.
- 405/405 project regression tests passed (`pytest backend/tests/ -q`).
- Offline mock transport ensures 0 requests touch live portal during automated test execution.

---

## 2026-10-01 — Live Doctus Portal Integration, Zero-Leak Credential Boundary & 4-Hour Freshness Sync

### Task / Change
Implemented end-to-end college portal (Doctus) integration with an interactive zero-leak credential onboarding flow, transport-level password redaction, immediate Telegram message deletion, auth-first credential verification, Fernet encryption at rest, 4-hour freshness attendance sync, key-based concurrency locking, and unambiguous timestamp provenance presentation.

### Why
Students need live, accurate attendance updates directly from their college portal (automation.vnrvjiet.ac.in). However, handling college portal credentials over a chat platform carries major security risks: credentials must never leak into chat history, application logs, database backups, or LLM context windows. Additionally, live attendance fetching must be protected against duplicate concurrent requests (thundering herd), must respect a 4-hour freshness TTL to avoid excessive load on the college portal, and must gracefully fall back to cached snapshots with degraded provenance if the portal is unreachable—strictly adhering to Beru's zero-fabrication invariant.

### What Changed
- `backend/app/models/portal_credential.py` & Alembic Migration `migrations/versions/a4b5c6d7e8f9_add_portal_credential_lifecycle.py`:
  - Added credential lifecycle tracking: `PortalCredentialStatus` (`CONNECTED`, `RECONNECT_REQUIRED`), `connected_at`, `last_successful_auth_at`, `last_auth_failure_at`, and `last_sync_at`.
- `backend/app/telegram/bot_adapter.py`:
  - Implemented `delete_message(chat_id, message_id)` via Telegram Bot API `/deleteMessage`.
  - Added sensitive chat registry (`register_sensitive_chat`, `unregister_sensitive_chat`, `is_sensitive_chat`) with string normalization.
  - Redacted `raw_provider_data` and logger output for sensitive chats receiving credential messages (`[REDACTED_SENSITIVE_CREDENTIAL]`).
- `backend/app/integrations/portal/onboarding_service.py` [NEW]:
  - Dedicated multi-step interactive onboarding state machine (`AWAITING_ROLL_NUMBER` → `AWAITING_PASSWORD`).
  - Auth-First Verification: Tests credentials against live Doctus before touching database persistence.
  - Safe Rollback: Failed authentication never corrupts or downgrades existing valid credentials.
  - Immediate Telegram message deletion: Dispatches `delete_message` to purge plaintext password from Telegram immediately after reading.
  - Unregisters sensitive chat filter upon completion or cancellation.
- `backend/app/core/concurrency.py` [NEW]:
  - Implemented `KeyedLockManager` providing in-memory key-based mutual exclusion (`asyncio.Lock` per key) to serialize duplicate requests for the same student while running distinct students concurrently. Automatically garbage-collects completed locks.
- `backend/app/integrations/portal/sync_service.py`:
  - Implemented 4-hour freshness TTL (`FRESHNESS_TTL = timedelta(hours=4)`).
  - Implemented `get_or_sync_attendance` with fast-path freshness check and `KeyedLockManager` concurrency guard.
  - Handled Doctus errors gracefully: marks credential status as `RECONNECT_REQUIRED` on `DoctusLoginError`; falls back to latest cached snapshot with `PORTAL_SNAPSHOT_STALE` on communication failures.
  - Enforced zero-fabrication: returns None/unavailable if Doctus is down and no cached snapshot exists.
  - Updated `last_sync_at` and `CONNECTED` status on successful sync.
- `backend/app/intelligence/services/attendance_service.py`:
  - Added `sync_service` property and auto-sync support to `get_overall_attendance` and `get_attendance_summary`.
  - Added `provenance` and `notice` fields and `to_dict` serialization to all attendance dataclasses.
- `backend/app/intelligence/rendering/attendance_renderer.py`:
  - Added provenance badge formatting: `📅 Synced live from Doctus just now`, `📅 Sourced from Doctus snapshot ({time})`, and `⚠️ Cached snapshot ({time}) (Live refresh unavailable)`.
  - Added dedicated renderer for `sync_attendance` tool execution.
- `backend/app/telegram/message_handler.py`:
  - Intercepted onboarding flow messages before conversation pipeline to prevent passwords from ever entering LLM prompts or audit logs.
  - Wired `/connect_portal` and `/sync_attendance` commands.
- `backend/app/intelligence/tools/attendance_tools.py`:
  - Added `start_portal_connection` tool definition and semantic routing for natural language requests ("connect my portal", "reconnect doctus").
- `backend/tests/`:
  - Added 21 new tests across `test_portal_security.py`, `test_portal_onboarding.py`, `test_portal_semantic_routing.py`, and `test_portal_sync_and_freshness.py`.

### Files Changed & Why
- `backend/app/models/portal_credential.py`: Model schema updates for lifecycle tracking.
- `migrations/versions/a4b5c6d7e8f9_add_portal_credential_lifecycle.py`: Database schema migration.
- `backend/app/telegram/bot_adapter.py`: Sensitive chat redaction and message deletion.
- `backend/app/telegram/message_handler.py`: Boundary interception for credential steps.
- `backend/app/integrations/portal/onboarding_service.py`: Multi-step credential flow orchestration.
- `backend/app/core/concurrency.py`: In-memory keyed lock manager.
- `backend/app/integrations/portal/sync_service.py`: Freshness engine, concurrency locking, and status transitions.
- `backend/app/intelligence/services/attendance_service.py`: Auto-sync and provenance propagation.
- `backend/app/intelligence/rendering/attendance_renderer.py`: Provenance badges and sync formatting.
- `backend/app/intelligence/tools/attendance_tools.py`: Tool definitions and forwarders.
- `backend/tests/test_portal_*.py`: Comprehensive test suites.
- `docs/STATE.md`, `docs/ARCHITECTURE.md`, `docs/REQUIREMENTS.md`: Documentation synchronization.

### Implementation Approach
Phase 1 decoupled credential intake completely from the LLM conversation pipeline, inserting a zero-leak transport filter into `TelegramBotAdapter` and an isolated `PortalCredentialOnboardingService`. Phase 2 built a deterministic 4-hour freshness engine in `PortalSyncService` backed by `KeyedLockManager`, and enriched `AttendanceRenderer` with unambiguous provenance indicators.

### Tests & Verification
- `pytest backend/tests/test_portal_security.py backend/tests/test_portal_onboarding.py backend/tests/test_portal_semantic_routing.py backend/tests/test_portal_sync_and_freshness.py -v`: 21/21 passed in 0.45s.
- `pytest backend/tests -q`: 385/385 passed in 26.05s with zero failures.

### Security Considerations
- Plaintext passwords never enter logs, `raw_provider_data`, `ConversationContext`, or LLM prompts.
- Telegram Bot API deletes password messages immediately upon arrival.
- Passwords encrypted at rest using AES-128-CBC / HMAC-SHA256 (Fernet).
- Concurrency locks prevent thundering-herd load on the college portal.
- Stale data is never represented as live data; failed syncs fallback honestly with degraded provenance flags.

---

## 2026-10-01 — Conversational Synthesis for Atomic Queries & Persona Ownership in Self-Model

### Task / Change
Implemented conversational synthesis for atomic lookup tools (`find_activity_details`, `find_faculty_details`, `find_room_details`), permanently moved `"Sir"` into Beru's self-model (`BeruIdentity`), refined `ResponseStyleLayer` strictly for Telegram HTML sanitization and entity escaping, and added comprehensive property-based and multi-turn tests.

### Why
When a student asks a direct, focused question (e.g. *"Where is OS lab?"*), forcing a 6-line structured card containing day, time, type, batch, room, and faculty feels robotic, bloated, and unresponsive to the specific question asked. Allowing the LLM to synthesize a natural, direct answer over verified backend data (e.g. *"Your Operating Systems Lab is held in room E-431, Sir (Thursday, 11:00 AM–1:00 PM)."*) provides a true copilot experience. Furthermore, mechanical regex injection of `"Sir"` into headers (e.g. `<b>Schedule Breakdown, Sir:</b>`) created awkward artifacts and risked altering sentence structure. Moving `"Sir"` into the core self-model allows the model to address the student naturally.

### What Changed
- `backend/app/intelligence/models/identity.py`:
  - Added `honorific: str = "Sir"` directly to `BeruIdentity`.
  - Added behavioral principle `respectful_persona` ensuring Beru naturally addresses the student as `"Sir"` within conversational sentences.
- `backend/app/intelligence/conversation/policy.py` [NEW]:
  - Created `ConversationalResponsePolicy` codifying the 7 core conversational rules: answer question first, use only relevant verified facts, avoid database card dumps, naturally address student as Sir, maintain multi-turn continuity, preserve ambiguity, and eliminate premature promises.
- `backend/app/intelligence/services/conversation.py`:
  - Defined `ATOMIC_QUERY_TOOLS = {"find_activity_details", "find_faculty_details", "find_room_details"}`.
  - In `_execute_tool`, routed atomic query results to `_generate_conversational_response` using `ConversationalResponsePolicy` and `recent_messages`.
  - Added resilient fallback: any LLM failure or timeout during synthesis gracefully falls back to the deterministic domain renderer without crashing.
  - Preserved 100% deterministic rendering for structured collections (day/week schedules, attendance math, analytics, briefings).
- `backend/app/intelligence/rendering/style_layer.py`:
  - Refined `ResponseStyleLayer` strictly for sanitization and Telegram HTML formatting.
  - Removed mechanical `_inject_honorific` regex sentence alterations.
  - Implemented `sanitize_telegram_html` ensuring stray `<` and `>` are escaped while preserving valid Telegram tags (`<b>`, `<i>`, `<code>`, `<pre>`, `<a>`, etc.).
- `backend/tests/test_conversational_synthesis.py` [NEW]:
  - 6 new tests covering policy prompt composition, direct answer synthesis, multi-turn context awareness, LLM error fallback, and deterministic preservation.
- `backend/tests/test_golden_outputs.py` & `backend/tests/test_semantic_invariance.py`:
  - Reconciled card header assertions to reflect clean deterministic headers without forced `, Sir:` suffixes.

### Files Changed & Why
- `backend/app/intelligence/models/identity.py`: Permanent persona ownership of `"Sir"` and respectful principle.
- `backend/app/intelligence/conversation/__init__.py`: Package export.
- `backend/app/intelligence/conversation/policy.py`: Dedicated conversational response policy and prompt synthesis.
- `backend/app/intelligence/services/conversation.py`: Hybrid execution routing for atomic queries and fallback.
- `backend/app/intelligence/rendering/style_layer.py`: Safe Telegram HTML sanitization and greeting cleanup without regex alteration.
- `backend/tests/test_conversational_synthesis.py`: Property-based and multi-turn tests.
- `backend/tests/test_golden_outputs.py` & `backend/tests/test_semantic_invariance.py`: Updated header expectations.
- `docs/STATE.md`, `docs/ARCHITECTURE.md`, `docs/CHANGELOG.md`: Canonical documentation synchronization.

### Tests & Verification
- `pytest backend/tests/test_conversational_synthesis.py -v`: 6/6 passed.
- `pytest backend/tests/test_semantic_invariance.py -v`: 13/13 passed.
- `pytest backend/tests/test_golden_outputs.py -v`: 14/14 passed.
- Full pytest test suite (`pytest backend/tests -q`): 364/364 passed in 26.62s with zero failures.

### Security Considerations
- Backend remains the security and truth boundary: LLM does not access the database or alter numbers/times/rooms. It only formats verified backend tool results.
- Robust HTML sanitization prevents Telegram entity parsing injection errors.

### Commit Hash
- `b1f9644`

---

## 2026-10-01 — Fix Live Conversation Defects: 429 Retry Crash, Room Fallback, Faculty/Room DB Enrichment & Tool Disambiguation

### Why
Live Telegram testing revealed four concrete defects:
1. `OpenAICompatibleLLMProvider._make_request` crashed with `NameError: name 'logger' is not defined` when handling Groq HTTP 429 rate limit backoff, forcing the user to resend prompts repeatedly.
2. `find_activity_details` omitted the location when `room` was `None` instead of falling back to the timetable's `default_classroom` (`E-505`), leaving questions like *"Where is DV lab?"* without a room.
3. Database timetable entries had `room = None` and `faculty = None` because the extraction step only parsed grid cells, leaving the timetable PDF legend unmapped.
4. Counting queries (e.g. *"How many OOPJ classes are there in a week"*) risked misrouting to `get_timetable_status` instead of `query_schedule_analytics(metric='subject_count')`.

### What changed
- `backend/app/intelligence/providers/openai_compatible.py`:
  - Imported `logging` and initialized module `logger = logging.getLogger(__name__)`, enabling seamless HTTP 429/5xx backoff without crashing.
- `backend/app/intelligence/tools/timetable_tools.py`:
  - Added fallback in `find_activity_details`: `room: e.room or timetable.default_classroom`, ensuring section lectures and default classroom activities accurately report location.
  - Refined semantic capability descriptions in `TIMETABLE_TOOL_DEFINITIONS`:
    - `get_timetable_status`: explicitly described as querying document lifecycle and confirmation state.
    - `query_schedule_analytics`: explicitly described as computing deterministic counts, frequencies (`subject_count`), workload, and free breaks.
- `backend/scripts/enrich_timetable_entries.py` [NEW]:
  - Script that enriched confirmed database timetable entries with verified room, faculty, and course codes from the timetable PDF legend (`5_6185777998969446650.pdf`).
- `backend/tests/test_semantic_invariance.py`:
  - Added 3 new tests: `test_activity_details_default_classroom_fallback`, `test_counting_invariance_oopj`, and `test_openai_compatible_429_logger_retry`.
  - Total tests in file expanded from 10 to 13 (all passing).

### Verification
- `pytest backend/tests/test_semantic_invariance.py`: 13/13 passed.
- `pytest backend/tests/test_golden_outputs.py`: 14/14 passed.
- Full pytest suite `pytest backend/tests/`: 358/358 passed.

---

## 2026-09-30 — Encyclopedic Timetable Intelligence, Deterministic Schedule Analytics & Semantic-Invariance (Phase 2)

### Why
Students ask open-ended, complex, and calculating questions about their confirmed timetable (e.g. "Where is DV lab?", "Who is my OS professor?", "What classes are in room E-505?", "How many labs do I have in a week?", "Classes vs labs", "What are my free slots on Tuesday?"). Previous tools only supported whole-day or week slices, leading the LLM to either guess arithmetic or dump raw responses. Furthermore, varying user phrasing for the same request ("What do I have on Tuesday?" vs "Tuesday schedule") required semantic-invariance verification to guarantee equivalent verified responses.

### What changed
- `backend/app/intelligence/tools/timetable_tools.py`:
  - Implemented 4 new encyclopedic backend tools:
    1. `find_activity_details`: Searches courses/labs, merges contiguous periods (e.g. 2-hour lab blocks), resolves student `lab_batch`, and returns matched sessions.
    2. `find_faculty_details`: Supports faculty directory mode, subject-to-instructor lookup, and professor teaching schedules.
    3. `find_room_details`: Looks up room schedules and identifies regular lectures in the student's `default_classroom`.
    4. `query_schedule_analytics`: Calculates deterministic timetable metrics:
       - `classes_vs_labs`: Total lectures vs practicals and hours breakdown.
       - `subject_count`: Course frequency across the week and remaining sessions from current weekday forward.
       - `daily_workload`: Workload distribution (session count and hours per day) identifying busiest and lightest days.
       - `free_slots`: Gap analysis calculating free periods between scheduled classes.
  - Added schemas to `TIMETABLE_TOOL_DEFINITIONS` and wired dispatch in `execute_timetable_tool`.
  - Added `lab_batch` to `get_week_schedule` and `get_schedule_for_weekday`.
- `backend/app/intelligence/services/conversation.py`:
  - Added the 4 new tool names to the active timetable tool dispatch set.
- `backend/app/intelligence/rendering/`:
  - `registry.py`: Registered the 4 new tools in `ResponseRendererRegistry`.
  - `schedule_renderer.py`: Implemented `render_activity_details`, `render_faculty_details`, `render_room_details`, and `render_schedule_analytics` with bold labels, code badges, and strict omission of missing room/faculty fields.
- `backend/tests/test_semantic_invariance.py` [NEW]:
  - Added 10 tests verifying:
    - Semantic invariance across 5 natural language phrasing variations of Tuesday schedule.
    - Contiguous lab merging and room lookup for `find_activity_details`.
    - Deterministic omission of missing room/faculty fields.
    - Faculty directory and subject lookup.
    - Default classroom and room schedule lookup.
    - Classes vs labs mathematical breakdown (theory vs lab count and hours).
    - Subject frequency (total vs remaining scope).
    - Daily workload calculation (heaviest/lightest days).
    - Free slots / breaks calculation.
- `backend/tests/test_intelligence.py`:
  - Updated tool count assertion from 20 to 24 (3 original + 21 timetable tools).
- `.gitignore`:
  - Added `storage/` directory.

### Verification
- `pytest backend/tests/test_semantic_invariance.py`: 10/10 tests passing.
- `pytest backend/tests/test_golden_outputs.py`: 14/14 tests passing.
- Full test suite `pytest backend/tests/`: 353/353 tests passing.

---

## 2026-09-30 — Presentation Decoupling, ResponseStyleLayer, Missing-Field Omission & Rate Limit Resilience (Phase 1)

### Why
Analysis of live user transcripts revealed key gaps in Beru's responses:
1. `ScheduleRenderer.render_week_schedule` looked for `"days"` while `get_week_schedule` returned `"week"`, triggering the fallback "No schedule data available for this week, Sir." on all weekly queries.
2. Domain renderers were directly coupled to Beru's personality by hardcoding `"Sir"` in headings, preventing clean reuse and violating the separation between presentation of verified data and personality.
3. Missing fields (e.g. absent room or faculty) needed deterministic omission rather than placeholder strings.
4. Groq HTTP 429 rate limit spikes during rapid student messages caused transient conversation failures.
5. Beru lacked persistent database memory directives in its self-model, causing the LLM to emit canned session-amnesia disclaimers.

### What changed
- `backend/app/intelligence/rendering/`:
  - `style_layer.py` [NEW]: Implemented `ResponseStyleLayer`, which cleanly wraps rendered domain outputs to inject Beru's persona (`"Sir"` honorific, consistent ChatGPT-style spacing, polite closings, greeting cleanup) without coupling domain renderers.
  - `registry.py`: Evolved `RendererRegistry` into `ResponseRendererRegistry` supporting typed result dispatch, pipeline execution (`result -> domain_renderer.render() -> style_layer.apply()`), and registered `get_timetable_metadata`.
  - `schedule_renderer.py`: Decoupled `"Sir"` from domain headings; added deterministic missing-field omission (omits `Room:` and `Faculty:` lines completely when values are None); fixed weekly schedule dictionary key lookup (`result.get("week") or result.get("days", {})`); implemented `render_timetable_metadata`.
  - `attendance_renderer.py` & `briefing_renderer.py`: Decoupled hardcoded honorifics from headings, delegating persona wrapping to `ResponseStyleLayer`.
- `backend/app/intelligence/providers/openai_compatible.py`:
  - Enhanced HTTP 429 error handling with `Retry-After` header parsing and adaptive backoff (up to 3 attempts with 2.5s base window) to prevent rate spikes from dropping user turns.
- `backend/app/intelligence/models/`:
  - `identity.py`: Added persistent database memory operating principle to `BeruIdentity`.
  - `context.py`: Added `graduation_year` field to `StudentProfile`.
- `backend/app/intelligence/services/context_builder.py`:
  - Injected `Graduation Year` into student context prompt when available.
- `backend/tests/test_golden_outputs.py`:
  - Expanded test suite from 10 to 14 tests: added tests for decoupled data formatting without "Sir", deterministic missing room/faculty omission, empty schedule rendering, and week schedule key handling.

### Verification
- `pytest backend/tests/test_golden_outputs.py`: 14/14 tests passing.
- Full test suite `pytest backend/tests/`: 345/345 tests passing.
- Verified presentation decoupling: direct domain renderer output is 100% free of hardcoded persona; `ResponseStyleLayer` injects `"Sir"` and normalizes typography.

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