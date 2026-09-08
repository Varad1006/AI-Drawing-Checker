from fastapi import APIRouter, Depends, UploadFile, File, BackgroundTasks
from sqlalchemy.orm import Session
from ..database import get_db, Base, engine
from ..models import db_models
from ..schemas import IssueSchema, EntitySchema, DrawingSchema
from ..parsers.dxf_parser import DXFParser
from ..parsers.pdf_parser import PDFParser
from ..extraction.entity_extractor import EntityExtractor
from ..rules.rule_engine import RuleEngine
from ..ai.gemini_client import AIService
import shutil
import os
import uuid

router = APIRouter()
Base.metadata.create_all(bind=engine)

UPLOAD_DIR = "../data/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

def process_drawing_task(drawing_id: int, file_path: str, ext: str, db: Session):
    try:
        # 1. Parse DXF or PDF
        if ext.lower() == 'pdf':
            parser = PDFParser(file_path)
        else:
            parser = DXFParser(file_path)
            
        raw_entities = parser.parse()
        
        # 2. Extract Entities
        extractor = EntityExtractor(raw_entities)
        eng_entities = extractor.extract()
        
        # 3. AI Analysis (replaces deterministic rule engine for PDF/Groq testing)
        ai_service = AIService()
        ai_results = ai_service.analyze_entities(eng_entities)
        
        # Store Extracted Entities
        for ent in eng_entities:
            db_ent = db_models.EngineeringEntity(
                drawing_id=drawing_id,
                entity_id=ent['entity_id'],
                type=ent['type'],
                tag=ent['tag'],
                pos_x=ent['pos_x'],
                pos_y=ent['pos_y'],
                source_entities=ent.get('source_entities', [])
            )
            db.add(db_ent)
            
        # Store Issues
        for iss in ai_results.get('issues', []):
            db_iss = db_models.Issue(
                drawing_id=drawing_id,
                issue_id=iss['issue_id'],
                rule_id=iss['rule_id'],
                category=iss['category'],
                severity=iss['severity'],
                title=iss['title'],
                description=iss['description'],
                recommendation=iss['recommendation'],
                confidence=iss['confidence'],
                pos_x=iss.get('pos_x'),
                pos_y=iss.get('pos_y'),
                related_entities=iss['related_entities']
            )
            db.add(db_iss)
            
        db.commit()
        
        # 4. Mark Processed
        drawing = db.query(db_models.Drawing).filter(db_models.Drawing.id == drawing_id).first()
        drawing.status = "processed"
        db.commit()

    except Exception as e:
        drawing = db.query(db_models.Drawing).filter(db_models.Drawing.id == drawing_id).first()
        drawing.status = "error"
        db.commit()

@router.post("/drawings/upload", response_model=DrawingSchema)
async def upload_drawing(background_tasks: BackgroundTasks, file: UploadFile = File(...), db: Session = Depends(get_db)):
    file_id = str(uuid.uuid4())
    ext = file.filename.split('.')[-1]
    safe_filename = f"{file_id}.{ext}"
    file_path = os.path.join(UPLOAD_DIR, safe_filename)
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    drawing = db_models.Drawing(filename=file.filename, status="uploaded", file_path=file_path)
    db.add(drawing)
    db.commit()
    db.refresh(drawing)
    
    background_tasks.add_task(process_drawing_task, drawing.id, file_path, ext, db)
    
    return drawing

@router.post("/drawings/demo", response_model=DrawingSchema)
async def generate_demo(db: Session = Depends(get_db)):
    drawing = db_models.Drawing(filename="DEMO_Water_Treatment_PID.pdf", status="processed", file_path="demo")
    db.add(drawing)
    db.commit()
    db.refresh(drawing)
    
    entities = [
        {"id": "ent_1", "type": "tank", "tag": "TK-101", "x": -200, "y": 100},
        {"id": "ent_2", "type": "pump", "tag": "P-101", "x": 0, "y": 100},
        {"id": "ent_3", "type": "pump", "tag": "P-101", "x": 0, "y": -100}, 
        {"id": "ent_4", "type": "valve", "tag": "V-101", "x": 200, "y": 100},
        {"id": "ent_5", "type": "filter", "tag": "FL-101", "x": 400, "y": 100},
        {"id": "ent_6", "type": "pipe_line", "tag": "L-001", "x": -100, "y": 100},
    ]
    
    for e in entities:
        db_ent = db_models.EngineeringEntity(
            drawing_id=drawing.id,
            entity_id=e["id"],
            type=e["type"],
            tag=e["tag"],
            pos_x=e["x"],
            pos_y=e["y"],
            source_entities=[]
        )
        db.add(db_ent)
        
    issues = [
        {
            "id": "ERR-DEMO-001", "rule": "GROQ-001", "cat": "Tagging", "sev": "HIGH",
            "title": "Duplicate equipment tag", "desc": "Equipment tag P-101 appears multiple times.",
            "rec": "AI will automatically resolve this by deleting one instance.", "conf": 0.99,
            "x": 0, "y": -100, "rels": ["P-101"]
        },
        {
            "id": "ERR-DEMO-002", "rule": "GROQ-002", "cat": "Connectivity", "sev": "MEDIUM",
            "title": "Unconnected Pipe", "desc": "Pipe L-001 does not connect.",
            "rec": "AI will auto-route the connection.", "conf": 0.95,
            "x": -100, "y": 100, "rels": ["L-001"]
        }
    ]
    
    for iss in issues:
        db_iss = db_models.Issue(
            drawing_id=drawing.id, issue_id=iss["id"], rule_id=iss["rule"], category=iss["cat"],
            severity=iss["sev"], title=iss["title"], description=iss["desc"], recommendation=iss["rec"],
            confidence=iss["conf"], pos_x=iss["x"], pos_y=iss["y"], related_entities=iss["rels"]
        )
        db.add(db_iss)
        
    db.commit()
    return drawing

@router.get("/drawings/{drawing_id}/issues", response_model=list[IssueSchema])
def get_drawing_issues(drawing_id: int, db: Session = Depends(get_db)):
    return db.query(db_models.Issue).filter(db_models.Issue.drawing_id == drawing_id).all()

@router.get("/drawings/{drawing_id}/entities", response_model=list[EntitySchema])
def get_drawing_entities(drawing_id: int, db: Session = Depends(get_db)):
    return db.query(db_models.EngineeringEntity).filter(db_models.EngineeringEntity.drawing_id == drawing_id).all()

@router.get("/drawings", response_model=list[DrawingSchema])
def get_drawings(db: Session = Depends(get_db)):
    return db.query(db_models.Drawing).all()
