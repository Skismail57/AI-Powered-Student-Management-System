# Timetable Models
from sqlalchemy import Column, Integer, String, ForeignKey, Time
from sqlalchemy.orm import relationship
from db import Base

class Timetable(Base):
    __tablename__ = 'timetables'
    id = Column(Integer, primary_key=True)
    dept_id = Column(Integer, nullable=False)
    semester = Column(Integer, nullable=False)
    day_of_week = Column(String(10), nullable=False)
    start_time = Column(String(5), nullable=False)  # e.g., '09:00'
    end_time = Column(String(5), nullable=False)    # e.g., '10:30'
    subject_id = Column(Integer, ForeignKey('subjects.id'))
    room_number = Column(String(20), nullable=False)
    subject = relationship('Subject')
