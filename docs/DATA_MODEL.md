# Data Model — Beru

## Implemented Entities (Milestone 2: Database Foundation)

### Student
**Table:** `students`

| Column | Type | Constraints |
|---|---|---|
| id | UUID | PRIMARY KEY, DEFAULT gen_random_uuid() |
| status | VARCHAR(8) | NOT NULL, DEFAULT 'active' |
| created_at | TIMESTAMP WITH TIME ZONE | NOT NULL, DEFAULT now() |
| updated_at | TIMESTAMP WITH TIME ZONE | NOT NULL, DEFAULT now() |

- **Ownership root** — all student-owned resources resolve through `Student.id`.
- Status enum: `active`, `inactive` (for future soft-delete/archive).
- UUID primary keys for domain entities.

### WhatsAppIdentity
**Table:** `whatsapp_identities`

| Column | Type | Constraints |
|---|---|---|
| id | UUID | PRIMARY KEY, DEFAULT gen_random_uuid() |
| student_id | UUID | FOREIGN KEY → students.id ON DELETE CASCADE |
| provider | VARCHAR(15) | NOT NULL, DEFAULT 'unknown' |
| provider_user_id | VARCHAR(255) | NOT NULL |
| normalized_identifier | VARCHAR(255) | NULLABLE |
| status | VARCHAR(8) | NOT NULL, DEFAULT 'active' |
| created_at | TIMESTAMP WITH TIME ZONE | NOT NULL, DEFAULT now() |
| updated_at | TIMESTAMP WITH TIME ZONE | NOT NULL, DEFAULT now() |

- **Unique constraint** on `(provider, provider_user_id)` — prevents same external identity belonging to multiple students.
- **Indexes** on `student_id` and `normalized_identifier` for lookup performance.
- Provider enum: `unknown`, `whatsapp_web_js`, `baileys`, `meta_cloud_api`.
- Status enum: `active`, `disabled`, `revoked`.
- Provider-neutral design — not tied to specific WhatsApp bridge implementation.

## Planned Entities (Future Milestones)

### AttendanceRecord
- Per-subject attendance entries.
- Source: college portal scrape or manual input.
- Linked to Student (via ownership).

### Timetable
- Versioned timetable entries.
- State machine: UPLOADED → EXTRACTING → REVIEW_REQUIRED → CONFIRMED → ARCHIVED.
- Linked to Student.

### AuditLog
- Security-sensitive operations.
- Immutable append-only.

## Notes

- All resources must have `owner_id` (Student.id) for ownership enforcement.
- Timestamps are timezone-aware (TIMESTAMP WITH TIME ZONE).
- Simulations produce ephemeral results — no database mutation.
- PostgreSQL-specific types used (UUID, TIMESTAMP WITH TIME ZONE) — not SQLite-compatible by design.

## Relationships

```
Student (1) ───< (N) WhatsAppIdentity
  │
  └── Future: AttendanceRecord, Timetable, etc.
```