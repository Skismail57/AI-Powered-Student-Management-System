import sqlite3
import os
import json
from werkzeug.security import generate_password_hash
import sys
import datetime

# Add the current directory to sys.path to import app
sys.path.append(os.path.dirname(__file__))
from app import _ensure_history_tables

DB_PATH = os.path.join(os.path.dirname(__file__), 'student_system.db')

def seed_data():
    # Ensure tables exist first
    _ensure_history_tables()
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Manual migrations for students table in seed script
    try:
        cursor.execute("ALTER TABLE students ADD COLUMN department_id INTEGER REFERENCES departments_master(id)")
    except Exception: pass
    try:
        cursor.execute("ALTER TABLE students ADD COLUMN semester_id INTEGER REFERENCES semesters_master(id)")
    except Exception: pass
    try:
        cursor.execute("ALTER TABLE students ADD COLUMN mobile TEXT")
    except Exception: pass
    conn.commit()

    print("🌱 Seeding Full-Scale Smart Education ERP data...")

    # 1. Admin User
    print("👤 Seeding Admin User...")
    admin_mobile = "1234567890"
    admin_pw = generate_password_hash("admin123")
    cursor.execute("INSERT OR IGNORE INTO users (name, role, mobile, password) VALUES (?, ?, ?, ?)",
                   ("Admin User", "admin", admin_mobile, admin_pw))

    # 2. Add Institutions (Bengaluru Colleges)
    print("🏫 Seeding Bengaluru Colleges...")
    colleges = [
        ("RV College of Engineering", "engineering", "https://images.unsplash.com/photo-1562774053-701939374585?auto=format&fit=crop&w=800&q=80"),
        ("PES University", "university", "https://images.unsplash.com/photo-1541339907198-e08756ebafe3?auto=format&fit=crop&w=800&q=80"),
        ("MS Ramaiah Institute of Technology", "engineering", "https://images.unsplash.com/photo-1523050853064-953327530612?auto=format&fit=crop&w=800&q=80"),
        ("BMS College of Engineering", "engineering", "https://images.unsplash.com/photo-1592280771190-3e2e4d571952?auto=format&fit=crop&w=800&q=80"),
        ("St. John's Medical College", "medical", "https://images.unsplash.com/photo-1519494026892-80bbd2d6fd0d?auto=format&fit=crop&w=800&q=80")
    ]
    
    inst_ids = {}
    for name, itype, img in colleges:
        cursor.execute("INSERT OR IGNORE INTO institutions (name, type, image_url) VALUES (?, ?, ?)", 
                       (name, itype, img))
        cursor.execute("SELECT id FROM institutions WHERE name = ?", (name,))
        inst_ids[name] = cursor.fetchone()[0]

    # Use RVCE as primary for seeding departments
    inst_id = inst_ids["RV College of Engineering"]

    # 3. ENGINEERING MODULES
    eng_depts = [
        ("Computer Science Engineering", "engineering"), ("AI & ML", "engineering"),
        ("Information Science", "engineering"), ("Electronics & Communication", "engineering"),
        ("Electrical Engineering", "engineering"), ("Mechanical Engineering", "engineering"),
        ("Civil Engineering", "engineering"), ("Aerospace Engineering", "engineering"),
        ("Biotechnology", "engineering"), ("Chemical Engineering", "engineering"),
        ("Data Science", "engineering"), ("Cyber Security", "engineering"),
        ("Robotics", "engineering"), ("IoT", "engineering"), ("Automobile Engineering", "engineering")
    ]
    
    dept_ids = {}
    for name, stream in eng_depts:
        cursor.execute("INSERT OR IGNORE INTO departments_master (institution_id, name, stream) VALUES (?, ?, ?)",
                       (inst_id, name, stream))
        cursor.execute("SELECT id FROM departments_master WHERE name = ? AND institution_id = ?", (name, inst_id))
        dept_ids[name] = cursor.fetchone()[0]

    # 4. MEDICAL MODULES
    med_inst_id = inst_ids["St. John's Medical College"]
    med_depts = [
        ("MBBS", "medical"), ("Nursing", "medical"), ("Physiotherapy", "medical"),
        ("Pharmacy", "medical"), ("Dentistry", "medical"), ("Radiology", "medical"),
        ("Pathology", "medical"), ("Cardiology", "medical"), ("Neurology", "medical"),
        ("Anatomy", "medical"), ("Biochemistry", "medical"), ("Microbiology", "medical")
    ]
    for name, stream in med_depts:
        cursor.execute("INSERT OR IGNORE INTO departments_master (institution_id, name, stream) VALUES (?, ?, ?)",
                       (med_inst_id, name, stream))
        cursor.execute("SELECT id FROM departments_master WHERE name = ? AND institution_id = ?", (name, med_inst_id))
        dept_ids[name] = cursor.fetchone()[0]

    # 5. COMMERCE MODULES
    comm_inst_id = inst_ids["PES University"]
    comm_depts = [
        ("BCom", "commerce"), ("BBA", "commerce"), ("MBA", "commerce"),
        ("Finance", "commerce"), ("Accounting", "commerce"), ("Economics", "commerce"),
        ("Banking", "commerce"), ("Marketing", "commerce"), ("HR Management", "commerce")
    ]
    for name, stream in comm_depts:
        cursor.execute("INSERT OR IGNORE INTO departments_master (institution_id, name, stream) VALUES (?, ?, ?)",
                       (comm_inst_id, name, stream))
        cursor.execute("SELECT id FROM departments_master WHERE name = ? AND institution_id = ?", (name, comm_inst_id))
        dept_ids[name] = cursor.fetchone()[0]

    # 6. Semesters for all institutions
    for iid in inst_ids.values():
        semesters = [f"Semester {i}" for i in range(1, 9)]
        for i, name in enumerate(semesters):
            cursor.execute("INSERT OR IGNORE INTO semesters_master (institution_id, name, order_index) VALUES (?, ?, ?)",
                           (iid, name, i + 1))
    
    # Fetch sem_ids for RVCE for subjects
    cursor.execute("SELECT id FROM semesters_master WHERE institution_id = ? ORDER BY order_index", (inst_id,))
    rvce_sem_ids = [row[0] for row in cursor.fetchall()]

    # 7. SUBJECTS
    print("📚 Seeding Subjects...")
    # Engineering Subjects (CSE/AIML)
    eng_subjects = [
        ("Python Programming", "CSE101"), ("Database Management Systems", "CSE301"), 
        ("Operating Systems", "CSE302"), ("Computer Networks", "CSE401"), 
        ("Machine Learning", "AI401"), ("Deep Learning", "AI501"),
        ("Artificial Intelligence", "AI502"), ("Software Engineering", "CSE303"), 
        ("Data Structures & Algorithms", "CSE201"), ("Compiler Design", "CSE402"),
        ("Cloud Computing", "CSE501"), ("Cyber Security Fundamentals", "CS601")
    ]
    for name, code in eng_subjects:
        cursor.execute("INSERT OR IGNORE INTO subjects_master (department_id, semester_id, code, name) VALUES (?, ?, ?, ?)",
                       (dept_ids["Computer Science Engineering"], rvce_sem_ids[2], code, name))

    # Medical Subjects (MBBS/Anatomy)
    cursor.execute("SELECT id FROM semesters_master WHERE institution_id = ? ORDER BY order_index", (med_inst_id,))
    med_sem_ids = [row[0] for row in cursor.fetchall()]
    med_subjects = [
        ("Human Anatomy", "MED101"), ("Physiology", "MED102"), ("Biochemistry", "MED103"),
        ("Pathology", "MED201"), ("Pharmacology", "MED202"), ("Microbiology", "MED203"),
        ("General Surgery", "MED301"), ("Internal Medicine", "MED302"),
        ("Pediatrics", "MED401"), ("Obstetrics & Gynecology", "MED402")
    ]
    for name, code in med_subjects:
        cursor.execute("INSERT OR IGNORE INTO subjects_master (department_id, semester_id, code, name) VALUES (?, ?, ?, ?)",
                       (dept_ids["MBBS"], med_sem_ids[0], code, name))

    # 8. FACULTY
    print("👨‍🏫 Seeding Realistic Faculty...")
    faculty_data = [
        ("Dr. Ramesh Babu", "faculty", "9876543210", "password123", "Professor", "Computer Science Engineering", "Machine Learning & AI", "20+ years of experience in AI research.", "https://images.unsplash.com/photo-1537368910025-700350fe46c7?auto=format&fit=crop&w=400&q=80"),
        ("Dr. Sneha Kulkarni", "faculty", "9876543211", "password123", "Associate Professor", "MBBS", "Cardiology", "Specialist in cardiovascular diseases and research.", "https://images.unsplash.com/photo-1559839734-2b71f1e3c77e?auto=format&fit=crop&w=400&q=80"),
        ("Prof. Ananth Kumar", "faculty", "9876543212", "password123", "Head of Department", "BCom", "Financial Accounting", "Expert in corporate finance and taxation.", "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?auto=format&fit=crop&w=400&q=80")
    ]
    
    hashed_pw = generate_password_hash("password123")
    for name, role, mobile, pw, desig, dept_name, spec, bio, img in faculty_data:
        cursor.execute("INSERT OR IGNORE INTO users (name, role, mobile, password) VALUES (?, ?, ?, ?)",
                       (name, role, mobile, hashed_pw))
        cursor.execute("SELECT id FROM users WHERE mobile = ?", (mobile,))
        u_id = cursor.fetchone()[0]
        
        d_id = dept_ids.get(dept_name)
        cursor.execute("""
            INSERT OR IGNORE INTO faculty_profiles (user_id, designation, department_id, specialization, bio, image_url)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (u_id, desig, d_id, spec, bio, img))

    # 9. Create Demo Students
    print("👨‍🎓 Creating demo students...")
    cursor.execute("""
        INSERT OR IGNORE INTO students (name, attendance, study_hours, sleep_hours, department_id, semester_id, mobile)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, ("Demo CSE Student", 85, 4.5, 7, dept_ids["Computer Science Engineering"], rvce_sem_ids[2], "9999999999"))
    cursor.execute("SELECT id FROM students WHERE mobile = ?", ("9999999999",))
    cse_student_id = cursor.fetchone()[0]

    cursor.execute("""
        INSERT OR IGNORE INTO students (name, attendance, study_hours, sleep_hours, department_id, semester_id, mobile)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, ("Demo Medical Student", 92, 6, 6, dept_ids["MBBS"], med_sem_ids[0], "8888888888"))
    cursor.execute("SELECT id FROM students WHERE mobile = ?", ("8888888888",))
    med_student_id = cursor.fetchone()[0]

    # Link students to users for login
    hashed_pw = generate_password_hash("password123")
    cursor.execute("INSERT OR IGNORE INTO users (name, role, mobile, password) VALUES (?, ?, ?, ?)",
                   ("Demo CSE Student", "student", "9999999999", hashed_pw))
    cursor.execute("SELECT id FROM users WHERE mobile = ?", ("9999999999",))
    cse_user_id = cursor.fetchone()[0]
    cursor.execute("INSERT OR IGNORE INTO student_user_links (user_id, student_id) VALUES (?, ?)",
                   (cse_user_id, cse_student_id))
    
    cursor.execute("INSERT OR IGNORE INTO users (name, role, mobile, password) VALUES (?, ?, ?, ?)",
                   ("Demo Medical Student", "student", "8888888888", hashed_pw))
    cursor.execute("SELECT id FROM users WHERE mobile = ?", ("8888888888",))
    med_user_id = cursor.fetchone()[0]
    cursor.execute("INSERT OR IGNORE INTO student_user_links (user_id, student_id) VALUES (?, ?)",
                   (med_user_id, med_student_id))

    # 10. Parents
    print("👨‍👩‍👧 Seeding Parents...")
    parent_pw = generate_password_hash("parent123")
    cursor.execute("""
        INSERT OR IGNORE INTO parents (name, mobile, password, student_id)
        VALUES (?, ?, ?, ?)
    """, ("Demo Parent", "7777777777", parent_pw, cse_student_id))
    cursor.execute("SELECT id FROM parents WHERE mobile = '7777777777'")
    parent_id = cursor.fetchone()[0]
    cursor.execute("INSERT OR IGNORE INTO users (name, role, mobile, password) VALUES (?, ?, ?, ?)",
                   ("Demo Parent", "parent", "7777777777", parent_pw))

    # 11. NOTIFICATIONS
    print("🔔 Seeding Notifications...")
    notifications = [
        ("student", cse_user_id, "Welcome!", "Welcome to the Smart Education ERP system.", "general"),
        ("student", cse_user_id, "Assignment Due", "Your Python assignment is due tomorrow.", "academic"),
        ("parent", parent_id, "Attendance Alert", "Your ward's attendance is below 75% in one subject.", "alert")
    ]
    for role, rid, title, msg, cat in notifications:
        cursor.execute("INSERT INTO notifications (recipient_role, recipient_id, title, message, category) VALUES (?, ?, ?, ?, ?)", 
                       (role, rid, title, msg, cat))

    # 12. ATTENDANCE
    print("📅 Seeding Attendance...")
    today = datetime.date.today()
    for i in range(15):
        date = (today - datetime.timedelta(days=i)).isoformat()
        cursor.execute("INSERT INTO attendance (student_id, date, status) VALUES (?, ?, ?)", 
                       (cse_student_id, date, "present" if i % 5 != 0 else "absent"))

    # 13. TIMETABLE
    print("⏰ Seeding Timetable...")
    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
    cursor.execute("SELECT id FROM subjects_master WHERE department_id = ?", (dept_ids["Computer Science Engineering"],))
    cse_subs = [r[0] for r in cursor.fetchall()]
    if cse_subs:
        for day in days:
            for slot in range(4):
                cursor.execute("""
                    INSERT INTO timetables (dept_id, semester, day_of_week, start_time, end_time, subject_id, room_number)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (dept_ids["Computer Science Engineering"], rvce_sem_ids[2], day, f"{9+slot}:00", f"{10+slot}:00", cse_subs[slot % len(cse_subs)], f"LHC-{100+slot}"))

    # 14. Library, Jobs, etc.
    print("📚 Seeding Library & Jobs...")
    books = [("Clean Code", "Robert C. Martin", "CS", "978-0132350884", 5, "")]
    for t, a, c, i, cp, p in books:
        cursor.execute("INSERT OR IGNORE INTO library_books (title, author, category, isbn, available_copies, pdf_url) VALUES (?, ?, ?, ?, ?, ?)", (t, a, c, i, cp, p))
    
    jobs = [("Google", "SDE", "Dev role", "30 LPA", "Remote", "2024-12-31", "B.Tech")]
    for co, r, d, s, l, dl, req in jobs:
        cursor.execute("INSERT OR IGNORE INTO placement_jobs (company_name, role, description, salary_package, location, deadline, requirements) VALUES (?, ?, ?, ?, ?, ?, ?)", (co, r, d, s, l, dl, req))

    conn.commit()
    cursor.close()
    conn.close()
    print("✅ All data seeded successfully!")

if __name__ == "__main__":
    seed_data()
