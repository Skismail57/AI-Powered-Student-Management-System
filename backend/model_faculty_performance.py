# Faculty Performance Evaluation Models
from sqlalchemy import Column, Integer, Float, String, Text, ForeignKey
from sqlalchemy.orm import relationship
from db import Base

class FacultyFeedback(Base):
    __tablename__ = 'faculty_feedback'
    id = Column(Integer, primary_key=True)
    faculty_id = Column(Integer, ForeignKey('users.id'))
    student_id = Column(Integer, ForeignKey('students.id'))
    rating = Column(Float, nullable=False)  # 1-5 scale
    comments = Column(Text)
    created_at = Column(String(20))  # ISO date string
    faculty = relationship('User')
    student = relationship('Student')

class FacultyPerformance(Base):
    __tablename__ = 'faculty_performance'
    id = Column(Integer, primary_key=True)
    faculty_id = Column(Integer, ForeignKey('users.id'))
    avg_rating = Column(Float, default=0.0)
    feedback_count = Column(Integer, default=0)
    analytics_json = Column(Text, default='{}')
    faculty = relationship('User')
