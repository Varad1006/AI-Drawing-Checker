# Lead Checker — common tasks.  `make setup` once, then `make dev`.
API_PORT ?= 8000
WEB_PORT ?= 5173
PY := backend/venv/bin/python

.PHONY: setup dev backend frontend test lint samples build

setup:
	python3 -m venv backend/venv
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -q -r backend/requirements.txt
	npm --prefix frontend install
	@test -f backend/.env || cp backend/.env.example backend/.env
	@echo "Ready. Add GROQ_API_KEY to backend/.env (optional), then run: make dev"

backend:
	cd backend && ./venv/bin/uvicorn app.main:app --reload --port $(API_PORT)

frontend:
	cd frontend && API_URL=http://localhost:$(API_PORT) npx vite --port $(WEB_PORT)

dev:
	@echo "API → http://localhost:$(API_PORT)/docs   UI → http://localhost:$(WEB_PORT)"
	@trap 'kill 0' INT TERM; $(MAKE) --no-print-directory backend & $(MAKE) --no-print-directory frontend & wait

test:
	cd backend && ./venv/bin/python -m pytest -q
	cd frontend && npx tsc -b && npx oxlint

samples:
	cd backend && ./venv/bin/python -m scripts.generate_samples

build:
	npm --prefix frontend run build
