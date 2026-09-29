# Data Model — Beru

## Current Entities

### Student
**Table:** `students`

| Column | Type | Constraints |
|---|---|---|
| id | UUID | PRIMARY KEY |
| status | VARCHAR(8) | NOT NULL, DEFAULT 'active' |
| lab_batch | VARCHAR(10) | NOT NULL, DEFAULT 'unknown' |
| name | VARCHAR(100) | NULLABLE |
| attendance_target | FLOAT | NULLABLE |
| briefing_time | VARCHAR(5) | NULLABLE (HH:MM) |
| timezone | VARCHAR(50) | NOT NULL, DEFAULT 'Asia/Kolkata' |
| created_at | TIMESTAMP WITH TIME ZONE | NOT NULL, DEFAULT now() |
| updated_at | TIMESTAMP WITH TIME ZONE | NOT NULL, DEFAULT now() |

- **Ownership root** — all student-owned resources resolve through `Student.id`.
- Status enum: `active`, `inactive`.
- Lab batch enum: `unknown`, `batch_1`, `batch_2`.

### TelegramIdentity
**Table:** `telegram_identities`

| Column | Type | Constraints |
|---|---|---|
| id | UUID | PRIMARY KEY |
| student_id | UUID | FK → students.id ON DELETE CASCADE |
| provider | VARCHAR(15) | NOT NULL, DEFAULT 'telegram_bot' |
| provider_user_id | VARCHAR(255) | NOT NULL |
| normalized_identifier | VARCHAR(255) | NULLABLE |
| status | VARCHAR(8) | NOT NULL, DEFAULT 'active' |
| created_at | TIMESTAMP WITH TIME ZONE | NOT NULL, DEFAULT now() |
| updated_at | TIMESTAMP WITH TIME ZONE | NOT NULL, DEFAULT now() |

- **Unique constraint** on `(provider, provider_user_id)`.
- Status enum: `active`, `disabled`, `revoked`.

### TelegramLinkingChallenge
**Table:** `telegram_linking_challenges`

| Column | Type | Constraints |
|---|---|---|
| id | UUID | PRIMARY KEY |
| telegram_user_id | VARCHAR(255) | NOT NULL |
| challenge_token | VARCHAR(64) | NOT NULL, UNIQUE |
| expires_at | TIMESTAMP WITH TIME ZONE | NOT NULL |
| status | VARCHAR(20) | NOT NULL, DEFAULT 'pending' |
| student_id | UUID | NULLABLE, FK → students.id ON DELETE SET NULL |
| telegram_identity_id | UUID | NULLABLE, FK → telegram_identities.id ON DELETE SET NULL |
| created_at | TIMESTAMP WITH TIME ZONE | NOT NULL, DEFAULT now() |
| updated_at | TIMESTAMP WITH TIME ZONE | NOT NULL, DEFAULT now() |

- Status values: `pending`, `used`, `expired` (lowercase, stored as String).
- 10-minute TTL, single-use.

### Timetable
**Table:** `timetables`

| Column | Type | Constraints |
|---|---|---|
| id | UUID | PRIMARY KEY |
| student_id | UUID | FK → students.id ON DELETE CASCADE |
| status | VARCHAR(20) | NOT NULL, DEFAULT 'uploaded' |
| version | INTEGER | NOT NULL, DEFAULT 1 |
| academic_year | VARCHAR(20) | NULLABLE |
| regulation | VARCHAR(50) | NULLABLE |
| programme | VARCHAR(100) | NULLABLE |
| branch | VARCHAR(100) | NULLABLE |
| year | INTEGER | NULLABLE |
| semester | INTEGER | NULLABLE |
| section | VARCHAR(10) | NULLABLE |
| effective_from | DATE | NULLABLE |
| default_classroom | VARCHAR(100) | NULLABLE |
| confirmed_at | TIMESTAMP WITH TIME ZONE | NULLABLE |
| created_at | TIMESTAMP WITH TIME ZONE | NOT NULL, DEFAULT now() |
| updated_at | TIMESTAMP WITH TIME ZONE | NOT NULL, DEFAULT now() |

- Status enum: `uploaded`, `extracting`, `review_required`, `confirmed`, `archived`, `failed`.

### TimetableEntry
**Table:** `timetable_entries`

| Column | Type | Constraints |
|---|---|---|
| id | UUID | PRIMARY KEY |
| timetable_id | UUID | FK → timetables.id ON DELETE CASCADE |
| day_of_week | INTEGER | NOT NULL (0=Mon, 6=Sun) |
| start_time | TIME | NOT NULL |
| end_time | TIME | NOT NULL |
| activity_name | VARCHAR(200) | NOT NULL |
| activity_type | VARCHAR(20) | NOT NULL |
| course_code | VARCHAR(20) | NULLABLE |
| room | VARCHAR(50) | NULLABLE |
| faculty | VARCHAR(100) | NULLABLE |
| lab_batch | VARCHAR(10) | NULLABLE |
| extraction_confidence | FLOAT | NULLABLE |
| extraction_notes | TEXT | NULLABLE |
| created_at | TIMESTAMP WITH TIME ZONE | NOT NULL, DEFAULT now() |
| updated_at | TIMESTAMP WITH TIME ZONE | NOT NULL, DEFAULT now() |

- Activity type enum: `academic`, `lab`, `break`, `activity`.

### AttendanceSnapshot
**Table:** `attendance_snapshots`

| Column | Type | Constraints |
|---|---|---|
| id | UUID | PRIMARY KEY |
| student_id | UUID | FK → students.id ON DELETE CASCADE |
| source | VARCHAR(20) | NOT NULL |
| captured_at | TIMESTAMP WITH TIME ZONE | NOT NULL |
| semester_id | VARCHAR(50) | NULLABLE |
| overall_attended | INTEGER | NOT NULL |
| overall_conducted | INTEGER | NOT NULL |
| created_at | TIMESTAMP WITH TIME ZONE | NOT NULL, DEFAULT now() |
| updated_at | TIMESTAMP WITH TIME ZONE | NOT NULL, DEFAULT now() |

- Source enum: `doctus`.
- Check: `overall_attended <= overall_conducted`.

### SubjectAttendance
**Table:** `subject_attendance`

| Column | Type | Constraints |
|---|---|---|
| id | UUID | PRIMARY KEY |
| snapshot_id | UUID | FK → attendance_snapshots.id ON DELETE CASCADE |
| subject_code | VARCHAR(20) | NOT NULL |
| subject_name | VARCHAR(100) | NULLABLE |
| monthly_period | VARCHAR(20) | NULLABLE |
| monthly_attended | INTEGER | NULLABLE |
| monthly_conducted | INTEGER | NULLABLE |
| cumulative_attended | INTEGER | NOT NULL |
| cumulative_conducted | INTEGER | NOT NULL |
| created_at | TIMESTAMP WITH TIME ZONE | NOT NULL, DEFAULT now() |
| updated_at | TIMESTAMP WITH TIME ZONE | NOT NULL, DEFAULT now() |

### BriefingDelivery
**Table:** `briefing_deliveries`

| Column | Type | Constraints |
|---|---|---|
| id | UUID | PRIMARY KEY |
| student_id | UUID | FK → students.id ON DELETE CASCADE |
| telegram_identity_id | UUID | FK → telegram_identities.id ON DELETE CASCADE |
| delivery_date | DATE | NOT NULL |
| status | VARCHAR(20) | NOT NULL, DEFAULT 'pending' |
| scheduled_at | TIMESTAMP WITH TIME ZONE | NOT NULL |
| sent_at | TIMESTAMP WITH TIME ZONE | NULLABLE |
| error_message | TEXT | NULLABLE |
| attempt_count | INTEGER | NOT NULL, DEFAULT 0 |
| created_at | TIMESTAMP WITH TIME ZONE | NOT NULL, DEFAULT now() |
| updated_at | TIMESTAMP WITH TIME ZONE | NOT NULL, DEFAULT now() |

- **Unique constraint** on `(student_id, delivery_date)` — idempotency.
- Status values: `pending`, `sent`, `failed` (lowercase, stored as String).

### AuditEvent
**Table:** `audit_events`

| Column | Type | Constraints |
|---|---|---|
| id | UUID | PRIMARY KEY |
| event_type | VARCHAR(50) | NOT NULL |
| student_id | UUID | NULLABLE, FK → students.id ON DELETE SET NULL |
| provider | VARCHAR(50) | NULLABLE |
| external_identity_id | VARCHAR(255) | NULLABLE |
| resource_type | VARCHAR(50) | NULLABLE |
| resource_id | UUID | NULLABLE |
| success | BOOLEAN | NOT NULL, DEFAULT true |
| error_message | TEXT | NULLABLE |
| event_metadata | TEXT | NULLABLE |
| created_at | TIMESTAMP WITH TIME ZONE | NOT NULL, DEFAULT now() |
| updated_at | TIMESTAMP WITH TIME ZONE | NOT NULL, DEFAULT now() |

- Append-only by design.

### WhatsAppIdentity
**Table:** `whatsapp_identities`

| Column | Type | Constraints |
|---|---|---|
| id | UUID | PRIMARY KEY |
| student_id | UUID | FK → students.id ON DELETE CASCADE |
| provider | VARCHAR(15) | NOT NULL |
| provider_user_id | VARCHAR(255) | NOT NULL |
| normalized_identifier | VARCHAR(255) | NULLABLE |
| status | VARCHAR(8) | NOT NULL, DEFAULT 'active' |
| created_at | TIMESTAMP WITH TIME ZONE | NOT NULL, DEFAULT now() |
| updated_at | TIMESTAMP WITH TIME ZONE | NOT NULL, DEFAULT now() |

- **Unique constraint** on `(provider, provider_user_id)`.

### PortalCredential
**Table:** `portal_credentials`

| Column | Type | Constraints |
|---|---|---|
| id | UUID | PRIMARY KEY |
| student_id | UUID | FK → students.id ON DELETE CASCADE |
| roll_number | VARCHAR(50) | NOT NULL |
| encrypted_password | TEXT | NOT NULL |
| created_at | TIMESTAMP WITH TIME ZONE | NOT NULL, DEFAULT now() |
| updated_at | TIMESTAMP WITH TIME ZONE | NOT NULL, DEFAULT now() |

- Password encrypted at rest.

## Relationships

```
Student (1) ───< (N) TelegramIdentity
  │
  ├── (N) TelegramLinkingChallenge
  │
  ├── (N) Timetable (1) ───< (N) TimetableEntry
  │
  ├── (N) AttendanceSnapshot (1) ───< (N) SubjectAttendance
  │
  ├── (N) BriefingDelivery
  │
  ├── (N) AuditEvent (nullable student_id for auth failures)
  │
  ├── (N) WhatsAppIdentity
  │
  └── (N) PortalCredential
```

## Notes

- All resources have `owner_id` (Student.id) for ownership enforcement.
- Timestamps are timezone-aware.
- Simulations produce ephemeral results — no database mutation.
- PostgreSQL-specific types used (UUID, TIMESTAMP WITH TIME ZONE).