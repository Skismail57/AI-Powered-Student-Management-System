# Faculty Performance Evaluation API Endpoints
from flask import Blueprint, request, jsonify
from db import db_session
from model_faculty_performance import FacultyFeedback, FacultyPerformance

faculty_perf_bp = Blueprint('faculty_perf', __name__)

@faculty_perf_bp.route('/faculty/feedback', methods=['POST'])
def submit_feedback():
    data = request.json
    feedback = FacultyFeedback(
        faculty_id=data['faculty_id'],
        student_id=data['student_id'],
        rating=data['rating'],
        comments=data.get('comments', ''),
        created_at=data.get('created_at', '')
    )
    db_session.add(feedback)
    db_session.commit()
    return jsonify({'id': feedback.id}), 201

@faculty_perf_bp.route('/faculty/performance/<int:faculty_id>', methods=['GET'])
def get_performance(faculty_id):
    perf = FacultyPerformance.query.filter_by(faculty_id=faculty_id).first()
    if perf:
        return jsonify({'avg_rating': perf.avg_rating, 'feedback_count': perf.feedback_count, 'analytics': perf.analytics_json})
    else:
        return jsonify({'message': 'No performance data found.'}), 404
