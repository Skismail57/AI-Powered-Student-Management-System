# Student Management System API (Backend)

Base URL: `http://localhost:5000`

Auth: Most endpoints require `Authorization: Bearer <token>`

## Auth

### POST `/register`
- **Body**
  - `name` (string)
  - `role` (`admin|faculty|student`)
  - `mobile` (string)
  - `password` (string)

### POST `/login`
- **Body**
  - `mobile` (string)
  - `password` (string)
- **Response**
  - `token`
  - `user` `{ id, name, role }`

### POST `/token/refresh`
- **Auth required**
- **Response**
  - `token` (new JWT)

## Students

### GET `/students`
- **Auth required**
- **Query**
  - `search` (string)
  - `attendance` (`all|low|medium|high`)
  - `risk` (`all|atrisk|good`)
  - `limit` (int)
  - `paged=1` (enable paginated response)
  - `page` (int, default 1)
  - `page_size` (int, default 25, max 200)
- **Response**
  - default: `[{student}, ...]`
  - when `paged=1`:
    - `{ items, page, page_size, total, total_pages }`

### POST `/students`
- **Role**: `admin|faculty`
- **Body**
  - `name` (string)
  - `attendance` (0–100)
  - `study_hours` (0–24)
  - `sleep_hours` (0–24)

### PUT `/students/<id>`
- **Role**: `admin|faculty`
- **Body**: same as create

### DELETE `/students/<id>`
- **Role**: `admin|faculty`

### GET `/students/<id>/profile`
- **Auth required**
- **Query**
  - `limit` (7–365, default 60)
- **Response**
  - `student`
  - `xai` (explainable prediction)
  - `risk` `{ score, level }`
  - `metrics_history[]`
  - `attendance_history[]`

## Attendance

### GET `/attendance`
- **Auth required**
- **Query**
  - `student_id` (optional)

### POST `/attendance`
- **Role**: `admin|faculty`
- **Body**
  - `student_id` (int)
  - `date` (string, e.g. `2026-05-06`)
  - `status` (`present|absent`)
  - `notes` (string, optional)

## Dashboard / Analytics / Insights

### GET `/dashboard`
- **Auth required**
- Cached (short TTL)

### GET `/analytics`
- **Auth required**
- **Query**
  - `days` (7–180, default 30)
- Cached (short TTL)

### GET `/insights`
- **Auth required**
- **Query**
  - `search`, `attendance`, `risk`, `limit`
- Cached (short TTL)

## Prediction

### POST `/predict`
- **Auth required**
- **Body**: `study_hours`, `sleep_hours`, `attendance`

### POST `/predict/explain`
- **Auth required**
- **Body**: `study_hours`, `sleep_hours`, `attendance`
- **Response**
  - `baseline_marks`
  - `predicted_marks`
  - `impacts[]` (per-feature mark deltas)
  - `risk`

## Reports (Exports)

### GET `/reports/students.csv`
### GET `/reports/students.xlsx`
### GET `/reports/students.pdf`
- **Role**: `admin|faculty`
- **Query**
  - `search`, `attendance`, `risk`

## Reliability / Ops

### GET `/monitoring/stats`
- **Role**: `admin`
- Returns request counts, error counts, active users, running jobs, recent errors.

### POST `/jobs/retrain-model`
- **Role**: `admin|faculty`
- Starts background retraining (demo task).

### POST `/jobs/full-report`
- **Role**: `admin|faculty`
- Starts background full system report generation.

### GET `/jobs/<job_id>`
- **Role**: `admin|faculty`
- Poll background job status/result.

### POST `/backup/create`
- **Role**: `admin`
- Creates DB backup snapshot file.

### GET `/backup/list`
- **Role**: `admin`
- Lists available backups.

### GET `/backup/download/<filename>`
- **Role**: `admin`
- Downloads a backup file.

## Master data (ERP / LMS foundation)

**Read** (`GET`): any authenticated role (student, faculty, parent, admin).

**Write**: `admin` for institutions/departments/semesters/subjects; `faculty` or `admin` for study materials (`POST`/`DELETE`).

Stores institutions, departments (with stream), semesters, subjects, and link-only study materials (`study_materials` table).

### Study materials GET

- `GET /master/materials?subject_id=<id>` — materials for one subject (with subject/department names)
- `GET /master/materials?limit=50` — latest materials across all subjects (faculty browse)

## Academic calendar (unified)

- `GET /academic/calendar?days=30` — merges calendar events, assignment due dates, exam schedule, and student meetings
- `POST /academic/calendar` — `faculty` or `admin`; body: `title`, `event_type` (`class|exam|assignment|holiday|meeting|other`), `starts_at`, optional `ends_at`, `description`, `subject_id`, `target_role`

## Curriculum (master catalog)

- `GET /academic/curriculum?semester=1` — subjects from `subjects_master` (fallback: legacy `curriculum_subjects`); includes per-student grades when role is `student`
- Response includes `gpa`: `{ cgpa, credits_earned, backlogs }`

## GPA / credits

- `GET /academic/gpa/me` — student: CGPA, credits earned, backlogs, grade list, predicted CGPA
- `GET /academic/gpa/students/<student_id>` — faculty/admin view
- `POST /academic/gpa/grades` — faculty/admin upsert grade: `student_id`, `subject_id`, `grade_points` (0–10), `status` (`passed|failed|backlog|pending`), optional `marks`, `credits`, `remarks`

## OBE

- `GET /academic/obe?master_subject_id=<id>` — outcomes for a master-catalog subject
- `GET /academic/obe?subject_id=<id>` — legacy curriculum subject id

### Institutions

- `GET /master/institutions` — `{ items, count }`
- `POST /master/institutions` — body: `name`, `type` (optional, default `college`)
- `PUT /master/institutions/<id>` — body: `name`, `type`
- `DELETE /master/institutions/<id>` — blocked if departments or semesters exist

### Departments

- `GET /master/departments` — query: `institution_id`, optional `stream` (`engineering|medical|commerce|general`)
- `POST /master/departments` — body: `institution_id`, `name`, `stream`
- `PUT /master/departments/<id>` — body: `institution_id`, `name`, `stream`
- `DELETE /master/departments/<id>` — blocked if subjects exist

### Semesters

- `GET /master/semesters` — query: `institution_id` (required)
- `POST /master/semesters` — body: `institution_id`, `name`, `order_index`
- `PUT /master/semesters/<id>` — body: `institution_id`, `name`, `order_index`
- `DELETE /master/semesters/<id>` — clears `semester_id` on linked subjects, then deletes semester

### Subjects

- `GET /master/subjects` — query: optional `department_id`, `semester_id`
- `POST /master/subjects` — body: `department_id`, `name`, optional `code`, optional `semester_id`
- `PUT /master/subjects/<id>` — body: `department_id`, `name`, optional `code`; optional `semester_id` (omit to keep, send `null`/0 to clear)
- `DELETE /master/subjects/<id>` — deletes linked materials first

### Study materials (links only)

- `GET /master/materials` — query: `subject_id` (required)
- `POST /master/materials` — body: `subject_id`, `title`, `material_type` (`note|pdf|ppt|video|link`), `url`, optional `description`
- `DELETE /master/materials/<id>`

