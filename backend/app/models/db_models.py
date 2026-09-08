from sqlalchemy import Column, Integer, String, Float, ForeignKey, JSON
from sqlalchemy.orm import relationship
from ..database import Base

class Drawing(Base):
    __tablename__ = "drawings"
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, index=True)
    status = Column(String)  # uploaded, processed, error
    file_path = Column(String)
    
class EngineeringEntity(Base):
    __tablename__ = "engineering_entities"
    id = Column(Integer, primary_key=True, index=True)
    drawing_id = Column(Integer, ForeignKey("drawings.id"))
    entity_id = Column(String)
    type = Column(String)
    tag = Column(String)
    pos_x = Column(Float)
    pos_y = Column(Float)
    source_entities = Column(JSON) # Store related CAD entities

class Connection(Base):
    __tablename__ = "connections"
    id = Column(Integer, primary_key=True, index=True)
    drawing_id = Column(Integer, ForeignKey("drawings.id"))
    source_tag = Column(String)
    target_tag = Column(String)
    connection_type = Column(String)
    
class Issue(Base):
    __tablename__ = "issues"
    id = Column(Integer, primary_key=True, index=True)
    drawing_id = Column(Integer, ForeignKey("drawings.id"))
    issue_id = Column(String)
    rule_id = Column(String)
    category = Column(String)
    severity = Column(String)
    status = Column(String, default="OPEN")
    title = Column(String)
    description = Column(String)
    recommendation = Column(String)
    confidence = Column(Float)
    pos_x = Column(Float, nullable=True)
    pos_y = Column(Float, nullable=True)
    related_entities = Column(JSON)
