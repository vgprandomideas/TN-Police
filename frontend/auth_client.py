from typing import Any, Dict

import requests


def safe_json(resp: requests.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        return {
            "error": "Non-JSON response received from API",
            "status_code": resp.status_code,
            "text": resp.text[:1000],
        }


def request_login(api_url: str, username: str, password: str, timeout: int = 20) -> Dict[str, Any]:
    base_url = api_url.rstrip("/")
    attempts = [
        {
            "path": "/auth/login",
            "request_kwargs": {"json": {"username": username, "password": password}},
        },
        {
            "path": "/token",
            "request_kwargs": {"data": {"username": username, "password": password}},
        },
        {
            "path": "/login",
            "request_kwargs": {"json": {"username": username, "password": password}},
        },
    ]
    fallback_statuses = {404, 405, 415, 422}
    last_result: Dict[str, Any] = {
        "ok": False,
        "status_code": None,
        "data": {"error": "No compatible login endpoint responded"},
        "path": None,
    }

    for attempt in attempts:
        try:
            resp = requests.post(
                f"{base_url}{attempt['path']}",
                timeout=timeout,
                **attempt["request_kwargs"],
            )
        except requests.RequestException as exc:
            return {
                "ok": False,
                "status_code": None,
                "data": {"error": f"Login failed: {str(exc)}"},
                "path": attempt["path"],
            }

        data = safe_json(resp)
        result = {
            "ok": resp.ok,
            "status_code": resp.status_code,
            "data": data,
            "path": attempt["path"],
        }
        if resp.ok or resp.status_code not in fallback_statuses:
            return result
        last_result = result

    return last_result
