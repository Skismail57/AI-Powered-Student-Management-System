# Curriculum Management System API Endpoints
from flask import Blueprint, request, jsonify
from db import db_session
from model_curriculum import Curriculum, Semester, Subject

curriculum_bp = Blueprint('curriculum', __name__)

@curriculum_bp.route('/curriculums', methods=['GET'])
def get_curriculums():
    curriculums = Curriculum.query.all()
    return jsonify([
        {'id': c.id, 'name': c.name, 'description': c.description} for c in curriculums
    ])

@curriculum_bp.route('/curriculums', methods=['POST'])
def add_curriculum():
    data = request.json
    curriculum = Curriculum(name=data['name'], description=data.get('description', ''))
    db_session.add(curriculum)
    db_session.commit()
    return jsonify({'id': curriculum.id}), 201

@curriculum_bp.route('/curriculums/<int:curriculum_id>/semesters', methods=['POST'])
def add_semester(curriculum_id):
    data = request.json
    semester = Semester(curriculum_id=curriculum_id, number=data['number'])
    db_session.add(semester)
    db_session.commit()
    return jsonify({'id': semester.id}), 201

@curriculum_bp.route('/semesters/<int:semester_id>/subjects', methods=['POST'])
def add_subject(semester_id):
    data = request.json
    subject = Subject(
        semester_id=semester_id,
        code=data['code'],
        name=data['name'],
        credits=data['credits'],
        syllabus=data.get('syllabus', '')
    )
    db_session.add(subject)
    db_session.commit()
    return jsonify({'id': subject.id}), 201

@curriculum_bp.route('/semesters/<int:semester_id>/subjects', methods=['GET'])
def get_subjects(semester_id):
    subjects = Subject.query.filter_by(semester_id=semester_id).all()
    return jsonify([
        {'id': s.id, 'code': s.code, 'name': s.name, 'credits': s.credits, 'syllabus': s.syllabus} for s in subjects
    ])
