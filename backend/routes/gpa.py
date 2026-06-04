# Credit & GPA Management API Endpoints
from flask import Blueprint, request, jsonify
from db import db_session
from model_gpa import StudentGPA

gpa_bp = Blueprint('gpa', __name__)

@gpa_bp.route('/gpa/<int:student_id>', methods=['GET'])
def get_gpa(student_id):
    records = StudentGPA.query.filter_by(student_id=student_id).all()
    return jsonify([
        {'semester': r.semester, 'gpa': r.gpa, 'credits_earned': r.credits_earned, 'backlogs': r.backlogs} for r in records
    ])

@gpa_bp.route('/gpa', methods=['POST'])
def add_gpa():
    data = request.json
    record = StudentGPA(
        student_id=data['student_id'],
        semester=data['semester'],
        gpa=data['gpa'],
        credits_earned=data['credits_earned'],
        backlogs=data.get('backlogs', 0)
    )
    db_session.add(record)
    db_session.commit()
    return jsonify({'id': record.id}), 201
