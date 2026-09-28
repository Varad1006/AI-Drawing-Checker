"""Runtime settings, read from the environment (and backend/.env if present)."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent
load_dotenv(BACKEND_DIR / ".env")

DATA_DIR = Path(os.getenv("DATA_DIR") or REPO_DIR / "data")
UPLOAD_DIR = DATA_DIR / "uploads"
DB_URL = os.getenv("DATABASE_URL") or f"sqlite:///{DATA_DIR / 'drawings.db'}"
SAMPLES_DIR = REPO_DIR / "samples"
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "25"))
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()]

GROQ_API_KEY = os.getenv("GROQ_API_KEY") or None
GROQ_MODEL = os.getenv("GROQ_MODEL") or "openai/gpt-oss-120b"
AI_REVIEW_ON_UPLOAD = os.getenv("AI_REVIEW_ON_UPLOAD", "true").lower() in ("1", "true", "yes")
