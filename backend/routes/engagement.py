# Classroom Engagement Analytics API Endpoints
from flask import Blueprint, request, jsonify
from db import db_session
from model_engagement_analytics import EngagementAnalytics

engagement_bp = Blueprint('engagement', __name__)

@engagement_bp.route('/engagement/<int:class_id>', methods=['GET'])
def get_engagement(class_id):
    records = EngagementAnalytics.query.filter_by(class_id=class_id).all()
    return jsonify([
        {
            'id': r.id,
            'faculty_id': r.faculty_id,
            'date': r.date,
            'quiz_participation': r.quiz_participation,
            'attendance_interaction': r.attendance_interaction,
            'notes': r.notes
        } for r in records
    ])

@engagement_bp.route('/engagement', methods=['POST'])
def add_engagement():
    data = request.json
    record = EngagementAnalytics(
        class_id=data['class_id'],
        faculty_id=data['faculty_id'],
        date=data['date'],
        quiz_participation=data.get('quiz_participation', 0.0),
        attendance_interaction=data.get('attendance_interaction', 0.0),
        notes=data.get('notes', '')
    )
    db_session.add(record)
    db_session.commit()
    return jsonify({'id': record.id}), 201
