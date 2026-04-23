from __future__ import annotations

from collections import defaultdict
import csv
from itertools import combinations
import json
import math
import os
import time
from html import escape
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlencode, urlparse

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

        .tn-room-pill {
            display: inline-flex;
            align-items: center;
            gap: 0.45rem;
            border-radius: 999px;
            padding: 0.24rem 0.6rem;
            background: rgba(118, 183, 255, 0.12);
            color: #d9e9ff;
            border: 1px solid rgba(118, 183, 255, 0.2);
            font-size: 0.78rem;
            margin-left: 0.55rem;
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


def get_query_param(name: str) -> str | None:
    try:
        value = st.query_params.get(name)
    except Exception:
        return None
    if isinstance(value, list):
        return str(value[0]) if value else None
    if value in (None, ""):
        return None
    return str(value)


def set_query_param(name: str, value: str | None) -> None:
    try:
        current_value = get_query_param(name)
        if value in (None, ""):
            if current_value is not None:
                del st.query_params[name]
            return
        if current_value != str(value):
            st.query_params[name] = str(value)
    except Exception:
        return


def build_query_url(updates: dict[str, Any]) -> str:
    query_map: dict[str, str] = {}
    try:
        for key in st.query_params:
            value = st.query_params.get(key)
            if value not in (None, ""):
                query_map[str(key)] = str(value)
    except Exception:
        query_map = {}

    for key, value in updates.items():
        if value in (None, ""):
            query_map.pop(key, None)
        else:
            query_map[key] = str(value)

    encoded = urlencode(query_map)
    return f"?{encoded}" if encoded else "?"


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


def clamp_session_int(key: str, lower: int, upper: int, fallback: int) -> int:
    if upper < lower:
        return fallback
    raw_value = st.session_state.get(key, fallback)
    try:
        numeric_value = int(raw_value)
    except (TypeError, ValueError):
        numeric_value = fallback
    numeric_value = max(lower, min(upper, numeric_value))
    st.session_state[key] = numeric_value
    return numeric_value


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
    link_getter: Callable[[dict[str, Any]], str | None] | None = None,
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
        point_body = f"""
                {coverage_markup}
                <circle cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}" fill="{fill}" fill-opacity="0.88"
                    stroke="{stroke}" stroke-width="{stroke_width}">
                    <title>{escape(tooltip)}</title>
                </circle>
                {label_markup}
        """
        if link_getter:
            point_url = link_getter(row)
            if point_url:
                point_body = (
                    f'<a href="{escape(point_url, quote=True)}" target="_top" style="cursor:pointer;text-decoration:none;">'
                    f"{point_body}"
                    "</a>"
                )
        point_markup.append(
            f"""
            <g>
                {point_body}
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
    if hasattr(st, "html"):
        try:
            st.html(markup)
            return
        except Exception:
            pass
    components.html(markup, height=height, scrolling=False)


def build_flow_svg(
    title: str,
    subtitle: str,
    district_rows: list[dict[str, Any]],
    flow_rows: list[dict[str, Any]],
    selected_district: str | None = None,
    link_getter: Callable[[dict[str, Any]], str | None] | None = None,
) -> str:
    width = 980
    height = 760
    padding = 70
    if not district_rows:
        return '<div class="tn-inline-note">District flow data is not available for the current selection.</div>'

    district_lookup = {str(row.get("district")): row for row in district_rows if row.get("district")}
    all_lons = [coord[0] for coord in TN_STATE_OUTLINE] + [to_float(row.get("longitude")) for row in district_rows]
    all_lats = [coord[1] for coord in TN_STATE_OUTLINE] + [to_float(row.get("latitude")) for row in district_rows]
    min_lon, max_lon = min(all_lons), max(all_lons)
    min_lat, max_lat = min(all_lats), max(all_lats)

    outline_points = []
    for lon, lat in TN_STATE_OUTLINE:
        x, y = project_geo_point(lon, lat, min_lon, max_lon, min_lat, max_lat, width, height, padding)
        outline_points.append(f"{x:.1f},{y:.1f}")
    outline_markup = " ".join(outline_points)

    max_weight = max((to_float(row.get("flow_weight")) for row in flow_rows), default=1.0)
    flow_markup: list[str] = []
    for row in flow_rows:
        source = district_lookup.get(str(row.get("source_district")))
        target = district_lookup.get(str(row.get("target_district")))
        if not source or not target:
            continue
        x1, y1 = project_geo_point(to_float(source.get("longitude")), to_float(source.get("latitude")), min_lon, max_lon, min_lat, max_lat, width, height, padding)
        x2, y2 = project_geo_point(to_float(target.get("longitude")), to_float(target.get("latitude")), min_lon, max_lon, min_lat, max_lat, width, height, padding)
        weight = to_float(row.get("flow_weight"))
        ratio = weight / max(max_weight, 1.0)
        stroke_width = 1.6 + (ratio * 6.5)
        highlighted = selected_district and selected_district in {row.get("source_district"), row.get("target_district")}
        stroke = "rgba(255, 140, 66, 0.82)" if highlighted else "rgba(118, 183, 255, 0.38)"
        tooltip = (
            f"{row.get('source_district')} -> {row.get('target_district')} | "
            f"Flow weight: {row.get('flow_weight')} | Clusters: {row.get('cluster_count')} | Cases: {row.get('case_count')}"
        )
        flow_markup.append(
            f"""
            <line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}"
                stroke="{stroke}" stroke-width="{stroke_width:.1f}" stroke-linecap="round">
                <title>{escape(tooltip)}</title>
            </line>
            """
        )

    point_markup: list[str] = []
    max_intensity = max((to_float(row.get("intensity")) for row in district_rows), default=1.0)
    for row in district_rows:
        label = str(row.get("district") or "Unknown")
        x, y = project_geo_point(to_float(row.get("longitude")), to_float(row.get("latitude")), min_lon, max_lon, min_lat, max_lat, width, height, padding)
        intensity = to_float(row.get("intensity"))
        ratio = intensity / max(max_intensity, 1.0)
        radius = 7 + (ratio * 12)
        stroke = "#ffe2bf" if selected_district and label == selected_district else "#d8e6ff"
        point_body = (
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}" fill="{interpolate_color((71, 122, 199), (255, 140, 66), ratio)}" '
            f'fill-opacity="0.92" stroke="{stroke}" stroke-width="2.2"><title>{escape(label)}</title></circle>'
            f'<text x="{x:.1f}" y="{(y - radius - 7):.1f}" text-anchor="middle" '
            'style="fill:#eaf2ff;font-size:11px;font-family:system-ui,sans-serif;font-weight:600;">'
            f"{escape(label)}</text>"
        )
        if link_getter:
            point_url = link_getter(row)
            if point_url:
                point_body = (
                    f'<a href="{escape(point_url, quote=True)}" target="_top" style="cursor:pointer;text-decoration:none;">'
                    f"{point_body}</a>"
                )
        point_markup.append(f"<g>{point_body}</g>")

    return f"""
    <div style="border:1px solid rgba(92,116,151,0.35);border-radius:24px;padding:1rem 1rem 0.7rem 1rem;
        background:linear-gradient(180deg, rgba(15,25,40,0.98), rgba(10,18,28,0.96));">
        <div style="display:flex;justify-content:space-between;align-items:flex-end;gap:1rem;flex-wrap:wrap;">
            <div>
                <div style="color:#76b7ff;font-size:0.82rem;letter-spacing:0.12em;text-transform:uppercase;font-weight:700;">{escape(title)}</div>
                <div style="color:#97a8c4;font-size:0.95rem;margin-top:0.25rem;">{escape(subtitle)}</div>
            </div>
            <div style="color:#97a8c4;font-size:0.82rem;">Click district nodes to pin drill-down. Hover flow lines for movement details.</div>
        </div>
        <svg viewBox="0 0 {width} {height}" style="width:100%;height:auto;margin-top:0.8rem;">
            <polygon points="{outline_markup}" fill="rgba(118,183,255,0.04)"
                stroke="rgba(118,183,255,0.35)" stroke-width="3" />
            {"".join(flow_markup)}
            {"".join(point_markup)}
        </svg>
    </div>
    """


def build_route_svg(
    title: str,
    subtitle: str,
    district_rows: list[dict[str, Any]],
    route_rows: list[dict[str, Any]],
    selected_route_id: str | None = None,
    selected_district: str | None = None,
    link_getter: Callable[[dict[str, Any]], str | None] | None = None,
) -> str:
    width = 980
    height = 760
    padding = 70
    if not district_rows:
        return '<div class="tn-inline-note">Route overlay data is not available for the current selection.</div>'

    district_lookup = {str(row.get("district")): row for row in district_rows if row.get("district")}
    all_lons = [coord[0] for coord in TN_STATE_OUTLINE] + [to_float(row.get("longitude")) for row in district_rows]
    all_lats = [coord[1] for coord in TN_STATE_OUTLINE] + [to_float(row.get("latitude")) for row in district_rows]
    min_lon, max_lon = min(all_lons), max(all_lons)
    min_lat, max_lat = min(all_lats), max(all_lats)

    outline_points = []
    for lon, lat in TN_STATE_OUTLINE:
        x, y = project_geo_point(lon, lat, min_lon, max_lon, min_lat, max_lat, width, height, padding)
        outline_points.append(f"{x:.1f},{y:.1f}")
    outline_markup = " ".join(outline_points)

    route_markup: list[str] = []
    route_color_map = {"suspect": "#ff8c42", "vehicle": "#6bc7ff"}
    for row in route_rows:
        if selected_route_id and row.get("route_id") != selected_route_id:
            continue
        points = []
        for district in row.get("districts") or []:
            district_row = district_lookup.get(str(district))
            if not district_row:
                continue
            x, y = project_geo_point(to_float(district_row.get("longitude")), to_float(district_row.get("latitude")), min_lon, max_lon, min_lat, max_lat, width, height, padding)
            points.append((x, y, district))
        if len(points) < 2:
            continue
        polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y, _ in points)
        route_type = str(row.get("route_type") or "suspect")
        color = route_color_map.get(route_type, "#ff8c42")
        width_scale = 2.0 + (to_float(row.get("risk_score")) / 8.0)
        tooltip = f"{row.get('subject_label')} | {' -> '.join(str(d) for d in row.get('districts', []))} | Risk: {row.get('risk_score')}"
        route_markup.append(
            f"""
            <g>
                <polyline points="{polyline}" fill="none" stroke="{color}" stroke-width="{width_scale:.1f}"
                    stroke-linecap="round" stroke-linejoin="round" opacity="0.82">
                    <title>{escape(tooltip)}</title>
                </polyline>
                {''.join(
                    f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6.2" fill="{color}" stroke="#f8fbff" stroke-width="1.2"></circle>'
                    for x, y, _ in points
                )}
            </g>
            """
        )

    point_markup: list[str] = []
    for row in district_rows:
        label = str(row.get("district") or "Unknown")
        x, y = project_geo_point(to_float(row.get("longitude")), to_float(row.get("latitude")), min_lon, max_lon, min_lat, max_lat, width, height, padding)
        point_stroke = "#ffe2bf" if selected_district and label == selected_district else "#8cbcff"
        point_body = (
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5.6" fill="rgba(118, 183, 255, 0.32)" stroke="{point_stroke}" stroke-width="1.4"></circle>'
        )
        if link_getter:
            point_url = link_getter(row)
            if point_url:
                point_body = (
                    f'<a href="{escape(point_url, quote=True)}" target="_top" style="cursor:pointer;text-decoration:none;">'
                    f"{point_body}</a>"
                )
        point_markup.append(f"<g>{point_body}</g>")

    return f"""
    <div style="border:1px solid rgba(92,116,151,0.35);border-radius:24px;padding:1rem 1rem 0.7rem 1rem;
        background:linear-gradient(180deg, rgba(15,25,40,0.98), rgba(10,18,28,0.96));">
        <div style="display:flex;justify-content:space-between;align-items:flex-end;gap:1rem;flex-wrap:wrap;">
            <div>
                <div style="color:#76b7ff;font-size:0.82rem;letter-spacing:0.12em;text-transform:uppercase;font-weight:700;">{escape(title)}</div>
                <div style="color:#97a8c4;font-size:0.95rem;margin-top:0.25rem;">{escape(subtitle)}</div>
            </div>
            <div style="color:#97a8c4;font-size:0.82rem;">Suspect tracks are orange. Vehicle corridors are blue.</div>
        </div>
        <svg viewBox="0 0 {width} {height}" style="width:100%;height:auto;margin-top:0.8rem;">
            <polygon points="{outline_markup}" fill="rgba(118,183,255,0.04)"
                stroke="rgba(118,183,255,0.35)" stroke-width="3" />
            {"".join(route_markup)}
            {"".join(point_markup)}
        </svg>
    </div>
    """


def build_regular_polygon_points(cx: float, cy: float, radius: float, sides: int = 6, rotation_deg: float = -30.0) -> str:
    points = []
    for index in range(sides):
        angle = math.radians(rotation_deg + ((360 / sides) * index))
        x = cx + (math.cos(angle) * radius)
        y = cy + (math.sin(angle) * radius)
        points.append(f"{x:.1f},{y:.1f}")
    return " ".join(points)


def build_operational_polygon_svg(
    title: str,
    subtitle: str,
    district_rows: list[dict[str, Any]],
    checkpoint_rows: list[dict[str, Any]],
    selected_district: str | None = None,
    link_getter: Callable[[dict[str, Any]], str | None] | None = None,
) -> str:
    width = 980
    height = 760
    padding = 70
    if not district_rows:
        return '<div class="tn-inline-note">Operational polygon data is not available for the current selection.</div>'

    all_lons = [coord[0] for coord in TN_STATE_OUTLINE] + [to_float(row.get("longitude")) for row in district_rows]
    all_lats = [coord[1] for coord in TN_STATE_OUTLINE] + [to_float(row.get("latitude")) for row in district_rows]
    min_lon, max_lon = min(all_lons), max(all_lons)
    min_lat, max_lat = min(all_lats), max(all_lats)
    outline_points = []
    for lon, lat in TN_STATE_OUTLINE:
        x, y = project_geo_point(lon, lat, min_lon, max_lon, min_lat, max_lat, width, height, padding)
        outline_points.append(f"{x:.1f},{y:.1f}")
    outline_markup = " ".join(outline_points)

    max_intensity = max((to_float(row.get("intensity")) for row in district_rows), default=1.0)
    polygon_markup: list[str] = []
    for row in district_rows:
        district = str(row.get("district") or "Unknown")
        x, y = project_geo_point(to_float(row.get("longitude")), to_float(row.get("latitude")), min_lon, max_lon, min_lat, max_lat, width, height, padding)
        intensity = to_float(row.get("intensity"))
        radius = 20 + ((intensity / max(max_intensity, 1.0)) * 30)
        polygon_points = build_regular_polygon_points(x, y, radius)
        fill = interpolate_color((36, 93, 168), (255, 140, 66), intensity / max(max_intensity, 1.0))
        stroke = "#ffe2bf" if selected_district == district else "rgba(216, 230, 255, 0.72)"
        body = (
            f'<polygon points="{polygon_points}" fill="{fill}" fill-opacity="0.20" stroke="{stroke}" stroke-width="2.2">'
            f'<title>{escape(district)} | Intensity: {row.get("intensity")} | Incidents: {row.get("incident_count")}</title>'
            '</polygon>'
            f'<text x="{x:.1f}" y="{(y + 4):.1f}" text-anchor="middle" '
            'style="fill:#eaf2ff;font-size:10.6px;font-family:system-ui,sans-serif;font-weight:700;">'
            f"{escape(district)}</text>"
        )
        if link_getter:
            polygon_url = link_getter(row)
            if polygon_url:
                body = f'<a href="{escape(polygon_url, quote=True)}" target="_top" style="text-decoration:none;">{body}</a>'
        polygon_markup.append(f"<g>{body}</g>")

    checkpoint_markup: list[str] = []
    for row in checkpoint_rows:
        latitude = row.get("latitude")
        longitude = row.get("longitude")
        if latitude in (None, "", "N/A") or longitude in (None, "", "N/A"):
            continue
        x, y = project_geo_point(to_float(longitude), to_float(latitude), min_lon, max_lon, min_lat, max_lat, width, height, padding)
        status = str(row.get("status") or "planned")
        color = "#ff8c42" if status in {"active", "deployed"} else "#76b7ff" if status == "planned" else "#b0bccf"
        checkpoint_markup.append(
            f"""
            <g>
                <polygon points="{build_regular_polygon_points(x, y, 9, sides=4, rotation_deg=45)}" fill="{color}" fill-opacity="0.88"
                    stroke="#f8fbff" stroke-width="1.2">
                    <title>{escape(str(row.get('checkpoint_name') or 'Checkpoint'))} | Status: {escape(status)} | Unit: {escape(str(row.get('assigned_unit') or 'Unassigned'))}</title>
                </polygon>
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
            <div style="color:#97a8c4;font-size:0.82rem;">District polygons are operational sectors. Diamonds are checkpoints.</div>
        </div>
        <svg viewBox="0 0 {width} {height}" style="width:100%;height:auto;margin-top:0.8rem;">
            <polygon points="{outline_markup}" fill="rgba(118,183,255,0.04)"
                stroke="rgba(118,183,255,0.35)" stroke-width="3" />
            {"".join(polygon_markup)}
            {"".join(checkpoint_markup)}
        </svg>
    </div>
    """


def build_boundary_layer_svg(
    title: str,
    subtitle: str,
    boundary_rows: list[dict[str, Any]],
    geofence_rows: list[dict[str, Any]],
    checkpoint_rows: list[dict[str, Any]],
    selected_district: str | None = None,
    link_getter: Callable[[dict[str, Any]], str | None] | None = None,
) -> str:
    width = 980
    height = 760
    padding = 70
    if not boundary_rows and not geofence_rows:
        return '<div class="tn-inline-note">Boundary and geofence layers are not available for the current selection.</div>'

    geo_points = list(TN_STATE_OUTLINE)
    for row in boundary_rows + geofence_rows:
        for point in row.get("points") or []:
            geo_points.append((to_float(point.get("longitude")), to_float(point.get("latitude"))))
    min_lon = min(point[0] for point in geo_points)
    max_lon = max(point[0] for point in geo_points)
    min_lat = min(point[1] for point in geo_points)
    max_lat = max(point[1] for point in geo_points)

    outline_points = []
    for lon, lat in TN_STATE_OUTLINE:
        x, y = project_geo_point(lon, lat, min_lon, max_lon, min_lat, max_lat, width, height, padding)
        outline_points.append(f"{x:.1f},{y:.1f}")
    outline_markup = " ".join(outline_points)

    boundary_palette = {
        "district": ("rgba(118,183,255,0.12)", "rgba(118,183,255,0.54)"),
        "station": ("rgba(71,216,154,0.12)", "rgba(71,216,154,0.58)"),
        "patrol_sector": ("rgba(255,140,66,0.12)", "rgba(255,140,66,0.54)"),
    }
    boundary_markup: list[str] = []
    for row in boundary_rows:
        points = row.get("points") or []
        if not points:
            continue
        projected = []
        for point in points:
            x, y = project_geo_point(
                to_float(point.get("longitude")),
                to_float(point.get("latitude")),
                min_lon,
                max_lon,
                min_lat,
                max_lat,
                width,
                height,
                padding,
            )
            projected.append(f"{x:.1f},{y:.1f}")
        boundary_type = str(row.get("boundary_type") or "district")
        fill, stroke = boundary_palette.get(boundary_type, ("rgba(157,176,204,0.1)", "rgba(216,230,255,0.45)"))
        highlighted = selected_district and str(row.get("district")) == selected_district
        body = (
            f'<polygon points="{" ".join(projected)}" fill="{fill}" stroke="{"#ffe2bf" if highlighted else stroke}" '
            f'stroke-width="{"2.8" if highlighted else "1.6"}"><title>{escape(str(row.get("zone_name") or "Boundary"))}</title></polygon>'
        )
        centroid_lat = to_float(row.get("centroid_latitude"))
        centroid_lon = to_float(row.get("centroid_longitude"))
        if centroid_lat or centroid_lon:
            x, y = project_geo_point(centroid_lon, centroid_lat, min_lon, max_lon, min_lat, max_lat, width, height, padding)
            body += (
                f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="middle" '
                'style="fill:#eaf2ff;font-size:10.5px;font-family:system-ui,sans-serif;font-weight:650;">'
                f"{escape(str(row.get('zone_name') or 'Boundary')[:28])}</text>"
            )
        if link_getter:
            boundary_url = link_getter(row)
            if boundary_url:
                body = f'<a href="{escape(boundary_url, quote=True)}" target="_top" style="text-decoration:none;">{body}</a>'
        boundary_markup.append(f"<g>{body}</g>")

    geofence_markup: list[str] = []
    for row in geofence_rows:
        points = row.get("points") or []
        if not points:
            continue
        projected = []
        for point in points:
            x, y = project_geo_point(
                to_float(point.get("longitude")),
                to_float(point.get("latitude")),
                min_lon,
                max_lon,
                min_lat,
                max_lat,
                width,
                height,
                padding,
            )
            projected.append(f"{x:.1f},{y:.1f}")
        geofence_markup.append(
            f'<polygon points="{" ".join(projected)}" fill="rgba(255,140,66,0.08)" stroke="rgba(255,140,66,0.72)" stroke-width="1.8" stroke-dasharray="7 5">'
            f'<title>{escape(str(row.get("zone_name") or "Geofence"))} | {escape(str(row.get("geofence_type") or "watch_zone"))}</title></polygon>'
        )

    checkpoint_markup: list[str] = []
    for row in checkpoint_rows:
        latitude = row.get("latitude")
        longitude = row.get("longitude")
        if latitude in (None, "", "N/A") or longitude in (None, "", "N/A"):
            continue
        x, y = project_geo_point(to_float(longitude), to_float(latitude), min_lon, max_lon, min_lat, max_lat, width, height, padding)
        color = "#ff8c42" if str(row.get("status") or "").lower() in {"active", "deployed"} else "#76b7ff"
        checkpoint_markup.append(
            f'<polygon points="{build_regular_polygon_points(x, y, 8.5, sides=4, rotation_deg=45)}" fill="{color}" stroke="#f8fbff" stroke-width="1.1">'
            f'<title>{escape(str(row.get("checkpoint_name") or "Checkpoint"))}</title></polygon>'
        )

    return f"""
    <div style="border:1px solid rgba(92,116,151,0.35);border-radius:24px;padding:1rem 1rem 0.7rem 1rem;
        background:linear-gradient(180deg, rgba(15,25,40,0.98), rgba(10,18,28,0.96));">
        <div style="display:flex;justify-content:space-between;align-items:flex-end;gap:1rem;flex-wrap:wrap;">
            <div>
                <div style="color:#76b7ff;font-size:0.82rem;letter-spacing:0.12em;text-transform:uppercase;font-weight:700;">{escape(title)}</div>
                <div style="color:#97a8c4;font-size:0.95rem;margin-top:0.25rem;">{escape(subtitle)}</div>
            </div>
            <div style="color:#97a8c4;font-size:0.82rem;">District, station, patrol, geofence, and checkpoint layers are stacked together.</div>
        </div>
        <svg viewBox="0 0 {width} {height}" style="width:100%;height:auto;margin-top:0.8rem;">
            <polygon points="{outline_markup}" fill="rgba(118,183,255,0.04)"
                stroke="rgba(118,183,255,0.35)" stroke-width="3" />
            {"".join(boundary_markup)}
            {"".join(geofence_markup)}
            {"".join(checkpoint_markup)}
        </svg>
    </div>
    """


def build_corridor_svg(
    title: str,
    subtitle: str,
    district_rows: list[dict[str, Any]],
    corridor_rows: list[dict[str, Any]],
    selected_district: str | None = None,
    link_getter: Callable[[dict[str, Any]], str | None] | None = None,
) -> str:
    width = 980
    height = 760
    padding = 70
    if not district_rows:
        return '<div class="tn-inline-note">Operational corridor data is not available for the current selection.</div>'

    geo_points = list(TN_STATE_OUTLINE)
    for row in district_rows:
        geo_points.append((to_float(row.get("longitude")), to_float(row.get("latitude"))))
    for row in corridor_rows:
        for point in row.get("points") or []:
            geo_points.append((to_float(point.get("longitude")), to_float(point.get("latitude"))))

    min_lon = min(point[0] for point in geo_points)
    max_lon = max(point[0] for point in geo_points)
    min_lat = min(point[1] for point in geo_points)
    max_lat = max(point[1] for point in geo_points)

    outline_points = []
    for lon, lat in TN_STATE_OUTLINE:
        x, y = project_geo_point(lon, lat, min_lon, max_lon, min_lat, max_lat, width, height, padding)
        outline_points.append(f"{x:.1f},{y:.1f}")
    outline_markup = " ".join(outline_points)

    district_markup: list[str] = []
    for row in district_rows:
        label = str(row.get("district") or "Unknown")
        x, y = project_geo_point(to_float(row.get("longitude")), to_float(row.get("latitude")), min_lon, max_lon, min_lat, max_lat, width, height, padding)
        point_stroke = "#ffe2bf" if selected_district and label == selected_district else "#8cbcff"
        point_body = (
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5.6" fill="rgba(118, 183, 255, 0.32)" stroke="{point_stroke}" stroke-width="1.4"></circle>'
            f'<text x="{x:.1f}" y="{(y - 10):.1f}" text-anchor="middle" style="fill:#cfe3ff;font-size:10px;font-family:system-ui,sans-serif;">{escape(label)}</text>'
        )
        if link_getter:
            point_url = link_getter(row)
            if point_url:
                point_body = f'<a href="{escape(point_url, quote=True)}" target="_top" style="text-decoration:none;">{point_body}</a>'
        district_markup.append(f"<g>{point_body}</g>")

    corridor_palette = {
        "high": "#ff8c42",
        "medium": "#76b7ff",
        "low": "#9db0cc",
    }
    corridor_markup: list[str] = []
    for row in corridor_rows:
        points = []
        for point in row.get("points") or []:
            x, y = project_geo_point(
                to_float(point.get("longitude")),
                to_float(point.get("latitude")),
                min_lon,
                max_lon,
                min_lat,
                max_lat,
                width,
                height,
                padding,
            )
            points.append((x, y, str(point.get("district") or "")))
        if len(points) < 2:
            continue
        polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y, _district in points)
        color = corridor_palette.get(str(row.get("surveillance_priority") or "medium").lower(), "#76b7ff")
        width_scale = 2.2 + (to_float(row.get("risk_score")) * 0.8)
        corridor_markup.append(
            f"""
            <g>
                <polyline points="{polyline}" fill="none" stroke="{color}" stroke-width="{width_scale:.1f}"
                    stroke-linecap="round" stroke-linejoin="round" opacity="0.86">
                    <title>{escape(str(row.get("corridor_name") or "Corridor"))} | Risk: {row.get("risk_score")} | Priority: {row.get("surveillance_priority")}</title>
                </polyline>
                {''.join(
                    f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6.2" fill="{color}" stroke="#f8fbff" stroke-width="1.2"></circle>'
                    for x, y, _district in points
                )}
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
            <div style="color:#97a8c4;font-size:0.82rem;">Orange corridors are high-priority. Blue corridors are active surveillance lanes.</div>
        </div>
        <svg viewBox="0 0 {width} {height}" style="width:100%;height:auto;margin-top:0.8rem;">
            <polygon points="{outline_markup}" fill="rgba(118,183,255,0.04)"
                stroke="rgba(118,183,255,0.35)" stroke-width="3" />
            {"".join(corridor_markup)}
            {"".join(district_markup)}
        </svg>
    </div>
    """


def maybe_send_presence_heartbeat(room_name: str, district_scope: str, status_label: str = "active") -> None:
    now = time.time()
    last_ping = float(st.session_state.get("presence_last_ping_ts", 0.0))
    last_room = str(st.session_state.get("presence_last_room", ""))
    last_district = str(st.session_state.get("presence_last_district", ""))
    payload_district = None if district_scope == DEFAULT_DISTRICT_SCOPE else district_scope
    if (now - last_ping) < 25 and room_name == last_room and str(payload_district or "") == last_district:
        return
    result = api_post(
        "/personnel/presence/heartbeat",
        payload={
            "room_name": room_name,
            "district": payload_district,
            "status_label": status_label,
        },
    )
    if result.get("ok"):
        st.session_state.presence_last_ping_ts = now
        st.session_state.presence_last_room = room_name
        st.session_state.presence_last_district = str(payload_district or "")


def maybe_send_typing_heartbeat(room_name: str, district_scope: str, case_id: int | None, is_typing: bool) -> None:
    now = time.time()
    payload_district = None if district_scope == DEFAULT_DISTRICT_SCOPE else district_scope
    last_ping = float(st.session_state.get("typing_last_ping_ts", 0.0))
    last_room = str(st.session_state.get("typing_last_room", ""))
    active_state = bool(st.session_state.get("typing_active", False))
    if is_typing:
        if (now - last_ping) < 7 and active_state and room_name == last_room:
            return
        result = api_post(
            "/internal-comms/typing",
            payload={
                "room_name": room_name,
                "district": payload_district,
                "case_id": case_id,
                "is_typing": True,
            },
        )
        if result.get("ok"):
            st.session_state.typing_last_ping_ts = now
            st.session_state.typing_last_room = room_name
            st.session_state.typing_active = True
    elif active_state:
        result = api_post(
            "/internal-comms/typing",
            payload={
                "room_name": room_name,
                "district": payload_district,
                "case_id": case_id,
                "is_typing": False,
            },
        )
        if result.get("ok"):
            st.session_state.typing_active = False
            st.session_state.typing_last_room = room_name


def maybe_send_video_participant_heartbeat(
    session_code: str,
    *,
    device_label: str,
    join_state: str,
    hand_raised: bool,
    muted: bool,
    camera_enabled: bool,
    screen_sharing: bool,
) -> None:
    if not session_code:
        return
    now = time.time()
    state_signature = json.dumps(
        {
            "device_label": device_label,
            "join_state": join_state,
            "hand_raised": hand_raised,
            "muted": muted,
            "camera_enabled": camera_enabled,
            "screen_sharing": screen_sharing,
        },
        sort_keys=True,
    )
    last_ping = float(st.session_state.get("video_presence_last_ping_ts", 0.0))
    last_session = str(st.session_state.get("video_presence_last_session", ""))
    last_signature = str(st.session_state.get("video_presence_signature", ""))
    if (now - last_ping) < 20 and last_session == session_code and last_signature == state_signature:
        return
    result = api_post(
        f"/video/sessions/{session_code}/participant-state",
        payload={
            "device_label": device_label,
            "join_state": join_state,
            "hand_raised": hand_raised,
            "muted": muted,
            "camera_enabled": camera_enabled,
            "screen_sharing": screen_sharing,
        },
    )
    if result.get("ok"):
        st.session_state.video_presence_last_ping_ts = now
        st.session_state.video_presence_last_session = session_code
        st.session_state.video_presence_signature = state_signature


def websocket_api_url() -> str:
    api_url = get_api_url()
    if api_url.startswith("https://"):
        return "wss://" + api_url[len("https://") :]
    if api_url.startswith("http://"):
        return "ws://" + api_url[len("http://") :]
    return api_url


def render_war_room_socket_panel(room_name: str, district_scope: str) -> None:
    token = str(st.session_state.get("token") or "")
    if not token or not room_name:
        return
    district_value = "" if district_scope == DEFAULT_DISTRICT_SCOPE else district_scope
    ws_url = f"{websocket_api_url()}/internal-comms/ws?token={token}&room_name={room_name}&district={district_value}"
    components.html(
        f"""
        <div style="border:1px solid rgba(92,116,151,0.35);border-radius:18px;padding:0.85rem 1rem;background:rgba(10,18,28,0.92);font-family:system-ui,sans-serif;color:#eaf2ff;">
            <div style="display:flex;justify-content:space-between;align-items:center;gap:0.8rem;">
                <div style="font-weight:700;">Socket Monitor</div>
                <div id="tn-ws-status" style="font-size:0.8rem;color:#97a8c4;">Connecting...</div>
            </div>
            <div style="font-size:0.82rem;color:#97a8c4;margin-top:0.35rem;">WebSocket feed for {escape(room_name)}.</div>
            <div id="tn-ws-events" style="margin-top:0.8rem;display:flex;flex-direction:column;gap:0.55rem;max-height:210px;overflow:auto;"></div>
        </div>
        <script>
        const statusEl = document.getElementById("tn-ws-status");
        const eventsEl = document.getElementById("tn-ws-events");
        const ws = new WebSocket("{escape(ws_url, quote=True)}");
        const renderEvent = (payload) => {{
            const card = document.createElement("div");
            card.style.border = "1px solid rgba(92,116,151,0.35)";
            card.style.borderRadius = "12px";
            card.style.padding = "0.55rem 0.7rem";
            card.style.background = "rgba(17,26,39,0.92)";
            const title = payload.event_type === "message"
                ? `${{payload.sender_username || "system"}} posted`
                : payload.event_type === "typing"
                    ? `${{payload.username || "user"}} is typing`
                    : payload.event_type;
            card.innerHTML = `<div style="font-size:0.78rem;color:#76b7ff;font-weight:700;">${{title}}</div><div style="font-size:0.8rem;margin-top:0.2rem;">${{payload.message_text || payload.room_name || ""}}</div>`;
            eventsEl.prepend(card);
            while (eventsEl.children.length > 8) {{
                eventsEl.removeChild(eventsEl.lastChild);
            }}
        }};
        ws.onopen = () => {{ statusEl.textContent = "Connected"; statusEl.style.color = "#47d89a"; }};
        ws.onmessage = (event) => {{
            try {{
                renderEvent(JSON.parse(event.data));
            }} catch (error) {{
                renderEvent({{ event_type: "socket", message_text: "Realtime payload received." }});
            }}
        }};
        ws.onerror = () => {{ statusEl.textContent = "Signal degraded"; statusEl.style.color = "#ff8c42"; }};
        ws.onclose = () => {{ statusEl.textContent = "Disconnected"; statusEl.style.color = "#ff8c42"; }};
        </script>
        """,
        height=320,
        scrolling=False,
    )


def render_video_signal_panel(session_code: str) -> None:
    token = str(st.session_state.get("token") or "")
    if not token or not session_code:
        return
    ws_url = f"{websocket_api_url()}/video/sessions/{quote(session_code)}/ws?token={token}"
    components.html(
        f"""
        <div style="border:1px solid rgba(92,116,151,0.35);border-radius:18px;padding:0.85rem 1rem;background:rgba(10,18,28,0.92);font-family:system-ui,sans-serif;color:#eaf2ff;">
            <div style="display:flex;justify-content:space-between;align-items:center;gap:0.8rem;">
                <div style="font-weight:700;">Video Signal Bus</div>
                <div id="tn-video-ws-status" style="font-size:0.8rem;color:#97a8c4;">Connecting...</div>
            </div>
            <div style="font-size:0.82rem;color:#97a8c4;margin-top:0.35rem;">Session signaling for {escape(session_code)}.</div>
            <div id="tn-video-ws-events" style="margin-top:0.8rem;display:flex;flex-direction:column;gap:0.55rem;max-height:220px;overflow:auto;"></div>
        </div>
        <script>
        const statusEl = document.getElementById("tn-video-ws-status");
        const eventsEl = document.getElementById("tn-video-ws-events");
        const ws = new WebSocket("{escape(ws_url, quote=True)}");
        const renderEvent = (payload) => {{
            const card = document.createElement("div");
            card.style.border = "1px solid rgba(92,116,151,0.35)";
            card.style.borderRadius = "12px";
            card.style.padding = "0.55rem 0.7rem";
            card.style.background = "rgba(17,26,39,0.92)";
            const title = payload.event_type === "participant_state"
                ? `${{payload.username || "participant"}} state sync`
                : payload.event_type === "signal"
                    ? `${{payload.username || "participant"}} signaling`
                    : payload.event_type;
            card.innerHTML = `<div style="font-size:0.78rem;color:#76b7ff;font-weight:700;">${{title}}</div><div style="font-size:0.8rem;margin-top:0.2rem;">${{payload.join_state || payload.payload || payload.room_name || ""}}</div>`;
            eventsEl.prepend(card);
            while (eventsEl.children.length > 8) {{
                eventsEl.removeChild(eventsEl.lastChild);
            }}
        }};
        ws.onopen = () => {{ statusEl.textContent = "Connected"; statusEl.style.color = "#47d89a"; }};
        ws.onmessage = (event) => {{
            try {{
                renderEvent(JSON.parse(event.data));
            }} catch (error) {{
                renderEvent({{ event_type: "signal", payload: "Video signal received." }});
            }}
        }};
        ws.onerror = () => {{ statusEl.textContent = "Signal degraded"; statusEl.style.color = "#ff8c42"; }};
        ws.onclose = () => {{ statusEl.textContent = "Disconnected"; statusEl.style.color = "#ff8c42"; }};
        </script>
        """,
        height=330,
        scrolling=False,
    )


def sanitize_room_slug(value: str) -> str:
    slug = "".join(character.lower() if character.isalnum() else "-" for character in str(value or ""))
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "state-command-net"


def render_video_briefing_panel(
    room_name: str,
    district_scope: str,
    selected_case_id: int | None,
    me_payload: dict[str, Any],
    presence_rows: list[dict[str, Any]],
) -> None:
    district_slug = sanitize_room_slug("statewide" if district_scope == DEFAULT_DISTRICT_SCOPE else district_scope)
    room_slug = sanitize_room_slug(room_name)
    case_slug = f"case-{selected_case_id}" if selected_case_id is not None else "general-ops"
    fallback_room_code = f"tn-police-{district_slug}-{room_slug}-{case_slug}"
    fallback_meeting_url = (
        f"https://meet.jit.si/{fallback_room_code}"
        + f"#userInfo.displayName=\"{quote(str(me_payload.get('username') or st.session_state.get('username') or 'Analyst'))}\""
        + "&config.prejoinPageEnabled=false"
    )
    district_param = None if district_scope == DEFAULT_DISTRICT_SCOPE else district_scope
    session_rows = raw_rows_from_result(
        api_get(
            "/video/sessions",
            params=compact_params(
                {
                    "district": district_param,
                    "room_name": room_name,
                    "case_id": selected_case_id,
                }
            ) or None,
        )
    )
    online_personnel = [row for row in presence_rows if str(row.get("is_online")).lower() == "yes"]

    session_option_map = {
        f"{row.get('room_name')} | {row.get('session_mode')} | {row.get('status')}": row
        for row in session_rows
        if row.get("session_code")
    }
    query_session_code = get_query_param("ops_video")
    selected_session = next((row for row in session_rows if str(row.get("session_code")) == str(query_session_code)), session_rows[0] if session_rows else {})
    if session_option_map:
        reverse_map = {str(value.get("session_code")): key for key, value in session_option_map.items()}
        default_label = reverse_map.get(str(selected_session.get("session_code"))) or next(iter(session_option_map))
        selected_session_label = st.selectbox(
            "Video session",
            list(session_option_map.keys()),
            index=list(session_option_map.keys()).index(default_label),
            key="video_session_select",
        )
        selected_session = session_option_map[selected_session_label]
        set_query_param("ops_video", selected_session.get("session_code"))

    active_session_code = str(selected_session.get("session_code") or fallback_room_code)
    meeting_room_code = active_session_code
    meeting_url_with_name = str(selected_session.get("join_url") or fallback_meeting_url)
    participant_rows = raw_rows_from_result(api_get(f"/video/sessions/{active_session_code}/participants")) if selected_session else []
    quality_result = api_get(f"/video/sessions/{active_session_code}/quality") if selected_session else {"ok": False, "data": {}}
    quality_payload = quality_result.get("data") if quality_result.get("ok") and isinstance(quality_result.get("data"), dict) else {}

    render_metric_grid(
        [
            ("Video Sessions", len(session_rows)),
            ("Active Participants", len(participant_rows)),
            ("Eligible Personnel", len(online_personnel)),
            ("Raised Hands", sum(1 for row in participant_rows if row.get("hand_raised"))),
            ("Screen Shares", sum(1 for row in participant_rows if row.get("screen_sharing"))),
            ("Command Readiness", (quality_payload.get("command_readiness_score", "N/A") if quality_payload else "N/A")),
            ("District Scope", district_scope),
        ]
    )

    bridge_left, bridge_right = st.columns([1.2, 0.8])
    with bridge_left:
        components.html(
            f"""
            <div style="border:1px solid rgba(92,116,151,0.35);border-radius:24px;overflow:hidden;background:linear-gradient(180deg, rgba(15,25,40,0.98), rgba(10,18,28,0.96));">
                <div style="padding:1rem 1rem 0.8rem 1rem;display:flex;justify-content:space-between;align-items:flex-end;gap:1rem;flex-wrap:wrap;">
                    <div>
                        <div style="color:#76b7ff;font-size:0.82rem;letter-spacing:0.12em;text-transform:uppercase;font-weight:700;">Video Command Plane</div>
                        <div style="color:#97a8c4;font-size:0.95rem;margin-top:0.25rem;">Session registry, participant state, signaling bus, and live briefing bridge aligned to the active war-room thread.</div>
                    </div>
                    <div style="color:#97a8c4;font-size:0.82rem;">Camera, microphone, fullscreen, and screen sharing enabled.</div>
                </div>
                <iframe
                    src="{escape(meeting_url_with_name, quote=True)}"
                    allow="camera; microphone; fullscreen; display-capture"
                    style="width:100%;height:720px;border:0;background:#081019;"
                    referrerpolicy="no-referrer"
                ></iframe>
            </div>
            """,
            height=820,
            scrolling=False,
        )
    with bridge_right:
        session_mode = st.selectbox("Session mode", ["webrtc_mesh", "sfu_ready", "command_bridge"], index=1, key="video_session_mode")
        session_notes = st.text_area(
            "Session notes",
            height=90,
            key="video_session_notes",
            placeholder="Command briefing, evidence review, cross-district escalation, or corridor intercept coordination.",
        )
        if st.button("Create or Join Department Session", use_container_width=True, key="video_create_join"):
            run_action_and_refresh(
                "/video/sessions",
                payload={
                    "room_name": room_name,
                    "district": district_param,
                    "case_id": selected_case_id,
                    "session_mode": session_mode,
                    "notes": session_notes or None,
                },
                success_message="Video session is ready.",
            )
        st.link_button("Open Video Conference in New Tab", meeting_url_with_name, use_container_width=True)
        st.code(meeting_room_code)
        render_inline_note(
            "The department video layer now uses an app-native control plane: session registry, participant heartbeat, live signaling bus, and room-aligned meeting bridge."
        )
        render_table(
            "Session Registry",
            session_rows,
            caption="Visible briefing sessions for the current war-room and district lens.",
            limit=10,
        )

        if selected_session:
            render_table(
                "Session Quality",
                [quality_payload] if quality_payload else [],
                caption="Readiness and media-health indicators for the selected native video session.",
                limit=1,
            )
            session_status = st.selectbox(
                "Session status",
                ["active", "standby", "closed"],
                index=["active", "standby", "closed"].index(str(selected_session.get("status") or "active")) if str(selected_session.get("status") or "active") in {"active", "standby", "closed"} else 0,
                key=f"video_status_{active_session_code}",
            )
            session_control_notes = st.text_area(
                "Session control notes",
                height=80,
                key=f"video_control_notes_{active_session_code}",
                placeholder="Shift room to standby, close briefing, or note conference posture.",
            )
            if st.button("Apply session control", use_container_width=True, key=f"video_control_{active_session_code}"):
                run_action_and_refresh(
                    f"/video/sessions/{active_session_code}/control",
                    payload={
                        "status": session_status,
                        "notes": session_control_notes or None,
                    },
                    success_message="Video session control applied.",
                )
            device_label = st.text_input("Device label", value="Browser console", key=f"video_device_{active_session_code}")
            join_state = st.selectbox("Join state", ["connected", "monitoring", "reconnecting", "observer"], index=0, key=f"video_join_state_{active_session_code}")
            hand_raised = st.checkbox("Hand raised", value=False, key=f"video_hand_raised_{active_session_code}")
            muted = st.checkbox("Muted", value=False, key=f"video_muted_{active_session_code}")
            camera_enabled = st.checkbox("Camera enabled", value=True, key=f"video_camera_enabled_{active_session_code}")
            screen_sharing = st.checkbox("Screen sharing", value=False, key=f"video_screen_sharing_{active_session_code}")
            maybe_send_video_participant_heartbeat(
                active_session_code,
                device_label=device_label,
                join_state=join_state,
                hand_raised=hand_raised,
                muted=muted,
                camera_enabled=camera_enabled,
                screen_sharing=screen_sharing,
            )
            if st.button("Sync participant state", use_container_width=True, key=f"video_sync_{active_session_code}"):
                run_action_and_refresh(
                    f"/video/sessions/{active_session_code}/participant-state",
                    payload={
                        "device_label": device_label,
                        "join_state": join_state,
                        "hand_raised": hand_raised,
                        "muted": muted,
                        "camera_enabled": camera_enabled,
                        "screen_sharing": screen_sharing,
                    },
                    success_message="Video participant state synchronized.",
                )
            render_table(
                "Participant Board",
                participant_rows,
                caption="Current participant posture, device state, mute/camera flags, and live control status.",
                limit=16,
            )
            render_video_signal_panel(active_session_code)

        render_table(
            "Suggested Participants",
            online_personnel,
            caption="Currently online personnel who can join this briefing immediately.",
            limit=16,
        )


def activate_live_refresh(enabled: bool, interval_seconds: int = 20, component_key: str = "live_refresh") -> None:
    if not enabled:
        return
    components.html(
        f"""
        <script>
        const timerKey = "{escape(component_key)}";
        window.clearTimeout(window[timerKey]);
        window[timerKey] = window.setTimeout(function() {{
            try {{
                if (window.parent && window.parent.location) {{
                    window.parent.location.reload();
                }} else {{
                    window.location.reload();
                }}
            }} catch (error) {{
                window.location.reload();
            }}
        }}, {interval_seconds * 1000});
        </script>
        """,
        height=0,
    )


def build_graph_canvas_payload(
    entity_rows: list[dict[str, Any]],
    link_rows: list[dict[str, Any]],
    case_graph_payload: dict[str, Any] | None = None,
    district_scope: str = DEFAULT_DISTRICT_SCOPE,
    selected_node_id: str | None = None,
) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []

    for row in entity_rows:
        district = str(row.get("district") or "")
        if district_scope != DEFAULT_DISTRICT_SCOPE and district and district != district_scope:
            continue
        node_id = f"entity-{row.get('id')}"
        nodes[node_id] = {
            "id": node_id,
            "label": str(row.get("name") or f"Entity {row.get('id')}"),
            "type": str(row.get("type") or "entity"),
            "district": district,
            "risk_score": to_float(row.get("risk_score")),
        }

    for row in link_rows:
        source_id = f"entity-{row.get('source')}"
        target_id = f"entity-{row.get('target')}"
        if source_id in nodes and target_id in nodes:
            edges.append(
                {
                    "source": source_id,
                    "target": target_id,
                    "label": row.get("relationship_type"),
                    "weight": to_float(row.get("weight"), 1.0),
                }
            )

    if case_graph_payload:
        for row in payload_to_rows(case_graph_payload.get("nodes")):
            node_id = str(row.get("id") or "")
            if not node_id:
                continue
            nodes[node_id] = {
                "id": node_id,
                "label": str(row.get("label") or node_id),
                "type": str(row.get("type") or "entity"),
                "district": str(row.get("district") or district_scope),
                "risk_score": to_float(row.get("risk_score")),
            }
        for row in payload_to_rows(case_graph_payload.get("edges")):
            source_id = str(row.get("source") or "")
            target_id = str(row.get("target") or "")
            if source_id in nodes and target_id in nodes:
                edges.append(
                    {
                        "source": source_id,
                        "target": target_id,
                        "label": row.get("label"),
                        "weight": to_float(row.get("weight"), 1.0),
                    }
                )

    adjacency: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in edges:
        adjacency[row["source"]].append(row)
        adjacency[row["target"]].append(row)

    if not selected_node_id or selected_node_id not in nodes:
        if case_graph_payload and any(node_id.startswith("case-") for node_id in nodes):
            selected_node_id = next(node_id for node_id in nodes if node_id.startswith("case-"))
        else:
            selected_node_id = next(
                (node_id for node_id, row in sorted(nodes.items(), key=lambda item: item[1].get("risk_score", 0.0), reverse=True)),
                next(iter(nodes), None),
            )

    related_ids: list[str] = []
    if selected_node_id:
        for row in sorted(adjacency.get(selected_node_id, []), key=lambda item: item.get("weight", 0.0), reverse=True):
            peer_id = row["target"] if row["source"] == selected_node_id else row["source"]
            if peer_id not in related_ids:
                related_ids.append(peer_id)
    display_ids = []
    if selected_node_id:
        display_ids.append(selected_node_id)
    display_ids.extend(related_ids[:14])
    for node_id, row in sorted(nodes.items(), key=lambda item: item[1].get("risk_score", 0.0), reverse=True):
        if node_id not in display_ids:
            display_ids.append(node_id)
        if len(display_ids) >= 26:
            break

    display_nodes = [nodes[node_id] for node_id in display_ids if node_id in nodes]
    display_id_set = {row["id"] for row in display_nodes}
    display_edges = [row for row in edges if row["source"] in display_id_set and row["target"] in display_id_set]
    selected_node = nodes.get(selected_node_id) if selected_node_id else None
    linked_rows = []
    for row in display_edges:
        if selected_node_id not in {row["source"], row["target"]}:
            continue
        peer_id = row["target"] if row["source"] == selected_node_id else row["source"]
        peer_row = nodes.get(peer_id, {})
        linked_rows.append(
            {
                "peer_id": peer_id,
                "peer_label": peer_row.get("label"),
                "peer_type": peer_row.get("type"),
                "district": peer_row.get("district"),
                "edge_label": row.get("label"),
                "weight": row.get("weight"),
            }
        )

    return {
        "nodes": display_nodes,
        "edges": display_edges,
        "selected_node_id": selected_node_id,
        "selected_node": selected_node,
        "linked_rows": linked_rows,
    }


def build_graph_svg(
    title: str,
    subtitle: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    selected_node_id: str | None = None,
    link_getter: Callable[[dict[str, Any]], str | None] | None = None,
) -> str:
    width = 980
    height = 760
    center_x = width / 2
    center_y = height / 2
    type_colors = {
        "person": "#ff8c42",
        "vehicle": "#6bc7ff",
        "phone": "#7ef0c4",
        "device": "#7ef0c4",
        "case": "#f6cf61",
        "evidence": "#d68cff",
        "account": "#8cc7ff",
        "entity": "#9db0cc",
    }
    if not nodes:
        return '<div class="tn-inline-note">Graph canvas data is not available for the current selection.</div>'

    selected_row = next((row for row in nodes if row.get("id") == selected_node_id), nodes[0])
    selected_node_id = str(selected_row.get("id"))
    related_ids = {
        row["target"] if row["source"] == selected_node_id else row["source"]
        for row in edges
        if selected_node_id in {row["source"], row["target"]}
    }
    outer_nodes = [row for row in nodes if row.get("id") not in related_ids and row.get("id") != selected_node_id]
    related_nodes = [row for row in nodes if row.get("id") in related_ids]

    positions: dict[str, tuple[float, float]] = {selected_node_id: (center_x, center_y)}
    for index, row in enumerate(related_nodes):
        angle = ((2 * math.pi) / max(len(related_nodes), 1)) * index
        positions[str(row.get("id"))] = (center_x + (math.cos(angle) * 210), center_y + (math.sin(angle) * 210))
    for index, row in enumerate(outer_nodes):
        angle = ((2 * math.pi) / max(len(outer_nodes), 1)) * index
        positions[str(row.get("id"))] = (center_x + (math.cos(angle) * 325), center_y + (math.sin(angle) * 325))

    edge_markup = []
    for row in edges:
        source = positions.get(str(row.get("source")))
        target = positions.get(str(row.get("target")))
        if not source or not target:
            continue
        highlighted = selected_node_id in {row.get("source"), row.get("target")}
        edge_markup.append(
            f"""
            <line x1="{source[0]:.1f}" y1="{source[1]:.1f}" x2="{target[0]:.1f}" y2="{target[1]:.1f}"
                stroke="{'rgba(255, 140, 66, 0.65)' if highlighted else 'rgba(118, 183, 255, 0.22)'}"
                stroke-width="{1.2 + min(to_float(row.get('weight'), 1.0), 5.0):.1f}">
                <title>{escape(str(row.get('label') or 'linked'))}</title>
            </line>
            """
        )

    node_markup = []
    for row in nodes:
        node_id = str(row.get("id"))
        x, y = positions.get(node_id, (center_x, center_y))
        node_type = str(row.get("type") or "entity").lower()
        color = type_colors.get(node_type, type_colors["entity"])
        radius = 16 if node_id == selected_node_id else 11 + min(to_float(row.get("risk_score")), 1.0) * 8
        stroke = "#ffe2bf" if node_id == selected_node_id else "#eaf2ff"
        body = (
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}" fill="{color}" fill-opacity="0.92" stroke="{stroke}" stroke-width="2.2">'
            f'<title>{escape(str(row.get("label")))} | {escape(str(row.get("type")))} | District: {escape(str(row.get("district") or "statewide"))}</title>'
            '</circle>'
            f'<text x="{x:.1f}" y="{(y + radius + 15):.1f}" text-anchor="middle" '
            'style="fill:#eaf2ff;font-size:10.8px;font-family:system-ui,sans-serif;font-weight:600;">'
            f"{escape(str(row.get('label'))[:24])}</text>"
        )
        if link_getter:
            node_url = link_getter(row)
            if node_url:
                body = f'<a href="{escape(node_url, quote=True)}" target="_top" style="text-decoration:none;">{body}</a>'
        node_markup.append(f"<g>{body}</g>")

    return f"""
    <div style="border:1px solid rgba(92,116,151,0.35);border-radius:24px;padding:1rem 1rem 0.7rem 1rem;
        background:linear-gradient(180deg, rgba(15,25,40,0.98), rgba(10,18,28,0.96));">
        <div style="display:flex;justify-content:space-between;align-items:flex-end;gap:1rem;flex-wrap:wrap;">
            <div>
                <div style="color:#76b7ff;font-size:0.82rem;letter-spacing:0.12em;text-transform:uppercase;font-weight:700;">{escape(title)}</div>
                <div style="color:#97a8c4;font-size:0.95rem;margin-top:0.25rem;">{escape(subtitle)}</div>
            </div>
            <div style="color:#97a8c4;font-size:0.82rem;">Click nodes to focus the graph. Center node is the active selection.</div>
        </div>
        <svg viewBox="0 0 {width} {height}" style="width:100%;height:auto;margin-top:0.8rem;">
            {"".join(edge_markup)}
            {"".join(node_markup)}
        </svg>
    </div>
    """

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


def raw_rows_from_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    return payload_to_rows(result.get("data"))


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


def build_movement_flow_rows(
    district_map_rows: list[dict[str, Any]],
    cluster_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    district_lookup = {str(row.get("district")): row for row in district_map_rows if row.get("district")}
    cluster_groups: dict[str, dict[str, Any]] = defaultdict(lambda: {"districts": set(), "cases": set(), "signal_sum": 0.0})
    for row in cluster_rows:
        cluster_id = str(row.get("cluster_id") or "").strip()
        district = str(row.get("district") or "").strip()
        if not cluster_id or district not in district_lookup:
            continue
        group = cluster_groups[cluster_id]
        group["districts"].add(district)
        if row.get("case_id") not in (None, "", "N/A"):
            group["cases"].add(str(row.get("case_id")))
        group["signal_sum"] += to_float(row.get("signal_strength"), 0.5)

    flow_accumulator: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"flow_weight": 0.0, "cluster_count": 0, "cases": set()}
    )
    for payload in cluster_groups.values():
        districts = sorted(payload["districts"])
        if len(districts) < 2:
            continue
        base_signal = payload["signal_sum"] / max(len(districts), 1)
        for source_district, target_district in combinations(districts, 2):
            slot = flow_accumulator[(source_district, target_district)]
            slot["flow_weight"] += base_signal + 0.65
            slot["cluster_count"] += 1
            slot["cases"].update(payload["cases"])

    if not flow_accumulator:
        ranked_districts = [
            str(row.get("district"))
            for row in sorted(district_map_rows, key=lambda item: to_float(item.get("intensity")), reverse=True)
            if row.get("district")
        ]
        for index in range(max(0, len(ranked_districts) - 1)):
            source_district = ranked_districts[index]
            target_district = ranked_districts[index + 1]
            flow_accumulator[(source_district, target_district)] = {
                "flow_weight": 2.0 + (index * 0.4),
                "cluster_count": 1,
                "cases": set(),
            }

    output: list[dict[str, Any]] = []
    for (source_district, target_district), payload in flow_accumulator.items():
        source_row = district_lookup.get(source_district)
        target_row = district_lookup.get(target_district)
        if not source_row or not target_row:
            continue
        output.append(
            {
                "source_district": source_district,
                "target_district": target_district,
                "source_latitude": source_row.get("latitude"),
                "source_longitude": source_row.get("longitude"),
                "target_latitude": target_row.get("latitude"),
                "target_longitude": target_row.get("longitude"),
                "flow_weight": round(to_float(payload.get("flow_weight")), 2),
                "cluster_count": to_int(payload.get("cluster_count")),
                "case_count": len(payload.get("cases", set())),
                "flow_type": "cross-district linkage",
            }
        )
    return sorted(output, key=lambda item: to_float(item.get("flow_weight")), reverse=True)


def build_camera_registry_rows(station_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for index, row in enumerate(station_rows, start=1):
        district_code = str(row.get("district") or "TN")[:3].upper()
        station_code = str(row.get("station_name") or "NODE").split()[0][:4].upper()
        blind_risk = str(row.get("blind_spot_risk") or "Moderate")
        status = "monitoring"
        if blind_risk == "High":
            status = "priority_watch"
        elif blind_risk == "Low":
            status = "stable"
        profiles = [
            ("PTZ perimeter", "ptz", 0.42),
            ("ANPR corridor", "anpr", 0.33),
            ("Command overwatch" if str(row.get("station_type")) == "Central" else "Digital ingress", "fixed_dome", 0.25),
        ]
        for profile_index, (zone_label, camera_type, weight) in enumerate(profiles, start=1):
            blind_spot_score = round(
                (to_float(row.get("intensity")) * 0.95)
                + (to_float(row.get("avg_anomaly")) * 7.0)
                + (to_int(row.get("incident_count")) * 0.28)
                + (weight * 4.2),
                2,
            )
            output.append(
                {
                    "camera_id": f"{district_code}-{station_code}-{index:02d}-{profile_index}",
                    "district": row.get("district"),
                    "station_name": row.get("station_name"),
                    "camera_type": camera_type,
                    "zone_label": zone_label,
                    "blind_spot_score": blind_spot_score,
                    "coverage_circle_km": row.get("coverage_circle_km"),
                    "retention_profile": "90 days" if blind_spot_score >= 12 else "60 days",
                    "feed_status": status,
                    "priority_band": blind_risk,
                }
            )
    return sorted(output, key=lambda item: to_float(item.get("blind_spot_score")), reverse=True)


def build_blind_spot_rows(
    station_rows: list[dict[str, Any]],
    patrol_rows: list[dict[str, Any]],
    geofence_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    patrol_lookup: dict[int, list[float]] = defaultdict(list)
    district_geofence_count: dict[str, int] = defaultdict(int)
    for row in patrol_rows:
        station_id = to_optional_int(str(row.get("station_id", "")))
        if station_id is not None:
            patrol_lookup[station_id].append(to_float(row.get("coverage_ratio"), 0.65))
    for row in geofence_rows:
        district = str(row.get("district") or "")
        if district:
            district_geofence_count[district] += 1

    output: list[dict[str, Any]] = []
    for row in station_rows:
        station_id = to_optional_int(str(row.get("station_id", "")))
        coverage_ratio = 0.65
        if station_id is not None and patrol_lookup.get(station_id):
            coverage_ratio = min(patrol_lookup[station_id])
        district = str(row.get("district") or "")
        blind_spot_score = round(
            ((1 - coverage_ratio) * 10.5)
            + (to_float(row.get("avg_anomaly")) * 6.4)
            + (to_float(row.get("intensity")) * 0.92)
            + (district_geofence_count.get(district, 0) * 0.42),
            2,
        )
        output.append(
            {
                "district": district,
                "station_name": row.get("station_name"),
                "station_type": row.get("station_type"),
                "latitude": row.get("latitude"),
                "longitude": row.get("longitude"),
                "intensity": row.get("intensity"),
                "incident_count": row.get("incident_count"),
                "coverage_gap_pct": round((1 - coverage_ratio) * 100, 1),
                "blind_spot_score": blind_spot_score,
                "recommended_action": "Deploy mobile mast and PTZ corridor watch" if blind_spot_score >= 12 else "Rebalance patrol and ANPR coverage" if blind_spot_score >= 8 else "Maintain current camera posture",
            }
        )
    return sorted(output, key=lambda item: to_float(item.get("blind_spot_score")), reverse=True)


def build_route_rows(
    district_map_rows: list[dict[str, Any]],
    flow_rows: list[dict[str, Any]],
    suspect_rows: list[dict[str, Any]],
    case_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    district_lookup = {str(row.get("district")): row for row in district_map_rows if row.get("district")}
    adjacency: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for row in flow_rows:
        source = str(row.get("source_district") or "")
        target = str(row.get("target_district") or "")
        weight = to_float(row.get("flow_weight"), 0.0)
        if source and target:
            adjacency[source].append((target, weight))
            adjacency[target].append((source, weight))

    for district in adjacency:
        adjacency[district] = sorted(adjacency[district], key=lambda item: item[1], reverse=True)

    intensity_rank = [
        str(row.get("district"))
        for row in sorted(district_map_rows, key=lambda item: to_float(item.get("intensity")), reverse=True)
        if row.get("district")
    ]

    def pick_targets(origin: str, limit: int = 2) -> list[str]:
        targets = [target for target, _ in adjacency.get(origin, []) if target != origin]
        if len(targets) < limit:
            targets.extend([district for district in intensity_rank if district not in {origin, *targets}])
        return targets[:limit]

    threat_rank = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    route_rows: list[dict[str, Any]] = []
    sorted_suspects = sorted(
        suspect_rows,
        key=lambda row: (
            threat_rank.get(str(row.get("threat_level") or "").lower(), 0),
            to_int(row.get("open_alerts")),
            to_int(row.get("linked_cases")),
        ),
        reverse=True,
    )
    for row in sorted_suspects[:4]:
        origin = str(row.get("district") or "")
        if origin not in district_lookup:
            continue
        districts = [origin] + pick_targets(origin)
        route_rows.append(
            {
                "route_id": f"suspect-{row.get('id')}",
                "route_type": "suspect",
                "subject_label": f"Suspect trail | {row.get('category') or 'fusion target'}",
                "districts": districts,
                "risk_score": round((threat_rank.get(str(row.get("threat_level") or "").lower(), 1) * 4.8) + to_int(row.get("open_alerts")) + (to_int(row.get("linked_cases")) * 0.7), 2),
                "status": "active watch",
                "last_seen": f"{origin} sector",
            }
        )

    priority_rank = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    sorted_cases = sorted(
        case_rows,
        key=lambda row: priority_rank.get(str(row.get("priority") or "medium").lower(), 0),
        reverse=True,
    )
    for row in sorted_cases[:3]:
        origin = str(row.get("district") or "")
        if origin not in district_lookup:
            continue
        districts = [origin] + pick_targets(origin)
        route_rows.append(
            {
                "route_id": f"vehicle-{row.get('id')}",
                "route_type": "vehicle",
                "subject_label": f"Vehicle corridor | Case {row.get('id')}",
                "districts": districts,
                "risk_score": round((priority_rank.get(str(row.get("priority") or "").lower(), 1) * 4.0) + len(districts), 2),
                "status": "route monitor",
                "last_seen": f"Case district {origin}",
            }
        )

    return route_rows


def build_incident_playback_rows(
    incident_rows: list[dict[str, Any]],
    station_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    station_lookup = {
        to_optional_int(str(row.get("station_id", ""))): row
        for row in station_rows
        if to_optional_int(str(row.get("station_id", ""))) is not None
    }
    ordered_rows = sorted(incident_rows, key=lambda row: str(row.get("created_at") or ""))
    output: list[dict[str, Any]] = []
    for index, row in enumerate(ordered_rows, start=1):
        station_row = station_lookup.get(to_optional_int(str(row.get("station_id", ""))), {})
        latitude = station_row.get("latitude")
        longitude = station_row.get("longitude")
        if latitude in (None, "", "N/A") or longitude in (None, "", "N/A"):
            continue
        output.append(
            {
                "sequence": index,
                "sequence_label": f"T{index}",
                "incident_id": row.get("id"),
                "district": row.get("district"),
                "station_name": station_row.get("station_name") or f"Station {row.get('station_id')}",
                "category": row.get("category"),
                "severity": row.get("severity"),
                "anomaly_score": row.get("anomaly_score"),
                "status": row.get("status"),
                "created_at": row.get("created_at"),
                "latitude": latitude,
                "longitude": longitude,
                "intensity": round(to_int(row.get("severity")) + (to_float(row.get("anomaly_score")) * 4.0), 2),
            }
        )
    return output


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


def parse_attachment_manifest(raw_text: str) -> list[dict[str, Any]]:
    attachments: list[dict[str, Any]] = []
    for line in str(raw_text or "").splitlines():
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 3 or not parts[0] or not parts[2]:
            continue
        attachments.append(
            {
                "attachment_name": parts[0],
                "attachment_type": parts[1] or "document",
                "storage_ref": parts[2],
            }
        )
    return attachments


def render_message_feed(rows: list[dict[str, Any]], empty_message: str = "No coordination traffic available.") -> None:
    if not rows:
        st.caption(empty_message)
        return

    for row in rows:
        priority = str(row.get("priority") or "routine")
        recipient = row.get("recipient_username") or row.get("room_name") or "broadcast"
        unread_markup = ""
        if bool(row.get("is_unread")):
            unread_markup = '<span class="tn-room-pill">Unread</span>'
        if bool(row.get("mentions_me")):
            unread_markup += '<span class="tn-room-pill">Mention</span>'
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
        attachment_markup = ""
        attachments = row.get("attachments") or []
        if isinstance(attachments, list) and attachments:
            attachment_markup = (
                '<div style="margin-top:0.55rem;color:#cfe3ff;font-size:0.82rem;"><strong>Attachments:</strong> '
                + ", ".join(
                    f"{escape(str(item.get('attachment_name') or 'attachment'))} ({escape(str(item.get('attachment_type') or 'document'))})"
                    for item in attachments
                    if isinstance(item, dict)
                )
                + "</div>"
            )
        st.markdown(
            f"""
            <div class="tn-message-card">
                <div class="tn-message-priority">{escape(priority)} {unread_markup}</div>
                <div class="tn-message-meta">{escape(meta)}</div>
                <div>{body}</div>
                {attachment_markup}
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
        "Statewide Tamil Nadu district visibility, live operational overlays, route tracking, CCTV planning, and station lookout circles aligned in one command surface.",
        eyebrow="Statewide Geospatial Intelligence",
        chips=[
            "Visible to every logged-in role",
            "All 38 Tamil Nadu districts",
            "Flows, routes, CCTV, playback",
        ],
    )
    render_inline_note(
        "Statewide district visibility is available to all authenticated users. Click district nodes where supported to pin the drill-down lens, then inspect flows, routes, CCTV posture, blind spots, and incident playback."
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
    query_district = get_query_param("ops_district")
    if query_district in available_districts and st.session_state.get("geo_detail_district") != query_district:
        st.session_state.geo_detail_district = query_district

    if district_scope != DEFAULT_DISTRICT_SCOPE and district_scope in available_districts:
        detail_district = district_scope
        st.caption(f"District detail is pinned to `{district_scope}` by your current workspace scope.")
    else:
        default_district = None
        if district_heatmap_rows:
            top_row = max(district_heatmap_rows, key=lambda row: to_float(row.get("intensity")))
            default_district = str(top_row.get("district") or "")
        if query_district in available_districts:
            default_district = query_district
        if not default_district and available_districts:
            default_district = available_districts[0]
        detail_district = st.selectbox(
            "District detail lens",
            available_districts,
            index=available_districts.index(default_district) if default_district in available_districts else 0,
            key="geo_detail_district",
        ) if available_districts else None
    set_query_param("ops_district", detail_district)

    district_link_getter = lambda row: build_query_url({"ops_district": row.get("district")})
    station_link_getter = lambda row: build_query_url({"ops_district": row.get("district")})

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
    statewide_boundary_rows = raw_rows_from_result(api_get("/geo/boundaries", params={"boundary_type": "district"}))
    detail_boundary_rows = raw_rows_from_result(
        api_get("/geo/boundaries", params=compact_params({"district": detail_district}) or None)
    )
    detail_geofence_zone_rows = raw_rows_from_result(
        api_get("/geo/geofences", params=compact_params({"district": detail_district}) or None)
    )
    statewide_geofence_zone_rows = raw_rows_from_result(api_get("/geo/geofences"))
    statewide_hotspot_rows = rows_from_result(api_get("/hotspot-forecasts"))
    statewide_patrol_rows = rows_from_result(api_get("/patrol-coverage"))
    detail_hotspot_rows = rows_from_result(
        api_get("/hotspot-forecasts", params=compact_params({"district": detail_district}) or None)
    )
    detail_patrol_rows = rows_from_result(
        api_get("/patrol-coverage", params=compact_params({"district": detail_district}) or None)
    )
    cluster_rows = rows_from_result(api_get("/fusion/clusters"))
    suspect_rows = rows_from_result(api_get("/suspect-dossiers"))
    scoped_case_rows = rows_from_result(api_get("/cases"))

    selected_district_map_rows = build_district_map_rows(district_heatmap_rows, selected_district=detail_district)
    cctv_district_rows = build_cctv_district_rows(
        district_map_rows,
        statewide_geofence_rows,
        statewide_hotspot_rows,
        statewide_patrol_rows,
    )
    statewide_cctv_station_rows = build_cctv_station_rows(statewide_station_map_rows)
    cctv_station_rows = build_cctv_station_rows(station_map_rows)
    statewide_circle_rows = build_police_circle_rows(statewide_station_map_rows)
    detail_circle_rows = build_police_circle_rows(station_map_rows)
    movement_flow_rows = build_movement_flow_rows(district_map_rows, cluster_rows)
    focused_flow_rows = [
        row for row in movement_flow_rows
        if detail_district in {row.get("source_district"), row.get("target_district")}
    ] or movement_flow_rows[:12]
    route_rows = build_route_rows(district_map_rows, movement_flow_rows, suspect_rows, scoped_case_rows)
    route_rows = [
        row for row in route_rows
        if not detail_district or detail_district in set(str(item) for item in row.get("districts", []))
    ] or build_route_rows(district_map_rows, movement_flow_rows[:12], suspect_rows, scoped_case_rows)
    statewide_corridor_rows = raw_rows_from_result(api_get("/geo/corridors"))
    corridor_rows = raw_rows_from_result(
        api_get("/geo/corridors", params=compact_params({"district": detail_district}) or None)
    ) or statewide_corridor_rows
    corridor_camera_rows = rows_from_result(
        api_get("/geo/corridor-camera-coupling", params=compact_params({"district": detail_district}) or None)
    ) or rows_from_result(api_get("/geo/corridor-camera-coupling"))
    route_option_map = {f"{row.get('subject_label')} | {row.get('route_type')}": str(row.get("route_id")) for row in route_rows}
    query_route = get_query_param("ops_route")
    if query_route and route_rows and st.session_state.get("geo_route_id") != query_route:
        st.session_state.geo_route_id = query_route
    selected_route_id = None
    if route_option_map:
        reverse_option_map = {value: key for key, value in route_option_map.items()}
        default_route_label = reverse_option_map.get(query_route) or next(iter(route_option_map))
        selected_route_label = st.selectbox("Tracked route overlay", list(route_option_map.keys()), index=list(route_option_map.keys()).index(default_route_label), key="geo_selected_route")
        selected_route_id = route_option_map.get(selected_route_label)
        set_query_param("ops_route", selected_route_id)
    statewide_checkpoint_rows = rows_from_result(api_get("/checkpoint-plans"))
    detail_checkpoint_rows = [
        row for row in statewide_checkpoint_rows
        if str(row.get("district")) == str(detail_district)
    ]
    statewide_blind_spot_rows = build_blind_spot_rows(statewide_cctv_station_rows, statewide_patrol_rows, statewide_geofence_rows)
    detail_blind_spot_rows = build_blind_spot_rows(cctv_station_rows, detail_patrol_rows, geofence_rows)
    statewide_camera_registry_rows = build_camera_registry_rows(statewide_cctv_station_rows)
    detail_camera_registry_rows = [row for row in statewide_camera_registry_rows if str(row.get("district")) == str(detail_district)]
    playback_rows = build_incident_playback_rows(incident_rows, station_map_rows)

    total_incidents = sum(to_int(row.get("incident_count")) for row in district_map_rows)
    max_intensity = max((to_float(row.get("intensity")) for row in district_map_rows), default=0.0)
    active_geofences = sum(1 for row in geofence_rows if str(row.get("active")).lower() == "yes")
    active_geofence_zones = sum(1 for row in detail_geofence_zone_rows if str(row.get("status")).lower() == "active")
    total_recommended_cameras = sum(to_int(row.get("recommended_cameras")) for row in cctv_district_rows)
    active_checkpoints = sum(1 for row in statewide_checkpoint_rows if str(row.get("status")).lower() in {"active", "deployed"})
    visible_boundary_rows = list(statewide_boundary_rows)
    for row in detail_boundary_rows:
        if row not in visible_boundary_rows:
            visible_boundary_rows.append(row)
    render_metric_grid(
        [
            ("Districts Mapped", len(district_map_rows)),
            ("Movement Flows", len(movement_flow_rows)),
            ("Operational Corridors", len(statewide_corridor_rows)),
            ("Tracked Routes", len(route_rows)),
            ("Police Station Circles", len(statewide_circle_rows)),
            ("District Incidents", total_incidents),
            ("Peak District Intensity", round(max_intensity, 2)),
            ("Recommended CCTV Units", total_recommended_cameras),
            ("Checkpoint Plans", len(statewide_checkpoint_rows)),
            ("Active Checkpoints", active_checkpoints),
            ("Detail District", detail_district or "N/A"),
            ("Stations Visible", len(station_map_rows)),
            ("Filtered Incidents", len(incident_rows)),
            ("Geofence Alerts", len(geofence_rows)),
            ("Active Geofences", active_geofences),
            ("Boundary Layers", len(visible_boundary_rows)),
            ("Editable Geofences", len(detail_geofence_zone_rows) or len(statewide_geofence_zone_rows)),
            ("Active Geo Zones", active_geofence_zones),
        ]
    )

    tabs = st.tabs(["Situation", "Movement Flows", "Corridors", "CCTV Ops", "Police Circles", "Routes", "GIS and Checkpoints", "Timeline Playback"])
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
                    link_getter=district_link_getter,
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
                        link_getter=station_link_getter,
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
            "Cross-district movement flows are inferred from fusion-cluster overlap and case-linked convergence. Use them as movement hypotheses for operational coordination and interdiction planning."
        )
        flow_left, flow_right = st.columns([1.16, 0.84])
        with flow_left:
            render_geo_html(
                build_flow_svg(
                    "Tamil Nadu District-to-District Flow Map",
                    "Flow weight indicates converging case, entity, and cluster movement pressure across districts.",
                    selected_district_map_rows,
                    movement_flow_rows[:18],
                    selected_district=detail_district,
                    link_getter=district_link_getter,
                ),
                height=920,
            )
        with flow_right:
            render_table(
                "Focused District Flows",
                focused_flow_rows,
                caption="Highest-weight district flows touching the active drill-down district.",
                limit=14,
            )
            render_table(
                "Fusion Cluster Members",
                [row for row in cluster_rows if detail_district in {str(row.get('district'))}],
                caption="Cluster members inside the current district lens.",
                limit=14,
            )

    with tabs[2]:
        render_inline_note(
            "Operational corridors blend route intelligence, surveillance priority, and district sequencing. Use them to place checkpoints, corridor cameras, and patrol saturation against repeated movement lanes."
        )
        corridor_left, corridor_right = st.columns([1.16, 0.84])
        with corridor_left:
            render_geo_html(
                build_corridor_svg(
                    "Operational Corridor Overlay",
                    "Corridors are seeded from operational route intelligence and connector-backed movement hypotheses.",
                    selected_district_map_rows,
                    corridor_rows,
                    selected_district=detail_district,
                    link_getter=district_link_getter,
                ),
                height=920,
            )
        with corridor_right:
            render_table(
                "Corridor Registry",
                corridor_rows,
                caption="Visible corridor layers with route reference, risk score, and surveillance priority.",
                limit=18,
            )
            render_table(
                "Corridor-Camera Coupling",
                corridor_camera_rows,
                caption="Recommended camera posture and assignment density against each operational corridor.",
                limit=14,
            )
            render_table(
                "Checkpoint Coupling",
                [
                    row for row in statewide_checkpoint_rows
                    if not corridor_rows or str(row.get("route_ref")) in {str(corridor.get("route_ref")) for corridor in corridor_rows}
                ],
                caption="Checkpoint plans currently coupled to corridor-linked route references.",
                limit=14,
            )

    with tabs[3]:
        render_inline_note(
            "CCTV planning and blind-spot heatmaps are derived from district intensity, anomaly load, hotspot forecasts, patrol gaps, and geofence activity. These are deployment recommendations rather than claims of live camera access."
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
                    link_getter=district_link_getter,
                ),
                height=920,
            )
        with cctv_right:
            if detail_blind_spot_rows:
                render_geo_html(
                    build_geo_svg(
                        "District Blind-Spot Heatmap",
                        f"Blind-spot intensity and camera reinforcement zones for {detail_district}.",
                        detail_blind_spot_rows,
                        point_label_key="station_name",
                        intensity_key="blind_spot_score",
                        value_key="coverage_gap_pct",
                        coverage_key="blind_spot_score",
                        height=700,
                        link_getter=station_link_getter,
                    ),
                    height=830,
                )
            else:
                render_inline_note("District blind-spot heatmap appears once station and patrol activity are available.")

        cctv_lower_left, cctv_lower_right = st.columns(2)
        with cctv_lower_left:
            render_table(
                "Statewide CCTV Deployment Matrix",
                cctv_district_rows,
                caption="District-level CCTV reinforcement options across Tamil Nadu, including PTZ, dome, ANPR, and mobile tower recommendations.",
                limit=38,
            )
            render_table(
                "Camera Registry",
                statewide_camera_registry_rows,
                caption="Planned statewide camera registry entries, including device type, zone label, retention profile, and blind-spot priority.",
                limit=30,
            )
        with cctv_lower_right:
            render_table(
                "District Camera Packages",
                cctv_station_rows,
                caption="Station-level camera packages for the selected district, including watch posture and blind-spot risk.",
                limit=20,
            )
            render_table(
                "Blind-Spot Registry",
                detail_blind_spot_rows,
                caption="Blind-spot risk, coverage gap percentage, and recommended action by station inside the active district lens.",
                limit=20,
            )

    with tabs[4]:
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
                    link_getter=station_link_getter,
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
                        link_getter=station_link_getter,
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

    with tabs[5]:
        render_inline_note(
            "Tracked routes combine district-to-district linkage pressure, suspect threat posture, and high-priority case corridors. Use the selected route overlay to inspect likely movement chains."
        )
        route_left, route_right = st.columns([1.14, 0.86])
        with route_left:
            render_geo_html(
                build_route_svg(
                    "Vehicle and Suspect Route Overlay",
                    "Orange polylines represent suspect trails. Blue polylines represent vehicle-interest corridors.",
                    selected_district_map_rows,
                    route_rows,
                    selected_route_id=selected_route_id,
                    selected_district=detail_district,
                    link_getter=district_link_getter,
                ),
                height=920,
            )
        with route_right:
            selected_route_row = next((row for row in route_rows if str(row.get("route_id")) == str(selected_route_id)), route_rows[0] if route_rows else {})
            render_metric_grid(
                [
                    ("Selected Route", selected_route_row.get("route_type", "N/A")),
                    ("Risk Score", selected_route_row.get("risk_score", "N/A")),
                    ("Stops", len(selected_route_row.get("districts", [])) if selected_route_row else 0),
                ]
            )
            render_table(
                "Route Registry",
                route_rows,
                caption="Tracked suspect and vehicle routes inferred from district linkages and case pressure.",
                limit=20,
            )
            if selected_route_row:
                render_table(
                    "Selected Route Stops",
                    [
                        {
                            "route_id": selected_route_row.get("route_id"),
                            "subject_label": selected_route_row.get("subject_label"),
                            "route_type": selected_route_row.get("route_type"),
                            "stop_order": index + 1,
                            "district": district_name,
                        }
                        for index, district_name in enumerate(selected_route_row.get("districts", []))
                    ],
                    caption="Ordered district stops for the selected route overlay.",
                    limit=10,
                )

    with tabs[6]:
        render_inline_note(
            "Boundary layers now stack district, station, and patrol-sector geometry with editable geofences and checkpoint planning. These remain operational planning layers rather than legal cadastral maps."
        )
        gis_left, gis_right = st.columns([1.15, 0.85])
        with gis_left:
            render_geo_html(
                build_boundary_layer_svg(
                    "Operational Boundary and Geofence Map",
                    "District, station, patrol-sector, geofence, and checkpoint layers are aligned in one editable planning surface.",
                    visible_boundary_rows,
                    detail_geofence_zone_rows or statewide_geofence_zone_rows,
                    statewide_checkpoint_rows,
                    selected_district=detail_district,
                    link_getter=district_link_getter,
                ),
                height=920,
            )
        with gis_right:
            render_table(
                "Checkpoint Registry",
                detail_checkpoint_rows or statewide_checkpoint_rows,
                caption="Checkpoint plans in the active district lens, including route assignment, status, unit, and notes.",
                limit=18,
            )
            render_table(
                "Boundary Registry",
                detail_boundary_rows or statewide_boundary_rows,
                caption="District, station, and patrol-sector boundary rows visible to the active lens.",
                limit=18,
            )
            render_table(
                "Editable Geofences",
                detail_geofence_zone_rows or statewide_geofence_zone_rows,
                caption="Operational geofence zones with geometry, status, and district alignment.",
                limit=12,
            )
            with st.expander("Create checkpoint plan", expanded=False):
                route_choices = ["None"] + list(route_option_map.keys())
                district_row = next((row for row in district_map_rows if str(row.get("district")) == str(detail_district)), {})
                with st.form("checkpoint_plan_form"):
                    checkpoint_name = st.text_input("Checkpoint name")
                    checkpoint_type = st.selectbox("Checkpoint type", ["vehicle_intercept", "device_screening", "perimeter_lock", "patrol_gate"], index=0)
                    checkpoint_status = st.selectbox("Status", ["planned", "active", "deployed", "completed"], index=0)
                    assigned_unit = st.text_input("Assigned unit")
                    selected_checkpoint_route = st.selectbox("Linked route", route_choices, index=0)
                    checkpoint_latitude = st.text_input("Latitude", value=str(district_row.get("latitude") or ""))
                    checkpoint_longitude = st.text_input("Longitude", value=str(district_row.get("longitude") or ""))
                    checkpoint_notes = st.text_area("Checkpoint notes", height=110)
                    if st.form_submit_button("Create checkpoint plan", use_container_width=True):
                        payload = {
                            "district": detail_district or district_scope,
                            "checkpoint_name": checkpoint_name,
                            "checkpoint_type": checkpoint_type,
                            "route_ref": None if selected_checkpoint_route == "None" else route_option_map.get(selected_checkpoint_route),
                            "status": checkpoint_status,
                            "assigned_unit": assigned_unit or None,
                            "latitude": to_float(checkpoint_latitude) if str(checkpoint_latitude).strip() else None,
                            "longitude": to_float(checkpoint_longitude) if str(checkpoint_longitude).strip() else None,
                            "case_id": selected_case_id,
                            "notes": checkpoint_notes or None,
                        }
                        run_action_and_refresh(
                            "/checkpoint-plans",
                            payload=payload,
                            success_message="Checkpoint plan created.",
                        )
            with st.expander("Create editable geofence", expanded=False):
                station_options = ["Unspecified"] + sorted({str(row.get("station_name")) for row in station_map_rows if row.get("station_name")})
                district_row = next((row for row in district_map_rows if str(row.get("district")) == str(detail_district)), {})
                with st.form("geofence_zone_form"):
                    zone_name = st.text_input("Zone name")
                    geofence_type = st.selectbox("Geofence type", ["watch_zone", "movement_watch", "high_watch", "device_sweep", "camera_priority"], index=0)
                    station_name = st.selectbox("Station anchor", station_options, index=0)
                    center_lat = st.text_input("Center latitude", value=str(district_row.get("latitude") or ""))
                    center_lon = st.text_input("Center longitude", value=str(district_row.get("longitude") or ""))
                    radius_km = st.slider("Radius (km)", 1.0, 12.0, 3.5, 0.5)
                    zone_status = st.selectbox("Zone status", ["active", "planned", "paused"], index=0)
                    zone_notes = st.text_area("Zone notes", height=100)
                    if st.form_submit_button("Create geofence zone", use_container_width=True):
                        payload = {
                            "district": detail_district or district_scope,
                            "zone_name": zone_name,
                            "geofence_type": geofence_type,
                            "station_name": None if station_name == "Unspecified" else station_name,
                            "center_latitude": to_float(center_lat),
                            "center_longitude": to_float(center_lon),
                            "radius_km": radius_km,
                            "status": zone_status,
                            "notes": zone_notes or None,
                        }
                        run_action_and_refresh(
                            "/geo/geofences",
                            payload=payload,
                            success_message="Geofence zone created.",
                        )

    with tabs[7]:
        render_inline_note(
            "Timeline playback reconstructs filtered incidents in chronological order. Slide through the sequence to see how the incident picture escalates across the selected district."
        )
        if playback_rows:
            playback_max = len(playback_rows)
            playback_default = clamp_session_int("geo_playback_step", 1, playback_max, playback_max)
            playback_step = st.slider("Playback step", 1, playback_max, playback_default, key="geo_playback_step")
            visible_playback_rows = playback_rows[:playback_step]
            current_playback_row = visible_playback_rows[-1]
            playback_left, playback_right = st.columns([1.12, 0.88])
            with playback_left:
                render_geo_html(
                    build_geo_svg(
                        "Incident Timeline Playback",
                        f"Sequence through {playback_max} incidents in {detail_district or 'the active district lens'}. Current focus is step {playback_step}.",
                        visible_playback_rows,
                        point_label_key="sequence_label",
                        selected_label=str(current_playback_row.get("sequence_label")),
                        intensity_key="intensity",
                        value_key="severity",
                        show_labels=False,
                        label_stride=999,
                    ),
                    height=920,
                )
            with playback_right:
                render_metric_grid(
                    [
                        ("Playback Step", playback_step),
                        ("Current Category", current_playback_row.get("category", "N/A")),
                        ("Current Severity", current_playback_row.get("severity", "N/A")),
                        ("Current Station", current_playback_row.get("station_name", "N/A")),
                    ]
                )
                render_table(
                    "Current Incident Focus",
                    [current_playback_row],
                    caption="Current incident in the playback sequence.",
                    limit=1,
                )
                render_table(
                    "Playback Timeline",
                    list(reversed(visible_playback_rows)),
                    caption="Incidents revealed so far in the playback sequence.",
                    limit=20,
                )
        else:
            render_inline_note("No incident playback sequence is available for the active district and filter set.")


def render_graph_fabric(district_scope: str, selected_case_id: int | None) -> None:
    district_param = None if district_scope == DEFAULT_DISTRICT_SCOPE else district_scope
    entity_rows = rows_from_result(api_get("/graph/entities"))
    link_rows = rows_from_result(api_get("/graph/links"))
    if district_scope != DEFAULT_DISTRICT_SCOPE:
        entity_rows = [row for row in entity_rows if str(row.get("district")) == district_scope]

    case_graph_payload: dict[str, Any] | None = None
    if selected_case_id is not None:
        case_graph_result = api_get(f"/graph/case/{selected_case_id}")
        if case_graph_result.get("ok") and isinstance(case_graph_result.get("data"), dict):
            case_graph_payload = case_graph_result["data"]

    option_map: dict[str, str] = {}
    for row in entity_rows:
        option_map[f"{row.get('name')} | {row.get('type')} | {row.get('district') or 'statewide'}"] = f"entity-{row.get('id')}"
    if case_graph_payload:
        for row in payload_to_rows(case_graph_payload.get("nodes")):
            node_id = str(row.get("id") or "")
            if node_id:
                option_map[f"{row.get('label')} | {row.get('type')}"] = node_id

    query_node_id = get_query_param("ops_node")
    if query_node_id and query_node_id in option_map.values() and st.session_state.get("graph_focus_node") != query_node_id:
        st.session_state.graph_focus_node = query_node_id
    selected_node_id = query_node_id if query_node_id in option_map.values() else None
    if option_map:
        reverse_option_map = {value: key for key, value in option_map.items()}
        default_label = reverse_option_map.get(selected_node_id) or next(iter(option_map))
        selected_label = st.selectbox(
            "Graph focus node",
            list(option_map.keys()),
            index=list(option_map.keys()).index(default_label),
            key="graph_focus_select",
        )
        selected_node_id = option_map[selected_label]
        set_query_param("ops_node", selected_node_id)

    payload = build_graph_canvas_payload(
        entity_rows=entity_rows,
        link_rows=link_rows,
        case_graph_payload=case_graph_payload,
        district_scope=district_scope,
        selected_node_id=selected_node_id,
    )
    saved_view_rows = raw_rows_from_result(
        api_get(
            "/graph/saved-views",
            params=compact_params(
                {
                    "district": district_param,
                    "case_id": selected_case_id,
                }
            ) or None,
        )
    )
    node_link_getter = lambda row: build_query_url({"ops_node": row.get("id")})
    selected_node = payload.get("selected_node") or {}
    selected_entity_id = None
    if str(selected_node_id or "").startswith("entity-"):
        selected_entity_id = to_optional_int(str(selected_node_id).split("-", 1)[1])
    profile_result = api_get(f"/ontology/entities/{selected_entity_id}/profile") if selected_entity_id is not None else {"ok": False, "data": {}}
    profile_payload = profile_result.get("data") if profile_result.get("ok") and isinstance(profile_result.get("data"), dict) else {}
    ontology_summary = api_get("/ontology/summary", params=compact_params({"district": district_param}) or None).get("data")
    resolution_summary = api_get("/entity-resolution/summary", params=compact_params({"district": district_param}) or None).get("data")
    provenance_summary = api_get("/provenance/summary", params=compact_params({"district": district_param}) or None).get("data")
    ontology_class_rows = rows_from_result(api_get("/ontology/classes"))
    relationship_rows = rows_from_result(api_get("/ontology/relationship-types"))
    resolution_rows = rows_from_result(api_get("/entity-resolution/candidates", params=compact_params({"district": district_param, "entity_id": selected_entity_id}) or None))
    decision_rows = rows_from_result(api_get("/entity-resolution/decisions", params=compact_params({"district": district_param}) or None))
    provenance_rows = rows_from_result(api_get("/provenance/records", params=compact_params({"district": district_param, "entity_id": selected_entity_id, "case_id": selected_case_id}) or None))
    attribute_rows = payload_to_rows(profile_payload.get("attributes"))

    render_hero(
        "Graph Fabric",
        "Interactive graph intelligence for entities, cases, evidence, linked relationships, ontology facts, entity resolution, and provenance across the active operational scope.",
        eyebrow="Entity Graph Intelligence",
        chips=[
            f"District scope: {district_scope}",
            f"Case focus: {selected_case_id if selected_case_id is not None else 'none'}",
            f"Nodes: {len(payload.get('nodes', []))}",
            f"Edges: {len(payload.get('edges', []))}",
            f"Resolution candidates: {len(resolution_rows)}",
        ],
    )
    render_metric_grid(
        [
            ("Canvas Nodes", len(payload.get("nodes", []))),
            ("Canvas Edges", len(payload.get("edges", []))),
            ("Linked Neighbors", len(payload.get("linked_rows", []))),
            ("Selected Type", selected_node.get("type", "N/A")),
            ("Selected District", selected_node.get("district", "N/A")),
            ("Risk Score", selected_node.get("risk_score", "N/A")),
            ("Attribute Facts", len(attribute_rows)),
            ("Provenance Rows", len(provenance_rows)),
        ]
    )

    tabs = st.tabs(["Canvas", "Expand", "Trace and Compare", "Ontology Lens", "Saved Views"])
    with tabs[0]:
        graph_left, graph_right = st.columns([1.2, 0.8])
        with graph_left:
            render_geo_html(
                build_graph_svg(
                    "Entity Graph Canvas",
                    "Click nodes to refocus the graph around a suspect, vehicle, case, or evidence object.",
                    payload.get("nodes", []),
                    payload.get("edges", []),
                    selected_node_id=payload.get("selected_node_id"),
                    link_getter=node_link_getter,
                ),
                height=920,
            )
        with graph_right:
            render_table(
                "Selected Node",
                [selected_node] if selected_node else [],
                caption="Attributes for the currently selected graph node.",
                limit=1,
            )
            render_table(
                "Linked Neighbors",
                payload.get("linked_rows", []),
                caption="Immediate relationships and linked peers for the focused node.",
                limit=20,
            )
            if case_graph_payload:
                render_table(
                    "Case Graph Snapshot",
                    [case_graph_payload.get("snapshot", {})] if case_graph_payload.get("snapshot") else [],
                    caption="Current case graph density and summary for the active case lens.",
                    limit=1,
                )

        lower_left, lower_right = st.columns(2)
        with lower_left:
            render_table(
                "Entity Registry",
                sorted(entity_rows, key=lambda row: to_float(row.get("risk_score")), reverse=True),
                caption="Entity registry rows available in the current scope.",
                limit=25,
            )
        with lower_right:
            render_table(
                "Graph Edge Ledger",
                payload.get("edges", []),
                caption="Visible graph links currently rendered on the canvas.",
                limit=25,
            )

    with tabs[1]:
        depth = st.slider("Expansion depth", 1, 3, 2, key="graph_expand_depth")
        expand_result = api_get(
            "/graph/expand",
            params=compact_params(
                {
                    "node_id": selected_node_id,
                    "district": None if district_scope == DEFAULT_DISTRICT_SCOPE else district_scope,
                    "case_id": selected_case_id,
                    "depth": depth,
                }
            ) or None,
        )
        if expand_result.get("ok") and isinstance(expand_result.get("data"), dict):
            expand_payload = expand_result["data"]
            expand_left, expand_right = st.columns([1.15, 0.85])
            with expand_left:
                render_geo_html(
                    build_graph_svg(
                        "Expanded Neighborhood",
                        "Neighborhood expansion grows outward from the focused node to reveal related entities and case-linked objects.",
                        payload_to_rows(expand_payload.get("nodes")),
                        payload_to_rows(expand_payload.get("edges")),
                        selected_node_id=str((expand_payload.get("center_node") or {}).get("id") or selected_node_id),
                        link_getter=node_link_getter,
                    ),
                    height=920,
                )
            with expand_right:
                render_table(
                    "Expanded Nodes",
                    payload_to_rows(expand_payload.get("nodes")),
                    caption="Nodes revealed at the selected expansion depth.",
                    limit=24,
                )
                render_table(
                    "Expanded Edges",
                    payload_to_rows(expand_payload.get("edges")),
                    caption="Edges participating in the expanded neighborhood.",
                    limit=24,
                )
        else:
            render_result_error(expand_result, "Graph Expansion")

    with tabs[2]:
        compare_options = {label: value for label, value in option_map.items() if value != selected_node_id}
        selected_compare_node = None
        if compare_options:
            selected_compare_label = st.selectbox("Trace and compare with", list(compare_options.keys()), key="graph_compare_node")
            selected_compare_node = compare_options.get(selected_compare_label)

        if selected_compare_node:
            trace_result = api_get(
                "/graph/trace",
                params=compact_params(
                    {
                        "source_node_id": selected_node_id,
                        "target_node_id": selected_compare_node,
                        "district": None if district_scope == DEFAULT_DISTRICT_SCOPE else district_scope,
                        "case_id": selected_case_id,
                    }
                ) or None,
            )
            compare_result = api_get(
                "/graph/compare",
                params=compact_params(
                    {
                        "left_node_id": selected_node_id,
                        "right_node_id": selected_compare_node,
                        "district": None if district_scope == DEFAULT_DISTRICT_SCOPE else district_scope,
                        "case_id": selected_case_id,
                    }
                ) or None,
            )
            compare_left, compare_right = st.columns([1.08, 0.92])
            with compare_left:
                if trace_result.get("ok") and isinstance(trace_result.get("data"), dict):
                    trace_payload = trace_result["data"]
                    render_metric_grid(
                        [
                            ("Path Found", "Yes" if trace_payload.get("path_found") else "No"),
                            ("Hop Count", trace_payload.get("hop_count", 0)),
                        ]
                    )
                    render_geo_html(
                        build_graph_svg(
                            "Shortest Trace Path",
                            "The trace path highlights the shortest graph route between the two selected nodes.",
                            payload_to_rows(trace_payload.get("path_nodes")),
                            payload_to_rows(trace_payload.get("path_edges")),
                            selected_node_id=selected_node_id,
                            link_getter=node_link_getter,
                        ),
                        height=860,
                    )
                else:
                    render_result_error(trace_result, "Graph Trace")
            with compare_right:
                if compare_result.get("ok") and isinstance(compare_result.get("data"), dict):
                    compare_payload = compare_result["data"]
                    render_metric_grid(
                        [
                            ("Overlap Ratio", compare_payload.get("overlap_ratio", 0)),
                            ("Risk Delta", compare_payload.get("risk_delta", 0)),
                            ("Shared Neighbors", len(payload_to_rows(compare_payload.get("shared_neighbors")))),
                        ]
                    )
                    render_table(
                        "Shared Neighbors",
                        payload_to_rows(compare_payload.get("shared_neighbors")),
                        caption="Neighbors shared by both selected nodes.",
                        limit=18,
                    )
                    render_table(
                        "Left-Unique Neighbors",
                        payload_to_rows(compare_payload.get("left_unique_neighbors")),
                        caption="Neighbors only linked to the focused left-hand node.",
                        limit=12,
                    )
                    render_table(
                        "Right-Unique Neighbors",
                        payload_to_rows(compare_payload.get("right_unique_neighbors")),
                        caption="Neighbors only linked to the comparison node.",
                        limit=12,
                    )
                else:
                    render_result_error(compare_result, "Graph Compare")

    with tabs[3]:
        ontology_summary_payload = ontology_summary if isinstance(ontology_summary, dict) else {}
        resolution_summary_payload = resolution_summary if isinstance(resolution_summary, dict) else {}
        provenance_summary_payload = provenance_summary if isinstance(provenance_summary, dict) else {}
        ontology_counts = ontology_summary_payload.get("summary") or {}
        resolution_counts = resolution_summary_payload.get("summary") or {}
        provenance_counts = provenance_summary_payload.get("summary") or {}
        render_metric_grid(
            [
                ("Ontology Classes", ontology_counts.get("ontology_classes", 0)),
                ("Relation Types", ontology_counts.get("relationship_types", 0)),
                ("Entities in Scope", ontology_counts.get("entities_in_scope", 0)),
                ("Attribute Facts", ontology_counts.get("attribute_facts", 0)),
                ("Resolution Pending", resolution_counts.get("pending", 0)),
                ("Resolution Accepted", resolution_counts.get("accepted", 0)),
                ("Avg Match Score", resolution_counts.get("avg_match_score", 0)),
                ("Provenance Records", provenance_counts.get("record_count", 0)),
                ("Distinct Sources", provenance_counts.get("distinct_sources", 0)),
            ]
        )
        ontology_left, ontology_right = st.columns([1.05, 0.95])
        with ontology_left:
            render_table(
                "Ontology Classes",
                ontology_class_rows,
                caption="Core ontology classes available to the graph workbench.",
                limit=16,
            )
            render_table(
                "Relationship Types",
                relationship_rows,
                caption="Declared ontology relationship types and confidence bands.",
                limit=18,
            )
            render_table(
                "Attribute Facts",
                attribute_rows,
                caption="Observed attribute facts for the focused entity node.",
                limit=18,
            )
            render_table(
                "Class Breakdown",
                payload_to_rows(ontology_summary_payload.get("class_breakdown")),
                caption="Coverage of ontology classes by entities and captured attribute facts.",
                limit=12,
            )
        with ontology_right:
            render_table(
                "Entity Profile",
                payload_to_rows(profile_payload.get("entity")),
                caption="Focused entity profile sourced from the ontology workbench.",
                limit=1,
            )
            render_table(
                "Connector Artifacts",
                payload_to_rows(profile_payload.get("connector_artifacts")),
                caption="Connector artifacts linked to the focused entity.",
                limit=12,
            )
            render_table(
                "Provenance Trail",
                payload_to_rows(profile_payload.get("provenance")) or provenance_rows,
                caption="Source lineage and operational provenance for the selected entity or case lens.",
                limit=14,
            )
            render_table(
                "Source Breakdown",
                payload_to_rows(provenance_summary_payload.get("source_breakdown")),
                caption="Provenance density by source system or evidence lane.",
                limit=12,
            )

        resolution_left, resolution_right = st.columns([1.04, 0.96])
        with resolution_left:
            render_table(
                "Resolution Candidates",
                payload_to_rows(profile_payload.get("resolution_candidates")) or resolution_rows,
                caption="Entity-resolution candidates connected to the focused entity or current district scope.",
                limit=16,
            )
            render_table(
                "Resolution Decisions",
                payload_to_rows(profile_payload.get("resolution_decisions")) or decision_rows,
                caption="Analyst decisions previously recorded against candidate merges or reviews.",
                limit=12,
            )
            render_table(
                "Resolution Clusters",
                payload_to_rows(resolution_summary_payload.get("clusters")),
                caption="Duplicate-resolution cluster density across the active graph scope.",
                limit=12,
            )
        with resolution_right:
            candidate_rows = payload_to_rows(profile_payload.get("resolution_candidates")) or raw_rows_from_result(
                api_get("/entity-resolution/candidates", params=compact_params({"district": district_param, "entity_id": selected_entity_id}) or None)
            )
            candidate_option_map = {
                f"{row.get('left_entity_name')} ↔ {row.get('right_entity_name')} | {row.get('status')} | {row.get('match_score')}": to_int(row.get("id"))
                for row in candidate_rows
                if row.get("id") not in (None, "N/A")
            }
            if candidate_option_map:
                with st.form("entity_resolution_action_form"):
                    selected_candidate_label = st.selectbox("Resolution candidate", list(candidate_option_map.keys()))
                    decision_status = st.selectbox("Decision", ["accepted", "review", "rejected"], index=0)
                    decision_notes = st.text_area("Decision notes", height=110)
                    if st.form_submit_button("Record resolution decision", use_container_width=True):
                        run_action_and_refresh(
                            "/entity-resolution/resolve",
                            payload={
                                "candidate_id": candidate_option_map[selected_candidate_label],
                                "decision_status": decision_status,
                                "notes": decision_notes or None,
                            },
                            success_message="Resolution decision recorded.",
                        )
            else:
                render_inline_note("Resolution actions appear once a focused entity with ontology profile and duplicate candidate context is selected.")

    with tabs[4]:
        view_left, view_right = st.columns([1.0, 1.0])
        with view_left:
            render_table(
                "Saved Views",
                saved_view_rows,
                caption="Saved graph workbench states for the current analyst.",
                limit=18,
            )
            if saved_view_rows:
                view_option_map = {f"{row.get('title')} | {row.get('district') or 'statewide'}": row for row in saved_view_rows}
                selected_saved_view = st.selectbox("Apply saved view", list(view_option_map.keys()), key="graph_saved_view_select")
                chosen_view = view_option_map[selected_saved_view]
                if st.button("Load focus node", use_container_width=True, key="graph_saved_view_apply"):
                    set_query_param("ops_node", chosen_view.get("focus_node_id"))
                    st.rerun()
        with view_right:
            with st.form("graph_saved_view_form"):
                view_title = st.text_input("Saved view title")
                view_notes = st.text_area("Saved view notes", height=120)
                if st.form_submit_button("Save current view", use_container_width=True):
                    submit_payload = {
                        "title": view_title,
                        "district": None if district_scope == DEFAULT_DISTRICT_SCOPE else district_scope,
                        "case_id": selected_case_id,
                        "focus_node_id": selected_node_id,
                        "selected_node_ids": [row.get("id") for row in payload.get("nodes", []) if row.get("id")],
                        "notes": view_notes or None,
                    }
                    run_action_and_refresh(
                        "/graph/saved-views",
                        payload=submit_payload,
                        success_message="Graph view saved.",
                    )


def render_war_room(
    district_scope: str,
    selected_case_id: int | None,
    me_payload: dict[str, Any],
) -> None:
    district_param = None if district_scope == DEFAULT_DISTRICT_SCOPE else district_scope
    room_rows = rows_from_result(api_get("/internal-comms/rooms", params=compact_params({"district": district_param}) or None))
    presence_rows = rows_from_result(api_get("/personnel/presence", params=compact_params({"district": district_param}) or None))
    video_session_rows = rows_from_result(api_get("/video/sessions", params=compact_params({"district": district_param}) or None))
    snapshot_rows = rows_from_result(api_get("/war-room-snapshots", params=compact_params({"district": district_param}) or None))
    checkpoint_rows = rows_from_result(api_get("/checkpoint-plans", params=compact_params({"district": district_param}) or None))
    district_rows = build_district_map_rows(rows_from_result(api_get("/geo/district-heatmap")))
    cluster_rows = rows_from_result(api_get("/fusion/clusters"))
    suspect_rows = rows_from_result(api_get("/suspect-dossiers"))
    case_rows = rows_from_result(api_get("/cases"))
    flow_rows = build_movement_flow_rows(district_rows, cluster_rows)
    route_rows = build_route_rows(district_rows, flow_rows, suspect_rows, case_rows)
    route_option_map = {f"{row.get('subject_label')} | {row.get('route_type')}": str(row.get("route_id")) for row in route_rows}

    available_rooms = [str(row.get("room_name")) for row in room_rows if row.get("room_name")]
    query_room = get_query_param("ops_room")
    selected_room = query_room if query_room in available_rooms else (available_rooms[0] if available_rooms else "State Command Net")
    if available_rooms:
        selected_room = st.selectbox(
            "War-room thread",
            available_rooms,
            index=available_rooms.index(selected_room),
            key="war_room_thread",
        )
        set_query_param("ops_room", selected_room)
    live_updates = st.checkbox("Live war-room updates", value=False, key="war_room_live_updates")
    activate_live_refresh(live_updates, interval_seconds=18, component_key="war_room_live_refresh")
    maybe_send_presence_heartbeat(selected_room, district_scope, status_label="war_room")

    message_rows = raw_rows_from_result(
        api_get(
            "/internal-comms/messages",
            params=compact_params({"district": district_param, "room_name": selected_room}) or None,
        )
    )
    typing_rows = raw_rows_from_result(
        api_get(
            "/internal-comms/typing",
            params=compact_params({"district": district_param, "room_name": selected_room}) or None,
        )
    )
    selected_room_row = next((row for row in room_rows if str(row.get("room_name")) == str(selected_room)), {})

    online_count = sum(1 for row in presence_rows if str(row.get("is_online")).lower() == "yes")
    unread_total = sum(to_int(row.get("unread_count")) for row in room_rows)
    active_checkpoints = sum(1 for row in checkpoint_rows if str(row.get("status")).lower() in {"active", "deployed"})

    render_hero(
        "War Room",
        "Live coordination layer for room threads, personnel presence, checkpoint actions, and operational escalation context.",
        eyebrow="Real-Time Coordination",
        chips=[
            f"District scope: {district_scope}",
            f"Thread: {selected_room}",
            f"Live updates: {'on' if live_updates else 'off'}",
            f"Unread rooms: {unread_total}",
            f"Video sessions: {len(video_session_rows)}",
        ],
    )
    render_metric_grid(
        [
            ("Online Personnel", online_count),
            ("Room Unread", selected_room_row.get("unread_count", 0)),
            ("Messages in Thread", len(message_rows)),
            ("Typing Signals", len(typing_rows)),
            ("Checkpoint Plans", len(checkpoint_rows)),
            ("Active Checkpoints", active_checkpoints),
            ("War-Room Snapshots", len(snapshot_rows)),
            ("Video Sessions", len(video_session_rows)),
        ]
    )

    tabs = st.tabs(["Operations", "Live Chat", "Video Briefing", "Realtime Signals", "Action Planner"])
    with tabs[0]:
        ops_left, ops_right = st.columns([1.08, 0.92])
        with ops_left:
            render_table(
                "War-Room Snapshots",
                snapshot_rows,
                caption="Current war-room snapshots, command summaries, and active-case posture.",
                limit=12,
            )
            render_table(
                "Presence Board",
                presence_rows,
                caption="Live presence posture across command, fusion, and district personnel.",
                limit=20,
            )
        with ops_right:
            render_table(
                "Coordination Rooms",
                room_rows,
                caption="Room activity, unread counts, and latest-message posture.",
                limit=12,
            )
            render_table(
                "Checkpoint Ledger",
                checkpoint_rows,
                caption="Current checkpoint actions visible to the active district scope.",
                limit=12,
            )
            render_table(
                "Active Typing Signals",
                typing_rows,
                caption="Personnel currently drafting or actively signaling in the selected room.",
                limit=12,
            )

    with tabs[1]:
        chat_left, chat_right = st.columns([1.18, 0.82])
        with chat_left:
            if selected_room and to_int(selected_room_row.get("unread_count")) > 0:
                if st.button("Mark thread as read", use_container_width=True, key="war_room_mark_read"):
                    run_action_and_refresh(
                        "/internal-comms/mark-read",
                        payload={"room_name": selected_room},
                        success_message="Thread marked as read.",
                    )
            render_message_feed(message_rows, empty_message="No war-room traffic has been posted yet.")
        with chat_right:
            render_war_room_socket_panel(selected_room, district_scope)
            channel_scope = st.selectbox("Channel scope", ["statewide", "district", "direct", "case"], index=1 if district_scope != DEFAULT_DISTRICT_SCOPE else 0, key="war_room_channel_scope")
            recipient_choices = ["None"] + [str(row.get("username")) for row in presence_rows if str(row.get("username")) != str(me_payload.get("username") or st.session_state.get("username"))]
            recipient_username = st.selectbox("Direct recipient", recipient_choices, index=0, disabled=channel_scope != "direct", key="war_room_recipient")
            priority = st.selectbox("Priority", ["routine", "medium", "high", "critical"], index=1, key="war_room_priority")
            ack_required = st.checkbox("Acknowledge required", value=True, key="war_room_ack_required")
            mention_choices = [str(row.get("username")) for row in presence_rows if str(row.get("username")) != str(me_payload.get("username") or st.session_state.get("username"))]
            mentioned_usernames = st.multiselect("Mention personnel", mention_choices, key="war_room_mentions")
            attachment_manifest = st.text_area(
                "Attachments (name|type|storage_ref per line)",
                height=90,
                key="war_room_attachment_manifest",
                placeholder="checkpoint-plan.pdf|document|storage://war-room/checkpoint-plan\ncorridor-map.png|image|storage://war-room/corridor-map",
            )
            message_text = st.text_area("Post to war-room thread", height=130, key="war_room_message_draft")
            maybe_send_typing_heartbeat(selected_room, district_scope, selected_case_id, bool(str(message_text).strip()))
            if st.button("Post message", use_container_width=True, key="war_room_post_submit"):
                full_message_text = str(message_text or "").strip()
                if mentioned_usernames:
                    mention_prefix = " ".join(f"@{username}" for username in mentioned_usernames)
                    full_message_text = f"{mention_prefix} {full_message_text}".strip()
                payload = {
                    "room_name": selected_room or "State Command Net",
                    "message_text": full_message_text,
                    "channel_scope": channel_scope,
                    "district": district_param if channel_scope in {"district", "case"} else None,
                    "recipient_username": None if recipient_username == "None" or channel_scope != "direct" else recipient_username,
                    "priority": priority,
                    "ack_required": ack_required,
                    "case_id": selected_case_id if channel_scope == "case" else None,
                    "attachments": parse_attachment_manifest(attachment_manifest),
                }
                st.session_state.war_room_message_draft = ""
                st.session_state.war_room_attachment_manifest = ""
                st.session_state.war_room_mentions = []
                maybe_send_typing_heartbeat(selected_room, district_scope, selected_case_id, False)
                run_action_and_refresh("/internal-comms/messages", payload=payload, success_message="War-room message posted.")

    with tabs[2]:
        render_video_briefing_panel(selected_room, district_scope, selected_case_id, me_payload, presence_rows)

    with tabs[3]:
        signal_left, signal_right = st.columns([1.0, 1.0])
        with signal_left:
            render_table(
                "Typing Board",
                typing_rows,
                caption="Active typing and drafting signals in the selected war-room thread.",
                limit=16,
            )
            render_table(
                "Presence Board",
                presence_rows,
                caption="Online status, room posture, and district scope for visible personnel.",
                limit=16,
            )
        with signal_right:
            render_table(
                "Room Summary",
                room_rows,
                caption="Unread sync, room load, and latest activity across war-room channels.",
                limit=16,
            )
            render_inline_note(
                "Socket monitor provides live event awareness in the selected room. Streamlit still refreshes the wider workspace on the configured live-update cadence so the rest of the board stays synchronized."
            )

    with tabs[4]:
        planner_left, planner_right = st.columns([1.08, 0.92])
        with planner_left:
            render_geo_html(
                build_operational_polygon_svg(
                    "Checkpoint Planner Map",
                    "Operational GIS sectors and checkpoint diamonds for the current war-room scope.",
                    district_rows,
                    checkpoint_rows,
                    selected_district=None if district_scope == DEFAULT_DISTRICT_SCOPE else district_scope,
                    link_getter=lambda row: build_query_url({"ops_district": row.get("district")}),
                ),
                height=880,
            )
        with planner_right:
            render_table(
                "Route Registry",
                route_rows,
                caption="Available suspect and vehicle routes that can be tied to checkpoint actions.",
                limit=18,
            )
            with st.form("war_room_checkpoint_form"):
                checkpoint_name = st.text_input("Checkpoint name")
                checkpoint_type = st.selectbox("Checkpoint type", ["vehicle_intercept", "device_screening", "perimeter_lock", "patrol_gate"], index=0)
                selected_route_label = st.selectbox("Linked route", ["None"] + list(route_option_map.keys()), index=0)
                status = st.selectbox("Status", ["planned", "active", "deployed", "completed"], index=0)
                assigned_unit = st.text_input("Assigned unit")
                district_value = st.text_input("District", value="" if district_scope == DEFAULT_DISTRICT_SCOPE else district_scope)
                lat_value = st.text_input("Latitude")
                lon_value = st.text_input("Longitude")
                notes = st.text_area("Checkpoint notes", height=110)
                if st.form_submit_button("Create war-room checkpoint", use_container_width=True):
                    payload = {
                        "district": district_value,
                        "checkpoint_name": checkpoint_name,
                        "checkpoint_type": checkpoint_type,
                        "route_ref": None if selected_route_label == "None" else route_option_map.get(selected_route_label),
                        "status": status,
                        "assigned_unit": assigned_unit or None,
                        "latitude": to_float(lat_value) if str(lat_value).strip() else None,
                        "longitude": to_float(lon_value) if str(lon_value).strip() else None,
                        "case_id": selected_case_id,
                        "notes": notes or None,
                    }
                    run_action_and_refresh("/checkpoint-plans", payload=payload, success_message="Checkpoint action created.")


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
    room_rows = rows_from_result(
        api_get(
            "/internal-comms/rooms",
            params=compact_params({"district": district_param}) or None,
        )
    )
    available_rooms = [str(row.get("room_name")) for row in room_rows if row.get("room_name")]
    query_room = get_query_param("ops_room")
    if query_room in available_rooms and st.session_state.get("comms_room_selector") != query_room:
        st.session_state.comms_room_selector = query_room
    if available_rooms:
        default_room = query_room if query_room in available_rooms else available_rooms[0]
        selected_room = st.selectbox(
            "Coordination room",
            available_rooms,
            index=available_rooms.index(default_room),
            key="comms_room_selector",
        )
        set_query_param("ops_room", selected_room)
    else:
        selected_room = None

    message_rows = raw_rows_from_result(
        api_get(
            "/internal-comms/messages",
            params=compact_params(
                {
                    "district": district_param,
                    "room_name": selected_room,
                    "recipient_username": current_username,
                }
            ) or None,
        )
    )
    selected_room_row = next((row for row in room_rows if str(row.get("room_name")) == str(selected_room)), {})
    unread_total = sum(to_int(row.get("unread_count")) for row in room_rows)
    direct_count = sum(1 for row in message_rows if row.get("recipient_username") not in (None, "", "N/A"))
    ack_required_count = sum(1 for row in message_rows if str(row.get("ack_required")).lower() == "yes")

    render_hero(
        "Department Comms",
        "Operational coordination channels for statewide command, district rooms, case escalation, and direct personnel messaging with live thread state.",
        eyebrow="Internal Coordination Fabric",
        chips=[
            f"User: {current_username}",
            f"District lens: {district_scope}",
            f"Rooms: {len(room_rows)}",
            f"Unread: {unread_total}",
        ],
    )

    render_metric_grid(
        [
            ("Personnel Visible", len(directory_rows)),
            ("Active Rooms", len(room_rows)),
            ("Messages Loaded", len(message_rows)),
            ("Room Unread", selected_room_row.get("unread_count", 0)),
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
            if selected_room and to_int(selected_room_row.get("unread_count")) > 0:
                if st.button("Mark selected room as read", use_container_width=True, key="comms_mark_read"):
                    run_action_and_refresh(
                        "/internal-comms/mark-read",
                        payload={"room_name": selected_room},
                        success_message="Room marked as read.",
                    )
            render_message_feed(filtered_message_rows)
        with feed_right:
            render_table(
                "Coordination Rooms",
                room_rows,
                caption="Current rooms, latest activity, and unread-thread posture for the active comms surface.",
                limit=12,
            )
            render_table(
                "Personnel Posture",
                directory_rows,
                caption="Visible personnel roster with role, district scope, and status posture.",
                limit=12,
            )

    with tabs[1]:
        room_choices = available_rooms + [room for room in ["State Command Net", "Cyber Fusion Desk", "District Coordination", "Case Coordination", "Direct Coordination", "Custom Room"] if room not in available_rooms]
        recipient_choices = ["None"] + [str(row.get("username")) for row in directory_rows if row.get("username") != current_username]
        with st.form("department_comms_form"):
            compose_room = st.selectbox("Room", room_choices, index=room_choices.index(selected_room) if selected_room in room_choices else 0)
            custom_room = st.text_input("Custom room name", value="", disabled=compose_room != "Custom Room")
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
            attachment_manifest = st.text_area(
                "Attachments (name|type|storage_ref per line)",
                height=90,
                placeholder="briefing.pdf|document|storage://briefings/tn-01",
            )
            message_text = st.text_area("Message", height=140, placeholder="Type the operational instruction, coordination note, or escalation context.")
            if st.form_submit_button("Send message", use_container_width=True):
                room_name = custom_room.strip() if compose_room == "Custom Room" else compose_room
                payload = {
                    "room_name": room_name or "State Command Net",
                    "message_text": message_text,
                    "channel_scope": channel_scope,
                    "district": compose_district if channel_scope in {"district", "case"} else None,
                    "recipient_username": None if recipient_username == "None" or channel_scope != "direct" else recipient_username,
                    "priority": priority,
                    "ack_required": ack_required,
                    "case_id": selected_case_id if channel_scope == "case" else None,
                    "attachments": parse_attachment_manifest(attachment_manifest),
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
            caption="Rooms currently in use, including unread counts, latest sender, scope, and latest activity.",
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


def render_camera_command(district_scope: str, selected_case_id: int | None) -> None:
    district_param = None if district_scope == DEFAULT_DISTRICT_SCOPE else district_scope
    asset_rows = rows_from_result(api_get("/camera/assets", params=compact_params({"district": district_param}) or None))
    blind_rows = rows_from_result(api_get("/camera/blind-zones", params=compact_params({"district": district_param}) or None))
    incident_rows = rows_from_result(api_get("/incidents", params=compact_params({"district": district_param}) or None))
    assignment_rows = rows_from_result(
        api_get("/camera/assignments", params=compact_params({"district": district_param, "case_id": selected_case_id}) or None)
    )

    degraded_assets = [row for row in asset_rows if str(row.get("status")).lower() in {"degraded", "maintenance"}]
    linked_assignments = [row for row in assignment_rows if str(row.get("status")).lower() in {"linked", "active"}]

    render_hero(
        "Camera Command",
        "Camera registry, blind-zone posture, device health, and incident-linked camera lookup aligned in one surveillance operations workspace.",
        eyebrow="Camera Operations Center",
        chips=[
            f"District scope: {district_scope}",
            f"Case focus: {selected_case_id if selected_case_id is not None else 'none'}",
            f"Assets: {len(asset_rows)}",
            f"Blind zones: {len(blind_rows)}",
        ],
    )
    render_metric_grid(
        [
            ("Camera Assets", len(asset_rows)),
            ("Degraded or Maintenance", len(degraded_assets)),
            ("Blind-Zone Districts", len(blind_rows)),
            ("Linked Camera Assignments", len(linked_assignments)),
        ]
    )

    tabs = st.tabs(["Registry", "Blind Zones", "Incident Lookup"])
    with tabs[0]:
        registry_left, registry_right = st.columns([1.14, 0.86])
        with registry_left:
            if asset_rows:
                render_geo_html(
                    build_geo_svg(
                        "Camera Registry Map",
                        "Camera assets are plotted by location, with intensity reflecting blind-spot pressure and coverage importance.",
                        asset_rows,
                        point_label_key="camera_id",
                        intensity_key="blind_spot_score",
                        value_key="health_score",
                        coverage_key="blind_spot_score",
                        show_labels=False,
                    ),
                    height=920,
                )
            else:
                render_inline_note("Camera assets are not available for the active district scope.")
        with registry_right:
            render_table(
                "Camera Registry",
                asset_rows,
                caption="Camera asset registry with type, health, blind-spot score, retention, and owner unit.",
                limit=24,
            )
            render_table(
                "Degraded Assets",
                degraded_assets,
                caption="Devices needing maintenance, rebalancing, or heartbeat review.",
                limit=12,
            )

    with tabs[1]:
        blind_left, blind_right = st.columns([1.1, 0.9])
        with blind_left:
            if blind_rows:
                render_geo_html(
                    build_geo_svg(
                        "Blind-Zone Heatmap",
                        "Blind-zone intensity blends camera posture, health pressure, and active geofence count.",
                        blind_rows,
                        point_label_key="district",
                        selected_label=None if district_scope == DEFAULT_DISTRICT_SCOPE else district_scope,
                        intensity_key="blind_spot_score",
                        value_key="camera_count",
                        coverage_key="geofence_count",
                    ),
                    height=920,
                )
            else:
                render_inline_note("Blind-zone heatmap appears once camera registry rows are available.")
        with blind_right:
            render_table(
                "Blind-Zone Registry",
                blind_rows,
                caption="District blind-zone pressure and recommended surveillance action.",
                limit=16,
            )
            render_table(
                "Linked Assignments",
                linked_assignments,
                caption="Current camera-to-incident and camera-to-case links.",
                limit=14,
            )

    with tabs[2]:
        incident_option_map = {
            f"Incident {row.get('id')} | {row.get('district')} | {row.get('category')}": to_int(row.get("id"))
            for row in incident_rows
            if row.get("id") not in (None, "N/A")
        }
        selected_incident_id = None
        if incident_option_map:
            selected_incident_label = st.selectbox("Incident lens", list(incident_option_map.keys()), key="camera_incident_lens")
            selected_incident_id = incident_option_map[selected_incident_label]
        scoped_assignment_rows = [
            row for row in assignment_rows
            if selected_incident_id is None or to_int(row.get("incident_id")) == selected_incident_id
        ]
        lookup_left, lookup_right = st.columns([1.0, 1.0])
        with lookup_left:
            render_table(
                "Incident-Linked Cameras",
                scoped_assignment_rows,
                caption="Camera assets currently linked to the active incident or case lens.",
                limit=16,
            )
        with lookup_right:
            camera_option_map = {f"{row.get('camera_id')} | {row.get('camera_type')} | {row.get('district')}": to_int(row.get("id")) for row in asset_rows}
            with st.form("camera_assignment_form"):
                selected_camera_label = st.selectbox("Camera asset", list(camera_option_map.keys()), key="camera_assignment_asset") if camera_option_map else None
                assignment_type = st.selectbox("Assignment type", ["primary_coverage", "incident_cover", "checkpoint_watch", "suspect_route_watch"], index=0)
                assignment_status = st.selectbox("Status", ["linked", "active", "review", "closed"], index=0)
                assignment_notes = st.text_area("Assignment notes", height=110)
                if st.form_submit_button("Link camera to incident", use_container_width=True, disabled=not camera_option_map):
                    payload = {
                        "camera_asset_id": camera_option_map[selected_camera_label],
                        "incident_id": selected_incident_id,
                        "case_id": selected_case_id,
                        "assignment_type": assignment_type,
                        "status": assignment_status,
                        "notes": assignment_notes or None,
                    }
                    run_action_and_refresh("/camera/assignments", payload=payload, success_message="Camera assignment created.")


def render_connector_ops(district_scope: str, selected_case_id: int | None) -> None:
    district_param = None if district_scope == DEFAULT_DISTRICT_SCOPE else district_scope
    connector_rows = rows_from_result(api_get("/connectors"))
    connector_health_rows = rows_from_result(api_get("/connectors/health"))
    adapter_rows = rows_from_result(api_get("/adapter-stubs"))
    run_rows = rows_from_result(api_get("/connectors/runs"))
    artifact_rows = rows_from_result(
        api_get(
            "/connectors/artifacts",
            params=compact_params({"district": district_param, "case_id": selected_case_id}) or None,
        )
    )
    ingest_rows = rows_from_result(api_get("/ingest-queue"))
    running_rows = [row for row in run_rows if str(row.get("status")).lower() == "running"]
    completed_rows = [row for row in run_rows if str(row.get("status")).lower() == "completed"]

    render_hero(
        "Connector Ops",
        "Operational data connectors, sanctioned source registry, run history, artifact ledger, and trigger controls for the ingestion fabric.",
        eyebrow="Operational Data Connectors",
        chips=[
            f"District scope: {district_scope}",
            f"Case focus: {selected_case_id if selected_case_id is not None else 'none'}",
            f"Connectors: {len(connector_rows)}",
            f"Artifacts: {len(artifact_rows)}",
            f"Health rows: {len(connector_health_rows)}",
        ],
    )
    render_metric_grid(
        [
            ("Sanctioned Connectors", len(connector_rows)),
            ("Health Snapshots", len(connector_health_rows)),
            ("Adapter Stubs", len(adapter_rows)),
            ("Connector Runs", len(run_rows)),
            ("Running Runs", len(running_rows)),
            ("Completed Runs", len(completed_rows)),
            ("Artifacts", len(artifact_rows)),
            ("Ingest Queue", len(ingest_rows)),
        ]
    )

    tabs = st.tabs(["Registry", "Health and Freshness", "Run History", "Artifact Ledger", "Trigger Connector"])
    with tabs[0]:
        registry_left, registry_right = st.columns([1.02, 0.98])
        with registry_left:
            render_table(
                "Sanctioned Connector Registry",
                connector_rows,
                caption="Declared operational connector registry, sanctioned status, access mode, and source type.",
                limit=16,
            )
        with registry_right:
            render_table(
                "Adapter Stubs",
                adapter_rows,
                caption="Adapter scaffolds and sanctioned bridge stubs available to the connector fabric.",
                limit=16,
            )
            render_table(
                "Recent Ingest Queue",
                ingest_rows,
                caption="Observed ingest queue items across connector-triggered and seeded flows.",
                limit=16,
            )

    with tabs[1]:
        health_left, health_right = st.columns([1.0, 1.0])
        with health_left:
            render_table(
                "Connector Health",
                connector_health_rows,
                caption="Connector readiness scored across freshness, latency, backlog, and success ratio.",
                limit=16,
            )
        with health_right:
            freshness_buckets = defaultdict(int)
            for row in connector_health_rows:
                freshness_buckets[str(row.get("freshness") or "unknown")] += 1
            render_table(
                "Freshness Breakdown",
                [{"freshness": key, "connector_count": value} for key, value in freshness_buckets.items()],
                caption="How current each sanctioned connector is relative to its latest run or signal.",
                limit=8,
            )

    with tabs[2]:
        run_left, run_right = st.columns([1.0, 1.0])
        with run_left:
            render_table(
                "Connector Run History",
                run_rows,
                caption="Connector run timeline with status, latency, and emitted record counts.",
                limit=20,
            )
        with run_right:
            render_table(
                "Running Connectors",
                running_rows,
                caption="Runs currently marked active or streaming.",
                limit=10,
            )
            render_table(
                "Completed Connectors",
                completed_rows,
                caption="Most recent completed connector runs.",
                limit=10,
            )

    with tabs[3]:
        artifact_left, artifact_right = st.columns([1.06, 0.94])
        with artifact_left:
            render_table(
                "Connector Artifact Ledger",
                artifact_rows,
                caption="Artifacts emitted by operational connectors into the investigation fabric.",
                limit=24,
            )
        with artifact_right:
            connector_names = sorted({str(row.get("connector_name")) for row in artifact_rows if row.get("connector_name")})
            selected_connector_name = st.selectbox("Connector lens", ["All"] + connector_names, key="connector_ops_artifact_lens")
            filtered_rows = artifact_rows if selected_connector_name == "All" else [
                row for row in artifact_rows if str(row.get("connector_name")) == selected_connector_name
            ]
            render_table(
                "Filtered Artifacts",
                filtered_rows,
                caption="Connector artifacts scoped by connector lens.",
                limit=18,
            )

    with tabs[4]:
        connector_option_map = {
            str(row.get("connector_name")): row
            for row in connector_rows
            if row.get("connector_name")
        }
        with st.form("connector_trigger_form"):
            selected_connector = st.selectbox("Connector", list(connector_option_map.keys()) or ["tn_cctns_citizen_portal"])
            run_mode = st.selectbox("Run mode", ["poll", "stream", "manual_refresh"], index=0)
            trigger_notes = st.text_area("Trigger notes", height=110)
            if st.form_submit_button("Trigger connector run", use_container_width=True):
                run_action_and_refresh(
                    "/connectors/runs/trigger",
                    payload={
                        "connector_name": selected_connector,
                        "run_mode": run_mode,
                        "notes": trigger_notes or None,
                    },
                    success_message="Connector run triggered and artifacts emitted.",
                )


def render_dispatch_engine(district_scope: str, selected_case_id: int | None, me_payload: dict[str, Any]) -> None:
    district_param = None if district_scope == DEFAULT_DISTRICT_SCOPE else district_scope
    task_rows = rows_from_result(api_get("/tasks", params=compact_params({"district": district_param, "case_id": selected_case_id}) or None))
    checkpoint_rows = rows_from_result(api_get("/checkpoint-plans", params=compact_params({"district": district_param, "case_id": selected_case_id}) or None))
    playbook_rows = rows_from_result(api_get("/workflow/playbooks", params=compact_params({"district": district_param}) or None))
    workflow_intelligence = api_get("/workflow/intelligence", params=compact_params({"district": district_param, "case_id": selected_case_id}) or None).get("data")
    case_rows = rows_from_result(api_get("/cases"))
    district_rows = build_district_map_rows(rows_from_result(api_get("/geo/district-heatmap")))
    cluster_rows = rows_from_result(api_get("/fusion/clusters"))
    suspect_rows = rows_from_result(api_get("/suspect-dossiers"))
    route_rows = build_route_rows(district_rows, build_movement_flow_rows(district_rows, cluster_rows), suspect_rows, case_rows)

    queued_tasks = [row for row in task_rows if str(row.get("status")).lower() == "queued"]
    approved_tasks = [row for row in task_rows if str(row.get("status")).lower() == "approved"]
    active_tasks = [row for row in task_rows if str(row.get("status")).lower() in {"in_progress", "deployed"}]
    completed_tasks = [row for row in task_rows if str(row.get("status")).lower() in {"completed", "closed"}]
    workflow_summary = workflow_intelligence.get("summary") if isinstance(workflow_intelligence, dict) else {}
    workflow_breakdown = payload_to_rows((workflow_intelligence or {}).get("district_breakdown") if isinstance(workflow_intelligence, dict) else [])

    render_hero(
        "Dispatch Engine",
        "Assignment, approval, execution, and closure workflow for operational actions tied to tasks, checkpoints, routes, and case context.",
        eyebrow="Action Workflow Engine",
        chips=[
            f"District scope: {district_scope}",
            f"Case focus: {selected_case_id if selected_case_id is not None else 'none'}",
            f"Tasks: {len(task_rows)}",
            f"Checkpoints: {len(checkpoint_rows)}",
            f"Playbooks: {len(playbook_rows)}",
        ],
    )
    render_metric_grid(
        [
            ("Queued", len(queued_tasks)),
            ("Approved", len(approved_tasks)),
            ("Active", len(active_tasks)),
            ("Completed", len(completed_tasks)),
            ("Checkpoint Actions", len(checkpoint_rows)),
            ("Workflow Playbooks", len(playbook_rows)),
            ("Workflow Corridors", workflow_summary.get("corridor_count", 0)),
        ]
    )

    tabs = st.tabs(["Workflow Board", "Playbooks", "Assignments and Approvals", "Closure Timeline"])
    with tabs[0]:
        render_table(
            "Workflow Intelligence",
            [workflow_summary] if workflow_summary else [],
            caption="Operational workflow health across tasks, checkpoints, playbooks, and corridor coupling.",
            limit=1,
        )
        board_left, board_right = st.columns([1.0, 1.0])
        with board_left:
            render_table("Queued Tasks", queued_tasks, caption="Tasks awaiting assignment, approval, or dispatch action.", limit=16)
            render_table("Active Tasks", active_tasks, caption="Tasks currently executing or deployed.", limit=16)
        with board_right:
            render_table("Approved Tasks", approved_tasks, caption="Tasks cleared for field execution.", limit=16)
            render_table("Checkpoint Workflow", checkpoint_rows, caption="Checkpoint actions participating in the current workflow lens.", limit=16)
            render_table("District Breakdown", workflow_breakdown, caption="District-level distribution of task, checkpoint, playbook, and corridor pressure.", limit=12)

        route_option_map = {f"{row.get('subject_label')} | {row.get('route_type')}": row for row in route_rows}
        with st.expander("Create workflow task", expanded=False):
            with st.form("dispatch_create_task_form"):
                task_type = st.text_input("Task type", value="checkpoint_deployment")
                priority = st.selectbox("Priority", ["low", "medium", "high", "critical"], index=2)
                assigned_unit = st.text_input("Assigned unit", value=str(me_payload.get("district") or "State Command Cell"))
                route_label = st.selectbox("Route context", ["None"] + list(route_option_map.keys()), index=0)
                details = st.text_area("Task details", height=110)
                if st.form_submit_button("Create workflow task", use_container_width=True):
                    route_context = None if route_label == "None" else route_option_map[route_label]
                    full_details = details
                    if route_context:
                        full_details = (full_details + "\n" if full_details else "") + f"Route context: {route_context.get('route_id')} | {route_context.get('subject_label')}"
                    payload = {
                        "district": district_scope if district_scope != DEFAULT_DISTRICT_SCOPE else (route_context.get("districts", ["Statewide"])[0] if route_context else "Statewide"),
                        "task_type": task_type,
                        "priority": priority,
                        "assigned_unit": assigned_unit or None,
                        "status": "queued",
                        "details": full_details or None,
                        "case_id": selected_case_id,
                    }
                    run_action_and_refresh("/tasks", payload=payload, success_message="Workflow task created.")

    with tabs[1]:
        playbook_left, playbook_right = st.columns([1.04, 0.96])
        with playbook_left:
            render_table(
                "Workflow Playbooks",
                playbook_rows,
                caption="District-aligned operational playbooks with trigger type, priority, and action templates.",
                limit=16,
            )
        with playbook_right:
            playbook_option_map = {
                f"{row.get('playbook_name')} | {row.get('district')} | {row.get('trigger_type')}": to_int(row.get("id"))
                for row in playbook_rows
                if row.get("id") not in (None, "N/A")
            }
            if playbook_option_map:
                with st.form("workflow_playbook_launch_form"):
                    selected_playbook_label = st.selectbox("Playbook", list(playbook_option_map.keys()))
                    launch_district = st.text_input("Launch district", value="" if district_scope == DEFAULT_DISTRICT_SCOPE else district_scope)
                    launch_unit = st.text_input("Assigned unit", value=str(me_payload.get("district") or "State Command Cell"))
                    launch_notes = st.text_area("Launch notes", height=110)
                    if st.form_submit_button("Launch workflow playbook", use_container_width=True):
                        run_action_and_refresh(
                            f"/workflow/playbooks/{playbook_option_map[selected_playbook_label]}/launch",
                            payload={
                                "district": launch_district,
                                "assigned_unit": launch_unit or None,
                                "case_id": selected_case_id,
                                "notes": launch_notes or None,
                            },
                            success_message="Workflow playbook launched.",
                        )
            else:
                render_inline_note("No playbooks are visible for the current district scope.")

    with tabs[2]:
        task_option_map = {
            f"Task {row.get('id')} | {row.get('task_type')} | {row.get('status')}": to_int(row.get("id"))
            for row in task_rows
            if row.get("id") not in (None, "N/A")
        }
        selected_task_id = None
        if task_option_map:
            selected_task_label = st.selectbox("Task action lens", list(task_option_map.keys()), key="dispatch_task_lens")
            selected_task_id = task_option_map[selected_task_label]
        task_execution_rows = rows_from_result(api_get(f"/tasks/{selected_task_id}/executions")) if selected_task_id else []

        assignment_left, assignment_right = st.columns([1.0, 1.0])
        with assignment_left:
            render_table("Task Executions", task_execution_rows, caption="Execution trail for the selected workflow task.", limit=20)
        with assignment_right:
            with st.form("dispatch_task_action_form"):
                action = st.selectbox("Action", ["assigned", "approved", "deployed", "rerouted", "closed"], index=0)
                new_status = st.selectbox("Resulting status", ["assigned", "approved", "in_progress", "deployed", "completed", "closed"], index=0)
                assigned_unit = st.text_input("Assigned unit")
                notes = st.text_area("Action notes", height=120)
                if st.form_submit_button("Record task action", use_container_width=True, disabled=selected_task_id is None):
                    payload = {
                        "action": action,
                        "status": new_status,
                        "assigned_unit": assigned_unit or None,
                        "notes": notes or None,
                    }
                    run_action_and_refresh(f"/tasks/{selected_task_id}/actions", payload=payload, success_message="Task action recorded.")

    with tabs[3]:
        closure_left, closure_right = st.columns([1.0, 1.0])
        with closure_left:
            render_table("Completed Tasks", completed_tasks, caption="Workflow tasks that reached closure or completion.", limit=18)
        with closure_right:
            if selected_case_id is not None:
                timeline_rows = rows_from_result(api_get(f"/cases/{selected_case_id}/timeline"))
                render_table(
                    "Case Timeline Alignment",
                    timeline_rows,
                    caption="Case timeline entries aligned to the current case focus for closure review.",
                    limit=18,
                )
            else:
                render_inline_note("Select a case focus from the sidebar to align dispatch closure with a case timeline.")


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

    tabs = st.tabs(["Create Case", "Complaint Intake", "Link Records", "Registry Search", "Unified Search and Fusion"])
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

    with tabs[4]:
        unified_query = st.text_input("Unified search query", key="unified_search_query")
        if st.button("Run unified search fabric", key="unified_search_submit", use_container_width=True):
            params = compact_params(
                {
                    "q": unified_query.strip(),
                    "district": None if district_scope == DEFAULT_DISTRICT_SCOPE else district_scope,
                    "case_id": selected_case_id,
                }
            )
            search_result = api_get("/search/unified", params=params or None)
            if search_result.get("ok") and isinstance(search_result.get("data"), dict):
                payload = search_result["data"]
                count_payload = payload.get("counts") or {}
                render_metric_grid(
                    [
                        ("Complaints", count_payload.get("complaints", 0)),
                        ("Cases", count_payload.get("cases", 0)),
                        ("Entities", count_payload.get("entities", 0)),
                        ("Watchlists", count_payload.get("watchlists", 0)),
                        ("Tasks", count_payload.get("tasks", 0)),
                        ("Messages", count_payload.get("messages", 0)),
                        ("Checkpoints", count_payload.get("checkpoints", 0)),
                        ("Geofences", count_payload.get("geofences", 0)),
                        ("Cameras", count_payload.get("cameras", 0)),
                        ("Attribute Facts", count_payload.get("attribute_facts", 0)),
                        ("Resolution Candidates", count_payload.get("resolution_candidates", 0)),
                        ("Connector Artifacts", count_payload.get("connector_artifacts", 0)),
                        ("Provenance", count_payload.get("provenance_records", 0)),
                        ("Corridors", count_payload.get("corridors", 0)),
                        ("Playbooks", count_payload.get("playbooks", 0)),
                        ("Video Sessions", count_payload.get("video_sessions", 0)),
                    ]
                )
                render_table(
                    "Top Fusion-Scored Hits",
                    payload_to_rows(payload.get("top_hits")),
                    caption="Unified search results scored by fusion weight, operational relevance, and local context.",
                    limit=25,
                )
            else:
                render_result_error(search_result, "Unified Search")

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
            "Graph Fabric",
            "Connector Ops",
            "Camera Command",
            "Fusion Center",
            "Case Dossier",
            "District Command",
            "War Room",
            "Dispatch Engine",
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
elif workspace == "Graph Fabric":
    render_graph_fabric(district_scope, selected_case_id)
elif workspace == "Connector Ops":
    render_connector_ops(district_scope, selected_case_id)
elif workspace == "Camera Command":
    render_camera_command(district_scope, selected_case_id)
elif workspace == "Fusion Center":
    render_fusion_center(district_scope, selected_case_id)
elif workspace == "Case Dossier":
    render_case_dossier(selected_case_id)
elif workspace == "District Command":
    render_district_command(district_scope, me_payload, case_rows)
elif workspace == "War Room":
    render_war_room(district_scope, selected_case_id, me_payload)
elif workspace == "Dispatch Engine":
    render_dispatch_engine(district_scope, selected_case_id, me_payload)
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
