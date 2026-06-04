# OBE (Outcome-Based Education) Models
from sqlalchemy import Column, Integer, String, ForeignKey, Text
from sqlalchemy.orm import relationship
from db import Base

class OBEOutcome(Base):
    __tablename__ = 'obe_outcomes'
    id = Column(Integer, primary_key=True)
    subject_id = Column(Integer, ForeignKey('subjects.id'))
    outcome_type = Column(String(10), nullable=False)  # 'CO' or 'PO'
    outcome_code = Column(String(20), nullable=False)  # e.g., 'CO1', 'PO2'
    description = Column(Text, nullable=False)
    subject = relationship('Subject')
