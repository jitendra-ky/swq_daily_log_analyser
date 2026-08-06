# EOD Billing & Analytics Agent

This repository contains the SwasthiQ hiring assignment implementation with:

- `backend/`: Django REST API for deterministic reconciliation, analytics, and grounded narrative generation.
- `frontend/`: React (Vite) UI with three views: Reconciliation Dashboard, Analytics, and AI Narrative Summary.

## 1. Setup

### Prerequisites

- Python 3.12+
- Node.js 20+
- npm 10+
- A Groq API key (for narrative generation)

### Backend Setup

Run from the repository root:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -e .
python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

### Frontend Setup

Open a second terminal from the repository root:

```powershell
cd frontend
npm install
npm run dev
```

Frontend runs on `http://localhost:5173` by default and proxies `/api/*` to backend `http://localhost:8000` via Vite config.

## 2. Environment Variables and LLM Key Setup

Create `backend/.env` with:

```env
GROQ_API_KEY=your_groq_api_key_here
SECRET_KEY=replace_with_a_secure_value
DEBUG=True
CORS_ALLOW_ALL_ORIGINS=True
# Optional for explicit CORS origin allowlist
# CORS_ALLOWED_ORIGINS=http://localhost:5173
```

Notes:

- `GROQ_API_KEY` is required for the narrative layer LLM call.
- If the key is missing or the model response is invalid, deterministic report generation still works and the system falls back to a safe narrative.

## 3. Exact Run Commands

Backend:

```powershell
cd backend
.\.venv\Scripts\activate
python manage.py runserver 0.0.0.0:8000
```

Frontend:

```powershell
cd frontend
npm run dev
```

Backend tests:

```powershell
cd backend
.\.venv\Scripts\activate
pytest -q
```

Frontend production build:

```powershell
cd frontend
npm run build
```

## 4. API Contract Summary

Base path: `/api/v1`

- `POST /reports/generate/`
	- Input: JSON array of billing rows.
	- Output: `recon_report`, `analytics_report`, `narrative_result`, ingestion error list, and processing counts.
	- Validates malformed rows with actionable errors.

- `GET /reports/<clinic_id>/<date>/`
	- Retrieves previously generated report for a clinic/date pair.

Full request/response schema and examples are documented in:

- [docs/api_contracts.md](docs/api_contracts.md)

## 5. Grounding Guarantee and Fallback Behavior

The narrative layer is grounded by construction:

1. Deterministic services compute reconciliation and analytics first.
2. Narrative context is built as a strict whitelist of allowed placeholders.
3. LLM is instructed to return JSON with a template (`summaryTemplate`) and placeholders only.
4. Validation rejects:
	 - hardcoded digits outside placeholders,
	 - unknown placeholders,
	 - unresolved placeholders after substitution.
5. One retry is attempted with rejection reason feedback.
6. If retry fails (provider error, malformed JSON, or grounding rejection), the service returns deterministic fallback narrative text instead of crashing.

This ensures final displayed figures are sourced from deterministic report fields, not invented by the model.

## 6. Architecture Summary

High-level pipeline:

1. Ingestion + validation
2. Reconciliation computation
3. Analytics computation
4. Narrative template generation and grounding validation
5. Unified API response for frontend rendering

Detailed low-level design, data model, sequence and validation flows are documented in:

- [docs/low_leve_design.md](docs/low_leve_design.md)