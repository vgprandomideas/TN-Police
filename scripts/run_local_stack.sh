#!/usr/bin/env bash
set -euo pipefail
python -m db.init_db
python scripts/seed_demo.py
uvicorn app.main:app --reload &
API_PID=$!
streamlit run frontend/frontend_app.py
kill $API_PID
