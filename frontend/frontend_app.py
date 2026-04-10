import os
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import pydeck as pdk
import requests
import streamlit as st

try:
    from auth_client import request_login
except ImportError:
    from frontend.auth_client import request_login

st.set_page_config(
    page_title="TN Police Intelligence Platform",
    page_icon="🚨",
    layout="wide",
)

APP_DIR = Path(__file__).resolve().parent
TN_DISTRICT_COORDS_PATH = APP_DIR.parent / "data" / "tn_district_coordinates.csv"
TN_STATE_OUTLINE = [
    [76.17, 12.18],
    [76.42, 12.55],
    [76.82, 12.92],
    [77.28, 13.17],
    [77.92, 13.33],
    [78.62, 13.39],
    [79.21, 13.35],
    [79.78, 13.25],
    [80.25, 13.12],
    [80.43, 12.78],
    [80.46, 12.36],
    [80.36, 11.89],
    [80.28, 11.42],
    [80.18, 10.98],
    [80.01, 10.55],
    [79.82, 10.16],
    [79.55, 9.74],
    [79.20, 9.39],
    [78.84, 9.20],
    [78.35, 9.00],
    [77.96, 8.86],
    [77.63, 8.56],
    [77.40, 8.22],
    [77.14, 8.08],
    [76.95, 8.36],
    [76.85, 8.79],
    [76.78, 9.31],
    [76.72, 9.86],
    [76.67, 10.34],
    [76.51, 10.82],
    [76.31, 11.23],
    [76.18, 11.72],
]
TN_MAP_VIEW_STATE = pdk.ViewState(latitude=10.85, longitude=78.62, zoom=6.35, pitch=0)


# ----------------------------
# Helpers
# ----------------------------
def resolve_api_url() -> str:
    env_api_url = os.getenv("API_URL", "").strip()
    if env_api_url:
        return env_api_url

    try:
        secrets_api_url = str(st.secrets.get("API_URL", "")).strip()
    except Exception:
        secrets_api_url = ""

    return secrets_api_url or "http://localhost:8000"


def get_api_url() -> str:
    if "api_url" not in st.session_state:
        st.session_state.api_url = resolve_api_url()
    return st.session_state.api_url.rstrip("/")


def get_headers() -> Dict[str, str]:
    token = st.session_state.get("token")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def clear_login_state() -> None:
    for key in ["token", "username", "logged_in", "role", "district"]:
        st.session_state.pop(key, None)


def handle_auth_error(result: Dict[str, Any]) -> None:
    data = result.get("data")
    if result.get("status_code") != 401 or not isinstance(data, dict):
        return
    detail = str(data.get("detail", "")).lower()
    if detail in {"invalid token", "user not found"}:
        clear_login_state()
        st.warning("Your session expired. Please log in again.")
        st.rerun()


def safe_json(resp: requests.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        return {
            "error": "Non-JSON response received from API",
            "status_code": resp.status_code,
            "text": resp.text[:1000],
        }


def api_get(path: str, params: Dict[str, Any] | None = None) -> Any:
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
    except requests.RequestException as e:
        return {
            "ok": False,
            "status_code": None,
            "data": {"error": f"GET failed: {str(e)}"},
        }


def api_post(path: str, payload: Dict[str, Any] | None = None) -> Any:
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
    except requests.RequestException as e:
        return {
            "ok": False,
            "status_code": None,
            "data": {"error": f"POST failed: {str(e)}"},
        }


def payload_to_df(payload: Any) -> pd.DataFrame:
    if payload is None:
        return pd.DataFrame()
    if isinstance(payload, list):
        return pd.DataFrame(payload)
    if isinstance(payload, dict):
        # common API wrappers
        for key in ["items", "results", "rows", "data", "records"]:
            if key in payload and isinstance(payload[key], list):
                return pd.DataFrame(payload[key])
        return pd.DataFrame([payload])
    return pd.DataFrame()


def add_radius_column(df: pd.DataFrame, intensity_column: str, output_column: str, scale: int) -> pd.DataFrame:
    radius_base = pd.to_numeric(df.get(intensity_column, 1), errors="coerce").fillna(1.0).clip(lower=1.0)
    df[output_column] = radius_base * scale
    return df


@st.cache_data(show_spinner=False)
def get_tn_district_reference() -> pd.DataFrame:
    if not TN_DISTRICT_COORDS_PATH.exists():
        return pd.DataFrame(columns=["district", "latitude", "longitude"])

    district_df = pd.read_csv(TN_DISTRICT_COORDS_PATH)
    if district_df.empty:
        return district_df

    district_df["district"] = district_df["district"].astype(str)
    district_df["latitude"] = pd.to_numeric(district_df["latitude"], errors="coerce")
    district_df["longitude"] = pd.to_numeric(district_df["longitude"], errors="coerce")
    return district_df.dropna(subset=["district", "latitude", "longitude"]).sort_values("district").reset_index(drop=True)


def blend_rgba(low: List[int], high: List[int], ratio: float) -> List[int]:
    safe_ratio = max(0.0, min(1.0, float(ratio)))
    return [int(low[idx] + ((high[idx] - low[idx]) * safe_ratio)) for idx in range(4)]


def enrich_tn_district_overlay(metric_df: pd.DataFrame, selected_district: str | None = None) -> pd.DataFrame:
    overlay_df = get_tn_district_reference().copy()
    if overlay_df.empty:
        return overlay_df

    if not metric_df.empty and "district" in metric_df.columns:
        merge_columns = [
            column
            for column in ["district", "incident_count", "avg_anomaly", "intensity", "radius_m"]
            if column in metric_df.columns
        ]
        overlay_df = overlay_df.merge(metric_df[merge_columns].drop_duplicates(subset=["district"]), on="district", how="left")

    for column, default in {
        "incident_count": 0,
        "avg_anomaly": 0.0,
        "intensity": 0.0,
        "radius_m": 0.0,
    }.items():
        overlay_df[column] = pd.to_numeric(overlay_df.get(column, default), errors="coerce").fillna(default)

    max_intensity = max(float(overlay_df["intensity"].max()), 1.0)
    overlay_df["fill_color"] = overlay_df["intensity"].apply(
        lambda value: blend_rgba([74, 163, 255, 80], [255, 105, 64, 210], float(value) / max_intensity)
    )
    overlay_df["stroke_color"] = overlay_df["intensity"].apply(
        lambda value: blend_rgba([145, 205, 255, 180], [255, 213, 94, 255], float(value) / max_intensity)
    )
    overlay_df["label_color"] = overlay_df["incident_count"].apply(
        lambda count: [241, 245, 249, 220] if count else [148, 163, 184, 180]
    )
    overlay_df["label_size"] = 13

    district_name = (selected_district or "").strip().lower()
    if district_name:
        selected_mask = overlay_df["district"].str.lower() == district_name
        overlay_df.loc[selected_mask, "label_color"] = [[255, 232, 153, 255]] * int(selected_mask.sum())
        overlay_df.loc[selected_mask, "label_size"] = 15

    return overlay_df


def build_tn_map_context_layers(overlay_df: pd.DataFrame) -> List[pdk.Layer]:
    layers: List[pdk.Layer] = [
        pdk.Layer(
            "PolygonLayer",
            data=[{"state": "Tamil Nadu", "polygon": TN_STATE_OUTLINE}],
            get_polygon="polygon",
            filled=True,
            stroked=True,
            get_fill_color=[18, 40, 74, 36],
            get_line_color=[93, 173, 226, 220],
            line_width_min_pixels=2,
            pickable=False,
        )
    ]

    if overlay_df.empty:
        return layers

    layers.append(
        pdk.Layer(
            "ScatterplotLayer",
            data=overlay_df,
            get_position="[longitude, latitude]",
            get_radius=4200,
            get_fill_color=[224, 231, 255, 40],
            get_line_color=[148, 163, 184, 120],
            line_width_min_pixels=1,
            stroked=True,
            pickable=False,
        )
    )
    layers.append(
        pdk.Layer(
            "TextLayer",
            data=overlay_df,
            get_position="[longitude, latitude]",
            get_text="district",
            get_color="label_color",
            get_size="label_size",
            size_units="pixels",
            size_scale=1,
            pickable=False,
        )
    )
    return layers


def show_api_result(
    result: Dict[str, Any],
    title: str | None = None,
    empty_message: str | None = None,
) -> pd.DataFrame:
    if title:
        st.subheader(title)

    if not result["ok"]:
        st.error(result["data"])
        return pd.DataFrame()

    payload = result["data"]
    df = payload_to_df(payload)

    if df.empty:
        if empty_message:
            st.info(empty_message)
        elif isinstance(payload, dict):
            st.json(payload)
        elif isinstance(payload, list):
            st.info("No records found.")
    else:
        st.dataframe(df, use_container_width=True)

    return df


def login(username: str, password: str) -> None:
    result = request_login(get_api_url(), username, password)
    data = result["data"]
    if result["ok"] and isinstance(data, dict) and "access_token" in data:
        st.session_state.token = data["access_token"]
        st.session_state.username = username
        st.session_state.logged_in = True
        st.session_state.role = data.get("role")
        st.session_state.district = data.get("district")
        st.success("Login successful")
        st.rerun()
    else:
        st.error(data)


def logout() -> None:
    clear_login_state()
    st.rerun()


def call_with_alternatives(paths: List[str], params: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """
    Tries multiple likely endpoint names because your backend versions changed a lot.
    """
    last_result = {"ok": False, "status_code": None, "data": {"error": "No endpoint matched"}}
    best_error = last_result
    retryable_statuses = {404, 405}
    terminal_statuses = {401, 403, 422}
    for path in paths:
        result = api_get(path, params=params)
        if result["ok"]:
            return result
        if result["status_code"] in terminal_statuses:
            return result
        if result["status_code"] not in retryable_statuses:
            best_error = result
        last_result = result
    if best_error["status_code"] is not None:
        return best_error
    return last_result


def compact_params(params: Dict[str, Any] | None) -> Dict[str, Any]:
    if not params:
        return {}
    return {
        key: value
        for key, value in params.items()
        if value not in (None, "", "All Districts", "All Cases", "Statewide")
    }


def build_case_option_map(case_df: pd.DataFrame) -> Dict[str, int]:
    options: Dict[str, int] = {}
    if case_df.empty or "id" not in case_df.columns:
        return options

    working = case_df.copy()
    working = working.dropna(subset=["id"]).sort_values(by="id")
    for _, row in working.iterrows():
        case_id = int(row["id"])
        title = str(row.get("title") or f"Case {case_id}")
        district = str(row.get("district") or "Unknown")
        options[f"{case_id} | {title} | {district}"] = case_id
    return options


def render_text_records(records: List[Dict[str, Any]], title_key: str, body_key: str, meta_keys: List[str] | None = None) -> None:
    if not records:
        st.caption("No records available.")
        return

    for row in records:
        st.markdown(f"**{row.get(title_key, 'Untitled')}**")
        if meta_keys:
            meta_parts = [str(row.get(key)) for key in meta_keys if row.get(key)]
            if meta_parts:
                st.caption(" | ".join(meta_parts))
        body = row.get(body_key)
        if body:
            st.write(body)


def render_graph_search_result(result: Dict[str, Any]) -> None:
    st.subheader("Graph Search Result")

    if not result["ok"]:
        st.error(result["data"])
        return

    payload = result["data"]
    if not isinstance(payload, dict):
        st.json(payload)
        return

    st.caption(f"Search query: {payload.get('query', '')}")

    section_keys = [
        ("Complaints", "complaints"),
        ("Cases", "cases"),
        ("Entities", "entities"),
        ("Watchlists", "watchlists"),
        ("Case Links", "complaint_case_links"),
        ("Watchlist Hits", "watchlist_hits"),
    ]

    metric_cols = st.columns(len(section_keys))
    for idx, (label, key) in enumerate(section_keys):
        records = payload.get(key)
        metric_cols[idx].metric(label, len(records) if isinstance(records, list) else 0)

    if all(len(payload.get(key) or []) == 0 for _, key in section_keys):
        st.info("No complaints, cases, entities, or watchlists matched this search.")
        return

    primary_left, primary_right = st.columns(2)
    primary_sections = [
        ("Complaints", "complaints"),
        ("Cases", "cases"),
        ("Entities", "entities"),
        ("Watchlists", "watchlists"),
    ]
    for idx, (label, key) in enumerate(primary_sections):
        records = payload.get(key) or []
        target_column = primary_left if idx % 2 == 0 else primary_right
        with target_column:
            st.markdown(f"#### {label}")
            section_df = payload_to_df(records)
            if section_df.empty:
                st.caption(f"No {label.lower()} matched this query.")
            else:
                st.dataframe(section_df, use_container_width=True)

    for label, key in [("Complaint-Case Links", "complaint_case_links"), ("Watchlist Hits", "watchlist_hits")]:
        st.markdown(f"#### {label}")
        section_df = payload_to_df(payload.get(key) or [])
        if section_df.empty:
            st.caption(f"No {label.lower()} matched this query.")
        else:
            st.dataframe(section_df, use_container_width=True)


def render_operations_center(case_df: pd.DataFrame) -> None:
    st.subheader("Operations Center")

    district_options = ["Statewide"]
    if not case_df.empty and "district" in case_df.columns:
        district_options.extend(
            sorted(
                district
                for district in case_df["district"].dropna().astype(str).unique().tolist()
                if district
            )
        )

    selected_district = st.selectbox("District focus", district_options, key="ops_center_district")
    params = compact_params({"district": None if selected_district == "Statewide" else selected_district})
    command_center = api_get("/operations/command-center", params=params or None)
    if not command_center["ok"]:
        show_api_result(command_center)
        return

    payload = command_center["data"] if isinstance(command_center["data"], dict) else {}
    overview = payload.get("overview", {})
    briefing = payload.get("daily_briefing", {})

    st.markdown("#### Daily Intelligence Brief")
    st.info(briefing.get("headline", "No briefing headline available."))
    for section in briefing.get("sections", []):
        st.write(f"- {section}")

    metric_cols = st.columns(6)
    metric_cols[0].metric("Active Cases", overview.get("active_cases", 0))
    metric_cols[1].metric("Active Alerts", overview.get("active_alerts", 0))
    metric_cols[2].metric("Breached SLA", overview.get("breached_sla_cases", 0))
    metric_cols[3].metric("Queued Tasks", overview.get("queued_tasks", 0))
    metric_cols[4].metric("Queued Notifications", overview.get("queued_notifications", 0))
    metric_cols[5].metric("Overloaded Officers", overview.get("overloaded_officers", 0))

    if str(st.session_state.get("role", "")).lower() == "admin":
        admin_cols = st.columns(2)
        with admin_cols[0]:
            if st.button("Recompute Anomalies", key="ops_recompute_anomalies"):
                result = api_post("/admin/recompute-anomalies")
                if result["ok"]:
                    st.success("Anomaly scoring recomputed.")
                else:
                    st.error(result["data"])
        with admin_cols[1]:
            if st.button("Dispatch Notifications", key="ops_dispatch_notifications"):
                result = api_post("/admin/dispatch-notifications")
                if result["ok"]:
                    st.success(result["data"])
                else:
                    st.error(result["data"])

    top_left, top_right = st.columns([1.1, 0.9])
    with top_left:
        st.markdown("#### District Pressure")
        pressure_df = payload_to_df(payload.get("district_pressure"))
        if pressure_df.empty:
            st.caption("No district pressure summary available.")
        else:
            st.dataframe(pressure_df, use_container_width=True)

        st.markdown("#### Hotspot Forecasts")
        hotspot_df = payload_to_df(payload.get("hotspot_forecasts"))
        if hotspot_df.empty:
            st.caption("No hotspot forecasts available.")
        else:
            st.dataframe(hotspot_df, use_container_width=True)

        st.markdown("#### Command Board")
        command_df = payload_to_df(payload.get("command_board"))
        if command_df.empty:
            st.caption("No live command-board items.")
        else:
            st.dataframe(command_df, use_container_width=True)

    with top_right:
        st.markdown("#### War Room Snapshots")
        war_room_df = payload_to_df(payload.get("war_room_snapshots"))
        if war_room_df.empty:
            st.caption("No war-room snapshots available.")
        else:
            st.dataframe(war_room_df, use_container_width=True)

        st.markdown("#### Patrol Gaps")
        patrol_df = payload_to_df(payload.get("patrol_gaps"))
        if patrol_df.empty:
            st.caption("No patrol gap data available.")
        else:
            st.dataframe(patrol_df, use_container_width=True)

        st.markdown("#### Queue Overview")
        task_df = payload_to_df(payload.get("task_queue"))
        notif_df = payload_to_df(payload.get("notification_queue"))
        if task_df.empty:
            st.caption("No queued tasks.")
        else:
            st.dataframe(task_df, use_container_width=True)
        if notif_df.empty:
            st.caption("No queued notifications.")
        else:
            st.dataframe(notif_df, use_container_width=True)

    lower_left, lower_right = st.columns(2)
    with lower_left:
        st.markdown("#### Suspect Focus")
        suspect_df = payload_to_df(payload.get("suspect_focus"))
        if suspect_df.empty:
            st.caption("No suspect dossiers available.")
        else:
            st.dataframe(suspect_df, use_container_width=True)

        st.markdown("#### Graph Insights")
        insights_df = payload_to_df(payload.get("graph_insights"))
        if insights_df.empty:
            st.caption("No graph insights available.")
        else:
            st.dataframe(insights_df, use_container_width=True)

    with lower_right:
        st.markdown("#### Fusion Cluster Summary")
        fusion_df = payload_to_df(payload.get("fusion_cluster_summary"))
        if fusion_df.empty:
            st.caption("No fusion cluster summary available.")
        else:
            st.dataframe(fusion_df, use_container_width=True)

        st.markdown("#### Officer Workload")
        workload_df = payload_to_df(payload.get("officer_workload"))
        if workload_df.empty:
            st.caption("No officer workload detail available.")
        else:
            st.dataframe(workload_df, use_container_width=True)


def render_fusion_workbench(case_option_map: Dict[str, int], case_df: pd.DataFrame) -> None:
    st.subheader("Fusion Workbench")

    district_options = ["All Districts"]
    if not case_df.empty and "district" in case_df.columns:
        district_options.extend(
            sorted(
                district
                for district in case_df["district"].dropna().astype(str).unique().tolist()
                if district
            )
        )

    filter_cols = st.columns(2)
    with filter_cols[0]:
        selected_district = st.selectbox("District filter", district_options, key="fusion_district_filter")
    with filter_cols[1]:
        selected_case_label = st.selectbox(
            "Case graph focus",
            ["All Cases"] + list(case_option_map.keys()),
            key="fusion_case_focus",
        )

    selected_case_id = case_option_map.get(selected_case_label)
    params = compact_params(
        {
            "district": None if selected_district == "All Districts" else selected_district,
            "case_id": selected_case_id,
        }
    )

    cluster_summary_result = api_get("/fusion/cluster-summary")
    cluster_result = api_get("/fusion/clusters", params=params or None)
    suspect_result = api_get(
        "/suspect-dossiers",
        params=compact_params({"district": None if selected_district == "All Districts" else selected_district}) or None,
    )
    insight_result = api_get("/graph/insights", params=params or None)
    similarity_result = api_get("/similarity-hits")

    cluster_summary_df = payload_to_df(cluster_summary_result["data"])
    cluster_df = payload_to_df(cluster_result["data"])
    suspect_df = payload_to_df(suspect_result["data"])
    insight_df = payload_to_df(insight_result["data"])
    similarity_df = payload_to_df(similarity_result["data"])

    metric_cols = st.columns(4)
    metric_cols[0].metric("Clusters", len(cluster_df.index))
    metric_cols[1].metric("Suspect Dossiers", len(suspect_df.index))
    metric_cols[2].metric("Graph Insights", len(insight_df.index))
    metric_cols[3].metric(
        "Top Similarity Score",
        "-" if similarity_df.empty or "similarity_score" not in similarity_df.columns else round(float(similarity_df["similarity_score"].max()), 2),
    )

    left, right = st.columns([1.05, 0.95])
    with left:
        st.markdown("#### Cluster Summary")
        if cluster_summary_result["ok"] and not cluster_summary_df.empty:
            st.dataframe(cluster_summary_df, use_container_width=True)
        elif cluster_summary_result["ok"]:
            st.caption("No cluster summary rows returned.")
        else:
            st.error(cluster_summary_result["data"])

        st.markdown("#### Cluster Members")
        if cluster_result["ok"] and not cluster_df.empty:
            st.dataframe(cluster_df, use_container_width=True)
        elif cluster_result["ok"]:
            st.caption("No fusion cluster rows returned.")
        else:
            st.error(cluster_result["data"])

        st.markdown("#### Similarity Hits")
        if similarity_result["ok"] and not similarity_df.empty:
            st.dataframe(similarity_df, use_container_width=True)
        elif similarity_result["ok"]:
            st.caption("No similarity hits available.")
        else:
            st.error(similarity_result["data"])

    with right:
        st.markdown("#### Suspect Dossiers")
        if suspect_result["ok"] and not suspect_df.empty:
            st.dataframe(suspect_df, use_container_width=True)
        elif suspect_result["ok"]:
            st.caption("No suspect dossiers available.")
        else:
            st.error(suspect_result["data"])

        st.markdown("#### Graph Insights")
        if insight_result["ok"] and not insight_df.empty:
            st.dataframe(insight_df, use_container_width=True)
        elif insight_result["ok"]:
            st.caption("No graph insights available.")
        else:
            st.error(insight_result["data"])

        if selected_case_id is not None:
            graph_result = api_get(f"/graph/case/{selected_case_id}")
            st.markdown("#### Case Graph Snapshot")
            if not graph_result["ok"]:
                st.error(graph_result["data"])
            else:
                graph_payload = graph_result["data"] if isinstance(graph_result["data"], dict) else {}
                snapshot = graph_payload.get("snapshot") or {}
                snapshot_cols = st.columns(4)
                snapshot_cols[0].metric("Nodes", len(graph_payload.get("nodes", [])))
                snapshot_cols[1].metric("Edges", len(graph_payload.get("edges", [])))
                snapshot_cols[2].metric("Timeline Events", graph_payload.get("timeline_count", 0))
                snapshot_cols[3].metric("Risk Density", snapshot.get("risk_density", "-"))
                with st.expander("Graph Nodes", expanded=False):
                    st.dataframe(payload_to_df(graph_payload.get("nodes")), use_container_width=True)
                with st.expander("Graph Edges", expanded=False):
                    st.dataframe(payload_to_df(graph_payload.get("edges")), use_container_width=True)


def render_case_dossier(case_option_map: Dict[str, int]) -> None:
    st.subheader("Case Dossier")
    if not case_option_map:
        st.warning("No cases available to load into the dossier view.")
        return

    selected_case_label = st.selectbox("Case focus", list(case_option_map.keys()), key="case_dossier_focus")
    selected_case_id = case_option_map[selected_case_label]
    dossier_result = api_get(f"/cases/{selected_case_id}/dossier")
    if not dossier_result["ok"]:
        show_api_result(dossier_result)
        return

    payload = dossier_result["data"] if isinstance(dossier_result["data"], dict) else {}
    case_row = payload.get("case", {})
    summary = payload.get("summary", {})
    graph_payload = payload.get("graph", {}) if isinstance(payload.get("graph"), dict) else {}
    snapshot = graph_payload.get("snapshot") or {}

    st.markdown(f"#### Case {case_row.get('id', selected_case_id)}: {case_row.get('title', 'Untitled Case')}")
    st.caption(case_row.get("summary") or "No case summary available.")

    bookmark_cols = st.columns([1, 1.2])
    with bookmark_cols[0]:
        bookmark_note = st.text_input("Bookmark note", key="case_dossier_bookmark_note")
    with bookmark_cols[1]:
        if st.button("Save Investigation Bookmark", key="case_dossier_bookmark"):
            bookmark_result = api_post(
                "/bookmarks",
                {
                    "bookmark_type": "case",
                    "object_ref": f"case:{selected_case_id}",
                    "title": f"Case {selected_case_id} | {case_row.get('title', 'Investigation dossier')}",
                    "notes": bookmark_note or None,
                },
            )
            if bookmark_result["ok"]:
                st.success("Investigation bookmark saved.")
            else:
                st.error(bookmark_result["data"])

    metric_cols = st.columns(7)
    metric_cols[0].metric("Status", summary.get("status", case_row.get("status", "-")))
    metric_cols[1].metric("Priority", summary.get("priority", case_row.get("priority", "-")))
    metric_cols[2].metric("SLA", summary.get("sla_status", case_row.get("sla_status", "-")))
    metric_cols[3].metric("Complaints", summary.get("linked_complaints", 0))
    metric_cols[4].metric("Evidence", summary.get("evidence_items", 0))
    metric_cols[5].metric("Tasks", summary.get("tasks", 0))
    metric_cols[6].metric("Hearings", summary.get("hearings", 0))

    left, right = st.columns([1.1, 0.9])
    with left:
        st.markdown("#### Narrative Briefs")
        render_text_records(payload.get("narrative_briefs", []), "title", "body", ["brief_type", "created_by"])

        st.markdown("#### Timeline Digests")
        render_text_records(payload.get("timeline_digests", []), "digest_title", "digest_body", ["generated_by"])

        st.markdown("#### Case Graph Snapshot")
        graph_cols = st.columns(4)
        graph_cols[0].metric("Nodes", summary.get("graph_nodes", len(graph_payload.get("nodes", []))))
        graph_cols[1].metric("Edges", summary.get("graph_edges", len(graph_payload.get("edges", []))))
        graph_cols[2].metric("Risk Density", snapshot.get("risk_density", "-"))
        graph_cols[3].metric("Complaint Links", graph_payload.get("complaint_links", 0))

        with st.expander("Graph Nodes", expanded=False):
            st.dataframe(payload_to_df(graph_payload.get("nodes")), use_container_width=True)
        with st.expander("Graph Edges", expanded=False):
            st.dataframe(payload_to_df(graph_payload.get("edges")), use_container_width=True)

    with right:
        linked_complaints = []
        for row in payload.get("linked_complaints", []):
            complaint = row.get("complaint") or {}
            linked_complaints.append(
                {
                    "complaint_id": row.get("complaint_id"),
                    "linked_by": row.get("linked_by"),
                    "rationale": row.get("rationale"),
                    "district": complaint.get("district"),
                    "complaint_type": complaint.get("complaint_type"),
                    "status": complaint.get("status"),
                }
            )

        st.markdown("#### Linked Complaints")
        linked_df = payload_to_df(linked_complaints)
        if linked_df.empty:
            st.caption("No complaints linked to this case.")
        else:
            st.dataframe(linked_df, use_container_width=True)

        st.markdown("#### Watchlist Hits")
        watchlist_df = payload_to_df(payload.get("watchlist_hits"))
        if watchlist_df.empty:
            st.caption("No watchlist hits recorded.")
        else:
            st.dataframe(watchlist_df, use_container_width=True)

        st.markdown("#### Task Queue")
        task_df = payload_to_df(payload.get("tasks"))
        if task_df.empty:
            st.caption("No tasks linked to this case.")
        else:
            st.dataframe(task_df, use_container_width=True)

    with st.expander("Timeline, Comments, and Assignments", expanded=False):
        st.markdown("##### Timeline")
        st.dataframe(payload_to_df(payload.get("timeline")), use_container_width=True)
        st.markdown("##### Comments")
        st.dataframe(payload_to_df(payload.get("comments")), use_container_width=True)
        st.markdown("##### Assignments")
        st.dataframe(payload_to_df(payload.get("assignments")), use_container_width=True)

    with st.expander("Evidence and Chain of Custody", expanded=True):
        st.markdown("##### Evidence Registry")
        st.dataframe(payload_to_df(payload.get("evidence")), use_container_width=True)
        st.markdown("##### Evidence Integrity")
        st.dataframe(payload_to_df(payload.get("evidence_integrity")), use_container_width=True)

    with st.expander("Judicial Pipeline", expanded=False):
        st.markdown("##### Prosecution Packets")
        st.dataframe(payload_to_df(payload.get("prosecution_packets")), use_container_width=True)
        st.markdown("##### Court Hearings")
        st.dataframe(payload_to_df(payload.get("court_hearings")), use_container_width=True)
        st.markdown("##### Custody and Medical")
        st.dataframe(payload_to_df(payload.get("custody_logs")), use_container_width=True)
        st.dataframe(payload_to_df(payload.get("medical_checks")), use_container_width=True)
        st.markdown("##### Prison Movements")
        st.dataframe(payload_to_df(payload.get("prison_movements")), use_container_width=True)
        st.markdown("##### Court Packet Exports")
        st.dataframe(payload_to_df(payload.get("court_packet_exports")), use_container_width=True)

    with st.expander("Document Intelligence and Exports", expanded=False):
        document_df = payload_to_df(payload.get("documents"))
        if document_df.empty:
            st.caption("No documents attached to this case.")
        else:
            st.dataframe(document_df, use_container_width=True)
        if payload.get("document_entities"):
            st.json(payload.get("document_entities"))
        export_df = payload_to_df(payload.get("export_jobs"))
        if not export_df.empty:
            st.markdown("##### Related Exports")
            st.dataframe(export_df, use_container_width=True)


# ----------------------------
# Sidebar
# ----------------------------
with st.sidebar:
    st.markdown("### API URL")
    api_url_input = st.text_input("API URL", value=get_api_url(), label_visibility="collapsed")
    st.session_state.api_url = api_url_input.rstrip("/")

    st.divider()

    if st.session_state.get("logged_in"):
        st.success(f"Logged in as: {st.session_state.get('username', 'unknown')}")
        if st.button("Logout", use_container_width=True):
            logout()
    else:
        st.info("Not logged in")

    st.divider()
    st.caption("Demo credentials")
    st.code(
        "admin_tn / admin123\n"
        "cyber_analyst / cyber123\n"
        "district_sp / district123\n"
        "viewer / viewer123"
    )


# ----------------------------
# Header
# ----------------------------
st.title("TN Police Intelligence Platform")
st.caption(
    "Public-source metrics for 2023 and partial 2024/2025, plus synthetic operational workflow data for MVP behavior."
)


# ----------------------------
# Login Gate
# ----------------------------
if not st.session_state.get("logged_in"):
    c1, c2 = st.columns([1.1, 1])

    with c1:
        st.subheader("Login")
        username = st.text_input("Username", value="admin_tn")
        password = st.text_input("Password", type="password", value="admin123")
        if st.button("Login"):
            login(username, password)

    with c2:
        st.subheader("Demo credentials")
        st.code(
            "admin_tn / admin123\n"
            "cyber_analyst / cyber123\n"
            "district_sp / district123\n"
            "viewer / viewer123"
        )

    st.stop()


# ----------------------------
# Top health checks
# ----------------------------
health_cols = st.columns(3)

with health_cols[0]:
    health = call_with_alternatives(["/health", "/"])
    if health["ok"]:
        st.success("API reachable")
    else:
        st.error("API not reachable")

with health_cols[1]:
    me = call_with_alternatives(["/auth/me", "/me", "/users/me"])
    if me["ok"]:
        payload = me["data"]
        if isinstance(payload, dict):
            role = payload.get("role")
            district = payload.get("district") or "statewide"
            label = "User context loaded"
            if role:
                label = f"{role} | {district}"
            st.info(label)
        else:
            st.info("User context available")
    else:
        st.warning("User profile endpoint unavailable")

with health_cols[2]:
    sla_summary = call_with_alternatives(["/sla/summary", "/sla-summary", "/metrics/sla"])
    if sla_summary["ok"]:
        payload = sla_summary["data"]
        if isinstance(payload, dict):
            k = payload.get("open_cases") or payload.get("total_cases") or payload.get("count")
            st.metric("SLA Snapshot", k if k is not None else "Ready")
        else:
            st.metric("SLA Snapshot", "Ready")
    else:
        st.metric("SLA Snapshot", "Unavailable")

cases_catalog = call_with_alternatives(
    [
        "/cases",
        "/case-list",
    ]
)
cases_catalog_df = payload_to_df(cases_catalog["data"]) if cases_catalog["ok"] else pd.DataFrame()
case_option_map = build_case_option_map(cases_catalog_df)


# ----------------------------
# Main Tabs
# ----------------------------
(
    command_dashboard_tab,
    operations_center_tab,
    geo_heatmaps_tab,
    cases_tab,
    case_dossier_tab,
    alerts_tab,
    fusion_workbench_tab,
    entities_graph_tab,
    complaints_tab,
    sla_tab,
    connectors_tab,
    timelines_evidence_tab,
    raw_explorer_tab,
) = st.tabs(
    [
        "Command Dashboard",
        "Operations Center",
        "Geo Heatmaps",
        "Cases",
        "Case Dossier",
        "Alerts",
        "Fusion Workbench",
        "Entities & Graph",
        "Complaints",
        "SLA",
        "Connectors",
        "Timelines & Evidence",
        "Raw Explorer",
    ]
)

# ----------------------------
# Tab 1: Command Dashboard
# ----------------------------
with command_dashboard_tab:
    st.subheader("Command Dashboard")

    c1, c2, c3, c4 = st.columns(4)

    dashboard = call_with_alternatives(
        [
            "/dashboard/summary",
            "/dashboard",
            "/metrics/summary",
            "/summary",
        ]
    )

    if dashboard["ok"] and isinstance(dashboard["data"], dict):
        data = dashboard["data"]
        with c1:
            st.metric("Open Cases", data.get("open_cases", data.get("cases_open", "-")))
        with c2:
            st.metric("Active Alerts", data.get("active_alerts", data.get("alerts_open", data.get("alerts", "-"))))
        with c3:
            st.metric("Complaints", data.get("complaints", data.get("complaints_count", data.get("total_complaints", "-"))))
        with c4:
            st.metric("Stations", data.get("stations", data.get("station_count", "-")))
        st.json(data)
    else:
        st.warning("Dashboard summary endpoint not available.")
        show_api_result(dashboard)

    st.divider()

    st.subheader("Public Metrics")
    metrics_result = call_with_alternatives(
        [
            "/metrics",
            "/public-metrics",
            "/metrics/public",
        ]
    )
    show_api_result(metrics_result)


# ----------------------------
# Tab 2: Geo Heatmaps
# ----------------------------
with geo_heatmaps_tab:
    st.subheader("Geo Heatmaps")

    f1, f2, f3, f4 = st.columns(4)
    with f1:
        district_filter = st.text_input("District filter", "")
    with f2:
        category_filter = st.text_input("Category filter", "")
    with f3:
        min_anomaly = st.slider("Minimum anomaly", 0.0, 1.0, 0.0, 0.01)
    with f4:
        source_type = st.selectbox(
            "Source type",
            ["synthetic_demo", "public", "all"],
            index=0,
        )

    params = {
        "district": district_filter or None,
        "category": category_filter or None,
        "min_anomaly": min_anomaly,
        "source_type": source_type if source_type != "all" else None,
    }

    district_result = call_with_alternatives(
        [
            "/geo/district-heatmap",
            "/district-heatmap",
            "/geo/districts",
        ],
        params=params,
    )
    district_rows = payload_to_df(district_result["data"])

    st.markdown("#### District Heatmap")
    if not district_result["ok"]:
        st.error(district_result["data"])
    elif district_rows.empty:
        st.info("No district heatmap rows returned.")
        if isinstance(district_result["data"], dict):
            st.json(district_result["data"])
    else:
        if {"latitude", "longitude"}.issubset(district_rows.columns):
            if "intensity" not in district_rows.columns:
                district_rows["intensity"] = 1
            if "district" not in district_rows.columns:
                district_rows["district"] = "Unknown"
            if "incident_count" not in district_rows.columns:
                district_rows["incident_count"] = 0
            if "avg_anomaly" not in district_rows.columns:
                district_rows["avg_anomaly"] = 0.0
            district_rows["intensity"] = pd.to_numeric(district_rows["intensity"], errors="coerce").fillna(0.0)
            district_rows = add_radius_column(district_rows, "intensity", "radius_m", 8000)
            tn_overlay_df = enrich_tn_district_overlay(district_rows, district_filter or None)

            st.caption("Tamil Nadu state view with district labels and incident intensity overlays.")
            st.pydeck_chart(
                pdk.Deck(
                    initial_view_state=TN_MAP_VIEW_STATE,
                    map_style=pdk.map_styles.LIGHT_NO_LABELS,
                    layers=build_tn_map_context_layers(tn_overlay_df)
                    + [
                        pdk.Layer(
                            "ScatterplotLayer",
                            data=tn_overlay_df,
                            get_position="[longitude, latitude]",
                            get_radius="radius_m",
                            get_fill_color="fill_color",
                            get_line_color="stroke_color",
                            line_width_min_pixels=2,
                            stroked=True,
                            pickable=True,
                            opacity=0.82,
                        )
                    ],
                    tooltip={
                        "text": "District: {district}\nIntensity: {intensity}\nIncidents: {incident_count}\nAvg anomaly: {avg_anomaly}"
                    },
                )
            )
        st.dataframe(district_rows, use_container_width=True)

    st.divider()

    station_result = call_with_alternatives(
        [
            "/geo/station-heatmap",
            "/station-heatmap",
            "/geo/stations",
        ],
        params=params,
    )
    station_rows = payload_to_df(station_result["data"])

    st.markdown("#### Station Heatmap")
    if not station_result["ok"]:
        st.error(station_result["data"])
    elif station_rows.empty:
        st.info("No station heatmap rows returned.")
        if isinstance(station_result["data"], dict):
            st.json(station_result["data"])
    else:
        if {"latitude", "longitude"}.issubset(station_rows.columns):
            if "intensity" not in station_rows.columns:
                station_rows["intensity"] = 1
            if "station_name" not in station_rows.columns:
                station_rows["station_name"] = station_rows.get("station", "Unknown")
            if "incident_count" not in station_rows.columns:
                station_rows["incident_count"] = 0
            station_rows["intensity"] = pd.to_numeric(station_rows["intensity"], errors="coerce").fillna(0.0)
            station_rows = add_radius_column(station_rows, "intensity", "radius_m", 2500)
            station_rows["fill_color"] = station_rows["intensity"].apply(
                lambda value: blend_rgba([56, 189, 248, 110], [249, 115, 22, 220], min(float(value) / 10.0, 1.0))
            )
            station_rows["stroke_color"] = station_rows["intensity"].apply(
                lambda value: blend_rgba([186, 230, 253, 180], [254, 215, 170, 255], min(float(value) / 10.0, 1.0))
            )
            station_overlay_df = enrich_tn_district_overlay(district_rows, district_filter or None)

            st.caption("Tamil Nadu station intelligence view anchored to district positions across the state.")
            st.pydeck_chart(
                pdk.Deck(
                    initial_view_state=TN_MAP_VIEW_STATE,
                    map_style=pdk.map_styles.LIGHT_NO_LABELS,
                    layers=build_tn_map_context_layers(station_overlay_df)
                    + [
                        pdk.Layer(
                            "ScatterplotLayer",
                            data=station_rows,
                            get_position="[longitude, latitude]",
                            get_radius="radius_m",
                            get_fill_color="fill_color",
                            get_line_color="stroke_color",
                            line_width_min_pixels=1.5,
                            stroked=True,
                            pickable=True,
                            opacity=0.75,
                        )
                    ],
                    tooltip={
                        "text": "Station: {station_name}\nIncidents: {incident_count}\nIntensity: {intensity}"
                    },
                )
            )
        st.dataframe(station_rows, use_container_width=True)


# ----------------------------
# Tab 3: Cases
# ----------------------------
with cases_tab:
    st.subheader("Cases")

    cases = cases_catalog
    case_df = show_api_result(cases)

    st.divider()
    st.markdown("#### Create / Link Complaint to Case")

    c1, c2 = st.columns(2)
    with c1:
        complaint_id = st.text_input("Complaint ID")
        case_id = st.text_input("Case ID")
    with c2:
        rationale = st.text_area("Rationale", height=100)

    if st.button("Create Complaint-Case Link"):
        result = api_post(
            "/complaint-case-links",
            {
                "complaint_id": complaint_id,
                "case_id": case_id,
                "rationale": rationale or None,
            },
        )
        if result["ok"]:
            st.success(result["data"])
        else:
            st.error(result["data"])


# ----------------------------
# Tab 4: Alerts
# ----------------------------
with alerts_tab:
    st.subheader("Alerts")

    alerts = call_with_alternatives(
        [
            "/alerts",
            "/alerts/list",
        ]
    )
    show_api_result(alerts)

    st.divider()

    rules = call_with_alternatives(
        [
            "/geo/geofence-alerts",
        ]
    )
    st.markdown("#### Geofence Alerts")
    show_api_result(rules)


# ----------------------------
# Tab 5: Entities & Graph
# ----------------------------
with entities_graph_tab:
    st.subheader("Entities & Graph")

    search_q = st.text_input("Search complaint/case/entity", "")
    if st.button("Run Graph Search"):
        query = search_q.strip()
        if not query:
            st.warning("Enter at least one character to run graph search.")
        else:
            result = call_with_alternatives(
                [
                    "/graph/complaint-case-search",
                    "/graph/search",
                    "/entities/search",
                ],
                params={"q": query},
            )
            render_graph_search_result(result)

    st.divider()

    entity_result = call_with_alternatives(
        [
            "/graph/entities",
            "/entities",
            "/entity-list",
        ]
    )
    st.markdown("#### Entities")
    show_api_result(entity_result)


# ----------------------------
# Tab 6: Complaints
# ----------------------------
with complaints_tab:
    st.subheader("Complaints")

    complaints = call_with_alternatives(
        [
            "/complaints",
            "/complaints/list",
        ]
    )
    show_api_result(complaints)

    st.divider()
    st.markdown("#### Complaint Intake")

    col1, col2 = st.columns(2)
    with col1:
        complainant_ref = st.text_input("Complainant reference")
        district = st.text_input("District")
    with col2:
        complaint_type = st.text_input("Complaint type")
        channel = st.selectbox("Channel", ["public_portal", "cyber_portal", "walkin", "synthetic_demo"], index=0)

    description = st.text_area("Description")

    if st.button("Submit Complaint"):
        result = api_post(
            "/complaints",
            {
                "complainant_ref": complainant_ref or None,
                "district": district,
                "complaint_type": complaint_type,
                "channel": channel,
                "description": description or None,
            },
        )
        if result["ok"]:
            st.success(result["data"])
        else:
            st.error(result["data"])


# ----------------------------
# Tab 7: SLA
# ----------------------------
with sla_tab:
    st.subheader("SLA")

    sla_result = call_with_alternatives(
        [
            "/sla/summary",
            "/sla-summary",
        ]
    )
    show_api_result(sla_result, title="SLA Summary")

    st.divider()

    routing_result = call_with_alternatives(
        [
            "/routing-rules",
            "/rules/routing",
        ]
    )
    st.markdown("#### Routing Rules")
    show_api_result(routing_result)


# ----------------------------
# Tab 8: Connectors
# ----------------------------
with connectors_tab:
    st.subheader("Connectors / Source Registry")

    connectors = call_with_alternatives(
        [
            "/connectors",
            "/source-registry",
            "/sources",
        ]
    )
    show_api_result(connectors)

    st.divider()

    ingest = call_with_alternatives(
        [
            "/ingest-queue",
            "/queue/ingest",
        ]
    )
    st.markdown("#### Ingest Queue")
    show_api_result(ingest)


# ----------------------------
# Tab 9: Timelines & Evidence
# ----------------------------
with timelines_evidence_tab:
    st.subheader("Timelines & Evidence")

    known_case_labels = ["Select a known case"] + list(case_option_map.keys())
    selected_case_label = st.selectbox("Known cases", known_case_labels, key="timeline_known_case")
    selected_case_id = case_option_map.get(selected_case_label)

    manual_case_id = st.text_input("Case ID for timeline/evidence", "", key="timeline_case_id_input").strip()
    case_id_lookup = manual_case_id or (str(selected_case_id) if selected_case_id is not None else "")
    st.caption("Case 1 and 2 currently include seeded timeline/evidence data. Case 3 is valid but may have lighter demo history.")

    selected_case_row = pd.DataFrame()
    if case_id_lookup and not cases_catalog_df.empty and "id" in cases_catalog_df.columns:
        selected_case_row = cases_catalog_df[
            cases_catalog_df["id"].astype(str) == str(case_id_lookup)
        ]

    if case_id_lookup:
        if selected_case_row.empty:
            st.warning(f"Case {case_id_lookup} is not in the current case catalog.")
        else:
            case_record = selected_case_row.iloc[0]
            case_cols = st.columns(4)
            case_cols[0].metric("Case", str(case_record.get("id", case_id_lookup)))
            case_cols[1].metric("District", str(case_record.get("district") or "Unknown"))
            case_cols[2].metric("Status", str(case_record.get("status") or "Unknown"))
            case_cols[3].metric("Priority", str(case_record.get("priority") or "Unknown"))

    c1, c2 = st.columns(2)

    with c1:
        if st.button("Load Timeline"):
            if not case_id_lookup:
                st.warning("Enter a case ID before loading the timeline.")
            else:
                result = call_with_alternatives(
                    [
                        f"/cases/{case_id_lookup}/timeline",
                        f"/timeline/{case_id_lookup}",
                    ]
                )
                show_api_result(
                    result,
                    title="Timeline",
                    empty_message=(
                        f"No timeline events are recorded for case {case_id_lookup} yet. "
                        "The case exists, but no activity has been logged into the demo registry."
                    ),
                )

    with c2:
        if st.button("Load Evidence"):
            if not case_id_lookup:
                st.warning("Enter a case ID before loading evidence.")
            else:
                result = call_with_alternatives(
                    [
                        f"/cases/{case_id_lookup}/evidence",
                        f"/evidence/{case_id_lookup}",
                    ]
                )
                show_api_result(
                    result,
                    title="Evidence Registry",
                    empty_message=(
                        f"No evidence is registered for case {case_id_lookup} yet. "
                        "Try case 1 or 2 for current demo evidence, or add evidence to this case."
                    ),
                )


# ----------------------------
# Tab 10: Raw Explorer
# ----------------------------
with raw_explorer_tab:
    st.subheader("Raw API Explorer")

    endpoint = st.text_input("Endpoint", value="/dashboard/summary")
    query_string = st.text_input("Query params as key=value,key2=value2", value="")

    params = {}
    if query_string.strip():
        for part in query_string.split(","):
            if "=" in part:
                k, v = part.split("=", 1)
                params[k.strip()] = v.strip()

    if st.button("Call Endpoint"):
        result = api_get(endpoint, params=params or None)
        if result["ok"]:
            st.success(f"HTTP {result['status_code']}")
            st.json(result["data"])
        else:
            st.error(result["data"])


# ----------------------------
# Advanced: Operations Center
# ----------------------------
with operations_center_tab:
    render_operations_center(cases_catalog_df)


# ----------------------------
# Advanced: Fusion Workbench
# ----------------------------
with fusion_workbench_tab:
    render_fusion_workbench(case_option_map, cases_catalog_df)


# ----------------------------
# Advanced: Case Dossier
# ----------------------------
with case_dossier_tab:
    render_case_dossier(case_option_map)
