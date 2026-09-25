# Beru — College Copilot

A personal AI-powered college assistant. WhatsApp-first.

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

**Phase: Foundation scaffolding.** No business features implemented yet.

## Architecture

See `docs/ARCHITECTURE.md` for full architecture documentation.

## Development Rules

See `AGENTS.md` for non-negotiable rules and conventions.

## License

MIT
