import sys
from pathlib import Path

from jose import jwt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import JWT_ALGORITHM, JWT_SECRET
from services.auth import create_access_token


def test_access_tokens_use_app_config_secret():
    token = create_access_token({"sub": "admin_tn", "role": "admin"})
    payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])

    assert payload["sub"] == "admin_tn"
    assert payload["role"] == "admin"
