# Documentation Index — Beru

## Canonical Current Guidance

| File | Status | Purpose | Authority |
|------|--------|---------|-----------|
| `AGENTS.md` | CANONICAL | Agent rules and conventions | Highest |
| `docs/PROJECT.md` | CANONICAL | Project identity and scope | High |
| `docs/ARCHITECTURE.md` | CANONICAL | Current system architecture | High |
| `docs/REQUIREMENTS.md` | CANONICAL | Locked requirements | High |
| `docs/STATE.md` | CANONICAL | Current live state | High |
| `docs/CHANGELOG.md` | CANONICAL | Engineering history | Medium |
| `docs/COMMITS.md` | CANONICAL | Git commit index | Medium |
| `docs/DOCUMENTATION_INDEX.md` | CANONICAL | This file | Medium |

## Reference Documents

| File | Status | Purpose | Authority |
|------|--------|---------|-----------|
| `docs/CONNECTION_LIFECYCLE.md` | REFERENCE | WhatsApp connection lifecycle | Medium |
| `docs/DATA_MODEL.md` | REFERENCE | Database schema reference | Medium |
| `docs/IDEMPOTENCY.md` | REFERENCE | Idempotency strategy | Medium |
| `docs/INTEGRATIONS.md` | REFERENCE | External integration details | Medium |
| `docs/TESTING.md` | REFERENCE | Testing conventions | Medium |
| `docs/THREAT_MODEL.md` | REFERENCE | Security threat model | Medium |

## Historical Documents

| File | Status | Purpose | Authority |
|------|--------|---------|-----------|
| `docs/ADR/001-project-structure.md` | ARCHIVED | Project structure decision | Low |
| `docs/ADR/002-database-ownership-foundation.md` | ARCHIVED | DB ownership decision | Low |
| `docs/ADR/003-authentication-authorization.md` | ARCHIVED | Auth decision | Low |
| `docs/ADR/004-whatsapp-provider.md` | ARCHIVED | WhatsApp provider decision | Low |

## Removed Documents

| File | Status | Reason |
|------|--------|--------|
| `BERU_STATE.md` | REMOVED | Redundant with `docs/STATE.md` |
| `.pytest_cache/README.md` | REMOVED | Auto-generated cache |

## Documentation Hierarchy

```
AGENTS.md (agent rules)
    ↓
docs/PROJECT.md (what/why Beru exists)
    ↓
docs/REQUIREMENTS.md (what the system must do)
    ↓
docs/ARCHITECTURE.md (how the system is built)
    ↓
docs/STATE.md (current reality)
    ↓
docs/CHANGELOG.md / docs/COMMITS.md (history)
    ↓
docs/DOCUMENTATION_INDEX.md (this file)
    ↓
Reference docs (DATA_MODEL, INTEGRATIONS, etc.)
    ↓
docs/ADR/* (historical decisions)
    ↓
Source code
```

## Key Principles

1. **Source code is the ultimate authority** — if docs disagree with code, code wins
2. **STATE.md = current reality** — updated after every implementation task
3. **ARCHITECTURE.md = current architecture** — describes what's actually built
4. **REQUIREMENTS.md = requirements** — not implementation details
5. **CHANGELOG.md = engineering history** — preserves reasoning
6. **COMMITS.md = Git history** — compact commit index
7. **AGENTS.md = agent rules** — governs future agent behavior
8. **Reference docs** — detailed reference material, not authoritative guidance
9. **ADR** — historical decision records, preserved for context