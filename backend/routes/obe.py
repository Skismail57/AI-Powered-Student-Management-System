# OBE (Outcome-Based Education) API Endpoints
from flask import Blueprint, request, jsonify
from db import db_session
from model_obe import OBEOutcome

obe_bp = Blueprint('obe', __name__)

@obe_bp.route('/obe/<int:subject_id>', methods=['GET'])
def get_outcomes(subject_id):
    outcomes = OBEOutcome.query.filter_by(subject_id=subject_id).all()
    return jsonify([
        {'id': o.id, 'type': o.outcome_type, 'code': o.outcome_code, 'description': o.description} for o in outcomes
    ])

@obe_bp.route('/obe', methods=['POST'])
def add_outcome():
    data = request.json
    outcome = OBEOutcome(
        subject_id=data['subject_id'],
        outcome_type=data['outcome_type'],
        outcome_code=data['outcome_code'],
        description=data['description']
    )
    db_session.add(outcome)
    db_session.commit()
    return jsonify({'id': outcome.id}), 201
