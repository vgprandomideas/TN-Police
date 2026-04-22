from __future__ import annotations

from collections import defaultdict
import csv
import json
import os
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
import streamlit as st
import streamlit.components.v1 as components

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
DEFAULT_DISTRICT_SCOPE = "Statewide"
NO_CASE_LABEL = "No case focus"
REQUEST_TIMEOUT = 75
APP_DIR = Path(__file__).resolve().parent
DISTRICT_COORDS_PATH = APP_DIR.parent / "data" / "tn_district_coordinates.csv"
STATION_MASTER_PATH = APP_DIR.parent / "data" / "station_master_seed.csv"
TN_STATE_OUTLINE = [
    (76.17, 12.18),
    (76.42, 12.55),
    (76.82, 12.92),
    (77.28, 13.17),
    (77.92, 13.33),
    (78.62, 13.39),
    (79.21, 13.35),
    (79.78, 13.25),
    (80.25, 13.12),
    (80.43, 12.78),
    (80.46, 12.36),
    (80.36, 11.89),
    (80.28, 11.42),
    (80.18, 10.98),
    (80.01, 10.55),
    (79.82, 10.16),
    (79.55, 9.74),
    (79.20, 9.39),
    (78.84, 9.20),
    (78.35, 9.00),
    (77.96, 8.86),
    (77.63, 8.56),
    (77.40, 8.22),
    (77.14, 8.08),
    (76.95, 8.36),
    (76.85, 8.79),
    (76.78, 9.31),
    (76.72, 9.86),
    (76.67, 10.34),
    (76.51, 10.82),
    (76.31, 11.23),
    (76.18, 11.72),
]


def apply_theme() -> None:
    st.markdown(
        """
        <style>
        :root {
            --tn-bg: #09111d;
            --tn-panel: rgba(16, 24, 37, 0.88);
            --tn-panel-strong: rgba(24, 36, 53, 0.94);
            --tn-line: rgba(92, 116, 151, 0.35);
            --tn-accent: #ff8c42;
            --tn-accent-soft: rgba(255, 140, 66, 0.14);
            --tn-info: #76b7ff;
            --tn-success: #47d89a;
            --tn-text: #edf2ff;
            --tn-muted: #97a8c4;
        }

        .stApp {
            background:
                radial-gradient(circle at 15% 20%, rgba(255, 140, 66, 0.14), transparent 28%),
                radial-gradient(circle at 85% 12%, rgba(91, 143, 249, 0.16), transparent 24%),
                linear-gradient(180deg, #081019 0%, #0b1320 46%, #0f1724 100%);
            color: var(--tn-text);
        }

        .main .block-container {
            padding-top: 2.1rem;
            padding-bottom: 3rem;
            max-width: 1400px;
        }

        [data-testid="stSidebar"] {
            background:
                linear-gradient(180deg, rgba(9, 17, 29, 0.98) 0%, rgba(15, 23, 36, 0.98) 100%);
            border-right: 1px solid var(--tn-line);
        }

        [data-testid="stMetric"] {
            background: linear-gradient(180deg, rgba(17, 26, 39, 0.92), rgba(11, 18, 29, 0.94));
            border: 1px solid var(--tn-line);
            border-radius: 18px;
            padding: 0.75rem 1rem;
            box-shadow: 0 18px 32px rgba(0, 0, 0, 0.18);
        }

        .tn-hero {
            border: 1px solid var(--tn-line);
            border-radius: 26px;
            padding: 1.5rem 1.6rem 1.25rem 1.6rem;
            background:
                linear-gradient(135deg, rgba(255, 140, 66, 0.12), rgba(118, 183, 255, 0.1)),
                linear-gradient(180deg, rgba(18, 28, 43, 0.98), rgba(10, 16, 27, 0.95));
            box-shadow: 0 24px 44px rgba(0, 0, 0, 0.22);
            margin-bottom: 1.25rem;
        }

        .tn-eyebrow {
            font-size: 0.84rem;
            letter-spacing: 0.16em;
            text-transform: uppercase;
            color: var(--tn-info);
            margin-bottom: 0.5rem;
            font-weight: 700;
        }

        .tn-title {
            font-size: 2.4rem;
            line-height: 1.03;
            font-weight: 800;
            color: var(--tn-text);
            margin: 0;
        }

        .tn-subtitle {
            margin-top: 0.6rem;
            color: var(--tn-muted);
            max-width: 980px;
            font-size: 1rem;
            line-height: 1.6;
        }

        .tn-chip-row {
            display: flex;
            flex-wrap: wrap;
            gap: 0.55rem;
            margin-top: 1rem;
        }

        .tn-chip {
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            border-radius: 999px;
            padding: 0.38rem 0.74rem;
            font-size: 0.82rem;
            color: var(--tn-text);
            background: rgba(255, 255, 255, 0.06);
            border: 1px solid rgba(255, 255, 255, 0.08);
        }

        .tn-panel-title {
            color: var(--tn-text);
            font-weight: 700;
            margin-top: 0.2rem;
        }

        .tn-inline-note {
            background: rgba(118, 183, 255, 0.1);
            border: 1px solid rgba(118, 183, 255, 0.18);
            border-radius: 16px;
            padding: 0.85rem 1rem;
            color: #cfe3ff;
            margin-bottom: 1rem;
        }

        .tn-brief {
            border-left: 3px solid var(--tn-accent);
            background: rgba(255, 140, 66, 0.08);
            border-radius: 0 16px 16px 0;
            padding: 0.95rem 1rem;
            margin-bottom: 0.8rem;
        }

        .tn-message-card {
            border: 1px solid var(--tn-line);
            border-radius: 18px;
            padding: 0.9rem 1rem;
            margin-bottom: 0.8rem;
            background: linear-gradient(180deg, rgba(17, 26, 39, 0.92), rgba(10, 17, 28, 0.94));
        }

        .tn-message-meta {
            color: var(--tn-muted);
            font-size: 0.84rem;
            margin-bottom: 0.45rem;
        }

        .tn-message-priority {
            color: var(--tn-accent);
            font-weight: 700;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            font-size: 0.74rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


apply_theme()


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
        resp = requests.get(url, headers=get_headers(), params=params, timeout=REQUEST_TIMEOUT)
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
        resp = requests.post(url, headers=get_headers(), json=payload or {}, timeout=REQUEST_TIMEOUT)
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
        if value not in (None, "", "All", "All Cases", "All Districts", DEFAULT_DISTRICT_SCOPE, NO_CASE_LABEL)
    }


def to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def to_optional_int(value: str) -> int | None:
    value = str(value).strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def interpolate_color(start: tuple[int, int, int], end: tuple[int, int, int], ratio: float) -> str:
    safe_ratio = clamp(ratio, 0.0, 1.0)
    red = round(start[0] + (end[0] - start[0]) * safe_ratio)
    green = round(start[1] + (end[1] - start[1]) * safe_ratio)
    blue = round(start[2] + (end[2] - start[2]) * safe_ratio)
    return f"rgb({red}, {green}, {blue})"


def load_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_district_reference_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in load_csv_rows(DISTRICT_COORDS_PATH):
        rows.append(
            {
                "district": row.get("district"),
                "latitude": to_float(row.get("latitude")),
                "longitude": to_float(row.get("longitude")),
            }
        )
    return rows


def load_station_reference_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in load_csv_rows(STATION_MASTER_PATH):
        rows.append(
            {
                "district": row.get("district"),
                "station_name": row.get("station_name"),
                "station_type": row.get("station_type"),
                "latitude": to_float(row.get("latitude")),
                "longitude": to_float(row.get("longitude")),
            }
        )
    return rows


def project_geo_point(
    longitude: float,
    latitude: float,
    min_lon: float,
    max_lon: float,
    min_lat: float,
    max_lat: float,
    width: int,
    height: int,
    padding: int,
) -> tuple[float, float]:
    usable_width = width - (padding * 2)
    usable_height = height - (padding * 2)
    x = padding + ((longitude - min_lon) / max(max_lon - min_lon, 0.0001)) * usable_width
    y = height - padding - ((latitude - min_lat) / max(max_lat - min_lat, 0.0001)) * usable_height
    return x, y


def build_geo_svg(
    title: str,
    subtitle: str,
    points: list[dict[str, Any]],
    point_label_key: str,
    selected_label: str | None = None,
    intensity_key: str = "intensity",
    value_key: str = "incident_count",
    height: int = 760,
    coverage_key: str | None = None,
    label_stride: int = 1,
    show_labels: bool = True,
) -> str:
    width = 980
    padding = 70
    if not points:
        return (
            '<div class="tn-inline-note">'
            f"{escape(title)} data is not available for the current selection."
            "</div>"
        )

    all_lons = [coord[0] for coord in TN_STATE_OUTLINE] + [to_float(row.get("longitude")) for row in points]
    all_lats = [coord[1] for coord in TN_STATE_OUTLINE] + [to_float(row.get("latitude")) for row in points]
    min_lon, max_lon = min(all_lons), max(all_lons)
    min_lat, max_lat = min(all_lats), max(all_lats)

    outline_points = []
    for lon, lat in TN_STATE_OUTLINE:
        x, y = project_geo_point(lon, lat, min_lon, max_lon, min_lat, max_lat, width, height, padding)
        outline_points.append(f"{x:.1f},{y:.1f}")
    outline_markup = " ".join(outline_points)

    max_intensity = max((to_float(row.get(intensity_key)) for row in points), default=0.0)
    max_intensity = max(max_intensity, 1.0)

    point_markup: list[str] = []
    for index, row in enumerate(points):
        label = str(row.get(point_label_key) or "Unknown")
        latitude = to_float(row.get("latitude"))
        longitude = to_float(row.get("longitude"))
        x, y = project_geo_point(longitude, latitude, min_lon, max_lon, min_lat, max_lat, width, height, padding)
        intensity = to_float(row.get(intensity_key))
        ratio = intensity / max_intensity
        radius = 8 + (ratio * 16)
        fill = interpolate_color((71, 122, 199), (255, 140, 66), ratio)
        stroke = "#ffe2bf" if selected_label and label == selected_label else "#d8e6ff"
        stroke_width = 4 if selected_label and label == selected_label else 1.6
        label_y = y - radius - (15 if index % 2 else 7)
        metric_value = row.get(value_key, row.get(intensity_key, 0))
        coverage_value = to_float(row.get(coverage_key)) if coverage_key else 0.0
        tooltip_lines = [
            label,
            f"Intensity: {row.get(intensity_key, 0)}",
            f"Metric: {metric_value}",
        ]
        if coverage_key:
            tooltip_lines.append(f"{coverage_key.replace('_', ' ').title()}: {row.get(coverage_key, 0)}")
        if row.get("avg_anomaly") not in (None, "", "N/A"):
            tooltip_lines.append(f"Avg anomaly: {row.get('avg_anomaly')}")
        tooltip = " | ".join(str(item) for item in tooltip_lines)
        coverage_markup = ""
        if coverage_key:
            coverage_radius = radius + min(coverage_value * 2.4, 42)
            coverage_markup = (
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{coverage_radius:.1f}" '
                'fill="rgba(255, 140, 66, 0.08)" stroke="rgba(255, 140, 66, 0.22)" '
                'stroke-width="1.1" stroke-dasharray="6 4"></circle>'
            )
        label_markup = ""
        if show_labels and (label_stride <= 1 or index % label_stride == 0 or label == selected_label):
            label_markup = (
                f'<text x="{x:.1f}" y="{label_y:.1f}" text-anchor="middle" '
                'style="fill:#eaf2ff;font-size:11px;font-family:system-ui,sans-serif;font-weight:600;">'
                f"{escape(label)}</text>"
            )
        point_markup.append(
            f"""
            <g>
                {coverage_markup}
                <circle cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}" fill="{fill}" fill-opacity="0.88"
                    stroke="{stroke}" stroke-width="{stroke_width}">
                    <title>{escape(tooltip)}</title>
                </circle>
                {label_markup}
            </g>
            """
        )

    return f"""
    <div style="border:1px solid rgba(92,116,151,0.35);border-radius:24px;padding:1rem 1rem 0.7rem 1rem;
        background:linear-gradient(180deg, rgba(15,25,40,0.98), rgba(10,18,28,0.96));">
        <div style="display:flex;justify-content:space-between;align-items:flex-end;gap:1rem;flex-wrap:wrap;">
            <div>
                <div style="color:#76b7ff;font-size:0.82rem;letter-spacing:0.12em;text-transform:uppercase;font-weight:700;">{escape(title)}</div>
                <div style="color:#97a8c4;font-size:0.95rem;margin-top:0.25rem;">{escape(subtitle)}</div>
            </div>
            <div style="color:#97a8c4;font-size:0.82rem;">Hover points for district or station detail.</div>
        </div>
        <svg viewBox="0 0 {width} {height}" style="width:100%;height:auto;margin-top:0.8rem;">
            <polygon points="{outline_markup}" fill="rgba(118,183,255,0.06)"
                stroke="rgba(118,183,255,0.45)" stroke-width="3" />
            {"".join(point_markup)}
        </svg>
    </div>
    """


def render_geo_html(markup: str, height: int) -> None:
    if markup.strip().startswith('<div class="tn-inline-note">'):
        st.markdown(markup, unsafe_allow_html=True)
        return
    components.html(markup, height=height, scrolling=False)

def scalarize(value: Any) -> Any:
    if value is None:
        return "N/A"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(item) for item in value) if value else "N/A"
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=True)
    return value


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
            if isinstance(payload.get(key), list):
                return payload_to_rows(payload.get(key))
        return [payload]
    return [{"value": payload}]


def clean_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: scalarize(value) for key, value in row.items()} for row in rows]


def rows_from_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    return clean_rows(payload_to_rows(result.get("data")))


def build_district_map_rows(
    heatmap_rows: list[dict[str, Any]],
    selected_district: str | None = None,
) -> list[dict[str, Any]]:
    heatmap_lookup = {str(row.get("district")): row for row in heatmap_rows if row.get("district")}
    combined_rows: list[dict[str, Any]] = []
    for row in load_district_reference_rows():
        district = str(row.get("district") or "")
        metric_row = heatmap_lookup.get(district, {})
        combined_rows.append(
            {
                "district": district,
                "latitude": row.get("latitude"),
                "longitude": row.get("longitude"),
                "incident_count": to_int(metric_row.get("incident_count")),
                "avg_anomaly": to_float(metric_row.get("avg_anomaly")),
                "intensity": round(to_float(metric_row.get("intensity")), 2),
                "selected": district == selected_district,
            }
        )
    return combined_rows


def build_station_map_rows(
    station_heatmap_rows: list[dict[str, Any]],
    district_scope: str,
) -> list[dict[str, Any]]:
    heatmap_lookup = {
        (str(row.get("district")), str(row.get("station_name"))): row
        for row in station_heatmap_rows
        if row.get("station_name")
    }
    combined_rows: list[dict[str, Any]] = []
    for row in load_station_reference_rows():
        district = str(row.get("district") or "")
        if district_scope != DEFAULT_DISTRICT_SCOPE and district != district_scope:
            continue
        station_name = str(row.get("station_name") or "")
        metric_row = heatmap_lookup.get((district, station_name), {})
        combined_rows.append(
            {
                "station_id": to_optional_int(str(metric_row.get("station_id", ""))),
                "district": district,
                "station_name": station_name,
                "station_type": row.get("station_type"),
                "latitude": row.get("latitude"),
                "longitude": row.get("longitude"),
                "incident_count": to_int(metric_row.get("incident_count")),
                "avg_anomaly": to_float(metric_row.get("avg_anomaly")),
                "intensity": round(to_float(metric_row.get("intensity")), 2),
            }
        )
    return combined_rows


def build_cctv_district_rows(
    district_map_rows: list[dict[str, Any]],
    geofence_rows: list[dict[str, Any]],
    hotspot_rows: list[dict[str, Any]],
    patrol_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    geofence_counts: dict[str, int] = defaultdict(int)
    hotspot_counts: dict[str, int] = defaultdict(int)
    patrol_gap_counts: dict[str, int] = defaultdict(int)

    for row in geofence_rows:
        district = str(row.get("district") or "")
        if district:
            geofence_counts[district] += 1
    for row in hotspot_rows:
        district = str(row.get("district") or "")
        if district:
            hotspot_counts[district] += 1
    for row in patrol_rows:
        district = str(row.get("district") or "")
        if district and to_float(row.get("coverage_ratio"), 1.0) < 0.7:
            patrol_gap_counts[district] += 1

    output: list[dict[str, Any]] = []
    for row in district_map_rows:
        district = str(row.get("district") or "")
        incident_count = to_int(row.get("incident_count"))
        intensity = to_float(row.get("intensity"))
        avg_anomaly = to_float(row.get("avg_anomaly"))
        geofence_count = geofence_counts.get(district, 0)
        hotspot_count = hotspot_counts.get(district, 0)
        patrol_gap_count = patrol_gap_counts.get(district, 0)
        surveillance_score = round(
            (intensity * 1.45)
            + (incident_count * 0.22)
            + (avg_anomaly * 8.5)
            + (geofence_count * 2.4)
            + (hotspot_count * 1.8)
            + (patrol_gap_count * 1.6),
            2,
        )
        recommended_cameras = max(
            8,
            round((incident_count * 0.55) + (intensity * 1.25) + (hotspot_count * 4.2) + (patrol_gap_count * 3.4)),
        )
        ptz_units = max(2, round(recommended_cameras * 0.22))
        fixed_dome_units = max(3, round(recommended_cameras * 0.43))
        anpr_units = max(1, round(recommended_cameras * 0.18))
        mobile_towers = max(0, round((geofence_count + hotspot_count) * 0.6))
        posture = "Immediate dense coverage"
        if surveillance_score < 18:
            posture = "Preventive monitoring"
        elif surveillance_score < 30:
            posture = "Targeted reinforcement"
        output.append(
            {
                "district": district,
                "latitude": row.get("latitude"),
                "longitude": row.get("longitude"),
                "incident_count": incident_count,
                "avg_anomaly": round(avg_anomaly, 2),
                "intensity": round(intensity, 2),
                "geofence_zones": geofence_count,
                "forecast_hotspots": hotspot_count,
                "patrol_gaps": patrol_gap_count,
                "surveillance_score": surveillance_score,
                "recommended_cameras": recommended_cameras,
                "ptz_units": ptz_units,
                "fixed_dome_units": fixed_dome_units,
                "anpr_units": anpr_units,
                "mobile_towers": mobile_towers,
                "retention_profile": "90 days" if surveillance_score >= 30 else "60 days" if surveillance_score >= 18 else "30 days",
                "deployment_posture": posture,
            }
        )
    return sorted(output, key=lambda item: to_float(item.get("surveillance_score")), reverse=True)


def build_cctv_station_rows(station_map_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in station_map_rows:
        station_type = str(row.get("station_type") or "Police Station")
        incident_count = to_int(row.get("incident_count"))
        intensity = to_float(row.get("intensity"))
        avg_anomaly = to_float(row.get("avg_anomaly"))
        coverage_circle_km = round(1.2 + (intensity * 0.08) + (incident_count * 0.03) + (0.9 if station_type == "Central" else 0.7), 2)
        recommended_cameras = max(3, round((incident_count * 0.85) + (intensity * 0.6) + (3 if station_type == "Central" else 2)))
        output.append(
            {
                "district": row.get("district"),
                "station_name": row.get("station_name"),
                "station_type": station_type,
                "latitude": row.get("latitude"),
                "longitude": row.get("longitude"),
                "incident_count": incident_count,
                "avg_anomaly": round(avg_anomaly, 2),
                "intensity": round(intensity, 2),
                "coverage_circle_km": coverage_circle_km,
                "recommended_cameras": recommended_cameras,
                "camera_profile": "PTZ + Dome grid" if station_type == "Central" else "Cyber ingress + ANPR",
                "blind_spot_risk": "High" if intensity >= 8 or avg_anomaly >= 0.7 else "Moderate" if intensity >= 4 else "Low",
                "watch_posture": "Junction saturation" if station_type == "Central" else "Digital corridor watch",
            }
        )
    return sorted(output, key=lambda item: (to_float(item.get("intensity")), to_int(item.get("incident_count"))), reverse=True)


def build_police_circle_rows(station_map_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in station_map_rows:
        intensity = to_float(row.get("intensity"))
        incident_count = to_int(row.get("incident_count"))
        station_type = str(row.get("station_type") or "Police Station")
        lookout_radius_km = round(1.5 + (intensity * 0.11) + (incident_count * 0.04) + (1.0 if station_type == "Central" else 0.8), 2)
        output.append(
            {
                "district": row.get("district"),
                "station_name": row.get("station_name"),
                "station_type": station_type,
                "latitude": row.get("latitude"),
                "longitude": row.get("longitude"),
                "intensity": round(intensity, 2),
                "incident_count": incident_count,
                "lookout_radius_km": lookout_radius_km,
                "circle_priority": "Red" if intensity >= 8 else "Amber" if intensity >= 4 else "Blue",
                "lookout_focus": "Road and junction interception" if station_type == "Central" else "Fraud and digital evidence watch",
            }
        )
    return sorted(output, key=lambda item: to_float(item.get("lookout_radius_km")), reverse=True)


def summarize_comms_rooms(message_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in message_rows:
        room_name = str(row.get("room_name") or "Unassigned")
        slot = grouped.setdefault(
            room_name,
            {
                "room_name": room_name,
                "channel_scope": row.get("channel_scope"),
                "district": row.get("district"),
                "messages": 0,
                "priority_messages": 0,
                "latest_sender": row.get("sender_username"),
                "latest_activity": row.get("created_at"),
            },
        )
        slot["messages"] += 1
        if str(row.get("priority")).lower() in {"high", "critical"}:
            slot["priority_messages"] += 1
        if str(row.get("created_at")) > str(slot.get("latest_activity")):
            slot["latest_sender"] = row.get("sender_username")
            slot["latest_activity"] = row.get("created_at")
    return sorted(grouped.values(), key=lambda item: str(item.get("latest_activity")), reverse=True)


def render_message_feed(rows: list[dict[str, Any]], empty_message: str = "No coordination traffic available.") -> None:
    if not rows:
        st.caption(empty_message)
        return

    for row in rows:
        priority = str(row.get("priority") or "routine")
        recipient = row.get("recipient_username") or row.get("room_name") or "broadcast"
        meta = " | ".join(
            part for part in [
                f"{row.get('sender_username', 'unknown')} -> {recipient}",
                str(row.get("channel_scope") or "statewide"),
                str(row.get("district") or "statewide"),
                str(row.get("created_at") or "n/a"),
            ]
            if part
        )
        body = escape(str(row.get("message_text") or ""))
        st.markdown(
            f"""
            <div class="tn-message-card">
                <div class="tn-message-priority">{escape(priority)}</div>
                <div class="tn-message-meta">{escape(meta)}</div>
                <div>{body}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_result_error(result: dict[str, Any], title: str) -> None:
    st.error(f"{title} unavailable.")
    data = result.get("data")
    if isinstance(data, dict):
        st.json(data)
    else:
        st.write(data)


def render_table(
    title: str,
    rows: list[dict[str, Any]],
    caption: str | None = None,
    empty_message: str = "No records found.",
    limit: int | None = None,
) -> None:
    st.markdown(f"#### {title}")
    if caption:
        st.caption(caption)
    working_rows = clean_rows(rows)
    if limit is not None:
        working_rows = working_rows[:limit]
    if working_rows:
        st.dataframe(working_rows, use_container_width=True, hide_index=True)
    else:
        st.caption(empty_message)


def render_result_table(
    title: str,
    result: dict[str, Any],
    caption: str | None = None,
    empty_message: str = "No records found.",
    limit: int | None = None,
) -> list[dict[str, Any]]:
    if not result.get("ok"):
        render_result_error(result, title)
        return []
    rows = rows_from_result(result)
    render_table(title, rows, caption=caption, empty_message=empty_message, limit=limit)
    return rows


def render_metric_grid(items: list[tuple[str, Any]]) -> None:
    if not items:
        return
    width = 4 if len(items) >= 4 else len(items)
    for start in range(0, len(items), width):
        chunk = items[start : start + width]
        cols = st.columns(len(chunk))
        for col, (label, value) in zip(cols, chunk):
            with col:
                col.metric(label, value)


def render_text_briefs(
    title: str,
    rows: list[dict[str, Any]],
    title_key: str,
    body_key: str,
    meta_keys: list[str] | None = None,
    empty_message: str = "No narrative records available.",
) -> None:
    st.markdown(f"#### {title}")
    if not rows:
        st.caption(empty_message)
        return

    for row in rows:
        header = escape(str(row.get(title_key) or "Untitled"))
        body = escape(str(row.get(body_key) or "No narrative available."))
        meta_parts = []
        for key in meta_keys or []:
            value = row.get(key)
            if value not in (None, "", "N/A"):
                meta_parts.append(f"{key.replace('_', ' ').title()}: {value}")
        meta_text = " | ".join(meta_parts)
        st.markdown(f'<div class="tn-brief"><strong>{header}</strong></div>', unsafe_allow_html=True)
        if meta_text:
            st.caption(meta_text)
        st.write(body)


def render_hero(title: str, subtitle: str, eyebrow: str, chips: list[str] | None = None) -> None:
    chip_markup = ""
    if chips:
        chip_markup = '<div class="tn-chip-row">' + "".join(
            f'<span class="tn-chip">{escape(chip)}</span>' for chip in chips if chip
        ) + "</div>"
    st.markdown(
        f"""
        <div class="tn-hero">
            <div class="tn-eyebrow">{escape(eyebrow)}</div>
            <h1 class="tn-title">{escape(title)}</h1>
            <div class="tn-subtitle">{escape(subtitle)}</div>
            {chip_markup}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_inline_note(text: str) -> None:
    st.markdown(f'<div class="tn-inline-note">{escape(text)}</div>', unsafe_allow_html=True)


def build_case_option_map(case_rows: list[dict[str, Any]]) -> dict[str, int]:
    options: dict[str, int] = {}
    for row in case_rows:
        case_id = to_optional_int(str(row.get("id", "")))
        if case_id is None:
            continue
        title = str(row.get("title") or f"Case {case_id}")
        district = str(row.get("district") or "Unknown")
        status = str(row.get("status") or "open")
        options[f"{case_id} | {title} | {district} | {status}"] = case_id
    return options


def build_district_options(
    me_payload: dict[str, Any],
    performance_rows: list[dict[str, Any]],
    case_rows: list[dict[str, Any]],
) -> list[str]:
    role = str(me_payload.get("role") or "")
    district = str(me_payload.get("district") or "").strip()
    if role == "district_sp" and district:
        return [district]

    options = {DEFAULT_DISTRICT_SCOPE}
    for row in performance_rows:
        value = str(row.get("district") or "").strip()
        if value:
            options.add(value)
    for row in case_rows:
        value = str(row.get("district") or "").strip()
        if value:
            options.add(value)
    return [DEFAULT_DISTRICT_SCOPE] + sorted(option for option in options if option != DEFAULT_DISTRICT_SCOPE)


def get_dashboard_summary() -> dict[str, Any]:
    result = call_with_alternatives(["/dashboard/summary", "/dashboard", "/metrics/summary", "/summary"])
    if result.get("ok") and isinstance(result.get("data"), dict):
        return result["data"]
    return {}


def run_action_and_refresh(path: str, payload: dict[str, Any] | None = None, success_message: str = "Action completed.") -> None:
    result = api_post(path, payload)
    if result.get("ok"):
        st.success(success_message)
        st.rerun()
    else:
        st.error("Action failed.")
        data = result.get("data")
        if isinstance(data, dict):
            st.json(data)
        else:
            st.write(data)


def render_login_gate() -> None:
    render_hero(
        "TN Police Intelligence Platform",
        "Analyst-grade operational workspace for command, fusion, dossier, judicial, and export flows.",
        eyebrow="Secure Analyst Access",
        chips=["Secure sign-in", "Unified command workspace"],
    )

    left, right = st.columns([1.05, 0.95])
    with left:
        st.markdown("### Login")
        username = st.text_input("Username", value="admin_tn", key="login_username")
        password = st.text_input("Password", type="password", value="admin123", key="login_password")
        if st.button("Sign In", use_container_width=True, key="login_submit"):
            with st.spinner("Establishing secure session..."):
                result = request_login(get_api_url(), username, password, timeout=REQUEST_TIMEOUT)
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

    with right:
        st.markdown("### Demo Credentials")
        st.code(DEMO_CREDENTIALS)
        render_inline_note("Initial sign-in may take up to a minute while platform services initialize.")

    st.stop()


def render_global_header(
    me_payload: dict[str, Any],
    dashboard_summary: dict[str, Any],
    district_scope: str,
    selected_case_id: int | None,
) -> None:
    role = str(me_payload.get("role") or st.session_state.get("role") or "unknown")
    district = str(me_payload.get("district") or st.session_state.get("district") or "statewide")
    chips = [
        f"Role: {role}",
        f"User: {st.session_state.get('username', 'unknown')}",
        f"District scope: {district_scope}",
        f"Case focus: {selected_case_id if selected_case_id is not None else 'none'}",
    ]
    render_hero(
        "TN Police Intelligence Platform",
        "Mission control, entity fusion, dossiering, district command, watchlists, judicial chain, and export operations.",
        eyebrow="Analyst Operations Fabric",
        chips=chips,
    )
    render_metric_grid(
        [
            ("Open Cases", dashboard_summary.get("open_cases", "-")),
            ("Active Alerts", dashboard_summary.get("active_alerts", dashboard_summary.get("alerts_open", "-"))),
            ("Watchlists", dashboard_summary.get("watchlists_active", "-")),
            ("Evidence Items", dashboard_summary.get("evidence_attachments", "-")),
            ("SLA Breaches", dashboard_summary.get("sla_breached_cases", "-")),
            ("District Lens", district or "statewide"),
        ]
    )


def render_mission_control(district_scope: str, current_role: str) -> None:
    params = compact_params({"district": None if district_scope == DEFAULT_DISTRICT_SCOPE else district_scope})
    result = api_get("/operations/command-center", params=params or None)
    if not result.get("ok") or not isinstance(result.get("data"), dict):
        render_result_error(result, "Mission Control")
        return

    payload = result["data"]
    overview = payload.get("overview", {})
    briefing = payload.get("daily_briefing", {})

    render_hero(
        "Mission Control",
        str(briefing.get("headline") or "Operational pressure, hotspots, queues, and graph signals aligned in one command surface."),
        eyebrow="Strategic Command",
        chips=[
            f"Scope: {overview.get('district_scope', district_scope)}",
            f"Queued tasks: {overview.get('queued_tasks', 0)}",
            f"Fusion clusters: {overview.get('fusion_clusters', 0)}",
            f"Overloaded officers: {overview.get('overloaded_officers', 0)}",
        ],
    )

    render_metric_grid(
        [
            ("Active Cases", overview.get("active_cases", 0)),
            ("Active Alerts", overview.get("active_alerts", 0)),
            ("SLA Breaches", overview.get("breached_sla_cases", 0)),
            ("Complaints (7d)", overview.get("complaints_7d", 0)),
            ("Queued Tasks", overview.get("queued_tasks", 0)),
            ("In Progress", overview.get("in_progress_tasks", 0)),
            ("Queued Notifications", overview.get("queued_notifications", 0)),
            ("Fusion Clusters", overview.get("fusion_clusters", 0)),
        ]
    )

    if current_role == "admin":
        admin_left, admin_right = st.columns(2)
        with admin_left:
            if st.button("Recompute anomaly model", use_container_width=True, key="admin_recompute_anomalies"):
                run_action_and_refresh("/admin/recompute-anomalies", success_message="Anomaly scoring recomputed.")
        with admin_right:
            if st.button("Dispatch queued notifications", use_container_width=True, key="admin_dispatch_notifications"):
                run_action_and_refresh("/admin/dispatch-notifications", success_message="Queued notifications dispatched.")

    brief_col, pressure_col = st.columns([0.95, 1.05])
    with brief_col:
        st.markdown("#### Daily Intelligence Brief")
        st.caption(f"Generated at: {briefing.get('generated_at', 'n/a')}")
        sections = briefing.get("sections") or []
        if sections:
            for section in sections:
                st.markdown(f"- {section}")
        else:
            st.caption("No briefing sections available.")
        render_table(
            "Recent Briefings",
            payload_to_rows(payload.get("recent_briefings")),
            caption="Published briefings and registry entries for leadership context.",
            limit=5,
        )

    with pressure_col:
        render_table(
            "District Pressure",
            payload_to_rows(payload.get("district_pressure")),
            caption="Districts ranked by breached SLA, active alerts, and open-case load.",
            limit=5,
        )
        render_table(
            "Command Board",
            payload_to_rows(payload.get("command_board")),
            caption="Current command events, risk posture, and coordination notes.",
            limit=5,
        )

    top_left, top_right = st.columns(2)
    with top_left:
        render_table(
            "War Room Snapshots",
            payload_to_rows(payload.get("war_room_snapshots")),
            caption="Snapshot labels and command summaries from active war-room states.",
            limit=5,
        )
        render_table(
            "Patrol Gaps",
            payload_to_rows(payload.get("patrol_gaps")),
            caption="Lowest coverage beats with backlog and open-incident strain.",
            limit=5,
        )
    with top_right:
        render_table(
            "Hotspot Forecasts",
            payload_to_rows(payload.get("hotspot_forecasts")),
            caption="Highest forecast-score zones with recommended operational action.",
            limit=5,
        )
        render_table(
            "Notification Queue",
            payload_to_rows(payload.get("notification_queue")),
            caption="Queued notifications pending dispatch.",
            limit=5,
        )

    lower_left, lower_right = st.columns(2)
    with lower_left:
        render_table(
            "Suspect Focus",
            payload_to_rows(payload.get("suspect_focus")),
            caption="Highest-threat dossiers by alert load and linked-case pressure.",
            limit=5,
        )
        render_table(
            "Officer Workload",
            payload_to_rows(payload.get("officer_workload")),
            caption="Frontline workload and capacity view for balancing command demand.",
            limit=8,
        )
    with lower_right:
        render_table(
            "Fusion Cluster Summary",
            payload_to_rows(payload.get("fusion_cluster_summary")),
            caption="Cluster membership and signal strength for cross-case convergence.",
            limit=5,
        )
        render_table(
            "Graph Insights",
            payload_to_rows(payload.get("graph_insights")),
            caption="Highest-scoring graph insights available in the current scope.",
            limit=5,
        )

    render_table(
        "Task Queue",
        payload_to_rows(payload.get("task_queue")),
        caption="Queued and in-progress operational tasks surfaced from the command center.",
        limit=8,
    )


def render_geo_command(district_scope: str) -> None:
    render_hero(
        "Geo Command",
        "Statewide Tamil Nadu district visibility, CCTV deployment planning, and police-station lookout circles aligned in one geospatial command surface.",
        eyebrow="Statewide Geospatial Intelligence",
        chips=[
            "Visible to every logged-in role",
            "All 38 Tamil Nadu districts",
            "CCTV and station-circle overlays",
        ],
    )
    render_inline_note(
        "Statewide district visibility is available to all authenticated users. Use the district detail lens to inspect station concentration, CCTV reinforcement options, and police-station lookout circles."
    )

    control_left, control_mid, control_right = st.columns([1.1, 0.9, 1.0])
    with control_left:
        category_filter = st.text_input("Incident category filter", key="geo_category_filter")
    with control_mid:
        source_type = st.selectbox("Source type", ["all", "synthetic_demo", "public"], index=0, key="geo_source_type")
    with control_right:
        min_anomaly = st.slider("Minimum anomaly", 0.0, 1.0, 0.0, 0.05, key="geo_min_anomaly")

    heatmap_params = compact_params(
        {
            "category": category_filter or None,
            "source_type": None if source_type == "all" else source_type,
            "min_anomaly": min_anomaly,
        }
    )

    district_heatmap_result = api_get("/geo/district-heatmap", params=heatmap_params or None)
    district_heatmap_rows = rows_from_result(district_heatmap_result)
    district_map_rows = build_district_map_rows(district_heatmap_rows)
    statewide_station_heatmap_result = api_get("/geo/station-heatmap", params=heatmap_params or None)
    statewide_station_heatmap_rows = rows_from_result(statewide_station_heatmap_result)
    statewide_station_map_rows = build_station_map_rows(statewide_station_heatmap_rows, DEFAULT_DISTRICT_SCOPE)

    available_districts = [str(row.get("district")) for row in district_map_rows if row.get("district")]
    if district_scope != DEFAULT_DISTRICT_SCOPE and district_scope in available_districts:
        detail_district = district_scope
        st.caption(f"District detail is pinned to `{district_scope}` by your current workspace scope.")
    else:
        default_district = None
        if district_heatmap_rows:
            top_row = max(district_heatmap_rows, key=lambda row: to_float(row.get("intensity")))
            default_district = str(top_row.get("district") or "")
        if not default_district and available_districts:
            default_district = available_districts[0]
        detail_district = st.selectbox(
            "District detail lens",
            available_districts,
            index=available_districts.index(default_district) if default_district in available_districts else 0,
            key="geo_detail_district",
        ) if available_districts else None

    station_heatmap_result = api_get(
        "/geo/station-heatmap",
        params=compact_params({**heatmap_params, "district": detail_district}) or None,
    )
    station_heatmap_rows = rows_from_result(station_heatmap_result)
    station_map_rows = build_station_map_rows(station_heatmap_rows, detail_district or district_scope)

    incidents_result = api_get(
        "/incidents",
        params=compact_params({**heatmap_params, "district": detail_district}) or None,
    )
    incident_rows = rows_from_result(incidents_result)
    statewide_geofence_rows = rows_from_result(api_get("/geo/geofence-alerts"))
    geofence_result = api_get(
        "/geo/geofence-alerts",
        params=compact_params({"district": detail_district}) or None,
    )
    geofence_rows = rows_from_result(geofence_result)
    statewide_hotspot_rows = rows_from_result(api_get("/hotspot-forecasts"))
    statewide_patrol_rows = rows_from_result(api_get("/patrol-coverage"))
    detail_hotspot_rows = rows_from_result(
        api_get("/hotspot-forecasts", params=compact_params({"district": detail_district}) or None)
    )
    detail_patrol_rows = rows_from_result(
        api_get("/patrol-coverage", params=compact_params({"district": detail_district}) or None)
    )

    selected_district_map_rows = build_district_map_rows(district_heatmap_rows, selected_district=detail_district)
    cctv_district_rows = build_cctv_district_rows(
        district_map_rows,
        statewide_geofence_rows,
        statewide_hotspot_rows,
        statewide_patrol_rows,
    )
    cctv_station_rows = build_cctv_station_rows(station_map_rows)
    statewide_circle_rows = build_police_circle_rows(statewide_station_map_rows)
    detail_circle_rows = build_police_circle_rows(station_map_rows)
    total_incidents = sum(to_int(row.get("incident_count")) for row in district_map_rows)
    max_intensity = max((to_float(row.get("intensity")) for row in district_map_rows), default=0.0)
    active_geofences = sum(1 for row in geofence_rows if str(row.get("active")).lower() == "yes")
    total_recommended_cameras = sum(to_int(row.get("recommended_cameras")) for row in cctv_district_rows)
    render_metric_grid(
        [
            ("Districts Mapped", len(district_map_rows)),
            ("Police Station Circles", len(statewide_circle_rows)),
            ("District Incidents", total_incidents),
            ("Peak District Intensity", round(max_intensity, 2)),
            ("Recommended CCTV Units", total_recommended_cameras),
            ("Detail District", detail_district or "N/A"),
            ("Stations Visible", len(station_map_rows)),
            ("Filtered Incidents", len(incident_rows)),
            ("Geofence Alerts", len(geofence_rows)),
            ("Active Geofences", active_geofences),
        ]
    )

    tabs = st.tabs(["Situation", "CCTV Coverage", "Police Circles"])
    with tabs[0]:
        map_left, map_right = st.columns([1.18, 0.82])
        with map_left:
            render_geo_html(
                build_geo_svg(
                    "Tamil Nadu District Situation Map",
                    "Every district is visible here, with intensity driven by incident volume, severity, and anomaly score.",
                    selected_district_map_rows,
                    point_label_key="district",
                    selected_label=detail_district,
                    intensity_key="intensity",
                    value_key="incident_count",
                ),
                height=920,
            )
        with map_right:
            station_subtitle = (
                f"Station view for {detail_district}."
                if detail_district
                else "Select a district to inspect station-level disposition."
            )
            if station_map_rows:
                render_geo_html(
                    build_geo_svg(
                        "District Station Disposition",
                        station_subtitle,
                        station_map_rows,
                        point_label_key="station_name",
                        intensity_key="intensity",
                        value_key="incident_count",
                        height=700,
                    ),
                    height=830,
                )
            else:
                render_inline_note("Station map data is not available for the current detail district.")

        lower_left, lower_right = st.columns(2)
        with lower_left:
            render_table(
                "District Intensity Table",
                sorted(district_map_rows, key=lambda row: to_float(row.get("intensity")), reverse=True),
                caption="All Tamil Nadu districts ranked by current operational intensity.",
                limit=38,
            )
            render_table(
                "Station Disposition",
                sorted(station_map_rows, key=lambda row: to_float(row.get("intensity")), reverse=True),
                caption="Station-level incident and anomaly signal inside the selected district lens.",
                limit=20,
            )
        with lower_right:
            render_table(
                "Recent Incidents",
                incident_rows,
                caption="Filtered incidents for the current detail district and analytic filter set.",
                limit=20,
            )
            render_table(
                "Geofence Alerts",
                geofence_rows,
                caption="Configured geofence zones and threshold states for the detail district.",
                limit=16,
            )
            render_table(
                "Hotspot Forecasts",
                detail_hotspot_rows,
                caption="Forecast zones requiring forward surveillance and patrol attention inside the detail district.",
                limit=10,
            )
            render_table(
                "Patrol Coverage Gaps",
                detail_patrol_rows,
                caption="Lowest-coverage beats and backlog pressure inside the detail district.",
                limit=10,
            )

    with tabs[1]:
        render_inline_note(
            "CCTV planning is derived from district intensity, anomaly load, hotspot forecasts, geofence zones, and patrol gaps. These are deployment recommendations rather than claims of live camera access."
        )
        cctv_left, cctv_right = st.columns([1.14, 0.86])
        with cctv_left:
            render_geo_html(
                build_geo_svg(
                    "Statewide CCTV Prioritization Map",
                    "Districts are sized by recommended CCTV reinforcement volume and colored by surveillance pressure.",
                    cctv_district_rows,
                    point_label_key="district",
                    selected_label=detail_district,
                    intensity_key="surveillance_score",
                    value_key="recommended_cameras",
                    coverage_key="recommended_cameras",
                ),
                height=920,
            )
        with cctv_right:
            if cctv_station_rows:
                render_geo_html(
                    build_geo_svg(
                        "District CCTV Package Map",
                        f"Recommended camera package and coverage ring for {detail_district}.",
                        cctv_station_rows,
                        point_label_key="station_name",
                        intensity_key="intensity",
                        value_key="recommended_cameras",
                        coverage_key="coverage_circle_km",
                        height=700,
                    ),
                    height=830,
                )
            else:
                render_inline_note("District CCTV package planning appears once station activity is available in the selected district.")

        cctv_lower_left, cctv_lower_right = st.columns(2)
        with cctv_lower_left:
            render_table(
                "Statewide CCTV Deployment Matrix",
                cctv_district_rows,
                caption="District-level CCTV reinforcement options across Tamil Nadu, including PTZ, dome, ANPR, and mobile tower recommendations.",
                limit=38,
            )
        with cctv_lower_right:
            render_table(
                "District Camera Packages",
                cctv_station_rows,
                caption="Station-level packages for the selected district, including watch posture and blind-spot risk.",
                limit=20,
            )

    with tabs[2]:
        render_inline_note(
            "Coverage circles represent lookout and response radii around police stations. They are operational watch zones, not exact legal jurisdiction boundaries."
        )
        circle_left, circle_right = st.columns([1.12, 0.88])
        with circle_left:
            render_geo_html(
                build_geo_svg(
                    "Tamil Nadu Police Station Coverage Circles",
                    "Every seeded station is plotted statewide, with the outer ring indicating recommended lookout radius.",
                    statewide_circle_rows,
                    point_label_key="station_name",
                    intensity_key="intensity",
                    value_key="incident_count",
                    coverage_key="lookout_radius_km",
                    height=760,
                    label_stride=5,
                ),
                height=900,
            )
        with circle_right:
            if detail_circle_rows:
                render_geo_html(
                    build_geo_svg(
                        "District Lookout Circles",
                        f"Coverage circles for the {detail_district} station network.",
                        detail_circle_rows,
                        point_label_key="station_name",
                        intensity_key="intensity",
                        value_key="incident_count",
                        coverage_key="lookout_radius_km",
                        height=700,
                    ),
                    height=830,
                )
            else:
                render_inline_note("District lookout circles will appear when station-level reference data is available.")

        circle_lower_left, circle_lower_right = st.columns(2)
        with circle_lower_left:
            render_table(
                "Statewide Police Circle Registry",
                statewide_circle_rows,
                caption="All Tamil Nadu station circles with lookout radius, priority, and station focus.",
                limit=76,
            )
        with circle_lower_right:
            render_table(
                "Detail District Circles",
                detail_circle_rows,
                caption="Lookout circles for the selected district.",
                limit=20,
            )


def render_fusion_center(district_scope: str, selected_case_id: int | None) -> None:
    district_param = None if district_scope == DEFAULT_DISTRICT_SCOPE else district_scope
    params = compact_params({"district": district_param, "case_id": selected_case_id})
    cluster_summary_result = api_get("/fusion/cluster-summary")
    cluster_result = api_get("/fusion/clusters", params=params or None)
    suspect_result = api_get("/suspect-dossiers", params=compact_params({"district": district_param}) or None)
    insight_result = api_get("/graph/insights", params=params or None)
    similarity_result = api_get("/similarity-hits")

    cluster_summary_rows = rows_from_result(cluster_summary_result)
    if district_param:
        cluster_summary_rows = [
            row for row in cluster_summary_rows if district_param in str(row.get("districts", ""))
        ]

    cluster_rows = rows_from_result(cluster_result)
    suspect_rows = rows_from_result(suspect_result)
    insight_rows = rows_from_result(insight_result)
    similarity_rows = rows_from_result(similarity_result)

    render_hero(
        "Fusion Center",
        "Cross-case signals, entity overlap, graph indicators, and suspect dossiers aligned in a common analytic lane.",
        eyebrow="Entity and Pattern Convergence",
        chips=[
            f"District: {district_scope}",
            f"Case focus: {selected_case_id if selected_case_id is not None else 'all'}",
            f"Clusters: {len(cluster_rows)}",
            f"Insights: {len(insight_rows)}",
        ],
    )

    top_similarity = max((to_float(row.get("similarity_score")) for row in similarity_rows), default=0.0)
    render_metric_grid(
        [
            ("Cluster Members", len(cluster_rows)),
            ("Cluster Summaries", len(cluster_summary_rows)),
            ("Suspect Dossiers", len(suspect_rows)),
            ("Graph Insights", len(insight_rows)),
            ("Top Similarity", round(top_similarity, 3)),
        ]
    )

    left, right = st.columns([1.05, 0.95])
    with left:
        render_table(
            "Cluster Summary",
            cluster_summary_rows,
            caption="Each fusion cluster with member count, average signal, district spread, and case count.",
            limit=10,
        )
        render_table(
            "Cluster Members",
            cluster_rows,
            caption="Raw fusion members and signal strength contributing to the current convergence picture.",
            limit=18,
        )
        render_table(
            "Similarity Hits",
            similarity_rows,
            caption="Cross-object similarity signals ranked by model score and rationale.",
            limit=12,
        )
    with right:
        render_table(
            "Suspect Dossiers",
            suspect_rows,
            caption="Threat-level dossiers with linked-case and alert pressure context.",
            limit=10,
        )
        render_table(
            "Graph Insights",
            insight_rows,
            caption="Narrative graph findings surfaced for the current district or case scope.",
            limit=10,
        )

    if selected_case_id is not None:
        graph_result = api_get(f"/graph/case/{selected_case_id}")
        if graph_result.get("ok") and isinstance(graph_result.get("data"), dict):
            graph_payload = graph_result["data"]
            snapshot = graph_payload.get("snapshot") or {}
            render_metric_grid(
                [
                    ("Graph Nodes", len(payload_to_rows(graph_payload.get("nodes")))),
                    ("Graph Edges", len(payload_to_rows(graph_payload.get("edges")))),
                    ("Timeline Events", graph_payload.get("timeline_count", 0)),
                    ("Risk Density", snapshot.get("risk_density", "N/A")),
                    ("Complaint Links", graph_payload.get("complaint_links", 0)),
                ]
            )
            graph_left, graph_right = st.columns(2)
            with graph_left:
                render_table(
                    "Graph Nodes",
                    payload_to_rows(graph_payload.get("nodes")),
                    caption="Case, entity, and evidence nodes participating in the current graph snapshot.",
                    limit=20,
                )
            with graph_right:
                render_table(
                    "Graph Edges",
                    payload_to_rows(graph_payload.get("edges")),
                    caption="Relationship edges and case-evidence links in the current graph projection.",
                    limit=30,
                )
        else:
            render_result_error(graph_result, "Case Graph Snapshot")

    with st.expander("Save fusion bookmark", expanded=False):
        note = st.text_area("Bookmark note", key="fusion_bookmark_note")
        if st.button("Save fusion bookmark", key="fusion_bookmark_submit", use_container_width=True):
            object_ref = f"fusion:{district_param or 'statewide'}:{selected_case_id or 'all'}"
            payload = {
                "bookmark_type": "fusion",
                "object_ref": object_ref,
                "title": f"Fusion snapshot | {district_param or 'statewide'} | case {selected_case_id or 'all'}",
                "notes": note or None,
            }
            run_action_and_refresh("/bookmarks", payload=payload, success_message="Fusion bookmark saved.")


def render_case_dossier(selected_case_id: int | None) -> None:
    if selected_case_id is None:
        render_inline_note("Pick a case from the sidebar to open the full dossier workspace.")
        return

    result = api_get(f"/cases/{selected_case_id}/dossier")
    if not result.get("ok") or not isinstance(result.get("data"), dict):
        render_result_error(result, "Case Dossier")
        return

    payload = result["data"]
    case_row = payload.get("case", {})
    summary = payload.get("summary", {})
    graph_payload = payload.get("graph", {}) if isinstance(payload.get("graph"), dict) else {}
    snapshot = graph_payload.get("snapshot") or {}

    render_hero(
        f"Case Dossier #{case_row.get('id', selected_case_id)}",
        str(case_row.get("summary") or "Integrated case narrative, evidence chain, judicial movement, and graph context."),
        eyebrow="Operational Case File",
        chips=[
            f"District: {case_row.get('district', 'unknown')}",
            f"Priority: {case_row.get('priority', 'unknown')}",
            f"Status: {case_row.get('status', 'unknown')}",
            f"SLA: {case_row.get('sla_status', 'unknown')}",
        ],
    )

    render_metric_grid(
        [
            ("Timeline Events", summary.get("timeline_events", 0)),
            ("Evidence Items", summary.get("evidence_items", 0)),
            ("Linked Complaints", summary.get("linked_complaints", 0)),
            ("Watchlist Hits", summary.get("watchlist_hits", 0)),
            ("Tasks", summary.get("tasks", 0)),
            ("Hearings", summary.get("hearings", 0)),
            ("Documents", summary.get("documents", 0)),
            ("Graph Nodes", summary.get("graph_nodes", 0)),
            ("Graph Edges", summary.get("graph_edges", 0)),
            ("Risk Density", summary.get("risk_density", snapshot.get("risk_density", "N/A"))),
        ]
    )

    action_tabs = st.tabs(["Comment", "Assign", "Evidence", "Bookmark"])
    with action_tabs[0]:
        with st.form("case_comment_form"):
            comment_text = st.text_area("Case comment", height=120)
            if st.form_submit_button("Add comment", use_container_width=True):
                run_action_and_refresh(
                    f"/cases/{selected_case_id}/comments",
                    payload={"comment_text": comment_text},
                    success_message="Comment added to case timeline.",
                )
    with action_tabs[1]:
        with st.form("case_assign_form"):
            assignee_username = st.text_input("Assignee username")
            role_label = st.text_input("Role label")
            if st.form_submit_button("Assign case", use_container_width=True):
                run_action_and_refresh(
                    f"/cases/{selected_case_id}/assign",
                    payload={"assignee_username": assignee_username, "role_label": role_label or None},
                    success_message="Case assignment recorded.",
                )
    with action_tabs[2]:
        with st.form("case_evidence_form"):
            file_name = st.text_input("File name")
            storage_ref = st.text_input("Storage reference")
            attachment_type = st.selectbox("Attachment type", ["document", "image", "device_dump", "statement"], index=0)
            notes = st.text_area("Evidence notes", height=120)
            if st.form_submit_button("Add evidence", use_container_width=True):
                run_action_and_refresh(
                    f"/cases/{selected_case_id}/evidence",
                    payload={
                        "attachment_type": attachment_type,
                        "file_name": file_name,
                        "storage_ref": storage_ref,
                        "notes": notes or None,
                    },
                    success_message="Evidence entry added.",
                )
    with action_tabs[3]:
        with st.form("case_bookmark_form"):
            bookmark_note = st.text_area("Bookmark note", height=120)
            if st.form_submit_button("Save dossier bookmark", use_container_width=True):
                run_action_and_refresh(
                    "/bookmarks",
                    payload={
                        "bookmark_type": "case",
                        "object_ref": f"case:{selected_case_id}",
                        "title": f"Case {selected_case_id} | {case_row.get('title', 'Investigation dossier')}",
                        "notes": bookmark_note or None,
                    },
                    success_message="Dossier bookmark saved.",
                )

    dossier_tabs = st.tabs(
        ["Overview", "Timeline and Comms", "Evidence and Docs", "Graph and Watchlists", "Judicial Chain"]
    )
    with dossier_tabs[0]:
        overview_left, overview_right = st.columns([1.05, 0.95])
        with overview_left:
            render_table(
                "Linked Complaints",
                payload_to_rows(payload.get("linked_complaints")),
                caption="Complaint records linked into the current case package.",
                limit=12,
            )
            render_text_briefs(
                "Narrative Briefs",
                payload_to_rows(payload.get("narrative_briefs")),
                title_key="title",
                body_key="body",
                meta_keys=["brief_type", "created_by"],
            )
            render_text_briefs(
                "Timeline Digests",
                payload_to_rows(payload.get("timeline_digests")),
                title_key="digest_title",
                body_key="digest_body",
                meta_keys=["generated_by"],
            )
        with overview_right:
            render_table(
                "Task Queue",
                payload_to_rows(payload.get("tasks")),
                caption="Tasks linked to this case across operational units.",
                limit=10,
            )
            render_table(
                "Bookmarks",
                payload_to_rows(payload.get("bookmarks")),
                caption="Saved analyst bookmarks for this dossier.",
                limit=10,
            )

    with dossier_tabs[1]:
        render_table(
            "Timeline",
            payload_to_rows(payload.get("timeline")),
            caption="Chronological case activity trail with event type and actor attribution.",
            limit=40,
        )
        render_table(
            "Comments",
            payload_to_rows(payload.get("comments")),
            caption="Analyst and operational comments attached to the case.",
            limit=20,
        )
        render_table(
            "Assignments",
            payload_to_rows(payload.get("assignments")),
            caption="Assignment history and investigative ownership trail.",
            limit=20,
        )

    with dossier_tabs[2]:
        evidence_left, evidence_right = st.columns(2)
        with evidence_left:
            render_table(
                "Evidence Registry",
                payload_to_rows(payload.get("evidence")),
                caption="Registered evidence objects, attachment type, and storage reference.",
                limit=20,
            )
            render_table(
                "Evidence Integrity",
                payload_to_rows(payload.get("evidence_integrity")),
                caption="Integrity checks, checksum stubs, and verification notes.",
                limit=20,
            )
        with evidence_right:
            render_table(
                "Documents",
                payload_to_rows(payload.get("documents")),
                caption="Document intake ledger for this case.",
                limit=20,
            )
            document_entities = payload.get("document_entities") if isinstance(payload.get("document_entities"), dict) else {}
            if document_entities:
                st.markdown("#### Extracted Document Entities")
                for document_id, entities in document_entities.items():
                    with st.expander(f"Document {document_id}", expanded=False):
                        render_table(
                            f"Entities for Document {document_id}",
                            payload_to_rows(entities),
                            empty_message="No entities extracted for this document.",
                        )

    with dossier_tabs[3]:
        render_metric_grid(
            [
                ("Graph Nodes", len(payload_to_rows(graph_payload.get("nodes")))),
                ("Graph Edges", len(payload_to_rows(graph_payload.get("edges")))),
                ("Complaint Links", graph_payload.get("complaint_links", 0)),
                ("Timeline Count", graph_payload.get("timeline_count", 0)),
                ("Risk Density", snapshot.get("risk_density", "N/A")),
            ]
        )
        graph_left, graph_right = st.columns(2)
        with graph_left:
            render_table(
                "Graph Nodes",
                payload_to_rows(graph_payload.get("nodes")),
                caption="Case, entity, and evidence nodes participating in the graph snapshot.",
                limit=24,
            )
        with graph_right:
            render_table(
                "Graph Edges",
                payload_to_rows(graph_payload.get("edges")),
                caption="Relationship edges and case-evidence links.",
                limit=32,
            )
        render_table(
            "Watchlist Hits",
            payload_to_rows(payload.get("watchlist_hits")),
            caption="Watchlist matches associated with this case scope.",
            limit=20,
        )

    with dossier_tabs[4]:
        chain_left, chain_right = st.columns(2)
        with chain_left:
            render_table(
                "Prosecution Packets",
                payload_to_rows(payload.get("prosecution_packets")),
                caption="Prosecution packet status and court alignment.",
                limit=20,
            )
            render_table(
                "Court Hearings",
                payload_to_rows(payload.get("court_hearings")),
                caption="Hearing schedule, stage, outcome, and next action.",
                limit=20,
            )
            render_table(
                "Court Packet Exports",
                payload_to_rows(payload.get("court_packet_exports")),
                caption="Generated court packet export history.",
                limit=20,
            )
        with chain_right:
            render_table(
                "Custody Logs",
                payload_to_rows(payload.get("custody_logs")),
                caption="Custody actions, locations, and officers involved.",
                limit=20,
            )
            render_table(
                "Medical Checks",
                payload_to_rows(payload.get("medical_checks")),
                caption="Medical checks and status for people linked to the case.",
                limit=20,
            )
            render_table(
                "Prison Movements",
                payload_to_rows(payload.get("prison_movements")),
                caption="Movement chain for detainees and escort units.",
                limit=20,
            )
            render_table(
                "Related Export Jobs",
                payload_to_rows(payload.get("export_jobs")),
                caption="Associated export jobs connected to this case object.",
                limit=20,
            )


def render_district_command(
    district_scope: str,
    me_payload: dict[str, Any],
    case_rows: list[dict[str, Any]],
) -> None:
    district_param = None if district_scope == DEFAULT_DISTRICT_SCOPE else district_scope
    performance_result = api_get("/districts/performance-summary")
    station_result = api_get("/districts/station-dashboard", params=compact_params({"district": district_param}) or None)
    workload_summary_result = api_get("/officers/workload-summary")
    workload_result = api_get("/officers/workload", params=compact_params({"district": district_param}) or None)
    briefing_result = api_get("/briefings", params=compact_params({"district": district_param}) or None)
    daily_brief_result = api_get("/briefings/daily-summary")
    patrol_result = api_get("/patrol-coverage", params=compact_params({"district": district_param}) or None)
    hotspot_result = api_get("/hotspot-forecasts", params=compact_params({"district": district_param}) or None)
    permissions_result = api_get("/permissions/matrix")

    performance_rows = rows_from_result(performance_result)
    station_rows = rows_from_result(station_result)
    workload_rows = rows_from_result(workload_result)
    briefing_rows = rows_from_result(briefing_result)
    patrol_rows = rows_from_result(patrol_result)
    hotspot_rows = rows_from_result(hotspot_result)
    permissions_rows = rows_from_result(permissions_result)
    workload_summary = workload_summary_result.get("data") if workload_summary_result.get("ok") and isinstance(workload_summary_result.get("data"), dict) else {}
    daily_brief = daily_brief_result.get("data") if daily_brief_result.get("ok") and isinstance(daily_brief_result.get("data"), dict) else {}

    if district_param:
        summary_row = next((row for row in performance_rows if str(row.get("district")) == district_param), {})
        scoped_case_count = sum(1 for row in case_rows if str(row.get("district")) == district_param)
    else:
        summary_row = {
            "stations": sum(to_int(row.get("stations")) for row in performance_rows),
            "open_cases": sum(to_int(row.get("open_cases")) for row in performance_rows),
            "breached_sla_cases": sum(to_int(row.get("breached_sla_cases")) for row in performance_rows),
            "active_alerts": sum(to_int(row.get("active_alerts")) for row in performance_rows),
            "complaints_7d": sum(to_int(row.get("complaints_7d")) for row in performance_rows),
        }
        scoped_case_count = len(case_rows)

    render_hero(
        "District Command",
        "Station performance, officer strain, permissions, patrol coverage, and briefing posture aligned for district leadership.",
        eyebrow="District Performance and Control",
        chips=[
            f"Scope: {district_scope}",
            f"Stations: {summary_row.get('stations', 0)}",
            f"Scoped cases: {scoped_case_count}",
            f"Overloaded officers: {workload_summary.get('overloaded_officers', 0)}",
        ],
    )

    render_metric_grid(
        [
            ("Stations", summary_row.get("stations", 0)),
            ("Open Cases", summary_row.get("open_cases", 0)),
            ("SLA Breaches", summary_row.get("breached_sla_cases", 0)),
            ("Active Alerts", summary_row.get("active_alerts", 0)),
            ("Complaints (7d)", summary_row.get("complaints_7d", 0)),
            ("Officer Count", workload_summary.get("officer_count", 0)),
            ("Avg Capacity Index", workload_summary.get("avg_capacity_index", "N/A")),
            ("Overloaded Officers", workload_summary.get("overloaded_officers", 0)),
        ]
    )

    left, right = st.columns([1.1, 0.9])
    with left:
        render_table(
            "District Performance Summary",
            performance_rows,
            caption="District-wide case, alert, and SLA leaderboard.",
            limit=12,
        )
        render_table(
            "Station Dashboard",
            station_rows,
            caption="Station-level KPI surface from seeded district command indicators.",
            limit=20,
        )
    with right:
        st.markdown("#### Daily Briefing Summary")
        st.caption(f"Generated at: {daily_brief.get('generated_at', 'n/a')}")
        st.write(str(daily_brief.get("headline") or "No daily district summary available."))
        for section in daily_brief.get("sections") or []:
            st.markdown(f"- {section}")
        render_table(
            "Briefing Registry",
            briefing_rows,
            caption="Recent briefing packages and registry records for the selected scope.",
            limit=10,
        )

    lower_left, lower_right = st.columns(2)
    with lower_left:
        render_table(
            "Officer Workload",
            workload_rows,
            caption="Officer capacity and queue-pressure indicators for balancing assignments.",
            limit=18,
        )
        render_table(
            "Patrol Coverage",
            patrol_rows,
            caption="Coverage ratios, backlog, and incident pressure by beat.",
            limit=15,
        )
    with lower_right:
        render_table(
            "Hotspot Forecasts",
            hotspot_rows,
            caption="Forecasted district hotspots with recommended actions.",
            limit=12,
        )
        role_options = sorted({str(row.get("role_name")) for row in permissions_rows if row.get("role_name")})
        selected_role = st.selectbox(
            "Permission lens",
            role_options or [str(me_payload.get("role") or "viewer")],
            key="district_permission_lens",
        )
        effective_result = api_get(f"/permissions/effective/{selected_role}")
        effective_rows = rows_from_result(effective_result)
        render_table(
            f"Effective Permissions | {selected_role}",
            effective_rows,
            caption="Role-specific effective permissions from the seeded permission matrix.",
        )
        with st.expander("Full permission matrix", expanded=False):
            render_table(
                "Permissions Matrix",
                permissions_rows,
                empty_message="No permission matrix records available.",
            )


def render_watchlists_and_alerts(district_scope: str, selected_case_id: int | None) -> None:
    district_param = None if district_scope == DEFAULT_DISTRICT_SCOPE else district_scope
    alerts_result = api_get("/alerts")
    watchlists_result = api_get("/watchlists")
    hits_result = api_get("/watchlist-hits", params=compact_params({"case_id": selected_case_id}) or None)
    geofence_result = api_get("/geo/geofence-alerts", params=compact_params({"district": district_param}) or None)
    entities_result = api_get("/graph/entities")

    alerts_rows = rows_from_result(alerts_result)
    if district_param:
        alerts_rows = [row for row in alerts_rows if str(row.get("district")) == district_param]
    watchlist_rows = rows_from_result(watchlists_result)
    if district_param:
        watchlist_rows = [row for row in watchlist_rows if str(row.get("district")) in {"N/A", district_param}]
    hit_rows = rows_from_result(hits_result)
    geofence_rows = rows_from_result(geofence_result)
    entity_rows = rows_from_result(entities_result)
    if district_param:
        entity_rows = [row for row in entity_rows if str(row.get("district")) == district_param]

    render_hero(
        "Watchlists and Alerts",
        "Alert volume, watchlist pressure, geofence triggers, and entity search fused into one analyst lane.",
        eyebrow="Risk Monitoring and Detection",
        chips=[
            f"District: {district_scope}",
            f"Case focus: {selected_case_id if selected_case_id is not None else 'all'}",
            f"Alerts: {len(alerts_rows)}",
            f"Watchlists: {len(watchlist_rows)}",
        ],
    )

    active_geofences = sum(1 for row in geofence_rows if str(row.get("active")).lower() == "yes")
    render_metric_grid(
        [
            ("Alerts", len(alerts_rows)),
            ("Watchlists", len(watchlist_rows)),
            ("Watchlist Hits", len(hit_rows)),
            ("Active Geofences", active_geofences),
            ("Entities", len(entity_rows)),
        ]
    )

    creation_left, creation_right = st.columns([1.05, 0.95])
    with creation_left:
        render_table(
            "Alerts",
            alerts_rows,
            caption="Current alerts in the selected scope, including severity and message summary.",
            limit=18,
        )
        render_table(
            "Watchlist Hits",
            hit_rows,
            caption="Watchlist matches, hit reason, and confidence for the selected scope.",
            limit=18,
        )
    with creation_right:
        render_table(
            "Watchlists",
            watchlist_rows,
            caption="Watchlist registry with rationale, district, and ownership context.",
            limit=18,
        )
        render_table(
            "Geofence Alerts",
            geofence_rows,
            caption="Configured geofences and threshold triggers across active zones.",
            limit=18,
        )

    with st.expander("Create watchlist", expanded=False):
        with st.form("watchlist_create_form"):
            name = st.text_input("Watchlist name")
            create_district = st.text_input("District", value="" if district_scope == DEFAULT_DISTRICT_SCOPE else district_scope)
            watch_type = st.selectbox("Watch type", ["person", "device", "vehicle", "entity"], index=0)
            rationale = st.text_area("Rationale", height=110)
            if st.form_submit_button("Create watchlist", use_container_width=True):
                run_action_and_refresh(
                    "/watchlists",
                    payload={
                        "name": name,
                        "district": create_district or None,
                        "watch_type": watch_type,
                        "rationale": rationale or None,
                    },
                    success_message="Watchlist created.",
                )

    search_left, search_right = st.columns(2)
    with search_left:
        query = st.text_input("Graph search", key="watchlist_graph_search")
        if st.button("Run linked search", key="watchlist_graph_search_submit", use_container_width=True):
            search_result = api_get(
                "/graph/complaint-case-search",
                params=compact_params({"q": query.strip(), "district": district_param}) or None,
            )
            if search_result.get("ok") and isinstance(search_result.get("data"), dict):
                payload = search_result["data"]
                for section in [
                    "complaints",
                    "cases",
                    "entities",
                    "watchlists",
                    "complaint_case_links",
                    "watchlist_hits",
                ]:
                    render_table(
                        section.replace("_", " ").title(),
                        payload_to_rows(payload.get(section)),
                        empty_message="No matches in this section.",
                    )
            else:
                render_result_error(search_result, "Graph Search")
    with search_right:
        render_table(
            "Entities",
            entity_rows,
            caption="Entity registry rows surfaced in the current district scope.",
            limit=20,
        )


def render_department_comms(
    district_scope: str,
    selected_case_id: int | None,
    me_payload: dict[str, Any],
) -> None:
    district_param = None if district_scope == DEFAULT_DISTRICT_SCOPE else district_scope
    current_username = str(me_payload.get("username") or st.session_state.get("username") or "unknown")
    directory_rows = rows_from_result(api_get("/personnel/directory"))
    message_rows = rows_from_result(
        api_get(
            "/internal-comms/messages",
            params=compact_params(
                {
                    "district": district_param,
                    "recipient_username": current_username,
                }
            ) or None,
        )
    )
    room_rows = summarize_comms_rooms(message_rows)
    available_rooms = sorted({str(row.get("room_name")) for row in room_rows if row.get("room_name")})
    direct_count = sum(1 for row in message_rows if row.get("recipient_username") not in (None, "", "N/A"))
    ack_required_count = sum(1 for row in message_rows if str(row.get("ack_required")).lower() == "yes")

    render_hero(
        "Department Comms",
        "Operational coordination channels for statewide command, district rooms, case escalation, and direct personnel messaging.",
        eyebrow="Internal Coordination Fabric",
        chips=[
            f"User: {current_username}",
            f"District lens: {district_scope}",
            f"Rooms: {len(room_rows)}",
            f"Messages: {len(message_rows)}",
        ],
    )

    render_metric_grid(
        [
            ("Personnel Visible", len(directory_rows)),
            ("Active Rooms", len(room_rows)),
            ("Messages Loaded", len(message_rows)),
            ("Direct Messages", direct_count),
            ("Ack Required", ack_required_count),
            ("Case Lens", selected_case_id if selected_case_id is not None else "None"),
        ]
    )

    room_filter_left, room_filter_mid, room_filter_right = st.columns([1.0, 1.0, 0.9])
    with room_filter_left:
        room_filter = st.selectbox("Room filter", ["All Rooms"] + available_rooms, key="comms_room_filter")
    with room_filter_mid:
        scope_filter = st.selectbox("Channel scope", ["all", "statewide", "district", "direct", "case"], key="comms_scope_filter")
    with room_filter_right:
        priority_filter = st.selectbox("Priority", ["all", "routine", "medium", "high", "critical"], key="comms_priority_filter")

    filtered_message_rows = []
    for row in message_rows:
        if room_filter != "All Rooms" and str(row.get("room_name")) != room_filter:
            continue
        if scope_filter != "all" and str(row.get("channel_scope")) != scope_filter:
            continue
        if priority_filter != "all" and str(row.get("priority")) != priority_filter:
            continue
        filtered_message_rows.append(row)

    tabs = st.tabs(["Live Feed", "Compose", "Directory"])
    with tabs[0]:
        feed_left, feed_right = st.columns([1.18, 0.82])
        with feed_left:
            render_message_feed(filtered_message_rows)
        with feed_right:
            render_table(
                "Coordination Rooms",
                room_rows,
                caption="Current rooms, latest activity, and priority-message counts for the filtered comms surface.",
                limit=12,
            )
            render_table(
                "Personnel Posture",
                directory_rows,
                caption="Visible personnel roster with role, district scope, and status posture.",
                limit=12,
            )

    with tabs[1]:
        room_choices = ["State Command Net", "Cyber Fusion Desk", "District Coordination", "Case Coordination", "Direct Coordination", "Custom Room"]
        recipient_choices = ["None"] + [str(row.get("username")) for row in directory_rows if row.get("username") != current_username]
        with st.form("department_comms_form"):
            selected_room = st.selectbox("Room", room_choices, index=0)
            custom_room = st.text_input("Custom room name", value="", disabled=selected_room != "Custom Room")
            channel_scope = st.selectbox("Channel scope", ["statewide", "district", "direct", "case"], index=0)
            compose_district = st.text_input(
                "District",
                value="" if district_scope == DEFAULT_DISTRICT_SCOPE else district_scope,
                disabled=channel_scope not in {"district", "case"},
            )
            recipient_username = st.selectbox(
                "Direct recipient",
                recipient_choices,
                index=0,
                disabled=channel_scope != "direct",
            )
            priority = st.selectbox("Priority", ["routine", "medium", "high", "critical"], index=0)
            ack_required = st.checkbox("Acknowledge required")
            message_text = st.text_area("Message", height=140, placeholder="Type the operational instruction, coordination note, or escalation context.")
            if st.form_submit_button("Send message", use_container_width=True):
                room_name = custom_room.strip() if selected_room == "Custom Room" else selected_room
                payload = {
                    "room_name": room_name or "State Command Net",
                    "message_text": message_text,
                    "channel_scope": channel_scope,
                    "district": compose_district if channel_scope in {"district", "case"} else None,
                    "recipient_username": None if recipient_username == "None" or channel_scope != "direct" else recipient_username,
                    "priority": priority,
                    "ack_required": ack_required,
                    "case_id": selected_case_id if channel_scope == "case" else None,
                }
                run_action_and_refresh(
                    "/internal-comms/messages",
                    payload=payload,
                    success_message="Department message sent.",
                )

    with tabs[2]:
        render_table(
            "Personnel Directory",
            directory_rows,
            caption="Department-visible personnel and their current coordination posture.",
            limit=20,
        )
        render_table(
            "Room Registry",
            room_rows,
            caption="Rooms currently in use, including latest sender, scope, and latest activity.",
            limit=20,
        )


def render_tasking_and_exports(district_scope: str, selected_case_id: int | None, current_role: str) -> None:
    district_param = None if district_scope == DEFAULT_DISTRICT_SCOPE else district_scope
    task_result = api_get("/tasks", params=compact_params({"district": district_param, "case_id": selected_case_id}) or None)
    notification_result = api_get("/notifications")
    export_result = api_get("/export-jobs")
    document_result = api_get("/documents", params=compact_params({"district": district_param, "case_id": selected_case_id}) or None)
    connector_result = api_get("/connectors")
    ingest_result = api_get("/ingest-queue")
    adapter_result = api_get("/adapter-stubs")
    audit_result = api_get("/audit")

    task_rows = rows_from_result(task_result)
    notification_rows = rows_from_result(notification_result)
    export_rows = rows_from_result(export_result)
    document_rows = rows_from_result(document_result)
    connector_rows = rows_from_result(connector_result)
    ingest_rows = rows_from_result(ingest_result)
    adapter_rows = rows_from_result(adapter_result)
    audit_rows = rows_from_result(audit_result) if audit_result.get("ok") else []

    render_hero(
        "Tasking and Exports",
        "Operational queues, notifications, exports, intake pipelines, and audit visibility for the live workspace.",
        eyebrow="Operational Fabric and Audit",
        chips=[
            f"District: {district_scope}",
            f"Case focus: {selected_case_id if selected_case_id is not None else 'all'}",
            f"Tasks: {len(task_rows)}",
            f"Exports: {len(export_rows)}",
        ],
    )

    queued_tasks = sum(1 for row in task_rows if str(row.get("status")).lower() == "queued")
    in_progress_tasks = sum(1 for row in task_rows if str(row.get("status")).lower() == "in_progress")
    queued_notifications = sum(1 for row in notification_rows if str(row.get("status")).lower() == "queued")
    render_metric_grid(
        [
            ("Queued Tasks", queued_tasks),
            ("In Progress Tasks", in_progress_tasks),
            ("Notifications", len(notification_rows)),
            ("Queued Notifications", queued_notifications),
            ("Documents", len(document_rows)),
            ("Export Jobs", len(export_rows)),
            ("Connector Registry", len(connector_rows)),
            ("Ingest Queue", len(ingest_rows)),
        ]
    )

    if current_role == "admin":
        if st.button("Dispatch notifications now", key="tasking_dispatch_notifications", use_container_width=True):
            run_action_and_refresh("/admin/dispatch-notifications", success_message="Queued notifications dispatched.")

    left, right = st.columns(2)
    with left:
        render_table(
            "Task Queue",
            task_rows,
            caption="Queued and in-progress tasks across the current workspace scope.",
            limit=20,
        )
        if task_rows:
            task_options = {
                f"Task {row.get('id')} | Case {row.get('case_id')} | {row.get('task_type')}": to_int(row.get("id"))
                for row in task_rows
                if row.get("id") not in (None, "N/A")
            }
            if task_options:
                selected_task_label = st.selectbox("Task execution lens", list(task_options.keys()), key="task_execution_lens")
                execution_result = api_get(f"/tasks/{task_options[selected_task_label]}/executions")
                render_result_table(
                    "Task Executions",
                    execution_result,
                    caption="Execution trail for the currently selected task.",
                    empty_message="No executions recorded for this task.",
                )
        render_table(
            "Notifications",
            notification_rows,
            caption="Notification events across channels, recipients, and related objects.",
            limit=20,
        )
    with right:
        render_table(
            "Export Jobs",
            export_rows,
            caption="Export job ledger including scope, format, status, and export reference.",
            limit=20,
        )
        render_table(
            "Documents",
            document_rows,
            caption="Document intake rows available for the selected district or case scope.",
            limit=20,
        )
        render_table(
            "Connector Registry",
            connector_rows,
            caption="Sanctioned connector registry with source type and access mode.",
            limit=16,
        )
        render_table(
            "Adapter Stubs",
            adapter_rows,
            caption="Adapter stubs, source hints, and latest probe status.",
            limit=16,
        )

    lower_left, lower_right = st.columns(2)
    with lower_left:
        render_table(
            "Ingest Queue",
            ingest_rows,
            caption="Incoming payload queue with processing timestamps where available.",
            limit=16,
        )
    with lower_right:
        if audit_result.get("ok"):
            render_table(
                "Audit Trail",
                audit_rows,
                caption="Recent audit entries visible to admin and district leadership roles.",
                limit=25,
            )
        else:
            render_result_error(audit_result, "Audit Trail")


def render_intake_and_search(
    district_scope: str,
    selected_case_id: int | None,
    case_rows: list[dict[str, Any]],
) -> None:
    complaint_result = api_get("/complaints")
    complaint_rows = rows_from_result(complaint_result)

    render_hero(
        "Intake and Search",
        "Create cases, submit complaints, link records, and run integrated search without leaving the workspace.",
        eyebrow="Operational Intake and Discovery",
        chips=[
            f"District scope: {district_scope}",
            f"Case focus: {selected_case_id if selected_case_id is not None else 'none'}",
            f"Case registry: {len(case_rows)}",
            f"Complaint registry: {len(complaint_rows)}",
        ],
    )

    tabs = st.tabs(["Create Case", "Complaint Intake", "Link Records", "Registry Search"])
    with tabs[0]:
        with st.form("create_case_form"):
            title = st.text_input("Case title")
            district = st.text_input("District", value="" if district_scope == DEFAULT_DISTRICT_SCOPE else district_scope)
            station_id = st.text_input("Station ID")
            priority = st.selectbox("Priority", ["low", "medium", "high", "critical"], index=1)
            summary = st.text_area("Case summary", height=120)
            if st.form_submit_button("Create case", use_container_width=True):
                payload = {
                    "title": title,
                    "district": district,
                    "station_id": to_optional_int(station_id),
                    "priority": priority,
                    "summary": summary or None,
                }
                run_action_and_refresh("/cases", payload=payload, success_message="Case created.")

    with tabs[1]:
        with st.form("create_complaint_form"):
            complainant_ref = st.text_input("Complainant reference")
            district = st.text_input("Complaint district", value="" if district_scope == DEFAULT_DISTRICT_SCOPE else district_scope)
            complaint_type = st.text_input("Complaint type")
            channel = st.selectbox("Channel", ["public_portal", "cyber_portal", "walkin", "synthetic_demo"], index=0)
            description = st.text_area("Complaint description", height=120)
            if st.form_submit_button("Submit complaint", use_container_width=True):
                payload = {
                    "district": district,
                    "complaint_type": complaint_type,
                    "channel": channel,
                    "complainant_ref": complainant_ref or None,
                    "description": description or None,
                }
                run_action_and_refresh("/complaints", payload=payload, success_message="Complaint submitted.")

    with tabs[2]:
        with st.form("link_record_form"):
            complaint_id = st.text_input("Complaint ID")
            case_id = st.text_input("Case ID", value=str(selected_case_id) if selected_case_id is not None else "")
            rationale = st.text_area("Link rationale", height=120)
            if st.form_submit_button("Create complaint-case link", use_container_width=True):
                payload = {
                    "complaint_id": to_optional_int(complaint_id),
                    "case_id": to_optional_int(case_id),
                    "rationale": rationale or None,
                }
                run_action_and_refresh("/complaint-case-links", payload=payload, success_message="Complaint linked to case.")

    with tabs[3]:
        query = st.text_input("Search complaint, case, entity, or watchlist", key="global_search_query")
        if st.button("Run integrated search", key="global_search_submit", use_container_width=True):
            params = compact_params(
                {
                    "q": query.strip(),
                    "district": None if district_scope == DEFAULT_DISTRICT_SCOPE else district_scope,
                }
            )
            search_result = api_get("/graph/complaint-case-search", params=params or None)
            if search_result.get("ok") and isinstance(search_result.get("data"), dict):
                payload = search_result["data"]
                for section in [
                    "complaints",
                    "cases",
                    "entities",
                    "watchlists",
                    "complaint_case_links",
                    "watchlist_hits",
                ]:
                    render_table(
                        section.replace("_", " ").title(),
                        payload_to_rows(payload.get(section)),
                        empty_message="No rows returned for this section.",
                    )
            else:
                render_result_error(search_result, "Integrated Search")

    left, right = st.columns(2)
    with left:
        render_table(
            "Case Registry",
            case_rows,
            caption="Case catalog available to the current logged-in user.",
            limit=25,
        )
    with right:
        render_table(
            "Complaint Registry",
            complaint_rows,
            caption="Complaint intake ledger available for the current workspace.",
            limit=25,
        )


def render_explorer() -> None:
    endpoint_library = [
        "/dashboard/summary",
        "/operations/command-center",
        "/fusion/clusters",
        "/watchlists",
        "/tasks",
        "/export-jobs",
        "/briefings/daily-summary",
    ]

    render_hero(
        "Explorer",
        "Direct API inspection workspace for payload validation, endpoint discovery, and troubleshooting.",
        eyebrow="Low-Level Interface",
        chips=["Manual endpoint control", "Ad hoc params", "Payload inspection"],
    )
    endpoint = st.text_input("Endpoint", value="/dashboard/summary")
    query_string = st.text_input("Query params as key=value,key2=value2", value="")
    st.caption("Suggested endpoints: " + ", ".join(endpoint_library))

    params: dict[str, str] = {}
    if query_string.strip():
        for part in query_string.split(","):
            if "=" in part:
                key, value = part.split("=", 1)
                params[key.strip()] = value.strip()

    if st.button("Call endpoint", use_container_width=True):
        result = api_get(endpoint, params=compact_params(params) or None)
        if result.get("ok"):
            st.success(f"HTTP {result.get('status_code')}")
        else:
            st.error(f"HTTP {result.get('status_code')}")
        data = result.get("data")
        if isinstance(data, dict):
            st.json(data)
        else:
            st.write(data)


with st.sidebar:
    st.caption("Demo credentials")
    st.code(DEMO_CREDENTIALS)

    if st.session_state.get("logged_in"):
        st.success(f"Logged in as {st.session_state.get('username', 'unknown')}")
        if st.button("Logout", use_container_width=True, key="sidebar_logout"):
            clear_login_state()
            st.rerun()


if not st.session_state.get("logged_in"):
    render_login_gate()


me_result = call_with_alternatives(["/auth/me", "/me"])
me_payload = me_result.get("data") if me_result.get("ok") and isinstance(me_result.get("data"), dict) else {}
dashboard_summary = get_dashboard_summary()
cases_result = api_get("/cases")
case_rows = rows_from_result(cases_result)
performance_rows = rows_from_result(api_get("/districts/performance-summary"))
case_option_map = build_case_option_map(case_rows)
district_options = build_district_options(me_payload, performance_rows, case_rows)
current_role = str(me_payload.get("role") or st.session_state.get("role") or "viewer")


with st.sidebar:
    district_scope = st.selectbox("District scope", district_options, key="sidebar_district_scope")
    case_focus_label = st.selectbox(
        "Case focus",
        [NO_CASE_LABEL] + list(case_option_map.keys()),
        key="sidebar_case_focus",
    )
    selected_case_id = None if case_focus_label == NO_CASE_LABEL else case_option_map.get(case_focus_label)
    workspace = st.radio(
        "Workspace",
        [
            "Mission Control",
            "Geo Command",
            "Fusion Center",
            "Case Dossier",
            "District Command",
            "Watchlists and Alerts",
            "Department Comms",
            "Tasking and Exports",
            "Intake and Search",
            "Explorer",
        ],
        key="sidebar_workspace",
    )


render_global_header(me_payload, dashboard_summary, district_scope, selected_case_id)


if workspace == "Mission Control":
    render_mission_control(district_scope, current_role)
elif workspace == "Geo Command":
    render_geo_command(district_scope)
elif workspace == "Fusion Center":
    render_fusion_center(district_scope, selected_case_id)
elif workspace == "Case Dossier":
    render_case_dossier(selected_case_id)
elif workspace == "District Command":
    render_district_command(district_scope, me_payload, case_rows)
elif workspace == "Watchlists and Alerts":
    render_watchlists_and_alerts(district_scope, selected_case_id)
elif workspace == "Department Comms":
    render_department_comms(district_scope, selected_case_id, me_payload)
elif workspace == "Tasking and Exports":
    render_tasking_and_exports(district_scope, selected_case_id, current_role)
elif workspace == "Intake and Search":
    render_intake_and_search(district_scope, selected_case_id, case_rows)
else:
    render_explorer()
