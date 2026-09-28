# BERU LIVE STATE

## CURRENT OBJECTIVE
Fix Telegram linking challenge enum mismatch and verify `/start` flow works end-to-end.

## IMPLEMENTED
- Fixed `TelegramLinkingChallengeStatus` enum values to lowercase (`pending`, `used`, `expired`) matching PostgreSQL enum
- Changed `status` column from `SQLEnum` to `String(20)` to avoid enum binding issues
- `get_pending_by_telegram_user_id()` uses `cast("pending", ENUM(name="telegram_linking_challenge_status", create_type=False))` for proper PostgreSQL enum comparison
- `mark_used`/`mark_expired` use string literals
- Removed `TelegramLinkingChallengeStatus` from runtime imports
- All temporary `[DIAG]` instrumentation removed from `bot_adapter.py`
- Added structured logging in `main.py` lifespan for Telegram startup/shutdown

## TESTED
- 291 tests pass (1 pre-existing flaky: `test_get_next_class`, time-dependent)
- Telegram linking tests: 36 passed
- Ruff: clean on changed files
- Mypy: pre-existing errors only (unrelated to changes)

## RUNTIME VERIFIED
- `initialize: PASS` — adapter initializes, session created, token verified
- `start: PASS` — polling task created, `_running=True`, `_state="polling"`
- `getUpdates` polling loop runs (confirmed by diagnostic)
- `/start` update reaches `_handle_start_command` (confirmed by diagnostic)
- `get_pending_by_telegram_user_id()` returns result without enum error (confirmed by diagnostic)
- Telegram adapter polling task runs continuously

## USER VERIFIED
None — pending manual `/start` test against running server

## CURRENT BLOCKER
None

## LAST CHANGE
- `backend/app/models/telegram_linking_challenge.py` — enum values lowercase, status column String(20)
- `backend/app/repositories/telegram_linking_challenge.py` — cast to PostgreSQL enum type in query, string literals for status updates
- `backend/app/telegram/bot_adapter.py` — removed all [DIAG] instrumentation
- Commit: `2c16e7d`

## NEXT ACTION
Start server (`$env:PYTHONPATH="backend"; .venv\Scripts\python.exe -m uvicorn app.main:app --port 8000`), send `/start` to `@BeruHK_bot`, verify onboarding message with challenge code is received.

## IMPORTANT CONTEXT
- PostgreSQL enum `telegram_linking_challenge_status` has values: `pending`, `used`, `expired` (lowercase)
- Python enum `TelegramLinkingChallengeStatus` now matches with lowercase values
- Model `status` column is `String(20)`; queries use `cast("pending", ENUM(...))` for proper PostgreSQL enum comparison
- Telegram adapter polls with 30s long-poll timeout; drops pending updates on start
- `/start` handled in `TelegramBotAdapter._handle_start_command()` before message queue
- Challenge repo injected at startup via `adapter.set_challenge_repository()`
- No temporary diagnostics remain in codebase