# Curriculum Management System Models

from sqlalchemy import Column, Integer, String, ForeignKey, Text
from sqlalchemy.orm import relationship
from db import Base

class Curriculum(Base):
    __tablename__ = 'curriculums'
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    semesters = relationship('Semester', back_populates='curriculum')

class Semester(Base):
    __tablename__ = 'semesters'
    id = Column(Integer, primary_key=True)
    curriculum_id = Column(Integer, ForeignKey('curriculums.id'))
    number = Column(Integer, nullable=False)
    curriculum = relationship('Curriculum', back_populates='semesters')
    subjects = relationship('Subject', back_populates='semester')

class Subject(Base):
    __tablename__ = 'subjects'
    id = Column(Integer, primary_key=True)
    semester_id = Column(Integer, ForeignKey('semesters.id'))
    code = Column(String(20), nullable=False)
    name = Column(String(100), nullable=False)
    credits = Column(Integer, nullable=False)
    syllabus = Column(Text)
    semester = relationship('Semester', back_populates='subjects')
