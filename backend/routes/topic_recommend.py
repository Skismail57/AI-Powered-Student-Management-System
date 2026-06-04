# AI-Based Topic Recommendation API
from flask import Blueprint, request, jsonify
from db import db_session
from model_topic_progress import TopicProgress

topic_recommend_bp = Blueprint('topic_recommend', __name__)

@topic_recommend_bp.route('/recommend/topic/<int:student_id>/<int:subject_id>', methods=['GET'])
def recommend_topic(student_id, subject_id):
    # Simple logic: recommend the topic with the lowest progress
    progress = TopicProgress.query.filter_by(student_id=student_id, subject_id=subject_id).order_by(TopicProgress.progress_pct.asc()).first()
    if progress:
        return jsonify({'topic': progress.topic_name, 'progress_pct': progress.progress_pct})
    else:
        return jsonify({'message': 'No topics found for this student/subject.'}), 404
