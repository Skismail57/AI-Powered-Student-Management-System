
from flask import Flask, request, jsonify, send_from_directory, send_file
from flask_cors import CORS
from flask_socketio import SocketIO, emit
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import jwt
from datetime import datetime, timedelta, timezone
import os
import io
import csv
import json
import time
import logging
import shutil
import threading
import uuid
from typing import Optional, Tuple, List, Any, Dict
from model import predict_marks
from routes.curriculum import curriculum_bp
from routes.gpa import gpa_bp
from routes.obe import obe_bp
from routes.timetable import timetable_bp
from routes.topic_recommend import topic_recommend_bp
from routes.faculty_research import faculty_research_bp
from routes.faculty_performance import faculty_perf_bp
from routes.ai_assistant import ai_assistant_bp
from routes.engagement import engagement_bp
from db import get_db_connection, DB_PATH
from config import Config

from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle


app = Flask(__name__)
app.config.from_object(Config)

CORS(app, resources={r"/*": {"origins": "*"}})
socketio = SocketIO(app, cors_allowed_origins="*")

# Register Curriculum Management API
app.register_blueprint(curriculum_bp, url_prefix="/api")
app.register_blueprint(gpa_bp, url_prefix="/api")
app.register_blueprint(obe_bp, url_prefix="/api")
app.register_blueprint(timetable_bp, url_prefix="/api")
app.register_blueprint(topic_recommend_bp, url_prefix="/api")
app.register_blueprint(faculty_research_bp, url_prefix="/api")
app.register_blueprint(faculty_perf_bp, url_prefix="/api")
app.register_blueprint(ai_assistant_bp, url_prefix="/api")
app.register_blueprint(engagement_bp, url_prefix="/api")

UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'frontend', 'uploads')
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
BACKEND_DIR = os.path.dirname(__file__)
ASSIGNMENT_UPLOAD_DIR = os.path.join(BACKEND_DIR, "uploads", "assignments")
os.makedirs(ASSIGNMENT_UPLOAD_DIR, exist_ok=True)

# Simple in-memory TTL cache + rate limiter (good enough for single-instance dev/demo).
_CACHE: Dict[str, Dict[str, Any]] = {}
_RATE: Dict[str, List[float]] = {}
_ACTIVE_USERS: Dict[int, float] = {}
_JOBS: Dict[str, Dict[str, Any]] = {}
_METRICS: Dict[str, Any] = {
    "started_at": time.time(),
    "total_requests": 0,
    "error_requests": 0,
    "last_errors": [],
}

BACKUP_DIR = os.path.join(os.path.dirname(__file__), "backups")
os.makedirs(BACKUP_DIR, exist_ok=True)

logging.basicConfig(
    filename=os.path.join(os.path.dirname(__file__), "app.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("student-system")

def _cache_get(key: str) -> Optional[Any]:
    item = _CACHE.get(key)
    if not item:
        return None
    if item["expires_at"] < time.time():
        _CACHE.pop(key, None)
        return None
    return item["value"]

def _cache_set(key: str, value: Any, ttl_seconds: int = 20) -> None:
    _CACHE[key] = {"value": value, "expires_at": time.time() + ttl_seconds}

def _cache_invalidate(prefix: str) -> None:
    for k in list(_CACHE.keys()):
        if k.startswith(prefix):
            _CACHE.pop(k, None)

def _client_key() -> str:
    # Best-effort client identifier (behind proxies this can be wrong; fine for demo).
    return request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()

def _rate_limit(action: str, limit: int, window_seconds: int) -> Optional[Tuple[Dict[str, Any], int]]:
    if app.config.get('TESTING'):
        return None
    now = time.time()
    key = f"{action}:{_client_key()}"
    bucket = _RATE.get(key, [])
    bucket = [t for t in bucket if now - t < window_seconds]
    if len(bucket) >= limit:
        retry_after = max(1, int(window_seconds - (now - bucket[0])))
        _RATE[key] = bucket
        return ({"message": "Too many requests. Please slow down.", "retry_after_seconds": retry_after}, 429)
    bucket.append(now)
    _RATE[key] = bucket
    return None

def _record_user_activity(user_id: Optional[int]) -> None:
    if not user_id:
        return
    _ACTIVE_USERS[int(user_id)] = time.time()

def _active_users_count(window_seconds: int = 900) -> int:
    now = time.time()
    for uid, ts in list(_ACTIVE_USERS.items()):
        if now - ts > window_seconds:
            _ACTIVE_USERS.pop(uid, None)
    return len(_ACTIVE_USERS)

def _run_background_job(job_id: str, job_type: str, func, *args, **kwargs) -> None:
    _JOBS[job_id] = {
        "id": job_id,
        "type": job_type,
        "status": "queued",
        "created_at": datetime.now().isoformat(),
    }

    def _target():
        _JOBS[job_id]["status"] = "running"
        _JOBS[job_id]["started_at"] = datetime.now().isoformat()
        try:
            result = func(*args, **kwargs)
            _JOBS[job_id]["status"] = "completed"
            _JOBS[job_id]["result"] = result
        except Exception as e:
            _JOBS[job_id]["status"] = "failed"
            _JOBS[job_id]["error"] = str(e)
            logger.exception("Background job failed: %s", job_id)
        finally:
            _JOBS[job_id]["finished_at"] = datetime.now().isoformat()

    threading.Thread(target=_target, daemon=True).start()

def token_required(f):
    def decorated(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            token = request.headers['Authorization'].split(" ")[1]
        
        if not token:
            return jsonify({'message': 'Token is missing!'}), 401
        
        try:
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
            current_user = data
            request._current_user = current_user
            _record_user_activity(_parse_int(current_user.get("id"), 0))
        except:
            return jsonify({'message': 'Token is invalid!'}), 401
        
        return f(current_user, *args, **kwargs)
    
    decorated.__name__ = f.__name__
    return decorated

@app.before_request
def _before_request_metrics():
    _METRICS["total_requests"] += 1
    request._start_time = time.time()

@app.after_request
def _after_request_metrics(response):
    duration_ms = int((time.time() - getattr(request, "_start_time", time.time())) * 1000)
    if response.status_code >= 400:
        _METRICS["error_requests"] += 1
        if len(_METRICS["last_errors"]) > 50:
            _METRICS["last_errors"] = _METRICS["last_errors"][-50:]
        _METRICS["last_errors"].append(
            {
                "path": request.path,
                "method": request.method,
                "status": response.status_code,
                "time": datetime.now().isoformat(),
            }
        )
    logger.info(
        "API %s %s status=%s duration_ms=%s ip=%s",
        request.method,
        request.path,
        response.status_code,
        duration_ms,
        _client_key(),
    )
    try:
        if request.method in ["POST", "PUT", "DELETE"]:
            actor = getattr(request, "_current_user", {}) or {}
            _insert_audit_log(
                actor_role=str(actor.get("role") or "anonymous"),
                actor_id=_parse_int(actor.get("id"), 0) or None,
                action=f"{request.method} {request.path}",
                method=request.method,
                path=request.path,
                status_code=int(response.status_code),
                meta={"ip": _client_key()},
            )
    except Exception:
        pass
    return response

def _insert_audit_log(
    *,
    actor_role: str,
    actor_id: Optional[int],
    action: str,
    method: str,
    path: str,
    status_code: int,
    meta: Optional[Dict[str, Any]] = None,
) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO audit_logs (actor_role, actor_id, action, method, path, status_code, meta_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            actor_role,
            actor_id,
            action,
            method,
            path,
            _parse_int(status_code, 0),
            json.dumps(meta or {}),
        ),
    )
    # SEED INITIAL PHASE 1 DATA
    cursor.execute("SELECT COUNT(*) FROM curriculum_subjects")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO curriculum_subjects (subject_name, semester, credits) VALUES ('Mathematics IV', 4, 4)")
        cursor.execute("INSERT INTO curriculum_subjects (subject_name, semester, credits) VALUES ('Operating Systems', 4, 4)")
        cursor.execute("INSERT INTO curriculum_subjects (subject_name, semester, credits) VALUES ('Database Systems', 4, 3)")
        
        # OBE Data
        cursor.execute("INSERT INTO obe_outcomes (subject_id, outcome_type, outcome_code, description) VALUES (1, 'CO', 'CO1', 'Understand advanced calculus principles')")
        cursor.execute("INSERT INTO obe_outcomes (subject_id, outcome_type, outcome_code, description) VALUES (2, 'CO', 'CO1', 'Analyze process scheduling algorithms')")
        
        # Timetable Data
        cursor.execute("INSERT INTO timetables (dept_id, semester, day_of_week, start_time, end_time, subject_id, room_number) VALUES (1, 4, 'Monday', '09:00', '10:30', 1, 'LHC-101')")
        cursor.execute("INSERT INTO timetables (dept_id, semester, day_of_week, start_time, end_time, subject_id, room_number) VALUES (1, 4, 'Monday', '10:45', '12:15', 2, 'LHC-102')")
        
        # Social Feed
        cursor.execute("INSERT INTO campus_social_feed (author_id, author_role, content) VALUES (1, 'faculty', 'Welcome to the new semester! Focus on your OBE goals.')")

        # Notices
        cursor.execute("INSERT INTO smart_notices (title, content, target_role) VALUES ('Semester Exam Schedule Out', 'Please check the curriculum section for the detailed timetable of upcoming mid-sem exams.', 'student')")
        cursor.execute("INSERT INTO smart_notices (title, content, target_role) VALUES ('Campus Maintenance Drive', 'The main library will be closed this Sunday for scheduled maintenance.', 'all')")

    conn.commit()
    cursor.close()
    conn.close()

def row_to_dict(row):
    if row is None:
        return None
    d = dict(row)
    # Mock CDN integration: prefix file_path or submission_url with CDN domain
    cdn_prefix = "https://cdn.smartcampus.edu/files/"
    for key in ['file_path', 'submission_url', 'video_url', 'stream_url', 'audio_url']:
        if key in d and d[key] and not d[key].startswith('http'):
            d[key] = cdn_prefix + d[key]
    return d

def _parse_float(value, default: float = 0.0) -> float:
    try:
        if value is None or value == '':
            return default
        return float(value)
    except (ValueError, TypeError):
        return default

def _parse_int(value, default: int = 0) -> int:
    try:
        if value is None or value == '':
            return default
        return int(float(value))
    except (ValueError, TypeError):
        return default

def _build_students_where_clause(
    search: str,
    attendance_bucket: str,
    risk: str,
    performance: str = "all",
) -> Tuple[str, List[Any]]:
    clauses: List[str] = []
    params: List[Any] = []

    if search:
        clauses.append("name LIKE ?")
        params.append(f"%{search}%")

    if attendance_bucket == "low":
        clauses.append("attendance < ?")
        params.append(60)
    elif attendance_bucket == "medium":
        clauses.append("attendance >= ? AND attendance <= ?")
        params.extend([60, 75])
    elif attendance_bucket == "high":
        clauses.append("attendance > ?")
        params.append(75)

    # Risk is derived from fields; keep same logic as frontend.
    if risk == "atrisk":
        clauses.append("(attendance < ? OR study_hours < ? OR sleep_hours < ?)")
        params.extend([60, 2, 5])
    elif risk == "warning":
        clauses.append("(attendance >= ? AND attendance < ? AND study_hours >= ? AND sleep_hours >= ?)")
        params.extend([60, 75, 2, 5])
    elif risk == "good":
        clauses.append("(attendance >= ? AND study_hours >= ? AND sleep_hours >= ?)")
        params.extend([60, 2, 5])

    if performance == "high":
        clauses.append("((attendance * 0.5) + (study_hours * 10) + (sleep_hours * 2)) >= ?")
        params.append(80)
    elif performance == "weak":
        clauses.append("((attendance * 0.5) + (study_hours * 10) + (sleep_hours * 2)) < ?")
        params.append(60)

    if not clauses:
        return "", []
    return " WHERE " + " AND ".join(clauses), params

def _fetch_students_for_reporting(
    *,
    search: str,
    attendance_bucket: str,
    risk: str,
    performance: str = "all",
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    where_sql, params = _build_students_where_clause(search, attendance_bucket, risk, performance)
    sql = "SELECT id, name, attendance, study_hours, sleep_hours, created_at FROM students" + where_sql + " ORDER BY id ASC"
    if limit is not None and limit > 0:
        sql += " LIMIT ?"
        params.append(limit)
    cursor.execute(sql, params)
    rows = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return rows

def _ensure_history_tables() -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS student_metrics_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            attendance INTEGER DEFAULT 0,
            study_hours REAL DEFAULT 0,
            sleep_hours REAL DEFAULT 0,
            predicted_marks REAL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS student_user_links (
            user_id INTEGER PRIMARY KEY,
            student_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            level TEXT NOT NULL CHECK(level IN ('low','medium','high')),
            score INTEGER NOT NULL,
            predicted_marks REAL DEFAULT 0,
            reason TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            resolved_at TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            due_date DATE,
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS assignment_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            assignment_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('pending','submitted','completed')),
            notes TEXT DEFAULT '',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(assignment_id, student_id),
            FOREIGN KEY (assignment_id) REFERENCES assignments(id) ON DELETE CASCADE,
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
        )
        """
    )
    # Backward-compatible migrations for richer assignment lifecycle.
    try:
        cursor.execute("ALTER TABLE assignment_submissions ADD COLUMN file_path TEXT DEFAULT ''")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE assignment_submissions ADD COLUMN file_name TEXT DEFAULT ''")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE assignment_submissions ADD COLUMN grade_score REAL")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE assignment_submissions ADD COLUMN grade_feedback TEXT DEFAULT ''")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE assignment_submissions ADD COLUMN graded_by INTEGER")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE assignment_submissions ADD COLUMN graded_at TIMESTAMP")
    except Exception:
        pass

    # Backward-compatible migration: add attendance reason column when missing.
    try:
        cursor.execute("ALTER TABLE attendance ADD COLUMN reason TEXT DEFAULT ''")
    except Exception:
        pass

    # Digital Library System
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS library_books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            author TEXT,
            category TEXT,
            isbn TEXT UNIQUE,
            available_copies INTEGER DEFAULT 1,
            pdf_url TEXT,
            thumbnail_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS library_borrows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            borrowed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            due_date TIMESTAMP NOT NULL,
            returned_at TIMESTAMP,
            status TEXT DEFAULT 'borrowed' CHECK(status IN ('borrowed','returned','overdue')),
            FOREIGN KEY (book_id) REFERENCES library_books(id),
            FOREIGN KEY (student_id) REFERENCES students(id)
        )
    """)

    # Placement Portal
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS placement_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT NOT NULL,
            role TEXT NOT NULL,
            description TEXT,
            salary_package TEXT,
            location TEXT,
            deadline DATE,
            requirements TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS placement_applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            status TEXT DEFAULT 'applied' CHECK(status IN ('applied','shortlisted','interview','offered','rejected')),
            resume_url TEXT,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (job_id) REFERENCES placement_jobs(id),
            FOREIGN KEY (student_id) REFERENCES students(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS placement_interviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            application_id INTEGER NOT NULL,
            scheduled_at TIMESTAMP NOT NULL,
            mode TEXT DEFAULT 'online' CHECK(mode IN ('online','offline')),
            meeting_link TEXT DEFAULT '',
            interviewer_name TEXT DEFAULT '',
            status TEXT DEFAULT 'scheduled' CHECK(status IN ('scheduled','completed','cancelled')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (application_id) REFERENCES placement_applications(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS student_certificates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            issuer TEXT NOT NULL,
            category TEXT DEFAULT 'skill',
            issue_date DATE,
            certificate_url TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id)
        )
    """)

    # Campus Management (Hostel & Transport)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS hostel_rooms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            block TEXT NOT NULL,
            room_number TEXT NOT NULL,
            capacity INTEGER,
            occupied INTEGER DEFAULT 0,
            fee_per_sem REAL,
            UNIQUE(block, room_number)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transport_routes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            route_name TEXT NOT NULL,
            bus_number TEXT NOT NULL,
            driver_name TEXT,
            driver_contact TEXT,
            fee_per_sem REAL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS hostel_allocations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            room_id INTEGER NOT NULL,
            status TEXT DEFAULT 'allocated' CHECK(status IN ('allocated','vacated')),
            allocated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            vacated_at TIMESTAMP,
            UNIQUE(student_id, status),
            FOREIGN KEY (student_id) REFERENCES students(id),
            FOREIGN KEY (room_id) REFERENCES hostel_rooms(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transport_allocations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            route_id INTEGER NOT NULL,
            pickup_point TEXT DEFAULT '',
            status TEXT DEFAULT 'registered' CHECK(status IN ('registered','cancelled')),
            registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            cancelled_at TIMESTAMP,
            UNIQUE(student_id, status),
            FOREIGN KEY (student_id) REFERENCES students(id),
            FOREIGN KEY (route_id) REFERENCES transport_routes(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS campus_complaints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            category TEXT NOT NULL CHECK(category IN ('hostel','transport','technical','academic','general')),
            subject TEXT NOT NULL,
            description TEXT NOT NULL,
            status TEXT DEFAULT 'open' CHECK(status IN ('open','in_progress','resolved')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id)
        )
    """)

    # Parent Portal - Phase 4
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS parent_notification_settings (
            parent_id INTEGER PRIMARY KEY,
            email_enabled BOOLEAN DEFAULT 1,
            sms_enabled BOOLEAN DEFAULT 0,
            app_enabled BOOLEAN DEFAULT 1,
            FOREIGN KEY (parent_id) REFERENCES parents(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS parent_daily_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            parent_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            summary_date DATE DEFAULT (date('now')),
            attendance_today TEXT,
            study_minutes_today INTEGER,
            open_alerts_count INTEGER,
            predicted_marks REAL,
            summary_text TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (parent_id) REFERENCES parents(id),
            FOREIGN KEY (student_id) REFERENCES students(id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lesson_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            faculty_id INTEGER NOT NULL,
            subject_id INTEGER NOT NULL,
            topic TEXT NOT NULL,
            week_number INTEGER,
            learning_outcomes TEXT,
            status TEXT DEFAULT 'planned' CHECK(status IN ('planned', 'in_progress', 'completed')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (faculty_id) REFERENCES users(id),
            FOREIGN KEY (subject_id) REFERENCES subjects_master(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS voice_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            faculty_id INTEGER NOT NULL,
            subject_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            audio_url TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (faculty_id) REFERENCES users(id),
            FOREIGN KEY (subject_id) REFERENCES subjects_master(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS topic_analytics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_id INTEGER NOT NULL,
            topic_name TEXT NOT NULL,
            fail_rate REAL DEFAULT 0, -- Percentage of students struggling
            avg_score REAL DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (subject_id) REFERENCES subjects_master(id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS mock_tests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_type TEXT NOT NULL, -- GATE, NEET, UPSC, etc.
            title TEXT NOT NULL,
            total_marks INTEGER,
            duration_mins INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS mock_test_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            test_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            score REAL,
            rank_predicted INTEGER,
            percentile REAL,
            submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (test_id) REFERENCES mock_tests(id),
            FOREIGN KEY (student_id) REFERENCES students(id)
        )
    """)

    # Academic Planner
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS academic_goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            goal_text TEXT NOT NULL,
            target_date DATE,
            status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'completed')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id)
        )
    """)

    # CGPA Predictor (History)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS semester_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            semester_number INTEGER NOT NULL,
            cgpa REAL,
            attendance_pct REAL,
            internal_marks_avg REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id)
        )
    """)

    # Discussion Forum (Replies - adding if missing)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS forum_replies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER NOT NULL,
            author_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (topic_id) REFERENCES forum_topics(id),
            FOREIGN KEY (author_id) REFERENCES users(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS forum_topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            created_by INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (created_by) REFERENCES users(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS forum_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (topic_id) REFERENCES forum_topics(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS faculty_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            designation TEXT,
            department_id INTEGER,
            specialization TEXT,
            bio TEXT,
            image_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (department_id) REFERENCES departments_master(id)
        )
    """)

    try:
        cursor.execute("ALTER TABLE institutions ADD COLUMN image_url TEXT")
    except Exception:
        pass

    try:
        cursor.execute("ALTER TABLE students ADD COLUMN department_id INTEGER REFERENCES departments_master(id)")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE students ADD COLUMN semester_id INTEGER REFERENCES semesters_master(id)")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE students ADD COLUMN mobile TEXT")
    except Exception:
        pass

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS study_time_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            study_minutes INTEGER NOT NULL,
            logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_study_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            exam_date TEXT NOT NULL,
            weak_subjects TEXT NOT NULL,
            available_hours REAL NOT NULL,
            schedule_json TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS learning_resources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT NOT NULL,
            title TEXT NOT NULL,
            resource_type TEXT NOT NULL CHECK(resource_type IN ('note','video','assignment','link')),
            content_url TEXT NOT NULL,
            description TEXT DEFAULT '',
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS student_learning_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            resource_id INTEGER NOT NULL,
            progress_pct REAL NOT NULL DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(student_id, resource_id),
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
            FOREIGN KEY (resource_id) REFERENCES learning_resources(id) ON DELETE CASCADE
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS student_goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL UNIQUE,
            target_cgpa REAL NOT NULL,
            attendance_goal REAL NOT NULL,
            study_hours_goal REAL NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS quizzes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            topic TEXT NOT NULL,
            difficulty TEXT NOT NULL CHECK(difficulty IN ('basic','intermediate','advanced')),
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS quiz_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quiz_id INTEGER NOT NULL,
            question_text TEXT NOT NULL,
            option_a TEXT NOT NULL,
            option_b TEXT NOT NULL,
            option_c TEXT NOT NULL,
            option_d TEXT NOT NULL,
            correct_option TEXT NOT NULL CHECK(correct_option IN ('A','B','C','D')),
            FOREIGN KEY (quiz_id) REFERENCES quizzes(id) ON DELETE CASCADE
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS quiz_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quiz_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            score REAL NOT NULL,
            total_questions INTEGER NOT NULL,
            submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (quiz_id) REFERENCES quizzes(id) ON DELETE CASCADE,
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS faculty_remarks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            faculty_user_id INTEGER,
            remark TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS interventions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            risk_level TEXT NOT NULL CHECK(risk_level IN ('low','medium','high')),
            action_plan TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','in_progress','closed')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS escalation_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            target_role TEXT NOT NULL CHECK(target_role IN ('student','faculty','admin')),
            message TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS parents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            mobile TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            student_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS intelligent_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            recipient_role TEXT NOT NULL CHECK(recipient_role IN ('student','parent','faculty','admin')),
            recipient_id INTEGER,
            category TEXT NOT NULL,
            severity TEXT NOT NULL CHECK(severity IN ('info','medium','high')),
            message TEXT NOT NULL,
            source_key TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            resolved_at TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','in_progress','resolved')),
            severity TEXT NOT NULL DEFAULT 'medium' CHECK(severity IN ('low','medium','high')),
            notes TEXT DEFAULT '',
            actions TEXT DEFAULT '',
            suggestions TEXT DEFAULT '',
            resolution_summary TEXT DEFAULT '',
            created_by INTEGER,
            updated_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            resolved_at TIMESTAMP,
            parent_acknowledged_at TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS meetings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            parent_id INTEGER NOT NULL,
            faculty_user_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            requested_time TEXT NOT NULL,
            scheduled_time TEXT,
            status TEXT NOT NULL DEFAULT 'requested' CHECK(status IN ('requested','approved','rescheduled','completed','rejected','cancelled')),
            parent_note TEXT DEFAULT '',
            faculty_note TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS decision_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action_key TEXT NOT NULL,
            title TEXT NOT NULL,
            details TEXT DEFAULT '',
            completed_by INTEGER NOT NULL,
            completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recipient_role TEXT NOT NULL CHECK(recipient_role IN ('student','faculty','parent','admin')),
            recipient_id INTEGER,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            category TEXT DEFAULT 'general',
            is_read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS parent_daily_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            parent_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            summary_date DATE NOT NULL,
            attendance_today TEXT DEFAULT 'unknown',
            study_minutes_today INTEGER DEFAULT 0,
            open_alerts_count INTEGER DEFAULT 0,
            predicted_marks REAL DEFAULT 0,
            summary_text TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(parent_id, summary_date)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS auto_evaluation_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uploaded_by INTEGER NOT NULL,
            total_rows INTEGER DEFAULT 0,
            weak_students INTEGER DEFAULT 0,
            class_average REAL DEFAULT 0,
            summary_json TEXT DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS class_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            faculty_user_id INTEGER NOT NULL,
            class_name TEXT NOT NULL,
            subject TEXT NOT NULL,
            schedule_time TEXT NOT NULL,
            syllabus_url TEXT DEFAULT '',
            completion_pct REAL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'scheduled' CHECK(status IN ('scheduled','ongoing','completed','cancelled')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_role TEXT NOT NULL CHECK(sender_role IN ('student','faculty','parent','admin')),
            sender_id INTEGER NOT NULL,
            recipient_role TEXT NOT NULL CHECK(recipient_role IN ('student','faculty','parent','admin')),
            recipient_id INTEGER NOT NULL,
            body TEXT NOT NULL,
            is_read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS institutions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            type TEXT DEFAULT 'college',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS departments_master (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            institution_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            stream TEXT NOT NULL CHECK(stream IN ('engineering','medical','commerce','general')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (institution_id) REFERENCES institutions(id) ON DELETE CASCADE
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS semesters_master (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            institution_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            order_index INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (institution_id) REFERENCES institutions(id) ON DELETE CASCADE
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS subjects_master (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            department_id INTEGER NOT NULL,
            semester_id INTEGER,
            code TEXT DEFAULT '',
            name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (department_id) REFERENCES departments_master(id) ON DELETE CASCADE,
            FOREIGN KEY (semester_id) REFERENCES semesters_master(id) ON DELETE SET NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS study_materials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            material_type TEXT NOT NULL CHECK(material_type IN ('note','pdf','ppt','video','link')),
            url TEXT NOT NULL,
            description TEXT DEFAULT '',
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (subject_id) REFERENCES subjects_master(id) ON DELETE CASCADE
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS academic_calendar_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            event_type TEXT NOT NULL CHECK(event_type IN ('class','exam','assignment','holiday','meeting','other')),
            starts_at TEXT NOT NULL,
            ends_at TEXT,
            description TEXT DEFAULT '',
            subject_id INTEGER,
            created_by INTEGER,
            target_role TEXT DEFAULT 'all',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (subject_id) REFERENCES subjects_master(id) ON DELETE SET NULL
        )
        """
    )

    try:
        cursor.execute("ALTER TABLE subjects_master ADD COLUMN credits INTEGER DEFAULT 3")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE subjects_master ADD COLUMN syllabus TEXT DEFAULT ''")
    except Exception:
        pass

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS student_subject_grades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            subject_id INTEGER NOT NULL,
            credits INTEGER NOT NULL DEFAULT 3,
            grade_points REAL,
            marks REAL,
            status TEXT NOT NULL CHECK(status IN ('passed','failed','backlog','pending')) DEFAULT 'pending',
            faculty_user_id INTEGER,
            remarks TEXT DEFAULT '',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(student_id, subject_id),
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
            FOREIGN KEY (subject_id) REFERENCES subjects_master(id) ON DELETE CASCADE
        )
        """
    )

    try:
        cursor.execute(
            "ALTER TABLE obe_outcomes ADD COLUMN master_subject_id INTEGER REFERENCES subjects_master(id)"
        )
    except Exception:
        pass

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor_role TEXT DEFAULT 'anonymous',
            actor_id INTEGER,
            action TEXT NOT NULL,
            method TEXT NOT NULL,
            path TEXT NOT NULL,
            status_code INTEGER NOT NULL,
            meta_json TEXT DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    # Wellness & Counseling
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS wellness_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            log_date DATE NOT NULL,
            sleep_hours REAL,
            stress_level INTEGER CHECK(stress_level BETWEEN 1 AND 10),
            focus_score INTEGER CHECK(focus_score BETWEEN 1 AND 10),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
            UNIQUE(student_id, log_date)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS counseling_appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            counselor_name TEXT NOT NULL,
            appointment_date TIMESTAMP NOT NULL,
            status TEXT DEFAULT 'scheduled' CHECK(status IN ('scheduled','completed','cancelled')),
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
        )
    """)

    # Advanced LMS
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lecture_recordings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            video_url TEXT NOT NULL,
            duration_minutes INTEGER,
            recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (subject_id) REFERENCES subjects_master(id) ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS flashcards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_id INTEGER NOT NULL,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (subject_id) REFERENCES subjects_master(id) ON DELETE CASCADE
        )
    """)

    # Advanced Placement
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            website TEXT,
            industry TEXT,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS mock_interviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            interviewer_name TEXT,
            scheduled_at TIMESTAMP NOT NULL,
            feedback TEXT,
            score INTEGER,
            status TEXT DEFAULT 'scheduled' CHECK(status IN ('scheduled','completed','cancelled')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
        )
    """)

    # Study Groups
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS study_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            subject_id INTEGER,
            created_by INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (subject_id) REFERENCES subjects_master(id) ON DELETE SET NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS study_group_members (
            group_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (group_id, student_id),
            FOREIGN KEY (group_id) REFERENCES study_groups(id) ON DELETE CASCADE,
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
        )
    """)

    # CAFETERIA & HEALTH SYSTEMS
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS parking_slots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slot_number TEXT NOT NULL UNIQUE,
            zone TEXT,
            status TEXT DEFAULT 'available' CHECK(status IN ('available', 'occupied', 'reserved'))
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS vehicle_registrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            vehicle_number TEXT NOT NULL UNIQUE,
            vehicle_type TEXT,
            parking_slot_id INTEGER,
            registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (parking_slot_id) REFERENCES parking_slots(id) ON DELETE SET NULL
        )
    """)

    # Events & Streaming
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS campus_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            event_date TIMESTAMP NOT NULL,
            is_live BOOLEAN DEFAULT 0,
            stream_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Assignment Versioning
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS assignment_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            submission_id INTEGER NOT NULL,
            file_path TEXT NOT NULL,
            version_number INTEGER NOT NULL,
            submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (submission_id) REFERENCES assignment_submissions(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cafeteria_menu (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_name TEXT NOT NULL,
            category TEXT,
            price REAL NOT NULL,
            is_available INTEGER DEFAULT 1,
            image_url TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cafeteria_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            items_json TEXT NOT NULL,
            total_price REAL NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS health_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER UNIQUE NOT NULL,
            blood_group TEXT,
            allergies TEXT,
            medical_history TEXT,
            emergency_contact_name TEXT,
            emergency_contact_phone TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
        )
    """)

    # PHASE 1: CORE ACADEMIC & SMART CAMPUS TABLES
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS curriculum_subjects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_name TEXT NOT NULL,
            semester INTEGER NOT NULL,
            credits INTEGER NOT NULL,
            syllabus_json TEXT DEFAULT '{}',
            dept_id INTEGER,
            is_elective INTEGER DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS obe_outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_id INTEGER NOT NULL,
            outcome_type TEXT CHECK(outcome_type IN ('CO','PO')),
            outcome_code TEXT NOT NULL,
            description TEXT NOT NULL,
            target_attainment REAL DEFAULT 70.0,
            FOREIGN KEY (subject_id) REFERENCES curriculum_subjects(id) ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS timetables (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dept_id INTEGER,
            semester INTEGER,
            day_of_week TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            subject_id INTEGER NOT NULL,
            faculty_id INTEGER,
            room_number TEXT,
            FOREIGN KEY (subject_id) REFERENCES curriculum_subjects(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS student_gamification (
            student_id INTEGER PRIMARY KEY,
            xp INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            badges_json TEXT DEFAULT '[]',
            streak_days INTEGER DEFAULT 0,
            last_activity_date DATE,
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS campus_social_feed (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            author_id INTEGER NOT NULL,
            author_role TEXT NOT NULL,
            content TEXT NOT NULL,
            media_url TEXT,
            likes_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS smart_notices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            target_dept TEXT DEFAULT 'all',
            target_sem TEXT DEFAULT 'all',
            target_role TEXT DEFAULT 'all',
            expires_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS faculty_research (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            faculty_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            publication_type TEXT CHECK(publication_type IN ('Paper','Patent','Journal','Book')),
            journal_name TEXT,
            publication_date DATE,
            url TEXT,
            status TEXT DEFAULT 'published',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (faculty_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS parent_appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            parent_id INTEGER NOT NULL,
            faculty_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            purpose TEXT NOT NULL,
            preferred_date DATE NOT NULL,
            status TEXT DEFAULT 'pending' CHECK(status IN ('pending','approved','completed','cancelled')),
            remarks TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (parent_id) REFERENCES users(id),
            FOREIGN KEY (faculty_id) REFERENCES users(id),
            FOREIGN KEY (student_id) REFERENCES students(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS maintenance_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            category TEXT CHECK(category IN ('Lab','Projector','Electricity','Furniture','Other')),
            location TEXT NOT NULL,
            description TEXT NOT NULL,
            status TEXT DEFAULT 'open' CHECK(status IN ('open','in-progress','resolved')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
        )
    """)

    try:
        cursor.execute("ALTER TABLE placement_jobs ADD COLUMN min_cgpa REAL DEFAULT 6.0")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE placement_jobs ADD COLUMN min_attendance INTEGER DEFAULT 60")
    except Exception:
        pass

    # PHASE 8: ENTERPRISE SECURITY & THEMES
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS login_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            ip_address TEXT,
            user_agent TEXT,
            device_type TEXT,
            location TEXT,
            status TEXT DEFAULT 'success',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    try:
        cursor.execute("ALTER TABLE users ADD COLUMN theme TEXT DEFAULT 'light'")
    except Exception:
        pass

    # PHASE 9: FINANCE & CAMPUS STORE
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS store_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT CHECK(category IN ('Book', 'Merchandise', 'Stationery', 'Other')),
            price REAL NOT NULL,
            stock INTEGER DEFAULT 10,
            image_url TEXT,
            description TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS store_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            items_json TEXT NOT NULL, -- List of {item_id, quantity, price}
            total_amount REAL NOT NULL,
            status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'paid', 'shipped', 'delivered', 'cancelled')),
            payment_method TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS student_wallet (
            student_id INTEGER PRIMARY KEY,
            balance REAL DEFAULT 0.0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS wallet_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            type TEXT CHECK(type IN ('credit', 'debit')),
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
        )
    """)

    # PHASE 10: SMART EXAM SCHEDULER & AUTOMATED WORKFLOW ENGINE
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS exam_schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_id INTEGER NOT NULL,
            exam_date DATE NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            room_number TEXT,
            exam_type TEXT DEFAULT 'Internal' CHECK(exam_type IN ('Internal', 'Semester', 'Lab')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (subject_id) REFERENCES curriculum_subjects(id) ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS workflow_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            trigger_type TEXT NOT NULL CHECK(trigger_type IN ('low_attendance', 'low_marks', 'fee_due')),
            threshold REAL NOT NULL,
            action_json TEXT NOT NULL, -- e.g. {"notify": ["student", "parent"], "alert_level": "high"}
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS workflow_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            action_taken TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (rule_id) REFERENCES workflow_rules(id) ON DELETE CASCADE,
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
        )
    """)

    conn.commit()
    cursor.close()
    conn.close()

def _get_linked_student_id(user_id: int) -> Optional[int]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT student_id FROM student_user_links WHERE user_id=?", (user_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return int(row[0]) if row else None

def _get_parent_student_id(parent_id: int) -> Optional[int]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT student_id FROM parents WHERE id=?", (parent_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return int(row[0]) if row else None

def _get_student_id(user_id: int) -> Optional[int]:
    """Return the student id related to a given user or parent id.

    Tries in order:
    - student_user_links (user -> student)
    - parents table (parent -> student)

    Returns None if no linked student found.
    """
    # try user -> student link (for student users)
    sid = _get_linked_student_id(user_id)
    if sid:
        return sid

    # try parent -> student link
    sid = _get_parent_student_id(user_id)
    if sid:
        return sid

    return None

def _create_notification(
    *,
    recipient_role: str,
    recipient_id: Optional[int],
    title: str,
    message: str,
    category: str = "general",
) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO notifications (recipient_role, recipient_id, title, message, category, is_read)
        VALUES (?, ?, ?, ?, ?, 0)
        """,
        (recipient_role, recipient_id, title, message, category),
    )
    nid = cursor.lastrowid
    conn.commit()
    cursor.close()
    conn.close()
    socketio.emit("notification_push", {
        "id": nid,
        "recipient_role": recipient_role,
        "recipient_id": recipient_id,
        "title": title,
        "message": message,
        "category": category,
    })

def _notify_student_and_parents(student_id: int, title: str, message: str, category: str = "general") -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM student_user_links WHERE student_id=?", (student_id,))
    link = cursor.fetchone()
    student_user_id = _parse_int(link[0], 0) if link else 0
    if student_user_id > 0:
        _create_notification(
            recipient_role="student",
            recipient_id=student_user_id,
            title=title,
            message=message,
            category=category,
        )
    cursor.execute("SELECT id FROM parents WHERE student_id=?", (student_id,))
    parents = cursor.fetchall() or []
    cursor.close()
    conn.close()
    for p in parents:
        pid = _parse_int(p[0], 0)
        if pid > 0:
            _create_notification(
                recipient_role="parent",
                recipient_id=pid,
                title=title,
                message=message,
                category=category,
            )

def _upsert_parent_daily_summary(parent_id: int, student_id: int) -> Dict[str, Any]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT attendance, study_hours, sleep_hours FROM students WHERE id=?", (student_id,))
    s = row_to_dict(cursor.fetchone()) or {}
    attendance = _parse_float(s.get("attendance"), 0.0)
    study_hours = _parse_float(s.get("study_hours"), 0.0)
    sleep_hours = _parse_float(s.get("sleep_hours"), 0.0)
    predicted = float(predict_marks(study_hours, sleep_hours, attendance))

    cursor.execute(
        """
        SELECT status
        FROM attendance
        WHERE student_id=? AND date(date)=date('now')
        ORDER BY id DESC LIMIT 1
        """,
        (student_id,),
    )
    a = row_to_dict(cursor.fetchone()) or {}
    attendance_today = str(a.get("status") or "unknown")

    cursor.execute(
        """
        SELECT COALESCE(SUM(study_minutes), 0) as minutes
        FROM study_time_logs
        WHERE student_id=? AND date(logged_at)=date('now')
        """,
        (student_id,),
    )
    study_minutes_today = _parse_int((row_to_dict(cursor.fetchone()) or {}).get("minutes"), 0)

    cursor.execute(
        """
        SELECT COUNT(*) as c
        FROM intelligent_alerts
        WHERE student_id=? AND recipient_role='parent' AND recipient_id=? AND resolved_at IS NULL
        """,
        (student_id, parent_id),
    )
    open_alerts = _parse_int((row_to_dict(cursor.fetchone()) or {}).get("c"), 0)

    summary = (
        f"Attendance today: {attendance_today}. "
        f"Study minutes today: {study_minutes_today}. "
        f"Open alerts: {open_alerts}. "
        f"Predicted marks: {round(predicted, 2)}."
    )
    cursor.execute(
        """
        INSERT INTO parent_daily_summaries
            (parent_id, student_id, summary_date, attendance_today, study_minutes_today, open_alerts_count, predicted_marks, summary_text)
        VALUES (?, ?, date('now'), ?, ?, ?, ?, ?)
        ON CONFLICT(parent_id, summary_date)
        DO UPDATE SET
            attendance_today=excluded.attendance_today,
            study_minutes_today=excluded.study_minutes_today,
            open_alerts_count=excluded.open_alerts_count,
            predicted_marks=excluded.predicted_marks,
            summary_text=excluded.summary_text
        """,
        (parent_id, student_id, attendance_today, study_minutes_today, open_alerts, round(predicted, 2), summary),
    )
    conn.commit()
    cursor.close()
    conn.close()
    return {
        "attendance_today": attendance_today,
        "study_minutes_today": study_minutes_today,
        "open_alerts_count": open_alerts,
        "predicted_marks": round(predicted, 2),
        "summary_text": summary,
    }

def _create_alert_if_needed(student_id: int, attendance: float, study_hours: float, sleep_hours: float) -> None:
    predicted = float(predict_marks(study_hours, sleep_hours, attendance))
    risk = _risk_score(attendance, study_hours, sleep_hours, predicted)
    if risk["level"] != "high":
        return

    reasons = []
    if attendance < 60:
        reasons.append("attendance < 60%")
    if study_hours < 2:
        reasons.append("study_hours < 2")
    if predicted < 60:
        reasons.append("predicted_marks < 60")
    reason = ", ".join(reasons) or "high risk"

    conn = get_db_connection()
    cursor = conn.cursor()
    # Deduplicate: only one active high alert per student in last 24h.
    cursor.execute(
        """
        SELECT id FROM alerts
        WHERE student_id=? AND resolved_at IS NULL AND level='high'
          AND created_at >= datetime('now', '-1 day')
        ORDER BY id DESC LIMIT 1
        """,
        (student_id,),
    )
    existing = cursor.fetchone()
    if existing:
        cursor.close()
        conn.close()
        return

    cursor.execute(
        """
        INSERT INTO alerts (student_id, level, score, predicted_marks, reason)
        VALUES (?, ?, ?, ?, ?)
        """,
        (student_id, risk["level"], int(risk["score"]), float(predicted), reason),
    )

    # Predictive intervention + escalation logs
    action_plan = "Recommend extra classes, weekly mentor follow-up, and attendance recovery plan."
    cursor.execute(
        """
        INSERT INTO interventions (student_id, risk_level, action_plan, status)
        VALUES (?, ?, ?, 'open')
        """,
        (student_id, risk["level"], action_plan),
    )
    cursor.execute(
        "INSERT INTO escalation_logs (student_id, target_role, message) VALUES (?, 'student', ?)",
        (student_id, "You are at high academic risk. Please follow the intervention plan."),
    )
    cursor.execute(
        "INSERT INTO escalation_logs (student_id, target_role, message) VALUES (?, 'faculty', ?)",
        (student_id, "High-risk student detected. Consider extra classes/intervention."),
    )
    cursor.execute(
        "INSERT INTO escalation_logs (student_id, target_role, message) VALUES (?, 'admin', ?)",
        (student_id, "Escalation: high-risk student intervention created."),
    )
    conn.commit()
    cursor.close()
    conn.close()

def _upsert_intelligent_alert(
    *,
    student_id: int,
    recipient_role: str,
    recipient_id: Optional[int],
    category: str,
    severity: str,
    message: str,
    source_key: str,
) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT OR IGNORE INTO intelligent_alerts
            (student_id, recipient_role, recipient_id, category, severity, message, source_key)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (student_id, recipient_role, recipient_id, category, severity, message, source_key),
    )
    inserted = cursor.rowcount > 0
    conn.commit()
    cursor.close()
    conn.close()
    return inserted

def _resolve_assignment_reminder_alerts(student_id: int, assignment_id: int) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE intelligent_alerts
        SET resolved_at=CURRENT_TIMESTAMP
        WHERE student_id=?
          AND category='assignment_missed'
          AND source_key LIKE ?
          AND resolved_at IS NULL
        """,
        (student_id, f"assignment_missed:{assignment_id}:{student_id}:%"),
    )
    conn.commit()
    cursor.close()
    conn.close()

def _run_intelligent_alert_engine(student_id: int) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, name, attendance, study_hours, sleep_hours FROM students WHERE id=?",
        (student_id,),
    )
    student = row_to_dict(cursor.fetchone())
    if not student:
        cursor.close()
        conn.close()
        return

    attendance = _parse_float(student.get("attendance"))
    study_hours = _parse_float(student.get("study_hours"))
    sleep_hours = _parse_float(student.get("sleep_hours"))
    predicted = float(predict_marks(study_hours, sleep_hours, attendance))
    student_name = student.get("name") or f"#{student_id}"

    # Trigger 1: attendance < 75 -> student + parent alert
    if attendance < 75:
        msg = f"Attendance is {round(attendance, 1)}%. Please improve attendance to stay above 75%."
        inserted_student = _upsert_intelligent_alert(
            student_id=student_id,
            recipient_role="student",
            recipient_id=student_id,
            category="low_attendance",
            severity="medium",
            message=msg,
            source_key=f"low_attendance:{student_id}:{datetime.now(timezone.utc).date().isoformat()}",
        )
        if inserted_student:
            _notify_student_and_parents(
                student_id,
                "Low Attendance Alert",
                msg,
                "attendance",
            )
        cursor.execute("SELECT id FROM parents WHERE student_id=?", (student_id,))
        for p in cursor.fetchall() or []:
            parent_id = _parse_int(p[0], 0)
            if parent_id > 0:
                _upsert_intelligent_alert(
                    student_id=student_id,
                    recipient_role="parent",
                    recipient_id=parent_id,
                    category="low_attendance",
                    severity="medium",
                    message=f"{student_name} attendance dropped below 75% ({round(attendance, 1)}%).",
                    source_key=f"low_attendance_parent:{student_id}:{parent_id}:{datetime.utcnow().date().isoformat()}",
                )

    # Trigger 2: predicted marks < 40 -> faculty alert
    if predicted < 40:
        inserted_faculty = _upsert_intelligent_alert(
            student_id=student_id,
            recipient_role="faculty",
            recipient_id=None,
            category="low_prediction",
            severity="high",
            message=f"{student_name} predicted marks are critically low ({round(predicted, 1)}).",
            source_key=f"low_prediction_faculty:{student_id}:{datetime.utcnow().date().isoformat()}",
        )
        if inserted_faculty:
            _create_notification(
                recipient_role="faculty",
                recipient_id=None,
                title="Critical Prediction Alert",
                message=f"{student_name} predicted marks are below 40. Faculty intervention required.",
                category="prediction",
            )
        # Parent should also receive low-marks warning.
        cursor.execute("SELECT id FROM parents WHERE student_id=?", (student_id,))
        for p in cursor.fetchall() or []:
            parent_id = _parse_int(p[0], 0)
            if parent_id <= 0:
                continue
            inserted_parent_low = _upsert_intelligent_alert(
                student_id=student_id,
                recipient_role="parent",
                recipient_id=parent_id,
                category="low_prediction",
                severity="high",
                message=f"{student_name} predicted marks are low ({round(predicted, 1)}). Parent follow-up recommended.",
                source_key=f"low_prediction_parent:{student_id}:{parent_id}:{datetime.utcnow().date().isoformat()}",
            )
            if inserted_parent_low:
                _create_notification(
                    recipient_role="parent",
                    recipient_id=parent_id,
                    title="Low Marks Warning",
                    message=f"{student_name} predicted marks dropped below 40. Please coordinate with faculty.",
                    category="prediction",
                )

    # Trigger 3: missed assignment due-date reminders -> student + parent alert
    cursor.execute(
        """
        SELECT a.id, a.title, a.due_date, COALESCE(s.status, 'pending') as status
        FROM assignments a
        LEFT JOIN assignment_submissions s
          ON s.assignment_id=a.id AND s.student_id=?
        WHERE a.due_date IS NOT NULL
          AND TRIM(COALESCE(a.due_date, '')) <> ''
          AND date(a.due_date) < date('now')
        ORDER BY a.due_date DESC
        """,
        (student_id,),
    )
    overdue_rows = [row_to_dict(r) for r in cursor.fetchall()]
    parent_ids = []
    cursor.execute("SELECT id FROM parents WHERE student_id=?", (student_id,))
    for p in cursor.fetchall() or []:
        pid = _parse_int(p[0], 0)
        if pid > 0:
            parent_ids.append(pid)

    for row in overdue_rows:
        assignment_id = _parse_int(row.get("id"), 0)
        title = str(row.get("title") or f"Assignment {assignment_id}")
        due_date = str(row.get("due_date") or "")
        status = str(row.get("status") or "pending")
        if status == "completed":
            _resolve_assignment_reminder_alerts(student_id, assignment_id)
            continue

        inserted_missed = _upsert_intelligent_alert(
            student_id=student_id,
            recipient_role="student",
            recipient_id=student_id,
            category="assignment_missed",
            severity="high",
            message=f"Missed due date for '{title}' ({due_date}). Submit as soon as possible.",
            source_key=f"assignment_missed:{assignment_id}:{student_id}:student",
        )
        if inserted_missed:
            _notify_student_and_parents(
                student_id,
                "Missed Assignment Reminder",
                f"Assignment '{title}' is overdue ({due_date}).",
                "assignment",
            )
        for parent_id in parent_ids:
            _upsert_intelligent_alert(
                student_id=student_id,
                recipient_role="parent",
                recipient_id=parent_id,
                category="assignment_missed",
                severity="high",
                message=f"{student_name} missed due date for '{title}' ({due_date}).",
                source_key=f"assignment_missed:{assignment_id}:{student_id}:parent:{parent_id}",
            )

    # Exam reminder alerts for parents (based on latest study plan).
    cursor.execute(
        """
        SELECT exam_date
        FROM ai_study_plans
        WHERE student_id=?
        ORDER BY id DESC
        LIMIT 1
        """,
        (student_id,),
    )
    plan = row_to_dict(cursor.fetchone()) or {}
    exam_date = str(plan.get("exam_date") or "").strip()
    if exam_date:
        try:
            exam_dt = datetime.strptime(exam_date[:10], "%Y-%m-%d").date()
            days_left = (exam_dt - datetime.utcnow().date()).days
            if 0 <= days_left <= 7:
                cursor.execute("SELECT id FROM parents WHERE student_id=?", (student_id,))
                for p in cursor.fetchall() or []:
                    parent_id = _parse_int(p[0], 0)
                    if parent_id <= 0:
                        continue
                    inserted_exam = _upsert_intelligent_alert(
                        student_id=student_id,
                        recipient_role="parent",
                        recipient_id=parent_id,
                        category="exam_reminder",
                        severity="medium",
                        message=f"Upcoming exam on {exam_date} ({days_left} day(s) left).",
                        source_key=f"exam_reminder_parent:{student_id}:{parent_id}:{datetime.utcnow().date().isoformat()}",
                    )
                    if inserted_exam:
                        _create_notification(
                            recipient_role="parent",
                            recipient_id=parent_id,
                            title="Exam Reminder",
                            message=f"{student_name} has an exam on {exam_date} ({days_left} day(s) left).",
                            category="exam",
                        )
        except Exception:
            pass

    cursor.close()
    conn.close()

def _snapshot_student_metrics(
    *,
    student_id: int,
    attendance: float,
    study_hours: float,
    sleep_hours: float,
) -> None:
    predicted = float(predict_marks(study_hours, sleep_hours, attendance))
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO student_metrics_history (student_id, attendance, study_hours, sleep_hours, predicted_marks)
        VALUES (?, ?, ?, ?, ?)
        """,
        (student_id, _parse_int(attendance), float(study_hours), float(sleep_hours), float(predicted)),
    )
    conn.commit()
    cursor.close()
    conn.close()

def _risk_score(attendance: float, study_hours: float, sleep_hours: float, predicted_marks: float) -> Dict[str, Any]:
    score = 0
    if attendance < 60:
        score += 30
    elif attendance < 75:
        score += 10

    if study_hours < 2:
        score += 15
    elif study_hours < 3:
        score += 5

    if sleep_hours < 5:
        score += 15
    elif sleep_hours < 6:
        score += 5

    if predicted_marks < 60:
        score += 40
    elif predicted_marks < 75:
        score += 20

    score = max(0, min(100, score))
    if score <= 33:
        level = "low"
    elif score <= 66:
        level = "medium"
    else:
        level = "high"

    return {"score": score, "level": level}

def _xai_impacts(study_hours: float, sleep_hours: float, attendance: float) -> Dict[str, Any]:
    """
    Lightweight explainability: compare each feature vs a reference profile,
    and show how much it shifts the prediction.
    """
    ref_study, ref_sleep, ref_att = 2.5, 7.5, 80.0
    baseline = float(predict_marks(ref_study, ref_sleep, ref_att))
    p_all = float(predict_marks(study_hours, sleep_hours, attendance))
    p_study = float(predict_marks(study_hours, ref_sleep, ref_att))
    p_sleep = float(predict_marks(ref_study, sleep_hours, ref_att))
    p_att = float(predict_marks(ref_study, ref_sleep, attendance))

    impacts = [
        {"feature": "attendance", "impact": round(p_att - baseline, 2)},
        {"feature": "study_hours", "impact": round(p_study - baseline, 2)},
        {"feature": "sleep_hours", "impact": round(p_sleep - baseline, 2)},
    ]
    impacts_sorted = sorted(impacts, key=lambda x: abs(x["impact"]), reverse=True)
    return {
        "reference": {"study_hours": ref_study, "sleep_hours": ref_sleep, "attendance": ref_att},
        "baseline_marks": round(baseline, 2),
        "predicted_marks": round(p_all, 2),
        "impacts": impacts_sorted,
    }

@app.route('/register', methods=['POST'])
def register():
    try:
        rl = _rate_limit("register", limit=10, window_seconds=60)
        if rl:
            body, code = rl
            return jsonify(body), code

        data = request.get_json()
        name = data.get('name')
        role = data.get('role')
        mobile = data.get('mobile')
        password = data.get('password')
        
        if not all([name, role, mobile, password]):
            return jsonify({'message': 'All fields required!'}), 400

        name = str(name).strip()
        role = str(role).strip()
        mobile = str(mobile).strip()
        password = str(password)

        if len(name) < 2 or len(name) > 80:
            return jsonify({'message': 'Invalid name'}), 400
        if role not in ['admin', 'student', 'faculty']:
            return jsonify({'message': 'Invalid role'}), 400
        if len(mobile) < 8 or len(mobile) > 20:
            return jsonify({'message': 'Invalid mobile'}), 400
        if len(password) < 4 or len(password) > 128:
            return jsonify({'message': 'Invalid password'}), 400
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        hashed_password = generate_password_hash(password)
        
        cursor.execute("""
            INSERT INTO users (name, role, mobile, password)
            VALUES (?, ?, ?, ?)
        """, (name, role, mobile, hashed_password))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return jsonify({'message': 'User registered successfully!'}), 201
    except Exception as e:
        return jsonify({'message': str(e)}), 500

@app.route('/admin/dashboard-stats', methods=['GET'])
@token_required
def admin_dashboard_stats(current_user):
    if current_user.get('role') != 'admin':
        return jsonify({'message': 'Admin access required!'}), 403
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM students")
    total_students = cursor.fetchone()[0]
    
    cursor.execute("SELECT AVG(attendance) FROM students")
    avg_attendance = cursor.fetchone()[0] or 0
    
    # Simple risk logic: attendance < 75
    cursor.execute("SELECT COUNT(*) FROM students WHERE attendance < 75")
    at_risk_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT SUM(amount) FROM payments")
    total_payments = cursor.fetchone()[0] or 0
    
    cursor.close()
    conn.close()
    
    return jsonify({
        'total_students': total_students,
        'avg_attendance': avg_attendance,
        'at_risk_count': at_risk_count,
        'total_payments': total_payments
    })

@app.route('/admin/users', methods=['GET'])
@token_required
def admin_users(current_user):
    if current_user.get('role') != 'admin':
        return jsonify({'message': 'Admin access required!'}), 403
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, role, mobile FROM users")
    users = [dict(row) for row in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify(users)

@app.route('/login', methods=['POST'])
def login():
    try:
        rl = _rate_limit("login", limit=15, window_seconds=60)
        if rl:
            body, code = rl
            return jsonify(body), code

        data = request.get_json()
        mobile = data.get('mobile')
        password = data.get('password')
        mobile = str(mobile or '').strip()
        password = str(password or '')
        if not mobile or not password:
            return jsonify({'message': 'Mobile and password required!'}), 400
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM users WHERE mobile = ?", (mobile,))
        user = cursor.fetchone()
        
        cursor.close()
        conn.close()
        
        user_dict = row_to_dict(user)
        
        # Fallback to parent table if no user row exists for a parent account.
        if not user_dict:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM parents WHERE mobile = ?", (mobile,))
            parent = cursor.fetchone()
            cursor.close()
            conn.close()
            parent_dict = row_to_dict(parent)
            if parent_dict and check_password_hash(parent_dict['password'], password):
                user_dict = {
                    'id': parent_dict['id'],
                    'name': parent_dict['name'],
                    'role': 'parent',
                    'mobile': parent_dict['mobile'],
                    'password': parent_dict['password']
                }
            else:
                user_dict = None
        
        if user_dict and check_password_hash(user_dict['password'], password):
            # Record Login History (Phase 8)
            try:
                ip_addr = request.remote_addr
                user_agent = request.headers.get('User-Agent', 'Unknown')
                device_type = "Desktop"
                if "Mobile" in user_agent:
                    device_type = "Mobile"
                elif "Tablet" in user_agent:
                    device_type = "Tablet"
                
                conn_log = get_db_connection()
                cursor_log = conn_log.cursor()
                cursor_log.execute("""
                    INSERT INTO login_history (user_id, ip_address, user_agent, device_type, status)
                    VALUES (?, ?, ?, ?, ?)
                """, (user_dict['id'], ip_addr, user_agent, device_type, 'success'))
                conn_log.commit()
                cursor_log.close()
                conn_log.close()
            except Exception as log_e:
                logger.error(f"Failed to log login history: {log_e}")

            # Fetch student_id, dept_id, semester_id, dept_name for students and parents
            student_id = None
            dept_id = None
            semester_id = None
            dept_name = None
            if user_dict['role'] == 'parent':
                cursor = get_db_connection().cursor()
                cursor.execute("SELECT student_id FROM parents WHERE mobile = ?", (mobile,))
                row = cursor.fetchone()
                if row:
                    student_id = row[0]
                    # Also get dept/sem for parent view
                    cursor.execute("""
                        SELECT s.department_id, s.semester_id, d.name as dept_name 
                        FROM students s 
                        LEFT JOIN departments_master d ON s.department_id = d.id 
                        WHERE s.id = ?
                    """, (student_id,))
                    s_row = cursor.fetchone()
                    if s_row:
                        dept_id, semester_id, dept_name = s_row[0], s_row[1], s_row[2]
                cursor.close()
            elif user_dict['role'] == 'student':
                student_id = _get_linked_student_id(user_dict['id'])
                if student_id:
                    cursor = get_db_connection().cursor()
                    cursor.execute("""
                        SELECT s.department_id, s.semester_id, d.name as dept_name 
                        FROM students s 
                        LEFT JOIN departments_master d ON s.department_id = d.id 
                        WHERE s.id = ?
                    """, (student_id,))
                    s_row = cursor.fetchone()
                    if s_row:
                        dept_id, semester_id, dept_name = s_row[0], s_row[1], s_row[2]
                    cursor.close()

            token_data = {
                'id': user_dict['id'],
                'role': user_dict['role'],
                'exp': datetime.now(timezone.utc) + timedelta(days=7)
            }
            if student_id:
                token_data['student_id'] = student_id
            if dept_id:
                token_data['dept_id'] = dept_id
            if semester_id:
                token_data['semester_id'] = semester_id

            token = jwt.encode(token_data, app.config['SECRET_KEY'], algorithm="HS256")
            
            return jsonify({
                'token': token,
                'user': {
                    'id': user_dict['id'],
                    'name': user_dict['name'],
                    'role': user_dict['role'],
                    'student_id': student_id,
                    'dept_id': dept_id,
                    'semester_id': semester_id,
                    'dept_name': dept_name
                }
            }), 200
        else:
            return jsonify({'message': 'Invalid credentials!'}), 401
    except Exception as e:
        return jsonify({'message': str(e)}), 500

@app.route('/token/refresh', methods=['POST'])
@token_required
def refresh_token(current_user):
    """
    Issue a new token if the current one is valid.
    """
    try:
        token = jwt.encode(
            {
                'id': current_user['id'],
                'role': current_user['role'],
                'exp': datetime.now(timezone.utc) + timedelta(days=7),
            },
            app.config['SECRET_KEY'],
            algorithm="HS256",
        )
        return jsonify({"token": token}), 200
    except Exception as e:
        return jsonify({"message": str(e)}), 500

@app.route('/parent/register', methods=['POST'])
def parent_register():
    try:
        data = request.get_json() or {}
        name = str(data.get('name') or '').strip()
        mobile = str(data.get('mobile') or '').strip()
        password = str(data.get('password') or '')
        student_id = _parse_int(data.get('student_id'), 0)

        if len(name) < 2 or len(name) > 80:
            return jsonify({'message': 'Invalid name'}), 400
        if len(mobile) < 8 or len(mobile) > 20:
            return jsonify({'message': 'Invalid mobile'}), 400
        if len(password) < 4 or len(password) > 128:
            return jsonify({'message': 'Invalid password'}), 400
        if student_id <= 0:
            return jsonify({'message': 'Invalid student_id'}), 400

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM students WHERE id=?", (student_id,))
        if not cursor.fetchone():
            cursor.close()
            conn.close()
            return jsonify({'message': 'student_id not found'}), 404

        hashed = generate_password_hash(password)
        cursor.execute(
            "INSERT INTO parents (name, mobile, password, student_id) VALUES (?, ?, ?, ?)",
            (name, mobile, hashed, student_id),
        )
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"message": "Parent registered successfully"}), 201
    except Exception as e:
        return jsonify({"message": str(e)}), 500

@app.route('/parent/login', methods=['POST'])
def parent_login():
    try:
        data = request.get_json() or {}
        mobile = str(data.get('mobile') or '').strip()
        password = str(data.get('password') or '')
        if not mobile or not password:
            return jsonify({'message': 'Mobile and password required'}), 400

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM parents WHERE mobile=?", (mobile,))
        p = row_to_dict(cursor.fetchone())
        cursor.close()
        conn.close()
        if not p or not check_password_hash(p['password'], password):
            return jsonify({'message': 'Invalid credentials'}), 401

        token = jwt.encode(
            {
                'id': p['id'],
                'role': 'parent',
                'student_id': p['student_id'],
                'exp': datetime.now(timezone.utc) + timedelta(days=7)
            },
            app.config['SECRET_KEY'],
            algorithm="HS256",
        )
        return jsonify({
            "token": token,
            "user": {"id": p["id"], "name": p["name"], "role": "parent", "student_id": p["student_id"]}
        }), 200
    except Exception as e:
        return jsonify({"message": str(e)}), 500

@app.route('/parent/me/dashboard', methods=['GET'])
@token_required
def parent_dashboard(current_user):
    if current_user.get("role") != "parent":
        return jsonify({"message": "Unauthorized!"}), 403
    student_id = _parse_int(current_user.get("student_id"), 0)
    if student_id <= 0:
        return jsonify({"message": "Parent account not linked to student"}), 409

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT s.id, s.name, s.attendance, s.study_hours, s.sleep_hours, s.created_at, d.name as department_name, d.stream
        FROM students s
        LEFT JOIN departments_master d ON d.id = s.department_id
        WHERE s.id=?
    """, (student_id,))
    student = row_to_dict(cursor.fetchone())
    if not student:
        cursor.close()
        conn.close()
        return jsonify({"message": "Student not found"}), 404

    attendance = _parse_float(student.get("attendance"))
    study_hours = _parse_float(student.get("study_hours"))
    sleep_hours = _parse_float(student.get("sleep_hours"))
    predicted = float(predict_marks(study_hours, sleep_hours, attendance))
    risk = _risk_score(attendance, study_hours, sleep_hours, predicted)

    cursor.execute(
        """
        SELECT date, status, reason, notes
        FROM attendance
        WHERE student_id=?
        ORDER BY date DESC
        LIMIT 20
        """,
        (student_id,),
    )
    attendance_history = [row_to_dict(r) for r in cursor.fetchall()]

    cursor.execute("SELECT * FROM announcements ORDER BY created_at DESC LIMIT 10")
    announcements = [row_to_dict(r) for r in cursor.fetchall()]

    cursor.execute(
        """
        SELECT level, score, reason, created_at
        FROM alerts
        WHERE student_id=?
        ORDER BY id DESC
        LIMIT 10
        """,
        (student_id,),
    )
    alerts = [row_to_dict(r) for r in cursor.fetchall()]

    cursor.execute(
        """
        SELECT date(logged_at) as day, SUM(study_minutes) as minutes
        FROM study_time_logs
        WHERE student_id=? AND logged_at >= datetime('now', '-7 day')
        GROUP BY date(logged_at)
        ORDER BY day DESC
        """,
        (student_id,),
    )
    daily_activity = [row_to_dict(r) for r in cursor.fetchall()]

    cursor.execute(
        """
        SELECT exam_date, weak_subjects, available_hours, schedule_json, created_at
        FROM ai_study_plans
        WHERE student_id=?
        ORDER BY id DESC
        LIMIT 1
        """,
        (student_id,),
    )
    latest_plan = row_to_dict(cursor.fetchone())
    cursor.close()
    conn.close()

    return jsonify({
        "student": student,
        "predicted_marks": round(predicted, 2),
        "risk": risk,
        "attendance_history": attendance_history,
        "announcements": announcements,
        "alerts": alerts,
        "daily_activity": daily_activity,
        "latest_study_plan": latest_plan,
    }), 200

@app.route('/parent/daily-summary', methods=['GET'])
@token_required
def parent_daily_summary(current_user):
    if current_user.get("role") != "parent":
        return jsonify({"message": "Unauthorized!"}), 403
    parent_id = _parse_int(current_user.get("id"), 0)
    student_id = _get_parent_student_id(parent_id)
    if not student_id:
        return jsonify({"message": "Parent account not linked to student"}), 409

    today_summary = _upsert_parent_daily_summary(parent_id, student_id)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT summary_date, attendance_today, study_minutes_today, open_alerts_count, predicted_marks, summary_text, created_at
        FROM parent_daily_summaries
        WHERE parent_id=?
        ORDER BY summary_date DESC
        LIMIT 7
        """,
        (parent_id,),
    )
    rows = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"today": today_summary, "items": rows}), 200

@app.route('/students', methods=['GET', 'POST'])
@token_required
def students(current_user):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if request.method == 'GET':
        search = request.args.get('search', '')
        attendance_bucket = request.args.get('attendance', 'all')  # all|low|medium|high
        risk = request.args.get('risk', 'all')  # all|atrisk|warning|good
        performance = request.args.get('performance', 'all')  # all|high|weak
        limit = request.args.get('limit')
        paged = request.args.get('paged', '0')  # 1 enables pagination response
        page = _parse_int(request.args.get('page'), 1)
        page_size = _parse_int(request.args.get('page_size'), 25)
        page = max(1, page)
        page_size = max(1, min(200, page_size))

        where_sql, params = _build_students_where_clause(search, attendance_bucket, risk, performance)
        base_sql = " FROM students s LEFT JOIN departments_master d ON d.id = s.department_id" + where_sql

        if paged == "1":
            # total count
            cursor.execute("SELECT COUNT(*) as c FROM students s" + where_sql, params)
            total = cursor.fetchone()[0]

            offset = (page - 1) * page_size
            cursor.execute(
                "SELECT s.*, d.name as department_name" + base_sql + " ORDER BY s.id DESC LIMIT ? OFFSET ?",
                params + [page_size, offset],
            )
            students_list = [row_to_dict(row) for row in cursor.fetchall()]
            cursor.close()
            conn.close()
            return jsonify(
                {
                    "items": students_list,
                    "page": page,
                    "page_size": page_size,
                    "total": total,
                    "total_pages": (total + page_size - 1) // page_size,
                }
            ), 200

        sql = "SELECT s.*, d.name as department_name" + base_sql + " ORDER BY s.id DESC"
        if limit:
            sql += " LIMIT ?"
            params.append(_parse_int(limit, 200))
        cursor.execute(sql, params)
        students_list = [row_to_dict(row) for row in cursor.fetchall()]
        cursor.close()
        conn.close()
        return jsonify(students_list), 200
    
    if request.method == 'POST':
        if current_user['role'] not in ['admin', 'faculty']:
            return jsonify({'message': 'Unauthorized!'}), 403
        
        data = request.get_json()
        name = str((data or {}).get('name', '')).strip()
        if len(name) < 2 or len(name) > 80:
            return jsonify({'message': 'Invalid student name'}), 400

        attendance = _parse_int((data or {}).get('attendance', 0), 0)
        study_hours = _parse_float((data or {}).get('study_hours', 0), 0)
        sleep_hours = _parse_float((data or {}).get('sleep_hours', 0), 0)
        if attendance < 0 or attendance > 100:
            return jsonify({'message': 'Attendance must be 0-100'}), 400
        if study_hours < 0 or study_hours > 24:
            return jsonify({'message': 'Study hours must be 0-24'}), 400
        if sleep_hours < 0 or sleep_hours > 24:
            return jsonify({'message': 'Sleep hours must be 0-24'}), 400

        department_id = _parse_int((data or {}).get('department_id'), None)
        semester_id = _parse_int((data or {}).get('semester_id'), None)
        mobile = str((data or {}).get('mobile') or "").strip()

        cursor.execute("""
            INSERT INTO students (name, attendance, study_hours, sleep_hours, department_id, semester_id, mobile)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (name, attendance, study_hours, sleep_hours, department_id, semester_id, mobile))

        student_id = cursor.lastrowid
        
        conn.commit()
        cursor.close()
        conn.close()

        try:
            _snapshot_student_metrics(
                student_id=int(student_id),
                attendance=float(attendance),
                study_hours=float(study_hours),
                sleep_hours=float(sleep_hours),
            )
        except Exception:
            # Snapshot is best-effort; core student creation must succeed.
            pass

        try:
            _create_alert_if_needed(int(student_id), float(attendance), float(study_hours), float(sleep_hours))
        except Exception:
            pass
        try:
            _run_intelligent_alert_engine(int(student_id))
        except Exception:
            pass

        _cache_invalidate("dashboard:")
        _cache_invalidate("analytics:")
        _cache_invalidate("insights:")
        _cache_invalidate("alerts:")

        socketio.emit('dashboard_update')
        return jsonify({'message': 'Student added!'}), 201

@app.route('/students/<int:id>', methods=['PUT', 'DELETE'])
@token_required
def student_detail(current_user, id):
    if current_user['role'] not in ['admin', 'faculty']:
        return jsonify({'message': 'Unauthorized!'}), 403
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if request.method == 'PUT':
        data = request.get_json()
        name = str((data or {}).get('name', '')).strip()
        attendance = _parse_int((data or {}).get('attendance', 0), 0)
        study_hours = _parse_float((data or {}).get('study_hours', 0), 0)
        sleep_hours = _parse_float((data or {}).get('sleep_hours', 0), 0)

        if len(name) < 2 or len(name) > 80:
            return jsonify({'message': 'Invalid student name'}), 400
        if attendance < 0 or attendance > 100:
            return jsonify({'message': 'Attendance must be 0-100'}), 400
        if study_hours < 0 or study_hours > 24:
            return jsonify({'message': 'Study hours must be 0-24'}), 400
        if sleep_hours < 0 or sleep_hours > 24:
            return jsonify({'message': 'Sleep hours must be 0-24'}), 400

        department_id = _parse_int((data or {}).get('department_id'), None)
        semester_id = _parse_int((data or {}).get('semester_id'), None)
        mobile = str((data or {}).get('mobile') or "").strip()

        cursor.execute("""
            UPDATE students 
            SET name=?, attendance=?, study_hours=?, sleep_hours=?, department_id=?, semester_id=?, mobile=?
            WHERE id=?
        """, (name, attendance, study_hours, sleep_hours, department_id, semester_id, mobile, id))
        
        conn.commit()
        
        cursor.execute("SELECT * FROM students WHERE id=?", (id,))
        student = cursor.fetchone()
        student_dict = row_to_dict(student)
        
        if student_dict and student_dict['attendance'] < 60 and app.config['MAIL_USERNAME']:
            msg = Message('Attendance Alert', sender=app.config['MAIL_USERNAME'], recipients=[app.config['MAIL_USERNAME']])
            msg.body = f"Student {student_dict['name']} has low attendance: {student_dict['attendance']}%"
            mail.send(msg)
        
        cursor.close()
        conn.close()

        try:
            _snapshot_student_metrics(
                student_id=int(id),
                attendance=float(attendance),
                study_hours=float(study_hours),
                sleep_hours=float(sleep_hours),
            )
        except Exception:
            pass

        try:
            _create_alert_if_needed(int(id), float(attendance), float(study_hours), float(sleep_hours))
        except Exception:
            pass
        try:
            _run_intelligent_alert_engine(int(id))
        except Exception:
            pass

        _cache_invalidate("dashboard:")
        _cache_invalidate("analytics:")
        _cache_invalidate("insights:")
        _cache_invalidate("student_profile:")
        _cache_invalidate("alerts:")

        socketio.emit('dashboard_update')
        return jsonify({'message': 'Student updated!'}), 200
    
    if request.method == 'DELETE':
        cursor.execute("DELETE FROM students WHERE id=?", (id,))
        conn.commit()
        cursor.close()
        conn.close()
        _cache_invalidate("dashboard:")
        _cache_invalidate("analytics:")
        _cache_invalidate("insights:")
        _cache_invalidate("student_profile:")
        socketio.emit('dashboard_update')
        return jsonify({'message': 'Student deleted!'}), 200

@app.route('/attendance', methods=['GET', 'POST'])
@token_required
def attendance(current_user):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if request.method == 'GET':
        student_id = request.args.get('student_id')
        if student_id:
            cursor.execute("SELECT * FROM attendance WHERE student_id=?", (student_id,))
        else:
            cursor.execute("SELECT * FROM attendance")
        
        attendance_list = [row_to_dict(row) for row in cursor.fetchall()]
        cursor.close()
        conn.close()
        return jsonify(attendance_list), 200
    
    if request.method == 'POST':
        if current_user['role'] not in ['admin', 'faculty']:
            return jsonify({'message': 'Unauthorized!'}), 403
        
        data = request.get_json() or {}
        student_id = _parse_int(data.get('student_id'), 0)
        date = str(data.get('date') or '').strip()
        status = str(data.get('status') or '').strip()
        notes = str(data.get('notes') or '')
        reason = str(data.get('reason') or '').strip().lower()

        if student_id <= 0:
            return jsonify({'message': 'Invalid student_id'}), 400
        if not date or len(date) > 32:
            return jsonify({'message': 'Invalid date'}), 400
        if status not in ['present', 'absent']:
            return jsonify({'message': 'Invalid status'}), 400
        if len(notes) > 500:
            return jsonify({'message': 'Notes too long'}), 400
        if reason and reason not in ['sick', 'personal', 'other']:
            return jsonify({'message': 'Invalid reason. Use sick/personal/other'}), 400

        cursor.execute("""
            INSERT INTO attendance (student_id, date, status, notes, reason)
            VALUES (?, ?, ?, ?, ?)
        """, (student_id, date, status, notes, reason))
        
        conn.commit()
        cursor.close()
        conn.close()
        try:
            # Recompute alert after attendance events (uses current student metrics from students table)
            conn2 = get_db_connection()
            cur2 = conn2.cursor()
            cur2.execute("SELECT attendance, study_hours, sleep_hours FROM students WHERE id=?", (student_id,))
            row = cur2.fetchone()
            cur2.close()
            conn2.close()
            if row:
                _create_alert_if_needed(student_id, _parse_float(row[0]), _parse_float(row[1]), _parse_float(row[2]))
        except Exception:
            pass
        try:
            _run_intelligent_alert_engine(int(student_id))
        except Exception:
            pass

        _cache_invalidate("dashboard:")
        _cache_invalidate("analytics:")
        _cache_invalidate("student_profile:")
        _cache_invalidate("alerts:")
        socketio.emit('attendance_update')
        socketio.emit('dashboard_update')
        return jsonify({'message': 'Attendance marked!'}), 201

@app.route('/attendance/self-report', methods=['POST'])
@token_required
def attendance_self_report(current_user):
    if current_user.get("role") != "student":
        return jsonify({'message': 'Unauthorized!'}), 403
    student_id = _get_linked_student_id(int(current_user["id"]))
    if not student_id:
        return jsonify({"message": "Student account not linked"}), 409

    data = request.get_json() or {}
    date = str(data.get('date') or '').strip()
    status = str(data.get('status') or '').strip()
    reason = str(data.get('reason') or '').strip().lower()
    notes = str(data.get('notes') or '').strip()

    if not date or len(date) > 32:
        return jsonify({'message': 'Invalid date'}), 400
    if status not in ['present', 'absent']:
        return jsonify({'message': 'Invalid status'}), 400
    if reason and reason not in ['sick', 'personal', 'other']:
        return jsonify({'message': 'Invalid reason. Use sick/personal/other'}), 400
    if len(notes) > 500:
        return jsonify({'message': 'Notes too long'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO attendance (student_id, date, status, notes, reason) VALUES (?, ?, ?, ?, ?)",
        (student_id, date, status, notes, reason),
    )
    conn.commit()
    cursor.close()
    conn.close()
    try:
        _run_intelligent_alert_engine(int(student_id))
    except Exception:
        pass

    _cache_invalidate("dashboard:")
    _cache_invalidate("analytics:")
    _cache_invalidate("student_profile:")
    _cache_invalidate("alerts:")
    socketio.emit('attendance_update')
    socketio.emit('dashboard_update')
    return jsonify({'message': 'Attendance self-report submitted'}), 201

@app.route('/announcements', methods=['GET', 'POST'])
@token_required
def announcements(current_user):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if request.method == 'GET':
        cursor.execute("SELECT * FROM announcements ORDER BY created_at DESC")
        announcements_list = [row_to_dict(row) for row in cursor.fetchall()]
        cursor.close()
        conn.close()
        return jsonify(announcements_list), 200
    
    if request.method == 'POST':
        if current_user['role'] not in ['admin', 'faculty']:
            return jsonify({'message': 'Unauthorized!'}), 403
        
        data = request.get_json() or {}
        message = str(data.get('message') or '').strip()
        if len(message) < 2 or len(message) > 2000:
            return jsonify({'message': 'Invalid message'}), 400
        cursor.execute("INSERT INTO announcements (message) VALUES (?)", (message,))
        
        conn.commit()
        cursor.close()
        conn.close()
        socketio.emit('new_announcement', {'message': message})
        return jsonify({'message': 'Announcement created!'}), 201

@app.route('/notes', methods=['GET', 'POST'])
@token_required
def notes(current_user):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if request.method == 'GET':
        cursor.execute("SELECT * FROM notes ORDER BY uploaded_at DESC")
        notes_list = [row_to_dict(row) for row in cursor.fetchall()]
        cursor.close()
        conn.close()
        return jsonify(notes_list), 200
    
    if request.method == 'POST':
        if current_user['role'] not in ['admin', 'faculty']:
            return jsonify({'message': 'Unauthorized!'}), 403
        
        course = request.form.get('course')
        file = request.files.get('file')
        
        if file:
            filename = file.filename
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            
            cursor.execute("INSERT INTO notes (course, file) VALUES (?, ?)", (course, filename))
            conn.commit()
        
        cursor.close()
        conn.close()
        return jsonify({'message': 'Note uploaded!'}), 201

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/dashboard')
@token_required
def dashboard(current_user):
    cache_key = f"dashboard:{current_user.get('role','')}:{current_user.get('id','')}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return jsonify(cached), 200

    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) as count FROM students")
    total_students = cursor.fetchone()[0]
    
    cursor.execute("SELECT AVG(attendance) as avg_att FROM students")
    avg_attendance = cursor.fetchone()[0] or 0
    
    cursor.execute("SELECT id, name, attendance, study_hours, sleep_hours FROM students LIMIT 7")
    students = [row_to_dict(row) for row in cursor.fetchall()]
    
    chart_data = {
        'labels': [s['name'] for s in students],
        'attendance': [s['attendance'] for s in students],
        'study_hours': [s['study_hours'] for s in students]
    }
    
    cursor.close()
    conn.close()

    payload = {
        'total_students': total_students,
        'avg_attendance': round(avg_attendance, 2),
        'chart_data': chart_data
    }
    _cache_set(cache_key, payload, ttl_seconds=15)
    return jsonify(payload), 200

@app.route('/analytics', methods=['GET'])
@token_required
def analytics(current_user):
    """
    Advanced analytics endpoint used by dashboards.
    Returns:
      - trend data (attendance marks by day)
      - top performers / at-risk lists (based on predicted marks)
      - distribution stats
    """
    days = _parse_int(request.args.get('days'), 30)
    days = max(7, min(days, 180))

    cache_key = f"analytics:{days}:{current_user.get('role','')}:{current_user.get('id','')}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return jsonify(cached), 200

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) as count FROM students")
    total_students = cursor.fetchone()[0]

    cursor.execute("SELECT AVG(attendance) as avg_att FROM students")
    avg_attendance = cursor.fetchone()[0] or 0

    # Attendance trends from attendance table; fallback to empty if table unused.
    cursor.execute(
        """
        SELECT date as day,
               AVG(CASE WHEN status='present' THEN 1.0 ELSE 0.0 END) as present_rate,
               COUNT(*) as records
        FROM attendance
        WHERE date >= date('now', ?)
        GROUP BY date
        ORDER BY date ASC
        """,
        (f"-{days} day",),
    )
    trend_rows = [row_to_dict(r) for r in cursor.fetchall()]

    # Student-level analytics with predicted marks.
    cursor.execute("SELECT id, name, attendance, study_hours, sleep_hours FROM students")
    student_rows = [row_to_dict(r) for r in cursor.fetchall()]

    enriched: List[Dict[str, Any]] = []
    for s in student_rows:
        predicted = predict_marks(
            _parse_float(s.get('study_hours')),
            _parse_float(s.get('sleep_hours')),
            _parse_float(s.get('attendance')),
        )
        risk_level = "safe"
        if (s.get('attendance') or 0) < 60 or (s.get('study_hours') or 0) < 2 or (s.get('sleep_hours') or 0) < 5:
            risk_level = "atrisk"
        elif (s.get('attendance') or 0) < 75:
            risk_level = "warning"

        enriched.append(
            {
                **s,
                "predicted_marks": round(float(predicted), 2),
                "risk_level": risk_level,
            }
        )

    top_performers = sorted(enriched, key=lambda x: x["predicted_marks"], reverse=True)[:5]
    at_risk = sorted([e for e in enriched if e["risk_level"] == "atrisk"], key=lambda x: x["predicted_marks"])[:8]

    distribution = {
        "attendance_low": len([e for e in enriched if (e.get("attendance") or 0) < 60]),
        "attendance_medium": len([e for e in enriched if 60 <= (e.get("attendance") or 0) <= 75]),
        "attendance_high": len([e for e in enriched if (e.get("attendance") or 0) > 75]),
    }

    cursor.close()
    conn.close()

    payload = {
        "total_students": total_students,
        "avg_attendance": round(avg_attendance, 2),
        "attendance_trend": trend_rows,  # {day, present_rate, records}
        "top_performers": top_performers,
        "at_risk": at_risk,
        "distribution": distribution,
    }
    _cache_set(cache_key, payload, ttl_seconds=20)
    return jsonify(payload), 200

@app.route('/insights', methods=['GET'])
@token_required
def insights(current_user):
    """
    Smart, human-readable recommendations per student.
    """
    limit = _parse_int(request.args.get('limit'), 50)
    limit = max(1, min(limit, 200))

    cache_key = f"insights:{request.args.get('search','')}:{request.args.get('attendance','all')}:{request.args.get('risk','all')}:{request.args.get('performance','all')}:{limit}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return jsonify(cached), 200

    students = _fetch_students_for_reporting(
        search=request.args.get('search', ''),
        attendance_bucket=request.args.get('attendance', 'all'),
        risk=request.args.get('risk', 'all'),
        performance=request.args.get('performance', 'all'),
        limit=limit,
    )

    results: List[Dict[str, Any]] = []
    for s in students:
        attendance = _parse_float(s.get("attendance"))
        study_hours = _parse_float(s.get("study_hours"))
        sleep_hours = _parse_float(s.get("sleep_hours"))

        predicted = float(predict_marks(study_hours, sleep_hours, attendance))
        tips: List[str] = []

        if attendance < 60:
            tips.append("Low attendance → risk of failure. Improve attendance above 60%.")

        if sleep_hours < 5:
            tips.append("Sleep < 5 hrs → performance drop. Aim for 7+ hrs sleep.")

        # Study-time delta suggestion toward a target marks band.
        target = 75.0
        if predicted < target:
            predicted_plus2 = float(predict_marks(study_hours + 2, sleep_hours, attendance))
            if predicted_plus2 > predicted:
                tips.append(f"Increase study by +2 hrs/day → predicted marks {predicted_plus2:.0f} (from {predicted:.0f}).")
            else:
                tips.append("Increase study hours gradually (+1 to +2 hrs/day) to improve marks.")
        else:
            tips.append("Good standing → maintain consistency to keep marks high.")

        results.append(
            {
                "id": s.get("id"),
                "name": s.get("name"),
                "attendance": attendance,
                "study_hours": study_hours,
                "sleep_hours": sleep_hours,
                "predicted_marks": round(predicted, 2),
                "recommendations": tips[:4],
            }
        )

    payload = {"count": len(results), "items": results}
    _cache_set(cache_key, payload, ttl_seconds=25)
    return jsonify(payload), 200

@app.route('/reports/students.csv', methods=['GET'])
@token_required
def report_students_csv(current_user):
    if current_user.get("role") not in ["admin", "faculty"]:
        return jsonify({"message": "Unauthorized!"}), 403

    students = _fetch_students_for_reporting(
        search=request.args.get('search', ''),
        attendance_bucket=request.args.get('attendance', 'all'),
        risk=request.args.get('risk', 'all'),
        performance=request.args.get('performance', 'all'),
        limit=None,
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Name", "Attendance (%)", "Study Hours", "Sleep Hours", "Predicted Marks"])
    for s in students:
        attendance = _parse_float(s.get("attendance"))
        study_hours = _parse_float(s.get("study_hours"))
        sleep_hours = _parse_float(s.get("sleep_hours"))
        predicted = float(predict_marks(study_hours, sleep_hours, attendance))
        writer.writerow([s.get("id"), s.get("name"), attendance, study_hours, sleep_hours, round(predicted, 2)])

    mem = io.BytesIO(output.getvalue().encode("utf-8-sig"))
    mem.seek(0)
    filename = f"students_{datetime.now().strftime('%Y-%m-%d')}.csv"
    return send_file(mem, as_attachment=True, download_name=filename, mimetype="text/csv")

@app.route('/reports/students.xlsx', methods=['GET'])
@token_required
def report_students_xlsx(current_user):
    if current_user.get("role") not in ["admin", "faculty"]:
        return jsonify({"message": "Unauthorized!"}), 403

    students = _fetch_students_for_reporting(
        search=request.args.get('search', ''),
        attendance_bucket=request.args.get('attendance', 'all'),
        risk=request.args.get('risk', 'all'),
        performance=request.args.get('performance', 'all'),
        limit=None,
    )

    wb = Workbook()
    ws = wb.active
    ws.title = "Students"
    ws.append(["ID", "Name", "Attendance (%)", "Study Hours", "Sleep Hours", "Predicted Marks"])

    for s in students:
        attendance = _parse_float(s.get("attendance"))
        study_hours = _parse_float(s.get("study_hours"))
        sleep_hours = _parse_float(s.get("sleep_hours"))
        predicted = float(predict_marks(study_hours, sleep_hours, attendance))
        ws.append([s.get("id"), s.get("name"), attendance, study_hours, sleep_hours, round(predicted, 2)])

    mem = io.BytesIO()
    wb.save(mem)
    mem.seek(0)
    filename = f"students_{datetime.now().strftime('%Y-%m-%d')}.xlsx"
    return send_file(
        mem,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

@app.route('/reports/students.pdf', methods=['GET'])
@token_required
def report_students_pdf(current_user):
    if current_user.get("role") not in ["admin", "faculty"]:
        return jsonify({"message": "Unauthorized!"}), 403

    students = _fetch_students_for_reporting(
        search=request.args.get('search', ''),
        attendance_bucket=request.args.get('attendance', 'all'),
        risk=request.args.get('risk', 'all'),
        performance=request.args.get('performance', 'all'),
        limit=None,
    )

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, title="Students Report")
    styles = getSampleStyleSheet()

    story = []
    story.append(Paragraph("Students Report", styles["Title"]))
    story.append(Paragraph(datetime.now().strftime("%Y-%m-%d %H:%M"), styles["Normal"]))
    story.append(Spacer(1, 12))

    data = [["ID", "Name", "Attendance", "Study", "Sleep", "Predicted"]]
    for s in students[:250]:  # keep PDFs readable
        attendance = _parse_float(s.get("attendance"))
        study_hours = _parse_float(s.get("study_hours"))
        sleep_hours = _parse_float(s.get("sleep_hours"))
        predicted = float(predict_marks(study_hours, sleep_hours, attendance))
        data.append(
            [
                str(s.get("id")),
                str(s.get("name")),
                f"{attendance:.0f}%",
                f"{study_hours:g}h",
                f"{sleep_hours:g}h",
                f"{predicted:.1f}",
            ]
        )

    table = Table(data, repeatRows=1, colWidths=[38, 170, 70, 55, 55, 65])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 10),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.lightgrey]),
                ("FONTSIZE", (0, 1), (-1, -1), 9),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ]
        )
    )
    story.append(table)
    doc.build(story)

    buffer.seek(0)
    filename = f"students_{datetime.now().strftime('%Y-%m-%d')}.pdf"
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype="application/pdf")

@app.route('/predict', methods=['POST'])
@token_required
def predict(current_user):
    data = request.get_json()
    study_hours = data.get('study_hours', 0)
    sleep_hours = data.get('sleep_hours', 0)
    attendance = data.get('attendance', 0)
    
    predicted_marks = predict_marks(study_hours, sleep_hours, attendance)
    
    if predicted_marks < 60 and app.config['MAIL_USERNAME']:
        msg = Message('Performance Alert', sender=app.config['MAIL_USERNAME'], recipients=[app.config['MAIL_USERNAME']])
        msg.body = f"Low performance predicted: {predicted_marks:.2f} marks"
        mail.send(msg)
    
    return jsonify({'predicted_marks': round(predicted_marks, 2)}), 200

@app.route('/predict/explain', methods=['POST'])
@token_required
def predict_explain(current_user):
    data = request.get_json() or {}
    study_hours = _parse_float(data.get('study_hours', 0))
    sleep_hours = _parse_float(data.get('sleep_hours', 0))
    attendance = _parse_float(data.get('attendance', 0))

    cache_key = f"predict_explain:{study_hours}:{sleep_hours}:{attendance}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return jsonify(cached), 200

    xai = _xai_impacts(study_hours, sleep_hours, attendance)
    risk = _risk_score(attendance, study_hours, sleep_hours, _parse_float(xai["predicted_marks"]))
    payload = {**xai, "risk": risk}
    _cache_set(cache_key, payload, ttl_seconds=60)
    return jsonify(payload), 200

@app.route('/students/<int:id>/profile', methods=['GET'])
@token_required
def student_profile(current_user, id):
    cache_key = f"student_profile:{id}:{_parse_int(request.args.get('limit'), 60)}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return jsonify(cached), 200

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM students WHERE id=?", (id,))
    student = row_to_dict(cursor.fetchone())
    if not student:
        cursor.close()
        conn.close()
        return jsonify({"message": "Student not found"}), 404

    limit = _parse_int(request.args.get("limit"), 60)
    limit = max(7, min(limit, 365))

    attendance = _parse_float(student.get("attendance"))
    study_hours = _parse_float(student.get("study_hours"))
    sleep_hours = _parse_float(student.get("sleep_hours"))

    xai = _xai_impacts(study_hours, sleep_hours, attendance)
    risk = _risk_score(attendance, study_hours, sleep_hours, _parse_float(xai["predicted_marks"]))

    cursor.execute(
        """
        SELECT created_at, attendance, study_hours, sleep_hours, predicted_marks
        FROM student_metrics_history
        WHERE student_id=?
        ORDER BY id DESC
        LIMIT ?
        """,
        (id, limit),
    )
    metrics_history = [row_to_dict(r) for r in cursor.fetchall()]

    cursor.execute(
        """
        SELECT date, status, notes, created_at
        FROM attendance
        WHERE student_id=?
        ORDER BY date DESC
        LIMIT ?
        """,
        (id, limit),
    )
    attendance_history = [row_to_dict(r) for r in cursor.fetchall()]

    cursor.close()
    conn.close()

    payload = {
        "student": student,
        "xai": xai,
        "risk": risk,
        "metrics_history": list(reversed(metrics_history)),
        "attendance_history": list(reversed(attendance_history)),
    }
    _cache_set(cache_key, payload, ttl_seconds=20)
    return jsonify(payload), 200

@app.route('/students/me/profile', methods=['GET'])
@token_required
def my_student_profile(current_user):
    if current_user.get("role") != "student":
        return jsonify({"message": "Unauthorized!"}), 403
    student_id = _get_linked_student_id(int(current_user["id"]))
    if not student_id:
        return jsonify({"message": "Student account not linked. Ask admin to link your user to a student record."}), 409
    # Reuse profile logic by calling the existing function implementation.
    return student_profile(current_user, int(student_id))

@app.route('/performance/me', methods=['GET'])
@token_required
def my_performance_breakdown(current_user):
    if current_user.get("role") != "student":
        return jsonify({"message": "Unauthorized!"}), 403
    student_id = _get_linked_student_id(int(current_user["id"]))
    if not student_id:
        return jsonify({"message": "Student account not linked"}), 409

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT attendance, study_hours, sleep_hours, name FROM students WHERE id=?", (student_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    if not row:
        return jsonify({"message": "Student not found"}), 404

    attendance = _parse_float(row[0])
    study_hours = _parse_float(row[1])
    sleep_hours = _parse_float(row[2])
    xai = _xai_impacts(study_hours, sleep_hours, attendance)
    risk = _risk_score(attendance, study_hours, sleep_hours, _parse_float(xai["predicted_marks"]))

    # Focus score (higher is better) - simple practical heuristic.
    focus = max(0, min(100, int(
        (attendance * 0.45) +
        (min(study_hours, 6) / 6 * 30) +
        (min(max(sleep_hours, 0), 8) / 8 * 25)
    )))

    return jsonify({
        "student_name": row[3],
        "predicted_marks": xai["predicted_marks"],
        "risk": risk,
        "focus_score": focus,
        "impacts": xai["impacts"],
    }), 200

@app.route('/recommendations/me', methods=['GET'])
@token_required
def my_recommendations(current_user):
    if current_user.get("role") != "student":
        return jsonify({"message": "Unauthorized!"}), 403
    student_id = _get_linked_student_id(int(current_user["id"]))
    if not student_id:
        return jsonify({"message": "Student account not linked"}), 409

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT s.name, s.attendance, s.study_hours, s.sleep_hours, d.stream, d.name as dept_name
        FROM students s
        LEFT JOIN departments_master d ON d.id = s.department_id
        WHERE s.id=?
    """, (student_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    if not row:
        return jsonify({"message": "Student not found"}), 404

    name, attendance, study_hours, sleep_hours, stream, dept_name = \
        row[0], _parse_float(row[1]), _parse_float(row[2]), _parse_float(row[3]), row[4], row[5]
    predicted = float(predict_marks(study_hours, sleep_hours, attendance))
    tips: List[str] = []

    # General Tips
    if attendance < 75:
        tips.append("Your attendance is below 75%. Attend upcoming classes to avoid risk.")
    if study_hours < 2.5:
        tips.append("Study 2 more hours daily this week to improve your predicted marks.")
    
    # Stream-Specific Tips
    if stream == 'engineering':
        tips.append(f"Focus on your core {dept_name} subjects like Python and Data Structures.")
        tips.append("Practice coding daily on platforms like LeetCode or GitHub.")
    elif stream == 'medical':
        tips.append(f"Revise Human Anatomy and Physiology diagrams regularly.")
        tips.append("Watch surgery simulation videos in the Learning Center.")
    elif stream == 'commerce':
        tips.append(f"Analyze latest market trends for your {dept_name} assignments.")
        tips.append("Review Financial Accounting principles for upcoming quizzes.")

    if predicted < 85:
        improved = float(predict_marks(study_hours + 2, max(sleep_hours, 6), max(attendance, 80)))
        tips.append(f"By increasing study time, you can reach {improved:.0f} predicted marks.")
    
    tips.append("Visit the 'Learning Center' to explore new study materials.")

    return jsonify({
        "student_name": name, 
        "stream": stream,
        "dept_name": dept_name,
        "predicted_marks": round(predicted, 2), 
        "recommendations": tips[:6]
    }), 200

@app.route('/weekly-report/me', methods=['GET'])
@token_required
def my_weekly_report(current_user):
    if current_user.get("role") != "student":
        return jsonify({"message": "Unauthorized!"}), 403
    student_id = _get_linked_student_id(int(current_user["id"]))
    if not student_id:
        return jsonify({"message": "Student account not linked"}), 409

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            AVG(attendance) as att_avg,
            AVG(study_hours) as study_avg,
            AVG(sleep_hours) as sleep_avg,
            AVG(predicted_marks) as pred_avg
        FROM student_metrics_history
        WHERE student_id=? AND created_at >= datetime('now', '-7 day')
        """,
        (student_id,),
    )
    current = row_to_dict(cursor.fetchone())
    cursor.execute(
        """
        SELECT
            AVG(attendance) as att_avg,
            AVG(study_hours) as study_avg,
            AVG(sleep_hours) as sleep_avg,
            AVG(predicted_marks) as pred_avg
        FROM student_metrics_history
        WHERE student_id=? AND created_at >= datetime('now', '-14 day')
          AND created_at < datetime('now', '-7 day')
        """,
        (student_id,),
    )
    previous = row_to_dict(cursor.fetchone())
    cursor.close()
    conn.close()

    def _v(d, key):
        return round(float((d or {}).get(key) or 0), 2)

    current_vals = {
        "attendance_avg": _v(current, "att_avg"),
        "study_hours_avg": _v(current, "study_avg"),
        "sleep_hours_avg": _v(current, "sleep_avg"),
        "predicted_marks_avg": _v(current, "pred_avg"),
    }
    prev_vals = {
        "attendance_avg": _v(previous, "att_avg"),
        "study_hours_avg": _v(previous, "study_avg"),
        "sleep_hours_avg": _v(previous, "sleep_avg"),
        "predicted_marks_avg": _v(previous, "pred_avg"),
    }
    trend = {
        k: round(current_vals[k] - prev_vals[k], 2) for k in current_vals.keys()
    }
    return jsonify({"current_week": current_vals, "previous_week": prev_vals, "trend": trend}), 200

@app.route('/improvement/me', methods=['GET'])
@token_required
def my_improvement_tracker(current_user):
    if current_user.get("role") != "student":
        return jsonify({"message": "Unauthorized!"}), 403
    student_id = _get_linked_student_id(int(current_user["id"]))
    if not student_id:
        return jsonify({"message": "Student account not linked"}), 409

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT AVG(predicted_marks) FROM student_metrics_history
        WHERE student_id=? AND created_at >= datetime('now', '-7 day')
        """,
        (student_id,),
    )
    curr = float(cursor.fetchone()[0] or 0)
    cursor.execute(
        """
        SELECT AVG(predicted_marks) FROM student_metrics_history
        WHERE student_id=? AND created_at >= datetime('now', '-14 day')
          AND created_at < datetime('now', '-7 day')
        """,
        (student_id,),
    )
    prev = float(cursor.fetchone()[0] or 0)
    cursor.close()
    conn.close()

    delta = round(curr - prev, 2)
    pct = round((delta / prev) * 100, 2) if prev > 0 else 0
    return jsonify({
        "current_predicted_marks_avg": round(curr, 2),
        "previous_predicted_marks_avg": round(prev, 2),
        "delta_marks": delta,
        "delta_percent": pct,
        "trend": "improving" if delta > 0 else ("declining" if delta < 0 else "stable"),
    }), 200

@app.route('/attendance/alerts/me', methods=['GET'])
@token_required
def my_attendance_alerts(current_user):
    if current_user.get("role") != "student":
        return jsonify({"message": "Unauthorized!"}), 403
    student_id = _get_linked_student_id(int(current_user["id"]))
    if not student_id:
        return jsonify({"message": "Student account not linked"}), 409

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT COUNT(*) FROM attendance
        WHERE student_id=? AND status='absent' AND date >= date('now', '-7 day')
        """,
        (student_id,),
    )
    absences_week = int(cursor.fetchone()[0] or 0)
    cursor.execute("SELECT attendance FROM students WHERE id=?", (student_id,))
    attendance_pct = _parse_float((cursor.fetchone() or [0])[0], 0)
    cursor.close()
    conn.close()

    alerts = []
    if absences_week >= 3:
        alerts.append(f"You missed {absences_week} classes this week.")
    if attendance_pct < 75:
        alerts.append(f"Your attendance is {attendance_pct:.0f}% (below 75%).")
    if not alerts:
        alerts.append("Great! No attendance alerts this week.")
    return jsonify({"alerts": alerts, "absences_this_week": absences_week, "attendance_pct": attendance_pct}), 200

@app.route('/attendance/reasons/summary', methods=['GET'])
@token_required
def attendance_reason_summary(current_user):
    if current_user.get("role") not in ["admin", "faculty"]:
        return jsonify({"message": "Unauthorized!"}), 403
    days = max(7, min(90, _parse_int(request.args.get("days"), 30)))
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT COALESCE(reason, '') as reason, COUNT(*) as count
        FROM attendance
        WHERE status='absent' AND date >= date('now', ?)
        GROUP BY COALESCE(reason, '')
        ORDER BY count DESC
        """,
        (f"-{days} day",),
    )
    rows = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"days": days, "items": rows}), 200

@app.route('/effort-analysis/me', methods=['GET'])
@token_required
def effort_analysis_me(current_user):
    if current_user.get("role") != "student":
        return jsonify({"message": "Unauthorized!"}), 403
    student_id = _get_linked_student_id(int(current_user["id"]))
    if not student_id:
        return jsonify({"message": "Student account not linked"}), 409

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT attendance, study_hours, sleep_hours FROM students WHERE id=?", (student_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    if not row:
        return jsonify({"message": "Student not found"}), 404

    attendance = _parse_float(row[0])
    study_hours = _parse_float(row[1])
    sleep_hours = _parse_float(row[2])
    predicted = float(predict_marks(study_hours, sleep_hours, attendance))

    effort_score = (attendance * 0.5) + (min(study_hours, 6) / 6 * 50)
    if effort_score >= 70 and predicted < 65:
        insight = "High effort but low marks -> you may need a better study strategy."
    elif effort_score < 55 and predicted >= 75:
        insight = "Low effort but good marks -> learning may be inconsistent; build routine."
    else:
        insight = "Effort and predicted outcomes are aligned. Maintain consistency."

    return jsonify({
        "attendance": attendance,
        "study_hours": study_hours,
        "sleep_hours": sleep_hours,
        "predicted_marks": round(predicted, 2),
        "effort_score": round(effort_score, 2),
        "insight": insight,
    }), 200

@app.route('/effort-analysis/class', methods=['GET'])
@token_required
def effort_analysis_class(current_user):
    if current_user.get("role") not in ["admin", "faculty"]:
        return jsonify({"message": "Unauthorized!"}), 403
    limit = max(5, min(100, _parse_int(request.args.get("limit"), 30)))
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, attendance, study_hours, sleep_hours FROM students ORDER BY id DESC LIMIT ?", (limit,))
    rows = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()

    items = []
    for s in rows:
        attendance = _parse_float(s.get("attendance"))
        study_hours = _parse_float(s.get("study_hours"))
        sleep_hours = _parse_float(s.get("sleep_hours"))
        predicted = float(predict_marks(study_hours, sleep_hours, attendance))
        effort_score = (attendance * 0.5) + (min(study_hours, 6) / 6 * 50)
        if effort_score >= 70 and predicted < 65:
            tag = "high_effort_low_result"
        elif effort_score < 55 and predicted >= 75:
            tag = "low_effort_high_result"
        else:
            tag = "aligned"
        items.append({
            "id": s.get("id"),
            "name": s.get("name"),
            "effort_score": round(effort_score, 2),
            "predicted_marks": round(predicted, 2),
            "tag": tag,
        })
    return jsonify({"count": len(items), "items": items}), 200

@app.route('/study-time/me', methods=['GET', 'POST'])
@token_required
def my_study_time(current_user):
    if current_user.get("role") != "student":
        return jsonify({"message": "Unauthorized!"}), 403
    student_id = _get_linked_student_id(int(current_user["id"]))
    if not student_id:
        return jsonify({"message": "Student account not linked"}), 409

    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'POST':
        data = request.get_json() or {}
        minutes = _parse_int(data.get("study_minutes"), 0)
        if minutes <= 0 or minutes > 1440:
            cursor.close()
            conn.close()
            return jsonify({"message": "study_minutes must be 1-1440"}), 400
        cursor.execute(
            "INSERT INTO study_time_logs (student_id, study_minutes) VALUES (?, ?)",
            (student_id, minutes),
        )
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"message": "Study time logged"}), 201

    cursor.execute(
        """
        SELECT date(logged_at) as day, SUM(study_minutes) as minutes
        FROM study_time_logs
        WHERE student_id=? AND logged_at >= datetime('now', '-14 day')
        GROUP BY date(logged_at)
        ORDER BY day ASC
        """,
        (student_id,),
    )
    rows = [row_to_dict(r) for r in cursor.fetchall()]
    week_minutes = sum(int(r.get("minutes") or 0) for r in rows if r.get("day"))
    cursor.close()
    conn.close()
    return jsonify({"items": rows, "last_14_days_total_minutes": week_minutes}), 200

@app.route('/study-planner/me', methods=['GET', 'POST'])
@token_required
def my_study_planner(current_user):
    if current_user.get("role") != "student":
        return jsonify({"message": "Unauthorized!"}), 403
    student_id = _get_linked_student_id(int(current_user["id"]))
    if not student_id:
        return jsonify({"message": "Student account not linked"}), 409

    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'POST':
        data = request.get_json() or {}
        exam_date = str(data.get("exam_date") or "").strip()
        available_hours = _parse_float(data.get("available_hours"), 0.0)
        weak_subjects_raw = data.get("weak_subjects") or []
        if isinstance(weak_subjects_raw, str):
            weak_subjects = [x.strip() for x in weak_subjects_raw.split(",") if x.strip()]
        elif isinstance(weak_subjects_raw, list):
            weak_subjects = [str(x).strip() for x in weak_subjects_raw if str(x).strip()]
        else:
            weak_subjects = []

        if not exam_date or len(exam_date) > 32:
            cursor.close()
            conn.close()
            return jsonify({"message": "Invalid exam_date"}), 400
        if available_hours <= 0 or available_hours > 16:
            cursor.close()
            conn.close()
            return jsonify({"message": "available_hours must be between 0 and 16"}), 400
        if not weak_subjects:
            cursor.close()
            conn.close()
            return jsonify({"message": "At least one weak subject is required"}), 400

        try:
            exam_dt = datetime.strptime(exam_date[:10], "%Y-%m-%d").date()
        except Exception:
            cursor.close()
            conn.close()
            return jsonify({"message": "exam_date must be YYYY-MM-DD"}), 400

        today = datetime.utcnow().date()
        days_until_exam = max(1, (exam_dt - today).days)
        horizon = min(14, max(3, days_until_exam))
        schedule: List[Dict[str, Any]] = []
        subjects_count = len(weak_subjects)
        for i in range(horizon):
            d = today + timedelta(days=i)
            focus_subject = weak_subjects[i % subjects_count]
            revision_subject = weak_subjects[(i + 1) % subjects_count]
            schedule.append({
                "day": d.isoformat(),
                "focus_subject": focus_subject,
                "tasks": [
                    f"{round(available_hours * 0.5, 1)}h concept revision for {focus_subject}",
                    f"{round(available_hours * 0.3, 1)}h practice questions ({focus_subject})",
                    f"{round(available_hours * 0.2, 1)}h recap + short quiz ({revision_subject})",
                ],
            })

        cursor.execute(
            """
            INSERT INTO ai_study_plans (student_id, exam_date, weak_subjects, available_hours, schedule_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                student_id,
                exam_date,
                ", ".join(weak_subjects),
                float(available_hours),
                json.dumps(schedule),
            ),
        )
        plan_id = cursor.lastrowid
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({
            "message": "AI study plan generated",
            "plan_id": plan_id,
            "exam_date": exam_date,
            "weak_subjects": weak_subjects,
            "available_hours": available_hours,
            "schedule": schedule,
        }), 201

    cursor.execute(
        """
        SELECT id, exam_date, weak_subjects, available_hours, schedule_json, created_at
        FROM ai_study_plans
        WHERE student_id=?
        ORDER BY id DESC
        LIMIT 1
        """,
        (student_id,),
    )
    plan = row_to_dict(cursor.fetchone())
    cursor.close()
    conn.close()
    if not plan:
        return jsonify({"message": "No study plan generated yet"}), 404
    try:
        parsed_schedule = json.loads(plan.get("schedule_json") or "[]")
    except Exception:
        parsed_schedule = []
    return jsonify({
        "id": plan.get("id"),
        "exam_date": plan.get("exam_date"),
        "weak_subjects": [x.strip() for x in str(plan.get("weak_subjects") or "").split(",") if x.strip()],
        "available_hours": plan.get("available_hours"),
        "schedule": parsed_schedule,
        "created_at": plan.get("created_at"),
    }), 200

@app.route('/learning/resources', methods=['GET', 'POST'])
@token_required
def learning_resources(current_user):
    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'POST':
        if current_user.get("role") not in ["admin", "faculty"]:
            cursor.close()
            conn.close()
            return jsonify({"message": "Unauthorized!"}), 403
        data = request.get_json() or {}
        subject = str(data.get("subject") or "").strip()
        title = str(data.get("title") or "").strip()
        resource_type = str(data.get("resource_type") or "link").strip().lower()
        content_url = str(data.get("content_url") or "").strip()
        description = str(data.get("description") or "").strip()
        if len(subject) < 2 or len(subject) > 100:
            cursor.close()
            conn.close()
            return jsonify({"message": "Invalid subject"}), 400
        if len(title) < 3 or len(title) > 200:
            cursor.close()
            conn.close()
            return jsonify({"message": "Invalid title"}), 400
        if resource_type not in ["note", "video", "assignment", "link"]:
            cursor.close()
            conn.close()
            return jsonify({"message": "Invalid resource_type"}), 400
        if len(content_url) < 3 or len(content_url) > 500:
            cursor.close()
            conn.close()
            return jsonify({"message": "Invalid content_url"}), 400
        if len(description) > 1000:
            cursor.close()
            conn.close()
            return jsonify({"message": "Description too long"}), 400
        cursor.execute(
            """
            INSERT INTO learning_resources (subject, title, resource_type, content_url, description, created_by)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (subject, title, resource_type, content_url, description, _parse_int(current_user.get("id"), 0)),
        )
        rid = cursor.lastrowid
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"message": "Resource added", "id": rid}), 201

    subject_filter = str(request.args.get("subject") or "").strip()
    limit = max(1, min(300, _parse_int(request.args.get("limit"), 100)))
    sql = "SELECT * FROM learning_resources WHERE 1=1"
    params: List[Any] = []
    if subject_filter:
        sql += " AND subject LIKE ?"
        params.append(f"%{subject_filter}%")
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    cursor.execute(sql, params)
    items = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"count": len(items), "items": items}), 200

@app.route('/learning/progress/me', methods=['GET', 'POST'])
@token_required
def my_learning_progress(current_user):
    if current_user.get("role") != "student":
        return jsonify({"message": "Unauthorized!"}), 403
    student_id = _get_linked_student_id(int(current_user["id"]))
    if not student_id:
        return jsonify({"message": "Student account not linked"}), 409

    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'POST':
        data = request.get_json() or {}
        resource_id = _parse_int(data.get("resource_id"), 0)
        progress_pct = _parse_float(data.get("progress_pct"), -1)
        if resource_id <= 0:
            cursor.close()
            conn.close()
            return jsonify({"message": "Invalid resource_id"}), 400
        if progress_pct < 0 or progress_pct > 100:
            cursor.close()
            conn.close()
            return jsonify({"message": "progress_pct must be 0-100"}), 400
        cursor.execute("SELECT id FROM learning_resources WHERE id=?", (resource_id,))
        if not cursor.fetchone():
            cursor.close()
            conn.close()
            return jsonify({"message": "Resource not found"}), 404
        cursor.execute(
            """
            INSERT INTO student_learning_progress (student_id, resource_id, progress_pct)
            VALUES (?, ?, ?)
            ON CONFLICT(student_id, resource_id)
            DO UPDATE SET progress_pct=excluded.progress_pct, updated_at=CURRENT_TIMESTAMP
            """,
            (student_id, resource_id, progress_pct),
        )
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"message": "Progress updated"}), 200

    cursor.execute(
        """
        SELECT r.id, r.subject, r.title, r.resource_type, r.content_url, r.description,
               COALESCE(p.progress_pct, 0) as progress_pct
        FROM learning_resources r
        LEFT JOIN student_learning_progress p
          ON p.resource_id=r.id AND p.student_id=?
        ORDER BY r.subject ASC, r.id DESC
        LIMIT 300
        """,
        (student_id,),
    )
    items = [row_to_dict(r) for r in cursor.fetchall()]
    overall_progress = round(sum(_parse_float(i.get("progress_pct"), 0) for i in items) / len(items), 2) if items else 0.0
    cursor.close()
    conn.close()
    return jsonify({"count": len(items), "overall_progress": overall_progress, "items": items}), 200

@app.route('/goals/me', methods=['GET', 'POST'])
@token_required
def my_goals(current_user):
    if current_user.get("role") != "student":
        return jsonify({"message": "Unauthorized!"}), 403
    student_id = _get_linked_student_id(int(current_user["id"]))
    if not student_id:
        return jsonify({"message": "Student account not linked"}), 409

    conn = get_db_connection()
    cursor = conn.cursor()
    if request.method == 'POST':
        data = request.get_json() or {}
        target_cgpa = _parse_float(data.get("target_cgpa"), -1)
        attendance_goal = _parse_float(data.get("attendance_goal"), -1)
        study_hours_goal = _parse_float(data.get("study_hours_goal"), -1)
        if target_cgpa <= 0 or target_cgpa > 10:
            cursor.close()
            conn.close()
            return jsonify({"message": "target_cgpa must be 0-10"}), 400
        if attendance_goal < 0 or attendance_goal > 100:
            cursor.close()
            conn.close()
            return jsonify({"message": "attendance_goal must be 0-100"}), 400
        if study_hours_goal < 0 or study_hours_goal > 24:
            cursor.close()
            conn.close()
            return jsonify({"message": "study_hours_goal must be 0-24"}), 400
        cursor.execute(
            """
            INSERT INTO student_goals (student_id, target_cgpa, attendance_goal, study_hours_goal)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(student_id)
            DO UPDATE SET
                target_cgpa=excluded.target_cgpa,
                attendance_goal=excluded.attendance_goal,
                study_hours_goal=excluded.study_hours_goal,
                updated_at=CURRENT_TIMESTAMP
            """,
            (student_id, target_cgpa, attendance_goal, study_hours_goal),
        )
        conn.commit()

    cursor.execute(
        "SELECT attendance, study_hours FROM students WHERE id=?",
        (student_id,),
    )
    s = row_to_dict(cursor.fetchone())
    current_attendance = _parse_float((s or {}).get("attendance"), 0.0)
    current_study_hours = _parse_float((s or {}).get("study_hours"), 0.0)
    predicted_marks = float(predict_marks(current_study_hours, 7.0, current_attendance))
    estimated_cgpa = round((predicted_marks / 100.0) * 10.0, 2)

    cursor.execute(
        """
        SELECT target_cgpa, attendance_goal, study_hours_goal, updated_at
        FROM student_goals
        WHERE student_id=?
        """,
        (student_id,),
    )
    goal = row_to_dict(cursor.fetchone())
    cursor.close()
    conn.close()
    if not goal:
        return jsonify({"message": "No goals set yet"}), 404

    cgpa_progress = round(min(100.0, (estimated_cgpa / max(_parse_float(goal.get("target_cgpa"), 1), 0.1)) * 100.0), 2)
    attendance_progress = round(min(100.0, (current_attendance / max(_parse_float(goal.get("attendance_goal"), 1), 0.1)) * 100.0), 2)
    study_progress = round(min(100.0, (current_study_hours / max(_parse_float(goal.get("study_hours_goal"), 1), 0.1)) * 100.0), 2)
    return jsonify({
        "goal": goal,
        "current": {
            "estimated_cgpa": estimated_cgpa,
            "attendance": round(current_attendance, 2),
            "study_hours": round(current_study_hours, 2),
        },
        "progress": {
            "cgpa": cgpa_progress,
            "attendance": attendance_progress,
            "study_hours": study_progress,
        },
    }), 200

@app.route('/students/link', methods=['POST'])
@token_required
def link_student_user(current_user):
    """
    Admin/faculty links a user (role=student) to a students row.
    Body: { user_id, student_id }
    """
    if current_user.get("role") not in ["admin", "faculty"]:
        return jsonify({"message": "Unauthorized!"}), 403

    data = request.get_json() or {}
    user_id = _parse_int(data.get("user_id"), 0)
    student_id = _parse_int(data.get("student_id"), 0)
    if user_id <= 0 or student_id <= 0:
        return jsonify({"message": "user_id and student_id required"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, role FROM users WHERE id=?", (user_id,))
    u = cursor.fetchone()
    if not u or u[1] != "student":
        cursor.close()
        conn.close()
        return jsonify({"message": "user_id must exist and be a student user"}), 400

    cursor.execute("SELECT id FROM students WHERE id=?", (student_id,))
    s = cursor.fetchone()
    if not s:
        cursor.close()
        conn.close()
        return jsonify({"message": "student_id not found"}), 404

    cursor.execute(
        """
        INSERT INTO student_user_links (user_id, student_id)
        VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET student_id=excluded.student_id
        """,
        (user_id, student_id),
    )
    conn.commit()
    cursor.close()
    conn.close()
    _cache_invalidate("student_profile:")
    return jsonify({"message": "Linked successfully"}), 200

@app.route('/alerts', methods=['GET'])
@token_required
def list_alerts(current_user):
    if current_user.get("role") not in ["admin", "faculty"]:
        return jsonify({"message": "Unauthorized!"}), 403

    limit = max(1, min(200, _parse_int(request.args.get("limit"), 50)))
    only_open = request.args.get("open", "1")  # default only open
    cache_key = f"alerts:{only_open}:{limit}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return jsonify(cached), 200

    conn = get_db_connection()
    cursor = conn.cursor()
    if only_open == "1":
        cursor.execute(
            """
            SELECT a.*, s.name as student_name
            FROM alerts a
            JOIN students s ON s.id=a.student_id
            WHERE a.resolved_at IS NULL
            ORDER BY a.id DESC
            LIMIT ?
            """,
            (limit,),
        )
    else:
        cursor.execute(
            """
            SELECT a.*, s.name as student_name
            FROM alerts a
            JOIN students s ON s.id=a.student_id
            ORDER BY a.id DESC
            LIMIT ?
            """,
            (limit,),
        )

    rows = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    payload = {"count": len(rows), "items": rows}
    _cache_set(cache_key, payload, ttl_seconds=10)
    return jsonify(payload), 200

@app.route('/students/<int:student_id>/academic-audit', methods=['GET'])
@token_required
def academic_audit_report(current_user, student_id):
    if current_user.get("role") not in ["admin", "faculty", "student"]:
        return jsonify({"message": "Unauthorized!"}), 403
    if current_user.get("role") == "student":
        linked = _get_linked_student_id(int(current_user["id"]))
        if linked != student_id:
            return jsonify({"message": "Unauthorized!"}), 403

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, attendance, study_hours, sleep_hours FROM students WHERE id=?", (student_id,))
    s = row_to_dict(cursor.fetchone())
    if not s:
        cursor.close()
        conn.close()
        return jsonify({"message": "Student not found"}), 404

    attendance = _parse_float(s.get("attendance"))
    study_hours = _parse_float(s.get("study_hours"))
    sleep_hours = _parse_float(s.get("sleep_hours"))
    predicted = float(predict_marks(study_hours, sleep_hours, attendance))
    risk = _risk_score(attendance, study_hours, sleep_hours, predicted)

    cursor.execute(
        """
        SELECT AVG(predicted_marks) as current_avg
        FROM student_metrics_history
        WHERE student_id=? AND created_at >= datetime('now', '-7 day')
        """,
        (student_id,),
    )
    current_avg = _parse_float((row_to_dict(cursor.fetchone()) or {}).get("current_avg"), 0)
    cursor.execute(
        """
        SELECT AVG(predicted_marks) as previous_avg
        FROM student_metrics_history
        WHERE student_id=? AND created_at >= datetime('now', '-14 day')
          AND created_at < datetime('now', '-7 day')
        """,
        (student_id,),
    )
    previous_avg = _parse_float((row_to_dict(cursor.fetchone()) or {}).get("previous_avg"), 0)

    cursor.execute(
        """
        SELECT remark, created_at FROM faculty_remarks
        WHERE student_id=?
        ORDER BY id DESC LIMIT 5
        """,
        (student_id,),
    )
    remarks = [row_to_dict(r) for r in cursor.fetchall()]

    cursor.close()
    conn.close()

    return jsonify({
        "student": s,
        "attendance_summary": {
            "attendance_pct": attendance,
            "study_hours": study_hours,
            "sleep_hours": sleep_hours,
        },
        "performance_trend": {
            "current_week_predicted_avg": round(current_avg, 2),
            "previous_week_predicted_avg": round(previous_avg, 2),
            "delta": round(current_avg - previous_avg, 2),
        },
        "risk_level": risk,
        "faculty_remarks": remarks,
    }), 200

@app.route('/students/<int:student_id>/remarks', methods=['POST'])
@token_required
def add_faculty_remark(current_user, student_id):
    if current_user.get("role") not in ["admin", "faculty"]:
        return jsonify({"message": "Unauthorized!"}), 403
    data = request.get_json() or {}
    remark = str(data.get("remark") or "").strip()
    if len(remark) < 3 or len(remark) > 2000:
        return jsonify({"message": "Invalid remark"}), 400
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM students WHERE id=?", (student_id,))
    if not cursor.fetchone():
        cursor.close()
        conn.close()
        return jsonify({"message": "Student not found"}), 404
    cursor.execute(
        "INSERT INTO faculty_remarks (student_id, faculty_user_id, remark) VALUES (?, ?, ?)",
        (student_id, _parse_int(current_user.get("id"), 0), remark),
    )
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"message": "Remark added"}), 201

@app.route('/interventions', methods=['GET'])
@token_required
def interventions_list(current_user):
    if current_user.get("role") not in ["admin", "faculty"]:
        return jsonify({"message": "Unauthorized!"}), 403
    status = request.args.get("status", "open")
    limit = max(1, min(200, _parse_int(request.args.get("limit"), 50)))
    conn = get_db_connection()
    cursor = conn.cursor()
    if status in ["open", "in_progress", "closed"]:
        cursor.execute(
            """
            SELECT i.*, s.name as student_name
            FROM interventions i
            JOIN students s ON s.id=i.student_id
            WHERE i.status=?
            ORDER BY i.id DESC LIMIT ?
            """,
            (status, limit),
        )
    else:
        cursor.execute(
            """
            SELECT i.*, s.name as student_name
            FROM interventions i
            JOIN students s ON s.id=i.student_id
            ORDER BY i.id DESC LIMIT ?
            """,
            (limit,),
        )
    rows = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"count": len(rows), "items": rows}), 200

@app.route('/intelligent-alerts', methods=['GET'])
@token_required
def intelligent_alerts(current_user):
    role = current_user.get("role")
    if role not in ["admin", "faculty", "student", "parent"]:
        return jsonify({"message": "Unauthorized!"}), 403

    status = request.args.get("status", "open")  # open|all
    limit = max(1, min(300, _parse_int(request.args.get("limit"), 100)))
    conn = get_db_connection()
    cursor = conn.cursor()

    if role in ["admin", "faculty"]:
        recipient_role = request.args.get("recipient_role", "").strip()
        sql = """
            SELECT ia.*, s.name as student_name
            FROM intelligent_alerts ia
            JOIN students s ON s.id=ia.student_id
            WHERE 1=1
        """
        params: List[Any] = []
        if status == "open":
            sql += " AND ia.resolved_at IS NULL"
        if recipient_role in ["student", "parent", "faculty", "admin"]:
            sql += " AND ia.recipient_role=?"
            params.append(recipient_role)
        sql += " ORDER BY ia.id DESC LIMIT ?"
        params.append(limit)
        cursor.execute(sql, params)
    elif role == "student":
        student_id = _get_linked_student_id(_parse_int(current_user.get("id"), 0))
        if not student_id:
            cursor.close()
            conn.close()
            return jsonify({"message": "Student account not linked"}), 409
        sql = """
            SELECT ia.*, s.name as student_name
            FROM intelligent_alerts ia
            JOIN students s ON s.id=ia.student_id
            WHERE ia.student_id=? AND ia.recipient_role='student'
        """
        params = [student_id]
        if status == "open":
            sql += " AND ia.resolved_at IS NULL"
        sql += " ORDER BY ia.id DESC LIMIT ?"
        params.append(limit)
        cursor.execute(sql, params)
    else:  # parent
        parent_id = _parse_int(current_user.get("id"), 0)
        sql = """
            SELECT ia.*, s.name as student_name
            FROM intelligent_alerts ia
            JOIN students s ON s.id=ia.student_id
            WHERE ia.recipient_role='parent' AND ia.recipient_id=?
        """
        params = [parent_id]
        if status == "open":
            sql += " AND ia.resolved_at IS NULL"
        sql += " ORDER BY ia.id DESC LIMIT ?"
        params.append(limit)
        cursor.execute(sql, params)

    rows = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"count": len(rows), "items": rows}), 200

@app.route('/notifications/me', methods=['GET'])
@token_required
def my_notifications(current_user):
    role = current_user.get("role")
    if role not in ["admin", "faculty", "student", "parent"]:
        return jsonify({"message": "Unauthorized!"}), 403

    limit = max(1, min(200, _parse_int(request.args.get("limit"), 30)))
    only_unread = str(request.args.get("unread") or "0") == "1"
    category = str(request.args.get("category") or "").strip().lower()
    only_today = str(request.args.get("today") or "0") == "1"
    user_id = _parse_int(current_user.get("id"), 0)

    conn = get_db_connection()
    cursor = conn.cursor()
    sql = "SELECT * FROM notifications WHERE recipient_role=? AND (recipient_id IS NULL OR recipient_id=?)"
    params: List[Any] = [role, user_id]
    if only_unread:
        sql += " AND is_read=0"
    if category:
        sql += " AND category=?"
        params.append(category)
    if only_today:
        sql += " AND date(created_at)=date('now')"
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    cursor.execute(sql, params)
    items = [row_to_dict(r) for r in cursor.fetchall()]

    # Global unread count for current role/user (ignores limit/filter widgets).
    cursor.execute(
        """
        SELECT COUNT(*) FROM notifications
        WHERE recipient_role=? AND (recipient_id IS NULL OR recipient_id=?) AND is_read=0
        """,
        (role, user_id),
    )
    unread_count = _parse_int(cursor.fetchone()[0], 0)

    categories = sorted({str((x.get("category") or "general")).strip().lower() for x in items})
    cursor.close()
    conn.close()
    return jsonify({"count": len(items), "unread_count": unread_count, "categories": categories, "items": items}), 200

@app.route('/notifications/mark-read', methods=['POST'])
@token_required
def mark_notifications_read(current_user):
    role = current_user.get("role")
    if role not in ["admin", "faculty", "student", "parent"]:
        return jsonify({"message": "Unauthorized!"}), 403
    user_id = _parse_int(current_user.get("id"), 0)
    data = request.get_json() or {}
    notification_id = _parse_int(data.get("id"), 0)
    mark_all = bool(data.get("all"))

    conn = get_db_connection()
    cursor = conn.cursor()
    if mark_all:
        cursor.execute(
            """
            UPDATE notifications
            SET is_read=1
            WHERE recipient_role=? AND (recipient_id IS NULL OR recipient_id=?)
            """,
            (role, user_id),
        )
    else:
        if notification_id <= 0:
            cursor.close()
            conn.close()
            return jsonify({"message": "id is required when all=false"}), 400
        cursor.execute(
            """
            UPDATE notifications
            SET is_read=1
            WHERE id=? AND recipient_role=? AND (recipient_id IS NULL OR recipient_id=?)
            """,
            (notification_id, role, user_id),
        )
    conn.commit()
    updated = cursor.rowcount
    cursor.close()
    conn.close()
    return jsonify({"message": "Notifications updated", "updated": updated}), 200

@app.route('/messages/send', methods=['POST'])
@token_required
def send_message(current_user):
    role = current_user.get("role")
    if role not in ["admin", "faculty", "student", "parent"]:
        return jsonify({"message": "Unauthorized!"}), 403
    data = request.get_json() or {}
    recipient_role = str(data.get("recipient_role") or "").strip().lower()
    recipient_id = _parse_int(data.get("recipient_id"), 0)
    body = str(data.get("body") or "").strip()
    if recipient_role not in ["admin", "faculty", "student", "parent"]:
        return jsonify({"message": "Invalid recipient_role"}), 400
    if recipient_id <= 0:
        return jsonify({"message": "Invalid recipient_id"}), 400
    if len(body) < 1 or len(body) > 2000:
        return jsonify({"message": "Invalid message body"}), 400

    sender_id = _parse_int(current_user.get("id"), 0)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO messages (sender_role, sender_id, recipient_role, recipient_id, body, is_read)
        VALUES (?, ?, ?, ?, ?, 0)
        """,
        (role, sender_id, recipient_role, recipient_id, body),
    )
    mid = cursor.lastrowid
    conn.commit()
    cursor.close()
    conn.close()

    socketio.emit("message_push", {
        "id": mid,
        "sender_role": role,
        "sender_id": sender_id,
        "recipient_role": recipient_role,
        "recipient_id": recipient_id,
        "body": body,
    })
    return jsonify({"message": "Message sent", "id": mid}), 201

@app.route('/messages/inbox', methods=['GET'])
@token_required
def inbox_messages(current_user):
    role = current_user.get("role")
    if role not in ["admin", "faculty", "student", "parent"]:
        return jsonify({"message": "Unauthorized!"}), 403
    user_id = _parse_int(current_user.get("id"), 0)
    peer_role = str(request.args.get("peer_role") or "").strip().lower()
    peer_id = _parse_int(request.args.get("peer_id"), 0)
    limit = max(1, min(300, _parse_int(request.args.get("limit"), 100)))

    conn = get_db_connection()
    cursor = conn.cursor()
    sql = """
        SELECT *
        FROM messages
        WHERE (
            sender_role=? AND sender_id=?
        ) OR (
            recipient_role=? AND recipient_id=?
        )
    """
    params: List[Any] = [role, user_id, role, user_id]
    if peer_role in ["admin", "faculty", "student", "parent"] and peer_id > 0:
        sql += """
            AND (
                (sender_role=? AND sender_id=?)
                OR
                (recipient_role=? AND recipient_id=?)
            )
        """
        params.extend([peer_role, peer_id, peer_role, peer_id])
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    cursor.execute(sql, params)
    items = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"count": len(items), "items": items}), 200

@app.route('/messages/mark-read', methods=['POST'])
@token_required
def mark_messages_read(current_user):
    role = current_user.get("role")
    if role not in ["admin", "faculty", "student", "parent"]:
        return jsonify({"message": "Unauthorized!"}), 403
    user_id = _parse_int(current_user.get("id"), 0)
    data = request.get_json() or {}
    message_id = _parse_int(data.get("id"), 0)
    if message_id <= 0:
        return jsonify({"message": "id required"}), 400
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE messages
        SET is_read=1
        WHERE id=? AND recipient_role=? AND recipient_id=?
        """,
        (message_id, role, user_id),
    )
    conn.commit()
    updated = cursor.rowcount
    cursor.close()
    conn.close()
    return jsonify({"message": "Messages updated", "updated": updated}), 200

@app.route('/search/global', methods=['GET'])
@token_required
def global_search(current_user):
    role = current_user.get("role")
    if role not in ["admin", "faculty", "student", "parent"]:
        return jsonify({"message": "Unauthorized!"}), 403
    q = str(request.args.get("q") or "").strip()
    if len(q) < 1:
        return jsonify({"message": "q is required"}), 400
    like = f"%{q}%"
    conn = get_db_connection()
    cursor = conn.cursor()

    out: Dict[str, Any] = {}
    cursor.execute("SELECT id, name, attendance FROM students WHERE name LIKE ? ORDER BY id DESC LIMIT 10", (like,))
    out["students"] = [row_to_dict(r) for r in cursor.fetchall()]

    cursor.execute("SELECT id, title, due_date FROM assignments WHERE title LIKE ? ORDER BY id DESC LIMIT 10", (like,))
    out["assignments"] = [row_to_dict(r) for r in cursor.fetchall()]

    cursor.execute("SELECT id, subject, title, resource_type FROM learning_resources WHERE subject LIKE ? OR title LIKE ? ORDER BY id DESC LIMIT 10", (like, like))
    out["resources"] = [row_to_dict(r) for r in cursor.fetchall()]

    cursor.execute("SELECT id, class_name, subject, schedule_time, status FROM class_plans WHERE class_name LIKE ? OR subject LIKE ? ORDER BY id DESC LIMIT 10", (like, like))
    out["class_plans"] = [row_to_dict(r) for r in cursor.fetchall()]

    if role in ["admin", "faculty"]:
        cursor.execute("SELECT id, role, name, mobile FROM users WHERE name LIKE ? OR mobile LIKE ? ORDER BY id DESC LIMIT 10", (like, like))
        out["users"] = [row_to_dict(r) for r in cursor.fetchall()]

    cursor.close()
    conn.close()
    return jsonify(out), 200

@app.route('/audit/logs', methods=['GET'])
@token_required
def audit_logs(current_user):
    if current_user.get("role") != "admin":
        return jsonify({"message": "Unauthorized!"}), 403
    page_size = max(1, min(500, _parse_int(request.args.get("page_size"), _parse_int(request.args.get("limit"), 100))))
    page = max(1, _parse_int(request.args.get("page"), 1))
    offset = max(0, _parse_int(request.args.get("offset"), (page - 1) * page_size))
    method = str(request.args.get("method") or "").strip().upper()
    path_query = str(request.args.get("path") or "").strip()
    actor_role = str(request.args.get("actor_role") or "").strip().lower()
    actor_id = _parse_int(request.args.get("actor_id"), 0)
    status_code = _parse_int(request.args.get("status_code"), 0)
    created_from = str(request.args.get("created_from") or "").strip()
    created_to = str(request.args.get("created_to") or "").strip()
    sort_by = str(request.args.get("sort_by") or "id").strip().lower()
    sort_dir = str(request.args.get("sort_dir") or "desc").strip().lower()
    allowed_sort = {"id", "created_at", "status_code", "method", "path", "actor_role", "actor_id"}
    if sort_by not in allowed_sort:
        sort_by = "id"
    if sort_dir not in ["asc", "desc"]:
        sort_dir = "desc"
    conn = get_db_connection()
    cursor = conn.cursor()
    where_sql = " FROM audit_logs WHERE 1=1"
    params: List[Any] = []
    if method in ["GET", "POST", "PUT", "DELETE"]:
        where_sql += " AND method=?"
        params.append(method)
    if path_query:
        where_sql += " AND path LIKE ?"
        params.append(f"%{path_query}%")
    if actor_role in ["admin", "faculty", "student", "parent", "anonymous"]:
        where_sql += " AND actor_role=?"
        params.append(actor_role)
    if actor_id > 0:
        where_sql += " AND actor_id=?"
        params.append(actor_id)
    if status_code > 0:
        where_sql += " AND status_code=?"
        params.append(status_code)

    if created_from:
        where_sql += " AND datetime(created_at) >= datetime(?)"
        params.append(created_from)
    if created_to:
        where_sql += " AND datetime(created_at) <= datetime(?)"
        params.append(created_to)

    count_sql = "SELECT COUNT(1) AS total" + where_sql
    cursor.execute(count_sql, params)
    total_row = cursor.fetchone()
    total = int(total_row["total"]) if total_row and "total" in total_row.keys() else 0

    sql = f"SELECT * {where_sql} ORDER BY {sort_by} {sort_dir.upper()}, id DESC LIMIT ? OFFSET ?"
    select_params = list(params)
    select_params.extend([page_size, offset])
    cursor.execute(sql, select_params)
    items = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({
        "count": len(items),
        "total": total,
        "page": page,
        "page_size": page_size,
        "offset": offset,
        "sort_by": sort_by,
        "sort_dir": sort_dir,
        "items": items
    }), 200

_MASTER_STREAMS = frozenset({"engineering", "medical", "commerce", "general"})
_MASTER_MATERIAL_TYPES = frozenset({"note", "pdf", "ppt", "video", "link"})


def _master_admin_guard(current_user):
    if current_user.get("role") != "admin":
        return jsonify({"message": "Unauthorized!"}), 403
    return None


def _master_faculty_or_admin_guard(current_user):
    if current_user.get("role") not in ("admin", "faculty"):
        return jsonify({"message": "Unauthorized!"}), 403
    return None


@app.route('/faculty/profiles', methods=['GET'])
def get_faculty_profiles():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT fp.*, u.name as faculty_name, dm.name as department_name 
        FROM faculty_profiles fp
        JOIN users u ON fp.user_id = u.id
        LEFT JOIN departments_master dm ON fp.department_id = dm.id
    """)
    profiles = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"items": profiles}), 200

@app.route('/institutions/detailed', methods=['GET'])
def get_detailed_institutions():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Fetch all institutions
    cursor.execute("SELECT * FROM institutions")
    institutions = [row_to_dict(r) for r in cursor.fetchall()]
    
    for inst in institutions:
        # Fetch departments for each institution
        cursor.execute("SELECT * FROM departments_master WHERE institution_id = ?", (inst['id'],))
        inst['departments'] = [row_to_dict(r) for r in cursor.fetchall()]
        
        for dept in inst['departments']:
            # Fetch some subjects for each department as highlights
            cursor.execute("SELECT name FROM subjects_master WHERE department_id = ? LIMIT 3", (dept['id'],))
            dept['subject_highlights'] = [r['name'] for r in cursor.fetchall()]

    cursor.close()
    conn.close()
    return jsonify({"items": institutions}), 200

@app.route('/master/institutions', methods=['GET', 'POST'])
@token_required
def master_institutions(current_user):
    if request.method != 'GET':
        err = _master_admin_guard(current_user)
        if err:
            return err
    conn = get_db_connection()
    cursor = conn.cursor()
    if request.method == 'GET':
        cursor.execute("SELECT * FROM institutions ORDER BY id DESC")
        items = [row_to_dict(r) for r in cursor.fetchall()]
        cursor.close()
        conn.close()
        return jsonify({"items": items, "count": len(items)}), 200
    data = request.get_json() or {}
    name = str(data.get("name") or "").strip()
    inst_type = str(data.get("type") or "college").strip() or "college"
    image_url = data.get("image_url", "")
    if len(name) < 2 or len(name) > 200:
        cursor.close()
        conn.close()
        return jsonify({"message": "Invalid name"}), 400
    if len(inst_type) > 80:
        cursor.close()
        conn.close()
        return jsonify({"message": "Invalid type"}), 400
    cursor.execute(
        "INSERT INTO institutions (name, type, image_url) VALUES (?, ?, ?)",
        (name, inst_type, image_url),
    )
    new_id = cursor.lastrowid
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"message": "Institution created", "id": new_id}), 201


@app.route('/master/institutions/<int:inst_id>', methods=['PUT', 'DELETE'])
@token_required
def master_institution_item(current_user, inst_id):
    err = _master_admin_guard(current_user)
    if err:
        return err
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM institutions WHERE id=?", (inst_id,))
    if not cursor.fetchone():
        cursor.close()
        conn.close()
        return jsonify({"message": "Institution not found"}), 404
    if request.method == 'DELETE':
        cursor.execute("SELECT COUNT(1) AS c FROM departments_master WHERE institution_id=?", (inst_id,))
        row = cursor.fetchone()
        cnt = int(row["c"]) if row else 0
        if cnt > 0:
            cursor.close()
            conn.close()
            return jsonify({"message": "Cannot delete institution with departments"}), 400
        cursor.execute("SELECT COUNT(1) AS c FROM semesters_master WHERE institution_id=?", (inst_id,))
        row2 = cursor.fetchone()
        cnt2 = int(row2["c"]) if row2 else 0
        if cnt2 > 0:
            cursor.close()
            conn.close()
            return jsonify({"message": "Cannot delete institution with semesters"}), 400
        cursor.execute("DELETE FROM institutions WHERE id=?", (inst_id,))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"message": "Institution deleted"}), 200
    data = request.get_json() or {}
    name = str(data.get("name") or "").strip()
    inst_type = str(data.get("type") or "").strip()
    image_url = data.get("image_url", "")
    if len(name) < 2 or len(name) > 200:
        cursor.close()
        conn.close()
        return jsonify({"message": "Invalid name"}), 400
    if len(inst_type) > 80:
        cursor.close()
        conn.close()
        return jsonify({"message": "Invalid type"}), 400
    cursor.execute(
        "UPDATE institutions SET name=?, type=?, image_url=? WHERE id=?",
        (name, inst_type or "college", image_url, inst_id),
    )
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"message": "Institution updated"}), 200


@app.route('/master/departments', methods=['GET', 'POST'])
@token_required
def master_departments(current_user):
    if request.method != 'GET':
        err = _master_admin_guard(current_user)
        if err:
            return err
    conn = get_db_connection()
    cursor = conn.cursor()
    if request.method == 'GET':
        institution_id = _parse_int(request.args.get("institution_id"), 0)
        stream = str(request.args.get("stream") or "").strip().lower()
        sql = "SELECT * FROM departments_master WHERE 1=1"
        params: List[Any] = []
        if institution_id > 0:
            sql += " AND institution_id=?"
            params.append(institution_id)
        if stream in _MASTER_STREAMS:
            sql += " AND stream=?"
            params.append(stream)
        sql += " ORDER BY id DESC"
        cursor.execute(sql, params)
        items = [row_to_dict(r) for r in cursor.fetchall()]
        cursor.close()
        conn.close()
        return jsonify({"items": items, "count": len(items)}), 200
    data = request.get_json() or {}
    institution_id = _parse_int(data.get("institution_id"), 0)
    name = str(data.get("name") or "").strip()
    stream = str(data.get("stream") or "").strip().lower()
    if institution_id <= 0:
        cursor.close()
        conn.close()
        return jsonify({"message": "Invalid institution_id"}), 400
    if len(name) < 2 or len(name) > 200:
        cursor.close()
        conn.close()
        return jsonify({"message": "Invalid name"}), 400
    if stream not in _MASTER_STREAMS:
        cursor.close()
        conn.close()
        return jsonify({"message": "Invalid stream"}), 400
    cursor.execute("SELECT id FROM institutions WHERE id=?", (institution_id,))
    if not cursor.fetchone():
        cursor.close()
        conn.close()
        return jsonify({"message": "Institution not found"}), 404
    cursor.execute(
        "INSERT INTO departments_master (institution_id, name, stream) VALUES (?, ?, ?)",
        (institution_id, name, stream),
    )
    new_id = cursor.lastrowid
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"message": "Department created", "id": new_id}), 201


@app.route('/master/departments/<int:dept_id>', methods=['PUT', 'DELETE'])
@token_required
def master_department_item(current_user, dept_id):
    err = _master_admin_guard(current_user)
    if err:
        return err
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM departments_master WHERE id=?", (dept_id,))
    row = cursor.fetchone()
    if not row:
        cursor.close()
        conn.close()
        return jsonify({"message": "Department not found"}), 404
    if request.method == 'DELETE':
        cursor.execute("SELECT COUNT(1) AS c FROM subjects_master WHERE department_id=?", (dept_id,))
        cr = cursor.fetchone()
        if cr and int(cr["c"]) > 0:
            cursor.close()
            conn.close()
            return jsonify({"message": "Cannot delete department with subjects"}), 400
        cursor.execute("DELETE FROM departments_master WHERE id=?", (dept_id,))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"message": "Department deleted"}), 200
    data = request.get_json() or {}
    institution_id = _parse_int(data.get("institution_id"), _parse_int(row["institution_id"], 0))
    name = str(data.get("name") or "").strip()
    stream = str(data.get("stream") or "").strip().lower()
    if institution_id <= 0:
        cursor.close()
        conn.close()
        return jsonify({"message": "Invalid institution_id"}), 400
    if len(name) < 2 or len(name) > 200:
        cursor.close()
        conn.close()
        return jsonify({"message": "Invalid name"}), 400
    if stream not in _MASTER_STREAMS:
        cursor.close()
        conn.close()
        return jsonify({"message": "Invalid stream"}), 400
    cursor.execute("SELECT id FROM institutions WHERE id=?", (institution_id,))
    if not cursor.fetchone():
        cursor.close()
        conn.close()
        return jsonify({"message": "Institution not found"}), 404
    cursor.execute(
        "UPDATE departments_master SET institution_id=?, name=?, stream=? WHERE id=?",
        (institution_id, name, stream, dept_id),
    )
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"message": "Department updated"}), 200


@app.route('/master/semesters', methods=['GET', 'POST'])
@token_required
def master_semesters(current_user):
    if request.method != 'GET':
        err = _master_admin_guard(current_user)
        if err:
            return err
    conn = get_db_connection()
    cursor = conn.cursor()
    if request.method == 'GET':
        institution_id = _parse_int(request.args.get("institution_id"), 0)
        if institution_id > 0:
            cursor.execute(
                "SELECT * FROM semesters_master WHERE institution_id=? ORDER BY order_index ASC, id ASC",
                (institution_id,),
            )
        else:
            cursor.execute(
                "SELECT * FROM semesters_master ORDER BY order_index ASC, id ASC"
            )
        items = [row_to_dict(r) for r in cursor.fetchall()]
        cursor.close()
        conn.close()
        return jsonify({"items": items, "count": len(items)}), 200
    data = request.get_json() or {}
    institution_id = _parse_int(data.get("institution_id"), 0)
    name = str(data.get("name") or "").strip()
    order_index = _parse_int(data.get("order_index"), 0)
    if institution_id <= 0:
        cursor.close()
        conn.close()
        return jsonify({"message": "Invalid institution_id"}), 400
    if len(name) < 1 or len(name) > 120:
        cursor.close()
        conn.close()
        return jsonify({"message": "Invalid name"}), 400
    cursor.execute("SELECT id FROM institutions WHERE id=?", (institution_id,))
    if not cursor.fetchone():
        cursor.close()
        conn.close()
        return jsonify({"message": "Institution not found"}), 404
    cursor.execute(
        "INSERT INTO semesters_master (institution_id, name, order_index) VALUES (?, ?, ?)",
        (institution_id, name, order_index),
    )
    new_id = cursor.lastrowid
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"message": "Semester created", "id": new_id}), 201


@app.route('/master/semesters/<int:sem_id>', methods=['PUT', 'DELETE'])
@token_required
def master_semester_item(current_user, sem_id):
    err = _master_admin_guard(current_user)
    if err:
        return err
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM semesters_master WHERE id=?", (sem_id,))
    row = cursor.fetchone()
    if not row:
        cursor.close()
        conn.close()
        return jsonify({"message": "Semester not found"}), 404
    if request.method == 'DELETE':
        cursor.execute("UPDATE subjects_master SET semester_id=NULL WHERE semester_id=?", (sem_id,))
        cursor.execute("DELETE FROM semesters_master WHERE id=?", (sem_id,))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"message": "Semester deleted"}), 200
    data = request.get_json() or {}
    institution_id = _parse_int(data.get("institution_id"), _parse_int(row["institution_id"], 0))
    name = str(data.get("name") or "").strip()
    order_index = _parse_int(data.get("order_index"), _parse_int(row["order_index"], 0))
    if institution_id <= 0:
        cursor.close()
        conn.close()
        return jsonify({"message": "Invalid institution_id"}), 400
    if len(name) < 1 or len(name) > 120:
        cursor.close()
        conn.close()
        return jsonify({"message": "Invalid name"}), 400
    cursor.execute("SELECT id FROM institutions WHERE id=?", (institution_id,))
    if not cursor.fetchone():
        cursor.close()
        conn.close()
        return jsonify({"message": "Institution not found"}), 404
    cursor.execute(
        "UPDATE semesters_master SET institution_id=?, name=?, order_index=? WHERE id=?",
        (institution_id, name, order_index, sem_id),
    )
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"message": "Semester updated"}), 200


@app.route('/master/subjects', methods=['GET', 'POST'])
@token_required
def master_subjects(current_user):
    if request.method != 'GET':
        err = _master_admin_guard(current_user)
        if err:
            return err
    conn = get_db_connection()
    cursor = conn.cursor()
    if request.method == 'GET':
        department_id = _parse_int(request.args.get("department_id"), 0)
        semester_id = _parse_int(request.args.get("semester_id"), 0)
        sql = """
            SELECT s.*, d.name AS department_name, d.stream AS department_stream
            FROM subjects_master s
            JOIN departments_master d ON d.id = s.department_id
            WHERE 1=1
        """
        params: List[Any] = []
        if department_id > 0:
            sql += " AND s.department_id=?"
            params.append(department_id)
        if semester_id > 0:
            sql += " AND s.semester_id=?"
            params.append(semester_id)
        sql += " ORDER BY s.id DESC"
        cursor.execute(sql, params)
        items = [row_to_dict(r) for r in cursor.fetchall()]
        cursor.close()
        conn.close()
        return jsonify({"items": items, "count": len(items)}), 200
    data = request.get_json() or {}
    department_id = _parse_int(data.get("department_id"), 0)
    semester_id = _parse_int(data.get("semester_id"), 0)
    code = str(data.get("code") or "").strip()
    name = str(data.get("name") or "").strip()
    credits = max(1, min(10, _parse_int(data.get("credits"), 3)))
    syllabus = str(data.get("syllabus") or "").strip()
    if department_id <= 0:
        cursor.close()
        conn.close()
        return jsonify({"message": "Invalid department_id"}), 400
    if len(name) < 2 or len(name) > 200:
        cursor.close()
        conn.close()
        return jsonify({"message": "Invalid name"}), 400
    if len(code) > 40:
        cursor.close()
        conn.close()
        return jsonify({"message": "Invalid code"}), 400
    cursor.execute("SELECT id FROM departments_master WHERE id=?", (department_id,))
    if not cursor.fetchone():
        cursor.close()
        conn.close()
        return jsonify({"message": "Department not found"}), 404
    if semester_id > 0:
        cursor.execute(
            "SELECT id FROM semesters_master WHERE id=? AND institution_id=(SELECT institution_id FROM departments_master WHERE id=?)",
            (semester_id, department_id),
        )
        if not cursor.fetchone():
            cursor.close()
            conn.close()
            return jsonify({"message": "Semester does not belong to this institution"}), 400
    sem_val = semester_id if semester_id > 0 else None
    cursor.execute(
        "INSERT INTO subjects_master (department_id, semester_id, code, name, credits, syllabus) VALUES (?, ?, ?, ?, ?, ?)",
        (department_id, sem_val, code, name, credits, syllabus),
    )
    new_id = cursor.lastrowid
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"message": "Subject created", "id": new_id}), 201


@app.route('/master/subjects/<int:subj_id>', methods=['PUT', 'DELETE'])
@token_required
def master_subject_item(current_user, subj_id):
    err = _master_admin_guard(current_user)
    if err:
        return err
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM subjects_master WHERE id=?", (subj_id,))
    row = cursor.fetchone()
    if not row:
        cursor.close()
        conn.close()
        return jsonify({"message": "Subject not found"}), 404
    if request.method == 'DELETE':
        cursor.execute("DELETE FROM study_materials WHERE subject_id=?", (subj_id,))
        cursor.execute("DELETE FROM subjects_master WHERE id=?", (subj_id,))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"message": "Subject deleted"}), 200
    data = request.get_json() or {}
    department_id = _parse_int(data.get("department_id"), _parse_int(row["department_id"], 0))
    code = str(data.get("code") if data.get("code") is not None else row["code"] or "").strip()
    name = str(data.get("name") or "").strip()
    try:
        default_credits = int(row["credits"] or 3)
    except (KeyError, IndexError, TypeError):
        default_credits = 3
    credits = max(1, min(10, _parse_int(data.get("credits"), default_credits)))
    syllabus = str(data.get("syllabus") if data.get("syllabus") is not None else (row["syllabus"] if "syllabus" in row.keys() else "") or "").strip()
    if department_id <= 0:
        cursor.close()
        conn.close()
        return jsonify({"message": "Invalid department_id"}), 400
    if len(name) < 2 or len(name) > 200:
        cursor.close()
        conn.close()
        return jsonify({"message": "Invalid name"}), 400
    if len(code) > 40:
        cursor.close()
        conn.close()
        return jsonify({"message": "Invalid code"}), 400
    if len(syllabus) > 5000:
        cursor.close()
        conn.close()
        return jsonify({"message": "Invalid syllabus"}), 400
    cursor.execute("SELECT id FROM departments_master WHERE id=?", (department_id,))
    if not cursor.fetchone():
        cursor.close()
        conn.close()
        return jsonify({"message": "Department not found"}), 404
    sem_val: Optional[int]
    if "semester_id" in data:
        semester_id_u = _parse_int(data.get("semester_id"), 0)
        if semester_id_u > 0:
            cursor.execute(
                "SELECT id FROM semesters_master WHERE id=? AND institution_id=(SELECT institution_id FROM departments_master WHERE id=?)",
                (semester_id_u, department_id),
            )
            if not cursor.fetchone():
                cursor.close()
                conn.close()
                return jsonify({"message": "Semester does not belong to this institution"}), 400
            sem_val = semester_id_u
        else:
            sem_val = None
    else:
        sem_val = row["semester_id"]
    cursor.execute(
        "UPDATE subjects_master SET department_id=?, semester_id=?, code=?, name=?, credits=?, syllabus=? WHERE id=?",
        (department_id, sem_val, code, name, credits, syllabus, subj_id),
    )
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"message": "Subject updated"}), 200


@app.route('/master/materials', methods=['GET', 'POST'])
@token_required
def master_materials(current_user):
    conn = get_db_connection()
    cursor = conn.cursor()
    if request.method == 'GET':
        subject_id = _parse_int(request.args.get("subject_id"), 0)
        limit = max(1, min(200, _parse_int(request.args.get("limit"), 50)))
        if subject_id > 0:
            cursor.execute(
                """
                SELECT m.*, s.name AS subject_name, s.code AS subject_code,
                       d.name AS department_name, d.stream AS department_stream
                FROM study_materials m
                JOIN subjects_master s ON s.id = m.subject_id
                JOIN departments_master d ON d.id = s.department_id
                WHERE m.subject_id=?
                ORDER BY m.id DESC
                LIMIT ?
                """,
                (subject_id, limit),
            )
        else:
            cursor.execute(
                """
                SELECT m.*, s.name AS subject_name, s.code AS subject_code,
                       d.name AS department_name, d.stream AS department_stream
                FROM study_materials m
                JOIN subjects_master s ON s.id = m.subject_id
                JOIN departments_master d ON d.id = s.department_id
                ORDER BY m.id DESC
                LIMIT ?
                """,
                (limit,),
            )
        items = [row_to_dict(r) for r in cursor.fetchall()]
        cursor.close()
        conn.close()
        return jsonify({"items": items, "count": len(items)}), 200
    err = _master_faculty_or_admin_guard(current_user)
    if err:
        cursor.close()
        conn.close()
        return err
    data = request.get_json() or {}
    subject_id = _parse_int(data.get("subject_id"), 0)
    title = str(data.get("title") or "").strip()
    material_type = str(data.get("material_type") or "").strip().lower()
    url = str(data.get("url") or "").strip()
    description = str(data.get("description") or "").strip()
    if subject_id <= 0:
        cursor.close()
        conn.close()
        return jsonify({"message": "Invalid subject_id"}), 400
    if len(title) < 2 or len(title) > 200:
        cursor.close()
        conn.close()
        return jsonify({"message": "Invalid title"}), 400
    if material_type not in _MASTER_MATERIAL_TYPES:
        cursor.close()
        conn.close()
        return jsonify({"message": "Invalid material_type"}), 400
    if len(url) < 8 or len(url) > 2000:
        cursor.close()
        conn.close()
        return jsonify({"message": "Invalid url"}), 400
    if len(description) > 2000:
        cursor.close()
        conn.close()
        return jsonify({"message": "Invalid description"}), 400
    cursor.execute("SELECT id FROM subjects_master WHERE id=?", (subject_id,))
    if not cursor.fetchone():
        cursor.close()
        conn.close()
        return jsonify({"message": "Subject not found"}), 404
    created_by = _parse_int(current_user.get("id"), 0) or None
    cursor.execute(
        """
        INSERT INTO study_materials (subject_id, title, material_type, url, description, created_by)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (subject_id, title, material_type, url, description, created_by),
    )
    new_id = cursor.lastrowid
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"message": "Material created", "id": new_id}), 201


@app.route('/master/materials/<int:mat_id>', methods=['DELETE'])
@token_required
def master_material_item(current_user, mat_id):
    err = _master_faculty_or_admin_guard(current_user)
    if err:
        return err
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM study_materials WHERE id=?", (mat_id,))
    if cursor.rowcount == 0:
        cursor.close()
        conn.close()
        return jsonify({"message": "Material not found"}), 404
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"message": "Material deleted"}), 200


@app.route('/cases', methods=['GET', 'POST'])
@token_required
def cases(current_user):
    role = current_user.get("role")
    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'POST':
        if role not in ["admin", "faculty"]:
            cursor.close()
            conn.close()
            return jsonify({"message": "Unauthorized!"}), 403
        data = request.get_json() or {}
        student_id = _parse_int(data.get("student_id"), 0)
        category = str(data.get("category") or "").strip()
        severity = str(data.get("severity") or "medium").strip().lower()
        notes = str(data.get("notes") or "").strip()
        actions = str(data.get("actions") or "").strip()
        suggestions = str(data.get("suggestions") or "").strip()
        if student_id <= 0:
            cursor.close()
            conn.close()
            return jsonify({"message": "Invalid student_id"}), 400
        if len(category) < 3 or len(category) > 120:
            cursor.close()
            conn.close()
            return jsonify({"message": "Invalid category"}), 400
        if severity not in ["low", "medium", "high"]:
            cursor.close()
            conn.close()
            return jsonify({"message": "Invalid severity"}), 400
        if len(notes) > 2000 or len(actions) > 2000 or len(suggestions) > 2000:
            cursor.close()
            conn.close()
            return jsonify({"message": "Text fields too long"}), 400
        cursor.execute("SELECT id FROM students WHERE id=?", (student_id,))
        if not cursor.fetchone():
            cursor.close()
            conn.close()
            return jsonify({"message": "Student not found"}), 404

        cursor.execute(
            """
            INSERT INTO cases (student_id, category, severity, notes, actions, suggestions, created_by, updated_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                student_id,
                category,
                severity,
                notes,
                actions,
                suggestions,
                _parse_int(current_user.get("id"), 0),
                _parse_int(current_user.get("id"), 0),
            ),
        )
        case_id = cursor.lastrowid
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"message": "Case created", "case_id": case_id}), 201

    # GET
    status = str(request.args.get("status") or "open").strip().lower()
    student_id_q = _parse_int(request.args.get("student_id"), 0)
    limit = max(1, min(300, _parse_int(request.args.get("limit"), 100)))
    sql = """
        SELECT c.*, s.name as student_name
        FROM cases c
        JOIN students s ON s.id=c.student_id
        WHERE 1=1
    """
    params: List[Any] = []
    if status in ["open", "in_progress", "resolved"]:
        sql += " AND c.status=?"
        params.append(status)

    if role in ["admin", "faculty"]:
        if student_id_q > 0:
            sql += " AND c.student_id=?"
            params.append(student_id_q)
    elif role == "student":
        linked = _get_linked_student_id(_parse_int(current_user.get("id"), 0))
        if not linked:
            cursor.close()
            conn.close()
            return jsonify({"message": "Student account not linked"}), 409
        sql += " AND c.student_id=?"
        params.append(linked)
    elif role == "parent":
        parent_student_id = _get_parent_student_id(_parse_int(current_user.get("id"), 0))
        if not parent_student_id:
            cursor.close()
            conn.close()
            return jsonify({"message": "Parent account not linked to student"}), 409
        sql += " AND c.student_id=?"
        params.append(parent_student_id)
    else:
        cursor.close()
        conn.close()
        return jsonify({"message": "Unauthorized!"}), 403

    sql += " ORDER BY c.id DESC LIMIT ?"
    params.append(limit)
    cursor.execute(sql, params)
    rows = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"count": len(rows), "items": rows}), 200

@app.route('/cases/<int:case_id>', methods=['PUT'])
@token_required
def update_case(current_user, case_id):
    if current_user.get("role") not in ["admin", "faculty"]:
        return jsonify({"message": "Unauthorized!"}), 403
    data = request.get_json() or {}
    status = str(data.get("status") or "").strip().lower()
    notes = str(data.get("notes") or "").strip()
    actions = str(data.get("actions") or "").strip()
    suggestions = str(data.get("suggestions") or "").strip()
    resolution_summary = str(data.get("resolution_summary") or "").strip()

    if status and status not in ["open", "in_progress", "resolved"]:
        return jsonify({"message": "Invalid status"}), 400
    if len(notes) > 2000 or len(actions) > 2000 or len(suggestions) > 2000 or len(resolution_summary) > 2000:
        return jsonify({"message": "Text fields too long"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, status FROM cases WHERE id=?", (case_id,))
    row = cursor.fetchone()
    if not row:
        cursor.close()
        conn.close()
        return jsonify({"message": "Case not found"}), 404

    update_parts = ["updated_by=?", "updated_at=CURRENT_TIMESTAMP"]
    params: List[Any] = [_parse_int(current_user.get("id"), 0)]
    if status:
        update_parts.append("status=?")
        params.append(status)
        if status == "resolved":
            update_parts.append("resolved_at=CURRENT_TIMESTAMP")
    if notes:
        update_parts.append("notes=?")
        params.append(notes)
    if actions:
        update_parts.append("actions=?")
        params.append(actions)
    if suggestions:
        update_parts.append("suggestions=?")
        params.append(suggestions)
    if resolution_summary:
        update_parts.append("resolution_summary=?")
        params.append(resolution_summary)

    params.append(case_id)
    cursor.execute(f"UPDATE cases SET {', '.join(update_parts)} WHERE id=?", params)
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"message": "Case updated"}), 200

@app.route('/cases/<int:case_id>/acknowledge', methods=['POST'])
@token_required
def acknowledge_case(current_user, case_id):
    if current_user.get("role") != "parent":
        return jsonify({"message": "Unauthorized!"}), 403
    parent_student_id = _get_parent_student_id(_parse_int(current_user.get("id"), 0))
    if not parent_student_id:
        return jsonify({"message": "Parent account not linked to student"}), 409

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, student_id FROM cases WHERE id=?", (case_id,))
    c = row_to_dict(cursor.fetchone())
    if not c:
        cursor.close()
        conn.close()
        return jsonify({"message": "Case not found"}), 404
    if _parse_int(c.get("student_id"), 0) != parent_student_id:
        cursor.close()
        conn.close()
        return jsonify({"message": "Unauthorized for this case"}), 403
    cursor.execute(
        "UPDATE cases SET parent_acknowledged_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (case_id,),
    )
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"message": "Case acknowledged by parent"}), 200

@app.route('/meetings/request', methods=['POST'])
@token_required
def request_meeting(current_user):
    if current_user.get("role") != "parent":
        return jsonify({"message": "Unauthorized!"}), 403
    parent_id = _parse_int(current_user.get("id"), 0)
    student_id = _get_parent_student_id(parent_id)
    if not student_id:
        return jsonify({"message": "Parent account not linked to student"}), 409

    data = request.get_json() or {}
    faculty_id = _parse_int(data.get("faculty_id"), 0)
    requested_time = str(data.get("time") or "").strip()
    parent_note = str(data.get("note") or "").strip()
    if faculty_id <= 0:
        return jsonify({"message": "Invalid faculty_id"}), 400
    if len(requested_time) < 5 or len(requested_time) > 64:
        return jsonify({"message": "Invalid meeting time"}), 400
    if len(parent_note) > 1000:
        return jsonify({"message": "Note too long"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, role FROM users WHERE id=?", (faculty_id,))
    u = row_to_dict(cursor.fetchone())
    if not u or str(u.get("role")) != "faculty":
        cursor.close()
        conn.close()
        return jsonify({"message": "faculty_id not found"}), 404
    cursor.execute(
        """
        INSERT INTO meetings (parent_id, faculty_user_id, student_id, requested_time, status, parent_note)
        VALUES (?, ?, ?, ?, 'requested', ?)
        """,
        (parent_id, faculty_id, student_id, requested_time, parent_note),
    )
    meeting_id = cursor.lastrowid
    conn.commit()
    cursor.close()
    conn.close()
    try:
        _create_notification(
            recipient_role="faculty",
            recipient_id=faculty_id,
            title="New Parent Meeting Request",
            message=f"A parent requested a meeting for student #{student_id} at {requested_time}.",
            category="meeting",
        )
    except Exception:
        pass
    return jsonify({"message": "Meeting requested", "meeting_id": meeting_id}), 201

@app.route('/meetings/<int:meeting_id>/approve', methods=['POST'])
@token_required
def approve_meeting(current_user, meeting_id):
    if current_user.get("role") not in ["faculty", "admin"]:
        return jsonify({"message": "Unauthorized!"}), 403
    data = request.get_json() or {}
    status = str(data.get("status") or "approved").strip().lower()
    scheduled_time = str(data.get("time") or "").strip()
    faculty_note = str(data.get("note") or "").strip()
    if status not in ["approved", "rescheduled", "rejected", "completed", "cancelled"]:
        return jsonify({"message": "Invalid status"}), 400
    if len(scheduled_time) > 64 or len(faculty_note) > 1000:
        return jsonify({"message": "Field too long"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM meetings WHERE id=?", (meeting_id,))
    m = row_to_dict(cursor.fetchone())
    if not m:
        cursor.close()
        conn.close()
        return jsonify({"message": "Meeting not found"}), 404
    if current_user.get("role") == "faculty" and _parse_int(m.get("faculty_user_id"), 0) != _parse_int(current_user.get("id"), 0):
        cursor.close()
        conn.close()
        return jsonify({"message": "Unauthorized for this meeting"}), 403

    cursor.execute(
        """
        UPDATE meetings
        SET status=?, scheduled_time=?, faculty_note=?, updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (status, scheduled_time, faculty_note, meeting_id),
    )
    conn.commit()
    cursor.close()
    conn.close()
    try:
        _create_notification(
            recipient_role="parent",
            recipient_id=_parse_int(m.get("parent_id"), 0),
            title="Meeting Status Updated",
            message=f"Your meeting request is now '{status}'. Time: {scheduled_time or 'TBD'}.",
            category="meeting",
        )
    except Exception:
        pass
    return jsonify({"message": "Meeting updated"}), 200

@app.route('/meetings', methods=['GET'])
@token_required
def list_meetings(current_user):
    role = current_user.get("role")
    status = str(request.args.get("status") or "all").strip().lower()
    limit = max(1, min(300, _parse_int(request.args.get("limit"), 100)))
    conn = get_db_connection()
    cursor = conn.cursor()

    sql = """
        SELECT m.*, p.name as parent_name, s.name as student_name, u.name as faculty_name
        FROM meetings m
        LEFT JOIN parents p ON p.id=m.parent_id
        LEFT JOIN students s ON s.id=m.student_id
        LEFT JOIN users u ON u.id=m.faculty_user_id
        WHERE 1=1
    """
    params: List[Any] = []
    if status in ["requested", "approved", "rescheduled", "completed", "rejected", "cancelled"]:
        sql += " AND m.status=?"
        params.append(status)

    if role == "parent":
        sql += " AND m.parent_id=?"
        params.append(_parse_int(current_user.get("id"), 0))
    elif role == "faculty":
        sql += " AND m.faculty_user_id=?"
        params.append(_parse_int(current_user.get("id"), 0))
    elif role == "student":
        linked = _get_linked_student_id(_parse_int(current_user.get("id"), 0))
        if not linked:
            cursor.close()
            conn.close()
            return jsonify({"message": "Student account not linked"}), 409
        sql += " AND m.student_id=?"
        params.append(linked)
    elif role != "admin":
        cursor.close()
        conn.close()
        return jsonify({"message": "Unauthorized!"}), 403

    sql += " ORDER BY m.id DESC LIMIT ?"
    params.append(limit)
    cursor.execute(sql, params)
    rows = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"count": len(rows), "items": rows}), 200

@app.route('/assignments', methods=['GET', 'POST'])
@token_required
def assignments(current_user):
    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'POST':
        if current_user.get("role") not in ["admin", "faculty"]:
            cursor.close()
            conn.close()
            return jsonify({"message": "Unauthorized!"}), 403
        data = request.get_json() or {}
        title = str(data.get("title") or "").strip()
        description = str(data.get("description") or "").strip()
        due_date = str(data.get("due_date") or "").strip()
        if len(title) < 3 or len(title) > 200:
            cursor.close()
            conn.close()
            return jsonify({"message": "Invalid title"}), 400
        cursor.execute(
            "INSERT INTO assignments (title, description, due_date, created_by) VALUES (?, ?, ?, ?)",
            (title, description, due_date, _parse_int(current_user.get("id"), 0)),
        )
        conn.commit()
        cursor.close()
        conn.close()
        try:
            _create_notification(
                recipient_role="student",
                recipient_id=None,
                title="New Assignment Published",
                message=f"'{title}' has been published. Due: {due_date or 'TBD'}.",
                category="assignment",
            )
            _create_notification(
                recipient_role="parent",
                recipient_id=None,
                title="New Assignment Published",
                message=f"A new assignment '{title}' was published for students.",
                category="assignment",
            )
        except Exception:
            pass
        return jsonify({"message": "Assignment created"}), 201

    # GET
    if current_user.get("role") == "student":
        student_id = _get_linked_student_id(int(current_user["id"]))
        if not student_id:
            cursor.close()
            conn.close()
            return jsonify({"message": "Student account not linked"}), 409
        cursor.execute(
            """
            SELECT a.id, a.title, a.description, a.due_date, a.created_at,
                   COALESCE(s.status, 'pending') as status,
                   COALESCE(s.notes, '') as notes,
                   COALESCE(s.file_name, '') as file_name,
                   s.grade_score as grade_score,
                   COALESCE(s.grade_feedback, '') as grade_feedback,
                   s.graded_at as graded_at
            FROM assignments a
            LEFT JOIN assignment_submissions s
              ON s.assignment_id=a.id AND s.student_id=?
            ORDER BY a.id DESC
            """,
            (student_id,),
        )
    else:
        cursor.execute("SELECT * FROM assignments ORDER BY id DESC")

    rows = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"count": len(rows), "items": rows}), 200

@app.route('/assignments/<int:assignment_id>/status', methods=['POST'])
@token_required
def assignment_status(current_user, assignment_id):
    if current_user.get("role") != "student":
        return jsonify({"message": "Unauthorized!"}), 403
    student_id = _get_linked_student_id(int(current_user["id"]))
    if not student_id:
        return jsonify({"message": "Student account not linked"}), 409
    data = request.get_json() or {}
    status = str(data.get("status") or "").strip()
    notes = str(data.get("notes") or "").strip()
    if status not in ["pending", "submitted", "completed"]:
        return jsonify({"message": "Invalid status"}), 400
    if len(notes) > 500:
        return jsonify({"message": "Notes too long"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO assignment_submissions (assignment_id, student_id, status, notes)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(assignment_id, student_id)
        DO UPDATE SET status=excluded.status, notes=excluded.notes, updated_at=CURRENT_TIMESTAMP
        """,
        (assignment_id, student_id, status, notes),
    )
    conn.commit()
    cursor.close()
    conn.close()
    try:
        _run_intelligent_alert_engine(int(student_id))
    except Exception:
        pass
    return jsonify({"message": "Assignment status updated"}), 200

@app.route('/assignments/<int:assignment_id>/submissions', methods=['GET'])
@token_required
def assignment_submissions(current_user, assignment_id):
    if current_user.get("role") not in ["admin", "faculty"]:
        return jsonify({"message": "Unauthorized!"}), 403

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, title FROM assignments WHERE id=?", (assignment_id,))
    assignment = cursor.fetchone()
    if not assignment:
        cursor.close()
        conn.close()
        return jsonify({"message": "Assignment not found"}), 404

    cursor.execute(
        """
        SELECT s.id as student_id, s.name as student_name,
               COALESCE(sub.status, 'pending') as status,
               COALESCE(sub.notes, '') as notes,
               sub.updated_at,
               COALESCE(sub.file_name, '') as file_name,
               sub.grade_score,
               COALESCE(sub.grade_feedback, '') as grade_feedback,
               sub.graded_at
        FROM students s
        LEFT JOIN assignment_submissions sub
          ON sub.student_id=s.id AND sub.assignment_id=?
        ORDER BY s.name ASC
        """,
        (assignment_id,),
    )
    rows = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"assignment_id": assignment_id, "assignment_title": assignment[1], "items": rows}), 200

@app.route('/assignments/<int:assignment_id>/upload', methods=['POST'])
@token_required
def assignment_upload(current_user, assignment_id):
    if current_user.get("role") != "student":
        return jsonify({"message": "Unauthorized!"}), 403
    student_id = _get_linked_student_id(int(current_user["id"]))
    if not student_id:
        return jsonify({"message": "Student account not linked"}), 409

    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return jsonify({"message": "File is required"}), 400

    original_name = secure_filename(upload.filename)
    if not original_name:
        return jsonify({"message": "Invalid file name"}), 400
    ext = os.path.splitext(original_name)[1].lower()
    allowed = {".pdf", ".doc", ".docx", ".txt", ".png", ".jpg", ".jpeg"}
    if ext not in allowed:
        return jsonify({"message": "Unsupported file type"}), 400

    safe_filename = f"a{assignment_id}_s{student_id}_{uuid.uuid4().hex[:10]}{ext}"
    save_path = os.path.join(ASSIGNMENT_UPLOAD_DIR, safe_filename)
    upload.save(save_path)

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM assignments WHERE id=?", (assignment_id,))
    if not cursor.fetchone():
        cursor.close()
        conn.close()
        try:
            os.remove(save_path)
        except Exception:
            pass
        return jsonify({"message": "Assignment not found"}), 404

    cursor.execute(
        """
        INSERT INTO assignment_submissions
            (assignment_id, student_id, status, notes, file_path, file_name)
        VALUES (?, ?, 'submitted', '', ?, ?)
        ON CONFLICT(assignment_id, student_id)
        DO UPDATE SET
            status='submitted',
            file_path=excluded.file_path,
            file_name=excluded.file_name,
            updated_at=CURRENT_TIMESTAMP
        """,
        (assignment_id, student_id, save_path, original_name),
    )
    conn.commit()
    cursor.close()
    conn.close()
    try:
        _run_intelligent_alert_engine(int(student_id))
    except Exception:
        pass
    return jsonify({"message": "Assignment uploaded", "file_name": original_name}), 200

@app.route('/assignments/<int:assignment_id>/grade', methods=['POST'])
@token_required
def assignment_grade(current_user, assignment_id):
    if current_user.get("role") not in ["admin", "faculty"]:
        return jsonify({"message": "Unauthorized!"}), 403
    data = request.get_json() or {}
    student_id = _parse_int(data.get("student_id"), 0)
    grade_score = _parse_float(data.get("grade_score"))
    grade_feedback = str(data.get("grade_feedback") or "").strip()
    if student_id <= 0:
        return jsonify({"message": "Invalid student_id"}), 400
    if grade_score < 0 or grade_score > 100:
        return jsonify({"message": "grade_score must be between 0 and 100"}), 400
    if len(grade_feedback) > 1000:
        return jsonify({"message": "grade_feedback too long"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM assignment_submissions WHERE assignment_id=? AND student_id=?",
        (assignment_id, student_id),
    )
    if not cursor.fetchone():
        cursor.close()
        conn.close()
        return jsonify({"message": "Submission not found"}), 404

    cursor.execute(
        """
        UPDATE assignment_submissions
        SET status='completed',
            grade_score=?,
            grade_feedback=?,
            graded_by=?,
            graded_at=CURRENT_TIMESTAMP,
            updated_at=CURRENT_TIMESTAMP
        WHERE assignment_id=? AND student_id=?
        """,
        (
            grade_score,
            grade_feedback,
            _parse_int(current_user.get("id"), 0),
            assignment_id,
            student_id,
        ),
    )
    conn.commit()
    cursor.close()
    conn.close()
    try:
        _run_intelligent_alert_engine(int(student_id))
    except Exception:
        pass
    return jsonify({"message": "Submission graded"}), 200

@app.route('/adaptive-learning/me', methods=['GET'])
@token_required
def adaptive_learning_me(current_user):
    if current_user.get("role") != "student":
        return jsonify({"message": "Unauthorized!"}), 403
    student_id = _get_linked_student_id(int(current_user["id"]))
    if not student_id:
        return jsonify({"message": "Student account not linked"}), 409

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT attendance, study_hours, sleep_hours FROM students WHERE id=?", (student_id,))
    row = cursor.fetchone()
    if not row:
        cursor.close()
        conn.close()
        return jsonify({"message": "Student not found"}), 404

    attendance = _parse_float(row[0])
    study_hours = _parse_float(row[1])
    sleep_hours = _parse_float(row[2])
    predicted = float(predict_marks(study_hours, sleep_hours, attendance))

    if predicted < 60:
        difficulty = "basic"
        tasks = [
            "Practice 5 foundational questions today.",
            "Revise class notes for 30 minutes.",
            "Complete one short recap quiz.",
        ]
    elif predicted < 80:
        difficulty = "intermediate"
        tasks = [
            "Solve 10 mixed-difficulty problems.",
            "Summarize one weak topic in your own words.",
            "Take one intermediate quiz.",
        ]
    else:
        difficulty = "advanced"
        tasks = [
            "Attempt 15 advanced application questions.",
            "Teach one concept to a peer.",
            "Take one advanced timed quiz.",
        ]
    cursor.close()
    conn.close()
    return jsonify({"difficulty": difficulty, "predicted_marks": round(predicted, 2), "tasks": tasks}), 200

@app.route('/quizzes', methods=['GET', 'POST'])
@token_required
def quizzes(current_user):
    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'POST':
        if current_user.get("role") not in ["admin", "faculty"]:
            cursor.close()
            conn.close()
            return jsonify({"message": "Unauthorized!"}), 403
        data = request.get_json() or {}
        title = str(data.get("title") or "").strip()
        topic = str(data.get("topic") or "").strip()
        difficulty = str(data.get("difficulty") or "basic").strip()
        questions = data.get("questions") or []
        if len(title) < 3 or not topic or difficulty not in ["basic", "intermediate", "advanced"]:
            cursor.close()
            conn.close()
            return jsonify({"message": "Invalid quiz payload"}), 400
        if not isinstance(questions, list) or len(questions) == 0:
            cursor.close()
            conn.close()
            return jsonify({"message": "At least one question required"}), 400

        cursor.execute(
            "INSERT INTO quizzes (title, topic, difficulty, created_by) VALUES (?, ?, ?, ?)",
            (title, topic, difficulty, _parse_int(current_user.get("id"), 0)),
        )
        quiz_id = cursor.lastrowid
        for q in questions:
            qt = str((q or {}).get("question_text") or "").strip()
            oa = str((q or {}).get("option_a") or "").strip()
            ob = str((q or {}).get("option_b") or "").strip()
            oc = str((q or {}).get("option_c") or "").strip()
            od = str((q or {}).get("option_d") or "").strip()
            co = str((q or {}).get("correct_option") or "").strip().upper()
            if not qt or not oa or not ob or not oc or not od or co not in ["A", "B", "C", "D"]:
                continue
            cursor.execute(
                """
                INSERT INTO quiz_questions (quiz_id, question_text, option_a, option_b, option_c, option_d, correct_option)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (quiz_id, qt, oa, ob, oc, od, co),
            )
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"message": "Quiz created", "quiz_id": quiz_id}), 201

    # GET
    difficulty = request.args.get("difficulty")
    topic = request.args.get("topic")
    sql = "SELECT * FROM quizzes WHERE 1=1"
    params: List[Any] = []
    if difficulty in ["basic", "intermediate", "advanced"]:
        sql += " AND difficulty=?"
        params.append(difficulty)
    if topic:
        sql += " AND topic LIKE ?"
        params.append(f"%{topic}%")
    sql += " ORDER BY id DESC"
    cursor.execute(sql, params)
    rows = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"count": len(rows), "items": rows}), 200

@app.route('/quizzes/<int:quiz_id>', methods=['GET'])
@token_required
def quiz_detail(current_user, quiz_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM quizzes WHERE id=?", (quiz_id,))
    quiz = row_to_dict(cursor.fetchone())
    if not quiz:
        cursor.close()
        conn.close()
        return jsonify({"message": "Quiz not found"}), 404
    cursor.execute(
        """
        SELECT id, question_text, option_a, option_b, option_c, option_d
        FROM quiz_questions WHERE quiz_id=? ORDER BY id ASC
        """,
        (quiz_id,),
    )
    questions = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"quiz": quiz, "questions": questions}), 200

@app.route('/quizzes/<int:quiz_id>/submit', methods=['POST'])
@token_required
def quiz_submit(current_user, quiz_id):
    if current_user.get("role") != "student":
        return jsonify({"message": "Unauthorized!"}), 403
    student_id = _get_linked_student_id(int(current_user["id"]))
    if not student_id:
        return jsonify({"message": "Student account not linked"}), 409

    data = request.get_json() or {}
    answers = data.get("answers") or {}
    if not isinstance(answers, dict):
        return jsonify({"message": "answers must be an object {question_id: option}"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, correct_option FROM quiz_questions WHERE quiz_id=?", (quiz_id,))
    qrows = cursor.fetchall()
    total = len(qrows)
    if total == 0:
        cursor.close()
        conn.close()
        return jsonify({"message": "Quiz has no questions"}), 400

    correct = 0
    for q in qrows:
        qid = str(q[0])
        chosen = str(answers.get(qid) or answers.get(int(qid)) or "").upper()
        if chosen == str(q[1]).upper():
            correct += 1
    score = round((correct / total) * 100, 2)
    cursor.execute(
        "INSERT INTO quiz_submissions (quiz_id, student_id, score, total_questions) VALUES (?, ?, ?, ?)",
        (quiz_id, student_id, score, total),
    )
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"score": score, "correct": correct, "total": total}), 200

@app.route('/weak-topics/me', methods=['GET'])
@token_required
def weak_topics_me(current_user):
    if current_user.get("role") != "student":
        return jsonify({"message": "Unauthorized!"}), 403
    student_id = _get_linked_student_id(int(current_user["id"]))
    if not student_id:
        return jsonify({"message": "Student account not linked"}), 409

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT q.topic, AVG(s.score) as avg_score, COUNT(*) as attempts
        FROM quiz_submissions s
        JOIN quizzes q ON q.id=s.quiz_id
        WHERE s.student_id=?
        GROUP BY q.topic
        ORDER BY avg_score ASC
        """,
        (student_id,),
    )
    rows = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()

    weak = [r for r in rows if _parse_float(r.get("avg_score"), 0) < 60]
    return jsonify({"items": rows, "weak_topics": weak[:5]}), 200

@app.route('/faculty/class-health', methods=['GET'])
@token_required
def faculty_class_health(current_user):
    if current_user.get("role") not in ["faculty", "admin"]:
        return jsonify({"message": "Unauthorized!"}), 403
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM students")
    total_students = int(cursor.fetchone()[0] or 0)
    cursor.execute("SELECT AVG(attendance) FROM students")
    avg_attendance = round(float(cursor.fetchone()[0] or 0), 2)
    cursor.execute("SELECT AVG((study_hours*10) + (attendance*0.5)) FROM students")
    avg_learning_index = round(float(cursor.fetchone()[0] or 0), 2)
    cursor.execute("SELECT COUNT(*) FROM alerts WHERE resolved_at IS NULL")
    risk_students = int(cursor.fetchone()[0] or 0)
    cursor.close()
    conn.close()
    return jsonify({
        "total_students": total_students,
        "avg_attendance": avg_attendance,
        "avg_learning_index": avg_learning_index,
        "risk_students": risk_students,
    }), 200

@app.route('/faculty/auto-evaluation/upload', methods=['POST'])
@token_required
def faculty_auto_evaluation_upload(current_user):
    if current_user.get("role") not in ["faculty", "admin"]:
        return jsonify({"message": "Unauthorized!"}), 403

    file = request.files.get("file")
    if not file:
        return jsonify({"message": "CSV file required as form-data 'file'"}), 400

    try:
        text = file.read().decode("utf-8-sig")
    except Exception:
        return jsonify({"message": "Invalid CSV encoding"}), 400

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return jsonify({"message": "CSV header required"}), 400

    total_rows = 0
    processed = 0
    weak_students = 0
    marks_values: List[float] = []
    weak_items: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    conn = get_db_connection()
    cursor = conn.cursor()
    for idx, row in enumerate(reader, start=2):
        total_rows += 1
        try:
            student_id = _parse_int(row.get("student_id"), 0)
            marks = _parse_float(row.get("marks"), -1)
            if student_id <= 0 or marks < 0 or marks > 100:
                errors.append({"line": idx, "error": "Invalid student_id or marks"})
                continue
            cursor.execute("SELECT id, name FROM students WHERE id=?", (student_id,))
            s = row_to_dict(cursor.fetchone())
            if not s:
                errors.append({"line": idx, "error": f"student_id {student_id} not found"})
                continue
            processed += 1
            marks_values.append(marks)
            if marks < 40:
                weak_students += 1
                weak_items.append({"student_id": student_id, "name": s.get("name"), "marks": round(marks, 2)})
        except Exception as e:
            errors.append({"line": idx, "error": str(e)})

    class_avg = round(sum(marks_values) / len(marks_values), 2) if marks_values else 0.0
    summary = {
        "processed": processed,
        "weak_students": weak_students,
        "class_average": class_avg,
        "weak_items": weak_items[:30],
        "errors": errors[:40],
    }
    cursor.execute(
        """
        INSERT INTO auto_evaluation_runs (uploaded_by, total_rows, weak_students, class_average, summary_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            _parse_int(current_user.get("id"), 0),
            total_rows,
            weak_students,
            class_avg,
            json.dumps(summary),
        ),
    )
    run_id = cursor.lastrowid
    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({
        "message": "Auto evaluation completed",
        "run_id": run_id,
        **summary,
    }), 200

@app.route('/faculty/class-planner', methods=['GET', 'POST'])
@token_required
def faculty_class_planner(current_user):
    if current_user.get("role") not in ["faculty", "admin"]:
        return jsonify({"message": "Unauthorized!"}), 403
    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'POST':
        data = request.get_json() or {}
        class_name = str(data.get("class_name") or "").strip()
        subject = str(data.get("subject") or "").strip()
        schedule_time = str(data.get("schedule_time") or "").strip()
        syllabus_url = str(data.get("syllabus_url") or "").strip()
        if len(class_name) < 2 or len(class_name) > 120:
            cursor.close()
            conn.close()
            return jsonify({"message": "Invalid class_name"}), 400
        if len(subject) < 2 or len(subject) > 120:
            cursor.close()
            conn.close()
            return jsonify({"message": "Invalid subject"}), 400
        if len(schedule_time) < 5 or len(schedule_time) > 80:
            cursor.close()
            conn.close()
            return jsonify({"message": "Invalid schedule_time"}), 400
        if len(syllabus_url) > 500:
            cursor.close()
            conn.close()
            return jsonify({"message": "Invalid syllabus_url"}), 400
        cursor.execute(
            """
            INSERT INTO class_plans (faculty_user_id, class_name, subject, schedule_time, syllabus_url, completion_pct, status)
            VALUES (?, ?, ?, ?, ?, 0, 'scheduled')
            """,
            (_parse_int(current_user.get("id"), 0), class_name, subject, schedule_time, syllabus_url),
        )
        plan_id = cursor.lastrowid
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"message": "Class plan created", "id": plan_id}), 201

    limit = max(1, min(200, _parse_int(request.args.get("limit"), 50)))
    sql = "SELECT * FROM class_plans"
    params: List[Any] = []
    if current_user.get("role") == "faculty":
        sql += " WHERE faculty_user_id=?"
        params.append(_parse_int(current_user.get("id"), 0))
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    cursor.execute(sql, params)
    rows = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"count": len(rows), "items": rows}), 200

@app.route('/faculty/class-planner/<int:plan_id>', methods=['PUT'])
@token_required
def update_class_plan(current_user, plan_id):
    if current_user.get("role") not in ["faculty", "admin"]:
        return jsonify({"message": "Unauthorized!"}), 403
    data = request.get_json() or {}
    status = str(data.get("status") or "").strip().lower()
    completion_pct = _parse_float(data.get("completion_pct"), -1.0)
    if status and status not in ["scheduled", "ongoing", "completed", "cancelled"]:
        return jsonify({"message": "Invalid status"}), 400
    if completion_pct < 0 or completion_pct > 100:
        return jsonify({"message": "completion_pct must be 0-100"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM class_plans WHERE id=?", (plan_id,))
    p = row_to_dict(cursor.fetchone())
    if not p:
        cursor.close()
        conn.close()
        return jsonify({"message": "Plan not found"}), 404
    if current_user.get("role") == "faculty" and _parse_int(p.get("faculty_user_id"), 0) != _parse_int(current_user.get("id"), 0):
        cursor.close()
        conn.close()
        return jsonify({"message": "Unauthorized for this plan"}), 403

    if not status:
        status = str(p.get("status") or "scheduled")
    cursor.execute(
        """
        UPDATE class_plans
        SET status=?, completion_pct=?, updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (status, completion_pct, plan_id),
    )
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"message": "Class plan updated"}), 200

@app.route('/faculty/teaching-effectiveness', methods=['GET'])
@token_required
def faculty_teaching_effectiveness(current_user):
    if current_user.get("role") not in ["faculty", "admin"]:
        return jsonify({"message": "Unauthorized!"}), 403
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT q.topic as topic, AVG(s.score) as avg_score, COUNT(*) as attempts
        FROM quiz_submissions s
        JOIN quizzes q ON q.id=s.quiz_id
        GROUP BY q.topic
        HAVING COUNT(*) >= 1
        ORDER BY avg_score ASC
        LIMIT 8
        """
    )
    topic_rows = [row_to_dict(r) for r in cursor.fetchall()]
    weak_topics = [r for r in topic_rows if _parse_float(r.get("avg_score"), 0) < 60]

    cursor.execute(
        """
        SELECT COUNT(*) as total,
               SUM(CASE WHEN COALESCE(sub.status, 'pending')='completed' THEN 1 ELSE 0 END) as completed
        FROM assignments a
        JOIN students st ON 1=1
        LEFT JOIN assignment_submissions sub ON sub.assignment_id=a.id AND sub.student_id=st.id
        """
    )
    a = row_to_dict(cursor.fetchone()) or {}
    total_assignments = _parse_int(a.get("total"), 0)
    completed_assignments = _parse_int(a.get("completed"), 0)
    completion_rate = round((completed_assignments / total_assignments * 100), 2) if total_assignments else 0.0

    cursor.execute("SELECT AVG(attendance) as att FROM students")
    avg_att = _parse_float((row_to_dict(cursor.fetchone()) or {}).get("att"), 0.0)
    cursor.execute(
        """
        SELECT AVG(attendance) as att
        FROM student_metrics_history
        WHERE created_at >= datetime('now', '-14 day')
          AND created_at < datetime('now', '-7 day')
        """
    )
    prev_att = _parse_float((row_to_dict(cursor.fetchone()) or {}).get("att"), avg_att)
    attendance_delta = round(avg_att - prev_att, 2)

    suggestions: List[str] = []
    if weak_topics:
        topics = ", ".join(str(t.get("topic")) for t in weak_topics[:3])
        suggestions.append(f"Reinforce weak topics this week: {topics}.")
    if completion_rate < 70:
        suggestions.append(f"Assignment completion is {completion_rate}%. Consider reminder sprint + guided session.")
    if attendance_delta < 0:
        suggestions.append(f"Attendance trend is down ({attendance_delta}). Add one engagement-focused class.")
    if not suggestions:
        suggestions.append("Teaching KPIs are stable. Continue current approach and review weekly.")

    cursor.close()
    conn.close()
    return jsonify({
        "kpis": {
            "assignment_completion_rate": completion_rate,
            "avg_attendance": round(avg_att, 2),
            "attendance_delta": attendance_delta,
            "weak_topics_count": len(weak_topics),
        },
        "weak_topics": weak_topics,
        "suggestions": suggestions,
    }), 200

@app.route('/faculty/decision-support', methods=['GET'])
@token_required
def faculty_decision_support(current_user):
    if current_user.get("role") not in ["faculty", "admin"]:
        return jsonify({"message": "Unauthorized!"}), 403

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM students")
    total_students = int(cursor.fetchone()[0] or 0)
    cursor.execute("SELECT COUNT(*) FROM students WHERE attendance < 75")
    low_attendance_count = int(cursor.fetchone()[0] or 0)
    cursor.execute("SELECT COUNT(*) FROM alerts WHERE resolved_at IS NULL")
    open_risk_alerts = int(cursor.fetchone()[0] or 0)
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM assignments a
        JOIN students s ON 1=1
        LEFT JOIN assignment_submissions sub
          ON sub.assignment_id=a.id AND sub.student_id=s.id
        WHERE a.due_date IS NOT NULL
          AND TRIM(COALESCE(a.due_date, '')) <> ''
          AND date(a.due_date) < date('now')
          AND COALESCE(sub.status, 'pending') <> 'completed'
        """
    )
    overdue_submission_count = int(cursor.fetchone()[0] or 0)

    cursor.execute(
        """
        SELECT AVG(attendance) FROM student_metrics_history
        WHERE created_at >= datetime('now', '-14 day')
        """
    )
    avg_att_last_14 = _parse_float(cursor.fetchone()[0], 0.0)
    cursor.execute(
        """
        SELECT AVG(attendance) FROM student_metrics_history
        WHERE created_at >= datetime('now', '-28 day')
          AND created_at < datetime('now', '-14 day')
        """
    )
    avg_att_prev_14 = _parse_float(cursor.fetchone()[0], 0.0)

    cursor.execute(
        """
        SELECT AVG(predicted_marks) FROM student_metrics_history
        WHERE created_at >= datetime('now', '-14 day')
        """
    )
    avg_pred_last_14 = _parse_float(cursor.fetchone()[0], 0.0)
    cursor.execute(
        """
        SELECT AVG(predicted_marks) FROM student_metrics_history
        WHERE created_at >= datetime('now', '-28 day')
          AND created_at < datetime('now', '-14 day')
        """
    )
    avg_pred_prev_14 = _parse_float(cursor.fetchone()[0], 0.0)

    cursor.close()
    conn.close()

    attendance_drop = round(avg_att_last_14 - avg_att_prev_14, 2)
    predicted_drop = round(avg_pred_last_14 - avg_pred_prev_14, 2)
    low_attendance_pct = round((low_attendance_count / total_students * 100), 2) if total_students else 0.0

    recommendations: List[Dict[str, Any]] = []
    if low_attendance_count >= 5 or low_attendance_pct >= 25:
        recommendations.append({
            "key": "attendance_recovery",
            "priority": "high",
            "title": "Run targeted attendance recovery intervention",
            "action": f"Schedule extra mentor check-ins for {low_attendance_count} students below 75% attendance.",
            "reason": f"{low_attendance_pct}% of class is below attendance target.",
        })
    if overdue_submission_count >= 5:
        recommendations.append({
            "key": "assignment_completion_drive",
            "priority": "high",
            "title": "Assignment completion drive needed",
            "action": "Run a 48-hour assignment completion window and notify pending students + parents.",
            "reason": f"{overdue_submission_count} overdue assignment submissions are still incomplete.",
        })
    if attendance_drop < -3:
        recommendations.append({
            "key": "attendance_trend_drop",
            "priority": "medium",
            "title": "Attendance trend is dropping",
            "action": "Take one attendance-focused session and monitor daily for next 7 days.",
            "reason": f"Average attendance dropped by {abs(attendance_drop)} points vs previous 14-day period.",
        })
    if predicted_drop < -4:
        recommendations.append({
            "key": "predicted_decline",
            "priority": "medium",
            "title": "Predicted performance decline detected",
            "action": "Provide revision micro-plan for weak students and add one doubt-clearing class.",
            "reason": f"Average predicted marks dropped by {abs(predicted_drop)} vs previous period.",
        })
    if open_risk_alerts > 0:
        recommendations.append({
            "key": "resolve_risk_alerts",
            "priority": "medium",
            "title": "Resolve open high-risk alerts",
            "action": "Review high-risk list and close/advance interventions this week.",
            "reason": f"{open_risk_alerts} unresolved risk alerts are active.",
        })
    if not recommendations:
        recommendations.append({
            "key": "class_stable",
            "priority": "info",
            "title": "Class is stable",
            "action": "Continue current plan; review trends weekly.",
            "reason": "No high-priority risk patterns detected in current data window.",
        })

    recommendation_keys = [str(r.get("key") or "") for r in recommendations if r.get("key")]
    completed_map: Dict[str, str] = {}
    if recommendation_keys:
        placeholders = ",".join(["?"] * len(recommendation_keys))
        conn2 = get_db_connection()
        cur2 = conn2.cursor()
        cur2.execute(
            f"""
            SELECT action_key, MAX(completed_at) as last_done
            FROM decision_actions
            WHERE completed_by=? AND action_key IN ({placeholders})
            GROUP BY action_key
            """,
            [_parse_int(current_user.get("id"), 0)] + recommendation_keys,
        )
        for row in cur2.fetchall():
            rd = row_to_dict(row) or {}
            if rd.get("action_key"):
                completed_map[str(rd.get("action_key"))] = str(rd.get("last_done") or "")
        cur2.close()
        conn2.close()

    for r in recommendations:
        k = str(r.get("key") or "")
        if k in completed_map:
            r["completed_at"] = completed_map[k]

    return jsonify({
        "kpis": {
            "total_students": total_students,
            "low_attendance_count": low_attendance_count,
            "low_attendance_pct": low_attendance_pct,
            "open_risk_alerts": open_risk_alerts,
            "overdue_submission_count": overdue_submission_count,
            "avg_attendance_last_14d": round(avg_att_last_14, 2),
            "avg_attendance_prev_14d": round(avg_att_prev_14, 2),
            "avg_predicted_last_14d": round(avg_pred_last_14, 2),
            "avg_predicted_prev_14d": round(avg_pred_prev_14, 2),
            "attendance_trend_delta": attendance_drop,
            "predicted_trend_delta": predicted_drop,
        },
        "recommendations": recommendations[:8],
        "generated_at": datetime.utcnow().isoformat(),
    }), 200

@app.route('/faculty/decision-support/actions', methods=['POST'])
@token_required
def faculty_decision_action(current_user):
    if current_user.get("role") not in ["faculty", "admin"]:
        return jsonify({"message": "Unauthorized!"}), 403
    data = request.get_json() or {}
    action_key = str(data.get("action_key") or "").strip()
    title = str(data.get("title") or "").strip()
    details = str(data.get("details") or "").strip()
    if len(action_key) < 2 or len(action_key) > 120:
        return jsonify({"message": "Invalid action_key"}), 400
    if len(title) < 3 or len(title) > 200:
        return jsonify({"message": "Invalid title"}), 400
    if len(details) > 2000:
        return jsonify({"message": "Details too long"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO decision_actions (action_key, title, details, completed_by)
        VALUES (?, ?, ?, ?)
        """,
        (action_key, title, details, _parse_int(current_user.get("id"), 0)),
    )
    action_id = cursor.lastrowid
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({
        "message": "Decision action marked done",
        "action_id": action_id,
        "completed_at": datetime.utcnow().isoformat()
    }), 201

@app.route('/faculty/decision-support/actions/history', methods=['GET'])
@token_required
def faculty_decision_actions_history(current_user):
    if current_user.get("role") not in ["faculty", "admin"]:
        return jsonify({"message": "Unauthorized!"}), 403

    user_id = _parse_int(current_user.get("id"), 0)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT date(completed_at) as day, COUNT(*) as count
        FROM decision_actions
        WHERE completed_by=?
          AND completed_at >= datetime('now', '-6 day')
        GROUP BY date(completed_at)
        ORDER BY day ASC
        """,
        (user_id,),
    )
    rows = [row_to_dict(r) for r in cursor.fetchall()]
    count_by_day = {str(r.get("day")): int(r.get("count") or 0) for r in rows}

    labels: List[str] = []
    daily_counts: List[int] = []
    for i in range(6, -1, -1):
        d = (datetime.utcnow() - timedelta(days=i)).date().isoformat()
        labels.append(d)
        daily_counts.append(int(count_by_day.get(d, 0)))

    cursor.execute(
        """
        SELECT action_key, title, completed_at
        FROM decision_actions
        WHERE completed_by=?
          AND completed_at >= datetime('now', '-7 day')
        ORDER BY completed_at DESC
        LIMIT 10
        """,
        (user_id,),
    )
    recent = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()

    return jsonify({
        "total_last_7_days": int(sum(daily_counts)),
        "daily": [{"day": labels[idx], "count": daily_counts[idx]} for idx in range(len(labels))],
        "recent": recent,
    }), 200

@app.route('/students/import', methods=['POST'])
@token_required
def import_students_csv(current_user):
    if current_user.get("role") not in ["admin", "faculty"]:
        return jsonify({"message": "Unauthorized!"}), 403

    file = request.files.get("file")
    if not file:
        return jsonify({"message": "CSV file required as form-data 'file'"}), 400

    raw = file.read()
    try:
        text = raw.decode("utf-8-sig")
    except Exception:
        text = raw.decode("utf-8", errors="replace")

    reader = csv.DictReader(io.StringIO(text))
    required = {"name"}
    if not reader.fieldnames or not required.issubset(set([h.strip() for h in reader.fieldnames if h])):
        return jsonify({"message": "CSV must include at least a 'name' column"}), 400

    inserted = 0
    skipped = 0
    errors: List[Dict[str, Any]] = []

    conn = get_db_connection()
    cursor = conn.cursor()
    for idx, row in enumerate(reader, start=2):  # header is line 1
        try:
            name = str((row.get("name") or "")).strip()
            if len(name) < 2 or len(name) > 80:
                skipped += 1
                continue
            attendance = _parse_int(row.get("attendance"), 0)
            study_hours = _parse_float(row.get("study_hours"), 0.0)
            sleep_hours = _parse_float(row.get("sleep_hours"), 0.0)
            if attendance < 0 or attendance > 100:
                skipped += 1
                continue
            if study_hours < 0 or study_hours > 24 or sleep_hours < 0 or sleep_hours > 24:
                skipped += 1
                continue

            cursor.execute(
                "INSERT INTO students (name, attendance, study_hours, sleep_hours) VALUES (?, ?, ?, ?)",
                (name, attendance, study_hours, sleep_hours),
            )
            sid = cursor.lastrowid
            inserted += 1
            try:
                _snapshot_student_metrics(
                    student_id=int(sid),
                    attendance=float(attendance),
                    study_hours=float(study_hours),
                    sleep_hours=float(sleep_hours),
                )
                _create_alert_if_needed(int(sid), float(attendance), float(study_hours), float(sleep_hours))
            except Exception:
                pass
        except Exception as e:
            errors.append({"line": idx, "error": str(e)})

    conn.commit()
    cursor.close()
    conn.close()

    _cache_invalidate("dashboard:")
    _cache_invalidate("analytics:")
    _cache_invalidate("insights:")
    _cache_invalidate("alerts:")

    return jsonify({"inserted": inserted, "skipped": skipped, "errors": errors[:20]}), 200

@app.route('/attendance/bulk', methods=['POST'])
@token_required
def attendance_bulk(current_user):
    if current_user.get("role") not in ["admin", "faculty"]:
        return jsonify({"message": "Unauthorized!"}), 403

    data = request.get_json() or {}
    date = str(data.get("date") or "").strip()
    items = data.get("items") or []
    if not date:
        return jsonify({"message": "date required"}), 400
    if not isinstance(items, list) or len(items) == 0:
        return jsonify({"message": "items must be a non-empty list"}), 400
    if len(items) > 300:
        return jsonify({"message": "Too many items (max 300)"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    inserted = 0
    skipped = 0
    for it in items:
        student_id = _parse_int((it or {}).get("student_id"), 0)
        status = str((it or {}).get("status") or "").strip()
        notes = str((it or {}).get("notes") or "")
        if student_id <= 0 or status not in ["present", "absent"] or len(notes) > 500:
            skipped += 1
            continue
        cursor.execute(
            "INSERT INTO attendance (student_id, date, status, notes) VALUES (?, ?, ?, ?)",
            (student_id, date, status, notes),
        )
        inserted += 1

    conn.commit()
    cursor.close()
    conn.close()

    _cache_invalidate("dashboard:")
    _cache_invalidate("analytics:")
    _cache_invalidate("student_profile:")
    _cache_invalidate("alerts:")
    socketio.emit('attendance_update')
    socketio.emit('dashboard_update')
    return jsonify({"inserted": inserted, "skipped": skipped}), 200

@app.route('/payments', methods=['GET', 'POST'])
@token_required
def payments(current_user):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if request.method == 'GET':
        cursor.execute("SELECT * FROM payments")
        payments_list = [row_to_dict(row) for row in cursor.fetchall()]
        cursor.close()
        conn.close()
        return jsonify(payments_list), 200
    
    if request.method == 'POST':
        if current_user.get('role') not in ['admin', 'faculty']:
            return jsonify({'message': 'Unauthorized!'}), 403

        data = request.get_json() or {}
        student_id = _parse_int(data.get('student_id'), 0)
        amount = _parse_float(data.get('amount'), 0.0)
        if student_id <= 0:
            return jsonify({'message': 'Invalid student_id'}), 400
        if amount <= 0:
            return jsonify({'message': 'Invalid amount'}), 400

        cursor.execute("""
            INSERT INTO payments (student_id, amount, status, payment_id)
            VALUES (?, ?, ?, ?)
        """, (student_id, amount, 'completed', f'test_pay_{datetime.now().strftime("%Y%m%d%H%M%S")}'))
        
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({'message': 'Payment successful!'}), 201

@app.route('/monitoring/stats', methods=['GET'])
@token_required
def monitoring_stats(current_user):
    if current_user.get("role") != "admin":
        return jsonify({"message": "Unauthorized!"}), 403
    uptime_seconds = int(time.time() - _METRICS["started_at"])
    payload = {
        "uptime_seconds": uptime_seconds,
        "total_requests": _METRICS["total_requests"],
        "error_requests": _METRICS["error_requests"],
        "active_users_15m": _active_users_count(),
        "jobs_open": len([a for a in _JOBS.values() if a.get("status") in ("queued", "running")]),
        "jobs_total": len(_JOBS),
        "jobs_running": len([j for j in _JOBS.values() if j.get("status") == "running"]),
        "last_errors": _METRICS["last_errors"][-10:],
    }
    return jsonify(payload), 200

def _job_generate_full_report() -> Dict[str, Any]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM students")
    total_students = cursor.fetchone()[0]
    cursor.execute("SELECT AVG(attendance) FROM students")
    avg_attendance = float(cursor.fetchone()[0] or 0)
    cursor.execute("SELECT COUNT(*) FROM attendance WHERE status='present'")
    present_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM attendance")
    attendance_rows = cursor.fetchone()[0]
    cursor.close()
    conn.close()

    filename = f"full_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    out_path = os.path.join(BACKUP_DIR, filename)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["metric", "value"])
        w.writerow(["total_students", total_students])
        w.writerow(["avg_attendance", round(avg_attendance, 2)])
        w.writerow(["attendance_present_count", present_count])
        w.writerow(["attendance_total_records", attendance_rows])
    return {"file": filename}

def _job_retrain_model_dummy() -> Dict[str, Any]:
    # Placeholder background retrain task for demo/interview purposes.
    time.sleep(2)
    return {"message": "Retraining completed (demo mode)", "model": "RandomForestRegressor"}

@app.route('/jobs/retrain-model', methods=['POST'])
@token_required
def start_retrain_job(current_user):
    if current_user.get("role") not in ["admin", "faculty"]:
        return jsonify({"message": "Unauthorized!"}), 403
    job_id = str(uuid.uuid4())
    _run_background_job(job_id, "retrain_model", _job_retrain_model_dummy)
    return jsonify({"job_id": job_id, "status": "queued"}), 202

@app.route('/jobs/full-report', methods=['POST'])
@token_required
def start_full_report_job(current_user):
    if current_user.get("role") not in ["admin", "faculty"]:
        return jsonify({"message": "Unauthorized!"}), 403
    job_id = str(uuid.uuid4())
    _run_background_job(job_id, "full_report", _job_generate_full_report)
    return jsonify({"job_id": job_id, "status": "queued"}), 202

@app.route('/jobs/<job_id>', methods=['GET'])
@token_required
def get_job_status(current_user, job_id):
    if current_user.get("role") not in ["admin", "faculty"]:
        return jsonify({"message": "Unauthorized!"}), 403
    job = _JOBS.get(job_id)
    if not job:
        return jsonify({"message": "Job not found"}), 404
    return jsonify(job), 200

@app.route('/backup/create', methods=['POST'])
@token_required
def create_backup(current_user):
    if current_user.get("role") != "admin":
        return jsonify({"message": "Unauthorized!"}), 403
    if not os.path.exists(DB_PATH):
        return jsonify({"message": "Database not found"}), 404
    filename = f"student_system_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    out_path = os.path.join(BACKUP_DIR, filename)
    shutil.copy2(DB_PATH, out_path)
    logger.info("Backup created: %s", filename)
    return jsonify({"message": "Backup created", "file": filename}), 201

@app.route('/backup/list', methods=['GET'])
@token_required
def list_backups(current_user):
    if current_user.get("role") != "admin":
        return jsonify({"message": "Unauthorized!"}), 403
    files = []
    for fn in sorted(os.listdir(BACKUP_DIR), reverse=True):
        p = os.path.join(BACKUP_DIR, fn)
        if os.path.isfile(p):
            files.append({"file": fn, "size_bytes": os.path.getsize(p)})
    return jsonify({"items": files}), 200

@app.route('/backup/download/<filename>', methods=['GET'])
@token_required
def download_backup(current_user, filename):
    if current_user.get("role") != "admin":
        return jsonify({"message": "Unauthorized!"}), 403
    return send_from_directory(BACKUP_DIR, filename, as_attachment=True)

@app.route('/frontend/<path:filename>')
def serve_frontend(filename):
    frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'frontend')
    return send_from_directory(frontend_dir, filename)

@app.route('/')
def index():
    return jsonify({
        'message': 'Student Management System API is running!',
        'status': 'success',
        'login_creds': {
            'mobile': '1234567890',
            'password': 'admin123'
        },
        'frontend_instructions': 'Open frontend/login.html in your browser!'
    })

@app.route('/docs', methods=['GET'])
def docs():
    return send_from_directory(BACKEND_DIR, 'API_DOCS.md')

# AI LEARNING FEATURES & ERP EXTENSIONS

@app.route('/quizzes', methods=['GET'])
@token_required
def get_quizzes_list(current_user):
    return jsonify({"items": [{"id": 1, "title": "Midterm Prep", "topic": "General", "difficulty": "Medium"}]}), 200

@app.route('/quizzes/<int:id>', methods=['GET'])
@token_required
def get_quiz_detail(current_user, id):
    return jsonify({
        "quiz": {"id": id, "title": "Midterm Prep", "topic": "General", "difficulty": "Medium"},
        "questions": [
            {"id": 1, "question_text": "What is 2+2?", "option_a": "3", "option_b": "4", "option_c": "5", "option_d": "6", "correct_option": "B"},
            {"id": 2, "question_text": "Capital of France?", "option_a": "London", "option_b": "Paris", "option_c": "Berlin", "option_d": "Madrid", "correct_option": "B"}
        ]
    }), 200

@app.route('/quizzes/<int:id>/submit', methods=['POST'])
@token_required
def submit_quiz_result(current_user, id):
    return jsonify({"score": 100, "correct": 2, "total": 2}), 200

@app.route('/weak-topics/me', methods=['GET'])
@token_required
def get_weak_topics(current_user):
    return jsonify({"weak_topics": [{"topic": "Mathematics", "avg_score": 45.5}]}), 200

@app.route('/effort-analysis/me', methods=['GET'])
@token_required
def get_effort_analysis(current_user):
    return jsonify({"insight": "Good consistency", "effort_score": 85, "predicted_marks": 88}), 200

@app.route('/attendance/self-report', methods=['POST'])
@token_required
def self_report_attendance(current_user):
    return jsonify({"message": "Self report submitted"}), 200

@app.route('/recommendations/me', methods=['GET'])
@token_required
def get_my_recommendations(current_user):
    student_id = _get_student_id(current_user['id'])
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT s.attendance, s.study_hours, d.stream FROM students s LEFT JOIN departments_master d ON d.id = s.department_id WHERE s.id=?", (student_id,))
    row = cursor.fetchone()
    if not row: return jsonify({"recommendations": []}), 200
    att, study, stream = row[0], row[1], row[2]
    
    recs = []
    if att < 75: recs.append("Increase attendance to 75%+ to avoid eligibility risk.")
    if study < 3: recs.append("Target at least 4 hours of focused study daily.")
    if stream == 'engineering': recs.append("Practice 2 coding problems on LeetCode today.")
    elif stream == 'medical': recs.append("Review Anatomy diagrams for 30 mins.")
    
    return jsonify({"recommendations": recs}), 200

@app.route('/weekly-report/me', methods=['GET'])
@token_required
def get_weekly_report(current_user):
    return jsonify({"trend": {"attendance_avg": 2.5, "study_hours_avg": 1.2, "predicted_marks_avg": 3.4}}), 200

@app.route('/attendance/alerts/me', methods=['GET'])
@token_required
def get_attendance_alerts(current_user):
    return jsonify({"alerts": ["Missing Labs: 2", "Lecture Shortage: 5%"]}), 200

@app.route('/performance/me', methods=['GET'])
@token_required
def get_performance_breakdown(current_user):
    return jsonify({"focus_score": 78, "impacts": [{"feature": "study_hours", "impact": 12}, {"feature": "sleep", "impact": -5}]}), 200

@app.route('/study-planner/me', methods=['GET', 'POST'])
@token_required
def handle_study_planner(current_user):
    if request.method == 'POST':
        data = request.get_json()
        return jsonify({
            "exam_date": data.get('exam_date'),
            "weak_subjects": data.get('weak_subjects', '').split(','),
            "available_hours": data.get('available_hours'),
            "schedule": [
                {"day": "Monday", "focus_subject": "Math", "tasks": ["Chapter 1", "Practice problems"]},
                {"day": "Tuesday", "focus_subject": "Physics", "tasks": ["Formulas", "Past papers"]}
            ]
        }), 200
    return jsonify({"message": "No plan yet"}), 404

@app.route('/learning/progress/me', methods=['GET', 'POST'])
@token_required
def handle_learning_hub(current_user):
    if request.method == 'POST':
        return jsonify({"message": "Progress saved"}), 200
    return jsonify({
        "overall_progress": 62,
        "items": [
            {"id": 1, "subject": "CS", "title": "Algorithms", "resource_type": "video", "content_url": "#", "progress_pct": 85},
            {"id": 2, "subject": "AI", "title": "Neural Networks", "resource_type": "pdf", "content_url": "#", "progress_pct": 30}
        ]
    }), 200

@app.route('/goals/me', methods=['GET', 'POST'])
@token_required
def handle_goals(current_user):
    return jsonify({"current": {"estimated_cgpa": 8.2, "attendance": 88, "study_hours": 4.5}, "progress": {"cgpa": 90, "attendance": 95, "study_hours": 80}}), 200

@app.route('/effort-insight/me', methods=['GET'])
@token_required
def get_effort_insight(current_user):
    return jsonify({"insight": "High effort in Labs, needs improvement in Theory."}), 200

@app.route('/quizzes/me', methods=['GET'])
@token_required
def get_my_quizzes(current_user):
    student_id = _get_student_id(current_user['id'])
    if not student_id:
        return jsonify({"message": "Not a student"}), 403
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT department_id FROM students WHERE id=?", (student_id,))
    row = cursor.fetchone()
    dept_id = row[0] if row else 1
    
    cursor.execute("SELECT name FROM subjects_master WHERE department_id=?", (dept_id,))
    subjects = cursor.fetchall()
    subject_name = subjects[0][0] if subjects else "General Knowledge"
    
    questions = [
        {"id": 1, "text": f"Basic concept of {subject_name}?", "options": ["A", "B", "C", "D"], "answer": 0},
        {"id": 2, "text": f"Advanced {subject_name} tool?", "options": ["X", "Y", "Z", "W"], "answer": 1}
    ]
    
    cursor.close()
    conn.close()
    return jsonify({
        "subject_name": subject_name,
        "questions": questions,
        "time_limit_mins": 15
    }), 200

@app.route('/quizzes/leaderboard/<int:quiz_id>', methods=['GET'])
@token_required
def get_quiz_leaderboard(current_user, quiz_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT s.name, qs.score, qs.total_questions, qs.submitted_at
        FROM quiz_submissions qs
        JOIN students s ON s.id = qs.student_id
        WHERE qs.quiz_id = ?
        ORDER BY qs.score DESC, qs.submitted_at ASC
        LIMIT 10
    """, (quiz_id,))
    rows = cursor.fetchall()
    leaderboard = [row_to_dict(r) for r in rows]
    cursor.close()
    conn.close()
    return jsonify({"leaderboard": leaderboard}), 200

@app.route('/faculty/analytics', methods=['GET'])
@token_required
def get_faculty_analytics(current_user):
    if current_user['role'] != 'faculty':
        return jsonify({"message": "Forbidden"}), 403
        
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Class Average Attendance
    cursor.execute("SELECT AVG(attendance) FROM students")
    avg_att = cursor.fetchone()[0] or 0
    
    # Risk Students (Attendance < 75)
    cursor.execute("""
        SELECT s.id, s.name, s.attendance, d.name as dept_name
        FROM students s
        LEFT JOIN departments_master d ON d.id = s.department_id
        WHERE s.attendance < 75
        ORDER BY s.attendance ASC
        LIMIT 10
    """)
    risk_students = [row_to_dict(r) for r in cursor.fetchall()]
    
    # Quiz Performance (Average scores)
    cursor.execute("""
        SELECT q.title, AVG(qs.score) as avg_score, COUNT(qs.id) as total_submissions
        FROM quizzes q
        LEFT JOIN quiz_submissions qs ON qs.quiz_id = q.id
        GROUP BY q.id
        LIMIT 5
    """)
    quiz_stats = [row_to_dict(r) for r in cursor.fetchall()]
    
    cursor.close()
    conn.close()
    return jsonify({
        "average_attendance": round(avg_att, 2),
        "risk_students": risk_students,
        "quiz_stats": quiz_stats
    }), 200

@app.route('/admin/payments', methods=['GET'])
@token_required
def get_admin_payments(current_user):
    if current_user['role'] != 'admin':
        return jsonify({"message": "Forbidden"}), 403
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Recent Payments
    cursor.execute("""
        SELECT p.id, s.name as student_name, p.amount, p.status, p.created_at
        FROM payments p
        JOIN students s ON s.id = p.student_id
        ORDER BY p.created_at DESC
        LIMIT 20
    """)
    payments = [row_to_dict(r) for r in cursor.fetchall()]
    
    # Total Collected
    cursor.execute("SELECT SUM(amount) FROM payments WHERE status='completed'")
    total_collected = cursor.fetchone()[0] or 0
    
    # Pending Count
    cursor.execute("SELECT COUNT(*) FROM payments WHERE status='pending'")
    pending_count = cursor.fetchone()[0] or 0
    
    cursor.close()
    conn.close()
    return jsonify({
        "recent_payments": payments,
        "total_collected": round(total_collected, 2),
        "pending_count": pending_count
    }), 200

# PARENT PORTAL APIS

@app.route('/parent/notification-settings', methods=['GET', 'POST'])
@token_required
def parent_notif_settings(current_user):
    if current_user.get("role") != "parent":
        return jsonify({"message": "Unauthorized!"}), 403
    parent_id = _parse_int(current_user.get("id"), 0)
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if request.method == 'POST':
        data = request.get_json()
        cursor.execute("""
            INSERT INTO parent_notification_settings (parent_id, email_enabled, sms_enabled, app_enabled)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(parent_id) DO UPDATE SET
            email_enabled=excluded.email_enabled,
            sms_enabled=excluded.sms_enabled,
            app_enabled=excluded.app_enabled
        """, (parent_id, data.get('email', 1), data.get('sms', 0), data.get('app', 1)))
        conn.commit()
        return jsonify({"message": "Settings updated"}), 200
        
    cursor.execute("SELECT * FROM parent_notification_settings WHERE parent_id = ?", (parent_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    if not row:
        return jsonify({"email": 1, "sms": 0, "app": 1}), 200
    return jsonify(row_to_dict(row)), 200

@app.route('/parent/performance-insights', methods=['GET'])
@token_required
def parent_performance_insights(current_user):
    if current_user.get("role") != "parent":
        return jsonify({"message": "Unauthorized!"}), 403
    student_id = _parse_int(current_user.get("student_id"), 0)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Class comparison (simplified: average of all students in same dept)
    cursor.execute("SELECT department_id FROM students WHERE id = ?", (student_id,))
    dept_id = cursor.fetchone()[0]
    
    cursor.execute("SELECT AVG(attendance) as avg_att, AVG(study_hours) as avg_study FROM students WHERE department_id = ?", (dept_id,))
    dept_avg = row_to_dict(cursor.fetchone())
    
    # Weak subjects (based on quiz scores)
    cursor.execute("""
        SELECT s.name as subject_name, AVG(qs.score) as avg_score
        FROM quiz_submissions qs
        JOIN quizzes q ON q.id = qs.quiz_id
        JOIN subjects_master s ON s.id = q.topic -- Assuming topic links to subject or similar
        WHERE qs.student_id = ?
        GROUP BY s.name
        HAVING avg_score < 60
    """, (student_id,))
    weak_subjects = [row_to_dict(r) for r in cursor.fetchall()]
    
    cursor.close()
    conn.close()
    
    return jsonify({
        "class_comparison": dept_avg,
        "weak_subjects": weak_subjects,
        "improvement_trend": "Improving in attendance, needs focus on Mathematics."
    }), 200

# END PARENT PORTAL APIS

# FACULTY PHASE 3 APIS

@app.route('/faculty/lesson-plans', methods=['GET', 'POST'])
@token_required
def handle_lesson_plans(current_user):
    if current_user['role'] != 'faculty':
        return jsonify({"message": "Unauthorized"}), 403
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if request.method == 'POST':
        data = request.get_json()
        cursor.execute("""
            INSERT INTO lesson_plans (faculty_id, subject_id, topic, week_number, learning_outcomes)
            VALUES (?, ?, ?, ?, ?)
        """, (current_user['id'], data['subject_id'], data['topic'], data.get('week_number'), data.get('learning_outcomes')))
        conn.commit()
        return jsonify({"message": "Lesson plan added"}), 201
        
    cursor.execute("""
        SELECT lp.*, s.name as subject_name 
        FROM lesson_plans lp 
        JOIN subjects_master s ON s.id = lp.subject_id 
        WHERE lp.faculty_id = ?
    """, (current_user['id'],))
    plans = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"items": plans}), 200

@app.route('/faculty/ai-generate-assignment', methods=['POST'])
@token_required
def ai_generate_assignment(current_user):
    if current_user['role'] != 'faculty':
        return jsonify({"message": "Unauthorized"}), 403
    
    data = request.get_json()
    topic = data.get('topic', 'General')
    difficulty = data.get('difficulty', 'intermediate')
    
    # Mock AI generation logic
    questions = [
        {"q": f"Explain the fundamental concepts of {topic}.", "type": "Theory"},
        {"q": f"Solve a problem related to {topic} at {difficulty} level.", "type": "Problem"},
        {"q": f"Compare {topic} with its alternatives.", "type": "Analysis"}
    ]
    
    return jsonify({
        "topic": topic,
        "difficulty": difficulty,
        "generated_questions": questions,
        "suggested_due_date": (datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d')
    }), 200

@app.route('/faculty/topic-analytics', methods=['GET'])
@token_required
def get_topic_analytics(current_user):
    if current_user['role'] != 'faculty':
        return jsonify({"message": "Unauthorized"}), 403
        
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM topic_analytics ORDER BY fail_rate DESC")
    analytics = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"items": analytics}), 200

@app.route('/faculty/voice-notes', methods=['GET', 'POST'])
@token_required
def handle_voice_notes(current_user):
    if current_user['role'] != 'faculty':
        return jsonify({"message": "Unauthorized"}), 403
        
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if request.method == 'POST':
        data = request.get_json()
        cursor.execute("""
            INSERT INTO voice_notes (faculty_id, subject_id, title, audio_url)
            VALUES (?, ?, ?, ?)
        """, (current_user['id'], data['subject_id'], data['title'], data['audio_url']))
        conn.commit()
        return jsonify({"message": "Voice note uploaded"}), 201
        
    cursor.execute("SELECT * FROM voice_notes WHERE faculty_id = ?", (current_user['id'],))
    notes = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"items": notes}), 200

# END FACULTY PHASE 3 APIS

# ACADEMIC & CAREER TOOLS APIS

@app.route('/exams/mock-tests', methods=['GET'])
@token_required
def get_mock_tests(current_user):
    exam_type = request.args.get('type')
    conn = get_db_connection()
    cursor = conn.cursor()
    if exam_type:
        cursor.execute("SELECT * FROM mock_tests WHERE exam_type = ?", (exam_type,))
    else:
        cursor.execute("SELECT * FROM mock_tests")
    tests = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"items": tests}), 200

@app.route('/exams/submit', methods=['POST'])
@token_required
def submit_mock_test(current_user):
    student_id = _get_student_id(current_user['id'])
    data = request.get_json()
    test_id = data.get('test_id')
    score = data.get('score')
    
    # Simple logic for rank/percentile prediction
    # In a real app, this would query historical data
    rank_predicted = 100 - int(score) if score < 100 else 1
    percentile = score
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO mock_test_submissions (test_id, student_id, score, rank_predicted, percentile)
        VALUES (?, ?, ?, ?, ?)
    """, (test_id, student_id, score, rank_predicted, percentile))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({
        "message": "Test submitted",
        "rank": rank_predicted,
        "percentile": percentile
    }), 201

@app.route('/planner/goals', methods=['GET', 'POST'])
@token_required
def handle_academic_goals(current_user):
    student_id = _get_student_id(current_user['id'])
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if request.method == 'POST':
        data = request.get_json()
        cursor.execute("""
            INSERT INTO academic_goals (student_id, goal_text, target_date)
            VALUES (?, ?, ?)
        """, (student_id, data['goal_text'], data.get('target_date')))
        conn.commit()
        return jsonify({"message": "Goal added"}), 201
    
    cursor.execute("SELECT * FROM academic_goals WHERE student_id = ? ORDER BY created_at DESC", (student_id,))
    goals = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"items": goals}), 200

@app.route('/cgpa/predict', methods=['GET'])
@token_required
def predict_cgpa(current_user):
    if current_user.get("role") != "student":
        return jsonify({"message": "Unauthorized!"}), 403
    student_id = _get_linked_student_id(int(current_user.get("id", 0)))
    if not student_id:
        return jsonify({"message": "Student account not linked"}), 409
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Fetch student data for prediction
    cursor.execute("SELECT attendance, study_hours, sleep_hours FROM students WHERE id = ?", (student_id,))
    row = cursor.fetchone()
    if not row:
        return jsonify({"message": "Student data not found"}), 404
        
    att, study, sleep = row
    
    # Use existing ML model to predict marks, then convert to CGPA
    predicted_marks = predict_marks(study, sleep, att)
    predicted_cgpa = round((predicted_marks / 100) * 10, 2)
    
    cursor.close()
    conn.close()
    return jsonify({
        "predicted_cgpa": predicted_cgpa,
        "predicted_marks": predicted_marks,
        "factors": {
            "attendance": att,
            "study_hours": study,
            "sleep_hours": sleep
        }
    }), 200

# END ACADEMIC & CAREER TOOLS APIS

# UNIVERSITY ECOSYSTEM APIS

@app.route('/library/books', methods=['GET'])
@token_required
def get_library_books(current_user):
    search = request.args.get('search', '')
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM library_books WHERE title LIKE ? OR author LIKE ? OR category LIKE ?", 
                   (f'%{search}%', f'%{search}%', f'%{search}%'))
    books = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"items": books}), 200

@app.route('/placement/jobs', methods=['GET'])
@token_required
def get_placement_jobs(current_user):
    job_type = request.args.get('type', 'full-time')
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM placement_jobs WHERE job_type = ? ORDER BY created_at DESC", (job_type,))
    jobs = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"items": jobs}), 200

@app.route('/campus/hostels', methods=['GET'])
@token_required
def get_hostels(current_user):
    student_id = _get_student_id(current_user['id'])
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT hr.*,
               MAX(hr.capacity - hr.occupied, 0) as available_slots
        FROM hostel_rooms hr
        ORDER BY hr.block, hr.room_number
        """
    )
    rooms = [row_to_dict(r) for r in cursor.fetchall()]
    my_allocation = None
    if student_id:
        cursor.execute(
            """
            SELECT ha.*, hr.block, hr.room_number, hr.fee_per_sem
            FROM hostel_allocations ha
            JOIN hostel_rooms hr ON hr.id = ha.room_id
            WHERE ha.student_id = ? AND ha.status = 'allocated'
            ORDER BY ha.id DESC
            LIMIT 1
            """,
            (student_id,),
        )
        my_allocation = row_to_dict(cursor.fetchone())
    cursor.close()
    conn.close()
    return jsonify({"items": rooms, "my_allocation": my_allocation}), 200

@app.route('/campus/hostel/book', methods=['POST'])
@token_required
def book_hostel_room(current_user):
    student_id = _get_student_id(current_user['id'])
    if not student_id:
        return jsonify({"message": "Student account required"}), 403

    data = request.get_json() or {}
    room_id = _parse_int(data.get('room_id'), 0)
    if room_id <= 0:
        return jsonify({"message": "Invalid room_id"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM hostel_allocations WHERE student_id = ? AND status = 'allocated'",
        (student_id,),
    )
    if cursor.fetchone():
        cursor.close()
        conn.close()
        return jsonify({"message": "Hostel room already allocated"}), 409

    cursor.execute("SELECT id, capacity, occupied FROM hostel_rooms WHERE id = ?", (room_id,))
    room = cursor.fetchone()
    if not room:
        cursor.close()
        conn.close()
        return jsonify({"message": "Room not found"}), 404
    if _parse_int(room["occupied"]) >= _parse_int(room["capacity"]):
        cursor.close()
        conn.close()
        return jsonify({"message": "Room is fully occupied"}), 409

    cursor.execute(
        "INSERT INTO hostel_allocations (student_id, room_id, status) VALUES (?, ?, 'allocated')",
        (student_id, room_id),
    )
    cursor.execute(
        "UPDATE hostel_rooms SET occupied = occupied + 1 WHERE id = ?",
        (room_id,),
    )
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"message": "Hostel room booked successfully"}), 201

@app.route('/campus/transport-routes', methods=['GET'])
@token_required
def get_transport_routes(current_user):
    student_id = _get_student_id(current_user['id'])
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM transport_routes ORDER BY route_name ASC")
    routes = [row_to_dict(r) for r in cursor.fetchall()]
    my_allocation = None
    if student_id:
        cursor.execute(
            """
            SELECT ta.*, tr.route_name, tr.bus_number, tr.driver_name, tr.driver_contact, tr.fee_per_sem
            FROM transport_allocations ta
            JOIN transport_routes tr ON tr.id = ta.route_id
            WHERE ta.student_id = ? AND ta.status = 'registered'
            ORDER BY ta.id DESC
            LIMIT 1
            """,
            (student_id,),
        )
        my_allocation = row_to_dict(cursor.fetchone())
    cursor.close()
    conn.close()
    return jsonify({"items": routes, "my_allocation": my_allocation}), 200

@app.route('/campus/transport/register', methods=['POST'])
@token_required
def register_transport(current_user):
    student_id = _get_student_id(current_user['id'])
    if not student_id:
        return jsonify({"message": "Student account required"}), 403

    data = request.get_json() or {}
    route_id = _parse_int(data.get('route_id'), 0)
    pickup_point = str(data.get('pickup_point') or '').strip()
    if route_id <= 0:
        return jsonify({"message": "Invalid route_id"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM transport_allocations WHERE student_id = ? AND status = 'registered'",
        (student_id,),
    )
    if cursor.fetchone():
        cursor.close()
        conn.close()
        return jsonify({"message": "Transport route already registered"}), 409

    cursor.execute("SELECT id FROM transport_routes WHERE id = ?", (route_id,))
    if not cursor.fetchone():
        cursor.close()
        conn.close()
        return jsonify({"message": "Route not found"}), 404

    cursor.execute(
        """
        INSERT INTO transport_allocations (student_id, route_id, pickup_point, status)
        VALUES (?, ?, ?, 'registered')
        """,
        (student_id, route_id, pickup_point),
    )
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"message": "Transport registered successfully"}), 201

@app.route('/campus/complaints', methods=['GET', 'POST'])
@token_required
def campus_complaints(current_user):
    student_id = _get_student_id(current_user['id'])
    if not student_id:
        return jsonify({"message": "Student account required"}), 403

    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'POST':
        data = request.get_json() or {}
        category = str(data.get('category') or 'general').strip().lower()
        subject = str(data.get('subject') or '').strip()
        description = str(data.get('description') or '').strip()
        if not subject or not description:
            cursor.close()
            conn.close()
            return jsonify({"message": "Subject and description are required"}), 400

        cursor.execute(
            """
            INSERT INTO campus_complaints (student_id, category, subject, description, status)
            VALUES (?, ?, ?, ?, 'open')
            """,
            (student_id, category, subject, description),
        )
        conn.commit()
        complaint_id = cursor.lastrowid
        cursor.close()
        conn.close()
        return jsonify({"message": "Complaint submitted successfully", "id": complaint_id}), 201

    cursor.execute(
        """
        SELECT *
        FROM campus_complaints
        WHERE student_id = ?
        ORDER BY id DESC
        """,
        (student_id,),
    )
    rows = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"items": rows}), 200

@app.route('/ai/solve-doubt', methods=['POST'])
@token_required
def solve_doubt(current_user):
    data = request.get_json() or {}
    subject = data.get('subject', 'General')
    doubt = data.get('doubt', '')
    
    if not doubt:
        return jsonify({"message": "Doubt text is required"}), 400
        
    # Simulate AI processing time
    time.sleep(1)
    
    # Simple keyword-based mock AI response
    explanation = f"Based on your question about '{doubt}' in {subject}, here is a comprehensive explanation. "
    explanation += "This concept is fundamental to understanding higher-level topics in this field. "
    explanation += "It involves analyzing the relationship between various components and ensuring that all constraints are met."
    
    notes = [
        "Focus on the core definitions first.",
        "Practice solving 3-4 basic problems daily.",
        "Refer to the standard textbook for detailed proofs.",
        "Check the previous year's questions for similar patterns."
    ]
    
    related_topics = [f"{subject} Basics", "Advanced Theory", "Practical Applications", "Case Studies"]
    
    return jsonify({
        "explanation": explanation,
        "notes": notes,
        "related_topics": related_topics
    }), 200

@app.route('/forum/topics', methods=['GET', 'POST'])
@token_required
def forum_topics(current_user):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if request.method == 'POST':
        data = request.get_json() or {}
        title = str(data.get('title') or '').strip()
        description = str(data.get('description') or '').strip()
        if not title:
            cursor.close()
            conn.close()
            return jsonify({"message": "Title is required"}), 400
            
        cursor.execute(
            "INSERT INTO forum_topics (title, description, created_by) VALUES (?, ?, ?)",
            (title, description, current_user['id'])
        )
        conn.commit()
        topic_id = cursor.lastrowid
        cursor.close()
        conn.close()
        return jsonify({"message": "Topic created", "id": topic_id}), 201

    cursor.execute("""
        SELECT ft.*, u.name as author_name 
        FROM forum_topics ft 
        JOIN users u ON u.id = ft.created_by 
        ORDER BY ft.created_at DESC
    """)
    topics = [row_to_dict(r) for r in cursor.fetchall()]
    
    # Get reply counts
    for t in topics:
        cursor.execute("SELECT COUNT(*) FROM forum_replies WHERE topic_id = ?", (t['id'],))
        t['reply_count'] = cursor.fetchone()[0]
        
    cursor.close()
    conn.close()
    return jsonify({"items": topics}), 200

@app.route('/forum/topics/<int:topic_id>/replies', methods=['GET', 'POST'])
@token_required
def forum_replies(current_user, topic_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if request.method == 'POST':
        data = request.get_json() or {}
        content = str(data.get('content') or '').strip()
        if not content:
            cursor.close()
            conn.close()
            return jsonify({"message": "Content is required"}), 400
            
        cursor.execute(
            "INSERT INTO forum_replies (topic_id, author_id, content) VALUES (?, ?, ?)",
            (topic_id, current_user['id'], content)
        )
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"message": "Reply posted"}), 201

    cursor.execute("""
        SELECT fr.*, u.name as author_name 
        FROM forum_replies fr 
        JOIN users u ON u.id = fr.author_id 
        WHERE fr.topic_id = ?
        ORDER BY fr.created_at ASC
    """, (topic_id,))
    replies = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"items": replies}), 200

@app.route('/library/borrows/me', methods=['GET'])
@token_required
def get_my_library_borrows(current_user):
    student_id = _get_student_id(current_user['id'])
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT lb.*, b.title, b.author 
        FROM library_borrows lb 
        JOIN library_books b ON b.id = lb.book_id 
        WHERE lb.student_id = ?
    """, (student_id,))
    borrows = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"items": borrows}), 200

@app.route('/library/borrow', methods=['POST'])
@token_required
def borrow_book(current_user):
    student_id = _get_student_id(current_user['id'])
    data = request.get_json()
    book_id = data.get('book_id')
    due_date = (datetime.now() + timedelta(days=14)).strftime('%Y-%m-%d %H:%M:%S')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO library_borrows (book_id, student_id, due_date) VALUES (?, ?, ?)", 
                   (book_id, student_id, due_date))
    cursor.execute("UPDATE library_books SET available_copies = available_copies - 1 WHERE id = ?", (book_id,))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"message": "Book borrowed successfully", "due_date": due_date}), 201

@app.route('/library/return', methods=['POST'])
@token_required
def return_book(current_user):
    data = request.get_json()
    borrow_id = data.get('borrow_id')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get book_id before marking as returned
    cursor.execute("SELECT book_id FROM library_borrows WHERE id = ?", (borrow_id,))
    row = cursor.fetchone()
    if not row:
        return jsonify({"message": "Borrow record not found"}), 404
    book_id = row[0]
    
    cursor.execute("UPDATE library_borrows SET returned_at = ?, status = 'returned' WHERE id = ?", 
                   (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), borrow_id))
    cursor.execute("UPDATE library_books SET available_copies = available_copies + 1 WHERE id = ?", (book_id,))
    
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"message": "Book returned successfully"}), 200

@app.route('/placement/applications/me', methods=['GET'])
@token_required
def get_my_placement_apps(current_user):
    student_id = _get_student_id(current_user['id'])
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT pa.*, j.company_name, j.role 
        FROM placement_applications pa 
        JOIN placement_jobs j ON j.id = pa.job_id 
        WHERE pa.student_id = ?
    """, (student_id,))
    apps = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"items": apps}), 200

@app.route('/placement/interviews/me', methods=['GET'])
@token_required
def get_my_placement_interviews(current_user):
    student_id = _get_student_id(current_user['id'])
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT pi.*, j.company_name, j.role
        FROM placement_interviews pi
        JOIN placement_applications pa ON pa.id = pi.application_id
        JOIN placement_jobs j ON j.id = pa.job_id
        WHERE pa.student_id = ?
        ORDER BY pi.scheduled_at ASC
    """, (student_id,))
    rows = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"items": rows}), 200

@app.route('/placement/certificates/me', methods=['GET', 'POST'])
@token_required
def handle_my_certificates(current_user):
    student_id = _get_student_id(current_user['id'])
    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'POST':
        data = request.get_json() or {}
        title = str(data.get('title') or '').strip()
        issuer = str(data.get('issuer') or '').strip()
        category = str(data.get('category') or 'skill').strip()
        issue_date = str(data.get('issue_date') or '').strip() or None
        certificate_url = str(data.get('certificate_url') or '').strip()
        if not title or not issuer:
            cursor.close()
            conn.close()
            return jsonify({"message": "Title and issuer are required"}), 400
        cursor.execute("""
            INSERT INTO student_certificates (student_id, title, issuer, category, issue_date, certificate_url)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (student_id, title, issuer, category, issue_date, certificate_url))
        conn.commit()
        certificate_id = cursor.lastrowid
        cursor.close()
        conn.close()
        return jsonify({"message": "Certificate added successfully", "id": certificate_id}), 201

    cursor.execute("""
        SELECT *
        FROM student_certificates
        WHERE student_id = ?
        ORDER BY COALESCE(issue_date, created_at) DESC, id DESC
    """, (student_id,))
    rows = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"items": rows}), 200

@app.route('/placement/analytics/me', methods=['GET'])
@token_required
def placement_analytics_me(current_user):
    student_id = _get_student_id(current_user['id'])
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT status, COUNT(*) as count
        FROM placement_applications
        WHERE student_id = ?
        GROUP BY status
    """, (student_id,))
    status_rows = [row_to_dict(r) for r in cursor.fetchall()]
    status_counts = {
        "applied": 0,
        "shortlisted": 0,
        "interview": 0,
        "offered": 0,
        "rejected": 0,
    }
    for row in status_rows:
        status_counts[str(row["status"])] = _parse_int(row["count"], 0)

    cursor.execute("SELECT COUNT(*) FROM student_certificates WHERE student_id = ?", (student_id,))
    certificates_count = _parse_int(cursor.fetchone()[0], 0)

    cursor.execute("""
        SELECT COUNT(*)
        FROM placement_interviews pi
        JOIN placement_applications pa ON pa.id = pi.application_id
        WHERE pa.student_id = ? AND pi.status = 'scheduled'
    """, (student_id,))
    scheduled_interviews = _parse_int(cursor.fetchone()[0], 0)

    cursor.close()
    conn.close()
    return jsonify({
        "application_counts": status_counts,
        "certificates_count": certificates_count,
        "scheduled_interviews": scheduled_interviews,
        "placement_readiness_score": min(
            100,
            35 + (certificates_count * 10) + (status_counts["shortlisted"] * 10) + (status_counts["interview"] * 15) + (status_counts["offered"] * 20),
        ),
    }), 200

@app.route('/placement/apply', methods=['POST'])
@token_required
def apply_for_job(current_user):
    student_id = _get_student_id(current_user['id'])
    data = request.get_json() or {}
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM placement_applications WHERE job_id = ? AND student_id = ?",
        (_parse_int(data.get('job_id'), 0), student_id),
    )
    if cursor.fetchone():
        cursor.close()
        conn.close()
        return jsonify({"message": "Already applied to this job"}), 409
    cursor.execute("INSERT INTO placement_applications (job_id, student_id, resume_url) VALUES (?, ?, ?)",
                   (data['job_id'], student_id, data.get('resume_url')))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"message": "Applied successfully"}), 201

@app.route('/student/resume', methods=['GET', 'POST'])
@token_required
def handle_resume(current_user):
    student_id = _get_student_id(current_user['id'])
    conn = get_db_connection()
    cursor = conn.cursor()
    if request.method == 'GET':
        cursor.execute("SELECT resume_data FROM students WHERE id=?", (student_id,))
        row = cursor.fetchone()
        data = json.loads(row[0]) if row and row[0] else {}
        return jsonify(data), 200
    else:
        data = request.get_json()
        cursor.execute("UPDATE students SET resume_data=? WHERE id=?", (json.dumps(data), student_id))
        conn.commit()
        return jsonify({"message": "Resume updated"}), 200

# END UNIVERSITY ECOSYSTEM APIS

# ASSIGNMENTS & SUBMISSIONS

@app.route('/assignments', methods=['GET'])
@token_required
def get_assignments(current_user):
    subject_id = request.args.get('subject_id')
    conn = get_db_connection()
    cursor = conn.cursor()
    if subject_id:
        cursor.execute("SELECT * FROM assignments WHERE subject_id=?", (subject_id,))
    else:
        cursor.execute("SELECT * FROM assignments")
    rows = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"items": rows}), 200

@app.route('/assignments', methods=['POST'])
@token_required
def create_assignment(current_user):
    if current_user['role'] not in ['faculty', 'admin']:
        return jsonify({"message": "Forbidden"}), 403
    data = request.get_json()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO assignments (subject_id, title, description, due_date)
        VALUES (?, ?, ?, ?)
    """, (data['subject_id'], data['title'], data['description'], data['due_date']))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"message": "Assignment created"}), 201

@app.route('/assignments/<int:id>/submit', methods=['POST'])
@token_required
def submit_assignment(current_user):
    student_id = _get_student_id(current_user['id'])
    data = request.get_json() or {}
    assignment_id = data.get('assignment_id')
    submission_url = data.get('submission_url')
    
    if not assignment_id or not submission_url:
        return jsonify({"message": "Missing assignment_id or submission_url"}), 400
        
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Check for existing submission
    cursor.execute("SELECT id FROM assignment_submissions WHERE student_id = ? AND assignment_id = ?", (student_id, assignment_id))
    existing = cursor.fetchone()
    
    if existing:
        submission_id = existing['id']
        # Increment version
        cursor.execute("SELECT MAX(version_number) FROM assignment_versions WHERE submission_id = ?", (submission_id,))
        max_v = cursor.fetchone()[0] or 1
        new_v = max_v + 1
        
        cursor.execute("""
            INSERT INTO assignment_versions (submission_id, file_path, version_number)
            VALUES (?, ?, ?)
        """, (submission_id, submission_url, new_v))
        
        cursor.execute("UPDATE assignment_submissions SET status = 'submitted', submitted_at = CURRENT_TIMESTAMP WHERE id = ?", (submission_id,))
        message = f"Assignment updated to version {new_v}"
    else:
        cursor.execute("""
            INSERT INTO assignment_submissions (student_id, assignment_id, status)
            VALUES (?, ?, 'submitted')
        """, (student_id, assignment_id))
        submission_id = cursor.lastrowid
        
        cursor.execute("""
            INSERT INTO assignment_versions (submission_id, file_path, version_number)
            VALUES (?, ?, 1)
        """, (submission_id, submission_url, 1))
        message = "Assignment submitted successfully"
        
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"message": message}), 201

# END ASSIGNMENTS

# PHASE 4 ENTERPRISE ROUTES

@app.route('/faculty/grade-submission', methods=['POST'])
@token_required
def grade_submission(current_user):
    if current_user['role'] != 'faculty':
        return jsonify({"message": "Unauthorized"}), 403
    
    data = request.get_json() or {}
    submission_id = data.get('submission_id')
    score = data.get('score')
    feedback = data.get('feedback', '')
    
    if submission_id is None or score is None:
        return jsonify({"message": "Submission ID and score required"}), 400
        
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE assignment_submissions 
        SET grade_score = ?, grade_feedback = ?, status = 'completed', graded_by = ?, graded_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (score, feedback, current_user['id'], submission_id))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"message": "Submission graded successfully"}), 200

@app.route('/cafeteria/menu', methods=['GET'])
@token_required
def get_cafeteria_menu(current_user):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM cafeteria_menu WHERE is_available = 1")
    rows = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"items": rows}), 200

@app.route('/cafeteria/order', methods=['POST'])
@token_required
def place_cafeteria_order(current_user):
    student_id = _get_student_id(current_user['id'])
    data = request.get_json() or {}
    items = data.get('items', [])
    total_price = data.get('total_price', 0)
    
    if not items:
        return jsonify({"message": "No items in order"}), 400
        
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO cafeteria_orders (student_id, items_json, total_price, status)
        VALUES (?, ?, ?, 'pending')
    """, (student_id, json.dumps(items), total_price))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"message": "Order placed successfully"}), 201

@app.route('/student/health-records', methods=['GET', 'POST'])
@token_required
def handle_health_records(current_user):
    student_id = _get_student_id(current_user['id'])
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if request.method == 'POST':
        data = request.get_json() or {}
        cursor.execute("""
            INSERT INTO health_records (student_id, blood_group, allergies, medical_history, emergency_contact_name, emergency_contact_phone)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(student_id) DO UPDATE SET
                blood_group=excluded.blood_group,
                allergies=excluded.allergies,
                medical_history=excluded.medical_history,
                emergency_contact_name=excluded.emergency_contact_name,
                emergency_contact_phone=excluded.emergency_contact_phone,
                updated_at=CURRENT_TIMESTAMP
        """, (student_id, data.get('blood_group'), data.get('allergies'), data.get('medical_history'), data.get('emergency_contact_name'), data.get('emergency_contact_phone')))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"message": "Health records updated"}), 200

    cursor.execute("SELECT * FROM health_records WHERE student_id = ?", (student_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return jsonify({"data": row_to_dict(row) if row else {}}), 200

# END PHASE 4

# PHASE 1: CORE ACADEMIC & SMART CAMPUS ROUTES

_CALENDAR_EVENT_TYPES = frozenset({"class", "exam", "assignment", "holiday", "meeting", "other"})


@app.route('/academic/calendar', methods=['GET', 'POST'])
@token_required
def academic_calendar(current_user):
    role = current_user.get("role")
    if request.method == 'POST':
        if role not in ("admin", "faculty"):
            return jsonify({"message": "Unauthorized!"}), 403
        data = request.get_json() or {}
        title = str(data.get("title") or "").strip()
        event_type = str(data.get("event_type") or "other").strip().lower()
        starts_at = str(data.get("starts_at") or "").strip()
        ends_at = str(data.get("ends_at") or "").strip() or None
        description = str(data.get("description") or "").strip()
        subject_id = _parse_int(data.get("subject_id"), 0)
        target_role = str(data.get("target_role") or "all").strip().lower()
        if len(title) < 2 or len(title) > 200:
            return jsonify({"message": "Invalid title"}), 400
        if event_type not in _CALENDAR_EVENT_TYPES:
            return jsonify({"message": "Invalid event_type"}), 400
        if len(starts_at) < 8:
            return jsonify({"message": "Invalid starts_at"}), 400
        if target_role not in ("all", "student", "faculty", "parent", "admin"):
            target_role = "all"
        conn = get_db_connection()
        cursor = conn.cursor()
        if subject_id > 0:
            cursor.execute("SELECT id FROM subjects_master WHERE id=?", (subject_id,))
            if not cursor.fetchone():
                cursor.close()
                conn.close()
                return jsonify({"message": "Subject not found"}), 404
        sub_val = subject_id if subject_id > 0 else None
        cursor.execute(
            """
            INSERT INTO academic_calendar_events
            (title, event_type, starts_at, ends_at, description, subject_id, created_by, target_role)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title,
                event_type,
                starts_at,
                ends_at,
                description,
                sub_val,
                _parse_int(current_user.get("id"), 0) or None,
                target_role,
            ),
        )
        new_id = cursor.lastrowid
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"message": "Calendar event created", "id": new_id}), 201

    days = max(7, min(120, _parse_int(request.args.get("days"), 30)))
    past_mod = f"-{days} days"
    future_mod = f"+{days} days"
    conn = get_db_connection()
    cursor = conn.cursor()
    events: List[Dict[str, Any]] = []

    cursor.execute(
        f"""
        SELECT e.*, s.name AS subject_name
        FROM academic_calendar_events e
        LEFT JOIN subjects_master s ON s.id = e.subject_id
        WHERE datetime(e.starts_at) >= datetime('now', ?)
          AND datetime(e.starts_at) <= datetime('now', ?)
          AND (e.target_role = 'all' OR e.target_role = ?)
        ORDER BY e.starts_at ASC
        """,
        (past_mod, future_mod, role),
    )
    for row in cursor.fetchall():
        item = row_to_dict(row)
        item["source"] = "calendar"
        events.append(item)

    cursor.execute(
        f"""
        SELECT id, title, due_date, description, created_at
        FROM assignments
        WHERE due_date IS NOT NULL AND due_date != ''
          AND date(due_date) >= date('now', ?)
          AND date(due_date) <= date('now', ?)
        ORDER BY due_date ASC
        """,
        (past_mod, future_mod),
    )
    for row in cursor.fetchall():
        r = row_to_dict(row)
        events.append({
            "id": f"assignment-{r.get('id')}",
            "title": r.get("title") or "Assignment",
            "event_type": "assignment",
            "starts_at": r.get("due_date"),
            "ends_at": None,
            "description": r.get("description") or "",
            "subject_name": None,
            "source": "assignment",
        })

    try:
        cursor.execute(
            f"""
            SELECT es.id, es.exam_date, es.start_time, es.end_time, es.exam_type, es.room_number,
                   cs.subject_name
            FROM exam_schedules es
            LEFT JOIN curriculum_subjects cs ON cs.id = es.subject_id
            WHERE date(es.exam_date) >= date('now', ?)
              AND date(es.exam_date) <= date('now', ?)
            ORDER BY es.exam_date ASC, es.start_time ASC
            """,
            (past_mod, future_mod),
        )
        for row in cursor.fetchall():
            r = row_to_dict(row)
            starts = f"{r.get('exam_date')} {r.get('start_time') or '09:00'}"
            events.append({
                "id": f"exam-{r.get('id')}",
                "title": f"{r.get('subject_name') or 'Exam'} ({r.get('exam_type') or 'Exam'})",
                "event_type": "exam",
                "starts_at": starts,
                "ends_at": f"{r.get('exam_date')} {r.get('end_time') or '12:00'}",
                "description": f"Room: {r.get('room_number') or 'TBA'}",
                "subject_name": r.get("subject_name"),
                "source": "exam_schedule",
            })
    except Exception:
        pass

    if role == "student":
        student_id = _get_linked_student_id(int(current_user.get("id", 0)))
        if student_id:
            cursor.execute(
                """
                SELECT id, requested_time, scheduled_time, status, parent_note
                FROM meetings
                WHERE student_id=?
                  AND status IN ('requested', 'approved', 'rescheduled')
                ORDER BY COALESCE(scheduled_time, requested_time) ASC
                LIMIT 20
                """,
                (student_id,),
            )
            for row in cursor.fetchall():
                r = row_to_dict(row)
                when = r.get("scheduled_time") or r.get("requested_time")
                if when:
                    events.append({
                        "id": f"meeting-{r.get('id')}",
                        "title": f"Parent meeting ({r.get('status')})",
                        "event_type": "meeting",
                        "starts_at": when,
                        "ends_at": None,
                        "description": r.get("parent_note") or "",
                        "source": "meeting",
                    })

    events.sort(key=lambda x: str(x.get("starts_at") or ""))
    cursor.close()
    conn.close()
    return jsonify({"items": events, "count": len(events), "days": days}), 200


def _compute_gpa_summary(cursor, student_id: int) -> Dict[str, Any]:
    cursor.execute(
        """
        SELECT g.*, s.name AS subject_name, s.code AS subject_code,
               d.name AS department_name, sem.name AS semester_name
        FROM student_subject_grades g
        JOIN subjects_master s ON s.id = g.subject_id
        JOIN departments_master d ON d.id = s.department_id
        LEFT JOIN semesters_master sem ON sem.id = s.semester_id
        WHERE g.student_id=?
        ORDER BY g.updated_at DESC
        """,
        (student_id,),
    )
    grades = [row_to_dict(r) for r in cursor.fetchall()]
    total_credits = 0
    weighted = 0.0
    earned_credits = 0
    backlogs = 0
    for g in grades:
        cred = int(g.get("credits") or 0)
        status = str(g.get("status") or "pending").lower()
        gp = g.get("grade_points")
        if status in ("failed", "backlog"):
            backlogs += 1
        if status == "passed" and gp is not None and cred > 0:
            total_credits += cred
            weighted += float(gp) * cred
            earned_credits += cred
    cgpa = round(weighted / total_credits, 2) if total_credits > 0 else None
    return {
        "cgpa": cgpa,
        "credits_earned": earned_credits,
        "total_graded_subjects": len(grades),
        "backlogs": backlogs,
        "grades": grades,
    }


@app.route('/academic/gpa/me', methods=['GET'])
@token_required
def academic_gpa_me(current_user):
    if current_user.get("role") != "student":
        return jsonify({"message": "Unauthorized!"}), 403
    student_id = _get_linked_student_id(int(current_user.get("id", 0)))
    if not student_id:
        return jsonify({"message": "Student account not linked"}), 409
    conn = get_db_connection()
    cursor = conn.cursor()
    summary = _compute_gpa_summary(cursor, int(student_id))
    cursor.execute("SELECT attendance, study_hours, sleep_hours, name FROM students WHERE id=?", (student_id,))
    st = cursor.fetchone()
    cursor.close()
    conn.close()
    predicted_cgpa = None
    if st:
        predicted_marks = predict_marks(
            float(st["study_hours"] or 0),
            float(st["sleep_hours"] or 0),
            float(st["attendance"] or 0),
        )
        predicted_cgpa = round((predicted_marks / 100.0) * 10.0, 2)
    summary["predicted_cgpa"] = predicted_cgpa
    summary["student_name"] = st["name"] if st else ""
    return jsonify(summary), 200


@app.route('/academic/gpa/students/<int:student_id>', methods=['GET'])
@token_required
def academic_gpa_student(current_user, student_id: int):
    if current_user.get("role") not in ("admin", "faculty"):
        return jsonify({"message": "Unauthorized!"}), 403
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM students WHERE id=?", (student_id,))
    st = cursor.fetchone()
    if not st:
        cursor.close()
        conn.close()
        return jsonify({"message": "Student not found"}), 404
    summary = _compute_gpa_summary(cursor, student_id)
    summary["student_id"] = student_id
    summary["student_name"] = st["name"]
    cursor.close()
    conn.close()
    return jsonify(summary), 200


@app.route('/academic/gpa/grades', methods=['POST'])
@token_required
def academic_gpa_upsert_grade(current_user):
    if current_user.get("role") not in ("admin", "faculty"):
        return jsonify({"message": "Unauthorized!"}), 403
    data = request.get_json() or {}
    student_id = _parse_int(data.get("student_id"), 0)
    subject_id = _parse_int(data.get("subject_id"), 0)
    grade_points = data.get("grade_points")
    marks = data.get("marks")
    status = str(data.get("status") or "pending").strip().lower()
    remarks = str(data.get("remarks") or "").strip()
    credits = _parse_int(data.get("credits"), 0)
    if student_id <= 0 or subject_id <= 0:
        return jsonify({"message": "Invalid student_id or subject_id"}), 400
    if status not in ("passed", "failed", "backlog", "pending"):
        return jsonify({"message": "Invalid status"}), 400
    gp_val: Optional[float] = None
    if grade_points is not None and str(grade_points).strip() != "":
        gp_val = round(_parse_float(grade_points, -1), 2)
        if gp_val < 0 or gp_val > 10:
            return jsonify({"message": "grade_points must be 0-10"}), 400
    marks_val: Optional[float] = None
    if marks is not None and str(marks).strip() != "":
        marks_val = round(_parse_float(marks, -1), 2)
        if marks_val < 0 or marks_val > 100:
            return jsonify({"message": "marks must be 0-100"}), 400
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM students WHERE id=?", (student_id,))
    if not cursor.fetchone():
        cursor.close()
        conn.close()
        return jsonify({"message": "Student not found"}), 404
    cursor.execute("SELECT id, credits FROM subjects_master WHERE id=?", (subject_id,))
    sub_row = cursor.fetchone()
    if not sub_row:
        cursor.close()
        conn.close()
        return jsonify({"message": "Subject not found"}), 404
    if credits <= 0:
        credits = int(sub_row["credits"] or 3)
    credits = max(1, min(10, credits))
    faculty_id = _parse_int(current_user.get("id"), 0) or None
    cursor.execute(
        """
        INSERT INTO student_subject_grades
        (student_id, subject_id, credits, grade_points, marks, status, faculty_user_id, remarks, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(student_id, subject_id) DO UPDATE SET
            credits=excluded.credits,
            grade_points=excluded.grade_points,
            marks=excluded.marks,
            status=excluded.status,
            faculty_user_id=excluded.faculty_user_id,
            remarks=excluded.remarks,
            updated_at=CURRENT_TIMESTAMP
        """,
        (student_id, subject_id, credits, gp_val, marks_val, status, faculty_id, remarks),
    )
    conn.commit()
    summary = _compute_gpa_summary(cursor, student_id)
    cursor.close()
    conn.close()
    return jsonify({"message": "Grade saved", "summary": summary}), 200


@app.route('/academic/curriculum', methods=['GET'])
@token_required
def get_curriculum(current_user):
    semester = str(request.args.get("semester") or "").strip()
    semester_id = _parse_int(request.args.get("semester_id"), 0)
    conn = get_db_connection()
    cursor = conn.cursor()

    student_id: Optional[int] = None
    if current_user.get("role") == "student":
        student_id = _get_linked_student_id(int(current_user.get("id", 0)))

    sql = """
        SELECT s.id, s.code, s.name,
               COALESCE(s.credits, 3) AS credits,
               COALESCE(s.syllabus, '') AS syllabus,
               s.semester_id, s.department_id,
               d.name AS department_name, d.stream AS department_stream,
               sem.name AS semester_name,
               COALESCE(sem.order_index, 0) AS semester_order,
               (SELECT COUNT(*) FROM study_materials m WHERE m.subject_id = s.id) AS material_count
        FROM subjects_master s
        JOIN departments_master d ON d.id = s.department_id
        LEFT JOIN semesters_master sem ON sem.id = s.semester_id
        WHERE 1=1
    """
    params: List[Any] = []
    if semester_id > 0:
        sql += " AND s.semester_id=?"
        params.append(semester_id)
    elif semester:
        sem_num = _parse_int(semester, 0)
        if sem_num > 0:
            sql += " AND (sem.order_index=? OR sem.id=? OR s.semester_id=?)"
            params.extend([sem_num, sem_num, sem_num])
    sql += " ORDER BY sem.order_index ASC, s.name ASC"
    cursor.execute(sql, params)
    master_rows = [row_to_dict(r) for r in cursor.fetchall()]

    items: List[Dict[str, Any]] = []
    for r in master_rows:
        item = {
            "id": r["id"],
            "source": "master",
            "subject_name": r["name"],
            "code": r.get("code") or "",
            "credits": int(r.get("credits") or 3),
            "syllabus": r.get("syllabus") or "",
            "semester": int(r.get("semester_order") or 0),
            "semester_name": r.get("semester_name") or "",
            "department_name": r.get("department_name") or "",
            "department_stream": r.get("department_stream") or "",
            "material_count": int(r.get("material_count") or 0),
            "grade": None,
        }
        if student_id:
            cursor.execute(
                """
                SELECT grade_points, marks, status, credits
                FROM student_subject_grades WHERE student_id=? AND subject_id=?
                """,
                (student_id, r["id"]),
            )
            gr = cursor.fetchone()
            if gr:
                item["grade"] = row_to_dict(gr)
        items.append(item)

    if not items and semester:
        cursor.execute(
            "SELECT * FROM curriculum_subjects WHERE semester=? ORDER BY subject_name ASC",
            (_parse_int(semester, 0),),
        )
        for r in cursor.fetchall():
            leg = row_to_dict(r)
            items.append({
                "id": leg["id"],
                "source": "legacy",
                "subject_name": leg.get("subject_name"),
                "code": "",
                "credits": int(leg.get("credits") or 3),
                "syllabus": leg.get("syllabus_json") or "",
                "semester": int(leg.get("semester") or 0),
                "semester_name": f"Semester {leg.get('semester')}",
                "department_name": "",
                "material_count": 0,
                "grade": None,
            })

    gpa_summary = _compute_gpa_summary(cursor, student_id) if student_id else None
    cursor.close()
    conn.close()
    return jsonify({
        "items": items,
        "count": len(items),
        "gpa": {
            "cgpa": gpa_summary.get("cgpa") if gpa_summary else None,
            "credits_earned": gpa_summary.get("credits_earned") if gpa_summary else 0,
            "backlogs": gpa_summary.get("backlogs") if gpa_summary else 0,
        } if gpa_summary else None,
    }), 200


@app.route('/academic/obe', methods=['GET'])
@token_required
def get_obe_outcomes(current_user):
    subject_id = request.args.get("subject_id")
    master_subject_id = _parse_int(request.args.get("master_subject_id"), 0)
    conn = get_db_connection()
    cursor = conn.cursor()
    if master_subject_id > 0:
        cursor.execute(
            """
            SELECT o.* FROM obe_outcomes o
            LEFT JOIN subjects_master sm ON sm.id = ?
            LEFT JOIN curriculum_subjects cs ON cs.id = o.subject_id
            WHERE o.master_subject_id = ?
               OR (sm.name IS NOT NULL AND cs.subject_name = sm.name)
            ORDER BY o.outcome_type, o.outcome_code
            """,
            (master_subject_id, master_subject_id),
        )
    elif subject_id:
        cursor.execute("SELECT * FROM obe_outcomes WHERE subject_id = ?", (subject_id,))
    else:
        cursor.execute("SELECT * FROM obe_outcomes ORDER BY subject_id, outcome_code")
    rows = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"items": rows}), 200

@app.route('/academic/timetable', methods=['GET'])
@token_required
def get_timetable(current_user):
    semester = request.args.get('semester')
    dept_id = request.args.get('dept_id')
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT t.*, cs.subject_name 
        FROM timetables t
        JOIN curriculum_subjects cs ON t.subject_id = cs.id
        WHERE t.semester = ? AND t.dept_id = ?
        ORDER BY CASE day_of_week 
            WHEN 'Monday' THEN 1 WHEN 'Tuesday' THEN 2 WHEN 'Wednesday' THEN 3 
            WHEN 'Thursday' THEN 4 WHEN 'Friday' THEN 5 WHEN 'Saturday' THEN 6 
        END, start_time ASC
    """, (semester, dept_id))
    rows = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"items": rows}), 200

@app.route('/campus/social-feed', methods=['GET', 'POST'])
@token_required
def handle_social_feed(current_user):
    conn = get_db_connection()
    cursor = conn.cursor()
    if request.method == 'POST':
        data = request.get_json() or {}
        content = data.get('content')
        media_url = data.get('media_url')
        if not content:
            return jsonify({"message": "Content is required"}), 400
        cursor.execute("""
            INSERT INTO campus_social_feed (author_id, author_role, content, media_url)
            VALUES (?, ?, ?, ?)
        """, (current_user['id'], current_user['role'], content, media_url))
        conn.commit()
        # Reward XP for posting
        if current_user['role'] == 'student':
            _add_xp(current_user['id'], 10)
        cursor.close()
        conn.close()
        return jsonify({"message": "Post shared"}), 201

    cursor.execute("SELECT * FROM campus_social_feed ORDER BY created_at DESC LIMIT 50")
    rows = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"items": rows}), 200

@app.route('/campus/notices', methods=['GET'])
@token_required
def get_notices(current_user):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM smart_notices 
        WHERE (target_role = 'all' OR target_role = ?)
        AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
        ORDER BY created_at DESC
    """, (current_user['role'],))
    rows = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"items": rows}), 200

@app.route('/student/dashboard', methods=['GET'])
@token_required
def student_dashboard(current_user):
    student_id = _get_linked_student_id(current_user['id'])
    if not student_id:
        return jsonify({"message": "Student record not found"}), 404

    conn = get_db_connection()
    cursor = conn.cursor()

    # Attendance Rate
    cursor.execute("SELECT status FROM attendance WHERE student_id = ?", (student_id,))
    att_rows = cursor.fetchall()
    att_rate = 0
    if att_rows:
        present = sum(1 for r in att_rows if r[0] == 'present')
        att_rate = round((present / len(att_rows)) * 100, 1)

    # Average Marks (Mocked from quiz submissions if available)
    cursor.execute("SELECT AVG(score) FROM quiz_submissions WHERE student_id = ?", (student_id,))
    avg_marks = round(cursor.fetchone()[0] or 0, 1)

    # Assignments
    cursor.execute("SELECT COUNT(*) FROM assignments") # Total for now
    total_assignments = cursor.fetchone()[0]
    
    # Chart Data (last 7 days attendance)
    cursor.execute("""
        SELECT date, status FROM attendance 
        WHERE student_id = ? 
        ORDER BY date DESC LIMIT 7
    """, (student_id,))
    recent_att = [row_to_dict(r) for r in cursor.fetchall()]

    # Performance Data (from quiz submissions)
    cursor.execute("""
        SELECT s.name as subject, AVG(qs.score) as marks
        FROM quiz_submissions qs
        JOIN subjects_master s ON (SELECT subject_id FROM quizzes WHERE id = qs.quiz_id) = s.id
        WHERE qs.student_id = ?
        GROUP BY s.id
    """, (student_id,))
    perf_rows = cursor.fetchall()
    perf_data = [row_to_dict(r) for r in perf_rows]
    if not perf_data:
        perf_data = [{"subject": "No Data", "marks": 0}]

    cursor.close()
    conn.close()

    return jsonify({
        "attendance_rate": att_rate,
        "average_marks": avg_marks,
        "assignments_completed": 0,
        "pending_tasks": total_assignments,
        "attendance_history": [
            {"date": r['date'], "value": 100 if r['status'] == 'present' else 0} 
            for r in reversed(recent_att)
        ],
        "performance_data": perf_data
    }), 200

@app.route('/student/recommendations', methods=['GET'])
@token_required
def student_recommendations(current_user):
    return jsonify({
        "items": [
            {"title": "Improve Python Skills", "description": "Based on your last quiz, we recommend watching 'Python Data Structures' video."},
            {"title": "Upcoming Workshop", "description": "A workshop on AI/ML is happening this Friday at the Main Hall."}
        ]
    }), 200

@app.route('/notifications', methods=['GET'])
@token_required
def get_notifications(current_user):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM notifications 
        WHERE recipient_role = ? AND (recipient_id = ? OR recipient_id IS NULL)
        ORDER BY created_at DESC LIMIT 20
    """, (current_user['role'], current_user['id']))
    notes = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify(notes), 200

@app.route('/student/gamification', methods=['GET'])
@token_required
def get_student_gamification(current_user):
    student_id = _get_student_id(current_user['id'])
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM student_gamification WHERE student_id = ?", (student_id,))
    row = cursor.fetchone()
    if not row:
        cursor.execute("INSERT INTO student_gamification (student_id) VALUES (?)", (student_id,))
        conn.commit()
        cursor.execute("SELECT * FROM student_gamification WHERE student_id = ?", (student_id,))
        row = cursor.fetchone()
    cursor.close()
    conn.close()
    return jsonify(row_to_dict(row)), 200

def _add_xp(user_id, amount):
    student_id = _get_student_id(user_id)
    if not student_id: return
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO student_gamification (student_id, xp, level)
        VALUES (?, ?, 1)
        ON CONFLICT(student_id) DO UPDATE SET
            xp = xp + ?,
            level = (xp + ?) / 100 + 1
    """, (student_id, amount, amount, amount))
    conn.commit()
    cursor.close()
    conn.close()

@app.route('/ai/advisor', methods=['POST'])
@token_required
def ai_advisor(current_user):
    data = request.get_json() or {}
    query = data.get('query', '').lower()
    student_id = _get_student_id(current_user['id'])
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Context gathering
    cursor.execute("SELECT * FROM students WHERE id = ?", (student_id,))
    student = row_to_dict(cursor.fetchone())
    
    response = "I've analyzed your query. "
    
    if "gpa" in query or "marks" in query or "cgpa" in query:
        response += f"Your current average marks are {student['average_marks']}. Based on your performance, your predicted semester CGPA is 8.4. You should focus on Mathematics to improve further."
    elif "attendance" in query:
        response += f"Your attendance is currently at {student['attendance']}%."
        if student['attendance'] < 75:
            response += " This is below the required 75%. I recommend attending all classes next week to avoid a warning."
        else:
            response += " Great job on staying regular!"
    elif "class" in query or "next" in query or "timetable" in query:
        response += "Your next class is Operating Systems at 10:45 AM in Room LHC-102."
    elif "study" in query or "tips" in query:
        response += "I recommend the 'Pomodoro Technique': study for 25 minutes, then take a 5-minute break. Also, check out the new Operating Systems notes in the Learning Center."
    else:
        response += "I'm here to help with your academic journey. You can ask me about your grades, attendance, or for study advice."

    cursor.close()
    conn.close()
    return jsonify({"response": response}), 200

@app.route('/student/leaderboard', methods=['GET'])
@token_required
def get_leaderboard(current_user):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT sg.*, s.name as student_name 
        FROM student_gamification sg
        JOIN students s ON sg.student_id = s.id
        ORDER BY sg.xp DESC LIMIT 20
    """)
    rows = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"items": rows}), 200

# END PHASE 1

# PHASE 5: ENGAGEMENT ROUTES

@app.route('/faculty/research', methods=['GET', 'POST'])
@token_required
def handle_faculty_research(current_user):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if request.method == 'POST':
        if current_user['role'] != 'faculty':
            return jsonify({"message": "Unauthorized"}), 403
        data = request.get_json() or {}
        cursor.execute("""
            INSERT INTO faculty_research (faculty_id, title, publication_type, journal_name, publication_date, url)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (current_user['id'], data.get('title'), data.get('type'), data.get('journal'), data.get('date'), data.get('url')))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"message": "Research record added"}), 201

    faculty_id = request.args.get('faculty_id', current_user['id'])
    cursor.execute("SELECT * FROM faculty_research WHERE faculty_id = ? ORDER BY publication_date DESC", (faculty_id,))
    rows = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"items": rows}), 200

@app.route('/appointments', methods=['GET', 'POST'])
@token_required
def handle_appointments(current_user):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if request.method == 'POST':
        data = request.get_json() or {}
        student_id = _get_student_id(current_user['id']) if current_user['role'] == 'student' else data.get('student_id')
        
        # If parent is booking
        if current_user['role'] == 'parent':
            student_id = _get_parent_student_id(current_user['id'])
            
        cursor.execute("""
            INSERT INTO parent_appointments (parent_id, faculty_id, student_id, purpose, preferred_date)
            VALUES (?, ?, ?, ?, ?)
        """, (current_user['id'], data.get('faculty_id'), student_id, data.get('purpose'), data.get('date')))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"message": "Appointment requested"}), 201

    # GET appointments based on role
    query = "SELECT pa.*, u.name as faculty_name, p.name as parent_name, s.name as student_name FROM parent_appointments pa "
    query += "JOIN users u ON pa.faculty_id = u.id "
    query += "JOIN users p ON pa.parent_id = p.id "
    query += "JOIN students s ON pa.student_id = s.id "
    
    if current_user['role'] == 'faculty':
        query += "WHERE pa.faculty_id = ?"
    elif current_user['role'] == 'parent':
        query += "WHERE pa.parent_id = ?"
    else:
        query += "WHERE pa.student_id = ?"
        
    cursor.execute(query + " ORDER BY preferred_date DESC", (current_user['id'],))
    rows = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"items": rows}), 200

@app.route('/appointments/<int:app_id>/status', methods=['PUT'])
@token_required
def update_appointment_status(current_user, app_id):
    data = request.get_json() or {}
    status = data.get('status')
    remarks = data.get('remarks', '')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE parent_appointments SET status = ?, remarks = ? WHERE id = ?", (status, remarks, app_id))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"message": "Appointment status updated"}), 200

# END PHASE 5

# PHASE 6: CAREER INTELLIGENCE ROUTES

@app.route('/placement/analyze-resume', methods=['GET'])
@token_required
def analyze_resume(current_user):
    student_id = _get_student_id(current_user['id'])
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM student_resumes WHERE student_id = ?", (student_id,))
    resume = cursor.fetchone()
    
    if not resume:
        return jsonify({"message": "No resume found. Build one first!"}), 404
        
    resume = row_to_dict(resume)
    summary = resume.get('summary', '')
    
    # Simple ATS Analysis Logic
    score = 0
    missing_skills = []
    
    # Keyword check
    keywords = ['python', 'sql', 'management', 'leadership', 'development', 'design', 'analysis']
    found_keywords = [k for k in keywords if k in summary.lower()]
    score += len(found_keywords) * 10
    
    # Length check
    if len(summary) > 200: score += 20
    elif len(summary) > 100: score += 10
    
    # Cap score at 100
    score = min(score, 100)
    
    if 'python' not in found_keywords: missing_skills.append('Python')
    if 'sql' not in found_keywords: missing_skills.append('SQL/Databases')
    
    cursor.close()
    conn.close()
    return jsonify({
        "score": score,
        "found_keywords": found_keywords,
        "missing_skills": missing_skills,
        "feedback": "Great start! Adding more industry-standard keywords like 'Python' or 'Cloud Computing' could improve your ATS visibility." if score < 80 else "Excellent resume! Your profile matches top-tier industry requirements."
    }), 200

@app.route('/placement/check-eligibility/<int:job_id>', methods=['GET'])
@token_required
def check_job_eligibility(current_user, job_id):
    student_id = _get_student_id(current_user['id'])
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get student data
    cursor.execute("SELECT * FROM students WHERE id = ?", (student_id,))
    student = row_to_dict(cursor.fetchone())
    
    # Get job data
    cursor.execute("SELECT * FROM placement_jobs WHERE id = ?", (job_id,))
    job = row_to_dict(cursor.fetchone())
    
    eligible = True
    reasons = []
    
    if student['average_marks'] < job['min_cgpa'] * 10: # Assuming marks are out of 100 and cgpa out of 10
        eligible = False
        reasons.append(f"CGPA requirement not met (Min: {job['min_cgpa']})")
        
    if student['attendance'] < job['min_attendance']:
        eligible = False
        reasons.append(f"Attendance requirement not met (Min: {job['min_attendance']}%)")
        
    cursor.close()
    conn.close()
    return jsonify({
        "eligible": eligible,
        "reasons": reasons,
        "student_stats": {"cgpa": student['average_marks']/10, "attendance": student['attendance']},
        "job_reqs": {"min_cgpa": job['min_cgpa'], "min_attendance": job['min_attendance']}
    }), 200

# END PHASE 6

# PHASE 7: UNIVERSAL SEARCH & INFRASTRUCTURE ROUTES

@app.route('/universal-search', methods=['GET'])
@token_required
def universal_search(current_user):
    query = request.args.get('q', '').lower()
    if not query:
        return jsonify({"results": []}), 200
        
    conn = get_db_connection()
    cursor = conn.cursor()
    results = []
    
    # Search Books
    cursor.execute("SELECT id, title, author as subtitle, 'Book' as type FROM library_books WHERE title LIKE ? OR author LIKE ?", (f'%{query}%', f'%{query}%'))
    results.extend([row_to_dict(r) for r in cursor.fetchall()])
    
    # Search Curriculum
    cursor.execute("SELECT id, subject_name as title, 'Semester ' || semester as subtitle, 'Subject' as type FROM curriculum_subjects WHERE subject_name LIKE ?", (f'%{query}%',))
    results.extend([row_to_dict(r) for r in cursor.fetchall()])
    
    # Search Forum
    cursor.execute("SELECT id, title, description as subtitle, 'Forum' as type FROM forum_topics WHERE title LIKE ? OR description LIKE ?", (f'%{query}%', f'%{query}%'))
    results.extend([row_to_dict(r) for r in cursor.fetchall()])
    
    cursor.close()
    conn.close()
    return jsonify({"results": results}), 200

@app.route('/campus/maintenance', methods=['GET', 'POST'])
@token_required
def handle_maintenance(current_user):
    student_id = _get_student_id(current_user['id'])
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if request.method == 'POST':
        data = request.get_json() or {}
        cursor.execute("""
            INSERT INTO maintenance_tickets (student_id, category, location, description)
            VALUES (?, ?, ?, ?)
        """, (student_id, data.get('category'), data.get('location'), data.get('description')))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"message": "Maintenance request submitted"}), 201

    cursor.execute("SELECT * FROM maintenance_tickets WHERE student_id = ? ORDER BY created_at DESC", (student_id,))
    rows = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"items": rows}), 200

# PHASE 8: ENTERPRISE SECURITY & THEMES

@app.route('/security/login-history', methods=['GET'])
@token_required
def get_login_history(current_user):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM login_history 
        WHERE user_id = ? 
        ORDER BY created_at DESC LIMIT 10
    """, (current_user['id'],))
    rows = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"history": rows}), 200

@app.route('/user/theme', methods=['GET', 'POST'])
@token_required
def handle_theme(current_user):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if request.method == 'POST':
        data = request.get_json() or {}
        theme = data.get('theme', 'light')
        cursor.execute("UPDATE users SET theme = ? WHERE id = ?", (theme, current_user['id']))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"message": "Theme updated", "theme": theme}), 200

    cursor.execute("SELECT theme FROM users WHERE id = ?", (current_user['id'],))
    row = cursor.fetchone()
    theme = row[0] if row and row[0] else 'light'
    cursor.close()
    conn.close()
    return jsonify({"theme": theme}), 200

# PHASE 9: FINANCE & CAMPUS STORE ROUTES

@app.route('/store/items', methods=['GET'])
@token_required
def get_store_items(current_user):
    category = request.args.get('category')
    conn = get_db_connection()
    cursor = conn.cursor()
    if category:
        cursor.execute("SELECT * FROM store_items WHERE category = ? AND stock > 0", (category,))
    else:
        cursor.execute("SELECT * FROM store_items WHERE stock > 0")
    rows = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"items": rows}), 200

@app.route('/store/order', methods=['POST'])
@token_required
def place_store_order(current_user):
    student_id = _get_student_id(current_user['id'])
    data = request.get_json() or {}
    items = data.get('items', [])
    total_amount = data.get('total_amount', 0)
    payment_method = data.get('payment_method', 'wallet')

    if not items:
        return jsonify({"message": "Cart is empty"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    # If paying via wallet, check balance
    if payment_method == 'wallet':
        cursor.execute("SELECT balance FROM student_wallet WHERE student_id = ?", (student_id,))
        row = cursor.fetchone()
        balance = row[0] if row else 0.0
        if balance < total_amount:
            cursor.close()
            conn.close()
            return jsonify({"message": "Insufficient wallet balance"}), 400
        
        # Deduct from wallet
        cursor.execute("UPDATE student_wallet SET balance = balance - ? WHERE student_id = ?", (total_amount, student_id))
        cursor.execute("""
            INSERT INTO wallet_transactions (student_id, amount, type, description)
            VALUES (?, ?, 'debit', 'Campus Store Purchase')
        """, (student_id, total_amount))

    # Record order
    cursor.execute("""
        INSERT INTO store_orders (student_id, items_json, total_amount, status, payment_method)
        VALUES (?, ?, ?, 'paid', ?)
    """, (student_id, json.dumps(items), total_amount, payment_method))

    # Update stock
    for item in items:
        cursor.execute("UPDATE store_items SET stock = stock - ? WHERE id = ?", (item['quantity'], item['id']))

    conn.commit()
    cursor.close()
    conn.close()
    
    _create_notification(
        recipient_role="student",
        recipient_id=current_user['id'],
        title="Order Placed",
        message=f"Your order for {len(items)} items has been placed successfully.",
        category="finance"
    )

    return jsonify({"message": "Order placed successfully"}), 201

@app.route('/wallet/balance', methods=['GET'])
@token_required
def get_wallet_info(current_user):
    student_id = _get_student_id(current_user['id'])
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Ensure wallet exists
    cursor.execute("INSERT OR IGNORE INTO student_wallet (student_id, balance) VALUES (?, 0.0)", (student_id,))
    conn.commit()

    cursor.execute("SELECT balance FROM student_wallet WHERE student_id = ?", (student_id,))
    balance = cursor.fetchone()[0]
    
    cursor.execute("SELECT * FROM wallet_transactions WHERE student_id = ? ORDER BY created_at DESC LIMIT 20", (student_id,))
    transactions = [row_to_dict(r) for r in cursor.fetchall()]
    
    cursor.close()
    conn.close()
    return jsonify({"balance": balance, "transactions": transactions}), 200

@app.route('/wallet/topup', methods=['POST'])
@token_required
def wallet_topup(current_user):
    student_id = _get_student_id(current_user['id'])
    data = request.get_json() or {}
    amount = float(data.get('amount', 0))
    
    if amount <= 0:
        return jsonify({"message": "Invalid amount"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE student_wallet SET balance = balance + ? WHERE student_id = ?", (amount, student_id))
    cursor.execute("""
        INSERT INTO wallet_transactions (student_id, amount, type, description)
        VALUES (?, ?, 'credit', 'Wallet Top-up')
    """, (student_id, amount))
    conn.commit()
    cursor.close()
    conn.close()
    
    return jsonify({"message": "Wallet topped up successfully"}), 200

# PHASE 10: SMART EXAM SCHEDULER & AUTOMATED WORKFLOW ENGINE ROUTES

@app.route('/exams/schedule', methods=['GET'])
@token_required
def get_exam_schedule(current_user):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT es.*, cs.subject_name, cs.semester 
        FROM exam_schedules es
        JOIN curriculum_subjects cs ON es.subject_id = cs.id
        ORDER BY es.exam_date ASC, es.start_time ASC
    """)
    rows = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"schedule": rows}), 200

@app.route('/admin/workflows/run', methods=['POST'])
@token_required
def run_workflow_engine(current_user):
    if current_user['role'] != 'admin':
        return jsonify({"message": "Unauthorized"}), 403
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Fetch active rules
    cursor.execute("SELECT * FROM workflow_rules WHERE is_active = 1")
    rules = [row_to_dict(r) for r in cursor.fetchall()]
    
    # 2. Process each rule
    actions_count = 0
    for rule in rules:
        action_cfg = json.loads(rule['action_json'])
        
        if rule['trigger_type'] == 'low_attendance':
            # Find students below threshold
            cursor.execute("SELECT id, name FROM students WHERE attendance < ?", (rule['threshold'],))
            students = cursor.fetchall()
            for s in students:
                sid = s[0]
                # Check if we already logged this recently (e.g. today) to avoid spam
                cursor.execute("SELECT id FROM workflow_logs WHERE rule_id = ? AND student_id = ? AND date(created_at) = date('now')", (rule['id'], sid))
                if not cursor.fetchone():
                    msg = f"Alert: Attendance for {s[1]} is below {rule['threshold']}%."
                    if 'student' in action_cfg.get('notify', []):
                        _notify_student_and_parents(sid, "Attendance Warning", msg, "academic")
                    
                    cursor.execute("INSERT INTO workflow_logs (rule_id, student_id, action_taken) VALUES (?, ?, ?)", (rule['id'], sid, "Notification Sent"))
                    actions_count += 1

        elif rule['trigger_type'] == 'low_marks':
            # Simplified: check average marks from some table (e.g. student_metrics_history)
            cursor.execute("""
                SELECT student_id, AVG(predicted_marks) as avg_marks 
                FROM student_metrics_history 
                GROUP BY student_id 
                HAVING avg_marks < ?
            """, (rule['threshold'],))
            struggling = cursor.fetchall()
            for row in struggling:
                sid = row[0]
                cursor.execute("SELECT id FROM workflow_logs WHERE rule_id = ? AND student_id = ? AND date(created_at) = date('now')", (rule['id'], sid))
                if not cursor.fetchone():
                    msg = f"Alert: Academic performance is dropping. Predicted average: {row[1]:.1f}."
                    _notify_student_and_parents(sid, "Performance Alert", msg, "academic")
                    cursor.execute("INSERT INTO workflow_logs (rule_id, student_id, action_taken) VALUES (?, ?, ?)", (rule['id'], sid, "Notification Sent"))
                    actions_count += 1

    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"message": f"Workflow engine processed {actions_count} actions."}), 200

# END PHASE 10

# END PHASE 9

# END PHASE 8

# END PHASE 7

# PHASE 11: HEALTH, PARENT & ADVANCED ACADEMIC FEATURES

@app.route('/student/wellness', methods=['GET', 'POST'])
@token_required
def handle_wellness(current_user):
    student_id = _get_student_id(current_user['id'])
    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'POST':
        data = request.get_json() or {}
        log_date = data.get('log_date') or datetime.now(timezone.utc).date().isoformat()
        cursor.execute("""
            INSERT INTO wellness_logs (student_id, log_date, sleep_hours, stress_level, focus_score)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(student_id, log_date) DO UPDATE SET
                sleep_hours=excluded.sleep_hours,
                stress_level=excluded.stress_level,
                focus_score=excluded.focus_score
        """, (student_id, log_date, data.get('sleep_hours'), data.get('stress_level'), data.get('focus_score')))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"message": "Wellness log saved"}), 200

    cursor.execute("SELECT * FROM wellness_logs WHERE student_id = ? ORDER BY log_date DESC LIMIT 30", (student_id,))
    rows = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"items": rows}), 200

@app.route('/parent/digest/<int:parent_id>', methods=['GET'])
@token_required
def get_parent_digest(current_user, parent_id):
    if current_user['role'] not in ['admin', 'parent']:
        return jsonify({"message": "Unauthorized"}), 403
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM parent_daily_summaries WHERE parent_id = ? ORDER BY summary_date DESC LIMIT 7", (parent_id,))
    rows = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"summaries": rows}), 200

@app.route('/academic/lectures', methods=['GET', 'POST'])
@token_required
def handle_lectures(current_user):
    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'POST':
        if current_user['role'] not in ['admin', 'faculty']:
            return jsonify({"message": "Unauthorized"}), 403
        data = request.get_json() or {}
        cursor.execute("""
            INSERT INTO lecture_recordings (subject_id, title, video_url, duration_minutes)
            VALUES (?, ?, ?, ?)
        """, (data.get('subject_id'), data.get('title'), data.get('video_url'), data.get('duration_minutes')))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"message": "Lecture recording added"}), 201

    subject_id = request.args.get('subject_id')
    if subject_id:
        cursor.execute("SELECT * FROM lecture_recordings WHERE subject_id = ? ORDER BY recorded_at DESC", (subject_id,))
    else:
        cursor.execute("SELECT * FROM lecture_recordings ORDER BY recorded_at DESC")
    
    rows = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"items": rows}), 200

@app.route('/academic/flashcards', methods=['GET', 'POST'])
@token_required
def handle_flashcards(current_user):
    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'POST':
        if current_user['role'] not in ['admin', 'faculty']:
            return jsonify({"message": "Unauthorized"}), 403
        data = request.get_json() or {}
        cursor.execute("""
            INSERT INTO flashcards (subject_id, question, answer)
            VALUES (?, ?, ?)
        """, (data.get('subject_id'), data.get('question'), data.get('answer')))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"message": "Flashcard added"}), 201

    subject_id = request.args.get('subject_id')
    if subject_id:
        cursor.execute("SELECT * FROM flashcards WHERE subject_id = ?", (subject_id,))
    else:
        cursor.execute("SELECT * FROM flashcards")
    
    rows = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"items": rows}), 200

@app.route('/placement/companies', methods=['GET', 'POST'])
@token_required
def handle_companies(current_user):
    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'POST':
        if current_user['role'] != 'admin':
            return jsonify({"message": "Unauthorized"}), 403
        data = request.get_json() or {}
        cursor.execute("""
            INSERT INTO companies (name, website, industry, description)
            VALUES (?, ?, ?, ?)
        """, (data.get('name'), data.get('website'), data.get('industry'), data.get('description')))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"message": "Company registered"}), 201

    cursor.execute("SELECT * FROM companies ORDER BY name ASC")
    rows = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"items": rows}), 200

@app.route('/placement/mock-interviews', methods=['GET', 'POST'])
@token_required
def handle_mock_interviews(current_user):
    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'POST':
        if current_user['role'] not in ['admin', 'faculty']:
            return jsonify({"message": "Unauthorized"}), 403
        data = request.get_json() or {}
        cursor.execute("""
            INSERT INTO mock_interviews (student_id, interviewer_name, scheduled_at, feedback, score, status)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (data.get('student_id'), data.get('interviewer_name'), data.get('scheduled_at'), data.get('feedback'), data.get('score'), data.get('status', 'scheduled')))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"message": "Mock interview scheduled/updated"}), 201

    student_id = request.args.get('student_id')
    if student_id:
        cursor.execute("SELECT * FROM mock_interviews WHERE student_id = ? ORDER BY scheduled_at DESC", (student_id,))
    else:
        cursor.execute("SELECT * FROM mock_interviews ORDER BY scheduled_at DESC")
    
    rows = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"items": rows}), 200

@app.route('/campus/study-groups', methods=['GET', 'POST'])
@token_required
def handle_study_groups(current_user):
    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'POST':
        data = request.get_json() or {}
        cursor.execute("""
            INSERT INTO study_groups (name, subject_id, created_by)
            VALUES (?, ?, ?)
        """, (data.get('name'), data.get('subject_id'), current_user['id']))
        group_id = cursor.lastrowid
        cursor.execute("INSERT INTO study_group_members (group_id, student_id) VALUES (?, ?)", (group_id, current_user['id']))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"message": "Study group created", "id": group_id}), 201

    cursor.execute("""
        SELECT sg.*, cs.subject_name 
        FROM study_groups sg
        LEFT JOIN curriculum_subjects cs ON sg.subject_id = cs.id
    """)
    rows = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"items": rows}), 200

@app.route('/academic/plagiarism-check', methods=['POST'])
@token_required
def check_plagiarism(current_user):
    data = request.get_json() or {}
    text = data.get('text', '')
    if not text:
        return jsonify({"message": "No text provided"}), 400
    
    # Mock plagiarism check logic
    score = random.randint(0, 15) # Usually 0-15% is normal
    if "lorem ipsum" in text.lower():
        score = 85
        
    return jsonify({
        "plagiarism_score": score,
        "status": "passed" if score < 20 else "failed",
        "matches": [
            {"source": "Internet Archive", "percentage": score if score > 5 else 0}
        ] if score > 0 else []
    }), 200

# PHASE 12: AUTOMATION, AUDIT & EXAM SCHEDULER

@app.route('/automation/low-attendance-workflow', methods=['POST'])
@token_required
def run_low_attendance_workflow(current_user):
    if current_user['role'] != 'admin':
        return jsonify({"message": "Unauthorized"}), 403
        
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Find students with attendance < 75%
    cursor.execute("""
        SELECT s.id, s.name, u.email, p.id as parent_id, pu.email as parent_email, 
               (SELECT AVG(CASE WHEN status='present' THEN 100 ELSE 0 END) FROM attendance WHERE student_id = s.id) as att_rate
        FROM students s
        JOIN users u ON s.user_id = u.id
        LEFT JOIN parents p ON p.student_id = s.id
        LEFT JOIN users pu ON p.user_id = pu.id
        GROUP BY s.id
        HAVING att_rate < 75
    """)
    at_risk = cursor.fetchall()
    
    actions = []
    for s in at_risk:
        # 1. Alert Student
        cursor.execute("INSERT INTO notifications (user_id, title, message) VALUES (?, ?, ?)", 
                       (s['id'], "Low Attendance Alert", f"Your attendance is {s['att_rate']:.1f}%. Please attend classes regularly."))
        
        # 2. Alert Parent
        if s['parent_id']:
            cursor.execute("INSERT INTO notifications (user_id, title, message) VALUES (?, ?, ?)", 
                           (s['parent_id'], "Child Attendance Alert", f"Your child {s['name']}'s attendance is low ({s['att_rate']:.1f}%)."))
        
        # 3. Faculty Reminder (Auto Attendance Reminder)
        cursor.execute("""
            INSERT INTO notifications (user_id, title, message)
            SELECT faculty_id, 'Attendance Reminder', ?
            FROM subjects_master
            WHERE id IN (SELECT subject_id FROM student_gpa_grades WHERE student_id = ?)
        """, (f"Reminder: Please verify attendance for {s['name']} (Current: {s['att_rate']:.1f}%)", s['id']))

        # 4. Schedule Counseling
        cursor.execute("INSERT INTO counseling_appointments (student_id, counselor_name, appointment_date, notes) VALUES (?, ?, ?, ?)",
                       (s['id'], "Auto-System", (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(), "Automatic counseling for low attendance."))
        
        actions.append({"student": s['name'], "rate": s['att_rate']})
        
    conn.commit()
    cursor.close()
    conn.close()
    
    return jsonify({"message": f"Workflow executed for {len(actions)} students", "actions": actions}), 200

@app.route('/academic/auto-exam-scheduler', methods=['POST'])
@token_required
def auto_exam_scheduler(current_user):
    if current_user['role'] != 'admin':
        return jsonify({"message": "Unauthorized"}), 403
    
    data = request.get_json() or {}
    semester = data.get('semester')
    start_date = datetime.fromisoformat(data.get('start_date', datetime.now(timezone.utc).date().isoformat()))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get all subjects for the semester
    cursor.execute("SELECT * FROM subjects_master WHERE semester_id = ?", (semester,))
    subjects = cursor.fetchall()
    
    if not subjects:
        return jsonify({"message": "No subjects found for this semester"}), 404
        
    scheduled = []
    current_exam_date = start_date
    
    for sub in subjects:
        # Schedule one exam every 2 days
        exam_time = "10:00 AM - 01:00 PM"
        room = f"Room {random.randint(101, 505)}"
        
        cursor.execute("""
            INSERT INTO exam_schedules (subject_id, exam_date, exam_time, room_number, exam_type)
            VALUES (?, ?, ?, ?, 'Final Semester')
        """, (sub['id'], current_exam_date.date().isoformat(), exam_time, room))
        
        scheduled.append({"subject": sub['name'], "date": current_exam_date.date().isoformat()})
        current_exam_date += timedelta(days=2)
        
    conn.commit()
    cursor.close()
    conn.close()
    
    return jsonify({"message": "Exams scheduled successfully", "scheduled": scheduled}), 201

@app.route('/analytics/audit-logs', methods=['GET'])
@token_required
def get_audit_logs(current_user):
    if current_user['role'] != 'admin':
        return jsonify({"message": "Unauthorized"}), 403
        
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT 100")
    rows = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"items": rows}), 200

# PHASE 13: PARKING, SMART EXAMS & ADVANCED ANALYTICS

@app.route('/campus/parking/slots', methods=['GET'])
@token_required
def get_parking_slots(current_user):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM parking_slots")
    rows = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"items": rows}), 200

@app.route('/campus/parking/register', methods=['POST'])
@token_required
def register_vehicle(current_user):
    data = request.get_json() or {}
    vehicle_number = data.get('vehicle_number')
    vehicle_type = data.get('vehicle_type')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO vehicle_registrations (user_id, vehicle_number, vehicle_type)
            VALUES (?, ?, ?)
        """, (current_user['id'], vehicle_number, vehicle_type))
        conn.commit()
        return jsonify({"message": "Vehicle registered"}), 201
    except sqlite3.IntegrityError:
        return jsonify({"message": "Vehicle already registered"}), 400
    finally:
        cursor.close()
        conn.close()

@app.route('/academic/exams/adaptive-difficulty', methods=['POST'])
@token_required
def adaptive_exam_difficulty(current_user):
    # Mock AI logic: Adjust difficulty based on student's past performance
    student_id = _get_student_id(current_user['id'])
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT AVG(grade_points) FROM student_gpa_grades WHERE student_id = ?", (student_id,))
    avg_gp = cursor.fetchone()[0] or 5.0
    
    difficulty = "intermediate"
    if avg_gp > 8.5: difficulty = "advanced"
    elif avg_gp < 5.0: difficulty = "basic"
    
    cursor.close()
    conn.close()
    return jsonify({
        "student_id": student_id,
        "recommended_difficulty": difficulty,
        "reason": f"Average GPA is {avg_gp:.1f}"
    }), 200

@app.route('/academic/exams/cheat-detection', methods=['POST'])
@token_required
def ai_cheat_detection(current_user):
    # Mock AI logic: Analyze patterns (tab switching, eye tracking mock, etc.)
    data = request.get_json() or {}
    patterns = data.get('patterns', [])
    
    suspicious = False
    if len(patterns) > 3: # Mock: more than 3 tab switches
        suspicious = True
        
    return jsonify({
        "is_suspicious": suspicious,
        "confidence": 0.85 if suspicious else 0.1,
        "alert": "Unusual activity detected" if suspicious else "Normal behavior"
    }), 200

@app.route('/campus/events/live', methods=['GET'])
@token_required
def get_live_events(current_user):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM campus_events WHERE is_live = 1 OR event_date > CURRENT_TIMESTAMP ORDER BY event_date ASC")
    rows = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"items": rows}), 200

@app.route('/admin/institution-comparison', methods=['GET'])
@token_required
def institution_comparison(current_user):
    if current_user['role'] != 'admin':
        return jsonify({"message": "Unauthorized"}), 403
        
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Comparison by department
    cursor.execute("""
        SELECT dm.name as department, 
               AVG(s.attendance) as avg_attendance,
               COUNT(s.id) as student_count
        FROM departments_master dm
        LEFT JOIN students s ON s.department_id = dm.id
        GROUP BY dm.id
    """)
    rows = [row_to_dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({"comparison": rows}), 200

@app.route('/admin/cloud-backup', methods=['POST'])
@token_required
def run_cloud_backup(current_user):
    if current_user['role'] != 'admin':
        return jsonify({"message": "Unauthorized"}), 403
    
    # Mock backup logic
    return jsonify({
        "status": "success",
        "backup_id": f"bkp-{random.randint(1000, 9999)}",
        "size_mb": 45.2,
        "destination": "AWS S3 / Cloud Storage"
    }), 200

# END PHASE 13

if __name__ == '__main__':
    _ensure_history_tables()
    socketio.run(app, debug=True, port=5000, host='0.0.0.0')
