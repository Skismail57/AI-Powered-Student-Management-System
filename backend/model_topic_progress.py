# Topic Progress Model (for AI Recommendation)
from sqlalchemy import Column, Integer, ForeignKey, Float, String
from sqlalchemy.orm import relationship
from db import Base

class TopicProgress(Base):
    __tablename__ = 'topic_progress'
    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey('students.id'))
    subject_id = Column(Integer, ForeignKey('subjects.id'))
    topic_name = Column(String(100), nullable=False)
    progress_pct = Column(Float, default=0.0)
    last_reviewed = Column(String(20))  # ISO date string
    # Optionally, add relationships to Student and Subject
