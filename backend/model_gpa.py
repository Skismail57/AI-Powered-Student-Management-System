# Credit & GPA Management Models
from sqlalchemy import Column, Integer, Float, ForeignKey
from sqlalchemy.orm import relationship
from db import Base

class StudentGPA(Base):
    __tablename__ = 'student_gpa'
    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey('students.id'))
    semester = Column(Integer, nullable=False)
    gpa = Column(Float, nullable=False)
    credits_earned = Column(Integer, nullable=False)
    backlogs = Column(Integer, default=0)
    # Optionally, add relationship to Student if needed
