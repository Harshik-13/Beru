# PROJECT.md — Beru

## STABLE PROJECT INTENT

**Project Name:** Beru (College Copilot)

**Purpose:** Personal AI-powered college assistant. WhatsApp-first interface.

**Product Vision:** A privacy-first, student-owned college assistant that lives in WhatsApp. Beru helps students manage their academic life — timetable, attendance, simulations, briefings — without requiring a separate app. The student owns their data; the college portal is a read-only integration.

**Intended User:** College students (starting with VNR VJIET Cybersecurity batch, Personal Alpha for Harshik).

**Current Product Scope (Personal Alpha):**
- Telegram as the live Personal Alpha interface (WhatsApp abstraction ready, Baileys adapter spike complete)
- Student onboarding via Telegram identity linking (/start flow with challenge token)
- Confirmed timetable ingestion (image upload → extraction → review → confirm)
- Deterministic attendance calculations (no LLM arithmetic)
- Attendance simulations (absence impact, recovery calculation)
- Daily morning briefing via Telegram at student-configured time
- Natural-language Telegram conversation (LLM interprets intent, backend executes typed tools)
- LLM provider abstraction (OpenAI-compatible + mock; provider selectable via config)
- Secure Telegram identity linking (challenge/verify flow with audit)
- Briefing scheduler (cron-like, per-student timezone/time)
- Briefing delivery via Telegram with idempotency

**Major Workflows:**
1. **Onboarding:** Student sends `/start` → Bot sends challenge → Student enters challenge in Beru app → TelegramIdentity linked → Authenticated
2. **Timetable:** Upload image → Extraction → Review/confirm lab batch → Confirm → Active timetable
3. **Attendance:** Portal sync (Doctus) → Snapshots stored → Queries/Simulations/Recovery via typed tools
3. **Briefing:** Scheduler → BriefingService (timetable + attendance) → Telegram send
4. **Conversation:** Telegram message → Identity resolution → Intent interpretation (LLM) → Tool dispatch → Deterministic backend execution → LLM response generation

**Important Constraints:**
- Backend is the security boundary; LLM is NOT a security boundary
- LLM never performs attendance arithmetic; only structured tool dispatch
- Deterministic calculations live in domain services; LLM only formats responses
- Multi-user isolation from day one; Student is ownership root
- Telegram is Personal Alpha LIVE interface; WhatsApp is future replaceable adapter
- No username/password auth; identity derived from Telegram identity resolution

**Current Rollout Stage:** Personal Alpha (Telegram bot live, Harshik piloting)

**Non-Goals / Intentionally Deferred:**
- Web/mobile app (WhatsApp is the interface)
- Vector DB / embeddings / RAG
- Multi-college tenancy
- Grade tracking / assignment submission
- Real-time collaboration features
- OCR fallback for timetable (image extraction is the primary path)
- Vector DB / embeddings / RAG

---

## CURRENT IMPLEMENTATION STATUS

| Component | Status | Notes |
|-----------|--------|-------|
| Foundation (DB, Auth, Ownership) | ✅ Implemented | Student, WhatsAppIdentity, AuditEvent models; repositories; auth context |
| Telegram Bot Adapter (Personal Alpha) | ✅ Implemented | Long polling, message normalization, /start linking |
| Telegram Identity Linking | ✅ Implemented | Challenge/verify flow, audit, TelegramIdentity model |
| LLM Provider Abstraction | ✅ Implemented | OpenAI-compatible + Mock; provider registry |
| Real LLM Integration | ✅ Implemented | OpenAI-compatible provider wired in lifespan |
| Telegram Conversation Handler | ✅ Implemented | Intent interpretation → Tool dispatch → Response |
| LLM Intent Interpretation | ✅ Implemented | LLM extracts intent/entities → tool dispatch |
| Tool Registry/Dispatch | ✅ Implemented | Typed tools for timetable, attendance, simulations |
| Telegram Message Handler | ✅ Implemented | Idempotency, identity resolution, conversation pipeline |
| Telegram Identity Linking | ✅ Implemented | /start challenge flow, challenge verification, TelegramIdentity creation |
| Telegram Linking Service | ✅ Implemented | Challenge creation/verification, audit logging |
| LLM Provider Abstraction | ✅ Implemented | OpenAI-compatible + Mock; registry pattern |
| Real LLM Provider (OpenAI-compatible) | ✅ Implemented | OpenRouter/NVIDIA/OpenCode Zen compatible |
| Attendance Service (deterministic) | ✅ Implemented | Snapshots, summaries, simulations, recovery calc |
| Attendance Tools | ✅ Implemented | Simulate absence, recovery, subjects below target |
| Timetable Service (state machine) | ✅ Implemented | Upload→Extract→Review→Confirm→Archive |
| Timetable Extraction | ✅ Implemented | PDF/image → cells → entries; slash lab handling |
| Timetable State Machine | ✅ Implemented | UPLOADED→EXTRACTING→REVIEW_REQUIRED→CONFIRMED→ARCHIVED |
| Timetable Query (deterministic) | ✅ Implemented | Today/tomorrow/next class/first class |
| Briefing Service | ✅ Implemented | Deterministic facts + natural language rendering |
| Briefing Scheduler | ✅ Implemented | Per-student timezone/time; idempotent delivery |
| Telegram Briefing Scheduler | ✅ Implemented | Per-student timezone/time; idempotent delivery |
| Telegram Message Handler | ✅ Implemented | Idempotency, identity resolution, conversation pipeline |
| Telegram Identity Linking | ✅ Implemented | Challenge/verify flow, audit, TelegramIdentity creation |
| Telegram Linking Service | ✅ Implemented | Challenge creation/verification, audit logging |
| LLM Provider Abstraction | ✅ Implemented | OpenAI-compatible + Mock; provider registry |
| Real LLM Provider (OpenAI-compatible) | ✅ Implemented | OpenRouter/NVIDIA/OpenCode Zen compatible |
| LLM Intent Interpretation | ✅ Implemented | LLM extracts intent/entities → tool dispatch |
| Tool Registry/Dispatch | ✅ Implemented | Typed tools for timetable, attendance, simulations |
| Telegram Message Handler | ✅ Implemented | Idempotency, identity resolution, conversation pipeline |
| Telegram Identity Linking | ✅ Implemented | Challenge/verify flow, audit, TelegramIdentity creation |
| Telegram Linking Service | ✅ Implemented | Challenge creation/verification, audit logging |
| LLM Provider Abstraction | ✅ Implemented | OpenAI-compatible + Mock; provider registry |
| Real LLM Provider (OpenAI-compatible) | ✅ Implemented | OpenRouter/NVIDIA/OpenCode Zen compatible |
| Attendance Service (deterministic) | ✅ Implemented | Snapshots, summaries, simulations, recovery calc |
| Attendance Tools | ✅ Implemented | Simulate absence, recovery, subjects below target |
| Timetable Service (state machine) | ✅ Implemented | Upload→Extract→Review→Confirm→Archive |
| Timetable Extraction | ✅ Implemented | PDF/image → cells → entries; slash lab handling |
| Timetable State Machine | ✅ Implemented | UPLOADED→EXTRACTING→REVIEW_REQUIRED→CONFIRMED→ARCHIVED |
| Timetable Query (deterministic) | ✅ Implemented | Today/tomorrow/next class/first class |
| Briefing Service | ✅ Implemented | Deterministic facts + natural language rendering |
| Briefing Scheduler | ✅ Implemented | Per-student timezone/time; idempotent delivery |
| Telegram Briefing Scheduler | ✅ Implemented | Per-student timezone/time; idempotent delivery |
| Portal Adapter (Doctus) | ✅ Implemented | Login, semesters, attendance HTML parsing |
| Portal Credential Store | ✅ Implemented | Encrypted storage, portal credential model |
| Portal Sync Service | ✅ Implemented | Sync attendance from portal to snapshots |
| Attendance Sync Tool | ✅ Implemented | CLI tool for manual/auto sync |
| Briefing Service | ✅ Implemented | Deterministic facts + natural language rendering |
| Briefing Scheduler | ✅ Implemented | Per-student timezone/time; idempotent delivery |
| Telegram Briefing Scheduler | ✅ Implemented | Per-student timezone/time; idempotent delivery |
| Security/Auth/Ownership | ✅ Implemented | Student resolver, identity resolution, authz |
| Audit Logging | ✅ Implemented | Immutable events, Telegram linking audit |
| Multi-user Isolation | ✅ Implemented | Student ownership root, repo scoping |
| LLM Provider Abstraction | ✅ Implemented | OpenAI-compatible + Mock; provider registry |
| LLM Intent Interpretation | ✅ Implemented | LLM extracts intent/entities → tool dispatch |
| Tool Registry/Dispatch | ✅ Implemented | Typed tools for timetable, attendance, simulations |
| Telegram Message Handler | ✅ Implemented | Idempotency, identity resolution, conversation pipeline |
| Telegram Identity Linking | ✅ Implemented | Challenge/verify flow, audit, TelegramIdentity creation |
| Telegram Linking Service | ✅ Implemented | Challenge creation/verification, audit logging |
| LLM Provider Abstraction | ✅ Implemented | OpenAI-compatible + Mock; provider registry |
| Real LLM Provider (OpenAI-compatible) | ✅ Implemented | OpenRouter/NVIDIA/OpenCode Zen compatible |
| Attendance Service (deterministic) | ✅ Implemented | Snapshots, summaries, simulations, recovery calc |
| Attendance Tools | ✅ Implemented | Simulate absence, recovery, subjects below target |
| Timetable Service (state machine) | ✅ Implemented | Upload→Extract→Review→Confirm→Archive |
| Timetable Extraction | ✅ Implemented | PDF/image → cells → entries; slash lab handling |
| Timetable State Machine | ✅ Implemented | UPLOADED→EXTRACTING→REVIEW_REQUIRED→CONFIRMED→ARCHIVED |
| Timetable Query (deterministic) | ✅ Implemented | Today/tomorrow/next class/first class |
| Briefing Service | ✅ Implemented | Deterministic facts + natural language rendering |
| Briefing Scheduler | ✅ Implemented | Per-student timezone/time; idempotent delivery |
| Telegram Briefing Scheduler | ✅ Implemented | Per-student timezone/time; idempotent delivery |
| Telegram Message Handler | ✅ Implemented | Idempotency, identity resolution, conversation pipeline |
| Telegram Identity Linking | ✅ Implemented | Challenge/verify flow, audit, TelegramIdentity creation |
| Telegram Linking Service | ✅ Implemented | Challenge creation/verification, audit logging |
| LLM Provider Abstraction | ✅ Implemented | OpenAI-compatible + Mock; provider registry |
| Real LLM Provider (OpenAI-compatible) | ✅ Implemented | OpenRouter/NVIDIA/OpenCode Zen compatible |
| Attendance Service (deterministic) | ✅ Implemented | Snapshots, summaries, simulations, recovery calc |
| Attendance Tools | ✅ Implemented | Simulate absence, recovery, subjects below target |
| Timetable Service (state machine) | ✅ Implemented | Upload→Extract→Review→Confirm→Archive |
| Timetable Extraction | ✅ Implemented | PDF/image → cells → entries; slash lab handling |
| Timetable State Machine | ✅ Implemented | UPLOADED→EXTRACTING→REVIEW_REQUIRED→CONFIRMED→ARCHIVED |
| Timetable Query (deterministic) | ✅ Implemented | Today/tomorrow/next class/first class |
| Briefing Service | ✅ Implemented | Deterministic facts + natural language rendering |
| Briefing Scheduler | ✅ Implemented | Per-student timezone/time; idempotent delivery |
| Telegram Briefing Scheduler | ✅ Implemented | Per-student timezone/time; idempotent delivery |
| Portal Adapter (Doctus) | ✅ Implemented | Login, semesters, attendance HTML parsing |
| Portal Credential Store | ✅ Implemented | Encrypted storage, portal credential model |
| Portal Sync Service | ✅ Implemented | Sync attendance from portal to snapshots |
| Attendance Sync Tool | ✅ Implemented | CLI tool for manual/auto sync |
| Security/Auth/Ownership | ✅ Implemented | Student resolver, identity resolution, authz |
| Audit Logging | ✅ Implemented | Immutable events, Telegram linking audit |
| Multi-user Isolation | ✅ Implemented | Student ownership root, repo scoping |

**What's NOT Implemented (Intentional Deferral):**
- Web/mobile app (WhatsApp/Telegram is the interface)
- Vector DB / embeddings / RAG
- Multi-college tenancy
- Grade tracking / assignment submission
- Real-time collaboration features
- OCR fallback for timetable (image extraction is primary)
- Vector DB / embeddings / RAG
- Multi-college tenancy
- Grade tracking / assignment submission
- Real-time collaboration features
- OCR fallback for timetable (image extraction is primary path)
- Broader platform rollout (Personal Alpha → Controlled Pilot → Broader Platform)

---

## Rollout Phases

| Phase | Scope | Status |
|-------|-------|--------|
| 1 | Foundation scaffolding | ✅ Complete |
| 2 | Database, auth, multi-user ownership | ✅ Complete |
| 3 | WhatsApp abstraction, message processing | ✅ Complete (abstraction + spike) |
| 4 | LLM abstraction, tool dispatch | ✅ Complete |
| 5 | Attendance domain engine | ✅ Complete |
| 6 | Timetable ingestion and state machine | ✅ Complete |
| 7 | Daily briefing worker | ✅ Complete |
| 8 | College portal integration | ✅ Complete |
| 9 | Invite-only pilot | Not started |
| 10 | Broader college platform | Not started |

---

## Non-Goals (Explicitly Deferred)

- Web/mobile app (WhatsApp/Telegram is the interface)
- Vector DB / embeddings / RAG
- Multi-college tenancy
- Grade tracking / assignment submission
- Real-time collaboration features
- OCR fallback for timetable (image extraction is primary)
- Broader platform rollout (Personal Alpha → Controlled Pilot → Broader Platform)