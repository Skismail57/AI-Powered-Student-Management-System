# Classroom Engagement Analytics Model
from sqlalchemy import Column, Integer, Float, String, ForeignKey
from sqlalchemy.orm import relationship
from db import Base

class EngagementAnalytics(Base):
    __tablename__ = 'engagement_analytics'
    id = Column(Integer, primary_key=True)
    class_id = Column(Integer, nullable=False)
    faculty_id = Column(Integer, ForeignKey('users.id'))
    date = Column(String(20), nullable=False)  # ISO date string
    quiz_participation = Column(Float, default=0.0)  # %
    attendance_interaction = Column(Float, default=0.0)  # %
    notes = Column(String(300), default='')
    faculty = relationship('User')
