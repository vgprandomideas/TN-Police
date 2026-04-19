import time
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


def request_login(api_url: str, username: str, password: str, timeout: int = 75) -> Dict[str, Any]:
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
    timeout_steps = [min(timeout, 20), min(timeout, 45), timeout]

    for attempt in attempts:
        for timeout_value in dict.fromkeys(timeout_steps):
            try:
                resp = requests.post(
                    f"{base_url}{attempt['path']}",
                    timeout=timeout_value,
                    **attempt["request_kwargs"],
                )
            except requests.Timeout:
                last_result = {
                    "ok": False,
                    "status_code": None,
                    "data": {
                        "error": (
                            f"Login timed out while waking the backend at {attempt['path']}. "
                            f"Tried waiting up to {timeout_value} seconds."
                        )
                    },
                    "path": attempt["path"],
                }
                time.sleep(2)
                continue
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
            break

    return last_result
