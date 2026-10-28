.PHONY: setup dev api web test lint build eval
setup:
	cd backend && python3 -m venv .venv && . .venv/bin/activate && pip install -e ".[dev,gcp]"
	cd frontend && npm install
api:
	cd backend && . .venv/bin/activate && uvicorn shelfsense.api.main:app --reload --port 8000
web:
	cd frontend && npm run dev
test:
	cd backend && . .venv/bin/activate && pytest -q
lint:
	cd backend && . .venv/bin/activate && ruff check . && ruff format --check .
build:
	cd frontend && npm run build && cd .. && docker build -t shelfsense .
eval:
	cd backend && . .venv/bin/activate && python ../scripts/evaluate_forecast.py
