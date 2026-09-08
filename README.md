# AI-powered Lead Engineering Drawing Checker

A Proof of Concept (POC) for automated QA of P&ID engineering drawings.

## Architecture

The system uses a layered architecture:
1.  **Frontend**: React (Vite) + Tailwind CSS, providing an engineering dashboard for drawing upload and issue tracking.
2.  **Backend**: FastAPI, handling file uploads, API endpoints, and coordinating the analysis pipeline.
3.  **Parsers**: Extracts raw CAD entities using `ezdxf` (currently supports DXF, extensible to PDF/DWG).
4.  **Extraction & Rules**: Interprets CAD primitives as engineering entities (Tanks, Pumps, Valves) and runs a deterministic rule engine (Duplicate tags, Missing connections) before falling back to simulated AI analysis.
5.  **Database**: SQLite (via SQLAlchemy) storing drawings, extracted entities, and identified issues.

## Installation

### Prerequisites
- Python 3.10+
- Node.js 18+

### Setup

```bash
# Clone the repository
cd drawing-checker-poc

# Backend Setup
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
# (For the POC, dependencies are installed directly if following the setup script)

# Frontend Setup
cd ../frontend
npm install
```

## Running the Application

You will need two terminal windows.

### Terminal 1: Backend
```bash
cd drawing-checker-poc/backend
source venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Terminal 2: Frontend
```bash
cd drawing-checker-poc/frontend
npm run dev
```

Then, open your browser to the URL provided by Vite (usually `http://localhost:5173`).

## Environment Variables
- `AI_API_KEY`: (Optional) Used by the AI service abstraction for advanced reasoning. The application continues functioning deterministically without it.

## How to use

1.  **Upload DXF**: Click the upload area and select a DXF file containing basic shapes and text (e.g., P-101, TK-101).
2.  **Demo Inspection**: Click "Run Demo Inspection (Live Data)" to generate a mock water treatment layout with intentionally injected engineering flaws.

## Supported Formats
- **DXF**: Full extraction of texts, lines, blocks (POC).
- **PDF**: Supported via abstraction, currently defaults to basic extraction.
- **DWG**: Future implementation planned using ODA pipelines.

## Current Limitations
- Basic geometry visualizer (renders extracted points directly instead of the full vector image).
- Simplified entity extraction using heuristic text/tag patterns.
- AI module is currently returning simulated insights for the POC.

## Adding a New Engineering Rule

1. Open `backend/app/rules/rule_engine.py`
2. Add a new method, e.g., `rule_missing_valve(self):`
3. Traverse `self.entities` and append dictionaries to `self.issues`.
4. Call your new method inside `run_all()`.
