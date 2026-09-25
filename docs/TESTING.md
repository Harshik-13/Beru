# Testing — Beru

## Commands

```bash
# Run all tests
pytest backend/tests/ -v

# Run a specific test file
pytest backend/tests/test_health.py -v

# Run with coverage
pytest backend/tests/ --cov=backend/app --cov-report=term-missing
```

## Conventions

- Tests live in `backend/tests/`.
- Test files are named `test_*.py`.
- Use `pytest-asyncio` for async endpoint tests.
- Security-sensitive behavior must have explicit tests.
- The `client` fixture in `conftest.py` provides an `httpx.AsyncClient` bound to the FastAPI app.

## What to Test

- API endpoints (request/response contracts)
- Domain logic (deterministic calculations)
- Authorization (ownership enforcement)
- State machine transitions (timetable)
- Idempotency of inbound events
- Idempotency of outbound jobs
