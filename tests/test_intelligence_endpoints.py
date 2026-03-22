import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.main import case_dossier, graph_insights, operations_command_center
from db.database import SessionLocal
from db.models import User


def _admin_user(db):
    return db.query(User).filter(User.username == "admin_tn").first()


def test_graph_insights_returns_serializable_rows():
    db = SessionLocal()
    try:
        rows = graph_insights(user=_admin_user(db), db=db)
        assert isinstance(rows, list)
        if rows:
            assert "headline" in rows[0]
            assert "entity_id" in rows[0]
    finally:
        db.close()


def test_operations_command_center_returns_overview():
    db = SessionLocal()
    try:
        payload = operations_command_center(user=_admin_user(db), db=db)
        assert "overview" in payload
        assert "daily_briefing" in payload
        assert "district_pressure" in payload
    finally:
        db.close()


def test_case_dossier_returns_expected_sections():
    db = SessionLocal()
    try:
        payload = case_dossier(case_id=1, user=_admin_user(db), db=db)
        assert payload["case"]["id"] == 1
        assert "graph" in payload
        assert "timeline" in payload
        assert "documents" in payload
    finally:
        db.close()
