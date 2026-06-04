# Faculty Research Model
from sqlalchemy import Column, Integer, String, Text, ForeignKey
from sqlalchemy.orm import relationship
from db import Base

class FacultyResearch(Base):
    __tablename__ = 'faculty_research'
    id = Column(Integer, primary_key=True)
    faculty_id = Column(Integer, ForeignKey('users.id'))
    title = Column(String(200), nullable=False)
    research_type = Column(String(20), nullable=False)  # 'paper', 'publication', 'patent'
    description = Column(Text)
    url = Column(String(300))
    year = Column(Integer)
    faculty = relationship('User')
