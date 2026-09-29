# Beru — College Copilot

A personal AI-powered college assistant. Telegram-first (Personal Alpha); WhatsApp-ready (future).

## Quick Start

```bash
# 1. Create virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # macOS/Linux

# 2. Install dependencies
pip install -e ".[dev]"

# 3. Copy environment config
cp .env.example .env

# 4. Run the application
uvicorn backend.app.main:app --reload

# 5. Verify
# Open http://localhost:8000/health
```

## Testing

```bash
pytest backend/tests/ -v
```

## Linting & Type Checking

```bash
ruff check backend/
ruff format backend/
mypy backend/
```

## Project Status

**Phase: Personal Alpha.** Telegram bot is live and functional. Core intelligence pipeline (LLM → tool dispatch → deterministic backend) is wired. Briefing scheduler is operational.

## Documentation

| Document | Purpose |
|----------|---------|
| `AGENTS.md` | Agent rules and conventions |
| `docs/PROJECT.md` | Project identity and scope |
| `docs/ARCHITECTURE.md` | Current system architecture |
| `docs/REQUIREMENTS.md` | Locked requirements |
| `docs/STATE.md` | Current live state |
| `docs/CHANGELOG.md` | Engineering history |
| `docs/COMMITS.md` | Git commit index |
| `docs/DOCUMENTATION_INDEX.md` | Documentation map |

## Development Rules

See `AGENTS.md` for non-negotiable rules and conventions.

## License

MIT