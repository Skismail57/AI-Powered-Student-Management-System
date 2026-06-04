
# AI-Powered Student Management System

A full-stack student management platform built for educational institutions with role-based access for `admin`, `faculty`, `student`, and `parent` users.

It includes dashboards, attendance tracking, curriculum management, GPA & predictive analytics, notifications, reports, and mobile-friendly login support.

---

## Key Features

- Role-based authentication and JWT security
- Admin, faculty, student, and parent portals
- Student attendance tracking and history
- Curriculum and OBE support with departments, semesters, and subjects
- GPA tracking, grade entry, and performance prediction
- Parent alerts, daily summaries, and notification center
- Export reports as CSV, XLSX, and PDF
- Dashboard analytics, monitoring, and backup management
- Responsive and mobile-friendly login interface

---

## Tech Stack

- Backend: `Python`, `Flask`, `Flask-CORS`, `Flask-SocketIO`
- Database: `SQLite` (local demo) / compatible with MySQL via config
- Frontend: `HTML`, `CSS`, `JavaScript`
- Reporting: `openpyxl`, `reportlab`
- Security: `werkzeug.security` password hashing
- Auth: JSON Web Tokens (JWT)

---

## Repository Structure

- `backend/`
  - `app.py` — main Flask backend and REST API server
  - `db.py` — database connection helper
  - `setup_db.py` — local SQLite database schema setup
  - `setup_admin.py` — create the default admin user
  - `seed_data.py` — seed demo users and academic data
  - `API_DOCS.md` — backend API reference
  - `routes/` — modular API route blueprints
  - `tests/` — backend tests
- `frontend/`
  - `login.html` — login and registration UI
  - `admin.html`, `faculty.html`, `student.html`, `parent.html` — portals
  - `css/style.css` — shared frontend styles
  - `js/` — client-side application logic
- `database/`
  - `schema.sql` — SQL schema for relational database setup
- Root files
  - `README.md` — project documentation
  - `requirements.txt` — Python dependencies

---

## Getting Started

### Prerequisites

- Python 3.8 or higher
- `pip` package manager
- Optional: `MySQL` if you want to run with MySQL instead of SQLite

### Install dependencies

```bash
cd backend
python -m pip install -r requirements.txt
```

### Initialize the database

For a quick local demo:

```bash
cd backend
python setup_db.py
python setup_admin.py
python seed_data.py
```

> `setup_db.py` creates the local SQLite database and required tables.
> `setup_admin.py` creates the default admin account.
> `seed_data.py` inserts demo users, students, parents, faculty, departments, subjects, and sample records.

### Run the backend server

```bash
cd backend
python app.py
```

The backend runs at:

- `http://127.0.0.1:5000`

### Open the frontend

Open `frontend/login.html` in your browser, or serve the `frontend/` directory with a static file server.

---

## Demo Credentials

- **Admin**
  - Mobile: `1234567890`
  - Password: `admin123`
- **Faculty**
  - `Dr. Ramesh Babu` — Mobile: `9876543210`, Password: `password123`
  - `Dr. Sneha Kulkarni` — Mobile: `9876543211`, Password: `password123`
  - `Prof. Ananth Kumar` — Mobile: `9876543212`, Password: `password123`
- **Student**
  - `Demo CSE Student` — Mobile: `9999999999`, Password: `password123`
  - `Demo Medical Student` — Mobile: `8888888888`, Password: `password123`
- **Parent**
  - `Demo Parent` — Mobile: `7777777777`, Password: `parent123`

---

## API Documentation

See `backend/API_DOCS.md` for full API details, including authentication, student management, attendance, dashboard analytics, report exports, backup endpoints, and master data management.

---

## Notes

- This project is intended as a demo and learning application.
- The default local setup uses SQLite, but the architecture supports MySQL via configuration.
- Passwords are hashed using `werkzeug.security` before storage.

---

## License

This project is released under the [MIT License](https://opensource.org/licenses/MIT).

If you want to use a different license, update this section accordingly.
