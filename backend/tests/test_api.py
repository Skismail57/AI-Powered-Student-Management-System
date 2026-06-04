import sys
from pathlib import Path


def _import_app(monkeypatch, tmp_path):
    # Add backend folder to sys.path so `app.py` can import `model`, `db`, etc.
    project_root = Path(__file__).resolve().parents[2]
    backend_dir = project_root / "backend"
    sys.path.insert(0, str(backend_dir))

    import db as db_module
    monkeypatch.setattr(db_module, "DB_PATH", str(tmp_path / "test.db"), raising=False)

    import app as app_module
    app_module.app.config['TESTING'] = True

    # Create core tables (minimal schema) in the temp DB for tests.
    conn = db_module.get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin', 'student', 'faculty')),
            mobile TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            attendance INTEGER DEFAULT 0,
            study_hours REAL DEFAULT 0,
            sleep_hours REAL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER,
            date DATE,
            status TEXT CHECK(status IN ('present', 'absent')),
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER,
            amount REAL NOT NULL,
            status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'completed', 'failed')),
            payment_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS announcements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course TEXT NOT NULL,
            file TEXT NOT NULL,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    cur.close()
    conn.close()

    # Ensure history table exists too.
    app_module._ensure_history_tables()
    return app_module


def _auth_header(token: str):
    return {"Authorization": f"Bearer {token}"}


def test_register_login_and_refresh(monkeypatch, tmp_path):
    app_module = _import_app(monkeypatch, tmp_path)
    client = app_module.app.test_client()

    r = client.post(
        "/register",
        json={"name": "Test User", "role": "admin", "mobile": "9999999999", "password": "pass1234"},
    )
    assert r.status_code in (201, 500, 400)

    r = client.post("/login", json={"mobile": "9999999999", "password": "pass1234"})
    assert r.status_code == 200
    data = r.get_json()
    assert "token" in data

    r = client.post("/token/refresh", headers=_auth_header(data["token"]))
    assert r.status_code == 200
    assert "token" in r.get_json()


def test_students_pagination(monkeypatch, tmp_path):
    app_module = _import_app(monkeypatch, tmp_path)
    client = app_module.app.test_client()

    client.post("/register", json={"name": "Admin", "role": "admin", "mobile": "1234500000", "password": "admin123"})
    login = client.post("/login", json={"mobile": "1234500000", "password": "admin123"}).get_json()
    token = login["token"]

    for i in range(30):
        res = client.post(
            "/students",
            headers=_auth_header(token),
            json={"name": f"Student {i}", "attendance": 80, "study_hours": 2.5, "sleep_hours": 7},
        )
        assert res.status_code == 201

    res = client.get("/students?paged=1&page=1&page_size=10", headers=_auth_header(token))
    assert res.status_code == 200
    data = res.get_json()
    assert data["page"] == 1
    assert data["page_size"] == 10
    assert data["total"] >= 30
    assert len(data["items"]) == 10


def test_reports_require_privileged_role(monkeypatch, tmp_path):
    app_module = _import_app(monkeypatch, tmp_path)
    client = app_module.app.test_client()

    client.post("/register", json={"name": "Student", "role": "student", "mobile": "1111222233", "password": "pass1234"})
    login = client.post("/login", json={"mobile": "1111222233", "password": "pass1234"}).get_json()
    token = login["token"]

    res = client.get("/reports/students.csv", headers=_auth_header(token))
    assert res.status_code == 403


def test_student_crud_and_attendance_flow(monkeypatch, tmp_path):
    app_module = _import_app(monkeypatch, tmp_path)
    client = app_module.app.test_client()

    client.post("/register", json={"name": "Admin", "role": "admin", "mobile": "7777000011", "password": "admin123"})
    token = client.post("/login", json={"mobile": "7777000011", "password": "admin123"}).get_json()["token"]

    created = client.post(
        "/students",
        headers=_auth_header(token),
        json={"name": "Flow Student", "attendance": 72, "study_hours": 2.2, "sleep_hours": 6.8},
    )
    assert created.status_code == 201

    page = client.get("/students?paged=1&page=1&page_size=5", headers=_auth_header(token)).get_json()
    assert page["total"] >= 1
    sid = page["items"][0]["id"]

    updated = client.put(
        f"/students/{sid}",
        headers=_auth_header(token),
        json={"name": "Flow Student Updated", "attendance": 75, "study_hours": 2.8, "sleep_hours": 7.0},
    )
    assert updated.status_code == 200

    att = client.post(
        "/attendance",
        headers=_auth_header(token),
        json={"student_id": sid, "date": "2026-05-06", "status": "present", "notes": "on time"},
    )
    assert att.status_code == 201

    deleted = client.delete(f"/students/{sid}", headers=_auth_header(token))
    assert deleted.status_code == 200


def test_invalid_input_edge_cases(monkeypatch, tmp_path):
    app_module = _import_app(monkeypatch, tmp_path)
    client = app_module.app.test_client()

    client.post("/register", json={"name": "Admin", "role": "admin", "mobile": "8888000011", "password": "admin123"})
    token = client.post("/login", json={"mobile": "8888000011", "password": "admin123"}).get_json()["token"]

    bad_student = client.post(
        "/students",
        headers=_auth_header(token),
        json={"name": "A", "attendance": 130, "study_hours": -1, "sleep_hours": 30},
    )
    assert bad_student.status_code == 400

    bad_attendance = client.post(
        "/attendance",
        headers=_auth_header(token),
        json={"student_id": 0, "date": "", "status": "maybe"},
    )
    assert bad_attendance.status_code == 400


def test_master_data_write_forbidden_for_faculty(monkeypatch, tmp_path):
    app_module = _import_app(monkeypatch, tmp_path)
    client = app_module.app.test_client()

    client.post(
        "/register",
        json={"name": "Faculty User", "role": "faculty", "mobile": "5555444433", "password": "pass1234"},
    )
    token = client.post("/login", json={"mobile": "5555444433", "password": "pass1234"}).get_json()["token"]
    h = _auth_header(token)

    assert client.get("/master/departments", headers=h).status_code == 200
    assert client.post("/master/institutions", headers=h, json={"name": "X", "type": "college"}).status_code == 403


def test_student_browse_and_calendar(monkeypatch, tmp_path):
    app_module = _import_app(monkeypatch, tmp_path)
    client = app_module.app.test_client()

    client.post("/register", json={"name": "Admin", "role": "admin", "mobile": "8888777766", "password": "admin123"})
    admin_token = client.post("/login", json={"mobile": "8888777766", "password": "admin123"}).get_json()["token"]
    ah = _auth_header(admin_token)

    inst_id = client.post("/master/institutions", headers=ah, json={"name": "Campus", "type": "college"}).get_json()["id"]
    dept_id = client.post(
        "/master/departments",
        headers=ah,
        json={"institution_id": inst_id, "name": "CSE", "stream": "engineering"},
    ).get_json()["id"]
    sub_id = client.post(
        "/master/subjects",
        headers=ah,
        json={"department_id": dept_id, "name": "Python", "code": "PY101"},
    ).get_json()["id"]

    client.post(
        "/register",
        json={"name": "Student Browse", "role": "student", "mobile": "9999888877", "password": "pass1234"},
    )
    st = _auth_header(client.post("/login", json={"mobile": "9999888877", "password": "pass1234"}).get_json()["token"])

    depts = client.get("/master/departments?stream=engineering", headers=st)
    assert depts.status_code == 200
    assert len(depts.get_json().get("items", [])) >= 1

    mats = client.get(f"/master/materials?subject_id={sub_id}", headers=st)
    assert mats.status_code == 200

    cal = client.get("/academic/calendar?days=30", headers=st)
    assert cal.status_code == 200
    assert "items" in cal.get_json()


def test_gpa_grade_flow(monkeypatch, tmp_path):
    app_module = _import_app(monkeypatch, tmp_path)
    client = app_module.app.test_client()

    client.post("/register", json={"name": "Admin GPA", "role": "admin", "mobile": "1111222233", "password": "admin123"})
    ah = _auth_header(client.post("/login", json={"mobile": "1111222233", "password": "admin123"}).get_json()["token"])

    inst_id = client.post("/master/institutions", headers=ah, json={"name": "GPA College", "type": "college"}).get_json()["id"]
    dept_id = client.post(
        "/master/departments", headers=ah,
        json={"institution_id": inst_id, "name": "CSE", "stream": "engineering"},
    ).get_json()["id"]
    sem_id = client.post(
        "/master/semesters", headers=ah,
        json={"institution_id": inst_id, "name": "Sem 1", "order_index": 1},
    ).get_json()["id"]
    sub_id = client.post(
        "/master/subjects", headers=ah,
        json={"department_id": dept_id, "semester_id": sem_id, "name": "Algorithms", "code": "ALG", "credits": 4},
    ).get_json()["id"]

    client.post(
        "/students", headers=ah,
        json={"name": "GPA Student", "attendance": 80, "study_hours": 5, "sleep_hours": 7},
    )
    students = client.get("/students?limit=5", headers=ah).get_json()
    student_list = students if isinstance(students, list) else students.get("items", [])
    student_id = student_list[0]["id"]

    client.post("/register", json={"name": "Faculty GPA", "role": "faculty", "mobile": "2222333344", "password": "pass1234"})
    fh = _auth_header(client.post("/login", json={"mobile": "2222333344", "password": "pass1234"}).get_json()["token"])

    grade = client.post(
        "/academic/gpa/grades",
        headers=fh,
        json={"student_id": student_id, "subject_id": sub_id, "grade_points": 8.5, "status": "passed"},
    )
    assert grade.status_code == 200
    assert grade.get_json()["summary"]["cgpa"] == 8.5

    view = client.get(f"/academic/gpa/students/{student_id}", headers=fh)
    assert view.status_code == 200
    assert view.get_json()["credits_earned"] == 4

    cur = client.get("/academic/curriculum?semester=1", headers=ah)
    assert cur.status_code == 200
    assert len(cur.get_json().get("items", [])) >= 1


def test_master_data_admin_flow(monkeypatch, tmp_path):
    app_module = _import_app(monkeypatch, tmp_path)
    client = app_module.app.test_client()

    client.post("/register", json={"name": "Admin MD", "role": "admin", "mobile": "6666555544", "password": "admin123"})
    token = client.post("/login", json={"mobile": "6666555544", "password": "admin123"}).get_json()["token"]
    h = _auth_header(token)

    inst = client.post("/master/institutions", headers=h, json={"name": "Test College", "type": "college"})
    assert inst.status_code == 201
    inst_id = inst.get_json()["id"]

    dept = client.post(
        "/master/departments",
        headers=h,
        json={"institution_id": inst_id, "name": "Computer Science", "stream": "engineering"},
    )
    assert dept.status_code == 201
    dept_id = dept.get_json()["id"]

    sem = client.post(
        "/master/semesters",
        headers=h,
        json={"institution_id": inst_id, "name": "Semester 1", "order_index": 1},
    )
    assert sem.status_code == 201
    sem_id = sem.get_json()["id"]

    sub = client.post(
        "/master/subjects",
        headers=h,
        json={"department_id": dept_id, "semester_id": sem_id, "code": "CS101", "name": "Introduction to Programming"},
    )
    assert sub.status_code == 201
    sub_id = sub.get_json()["id"]

    mat = client.post(
        "/master/materials",
        headers=h,
        json={
            "subject_id": sub_id,
            "title": "Syllabus PDF",
            "material_type": "pdf",
            "url": "https://example.com/syllabus.pdf",
            "description": "demo",
        },
    )
    assert mat.status_code == 201

    mats = client.get(f"/master/materials?subject_id={sub_id}", headers=h)
    assert mats.status_code == 200
    assert len(mats.get_json().get("items", [])) >= 1

