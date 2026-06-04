# AI-Powered Student Management System

[![Python](https://img.shields.io/badge/Python-3.8%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-Backend-000000?logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![SQLite](https://img.shields.io/badge/Database-SQLite-003B57?logo=sqlite&logoColor=white)](https://www.sqlite.org/)
[![JWT](https://img.shields.io/badge/Auth-JWT-D63AFF)](https://jwt.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/Skismail57/AI-Powered-Student-Management-System?style=social)](https://github.com/Skismail57/AI-Powered-Student-Management-System)

<p align="center">
  <img src="Github%20images/Github%20Cover%20Image.png" alt="AI-Powered Student Management System cover image" width="100%" />
</p>

A full-stack academic management platform for educational institutions with dedicated portals for `admin`, `faculty`, `student`, and `parent` users. The system combines student administration, attendance, curriculum workflows, GPA tracking, analytics, notifications, reports, and AI-assisted academic insights in one project.

## Overview

This project is designed as a practical educational ERP-style system with modern full-stack features. It helps institutions manage academic data while giving each user role a focused dashboard and workflow.

### Core Highlights

- Role-based authentication with secure password hashing and JWT tokens
- Admin, faculty, student, and parent portals with tailored navigation
- Student attendance management, history tracking, and alerts
- Curriculum, OBE, departments, semesters, and subject management
- GPA, grade entry, academic audit, and performance prediction
- Notifications, messaging, parent summaries, and engagement tools
- CSV, XLSX, and PDF report exports
- Monitoring, background jobs, and backup management
- Responsive UI with mobile-friendly login and dashboard screens

## Feature Breakdown

### User Roles

- **Admin**: manages institutions, departments, subjects, users, reports, monitoring, and backups
- **Faculty**: manages students, attendance, grades, assignments, class analytics, and teaching tools
- **Student**: views dashboard metrics, curriculum, study materials, progress, quizzes, and recommendations
- **Parent**: tracks attendance, student performance, notifications, and daily academic summaries

### Academic Modules

- Student profile and attendance tracking
- Curriculum and OBE support
- GPA, credits, grades, and academic audit
- Timetable and academic calendar utilities
- Assignment, quiz, and learning progress tools

### Smart and Analytics Features

- Predictive marks estimation
- Explainable academic insights
- Risk-based student monitoring
- Dashboard analytics and recommendations
- Global search and engagement features

## Screenshots

### Entry and Access

<p align="center">
  <img src="Github%20images/Screenshot%202026-06-03%20161649.png" alt="Login screen" width="49%" />
  <img src="Github%20images/Screenshot%202026-06-03%20162556.png" alt="Portal selection overview" width="49%" />
</p>

### Admin Portal

<p align="center">
  <img src="Github%20images/Screenshot%202026-06-03%20161141.png" alt="Admin dashboard overview" width="49%" />
  <img src="Github%20images/Screenshot%202026-06-03%20161243.png" alt="Admin departments management" width="49%" />
</p>

<p align="center">
  <img src="Github%20images/Screenshot%202026-06-03%20161256.png" alt="Admin subject catalog" width="49%" />
  <img src="Github%20images/Screenshot%202026-06-03%20161326.png" alt="Admin students management" width="49%" />
</p>

<p align="center">
  <img src="Github%20images/Screenshot%202026-06-03%20161314.png" alt="Admin faculty management" width="49%" />
  <img src="Github%20images/Screenshot%202026-06-03%20161342.png" alt="Admin reports and analytics" width="49%" />
</p>

### Faculty Portal

<p align="center">
  <img src="Github%20images/Screenshot%202026-06-03%20162100.png" alt="Faculty portal overview" width="49%" />
  <img src="Github%20images/Screenshot%202026-06-03%20162111.png" alt="Faculty attendance management" width="49%" />
</p>

<p align="center">
  <img src="Github%20images/Screenshot%202026-06-03%20162120.png" alt="Faculty grading portal" width="49%" />
  <img src="Github%20images/Screenshot%202026-06-03%20162130.png" alt="Faculty research section" width="49%" />
</p>

### Student Portal

<p align="center">
  <img src="Github%20images/Screenshot%202026-06-03%20182911.png" alt="Student dashboard" width="49%" />
  <img src="Github%20images/Screenshot%202026-06-03%20182923.png" alt="Student risk and attendance insight" width="49%" />
</p>

<p align="center">
  <img src="Github%20images/Screenshot%202026-06-03%20182935.png" alt="Student curriculum and OBE" width="49%" />
  <img src="Github%20images/Screenshot%202026-06-03%20182946.png" alt="Student timetable" width="49%" />
</p>

<p align="center">
  <img src="Github%20images/Screenshot%202026-06-03%20183055.png" alt="Student faculty profiles" width="49%" />
  <img src="Github%20images/Screenshot%202026-06-03%20183159.png" alt="Student AI campus advisor" width="49%" />
</p>

### Parent Portal

<p align="center">
  <img src="Github%20images/Screenshot%202026-06-03%20183956.png" alt="Parent portal dashboard" width="100%" />
</p>

## Tech Stack

### Backend

- `Python`
- `Flask`
- `Flask-CORS`
- `Flask-SocketIO`
- `Flask-Mail`
- `PyJWT`
- `Werkzeug`

### Frontend

- `HTML`
- `CSS`
- `JavaScript`

### Data and Reporting

- `SQLite` for local/demo use
- MySQL-compatible configuration support
- `openpyxl` for spreadsheet export
- `reportlab` for PDF report generation

### Testing and ML Utilities

- `pytest`
- `numpy`
- `scikit-learn`

## Project Structure Overview

```text
AI-Powered-Student-Management-System/
|-- backend/
|   |-- app.py                  # Main Flask application and API entry point
|   |-- db.py                   # Database connection utilities
|   |-- config.py               # Environment and app configuration
|   |-- setup_db.py             # SQLite schema/bootstrap setup
|   |-- setup_admin.py          # Default admin creation
|   |-- seed_data.py            # Demo data seeding
|   |-- API_DOCS.md             # API reference
|   |-- routes/                 # Modular route blueprints
|   |-- tests/                  # Backend tests
|   `-- model_*.py              # Prediction and domain-specific logic
|-- frontend/
|   |-- login.html              # Login and registration interface
|   |-- admin.html              # Admin portal
|   |-- faculty.html            # Faculty portal
|   |-- student.html            # Student portal
|   |-- parent.html             # Parent portal
|   |-- audit.html              # Audit and tracking page
|   |-- engagement.html         # Engagement analytics UI
|   |-- search.html             # Global search interface
|   |-- notifications.html      # Notifications center
|   |-- messages.html           # Messaging UI
|   |-- css/                    # Shared styles
|   |-- js/                     # Client-side logic
|   `-- uploads/                # Frontend-uploaded assets
|-- database/
|   `-- schema.sql              # Relational schema definition
|-- Github images/              # README screenshots and gallery assets
|-- README.md                   # Project documentation
|-- LICENSE                     # MIT license
|-- CONTRIBUTING.md             # Contribution notes
`-- pytest.ini                  # Test configuration
```

## Architecture Diagram

```text
+-------------------+        +---------------------+        +----------------------+
|    Frontend UI    | <----> |   Flask Backend     | <----> |      SQLite DB       |
| HTML / CSS / JS   |        | Auth + APIs + Logic |        | Student / Academic   |
+-------------------+        +---------------------+        +----------------------+
         |                               |                              |
         |                               |                              |
         v                               v                              v
+-------------------+        +---------------------+        +----------------------+
| Role-Based Pages  |        | AI / Analytics      |        | Reports / Exports    |
| Admin / Faculty   |        | Prediction / Risk   |        | CSV / XLSX / PDF     |
| Student / Parent  |        | Monitoring / Alerts |        | Backup / Audit Logs  |
+-------------------+        +---------------------+        +----------------------+
```

The architecture follows a simple full-stack pattern where the frontend interfaces communicate with Flask APIs, the backend handles authentication and business logic, and the database stores academic, user, and reporting data.

## Key Modules

- **Authentication Module**: login, registration, JWT authentication, role-based authorization, and token refresh
- **Admin Module**: dashboard, institutions, departments, subjects, faculty, students, reports, and system monitoring
- **Faculty Module**: attendance, grading, research tracking, class tools, and faculty-focused workflows
- **Student Module**: dashboard, curriculum, timetable, study materials, quizzes, AI support, and learning progress
- **Parent Module**: student monitoring, attendance trends, notifications, and performance summary view
- **Academic Module**: curriculum, OBE, GPA, credits, grades, audit, and academic calendar management
- **Analytics Module**: student insights, risk detection, prediction, explainable AI, and dashboard summaries
- **Communication Module**: announcements, notifications, messages, alerts, and engagement features
- **Reporting Module**: CSV, XLSX, PDF export, stats, logs, and operational reporting
- **System Utilities**: backups, audit logs, background jobs, and configuration support

## Getting Started

### Prerequisites

- Python `3.8+`
- `pip`
- Optional `MySQL` if you want to run beyond the local SQLite setup

### Installation

```bash
git clone https://github.com/Skismail57/AI-Powered-Student-Management-System.git
cd AI-Powered-Student-Management-System/backend
python -m pip install -r requirements.txt
```

### Initialize the Database

For a quick local demo:

```bash
python setup_db.py
python setup_admin.py
python seed_data.py
```

What these scripts do:

- `setup_db.py` creates the local SQLite database and required tables
- `setup_admin.py` creates the default admin account
- `seed_data.py` inserts demo users, students, faculty, parents, departments, subjects, and sample academic records

### Run the Backend

```bash
python app.py
```

Backend URL:

- `http://127.0.0.1:5000`

### Open the Frontend

Open `frontend/login.html` in your browser, or serve the `frontend/` directory with any static file server.

## Demo Credentials

| Role | User | Mobile | Password |
|------|------|--------|----------|
| Admin | Default Admin | `1234567890` | `admin123` |
| Faculty | Dr. Ramesh Babu | `9876543210` | `password123` |
| Faculty | Dr. Sneha Kulkarni | `9876543211` | `password123` |
| Faculty | Prof. Ananth Kumar | `9876543212` | `password123` |
| Student | Demo CSE Student | `9999999999` | `password123` |
| Student | Demo Medical Student | `8888888888` | `password123` |
| Parent | Demo Parent | `7777777777` | `parent123` |

## API Documentation

Full API details are available in `backend/API_DOCS.md`, including:

- Authentication and token refresh
- Student and attendance management
- Dashboard analytics and reporting
- Prediction and explainable AI endpoints
- GPA, curriculum, and master data endpoints
- Monitoring, jobs, and backup operations

## Advantages of the Project

- Combines student management, analytics, AI, and reporting in one integrated platform
- Supports multiple user roles with clearly separated workflows and dashboards
- Covers practical academic use cases instead of only basic CRUD features
- Includes export, monitoring, backup, and operational capabilities for a more complete system
- Demonstrates full-stack development using frontend, backend, database, and API integration
- Useful for portfolio presentation, final-year academic submission, and recruiter review

## Future Enhancements

- Add Docker support for easier local setup and deployment
- Deploy frontend and backend to cloud hosting platforms
- Add CI/CD pipelines for automated testing and release workflows
- Improve responsive design and mobile optimization across all portals
- Add email and SMS notification integration
- Introduce real-time dashboards and websocket-driven updates across more modules
- Expand AI models for smarter recommendation, prediction, and intervention support
- Add database migrations and stronger production-ready configuration management
- Increase test coverage with unit, API, and end-to-end test suites
- Add role-based admin controls for more granular permissions

## Notes

- This project is intended as a demo and learning application
- The default local setup uses SQLite, but the architecture can be adapted for MySQL
- Passwords are hashed before storage using `werkzeug.security`

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.
