from pydantic import BaseModel
from typing import List, Optional, Any, Dict

class IssueSchema(BaseModel):
    id: int
    issue_id: str
    rule_id: str
    category: str
    severity: str
    status: str
    title: str
    description: str
    recommendation: Optional[str]
    confidence: float
    pos_x: Optional[float]
    pos_y: Optional[float]
    related_entities: List[str]

class EntitySchema(BaseModel):
    id: int
    entity_id: str
    type: str
    tag: Optional[str]
    pos_x: float
    pos_y: float

class DrawingSchema(BaseModel):
    id: int
    filename: str
    status: str
