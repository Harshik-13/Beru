# Beru — AI College Copilot

A privacy-first, multi-tenant AI backend that helps college students manage timetables, attendance tracking, absence simulations, and daily morning briefings directly inside **Telegram** (with a replaceable adapter architecture ready for WhatsApp).

> **Status:** Personal Alpha — Live Telegram bot, deterministic domain services, encrypted portal sync, and per-user briefing scheduler operational.

<!-- Replace with a 20–30 second screen recording GIF of an attendance simulation + morning briefing -->
<!-- ![Beru Telegram Demo](docs/assets/demo.gif) -->

---

## Key Engineering Decisions

Most student AI projects are thin LLM wrappers. Beru is built as a deterministic backend system where the LLM is strictly sandboxed:

* **Backend as the Security & Determinism Boundary:** The LLM never touches raw credentials, enforces authorization, or performs attendance arithmetic. It strictly extracts intent/entities and formats final responses; all calculations execute in typed, deterministic domain services.
* **5-Stage Timetable State Machine:** Image/PDF timetable uploads move through an explicit lifecycle (`UPLOADED → EXTRACTING → REVIEW_REQUIRED → CONFIRMED → ARCHIVED`), handling slash-separated lab batches before becoming queryable.
* **Challenge-Based Identity & Multi-User Isolation:** No username/password auth. Students link accounts via a `/start` challenge-verify flow backed by immutable audit logs, with `Student` enforced as the strict ownership root across all repository queries.
* **Idempotent Scheduling & Portal Sync:** Per-student timezone-aware morning briefings use idempotent delivery keys to prevent duplicate sends. College portal (Doctus) credentials are stored encrypted at rest and synced into immutable attendance snapshots.

---

## System Architecture

```mermaid
flowchart LR
    TG[Telegram Bot Adapter] --> ID[Identity & Authz Resolver]
    ID --> LLM1[LLM Intent Parser]
    LLM1 --> TD[Typed Tool Dispatcher]
    TD --> SVC[Deterministic Domain Services<br/>Timetable · Attendance · Simulations]
    SVC --> DB[(Database & Encrypted<br/>Credential Store)]
    SVC --> LLM2[LLM Response Formatter]
    LLM2 --> TG
    SCH[Timezone Briefing Scheduler] -->|Idempotent| SVC
