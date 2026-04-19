from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

import requests
import streamlit as st

try:
    from auth_client import request_login
except ImportError:
    from frontend.auth_client import request_login


st.set_page_config(
    page_title="TN Police Intelligence Platform",
    page_icon=":rotating_light:",
    layout="wide",
)


DEMO_CREDENTIALS = (
    "admin_tn / admin123\n"
    "cyber_analyst / cyber123\n"
    "district_sp / district123\n"
    "viewer / viewer123"
)


def normalize_api_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    if not normalized:
        return ""
    parsed = urlparse(normalized)
    if parsed.scheme:
        return normalized
    return f"http://{normalized}"


def resolve_api_url() -> str:
    env_api_url = os.getenv("API_URL", "").strip()
    if env_api_url:
        return normalize_api_url(env_api_url)

    try:
        secrets_api_url = str(st.secrets.get("API_URL", "")).strip()
    except Exception:
        secrets_api_url = ""

    return normalize_api_url(secrets_api_url or "http://localhost:8000")


def get_api_url() -> str:
    if "api_url" not in st.session_state:
        st.session_state.api_url = resolve_api_url()
    return st.session_state.api_url.rstrip("/")


def get_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    token = st.session_state.get("token")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def safe_json(resp: requests.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        return {
            "error": "Non-JSON response received from API",
            "status_code": resp.status_code,
            "text": resp.text[:1000],
        }


def clear_login_state() -> None:
    for key in ["token", "username", "logged_in", "role", "district"]:
        st.session_state.pop(key, None)


def handle_auth_error(result: dict[str, Any]) -> None:
    data = result.get("data")
    if result.get("status_code") != 401 or not isinstance(data, dict):
        return
    detail = str(data.get("detail", "")).lower()
    if detail in {"invalid token", "user not found"}:
        clear_login_state()
        st.warning("Your session expired. Please log in again.")
        st.rerun()


def api_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"{get_api_url()}{path}"
    try:
        resp = requests.get(url, headers=get_headers(), params=params, timeout=20)
        result = {
            "ok": resp.ok,
            "status_code": resp.status_code,
            "data": safe_json(resp),
        }
        handle_auth_error(result)
        return result
    except requests.RequestException as exc:
        return {
            "ok": False,
            "status_code": None,
            "data": {"error": f"GET failed: {exc}"},
        }


def api_post(path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"{get_api_url()}{path}"
    try:
        resp = requests.post(url, headers=get_headers(), json=payload or {}, timeout=20)
        result = {
            "ok": resp.ok,
            "status_code": resp.status_code,
            "data": safe_json(resp),
        }
        handle_auth_error(result)
        return result
    except requests.RequestException as exc:
        return {
            "ok": False,
            "status_code": None,
            "data": {"error": f"POST failed: {exc}"},
        }


def call_with_alternatives(paths: list[str], params: dict[str, Any] | None = None) -> dict[str, Any]:
    last_result = {"ok": False, "status_code": None, "data": {"error": "No endpoint matched"}}
    retryable_statuses = {404, 405}
    terminal_statuses = {401, 403, 422}

    for path in paths:
        result = api_get(path, params=params)
        if result["ok"]:
            return result
        if result["status_code"] in terminal_statuses:
            return result
        if result["status_code"] not in retryable_statuses:
            last_result = result

    return last_result


def compact_params(params: dict[str, Any] | None) -> dict[str, Any]:
    if not params:
        return {}
    return {
        key: value
        for key, value in params.items()
        if value not in (None, "", "All", "All Cases", "All Districts", "Statewide")
    }


def payload_to_rows(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, list):
        rows: list[dict[str, Any]] = []
        for item in payload:
            if isinstance(item, dict):
                rows.append(item)
            else:
                rows.append({"value": item})
        return rows
    if isinstance(payload, dict):
        for key in ["items", "results", "rows", "records", "data"]:
            value = payload.get(key)
            if isinstance(value, list):
                return payload_to_rows(value)
        return [payload]
    return [{"value": payload}]


def show_result(title: str, result: dict[str, Any], empty_message: str = "No records found.") -> list[dict[str, Any]]:
    st.subheader(title)
    if not result["ok"]:
        st.error(f"Request failed ({result['status_code']})")
        if isinstance(result["data"], dict):
            st.json(result["data"])
        else:
            st.write(result["data"])
        return []

    payload = result["data"]
    rows = payload_to_rows(payload)
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    elif isinstance(payload, dict):
        st.json(payload)
    else:
        st.info(empty_message)
    return rows


def show_overview_metrics(summary: dict[str, Any]) -> None:
    metric_cols = st.columns(4)
    metric_cols[0].metric("Open Cases", summary.get("open_cases", "-"))
    metric_cols[1].metric("Active Alerts", summary.get("active_alerts", summary.get("alerts_open", "-")))
    metric_cols[2].metric("Complaints", summary.get("complaints", summary.get("complaints_count", "-")))
    metric_cols[3].metric("Stations", summary.get("stations", "-"))


def login_user(username: str, password: str) -> None:
    result = request_login(get_api_url(), username, password)
    data = result.get("data", {})
    if result.get("ok") and isinstance(data, dict) and "access_token" in data:
        st.session_state.token = data["access_token"]
        st.session_state.username = username
        st.session_state.logged_in = True
        st.session_state.role = data.get("role")
        st.session_state.district = data.get("district")
        st.success("Login successful.")
        st.rerun()

    st.error("Login failed.")
    if isinstance(data, dict):
        st.json(data)
    else:
        st.write(data)


def render_login_gate() -> None:
    st.title("TN Police Intelligence Platform")
    st.caption("Lean deployment-safe console for the TN intelligence backend.")

    left, right = st.columns([1.1, 1])
    with left:
        st.subheader("Login")
        username = st.text_input("Username", value="admin_tn")
        password = st.text_input("Password", type="password", value="admin123")
        if st.button("Login", use_container_width=True):
            login_user(username, password)

    with right:
        st.subheader("Demo credentials")
        st.code(DEMO_CREDENTIALS)
        st.info("If the backend is cold-starting on Render, the first login may take a little longer.")

    st.stop()


def render_connection_status() -> None:
    cols = st.columns(3)

    with cols[0]:
        health = call_with_alternatives(["/health", "/"])
        if health["ok"]:
            st.success("API reachable")
        else:
            st.error("API not reachable")

    with cols[1]:
        me = call_with_alternatives(["/auth/me", "/me"])
        if me["ok"] and isinstance(me["data"], dict):
            role = me["data"].get("role", "unknown")
            district = me["data"].get("district") or "statewide"
            st.info(f"{role} | {district}")
        else:
            st.warning("User context unavailable")

    with cols[2]:
        st.info(get_api_url())


def render_dashboard_page() -> None:
    dashboard = call_with_alternatives(
        ["/dashboard/summary", "/dashboard", "/metrics/summary", "/summary"]
    )

    st.header("Command Dashboard")
    if dashboard["ok"] and isinstance(dashboard["data"], dict):
        show_overview_metrics(dashboard["data"])
        with st.expander("Summary payload", expanded=False):
            st.json(dashboard["data"])
    else:
        show_result("Summary", dashboard)

    metrics = call_with_alternatives(["/metrics", "/public-metrics", "/metrics/public"])
    show_result("Public Metrics", metrics)


def render_cases_page() -> None:
    st.header("Cases")
    show_result("Case Registry", call_with_alternatives(["/cases", "/case-list"]))

    st.divider()
    st.subheader("Create Complaint-Case Link")
    left, right = st.columns(2)
    with left:
        complaint_id = st.text_input("Complaint ID")
        case_id = st.text_input("Case ID")
    with right:
        rationale = st.text_area("Rationale", height=110)

    if st.button("Create Complaint-Case Link", use_container_width=True):
        payload = {
            "complaint_id": complaint_id,
            "case_id": case_id,
            "rationale": rationale or None,
        }
        result = api_post("/complaint-case-links", payload)
        if result["ok"]:
            st.success("Link created.")
            st.json(result["data"])
        else:
            st.error("Link creation failed.")
            st.json(result["data"])


def render_alerts_graph_page() -> None:
    st.header("Alerts and Graph")
    show_result("Alerts", call_with_alternatives(["/alerts", "/alerts/list"]))

    st.divider()
    show_result("Entities", call_with_alternatives(["/graph/entities", "/entities", "/entity-list"]))

    st.divider()
    query = st.text_input("Graph search query")
    if st.button("Run Graph Search", use_container_width=True):
        if not query.strip():
            st.warning("Enter at least one character.")
        else:
            result = call_with_alternatives(
                ["/graph/complaint-case-search", "/graph/search", "/entities/search"],
                params={"q": query.strip()},
            )
            if result["ok"] and isinstance(result["data"], dict):
                payload = result["data"]
                for section in [
                    "complaints",
                    "cases",
                    "entities",
                    "watchlists",
                    "complaint_case_links",
                    "watchlist_hits",
                ]:
                    rows = payload_to_rows(payload.get(section))
                    st.markdown(f"#### {section.replace('_', ' ').title()}")
                    if rows:
                        st.dataframe(rows, use_container_width=True, hide_index=True)
                    else:
                        st.caption("No records.")
            else:
                show_result("Graph Search", result)


def render_complaints_page() -> None:
    st.header("Complaints")
    show_result("Complaint Registry", call_with_alternatives(["/complaints", "/complaints/list"]))

    st.divider()
    st.subheader("Complaint Intake")
    left, right = st.columns(2)
    with left:
        complainant_ref = st.text_input("Complainant reference")
        district = st.text_input("District")
    with right:
        complaint_type = st.text_input("Complaint type")
        channel = st.selectbox(
            "Channel",
            ["public_portal", "cyber_portal", "walkin", "synthetic_demo"],
            index=0,
        )
    description = st.text_area("Description", height=120)

    if st.button("Submit Complaint", use_container_width=True):
        payload = {
            "complainant_ref": complainant_ref or None,
            "district": district,
            "complaint_type": complaint_type,
            "channel": channel,
            "description": description or None,
        }
        result = api_post("/complaints", payload)
        if result["ok"]:
            st.success("Complaint submitted.")
            st.json(result["data"])
        else:
            st.error("Complaint submission failed.")
            st.json(result["data"])


def render_operations_page() -> None:
    st.header("Operations")
    show_result("SLA Summary", call_with_alternatives(["/sla/summary", "/sla-summary"]))
    show_result("Routing Rules", call_with_alternatives(["/routing-rules", "/rules/routing"]))
    show_result("Connectors", call_with_alternatives(["/connectors", "/source-registry", "/sources"]))
    show_result("Ingest Queue", call_with_alternatives(["/ingest-queue", "/queue/ingest"]))


def render_explorer_page() -> None:
    st.header("Raw API Explorer")
    endpoint = st.text_input("Endpoint", value="/dashboard/summary")
    query_string = st.text_input("Query params as key=value,key2=value2", value="")

    params: dict[str, str] = {}
    if query_string.strip():
        for part in query_string.split(","):
            if "=" in part:
                key, value = part.split("=", 1)
                params[key.strip()] = value.strip()

    if st.button("Call Endpoint", use_container_width=True):
        result = api_get(endpoint, params=compact_params(params) or None)
        if result["ok"]:
            st.success(f"HTTP {result['status_code']}")
        else:
            st.error(f"HTTP {result['status_code']}")
        if isinstance(result["data"], dict):
            st.json(result["data"])
        else:
            st.write(result["data"])


with st.sidebar:
    st.markdown("### API URL")
    api_url_input = st.text_input("API URL", value=get_api_url(), label_visibility="collapsed")
    st.session_state.api_url = normalize_api_url(api_url_input)

    st.divider()
    st.caption("Demo credentials")
    st.code(DEMO_CREDENTIALS)

    if st.session_state.get("logged_in"):
        st.success(f"Logged in as {st.session_state.get('username', 'unknown')}")
        if st.button("Logout", use_container_width=True):
            clear_login_state()
            st.rerun()
        page = st.radio(
            "Workspace",
            [
                "Dashboard",
                "Cases",
                "Alerts and Graph",
                "Complaints",
                "Operations",
                "Explorer",
            ],
        )
    else:
        page = "Login"


if not st.session_state.get("logged_in"):
    render_login_gate()


st.title("TN Police Intelligence Platform")
st.caption("Deployment-safe frontend connected to the FastAPI backend.")
render_connection_status()
st.divider()


if page == "Dashboard":
    render_dashboard_page()
elif page == "Cases":
    render_cases_page()
elif page == "Alerts and Graph":
    render_alerts_graph_page()
elif page == "Complaints":
    render_complaints_page()
elif page == "Operations":
    render_operations_page()
else:
    render_explorer_page()
