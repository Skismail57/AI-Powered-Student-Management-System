# Timetable API Endpoints
from flask import Blueprint, request, jsonify
from db import get_db_connection

timetable_bp = Blueprint('timetable', __name__)

@timetable_bp.route('/timetable/<int:dept_id>/<int:semester>', methods=['GET'])
def get_timetable(dept_id, semester):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = """
        SELECT t.*, s.name as subject_name 
        FROM timetables t
        JOIN subjects_master s ON t.subject_id = s.id
        WHERE t.dept_id = ? AND t.semester = ?
    """
    cursor.execute(query, (dept_id, semester))
    rows = cursor.fetchall()
    
    items = []
    for row in rows:
        d = dict(row)
        items.append(d)
        
    cursor.close()
    conn.close()
    return jsonify({"items": items}), 200

@timetable_bp.route('/timetable', methods=['POST'])
def add_timetable():
    data = request.json
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO timetables (dept_id, semester, day_of_week, start_time, end_time, subject_id, room_number)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (data['dept_id'], data['semester'], data['day_of_week'], data['start_time'], 
          data['end_time'], data['subject_id'], data['room_number']))
    
    new_id = cursor.lastrowid
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({'id': new_id}), 201
