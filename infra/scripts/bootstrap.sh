#!/usr/bin/env bash
set -euo pipefail
python -m db.init_db
python scripts/seed_demo.py
python scripts/run_worker.py
