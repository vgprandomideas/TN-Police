import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "frontend"))

from auth_client import request_login


class FakeResponse:
    def __init__(self, status_code, payload, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text or str(payload)
        self.ok = 200 <= status_code < 300

    def json(self):
        return self._payload


def test_request_login_prefers_current_auth_endpoint():
    calls = []

    def fake_post(url, timeout=20, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse(200, {"access_token": "token"})

    with patch("auth_client.requests.post", side_effect=fake_post):
        result = request_login("http://localhost:8000", "admin_tn", "admin123")

    assert result["ok"] is True
    assert result["path"] == "/auth/login"
    assert len(calls) == 1
    assert calls[0][0] == "http://localhost:8000/auth/login"
    assert calls[0][1]["json"] == {"username": "admin_tn", "password": "admin123"}


def test_request_login_falls_back_to_legacy_token_route_on_not_found():
    calls = []
    responses = [
        FakeResponse(404, {"detail": "Not Found"}),
        FakeResponse(200, {"access_token": "legacy-token"}),
    ]

    def fake_post(url, timeout=20, **kwargs):
        calls.append((url, kwargs))
        return responses.pop(0)

    with patch("auth_client.requests.post", side_effect=fake_post):
        result = request_login("http://localhost:8000", "admin_tn", "admin123")

    assert result["ok"] is True
    assert result["path"] == "/token"
    assert [call[0] for call in calls] == [
        "http://localhost:8000/auth/login",
        "http://localhost:8000/token",
    ]
    assert calls[0][1]["json"] == {"username": "admin_tn", "password": "admin123"}
    assert calls[1][1]["data"] == {"username": "admin_tn", "password": "admin123"}
