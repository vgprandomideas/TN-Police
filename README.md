# TN Police Intelligence Platform - Final Bundle

This is the final consolidated code bundle for the Tamil Nadu police-intelligence MVP/prototype.

It combines the major modules built across earlier iterations into one package and adds deployment infrastructure so you can run it locally or in containers without stitching files together manually.

## What is in the bundle

### Product layers
- state command dashboard
- district and station views
- incidents, complaints, cases, comments, assignments, and timelines
- entity graph, watchlists, suspect dossiers, graph insights, and fusion workbench
- evidence registry, evidence-integrity log, and prosecution workflow stubs
- routing rules, SLA tracking, officer workload, patrol coverage, hotspot forecasting, and briefings
- task orchestration, export jobs, notifications, and war-room snapshots

### Infrastructure layers
- FastAPI backend
- Streamlit frontend
- SQLAlchemy models
- PostgreSQL-ready configuration with SQLite fallback
- background worker process
- Dockerfiles
- Docker Compose stack
- Nginx reverse proxy
- `.env.example`
- Makefile and bootstrap scripts

## Data honesty
This package does **not** fake privileged access to CCTNS, FIR, CCTV, or other restricted police systems. Publicly available metrics are seeded where available. Operational feeds and restricted-source workflows remain stubbed or synthetic for MVP purposes.

## Quick start (local)

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m db.init_db
python scripts/seed_demo.py
uvicorn app.main:app --reload
streamlit run frontend/frontend_app.py
```

Worker in a second terminal:

```bash
python scripts/run_worker.py
```

## Quick start (Docker)

```bash
cp .env.example .env
docker compose up --build
```

- Streamlit UI: `http://localhost:8501`
- API: `http://localhost:8000`
- Reverse proxied entry: `http://localhost:8080`

## Cloud deployment

This repo is a two-service app:
- Streamlit frontend: `frontend/frontend_app.py`
- FastAPI backend: `app/main.py`

If you deploy only the Streamlit app, it will not work because the UI calls the API for login, dashboard data, heatmaps, dossier data, and admin actions.

### Streamlit Community Cloud

Use these settings:
- Repository: `vgprandomideas/TN-Police`
- Branch: `main`
- Main file path: `frontend/frontend_app.py`

Add this secret in the Streamlit app settings:

```toml
API_URL = "https://your-backend-url"
```

The Streamlit app now reads `API_URL` from either an environment variable or Streamlit secrets.

### Render backend

This repo includes `render.yaml` for the API service. You can deploy it as a Blueprint or create a web service manually with:
- Build Command: `pip install -r requirements.txt`
- Start Command: `python -m db.init_db && python scripts/seed_demo.py && uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Health Check Path: `/health`

After deploy, copy the Render service URL and set it as `API_URL` in Streamlit.

### Railway backend

This repo includes `railway.toml` for the API service. If you configure it manually, use:
- Build Command: `pip install -r requirements.txt`
- Start Command: `python -m db.init_db && python scripts/seed_demo.py && uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Health Check Path: `/health`

### Why the hosted site can stay stuck loading

Common causes:
- The Streamlit app is deployed without the FastAPI backend.
- `API_URL` is not set, so Streamlit falls back to `http://localhost:8000`.
- The backend host is sleeping or cold-starting, so the frontend waits for the API to wake up.
- Free-tier deployments with SQLite are demo-friendly, but the database is recreated on new instances or redeploys.

## Demo credentials
- `admin_tn / admin123`
- `cyber_analyst / cyber123`
- `district_sp / district123`
- `viewer / viewer123`

## Project structure

```text
app/                 FastAPI app and schemas
adapters/            sanctioned connector registry / adapter stubs
db/                  database engine, models, bootstrap
services/            auth, alerts, routing, anomaly, SLA, permissions
scripts/             seeding and worker scripts
frontend/            Streamlit console
data/                seeded public metrics and demo datasets
infra/               Docker and Nginx assets
docs/                architecture and source notes
tests/               smoke tests
```

## Production-minded notes
- For a serious deployment, switch fully to PostgreSQL.
- Replace demo auth secrets with strong secrets.
- Put the API and frontend behind TLS.
- Add sanctioned source adapters only after legal and operational approvals.
- Add proper object storage before enabling real evidence uploads.

## Caveat
I was able to package and syntax-check the code, but I did not fully run the whole multi-service stack inside this environment. You should run it locally or on your server and validate the full path.
