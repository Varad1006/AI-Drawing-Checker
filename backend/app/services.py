"""Drawing lifecycle: import, revisions, issue assembly, fixes and review decisions."""
from __future__ import annotations

import logging
from collections import OrderedDict

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .core import topology
from .core.document import find_entity, find_line
from .core.ops import apply_ops, OpError
from .core.symbols import TYPES
from .models import AIRun, ChatMessage, Drawing, IssueReview, Revision
from .parsers.dxf_parser import parse_dxf
from .parsers.pdf_parser import parse_pdf
from .rules.engine import SEVERITY_ORDER, run_rules

logger = logging.getLogger(__name__)

_RULE_CACHE: "OrderedDict[int, list[dict]]" = OrderedDict()


def rules_for(rev: Revision) -> list[dict]:
    """Rule findings for a revision. Revisions are immutable, so results are cached by id."""
    if rev.id in _RULE_CACHE:
        _RULE_CACHE.move_to_end(rev.id)
        return _RULE_CACHE[rev.id]
    findings = run_rules(rev.document)
    _RULE_CACHE[rev.id] = findings
    if len(_RULE_CACHE) > 256:
        _RULE_CACHE.popitem(last=False)
    return findings


# ---------------------------------------------------------------------------------------------------
# import / revisions
# ---------------------------------------------------------------------------------------------------

def parse_file(path: str, fmt: str) -> dict:
    return parse_pdf(path) if fmt == "pdf" else parse_dxf(path)


def ingest(db: Session, path: str, filename: str, fmt: str) -> Drawing:
    doc = parse_file(path, fmt)
    drawing = Drawing(filename=filename, format=fmt, file_path=path, head_rev=1,
                      ai_status="idle")
    drawing.revisions.append(Revision(rev_no=1, document=doc, author="import",
                                      summary=f"Imported {fmt.upper()} ({len(doc['entities'])} components, "
                                              f"{len(doc['lines'])} lines)"))
    db.add(drawing)
    db.commit()
    return drawing


def head(db: Session, drawing: Drawing) -> Revision:
    return db.scalar(select(Revision).where(Revision.drawing_id == drawing.id, Revision.rev_no == drawing.head_rev))


def max_rev(drawing: Drawing) -> int:
    return max((r.rev_no for r in drawing.revisions), default=1)


def commit_edit(db: Session, drawing: Drawing, doc: dict, ops: list[dict], author: str, summary: str,
                changed: set[str]) -> Revision:
    for r in list(drawing.revisions):  # editing after an undo discards the redo branch
        if r.rev_no > drawing.head_rev:
            _RULE_CACHE.pop(r.id, None)
            drawing.revisions.remove(r)
    db.flush()
    rev = Revision(rev_no=drawing.head_rev + 1, document=doc, author=author, summary=summary[:500], ops=ops,
                   changed=sorted(changed))
    drawing.revisions.append(rev)
    drawing.head_rev = rev.rev_no
    db.commit()
    return rev


def apply_edit(db: Session, drawing: Drawing, ops: list[dict], author: str, summary: str | None = None):
    rev = head(db, drawing)
    res = apply_ops(rev.document, ops)
    new = commit_edit(db, drawing, res.doc, ops, author, summary or "; ".join(res.messages), res.changed)
    return new, res.messages


def set_head(db: Session, drawing: Drawing, rev_no: int) -> None:
    if not 1 <= rev_no <= max_rev(drawing):
        raise OpError(f"revision {rev_no} does not exist")
    drawing.head_rev = rev_no
    db.commit()


# ---------------------------------------------------------------------------------------------------
# issues
# ---------------------------------------------------------------------------------------------------

def _ai_findings(drawing: Drawing, doc: dict, run: AIRun | None) -> list[dict]:
    if not run:
        return []
    out = []
    for f in run.findings:
        if all(find_entity(doc, e) for e in f.get("entities", [])) and all(find_line(doc, ln) for ln in f.get("lines", [])):
            out.append({**f, "ai_rev": run.rev_no})
    return out


def current_issues(db: Session, drawing: Drawing, rev: Revision | None = None) -> tuple[list[dict], dict]:
    rev = rev or head(db, drawing)
    doc = rev.document
    runs = drawing.ai_runs
    live = [dict(f) for f in rules_for(rev)] + _ai_findings(drawing, doc, runs[-1] if runs else None)
    live_keys = {f["key"] for f in live}

    first = next((r for r in drawing.revisions if r.rev_no == 1), None)
    baseline = [dict(f) for f in rules_for(first)] if first else []
    if runs:
        baseline += [dict(f) for f in runs[0].findings]
    reviews = {r.key: r for r in drawing.reviews}

    issues = []
    for f in live:
        r = reviews.get(f["key"])
        f["status"] = r.status if r else "OPEN"
        f["comment"] = r.comment if r else ""
        issues.append(f)
    seen = set()
    for f in baseline:
        if f["key"] in live_keys or f["key"] in seen:
            continue
        seen.add(f["key"])
        r = reviews.get(f["key"])
        f.update(status="FIXED", comment=r.comment if r else "", fix=None)
        issues.append(f)

    issues.sort(key=lambda f: (f["status"] == "FIXED", SEVERITY_ORDER.get(f["severity"], 9), f["rule_id"], f["key"]))
    active = [f for f in issues if f["status"] != "FIXED"]
    stats = {
        "open": sum(f["status"] == "OPEN" for f in active),
        "accepted": sum(f["status"] == "ACCEPTED" for f in active),
        "rejected": sum(f["status"] == "REJECTED" for f in active),
        "fixed": sum(f["status"] == "FIXED" for f in issues),
        "fixable": sum(1 for f in active if f.get("fix") and f["status"] != "REJECTED"),
        "by_severity": {s: sum(1 for f in active if f["severity"] == s and f["status"] != "REJECTED")
                        for s in SEVERITY_ORDER},
    }
    return issues, stats


def set_review(db: Session, drawing: Drawing, key: str, status: str, comment: str) -> None:
    review = db.scalar(select(IssueReview).where(IssueReview.drawing_id == drawing.id, IssueReview.key == key))
    if review is None:
        review = IssueReview(drawing_id=drawing.id, key=key, status=status, comment=comment)
        db.add(review)
    else:
        review.status, review.comment = status, comment
    db.commit()
    db.refresh(drawing)


def fix_issue(db: Session, drawing: Drawing, key: str, author: str = "auto-fix"):
    issues, _ = current_issues(db, drawing)
    issue = next((f for f in issues if f["key"] == key), None)
    if issue is None:
        raise OpError("that finding no longer exists on the current revision")
    if not issue.get("fix"):
        raise OpError("this finding has no automatic fix — resolve it by editing or via the assistant")
    return apply_edit(db, drawing, issue["fix"]["ops"], author, f"Fix {issue['rule_id']}: {issue['fix']['label']}")


def autofix_doc(doc: dict, skip_keys: set[str] | None = None, max_rounds: int = 30) -> tuple[dict, list[dict], list[str], set[str]]:
    """Apply every mechanical fix, re-checking after each one (fixes can create or clear findings)."""
    skip_keys = set(skip_keys or ())
    ops_done, messages, changed, tried = [], [], set(), set()
    for _ in range(max_rounds):
        candidate = next((f for f in run_rules(doc) if f.get("fix") and f["key"] not in skip_keys
                          and f["key"] not in tried), None)
        if candidate is None:
            break
        tried.add(candidate["key"])
        try:
            res = apply_ops(doc, candidate["fix"]["ops"])
        except OpError as exc:
            messages.append(f"Skipped {candidate['rule_id']} ({exc})")
            continue
        doc = res.doc
        ops_done += candidate["fix"]["ops"]
        messages += res.messages
        changed |= res.changed
    return doc, ops_done, messages, changed


def autofix(db: Session, drawing: Drawing, author: str = "auto-fix"):
    rejected = {r.key for r in drawing.reviews if r.status == "REJECTED"}
    rev = head(db, drawing)
    doc, ops, messages, changed = autofix_doc(rev.document, rejected)
    if not ops:
        return None, messages
    new = commit_edit(db, drawing, doc, ops, author, f"Auto-fix: {len(ops)} operation(s)", changed)
    return new, messages


# ---------------------------------------------------------------------------------------------------
# serialisation
# ---------------------------------------------------------------------------------------------------

def drawing_summary(db: Session, drawing: Drawing) -> dict:
    _, stats = current_issues(db, drawing)
    return {
        "id": drawing.id, "filename": drawing.filename, "format": drawing.format,
        "created_at": drawing.created_at.isoformat(), "updated_at": drawing.updated_at.isoformat(),
        "head_rev": drawing.head_rev, "max_rev": max_rev(drawing), "ai_status": drawing.ai_status,
        "ai_error": drawing.ai_error, "stats": stats,
    }


def drawing_detail(db: Session, drawing: Drawing) -> dict:
    rev = head(db, drawing)
    issues, stats = current_issues(db, drawing, rev)
    topo = topology.build(rev.document)
    return {
        "drawing": {**drawing_summary(db, drawing), "stats": stats},
        "document": rev.document,
        "topology": topology.summary(topo),
        "issues": issues,
        "revisions": [{"rev_no": r.rev_no, "author": r.author, "summary": r.summary,
                       "created_at": r.created_at.isoformat(), "changed": r.changed} for r in drawing.revisions],
        "changed": rev.changed or [],
        "ai": ai_info(),
    }


def ai_info() -> dict:
    from .ai import groq_client
    return {"enabled": groq_client.enabled(), "provider": "groq", "model": config.GROQ_MODEL if groq_client.enabled() else None}


def component_types() -> list[dict]:
    return [{"type": t, "name": m["name"], "category": m["category"], "prefixes": m["prefixes"]} for t, m in TYPES.items()]


def chat_history(drawing: Drawing) -> list[dict]:
    return [{"id": m.id, "role": m.role, "content": m.content, "actions": m.actions, "rev_no": m.rev_no,
             "engine": m.engine, "created_at": m.created_at.isoformat()} for m in drawing.messages]


def add_message(db: Session, drawing: Drawing, role: str, content: str, actions=None, rev_no=None, engine="") -> None:
    db.add(ChatMessage(drawing_id=drawing.id, role=role, content=content, actions=actions or [], rev_no=rev_no,
                       engine=engine))
    db.commit()
    db.refresh(drawing)
