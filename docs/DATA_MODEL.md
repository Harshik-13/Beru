# Data Model — Beru

## Implemented Entities (Milestone 2: Database Foundation + Milestone 3: Auth Foundation)

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

### AuditEvent
**Table:** `audit_events`

| Column | Type | Constraints |
|---|---|---|
| id | UUID | PRIMARY KEY, DEFAULT gen_random_uuid() |
| event_type | VARCHAR(50) | NOT NULL |
| student_id | UUID | FOREIGN KEY → students.id ON DELETE SET NULL |
| provider | VARCHAR(50) | NULLABLE |
| external_identity_id | VARCHAR(255) | NULLABLE |
| resource_type | VARCHAR(50) | NULLABLE |
| resource_id | UUID | NULLABLE |
| success | BOOLEAN | NOT NULL, DEFAULT true |
| error_message | TEXT | NULLABLE |
| event_metadata | TEXT | NULLABLE |
| created_at | TIMESTAMP WITH TIME ZONE | NOT NULL, DEFAULT now() |
| updated_at | TIMESTAMP WITH TIME ZONE | NOT NULL, DEFAULT now() |

- **Indexes** on `(student_id, created_at)` and `(event_type, created_at)` for query performance.
- Event type enum: `authentication_success`, `authentication_failure`, `identity_disabled`, `identity_revoked`, `unauthorized_access`, `authorization_failure`, `student_created`, `whatsapp_identity_created`, `whatsapp_identity_updated`.
- Append-only by design — no UPDATE/DELETE paths in application code.
- No secrets, credentials, or raw message payloads stored.

## Planned Entities (Future Milestones)

### AttendanceRecord
- Per-subject attendance entries.
- Source: college portal scrape or manual input.
- Linked to Student (via ownership).

### Timetable
- Versioned timetable entries.
- State machine: UPLOADED → EXTRACTING → REVIEW_REQUIRED → CONFIRMED → ARCHIVED.
- Linked to Student.

## Notes

- All resources must have `owner_id` (Student.id) for ownership enforcement.
- Timestamps are timezone-aware (TIMESTAMP WITH TIME ZONE).
- Simulations produce ephemeral results — no database mutation.
- PostgreSQL-specific types used (UUID, TIMESTAMP WITH TIME ZONE) — not SQLite-compatible by design.

## Relationships

```
Student (1) ───< (N) WhatsAppIdentity
  │
  ├── (N) AuditEvent (nullable student_id for auth failures)
  │
  └── Future: AttendanceRecord, Timetable, etc.
```