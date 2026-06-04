# Faculty Research Portal API Endpoints
from flask import Blueprint, request, jsonify
from db import db_session
from model_faculty_research import FacultyResearch

faculty_research_bp = Blueprint('faculty_research', __name__)

@faculty_research_bp.route('/faculty/research/<int:faculty_id>', methods=['GET'])
def get_research(faculty_id):
    items = FacultyResearch.query.filter_by(faculty_id=faculty_id).all()
    return jsonify([
        {'id': i.id, 'title': i.title, 'type': i.research_type, 'description': i.description, 'url': i.url, 'year': i.year} for i in items
    ])

@faculty_research_bp.route('/faculty/research', methods=['POST'])
def add_research():
    data = request.json
    item = FacultyResearch(
        faculty_id=data['faculty_id'],
        title=data['title'],
        research_type=data['research_type'],
        description=data.get('description', ''),
        url=data.get('url', ''),
        year=data.get('year')
    )
    db_session.add(item)
    db_session.commit()
    return jsonify({'id': item.id}), 201
