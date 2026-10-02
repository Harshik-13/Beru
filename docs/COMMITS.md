# COMMITS.md — Beru

## Attendance & Portal

| Commit | Date | Purpose | Subsystem | Verification |
|--------|------|---------|-----------|--------------|
| `b196cea` | 2026-10-02 | Fix portal sync greenlet error, add read-time snapshot reconciliation, and clarify attendance target status | Portal, Attendance, Rendering | 428 tests pass |
| `e33cac9` | 2026-10-02 | Allow null for optional tool arguments preventing Groq 400 validation error | Intelligence, Tools | 423 tests pass |
| `e043673` | 2026-10-02 | Dual overall/monthly attendance, multi-turn dialogue state & course mapping | Intelligence, Attendance, Portal | 423 tests pass |
| `dc82254` | 2026-10-02 | Align Doctus integration with App workspace, STDINFO widget, and undefined semId flow | Portal, Sync, Parser | 416 tests pass |
| `a72e07e` | 2026-10-02 | Direct GetStdAttPer attendance retrieval, timetable semId resolution, and redirect diagnostics | Portal, Sync, Parser | 416 tests pass |
| `1427eee` | 2026-10-01 | Reproduce browser document request on /Student/Dashboard and validate semId | Portal, Sync, Parser | 414 tests pass |
| `2b2f301` | 2026-10-01 | Align get_semesters to /Student/Dashboard and fix frozen PortalAttendance construction | Portal, Parser, Attendance | 414 tests pass |
| `6c74197` | 2026-10-01 | Fix student ID resolution, HTML extraction, and canonical attendance contract | Portal, Sync, Attendance | 412 tests pass |
| `d7282b1` | 2026-10-01 | Fix Doctus authentication and session handling with ASP.NET Core protocol & zero-retry guard | Portal, Security, Attendance | 405 tests pass |
| `21ee0d0` | 2026-10-01 | Live Doctus integration, zero-leak credential boundary, 4h freshness sync & concurrency locking | Portal, Attendance, Security | 385 tests pass |

## Timetable

| Commit | Date | Purpose | Subsystem | Verification |
|--------|------|---------|-----------|--------------|
| `b1f9644` | 2026-10-01 | Conversational synthesis for atomic queries, self-model persona & Telegram sanitization | Intelligence, Rendering | 364 tests pass |
| `1636e4e` | 2026-10-01 | Fix 429 retry logging, room fallback, legend DB enrichment & tool disambiguation | Intelligence, Timetable | 358 tests pass |
| `68d36f7` | 2026-09-30 | Encyclopedic timetable tools, schedule analytics & semantic-invariance tests | Timetable, Intelligence, Rendering | 353 tests pass |
| `2c585b3` | 2026-09-30 | Presentation decoupling, ResponseStyleLayer, missing-field omission & 429 resilience | Intelligence, Rendering, Telegram | 345 tests pass |
| `fdaea24` | 2026-09-29 | Fix LLM async promise hallucination and normalize weekday tool arguments | Intelligence, Timetable | 62 timetable tests pass |
| `cdbfef3` | 2026-09-29 | Fix duplicate slash-lab entries during timetable extraction | Timetable, Extraction | 62 timetable tests pass |
| `77f9271` | 2026-09-29 | Fix MultipleResultsFound on timetable queries with limit(1) | Timetable, DB | 62 timetable tests pass |
| `c2833d0` | 2026-09-29 | Phase 4C: full E2E pipeline, briefing scheduler integration & natural-language paraphrase simulation | Timetable, Intelligence, Briefing | 331 tests pass |
| `5c0c5f2` | 2026-09-29 | Phase 4B: security, boundary, failure-path & duplicate-upload hardening | Timetable, Security | 325 tests pass |
| `fabf9d2` | 2026-09-29 | Phase 4A: enrich academic profile, college domain self-model, and semantic tool definitions | Timetable, Telegram, Identity | 312 tests pass |
| `054488e` | 2026-09-29 | Phase 3: briefing time, week/weekday/metadata tools, course_metadata mapping | Timetable, Intelligence | Code complete |
| `c448e4e` | 2026-09-29 | Phase 2: correction tools, review context, explicit confirm | Timetable, Intelligence | Code complete |
| `e7622bb` | 2026-09-29 | Phase 1: disable auto-confirm, show weekday grid, photo upload | Timetable, Telegram | Code complete |

## Infrastructure

| Commit | Date | Purpose | Subsystem | Verification |
|--------|------|---------|-----------|--------------|
| `b13836f` | 2026-09-29 | Add permanent documentation synchronization rule | Docs | 292 tests pass |
| `3806fd4` | 2026-09-29 | Reconcile project documentation | Docs | 292 tests pass |

## Foundation

| Commit | Date | Purpose | Subsystem | Verification |
|--------|------|---------|-----------|--------------|
| `ca06495` | 2026-09-25 | Initial project scaffolding | All | Tests pass |
| `2dc8215` | 2026-09-25 | Database and ownership foundation | DB, Models | Tests pass |
| `6a5cdfc` | 2026-09-25 | Authentication and authorization foundation | Security | Tests pass |

## Database

| Commit | Date | Purpose | Subsystem | Verification |
|--------|------|---------|-----------|--------------|
| `5d414855ae22` | 2026-09-25 | Initial migration: students, whatsapp_identities | DB | Applied |
| `14fe74f16b74` | 2026-09-25 | Add audit events table | DB, Audit | Applied |
| `8f7e3a2b1c9d` | 2026-09-26 | Add timetable tables | DB, Timetable | Applied |
| `9a8b7c6d5e4f` | 2026-09-26 | Add attendance tables | DB, Attendance | Applied |
| `b2c3d4e5f6a7` | 2026-09-27 | Add portal credentials table | DB, Portal | Applied |
| `a1b2c3d4e5f6` | 2026-09-27 | Add telegram identities table | DB, Telegram | Applied |
| `c1d2e3f4a5b6` | 2026-09-28 | Add telegram linking challenge | DB, Telegram | Applied |
| `d1e2f3a4b5c6` | 2026-09-28 | Add briefing deliveries table | DB, Briefing | Applied |
| `e2f3a4b5c6d7` | 2026-09-28 | Add student briefing fields | DB, Student | Applied |
| `f3a4b5c6d7e8` | 2026-09-29 | Add student profile fields | DB, Student | Applied |

## Auth

| Commit | Date | Purpose | Subsystem | Verification |
|--------|------|---------|-----------|--------------|
| `6a5cdfc` | 2026-09-25 | Authentication and authorization foundation | Security | Tests pass |
| `13eed5b` | 2026-09-29 | Telegram identity linking | Security, Telegram | Tests pass |

## Intelligence

| Commit | Date | Purpose | Subsystem | Verification |
|--------|------|---------|-----------|--------------| 
| `6995d04` | 2026-09-30 | Phase 1 presentation decoupling, style layer, field omission, and week key fix | Intelligence, Rendering | 345 tests pass, 14 golden tests |
| `e6ec09d` | 2026-09-29 | Add network retry in bot adapter and refine schedule tool descriptions | Telegram, Intelligence | 341 tests pass |
| `2c585b3` | 2026-09-29 | Deterministic structured renderers, RendererRegistry, and style contract | Intelligence, Rendering, Telegram | 341 tests pass, 10 golden tests |
| `f765640` | 2026-09-29 | Fix Groq 400: strip student_id from LLM tool schemas, add error fallback | Intelligence, Telegram | 310 tests pass |
| `008d890` | 2026-09-29 | Fix real LLM message conversion, auto-register tools, add aliases, enrich persona | LLM, Intelligence | 303 tests pass |
| `f256662` | 2026-09-29 | Accept pre-formatted OpenAI tool schemas in _convert_tools | LLM, Intelligence | RUNTIME VERIFIED |
| `d40585f` | 2026-09-25 | Establish Beru intelligence foundation | Intelligence | Tests pass |
| `bbeeca9` | 2026-09-25 | Establish multi-provider LLM architecture | LLM | Tests pass |
| `23d10c9` | 2026-09-25 | Close phase 7 LLM integration | LLM | Tests pass |
| `635e5ff` | 2026-09-29 | Integrate real LLM provider into Telegram conversation flow | LLM, Telegram | RUNTIME VERIFIED |

## Providers

| Commit | Date | Purpose | Subsystem | Verification |
|--------|------|---------|-----------|--------------|
| `c32e1ee` | 2026-09-29 | Telegram Bot API adapter foundation | Telegram | Tests pass |
| `7fb5675` | 2026-09-29 | Telegram Bot API startup verification | Telegram | Tests pass |
| `30ca262` | 2026-09-28 | Baileys WhatsApp provider adapter | WhatsApp | Tests pass |
| `5254ac4` | 2026-09-28 | Fix Baileys persisted-session reconnection | WhatsApp | Tests pass |

## Timetable

| Commit | Date | Purpose | Subsystem | Verification |
|--------|------|---------|-----------|--------------|
| `5c0c5f2` | 2026-09-29 | Phase 4B: Security, boundary, failure-path & duplicate-upload hardening | Timetable, Tests | 13 tests pass |
| `fabf9d2` | 2026-09-29 | Phase 4A: Enrich academic profile, college domain self-model, and semantic tool definitions | Timetable, Intelligence | Tests pass |
| `054488e` | 2026-09-29 | Phase 3: Briefing time, week/weekday/metadata tools, course_metadata mapping | Timetable | Tests pass |
| `de13925` | 2026-09-29 | Implement hybrid OCR timetable extractor for scanned/image PDFs | Timetable | 312 tests pass |
| `f9ed817` | 2026-09-29 | Fix state machine transition before auto-confirmation | Timetable | 309 tests pass |
| `8f2daf9` | 2026-09-26 | Implement timetable pipeline | Timetable | Tests pass |
| `2a240a6` | 2026-09-26 | Verify timetable confirmation and extraction | Timetable | Tests pass |

## Attendance

| Commit | Date | Purpose | Subsystem | Verification |
|--------|------|---------|-----------|--------------|
| `2a38290` | 2026-09-26 | Attendance domain foundation | Attendance | Tests pass |
| `9408c09` | 2026-09-26 | Attendance service, calculations, and tools | Attendance | Tests pass |
| `b2c6a19` | 2026-09-26 | Wire date-based attendance simulation | Attendance | Tests pass |

## Telegram

| Commit | Date | Purpose | Subsystem | Verification |
|--------|------|---------|-----------|--------------|
| `cb61881` | 2026-09-29 | Decouple TelegramBotAdapter, scope DB session per message, fix logging | Telegram | 298 tests pass |
| `c32e1ee` | 2026-09-29 | Telegram Bot API adapter foundation | Telegram | Tests pass |
| `7fb5675` | 2026-09-29 | Telegram Bot API startup verification | Telegram | Tests pass |
| `13eed5b` | 2026-09-29 | Telegram identity linking | Telegram | Tests pass |
| `5609fb9` | 2026-09-29 | Telegram conversation integration | Telegram | Tests pass |
| `00471e1` | 2026-09-29 | Fix Telegram startup wiring | Telegram | RUNTIME VERIFIED |
| `2c16e7d` | 2026-09-29 | Align enum values with DB | Telegram | RUNTIME VERIFIED |
| `055bb09` | 2026-09-29 | Fix session lifetime and enum casting | Telegram | RUNTIME VERIFIED |
| `3d11e42` | 2026-09-29 | Align TelegramLinkingChallenge status with PostgreSQL native enum | Telegram | RUNTIME VERIFIED |
| `ec4fad8` | 2026-09-29 | Timetable media ingestion, proactive prompt, confirmation tool, multi-turn context | Telegram, Intelligence | 308 tests pass |
| `13fe634` | 2026-09-29 | Fix PostgreSQL native enums, export models, and safe commits | Telegram, DB | RUNTIME VERIFIED |

## Briefing

| Commit | Date | Purpose | Subsystem | Verification |
|--------|------|---------|-----------|--------------|
| `b34f58a` | 2026-09-29 | Daily morning briefing scheduler with Telegram delivery | Briefing | Tests pass |
| `512dadd` | 2026-09-29 | Persist student profile name and attendance target | Briefing, Student | Tests pass |

## Infrastructure

| Commit | Date | Purpose | Subsystem | Verification |
|--------|------|---------|-----------|--------------|
| `7db7f76` | 2026-09-29 | Repair alembic migration chain | DB, Migrations | RUNTIME VERIFIED |
| `2570ae7` | 2026-09-29 | Add BERU_STATE.md and update AGENTS.md | Docs | N/A |

## Portal

| Commit | Date | Purpose | Subsystem | Verification |
|--------|------|---------|-----------|--------------|
| `ad5d9fc` | 2026-09-27 | Doctus portal adapter and credential boundary | Portal | Tests pass |
| `cf21f73` | 2026-09-27 | Portal sync service and attendance sync tool | Portal | Tests pass |
| `f7499c1` | 2026-09-27 | Protected studentId extraction in Doctus adapter | Portal | Tests pass |