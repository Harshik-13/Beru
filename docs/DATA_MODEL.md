# Data Model — Beru

**Status:** Not yet implemented. This document tracks planned data entities.

## Planned Entities

### User
- Primary identity record.
- Links to WhatsApp identity.
- `owner_id` for multi-user isolation.

### AttendanceRecord
- Per-subject attendance entries.
- Source: college portal scrape or manual input.
- Linked to User.

### Timetable
- Versioned timetable entries.
- State machine: UPLOADED → EXTRACTING → REVIEW_REQUIRED → CONFIRMED → ARCHIVED.
- Linked to User.

### AuditLog
- Security-sensitive operations.
- Immutable append-only.

## Notes

- All resources must have `owner_id` for ownership enforcement.
- Timestamps and provenance are required on attendance snapshots.
- Simulations produce ephemeral results — no database mutation.
