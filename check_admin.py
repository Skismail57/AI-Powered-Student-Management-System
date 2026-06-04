import sqlite3
import os

DB_PATH = 'backend/student_system.db'
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()
cursor.execute("SELECT id, name, role, mobile FROM users WHERE mobile='1234567890'")
user = cursor.fetchone()
print(f"Admin User: {user}")
conn.close()
