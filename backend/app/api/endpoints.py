from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config, services
from ..ai import fallback, groq_client
from ..core.ops import OpError
from ..database import SessionLocal, get_db
from ..exporters.dxf_writer import dxf_bytes
from ..exporters.pdf_report import report_pdf
from ..models import AIRun, Drawing
from ..parsers.dxf_parser import ParseError
from ..rules.engine import catalog

logger = logging.getLogger(__name__)
router = APIRouter()
ALLOWED = {"dxf", "pdf"}
DEMO_FILE = "water_treatment_pid.dxf"


class EditRequest(BaseModel):
    ops: list[dict] = Field(..., min_length=1)
    summary: str | None = None


class HeadRequest(BaseModel):
    rev_no: int


class ReviewRequest(BaseModel):
    status: str = Field(..., pattern="^(OPEN|ACCEPTED|REJECTED)$")
    comment: str = ""


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)


def _drawing(db: Session, drawing_id: int) -> Drawing:
    drawing = db.get(Drawing, drawing_id)
    if drawing is None:
        raise HTTPException(404, "Drawing not found")
    return drawing


def _run_ai_review(drawing_id: int) -> None:
    """Background task: AI review of the current revision (own DB session)."""
    db = SessionLocal()
    try:
        drawing = db.get(Drawing, drawing_id)
        if drawing is None:
            return
        rev = services.head(db, drawing)
        try:
            findings = groq_client.review(rev.document, services.rules_for(rev))
            db.add(AIRun(drawing_id=drawing.id, rev_no=rev.rev_no, model=config.GROQ_MODEL, findings=findings))
            drawing.ai_status, drawing.ai_error = "done", None
        except Exception as exc:  # surfaced to the UI via ai_status / ai_error
            logger.warning("AI review failed: %s", exc)
            drawing.ai_status, drawing.ai_error = "error", str(exc)
        db.commit()
    finally:
        db.close()


def _start_ai_review(db: Session, drawing: Drawing, background: BackgroundTasks) -> None:
    drawing.ai_status, drawing.ai_error = "running", None
    db.commit()
    background.add_task(_run_ai_review, drawing.id)


# ---------------------------------------------------------------------------------------------------

@router.get("/health")
def health():
    return {"status": "ok", "ai": services.ai_info()}


@router.get("/rules")
def rules():
    return {"rules": catalog(), "types": services.component_types()}


@router.get("/drawings")
def list_drawings(db: Session = Depends(get_db)):
    drawings = db.scalars(select(Drawing).order_by(Drawing.id.desc())).all()
    return [services.drawing_summary(db, d) for d in drawings]


def _store_and_ingest(db: Session, src, filename: str, background: BackgroundTasks) -> dict:
    ext = Path(filename).suffix.lower().lstrip(".")
    if ext not in ALLOWED:
        raise HTTPException(415, "Only .dxf and .pdf drawings are supported")
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    dest = config.UPLOAD_DIR / f"{uuid.uuid4()}.{ext}"
    limit = config.MAX_UPLOAD_MB * 1024 * 1024
    size = 0
    with open(dest, "wb") as out:
        while chunk := src.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                out.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(413, f"File is larger than {config.MAX_UPLOAD_MB} MB")
            out.write(chunk)
    try:
        drawing = services.ingest(db, str(dest), filename, ext)
    except ParseError as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(422, str(exc)) from exc
    if groq_client.enabled() and config.AI_REVIEW_ON_UPLOAD:
        _start_ai_review(db, drawing, background)
    return services.drawing_summary(db, drawing)


@router.post("/drawings/upload")
def upload(background: BackgroundTasks, file: UploadFile = File(...), db: Session = Depends(get_db)):
    return _store_and_ingest(db, file.file, file.filename or "drawing", background)


@router.post("/drawings/demo")
def demo(background: BackgroundTasks, db: Session = Depends(get_db)):
    sample = config.SAMPLES_DIR / DEMO_FILE
    if not sample.exists():
        raise HTTPException(500, "Sample drawing missing — run `python -m scripts.generate_samples` in backend/")
    with open(sample, "rb") as src:
        return _store_and_ingest(db, src, f"DEMO_{DEMO_FILE}", background)


@router.get("/drawings/{drawing_id}")
def get_drawing(drawing_id: int, db: Session = Depends(get_db)):
    return services.drawing_detail(db, _drawing(db, drawing_id))


@router.delete("/drawings/{drawing_id}", status_code=204)
def delete_drawing(drawing_id: int, db: Session = Depends(get_db)):
    drawing = _drawing(db, drawing_id)
    path = Path(drawing.file_path)
    db.delete(drawing)
    db.commit()
    if path.is_file() and config.UPLOAD_DIR in path.parents:
        path.unlink(missing_ok=True)
    return Response(status_code=204)


@router.post("/drawings/{drawing_id}/edits")
def edit(drawing_id: int, body: EditRequest, db: Session = Depends(get_db)):
    drawing = _drawing(db, drawing_id)
    try:
        _, messages = services.apply_edit(db, drawing, body.ops, "user", body.summary)
    except OpError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {**services.drawing_detail(db, drawing), "messages": messages}


@router.post("/drawings/{drawing_id}/head")
def set_head(drawing_id: int, body: HeadRequest, db: Session = Depends(get_db)):
    drawing = _drawing(db, drawing_id)
    try:
        services.set_head(db, drawing, body.rev_no)
    except OpError as exc:
        raise HTTPException(400, str(exc)) from exc
    return services.drawing_detail(db, drawing)


@router.post("/drawings/{drawing_id}/issues/{key}/fix")
def fix_issue(drawing_id: int, key: str, db: Session = Depends(get_db)):
    drawing = _drawing(db, drawing_id)
    try:
        _, messages = services.fix_issue(db, drawing, key)
    except OpError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {**services.drawing_detail(db, drawing), "messages": messages}


@router.put("/drawings/{drawing_id}/issues/{key}/review")
def review_issue(drawing_id: int, key: str, body: ReviewRequest, db: Session = Depends(get_db)):
    drawing = _drawing(db, drawing_id)
    services.set_review(db, drawing, key, body.status, body.comment.strip())
    return services.drawing_detail(db, drawing)


@router.post("/drawings/{drawing_id}/autofix")
def autofix(drawing_id: int, db: Session = Depends(get_db)):
    drawing = _drawing(db, drawing_id)
    _, messages = services.autofix(db, drawing)
    return {**services.drawing_detail(db, drawing), "messages": messages}


@router.post("/drawings/{drawing_id}/ai-review", status_code=202)
def ai_review(drawing_id: int, background: BackgroundTasks, db: Session = Depends(get_db)):
    drawing = _drawing(db, drawing_id)
    if not groq_client.enabled():
        raise HTTPException(409, "AI review needs GROQ_API_KEY to be set on the server")
    if drawing.ai_status == "running":
        raise HTTPException(409, "An AI review is already running")
    _start_ai_review(db, drawing, background)
    return {"ai_status": "running"}


@router.get("/drawings/{drawing_id}/chat")
def get_chat(drawing_id: int, db: Session = Depends(get_db)):
    return services.chat_history(_drawing(db, drawing_id))


@router.post("/drawings/{drawing_id}/chat")
def chat(drawing_id: int, body: ChatRequest, db: Session = Depends(get_db)):
    drawing = _drawing(db, drawing_id)
    rev = services.head(db, drawing)
    history = services.chat_history(drawing)
    services.add_message(db, drawing, "user", body.message)
    try:
        if groq_client.enabled():
            result = groq_client.chat(rev.document, history, body.message)
        else:
            result = fallback.handle(rev.document, body.message)
    except groq_client.AIError as exc:
        services.add_message(db, drawing, "assistant", f"⚠️ {exc}", engine=f"groq:{config.GROQ_MODEL}")
        return {**services.drawing_detail(db, drawing), "chat": services.chat_history(drawing)}
    wb = result.workbench
    rev_no = None
    if wb.ops:
        new = services.commit_edit(db, drawing, wb.doc, wb.ops, "ai" if result.engine.startswith("groq") else "assistant",
                                   f"Assistant: {body.message}", wb.changed)
        rev_no = new.rev_no
    services.add_message(db, drawing, "assistant", result.reply, actions=wb.messages, rev_no=rev_no, engine=result.engine)
    return {**services.drawing_detail(db, drawing), "chat": services.chat_history(drawing)}


@router.get("/drawings/{drawing_id}/export/{kind}")
def export(drawing_id: int, kind: str, db: Session = Depends(get_db)):
    drawing = _drawing(db, drawing_id)
    rev = services.head(db, drawing)
    stem = Path(drawing.filename).stem
    if kind == "dxf":
        return _download(dxf_bytes(rev.document), f"{stem}_rev{rev.rev_no}.dxf", "application/dxf")
    issues, stats = services.current_issues(db, drawing, rev)
    active = [i for i in issues if i["status"] != "FIXED"]
    if kind == "markup-dxf":
        return _download(dxf_bytes(rev.document, active), f"{stem}_rev{rev.rev_no}_markup.dxf", "application/dxf")
    if kind == "report-pdf":
        meta = {"filename": drawing.filename, "revision": rev.rev_no, "revisions": services.max_rev(drawing),
                "stats": stats, "ai_model": config.GROQ_MODEL if drawing.ai_runs else None}
        return _download(report_pdf(rev.document, active + [i for i in issues if i["status"] == "FIXED"], meta),
                         f"{stem}_rev{rev.rev_no}_check_report.pdf", "application/pdf")
    if kind == "original":
        path = Path(drawing.file_path)
        if not path.is_file():
            raise HTTPException(404, "Original file is no longer available")
        return _download(path.read_bytes(), drawing.filename, "application/octet-stream")
    raise HTTPException(404, "Unknown export — use dxf, markup-dxf, report-pdf or original")


def _download(data: bytes, filename: str, media: str) -> Response:
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in filename)
    return Response(content=data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{safe}"'})
