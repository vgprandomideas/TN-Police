
from collections import defaultdict, deque
from datetime import datetime, timedelta
import json
import math
import re
from pathlib import Path
from urllib.parse import quote
from fastapi import FastAPI, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import or_
from sqlalchemy.orm import Session
from jose import jwt, JWTError

from app.config import JWT_SECRET, JWT_ALGORITHM
from app.schemas import (
    LoginRequest, ComplaintCreate, CaseCreate, CaseCommentCreate,
    CaseAssignCreate, ComplaintCaseLinkCreate, WatchlistCreate, EvidenceCreate,
    DepartmentMessageCreate, DepartmentMessageReadCreate, PresenceHeartbeatCreate, CheckpointPlanCreate,
    TypingHeartbeatCreate, GraphSavedViewCreate, GeofenceZoneCreate, CameraIncidentAssignmentCreate,
    TaskCreate, TaskActionCreate, EntityResolutionActionCreate, ConnectorRunCreate,
    VideoSessionCreate, VideoParticipantStateCreate, WorkflowPlaybookLaunchCreate
)
from db.database import get_db, SessionLocal
from db.models import (
    User, Role, PublicMetric, Complaint, Alert, Entity, EntityLink, Station, AuditLog, Case,
    CaseComment, CaseAssignment, Incident, IngestQueue, ComplaintCaseLink, ConnectorRegistry,
    Watchlist, WatchlistHit, EvidenceAttachment, CaseTimelineEvent, StationRoutingRule,
    ProsecutionPacket, CustodyLog, MedicalCheckLog, EventCommandBoard,
    DocumentIntake, ExtractedEntity, CourtHearing, PrisonMovement, NotificationEvent,
    DepartmentMessage, DepartmentMessageRead, MessageAttachment, RoomTypingSignal,
    PersonnelPresence, CheckpointPlan, GraphSavedView, GeoBoundary, GeofenceZone, CameraAsset,
    CameraIncidentAssignment, GraphSnapshot, GeoFenceAlert, AdapterStub, TaskQueue,
    TaskExecution, SuspectDossier, GraphInsight, CourtPacketExport, EvidenceIntegrityLog,
    NarrativeBrief, HotspotForecast, PatrolCoverageMetric, SimilarityHit, TimelineDigest,
    ExportJob, WarRoomSnapshot, ExplorationBookmark, OntologyClass, OntologyRelationType,
    EntityAttributeFact, EntityResolutionCandidate, EntityResolutionDecision, ProvenanceRecord,
    ConnectorRun, ConnectorArtifact, VideoSession, VideoParticipant, OperationalCorridor,
    WorkflowPlaybook
)
from services.auth import verify_password, create_access_token
from services.permissions import (
    can_write_case, can_assign_case, can_comment_case, can_manage_watchlist, can_add_evidence
)
from services.anomaly import score_incident_anomalies
from services.alerts import rebuild_alerts
from services.sla import apply_case_sla, update_sla_status
from services.routing import pick_station_for_case

app = FastAPI(title="TN Police Intelligence Platform Final")
security = HTTPBearer()
MENTION_PATTERN = re.compile(r"@([A-Za-z0-9_]+)")


class RealtimeConnectionManager:
    def __init__(self):
        self.connections: dict[str, list[WebSocket]] = defaultdict(list)

    async def connect(self, room_name: str, websocket: WebSocket):
        await websocket.accept()
        self.connections[room_name].append(websocket)

    def disconnect(self, room_name: str, websocket: WebSocket):
        room_connections = self.connections.get(room_name, [])
        if websocket in room_connections:
            room_connections.remove(websocket)
        if not room_connections:
            self.connections.pop(room_name, None)

    async def broadcast(self, room_name: str, payload: dict):
        for websocket in list(self.connections.get(room_name, [])):
            try:
                await websocket.send_json(payload)
            except Exception:
                self.disconnect(room_name, websocket)


realtime_manager = RealtimeConnectionManager()


def dispatch_realtime_payload(room_name: str, payload: dict):
    import asyncio
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(realtime_manager.broadcast(room_name, payload))
    except RuntimeError:
        asyncio.run(realtime_manager.broadcast(room_name, payload))

def current_user(credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    token = credentials.credentials
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        username = payload.get("sub")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = db.query(User).filter(User.username == username, User.is_active == True).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def current_user_from_token(token: str, db: Session) -> User:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        username = payload.get("sub")
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc
    user = db.query(User).filter(User.username == username, User.is_active == True).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user

def role_name(db: Session, user: User) -> str:
    role = db.query(Role).filter(Role.id == user.role_id).first()
    return role.name if role else "viewer"

def log_action(db: Session, username: str, action: str, object_type: str, object_id: str):
    db.add(AuditLog(username=username, action=action, object_type=object_type, object_id=object_id))

def add_timeline(db: Session, case_id: int, event_type: str, actor: str, details: str):
    db.add(CaseTimelineEvent(case_id=case_id, event_type=event_type, actor=actor, details=details))


def build_geo_polygon(center_latitude: float, center_longitude: float, radius_km: float, sides: int = 6, rotation_deg: float = -30.0) -> str:
    radius_lat = radius_km / 111.0
    radius_lon = radius_km / max(111.0 * max(math.cos(math.radians(center_latitude)), 0.2), 0.2)
    points = []
    for index in range(sides):
        angle = math.radians(rotation_deg + ((360 / sides) * index))
        points.append(
            {
                "latitude": round(center_latitude + (math.sin(angle) * radius_lat), 6),
                "longitude": round(center_longitude + (math.cos(angle) * radius_lon), 6),
            }
        )
    return json.dumps(points)


def parse_message_mentions(db: Session, message_text: str) -> list[str]:
    active_usernames = {
        row.username
        for row in db.query(User.username).filter(User.is_active == True).all()
    }
    return sorted(
        {
            match.group(1)
            for match in MENTION_PATTERN.finditer(message_text or "")
            if match.group(1) in active_usernames
        }
    )


def parse_message_mentions_text(message_text: str) -> list[str]:
    return sorted({match.group(1) for match in MENTION_PATTERN.finditer(message_text or "")})


def department_attachment_lookup(db: Session, message_ids: list[int]) -> dict[int, list[dict]]:
    if not message_ids:
        return {}
    rows = db.query(MessageAttachment).filter(MessageAttachment.message_id.in_(message_ids)).order_by(MessageAttachment.id.asc()).all()
    grouped: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row.message_id].append(
            {
                "id": row.id,
                "attachment_name": row.attachment_name,
                "attachment_type": row.attachment_type,
                "storage_ref": row.storage_ref,
                "uploaded_by": row.uploaded_by,
                "created_at": row.created_at.isoformat(),
            }
        )
    return grouped


def safe_json_list(payload: str | None) -> list:
    if not payload:
        return []
    try:
        value = json.loads(payload)
    except json.JSONDecodeError:
        return []
    return value if isinstance(value, list) else []


def simple_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", str(value or "").strip().lower())
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug or "ops"


def serialize_entity(entity: Entity) -> dict:
    return {
        "id": entity.id,
        "name": entity.display_name,
        "type": entity.entity_type,
        "district": entity.district,
        "risk_score": entity.risk_score,
    }


def entity_lookup_map(db: Session) -> dict[int, Entity]:
    return {row.id: row for row in db.query(Entity).all()}


def entity_resolution_candidate_payload(
    row: EntityResolutionCandidate,
    entity_lookup: dict[int, Entity],
) -> dict:
    left_entity = entity_lookup.get(row.left_entity_id)
    right_entity = entity_lookup.get(row.right_entity_id)
    return {
        "id": row.id,
        "left_entity_id": row.left_entity_id,
        "left_entity_name": None if left_entity is None else left_entity.display_name,
        "left_entity_type": None if left_entity is None else left_entity.entity_type,
        "left_district": None if left_entity is None else left_entity.district,
        "right_entity_id": row.right_entity_id,
        "right_entity_name": None if right_entity is None else right_entity.display_name,
        "right_entity_type": None if right_entity is None else right_entity.entity_type,
        "right_district": None if right_entity is None else right_entity.district,
        "match_score": row.match_score,
        "rationale": row.rationale,
        "status": row.status,
        "cluster_ref": row.cluster_ref,
        "created_at": row.created_at.isoformat(),
    }


def serialize_connector_run(row: ConnectorRun) -> dict:
    duration_ms = None
    if row.started_at and row.finished_at:
        duration_ms = int((row.finished_at - row.started_at).total_seconds() * 1000)
    return {
        "id": row.id,
        "connector_name": row.connector_name,
        "run_mode": row.run_mode,
        "status": row.status,
        "records_seen": row.records_seen,
        "records_emitted": row.records_emitted,
        "latency_ms": row.latency_ms,
        "notes": row.notes,
        "started_at": None if row.started_at is None else row.started_at.isoformat(),
        "finished_at": None if row.finished_at is None else row.finished_at.isoformat(),
        "duration_ms": duration_ms,
    }


def serialize_connector_artifact(row: ConnectorArtifact, entity_lookup: dict[int, Entity] | None = None) -> dict:
    entity_name = None
    if entity_lookup and row.entity_id:
        entity_name = getattr(entity_lookup.get(row.entity_id), "display_name", None)
    return {
        "id": row.id,
        "connector_run_id": row.connector_run_id,
        "connector_name": row.connector_name,
        "record_type": row.record_type,
        "external_ref": row.external_ref,
        "district": row.district,
        "case_id": row.case_id,
        "entity_id": row.entity_id,
        "entity_name": entity_name,
        "ingest_summary": row.ingest_summary,
        "status": row.status,
        "created_at": row.created_at.isoformat(),
    }


def video_room_name(session_code: str) -> str:
    return f"video::{session_code}"


def build_video_join_url(session_code: str, username: str) -> str:
    safe_code = simple_slug(session_code)
    safe_username = quote(username or "Analyst")
    return (
        f"https://meet.jit.si/{safe_code}"
        f"#userInfo.displayName=\"{safe_username}\""
        "&config.prejoinPageEnabled=false"
    )


def serialize_video_session(row: VideoSession, current_username: str | None = None) -> dict:
    return {
        "id": row.id,
        "room_name": row.room_name,
        "district": row.district,
        "case_id": row.case_id,
        "session_code": row.session_code,
        "session_mode": row.session_mode,
        "status": row.status,
        "notes": row.notes,
        "started_by": row.started_by,
        "started_at": None if row.started_at is None else row.started_at.isoformat(),
        "ended_at": None if row.ended_at is None else row.ended_at.isoformat(),
        "join_url": build_video_join_url(row.session_code, current_username or row.started_by),
        "signal_room": video_room_name(row.session_code),
    }


def serialize_video_participant(row: VideoParticipant) -> dict:
    return {
        "id": row.id,
        "session_id": row.session_id,
        "username": row.username,
        "role_label": row.role_label,
        "device_label": row.device_label,
        "join_state": row.join_state,
        "hand_raised": row.hand_raised,
        "muted": row.muted,
        "camera_enabled": row.camera_enabled,
        "screen_sharing": row.screen_sharing,
        "joined_at": None if row.joined_at is None else row.joined_at.isoformat(),
        "last_seen_at": None if row.last_seen_at is None else row.last_seen_at.isoformat(),
    }


def serialize_playbook(row: WorkflowPlaybook) -> dict:
    return {
        "id": row.id,
        "district": row.district,
        "playbook_name": row.playbook_name,
        "trigger_type": row.trigger_type,
        "default_priority": row.default_priority,
        "assigned_unit_hint": row.assigned_unit_hint,
        "action_template": safe_json_list(row.action_template_json),
        "status": row.status,
        "created_at": row.created_at.isoformat(),
    }


def create_playbook_task(
    db: Session,
    *,
    task_type: str,
    district: str,
    priority: str,
    assigned_unit: str | None,
    details: str,
    created_by: str,
    case_id: int | None = None,
) -> TaskQueue:
    row = TaskQueue(
        case_id=case_id,
        district=district,
        task_type=task_type,
        priority=priority,
        assigned_unit=assigned_unit,
        status="queued",
        details=details,
        created_by=created_by,
    )
    db.add(row)
    db.flush()
    db.add(
        TaskExecution(
            task_id=row.id,
            actor=created_by,
            action="playbook_launch",
            notes=f"Created from workflow playbook. Assigned unit: {assigned_unit or 'unassigned'}.",
        )
    )
    return row


def typing_signal_rows(db: Session, room_name: str | None = None, district: str | None = None) -> list[RoomTypingSignal]:
    q = db.query(RoomTypingSignal).filter(RoomTypingSignal.typing_until >= datetime.utcnow())
    if room_name:
        q = q.filter(RoomTypingSignal.room_name == room_name)
    if district:
        q = q.filter(or_(RoomTypingSignal.district == district, RoomTypingSignal.district == None))
    return q.order_by(RoomTypingSignal.typing_until.desc()).all()


def build_graph_scope(db: Session, district: str | None = None, case_id: int | None = None) -> tuple[dict[str, dict], list[dict]]:
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    entity_query = db.query(Entity)
    if district:
        entity_query = entity_query.filter(or_(Entity.district == district, Entity.district == None))
    entity_rows = entity_query.all()
    entity_ids = {row.id for row in entity_rows}
    for row in entity_rows:
        node_id = f"entity-{row.id}"
        nodes[node_id] = {
            "id": node_id,
            "label": row.display_name,
            "type": row.entity_type,
            "district": row.district,
            "risk_score": row.risk_score,
        }

    link_query = db.query(EntityLink)
    if entity_ids:
        link_query = link_query.filter(
            EntityLink.source_entity_id.in_(entity_ids),
            EntityLink.target_entity_id.in_(entity_ids),
        )
    for row in link_query.all():
        source_id = f"entity-{row.source_entity_id}"
        target_id = f"entity-{row.target_entity_id}"
        if source_id in nodes and target_id in nodes:
            edges.append(
                {
                    "source": source_id,
                    "target": target_id,
                    "label": row.relationship_type,
                    "weight": row.weight,
                }
            )

    if case_id:
        case = db.query(Case).filter(Case.id == case_id).first()
        if case:
            case_node_id = f"case-{case.id}"
            nodes[case_node_id] = {
                "id": case_node_id,
                "label": case.title,
                "type": "case",
                "district": case.district,
                "risk_score": 0.95 if case.priority in {"high", "critical"} else 0.55,
            }
            for row in db.query(EvidenceAttachment).filter(EvidenceAttachment.case_id == case_id).all():
                evidence_id = f"evidence-{row.id}"
                nodes[evidence_id] = {
                    "id": evidence_id,
                    "label": row.file_name,
                    "type": "evidence",
                    "district": case.district,
                    "risk_score": 0.42,
                }
                edges.append(
                    {
                        "source": case_node_id,
                        "target": evidence_id,
                        "label": row.attachment_type,
                        "weight": 1.0,
                    }
                )
            for row in db.query(WatchlistHit).filter(WatchlistHit.case_id == case_id).all():
                entity_node_id = f"entity-{row.entity_id}" if row.entity_id else None
                if entity_node_id and entity_node_id in nodes:
                    edges.append(
                        {
                            "source": case_node_id,
                            "target": entity_node_id,
                            "label": "watchlist_hit",
                            "weight": max(row.confidence, 0.55),
                        }
                    )
    return nodes, edges


def graph_adjacency(edges: list[dict]) -> dict[str, list[tuple[str, dict]]]:
    adjacency: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for row in edges:
        source = str(row.get("source"))
        target = str(row.get("target"))
        adjacency[source].append((target, row))
        adjacency[target].append((source, row))
    return adjacency


def shortest_graph_path(nodes: dict[str, dict], edges: list[dict], source_node_id: str, target_node_id: str) -> dict:
    adjacency = graph_adjacency(edges)
    queue = deque([(source_node_id, [source_node_id], [])])
    visited = {source_node_id}
    while queue:
        node_id, path_nodes, path_edges = queue.popleft()
        if node_id == target_node_id:
            return {
                "path_found": True,
                "path_node_ids": path_nodes,
                "path_nodes": [nodes[row_id] for row_id in path_nodes if row_id in nodes],
                "path_edges": path_edges,
                "hop_count": max(len(path_nodes) - 1, 0),
            }
        for peer_id, edge in adjacency.get(node_id, []):
            if peer_id in visited:
                continue
            visited.add(peer_id)
            queue.append((peer_id, path_nodes + [peer_id], path_edges + [edge]))
    return {
        "path_found": False,
        "path_node_ids": [],
        "path_nodes": [],
        "path_edges": [],
        "hop_count": 0,
    }

@app.get('/')
@app.get('/health')
def health():
    return {"status": "ok", "version": "final"}

@app.post('/auth/login')
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail='Bad credentials')
    role = role_name(db, user)
    token = create_access_token({"sub": user.username, "role": role, "district": user.district})
    log_action(db, user.username, 'login', 'auth', user.username)
    db.commit()
    return {"access_token": token, "token_type": "bearer", "role": role, "district": user.district}

@app.get('/me')
@app.get('/auth/me')
def me(user=Depends(current_user), db: Session = Depends(get_db)):
    return {
        "username": user.username,
        "role": role_name(db, user),
        "district": user.district,
        "is_active": user.is_active,
    }

@app.get('/dashboard/summary')
def dashboard_summary(user=Depends(current_user), db: Session = Depends(get_db)):
    cases = db.query(Case).all()
    for c in cases:
        update_sla_status(c)
    db.commit()
    return {
        "metrics_count": db.query(PublicMetric).count(),
        "alerts_open": db.query(Alert).filter(Alert.status == 'open').count(),
        "active_alerts": db.query(Alert).filter(Alert.status == 'open').count(),
        "complaints_count": db.query(Complaint).count(),
        "complaints": db.query(Complaint).count(),
        "entities": db.query(Entity).count(),
        "stations": db.query(Station).count(),
        "open_cases": db.query(Case).filter(Case.status != 'closed').count(),
        "watchlists_active": db.query(Watchlist).filter(Watchlist.status == 'active').count(),
        "watchlist_hits": db.query(WatchlistHit).count(),
        "evidence_attachments": db.query(EvidenceAttachment).count(),
        "sla_breached_cases": db.query(Case).filter(Case.sla_status == 'breached').count(),
        "user": user.username,
        "role": role_name(db, user),
        "district_scope": user.district or 'statewide',
    }

@app.get('/metrics')
def list_metrics(user=Depends(current_user), db: Session = Depends(get_db)):
    q = db.query(PublicMetric)
    return [{"year": m.year, "district": m.district, "metric_name": m.metric_name, "metric_value": m.metric_value,
             "unit": m.unit, "provenance": m.provenance, "notes": m.notes}
            for m in q.order_by(PublicMetric.year, PublicMetric.metric_name).all()]

@app.get('/alerts')
def list_alerts(user=Depends(current_user), db: Session = Depends(get_db)):
    return [{"id": a.id, "district": a.district, "type": a.alert_type, "message": a.message, "severity": a.severity, "status": a.status}
            for a in db.query(Alert).order_by(Alert.created_at.desc()).all()]

@app.get('/graph/entities')
def graph_entities(user=Depends(current_user), db: Session = Depends(get_db)):
    return [{"id": e.id, "name": e.display_name, "type": e.entity_type, "district": e.district, "risk_score": e.risk_score}
            for e in db.query(Entity).all()]

@app.get('/graph/links')
def graph_links(user=Depends(current_user), db: Session = Depends(get_db)):
    return [{"source": l.source_entity_id, "target": l.target_entity_id, "relationship_type": l.relationship_type, "weight": l.weight}
            for l in db.query(EntityLink).all()]

@app.get('/graph/complaint-case-search')
def complaint_case_search(
    q: str = Query(..., min_length=1),
    district: str | None = None,
    user=Depends(current_user),
    db: Session = Depends(get_db)
):
    q_like = f"%{q}%"
    complaints_q = db.query(Complaint).filter(or_(Complaint.description.ilike(q_like), Complaint.complaint_type.ilike(q_like), Complaint.complainant_ref.ilike(q_like)))
    cases_q = db.query(Case).filter(or_(Case.title.ilike(q_like), Case.summary.ilike(q_like), Case.created_by.ilike(q_like)))
    entities_q = db.query(Entity).filter(or_(Entity.display_name.ilike(q_like), Entity.entity_type.ilike(q_like)))
    watchlists_q = db.query(Watchlist).filter(or_(Watchlist.name.ilike(q_like), Watchlist.rationale.ilike(q_like)))
    if district:
        complaints_q = complaints_q.filter(Complaint.district == district)
        cases_q = cases_q.filter(Case.district == district)
        entities_q = entities_q.filter(Entity.district == district)
        watchlists_q = watchlists_q.filter(Watchlist.district == district)
    complaint_rows = complaints_q.limit(25).all()
    case_rows = cases_q.limit(25).all()
    entity_rows = entities_q.limit(25).all()
    watch_rows = watchlists_q.limit(25).all()
    links = db.query(ComplaintCaseLink).all()
    hits = db.query(WatchlistHit).all()
    return {
        "query": q,
        "complaints": [{"id": c.id, "district": c.district, "type": c.complaint_type, "status": c.status, "description": c.description} for c in complaint_rows],
        "cases": [{"id": c.id, "district": c.district, "title": c.title, "priority": c.priority, "sla_status": c.sla_status, "summary": c.summary} for c in case_rows],
        "entities": [{"id": e.id, "district": e.district, "name": e.display_name, "type": e.entity_type, "risk_score": e.risk_score} for e in entity_rows],
        "watchlists": [{"id": w.id, "name": w.name, "district": w.district, "watch_type": w.watch_type, "status": w.status, "rationale": w.rationale} for w in watch_rows],
        "complaint_case_links": [{"complaint_id": l.complaint_id, "case_id": l.case_id, "linked_by": l.linked_by, "rationale": l.rationale} for l in links if l.complaint_id in {c.id for c in complaint_rows} or l.case_id in {c.id for c in case_rows}],
        "watchlist_hits": [{"watchlist_id": h.watchlist_id, "entity_id": h.entity_id, "case_id": h.case_id, "incident_id": h.incident_id, "hit_reason": h.hit_reason, "confidence": h.confidence} for h in hits if h.case_id in {c.id for c in case_rows} or h.entity_id in {e.id for e in entity_rows} or h.watchlist_id in {w.id for w in watch_rows}]
    }

@app.get('/stations')
def stations(user=Depends(current_user), db: Session = Depends(get_db)):
    return [{"id": s.id, "district": s.district, "station_name": s.station_name, "station_type": s.station_type, "latitude": s.latitude, "longitude": s.longitude}
            for s in db.query(Station).all()]

@app.get('/routing-rules')
def routing_rules(user=Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(StationRoutingRule).order_by(StationRoutingRule.district, StationRoutingRule.complaint_type).all()
    return [{
        "id": r.id, "district": r.district, "complaint_type": r.complaint_type, "incident_category": r.incident_category,
        "min_severity": r.min_severity, "station_id": r.station_id, "priority_override": r.priority_override,
        "enabled": r.enabled, "notes": r.notes
    } for r in rows]

@app.get('/connectors')
def list_connectors(user=Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(ConnectorRegistry).order_by(ConnectorRegistry.connector_name).all()
    return [{"connector_name": r.connector_name, "source_type": r.source_type, "base_url": r.base_url, "sanctioned": r.sanctioned, "access_mode": r.access_mode, "notes": r.notes} for r in rows]

def _filtered_incidents(db: Session, district=None, category=None, min_anomaly=0.0, source_type=None):
    q = db.query(Incident)
    if district:
        q = q.filter(Incident.district == district)
    if category:
        q = q.filter(Incident.category == category)
    if min_anomaly:
        q = q.filter(Incident.anomaly_score >= float(min_anomaly))
    if source_type:
        q = q.filter(Incident.source_type == source_type)
    return q.all()

@app.get('/geo/district-heatmap')
def district_heatmap(
    district: str | None = None,
    category: str | None = None,
    min_anomaly: float = 0.0,
    source_type: str | None = None,
    user=Depends(current_user),
    db: Session = Depends(get_db)
):
    stations = db.query(Station).all()
    incidents = _filtered_incidents(db, district=district, category=category, min_anomaly=min_anomaly, source_type=source_type)
    stat = defaultdict(lambda: {"incident_count": 0, "avg_anomaly": 0.0, "severity_sum": 0.0, "latitude": None, "longitude": None})
    for s in stations:
        if district and s.district != district:
            continue
        if stat[s.district]["latitude"] is None:
            stat[s.district]["latitude"] = s.latitude
            stat[s.district]["longitude"] = s.longitude
    for i in incidents:
        stat[i.district]["incident_count"] += 1
        stat[i.district]["avg_anomaly"] += i.anomaly_score
        stat[i.district]["severity_sum"] += i.severity
    rows = []
    for district_name, vals in stat.items():
        count = vals["incident_count"]
        avg_anomaly = round(vals["avg_anomaly"] / count, 3) if count else 0
        rows.append({
            "district": district_name,
            "latitude": vals["latitude"],
            "longitude": vals["longitude"],
            "incident_count": count,
            "avg_anomaly": avg_anomaly,
            "intensity": round((count * 0.5) + (avg_anomaly * 5) + (vals["severity_sum"] * 0.15), 2),
        })
    return rows

@app.get('/geo/station-heatmap')
def station_heatmap(
    district: str | None = None,
    category: str | None = None,
    min_anomaly: float = 0.0,
    source_type: str | None = None,
    user=Depends(current_user),
    db: Session = Depends(get_db)
):
    stations = {s.id: s for s in db.query(Station).all() if not district or s.district == district}
    grouped = defaultdict(lambda: {"incident_count": 0, "avg_anomaly": 0.0, "severity_sum": 0.0})
    for i in _filtered_incidents(db, district=district, category=category, min_anomaly=min_anomaly, source_type=source_type):
        if i.station_id in stations:
            grouped[i.station_id]["incident_count"] += 1
            grouped[i.station_id]["avg_anomaly"] += i.anomaly_score
            grouped[i.station_id]["severity_sum"] += i.severity
    rows = []
    for station_id, g in grouped.items():
        s = stations[station_id]
        count = g["incident_count"]
        avg_anomaly = round(g["avg_anomaly"] / count, 3) if count else 0
        rows.append({
            "station_id": station_id,
            "station_name": s.station_name,
            "district": s.district,
            "latitude": s.latitude,
            "longitude": s.longitude,
            "incident_count": count,
            "avg_anomaly": avg_anomaly,
            "intensity": round((count * 0.6) + (avg_anomaly * 5) + (g["severity_sum"] * 0.2), 2),
        })
    return rows

@app.get('/incidents')
def list_incidents(
    district: str | None = None,
    category: str | None = None,
    min_anomaly: float = 0.0,
    source_type: str | None = None,
    user=Depends(current_user),
    db: Session = Depends(get_db)
):
    rows = _filtered_incidents(db, district=district, category=category, min_anomaly=min_anomaly, source_type=source_type)
    return [{
        "id": i.id, "district": i.district, "station_id": i.station_id, "category": i.category, "severity": i.severity,
        "status": i.status, "anomaly_score": i.anomaly_score, "description": i.description, "source_type": i.source_type,
        "created_at": i.created_at.isoformat(),
    } for i in sorted(rows, key=lambda x: x.created_at, reverse=True)]

@app.post('/complaints')
def create_complaint(body: ComplaintCreate, user=Depends(current_user), db: Session = Depends(get_db)):
    row = Complaint(**body.model_dump())
    db.add(row)
    db.flush()
    log_action(db, user.username, 'create_complaint', 'complaint', str(row.id))
    db.commit()
    return {"status": "created", "complaint_id": row.id}

@app.get('/complaints')
def list_complaints(user=Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(Complaint).order_by(Complaint.created_at.desc()).all()
    return [{"id": c.id, "district": c.district, "channel": c.channel, "complaint_type": c.complaint_type, "complainant_ref": c.complainant_ref, "status": c.status, "description": c.description, "created_at": c.created_at.isoformat()} for c in rows]

@app.get('/cases')
def list_cases(user=Depends(current_user), db: Session = Depends(get_db)):
    q = db.query(Case)
    current_role = role_name(db, user)
    if current_role == 'district_sp' and user.district:
        q = q.filter(Case.district == user.district)
    rows = q.order_by(Case.created_at.desc()).all()
    for c in rows:
        update_sla_status(c)
    db.commit()
    return [{
        "id": c.id, "title": c.title, "district": c.district, "station_id": c.station_id, "priority": c.priority,
        "status": c.status, "summary": c.summary, "created_by": c.created_by, "created_at": c.created_at.isoformat(),
        "response_due_at": c.response_due_at.isoformat() if c.response_due_at else None,
        "resolution_due_at": c.resolution_due_at.isoformat() if c.resolution_due_at else None,
        "sla_status": c.sla_status,
    } for c in rows]

@app.post('/cases')
def create_case(body: CaseCreate, user=Depends(current_user), db: Session = Depends(get_db)):
    current_role = role_name(db, user)
    if not can_write_case(current_role):
        raise HTTPException(status_code=403, detail='Role cannot create cases')
    station_id = body.station_id
    routing_decision = None
    if not station_id:
        routing_decision = pick_station_for_case(db, district=body.district, complaint_type=body.title.lower(), incident_category=body.title.lower(), severity=3 if body.priority == "high" else 1)
        if routing_decision:
            station_id = routing_decision.station_id
    row = Case(title=body.title, district=body.district, station_id=station_id, priority=body.priority, summary=body.summary, created_by=user.username)
    if routing_decision and routing_decision.priority_override:
        row.priority = routing_decision.priority_override
    apply_case_sla(row)
    db.add(row)
    db.flush()
    log_action(db, user.username, 'create_case', 'case', str(row.id))
    add_timeline(db, row.id, "case_created", user.username, f"Case created with priority {row.priority}")
    if routing_decision:
        add_timeline(db, row.id, "routed_to_station", user.username, f"Routing rule matched. Station ID {station_id}. Notes: {routing_decision.notes}")
    db.commit()
    return {"status": "created", "case_id": row.id, "station_id": station_id, "routed": bool(routing_decision)}

@app.get('/cases/{case_id}/comments')
def list_case_comments(case_id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    return [{"id": r.id, "username": r.username, "comment_text": r.comment_text, "created_at": r.created_at.isoformat()} for r in db.query(CaseComment).filter(CaseComment.case_id == case_id).order_by(CaseComment.created_at.desc()).all()]

@app.post('/cases/{case_id}/comments')
def add_case_comment(case_id: int, body: CaseCommentCreate, user=Depends(current_user), db: Session = Depends(get_db)):
    current_role = role_name(db, user)
    if not can_comment_case(current_role):
        raise HTTPException(status_code=403, detail='Role cannot comment')
    exists = db.query(Case).filter(Case.id == case_id).first()
    if not exists:
        raise HTTPException(status_code=404, detail='Case not found')
    row = CaseComment(case_id=case_id, username=user.username, comment_text=body.comment_text)
    db.add(row)
    add_timeline(db, case_id, "comment_added", user.username, body.comment_text[:180])
    log_action(db, user.username, 'comment_case', 'case', str(case_id))
    db.commit()
    return {"status": "comment_added"}

@app.get('/cases/{case_id}/assignments')
def list_case_assignments(case_id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    return [{"id": r.id, "assignee_username": r.assignee_username, "assigned_by": r.assigned_by, "role_label": r.role_label, "created_at": r.created_at.isoformat()} for r in db.query(CaseAssignment).filter(CaseAssignment.case_id == case_id).order_by(CaseAssignment.created_at.desc()).all()]

@app.post('/cases/{case_id}/assign')
def assign_case(case_id: int, body: CaseAssignCreate, user=Depends(current_user), db: Session = Depends(get_db)):
    current_role = role_name(db, user)
    if not can_assign_case(current_role):
        raise HTTPException(status_code=403, detail='Role cannot assign')
    if not db.query(Case).filter(Case.id == case_id).first():
        raise HTTPException(status_code=404, detail='Case not found')
    if not db.query(User).filter(User.username == body.assignee_username).first():
        raise HTTPException(status_code=404, detail='Assignee not found')
    row = CaseAssignment(case_id=case_id, assignee_username=body.assignee_username, assigned_by=user.username, role_label=body.role_label)
    db.add(row)
    add_timeline(db, case_id, "case_assigned", user.username, f"Assigned to {body.assignee_username} ({body.role_label or 'role_unspecified'})")
    log_action(db, user.username, 'assign_case', 'case', str(case_id))
    db.commit()
    return {"status": 'assigned'}

@app.post('/complaint-case-links')
def create_complaint_case_link(body: ComplaintCaseLinkCreate, user=Depends(current_user), db: Session = Depends(get_db)):
    complaint = db.query(Complaint).filter(Complaint.id == body.complaint_id).first()
    case = db.query(Case).filter(Case.id == body.case_id).first()
    if not complaint:
        raise HTTPException(status_code=404, detail='Complaint not found')
    if not case:
        raise HTTPException(status_code=404, detail='Case not found')
    row = ComplaintCaseLink(**body.model_dump(), linked_by=user.username)
    db.add(row)
    add_timeline(db, body.case_id, "complaint_linked", user.username, f"Complaint {body.complaint_id} linked. {body.rationale or ''}".strip())
    # watchlist hit heuristic
    matched_watchlists = db.query(Watchlist).filter(Watchlist.status == "active", Watchlist.district.in_([complaint.district, None])).all()
    for w in matched_watchlists:
        target = f"{complaint.complaint_type} {complaint.description or ''}".lower()
        if w.name.lower() in target:
            db.add(WatchlistHit(watchlist_id=w.id, case_id=body.case_id, hit_reason=f"Complaint text matched watchlist name '{w.name}'", confidence=0.72))
    log_action(db, user.username, 'link_complaint_case', 'case', str(body.case_id))
    db.commit()
    return {"status": 'linked'}

@app.get('/cases/{case_id}/timeline')
def case_timeline(case_id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(CaseTimelineEvent).filter(CaseTimelineEvent.case_id == case_id).order_by(CaseTimelineEvent.created_at.desc()).all()
    return [{"id": r.id, "event_type": r.event_type, "actor": r.actor, "details": r.details, "created_at": r.created_at.isoformat()} for r in rows]

@app.get('/cases/{case_id}/evidence')
def case_evidence(case_id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(EvidenceAttachment).filter(EvidenceAttachment.case_id == case_id).order_by(EvidenceAttachment.created_at.desc()).all()
    return [{"id": r.id, "attachment_type": r.attachment_type, "file_name": r.file_name, "storage_ref": r.storage_ref, "notes": r.notes, "uploaded_by": r.uploaded_by, "created_at": r.created_at.isoformat()} for r in rows]

@app.post('/cases/{case_id}/evidence')
def add_case_evidence(case_id: int, body: EvidenceCreate, user=Depends(current_user), db: Session = Depends(get_db)):
    current_role = role_name(db, user)
    if not can_add_evidence(current_role):
        raise HTTPException(status_code=403, detail='Role cannot add evidence')
    if not db.query(Case).filter(Case.id == case_id).first():
        raise HTTPException(status_code=404, detail='Case not found')
    row = EvidenceAttachment(case_id=case_id, uploaded_by=user.username, **body.model_dump())
    db.add(row)
    add_timeline(db, case_id, "evidence_added", user.username, f"Evidence added: {body.file_name}")
    log_action(db, user.username, 'add_evidence', 'case', str(case_id))
    db.commit()
    return {"status": "evidence_added"}

@app.get('/watchlists')
def list_watchlists(user=Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(Watchlist).order_by(Watchlist.created_at.desc()).all()
    return [{"id": r.id, "name": r.name, "district": r.district, "watch_type": r.watch_type, "rationale": r.rationale, "status": r.status, "created_by": r.created_by, "created_at": r.created_at.isoformat()} for r in rows]

@app.post('/watchlists')
def create_watchlist(body: WatchlistCreate, user=Depends(current_user), db: Session = Depends(get_db)):
    current_role = role_name(db, user)
    if not can_manage_watchlist(current_role):
        raise HTTPException(status_code=403, detail='Role cannot manage watchlists')
    row = Watchlist(**body.model_dump(), created_by=user.username)
    db.add(row)
    db.flush()
    log_action(db, user.username, 'create_watchlist', 'watchlist', str(row.id))
    db.commit()
    return {"status": "created", "watchlist_id": row.id}

@app.get('/watchlist-hits')
def list_watchlist_hits(case_id: int | None = None, watchlist_id: int | None = None, user=Depends(current_user), db: Session = Depends(get_db)):
    q = db.query(WatchlistHit)
    if case_id:
        q = q.filter(WatchlistHit.case_id == case_id)
    if watchlist_id:
        q = q.filter(WatchlistHit.watchlist_id == watchlist_id)
    rows = q.order_by(WatchlistHit.created_at.desc()).all()
    return [{"id": r.id, "watchlist_id": r.watchlist_id, "entity_id": r.entity_id, "case_id": r.case_id, "incident_id": r.incident_id, "hit_reason": r.hit_reason, "confidence": r.confidence, "created_at": r.created_at.isoformat()} for r in rows]

@app.get('/sla/summary')
def sla_summary(user=Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(Case).all()
    for c in rows:
        update_sla_status(c)
    db.commit()
    out = defaultdict(int)
    for c in rows:
        out[c.sla_status] += 1
    return dict(out)

@app.post('/admin/recompute-anomalies')
def admin_recompute_anomalies(user=Depends(current_user), db: Session = Depends(get_db)):
    if role_name(db, user) != 'admin':
        raise HTTPException(status_code=403, detail='Admin only')
    score_incident_anomalies(db)
    rebuild_alerts(db)
    log_action(db, user.username, 'recompute_anomalies', 'incident', 'all')
    db.commit()
    return {"status": 'ok'}

@app.get('/audit')
def list_audit(user=Depends(current_user), db: Session = Depends(get_db)):
    if role_name(db, user) not in {'admin', 'district_sp'}:
        raise HTTPException(status_code=403, detail='Insufficient role')
    rows = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(200).all()
    return [{"username": a.username, "action": a.action, "object_type": a.object_type, "object_id": a.object_id, "created_at": a.created_at.isoformat()} for a in rows]

@app.get('/ingest-queue')
def list_ingest_queue(user=Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(IngestQueue).order_by(IngestQueue.created_at.desc()).all()
    return [{"id": r.id, "source_name": r.source_name, "payload_ref": r.payload_ref, "status": r.status, "created_at": r.created_at.isoformat(), "processed_at": r.processed_at.isoformat() if r.processed_at else None} for r in rows]



@app.get('/prosecution-packets')
def prosecution_packets(user=Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(ProsecutionPacket).order_by(ProsecutionPacket.created_at.desc()).all()
    return [{"id": r.id, "case_id": r.case_id, "packet_status": r.packet_status, "summary_note": r.summary_note, "court_name": r.court_name, "created_by": r.created_by} for r in rows]

@app.get('/custody-logs')
def custody_logs(user=Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(CustodyLog).order_by(CustodyLog.created_at.desc()).all()
    return [{"id": r.id, "case_id": r.case_id, "person_ref": r.person_ref, "action": r.action, "location": r.location, "officer": r.officer, "created_at": r.created_at.isoformat()} for r in rows]

@app.get('/medical-check-logs')
def medical_checks(user=Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(MedicalCheckLog).order_by(MedicalCheckLog.created_at.desc()).all()
    return [{"id": r.id, "case_id": r.case_id, "person_ref": r.person_ref, "facility_name": r.facility_name, "status": r.status, "notes": r.notes} for r in rows]

@app.get('/event-command-board')
def command_board(user=Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(EventCommandBoard).order_by(EventCommandBoard.created_at.desc()).all()
    return [{"id": r.id, "district": r.district, "event_name": r.event_name, "event_type": r.event_type, "risk_level": r.risk_level, "status": r.status, "command_notes": r.command_notes} for r in rows]



@app.get('/documents')
def documents(case_id: int | None = None, district: str | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    q = db.query(DocumentIntake)
    if case_id: q = q.filter(DocumentIntake.case_id == case_id)
    if district: q = q.filter(DocumentIntake.district == district)
    rows = q.order_by(DocumentIntake.id.desc()).all()
    return [{"id": r.id, "case_id": r.case_id, "district": r.district, "source_name": r.source_name, "document_type": r.document_type, "file_name": r.file_name, "intake_status": r.intake_status, "summary": r.summary} for r in rows]

@app.get('/documents/{document_id}/entities')
def document_entities(document_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.query(ExtractedEntity).filter(ExtractedEntity.document_id == document_id).all()
    return [{"id": r.id, "entity_label": r.entity_label, "entity_value": r.entity_value, "confidence": r.confidence, "linked_entity_id": r.linked_entity_id} for r in rows]

@app.get('/court-hearings')
def court_hearings(case_id: int | None = None, district: str | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    q = db.query(CourtHearing).join(Case, CourtHearing.case_id == Case.id)
    if case_id: q = q.filter(CourtHearing.case_id == case_id)
    if district: q = q.filter(Case.district == district)
    rows = q.order_by(CourtHearing.hearing_date.desc()).all()
    return [{"id": r.id, "case_id": r.case_id, "court_name": r.court_name, "hearing_date": r.hearing_date.isoformat(), "hearing_stage": r.hearing_stage, "outcome": r.outcome, "next_action": r.next_action, "prosecutor": r.prosecutor} for r in rows]

@app.get('/prison-movements')
def prison_movements(case_id: int | None = None, district: str | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    q = db.query(PrisonMovement)
    if case_id: q = q.filter(PrisonMovement.case_id == case_id)
    if district: q = q.filter(PrisonMovement.district == district)
    rows = q.order_by(PrisonMovement.movement_time.desc()).all()
    return [{"id": r.id, "case_id": r.case_id, "person_ref": r.person_ref, "district": r.district, "prison_name": r.prison_name, "movement_type": r.movement_type, "movement_time": r.movement_time.isoformat(), "escort_unit": r.escort_unit, "notes": r.notes} for r in rows]

@app.get('/notifications')
def notifications(status: str | None = None, recipient: str | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    q = db.query(NotificationEvent)
    if status: q = q.filter(NotificationEvent.status == status)
    if recipient: q = q.filter(NotificationEvent.recipient == recipient)
    rows = q.order_by(NotificationEvent.id.desc()).all()
    return [{"id": r.id, "notification_type": r.notification_type, "channel": r.channel, "recipient": r.recipient, "subject": r.subject, "message": r.message, "status": r.status, "related_object_type": r.related_object_type, "related_object_id": r.related_object_id} for r in rows]

@app.post('/admin/dispatch-notifications')
def dispatch_notifications(db: Session = Depends(get_db), user: User = Depends(current_user)):
    if role_name(db, user) != 'admin':
        raise HTTPException(status_code=403, detail='Not permitted')
    rows = db.query(NotificationEvent).filter(NotificationEvent.status == 'queued').all()
    count = 0
    for r in rows:
        r.status = 'sent'
        r.sent_at = datetime.utcnow()
        count += 1
    log_action(db, user.username, 'dispatch_notifications', 'notification_events', str(count))
    db.commit()
    return {"sent": count}

@app.get('/personnel/directory')
def personnel_directory(user=Depends(current_user), db: Session = Depends(get_db)):
    role_lookup = {row.id: row.name for row in db.query(Role).all()}
    rows = db.query(User).filter(User.is_active == True).order_by(User.username).all()
    output = []
    for row in rows:
        role = role_lookup.get(row.role_id, "viewer")
        status = "available"
        if role == "admin":
            status = "command"
        elif role == "district_sp":
            status = "district_duty"
        elif role == "cyber_analyst":
            status = "fusion_watch"
        output.append(
            {
                "username": row.username,
                "full_name": row.full_name,
                "role": role,
                "district": row.district,
                "status": status,
                "scope": row.district or "statewide",
            }
        )
    return output

def visible_department_message_rows(db: Session, user: User, district: str | None = None) -> list[DepartmentMessage]:
    current_role = role_name(db, user)
    effective_district = district
    if current_role == "district_sp" and user.district:
        effective_district = user.district

    q = db.query(DepartmentMessage)
    if effective_district:
        q = q.filter(or_(DepartmentMessage.district == effective_district, DepartmentMessage.district == None))
    rows = q.order_by(DepartmentMessage.id.desc()).all()

    visible_rows: list[DepartmentMessage] = []
    for row in rows:
        if row.channel_scope == "direct":
            if user.username not in {row.sender_username, row.recipient_username}:
                continue
        elif row.recipient_username and row.recipient_username != user.username and row.sender_username != user.username:
            continue

        if current_role == "district_sp" and user.district and row.district not in (None, user.district):
            continue

        visible_rows.append(row)

    return visible_rows

def department_room_read_lookup(db: Session, username: str) -> dict[str, int]:
    rows = db.query(DepartmentMessageRead).filter(DepartmentMessageRead.username == username).all()
    return {row.room_name: row.last_read_message_id for row in rows}

def serialize_department_message(
    row: DepartmentMessage,
    current_username: str,
    read_lookup: dict[str, int],
    attachment_lookup: dict[int, list[dict]] | None = None,
) -> dict:
    last_read_id = read_lookup.get(row.room_name, 0)
    is_unread = row.sender_username != current_username and row.id > last_read_id
    mention_usernames = parse_message_mentions_text(row.message_text)
    return {
        "id": row.id,
        "sender_username": row.sender_username,
        "recipient_username": row.recipient_username,
        "district": row.district,
        "room_name": row.room_name,
        "channel_scope": row.channel_scope,
        "priority": row.priority,
        "message_text": row.message_text,
        "ack_required": row.ack_required,
        "case_id": row.case_id,
        "is_unread": is_unread,
        "mentioned_usernames": mention_usernames,
        "mentions_me": current_username in mention_usernames,
        "attachments": [] if attachment_lookup is None else attachment_lookup.get(row.id, []),
        "created_at": row.created_at.isoformat(),
    }

@app.get('/personnel/presence')
def personnel_presence(
    district: str | None = None,
    room_name: str | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    role_lookup = {row.id: row.name for row in db.query(Role).all()}
    presence_lookup = {
        row.username: row
        for row in db.query(PersonnelPresence).order_by(PersonnelPresence.last_seen_at.desc()).all()
    }
    current_time = datetime.utcnow()
    rows = []
    for row in db.query(User).filter(User.is_active == True).order_by(User.username).all():
        role = role_lookup.get(row.role_id, "viewer")
        presence = presence_lookup.get(row.username)
        if district and row.district not in {district, None}:
            continue
        if room_name and presence and presence.room_name not in {room_name, None}:
            continue
        last_seen_at = presence.last_seen_at if presence else None
        seconds_since_seen = int((current_time - last_seen_at).total_seconds()) if last_seen_at else None
        is_online = seconds_since_seen is not None and seconds_since_seen <= 180
        rows.append(
            {
                "username": row.username,
                "full_name": row.full_name,
                "role": role,
                "district": row.district,
                "room_name": None if presence is None else presence.room_name,
                "status_label": "offline" if not is_online else (presence.status_label if presence else "available"),
                "is_online": is_online,
                "last_seen_at": None if last_seen_at is None else last_seen_at.isoformat(),
                "seconds_since_seen": seconds_since_seen,
            }
        )
    return rows

@app.post('/personnel/presence/heartbeat')
def personnel_presence_heartbeat(
    body: PresenceHeartbeatCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    row = db.query(PersonnelPresence).filter(PersonnelPresence.username == user.username).first()
    if not row:
        row = PersonnelPresence(username=user.username)
        db.add(row)
    row.room_name = body.room_name
    row.district = body.district or user.district
    row.status_label = body.status_label
    row.last_seen_at = datetime.utcnow()
    db.commit()
    return {"status": "ok", "username": user.username, "last_seen_at": row.last_seen_at.isoformat()}

@app.get('/internal-comms/rooms')
def internal_comms_rooms(
    district: str | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    rows = visible_department_message_rows(db, user, district=district)
    read_lookup = department_room_read_lookup(db, user.username)
    active_typing = typing_signal_rows(db, district=district)
    typing_by_room = defaultdict(int)
    for row in active_typing:
        typing_by_room[row.room_name] += 1
    grouped = defaultdict(lambda: {
        "room_name": None,
        "channel_scope": "statewide",
        "district": None,
        "case_id": None,
        "message_count": 0,
        "unread_count": 0,
        "latest_sender": None,
        "latest_priority": "routine",
        "latest_activity": None,
        "latest_message": None,
    })

    for row in rows:
        slot = grouped[row.room_name]
        slot["room_name"] = row.room_name
        slot["channel_scope"] = row.channel_scope
        slot["district"] = row.district
        slot["case_id"] = row.case_id
        slot["message_count"] += 1
        if row.sender_username != user.username and row.id > read_lookup.get(row.room_name, 0):
            slot["unread_count"] += 1
        if slot["latest_activity"] is None or row.created_at > slot["latest_activity"]:
            slot["latest_sender"] = row.sender_username
            slot["latest_priority"] = row.priority
            slot["latest_activity"] = row.created_at
            slot["latest_message"] = row.message_text

    output = []
    for room_name, slot in grouped.items():
        output.append({
            "room_name": room_name,
            "channel_scope": slot["channel_scope"],
            "district": slot["district"],
            "case_id": slot["case_id"],
            "message_count": slot["message_count"],
            "unread_count": slot["unread_count"],
            "latest_sender": slot["latest_sender"],
            "latest_priority": slot["latest_priority"],
            "latest_activity": None if slot["latest_activity"] is None else slot["latest_activity"].isoformat(),
            "latest_message": slot["latest_message"],
            "typing_count": typing_by_room.get(room_name, 0),
        })
    return sorted(output, key=lambda row: row.get("latest_activity") or "", reverse=True)

@app.get('/internal-comms/messages')
def internal_comms_messages(
    district: str | None = None,
    room_name: str | None = None,
    channel_scope: str | None = None,
    case_id: int | None = None,
    recipient_username: str | None = None,
    limit: int = 120,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    rows = visible_department_message_rows(db, user, district=district)
    if room_name:
        rows = [row for row in rows if row.room_name == room_name]
    if channel_scope:
        rows = [row for row in rows if row.channel_scope == channel_scope]
    if case_id:
        rows = [row for row in rows if row.case_id == case_id]
    if recipient_username:
        rows = [
            row for row in rows
            if row.recipient_username in {None, recipient_username} or row.sender_username == user.username
        ]

    read_lookup = department_room_read_lookup(db, user.username)
    attachment_lookup = department_attachment_lookup(db, [row.id for row in rows[: min(limit, 200)]])
    return [
        serialize_department_message(row, user.username, read_lookup, attachment_lookup=attachment_lookup)
        for row in rows[: min(limit, 200)]
    ]

@app.post('/internal-comms/messages')
def create_internal_comms_message(
    body: DepartmentMessageCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    clean_mentions = parse_message_mentions(db, body.message_text)
    row = DepartmentMessage(
        sender_username=user.username,
        recipient_username=body.recipient_username,
        district=body.district,
        room_name=body.room_name,
        channel_scope=body.channel_scope,
        priority=body.priority,
        message_text=body.message_text,
        ack_required=body.ack_required,
        case_id=body.case_id,
    )
    db.add(row)
    db.flush()

    for attachment in body.attachments:
        db.add(
            MessageAttachment(
                message_id=row.id,
                attachment_name=attachment.attachment_name,
                attachment_type=attachment.attachment_type,
                storage_ref=attachment.storage_ref,
                uploaded_by=user.username,
            )
        )

    recipient = body.recipient_username or body.room_name
    db.add(
        NotificationEvent(
            notification_type="internal_message",
            channel="in_app",
            recipient=recipient,
            subject=f"{body.room_name} update",
            message=body.message_text,
            status="queued",
            related_object_type="department_message",
            related_object_id=str(row.id),
        )
    )
    for mentioned_username in clean_mentions:
        if mentioned_username == user.username:
            continue
        db.add(
            NotificationEvent(
                notification_type="mention",
                channel="in_app",
                recipient=mentioned_username,
                subject=f"Mention in {body.room_name}",
                message=body.message_text,
                status="queued",
                related_object_type="department_message",
                related_object_id=str(row.id),
            )
        )
    log_action(db, user.username, 'create_department_message', 'department_message', str(row.id))
    db.commit()
    attachment_lookup = department_attachment_lookup(db, [row.id])
    payload = serialize_department_message(row, user.username, {row.room_name: row.id}, attachment_lookup=attachment_lookup)
    payload["event_type"] = "message"
    payload["mentioned_usernames"] = clean_mentions
    dispatch_realtime_payload(row.room_name, payload)
    return {"status": "created", "message_id": row.id}

@app.post('/internal-comms/mark-read')
def mark_internal_comms_read(
    body: DepartmentMessageReadCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    visible_rows = visible_department_message_rows(db, user)
    room_rows = [row for row in visible_rows if row.room_name == body.room_name]
    if not room_rows:
        raise HTTPException(status_code=404, detail='Room not found')

    last_read_message_id = body.last_read_message_id or max(row.id for row in room_rows)
    receipt = db.query(DepartmentMessageRead).filter(
        DepartmentMessageRead.username == user.username,
        DepartmentMessageRead.room_name == body.room_name,
    ).first()
    if not receipt:
        receipt = DepartmentMessageRead(
            username=user.username,
            room_name=body.room_name,
            last_read_message_id=last_read_message_id,
        )
        db.add(receipt)
    else:
        receipt.last_read_message_id = max(receipt.last_read_message_id, last_read_message_id)
        receipt.read_at = datetime.utcnow()

    log_action(db, user.username, 'mark_department_room_read', 'department_room', body.room_name)
    db.commit()
    return {"status": "ok", "room_name": body.room_name, "last_read_message_id": receipt.last_read_message_id}


@app.get('/internal-comms/typing')
def internal_comms_typing(
    room_name: str | None = None,
    district: str | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    rows = typing_signal_rows(db, room_name=room_name, district=district)
    current_role = role_name(db, user)
    return [
        {
            "username": row.username,
            "room_name": row.room_name,
            "district": row.district,
            "case_id": row.case_id,
            "typing_until": row.typing_until.isoformat(),
            "seconds_remaining": max(int((row.typing_until - datetime.utcnow()).total_seconds()), 0),
        }
        for row in rows
        if row.username != user.username and not (current_role == "district_sp" and user.district and row.district not in {None, user.district})
    ]


@app.post('/internal-comms/typing')
def internal_comms_typing_heartbeat(
    body: TypingHeartbeatCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    row = db.query(RoomTypingSignal).filter(
        RoomTypingSignal.username == user.username,
        RoomTypingSignal.room_name == body.room_name,
    ).first()
    if body.is_typing:
        if not row:
            row = RoomTypingSignal(username=user.username, room_name=body.room_name)
            db.add(row)
        row.district = body.district or user.district
        row.case_id = body.case_id
        row.typing_until = datetime.utcnow() + timedelta(seconds=16)
        db.commit()
        payload = {
            "event_type": "typing",
            "username": user.username,
            "room_name": body.room_name,
            "district": row.district,
            "typing_until": row.typing_until.isoformat(),
        }
        dispatch_realtime_payload(body.room_name, payload)
        return {"status": "ok", **payload}
    if row:
        db.delete(row)
        db.commit()
    payload = {
        "event_type": "typing_stopped",
        "username": user.username,
        "room_name": body.room_name,
    }
    dispatch_realtime_payload(body.room_name, payload)
    return {"status": "ok", **payload}


@app.websocket('/internal-comms/ws')
async def internal_comms_ws(websocket: WebSocket):
    token = websocket.query_params.get("token")
    room_name = websocket.query_params.get("room_name") or "State Command Net"
    district = websocket.query_params.get("district")
    db = SessionLocal()
    try:
        if not token:
            await websocket.close(code=4401)
            return
        try:
            user = current_user_from_token(token, db)
        except HTTPException:
            await websocket.close(code=4401)
            return
        if district and role_name(db, user) == "district_sp" and user.district and district != user.district:
            await websocket.close(code=4403)
            return
        await realtime_manager.connect(room_name, websocket)
        await websocket.send_json(
            {
                "event_type": "connected",
                "room_name": room_name,
                "district": district or user.district,
                "username": user.username,
            }
        )
        while True:
            _ = await websocket.receive_text()
    except WebSocketDisconnect:
        realtime_manager.disconnect(room_name, websocket)
    finally:
        db.close()

@app.get('/checkpoint-plans')
def checkpoint_plans(
    district: str | None = None,
    status: str | None = None,
    route_ref: str | None = None,
    case_id: int | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    q = db.query(CheckpointPlan)
    current_role = role_name(db, user)
    if current_role == 'district_sp' and user.district:
        q = q.filter(CheckpointPlan.district == user.district)
    elif district:
        q = q.filter(CheckpointPlan.district == district)
    if status:
        q = q.filter(CheckpointPlan.status == status)
    if route_ref:
        q = q.filter(CheckpointPlan.route_ref == route_ref)
    if case_id:
        q = q.filter(CheckpointPlan.case_id == case_id)
    rows = q.order_by(CheckpointPlan.id.desc()).all()
    return [{
        "id": row.id,
        "district": row.district,
        "checkpoint_name": row.checkpoint_name,
        "checkpoint_type": row.checkpoint_type,
        "route_ref": row.route_ref,
        "status": row.status,
        "assigned_unit": row.assigned_unit,
        "latitude": row.latitude,
        "longitude": row.longitude,
        "case_id": row.case_id,
        "notes": row.notes,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat(),
    } for row in rows]

@app.post('/checkpoint-plans')
def create_checkpoint_plan(
    body: CheckpointPlanCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    row = CheckpointPlan(**body.model_dump(), created_by=user.username)
    db.add(row)
    db.flush()
    log_action(db, user.username, 'create_checkpoint_plan', 'checkpoint_plan', str(row.id))
    db.commit()
    return {"status": "created", "checkpoint_id": row.id}

@app.get('/graph/case/{case_id}')
def case_graph(case_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    links = db.query(ComplaintCaseLink).filter(ComplaintCaseLink.case_id == case_id).all()
    evidence = db.query(EvidenceAttachment).filter(EvidenceAttachment.case_id == case_id).all()
    timeline = db.query(CaseTimelineEvent).filter(CaseTimelineEvent.case_id == case_id).all()
    entity_rows = db.query(Entity).limit(20).all()
    edge_rows = db.query(EntityLink).limit(30).all()
    snapshot = db.query(GraphSnapshot).filter(GraphSnapshot.case_id == case_id).order_by(GraphSnapshot.id.desc()).first()
    nodes = [{"id": f"case-{case_id}", "label": f"Case {case_id}", "type": "case"}]
    for e in entity_rows:
        nodes.append({"id": f"entity-{e.id}", "label": e.display_name, "type": e.entity_type, "risk_score": e.risk_score})
    for ev in evidence:
        nodes.append({"id": f"evidence-{ev.id}", "label": ev.file_name, "type": "evidence"})
    edges = []
    for l in edge_rows:
        edges.append({"source": f"entity-{l.source_entity_id}", "target": f"entity-{l.target_entity_id}", "label": l.relationship_type, "weight": l.weight})
    for ev in evidence:
        edges.append({"source": f"case-{case_id}", "target": f"evidence-{ev.id}", "label": ev.attachment_type, "weight": 1})
    return {"nodes": nodes, "edges": edges, "snapshot": None if not snapshot else {"node_count": snapshot.node_count, "edge_count": snapshot.edge_count, "risk_density": snapshot.risk_density, "summary": snapshot.summary}, "timeline_count": len(timeline), "complaint_links": len(links)}


@app.get('/graph/expand')
def graph_expand(
    node_id: str,
    district: str | None = None,
    case_id: int | None = None,
    depth: int = 1,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    nodes, edges = build_graph_scope(db, district=district, case_id=case_id)
    if node_id not in nodes:
        raise HTTPException(status_code=404, detail='Graph node not found')
    adjacency = graph_adjacency(edges)
    queue = deque([(node_id, 0)])
    visited = {node_id}
    while queue:
        current_id, current_depth = queue.popleft()
        if current_depth >= max(min(depth, 3), 1):
            continue
        for peer_id, _edge in adjacency.get(current_id, []):
            if peer_id in visited:
                continue
            visited.add(peer_id)
            queue.append((peer_id, current_depth + 1))
    expanded_edges = [row for row in edges if row["source"] in visited and row["target"] in visited]
    return {
        "center_node": nodes[node_id],
        "depth": max(min(depth, 3), 1),
        "nodes": [nodes[row_id] for row_id in visited if row_id in nodes],
        "edges": expanded_edges,
    }


@app.get('/graph/trace')
def graph_trace(
    source_node_id: str,
    target_node_id: str,
    district: str | None = None,
    case_id: int | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    nodes, edges = build_graph_scope(db, district=district, case_id=case_id)
    if source_node_id not in nodes or target_node_id not in nodes:
        raise HTTPException(status_code=404, detail='Trace nodes not found')
    payload = shortest_graph_path(nodes, edges, source_node_id, target_node_id)
    payload["source_node"] = nodes[source_node_id]
    payload["target_node"] = nodes[target_node_id]
    return payload


@app.get('/graph/compare')
def graph_compare(
    left_node_id: str,
    right_node_id: str,
    district: str | None = None,
    case_id: int | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    nodes, edges = build_graph_scope(db, district=district, case_id=case_id)
    if left_node_id not in nodes or right_node_id not in nodes:
        raise HTTPException(status_code=404, detail='Comparison nodes not found')
    adjacency = graph_adjacency(edges)
    left_neighbors = {peer_id for peer_id, _row in adjacency.get(left_node_id, [])}
    right_neighbors = {peer_id for peer_id, _row in adjacency.get(right_node_id, [])}
    shared_neighbors = sorted(left_neighbors & right_neighbors)
    unique_left = sorted(left_neighbors - right_neighbors)
    unique_right = sorted(right_neighbors - left_neighbors)
    overlap_ratio = round(len(shared_neighbors) / max(len(left_neighbors | right_neighbors), 1), 3)
    return {
        "left_node": nodes[left_node_id],
        "right_node": nodes[right_node_id],
        "shared_neighbors": [nodes[row_id] for row_id in shared_neighbors if row_id in nodes],
        "left_unique_neighbors": [nodes[row_id] for row_id in unique_left if row_id in nodes][:12],
        "right_unique_neighbors": [nodes[row_id] for row_id in unique_right if row_id in nodes][:12],
        "overlap_ratio": overlap_ratio,
        "risk_delta": round(abs(float(nodes[left_node_id].get("risk_score", 0.0)) - float(nodes[right_node_id].get("risk_score", 0.0))), 3),
    }


@app.get('/graph/saved-views')
def graph_saved_views(
    district: str | None = None,
    case_id: int | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    q = db.query(GraphSavedView).filter(GraphSavedView.username == user.username)
    if district:
        q = q.filter(or_(GraphSavedView.district == district, GraphSavedView.district == None))
    if case_id:
        q = q.filter(or_(GraphSavedView.case_id == case_id, GraphSavedView.case_id == None))
    rows = q.order_by(GraphSavedView.id.desc()).all()
    return [
        {
            "id": row.id,
            "username": row.username,
            "title": row.title,
            "district": row.district,
            "case_id": row.case_id,
            "focus_node_id": row.focus_node_id,
            "selected_node_ids": json.loads(row.selected_node_ids_json or "[]"),
            "notes": row.notes,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


@app.post('/graph/saved-views')
def create_graph_saved_view(
    body: GraphSavedViewCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    row = GraphSavedView(
        username=user.username,
        title=body.title,
        district=body.district,
        case_id=body.case_id,
        focus_node_id=body.focus_node_id,
        selected_node_ids_json=json.dumps(body.selected_node_ids),
        notes=body.notes,
    )
    db.add(row)
    db.flush()
    log_action(db, user.username, 'create_graph_saved_view', 'graph_saved_view', str(row.id))
    db.commit()
    return {"status": "created", "saved_view_id": row.id}


@app.get('/ontology/classes')
def ontology_classes(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(OntologyClass).order_by(OntologyClass.category, OntologyClass.display_name).all()
    return [
        {
            "id": row.id,
            "class_name": row.class_name,
            "display_name": row.display_name,
            "description": row.description,
            "category": row.category,
            "attribute_schema": safe_json_list(row.attribute_schema_json),
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


@app.get('/ontology/relationship-types')
def ontology_relationship_types(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(OntologyRelationType).order_by(OntologyRelationType.relation_name).all()
    return [
        {
            "id": row.id,
            "relation_name": row.relation_name,
            "source_class": row.source_class,
            "target_class": row.target_class,
            "description": row.description,
            "directionality": row.directionality,
            "confidence_band": row.confidence_band,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


@app.get('/ontology/attribute-facts')
def ontology_attribute_facts(
    entity_id: int | None = None,
    district: str | None = None,
    attribute_name: str | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    q = db.query(EntityAttributeFact, Entity).join(Entity, EntityAttributeFact.entity_id == Entity.id)
    if entity_id:
        q = q.filter(EntityAttributeFact.entity_id == entity_id)
    if district:
        q = q.filter(Entity.district == district)
    if attribute_name:
        q = q.filter(EntityAttributeFact.attribute_name == attribute_name)
    rows = q.order_by(EntityAttributeFact.observed_at.desc(), EntityAttributeFact.id.desc()).all()
    return [
        {
            "id": fact.id,
            "entity_id": fact.entity_id,
            "entity_name": entity.display_name,
            "entity_type": entity.entity_type,
            "district": entity.district,
            "attribute_name": fact.attribute_name,
            "attribute_value": fact.attribute_value,
            "value_type": fact.value_type,
            "confidence": fact.confidence,
            "source_name": fact.source_name,
            "source_ref": fact.source_ref,
            "observed_at": fact.observed_at.isoformat(),
        }
        for fact, entity in rows
    ]


@app.get('/ontology/entities/{entity_id}/profile')
def ontology_entity_profile(
    entity_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    entity = db.query(Entity).filter(Entity.id == entity_id).first()
    if not entity:
        raise HTTPException(status_code=404, detail='Entity not found')

    attribute_rows = db.query(EntityAttributeFact).filter(EntityAttributeFact.entity_id == entity_id).order_by(EntityAttributeFact.confidence.desc()).all()
    candidate_rows = db.query(EntityResolutionCandidate).filter(
        or_(EntityResolutionCandidate.left_entity_id == entity_id, EntityResolutionCandidate.right_entity_id == entity_id)
    ).order_by(EntityResolutionCandidate.match_score.desc()).all()
    candidate_ids = [row.id for row in candidate_rows]
    decision_rows = db.query(EntityResolutionDecision).filter(EntityResolutionDecision.candidate_id.in_(candidate_ids)).order_by(EntityResolutionDecision.created_at.desc()).all() if candidate_ids else []
    provenance_rows = db.query(ProvenanceRecord).filter(
        or_(
            (ProvenanceRecord.object_type == "entity") & (ProvenanceRecord.object_id == str(entity_id)),
            ProvenanceRecord.source_ref == str(entity_id),
        )
    ).order_by(ProvenanceRecord.observed_at.desc()).all()
    artifact_rows = db.query(ConnectorArtifact).filter(ConnectorArtifact.entity_id == entity_id).order_by(ConnectorArtifact.created_at.desc()).all()
    watchlist_rows = db.query(WatchlistHit).filter(WatchlistHit.entity_id == entity_id).order_by(WatchlistHit.created_at.desc()).all()
    link_rows = db.query(EntityLink).filter(
        or_(EntityLink.source_entity_id == entity_id, EntityLink.target_entity_id == entity_id)
    ).order_by(EntityLink.weight.desc()).all()
    entity_lookup = entity_lookup_map(db)

    neighbor_rows = []
    for row in link_rows:
        peer_id = row.target_entity_id if row.source_entity_id == entity_id else row.source_entity_id
        peer = entity_lookup.get(peer_id)
        if not peer:
            continue
        neighbor_rows.append(
            {
                "peer_entity_id": peer.id,
                "peer_entity_name": peer.display_name,
                "peer_entity_type": peer.entity_type,
                "peer_district": peer.district,
                "relationship_type": row.relationship_type,
                "weight": row.weight,
            }
        )

    return {
        "entity": serialize_entity(entity),
        "attributes": [
            {
                "attribute_name": row.attribute_name,
                "attribute_value": row.attribute_value,
                "value_type": row.value_type,
                "confidence": row.confidence,
                "source_name": row.source_name,
                "source_ref": row.source_ref,
                "observed_at": row.observed_at.isoformat(),
            }
            for row in attribute_rows
        ],
        "resolution_candidates": [entity_resolution_candidate_payload(row, entity_lookup) for row in candidate_rows],
        "resolution_decisions": [
            {
                "id": row.id,
                "candidate_id": row.candidate_id,
                "decision_status": row.decision_status,
                "decided_by": row.decided_by,
                "notes": row.notes,
                "created_at": row.created_at.isoformat(),
            }
            for row in decision_rows
        ],
        "provenance": [
            {
                "id": row.id,
                "object_type": row.object_type,
                "object_id": row.object_id,
                "district": row.district,
                "source_name": row.source_name,
                "source_type": row.source_type,
                "source_ref": row.source_ref,
                "operation": row.operation,
                "confidence": row.confidence,
                "collected_by": row.collected_by,
                "notes": row.notes,
                "observed_at": row.observed_at.isoformat(),
            }
            for row in provenance_rows
        ],
        "connector_artifacts": [serialize_connector_artifact(row, entity_lookup=entity_lookup) for row in artifact_rows],
        "watchlist_hits": [
            {
                "id": row.id,
                "watchlist_id": row.watchlist_id,
                "case_id": row.case_id,
                "incident_id": row.incident_id,
                "hit_reason": row.hit_reason,
                "confidence": row.confidence,
                "created_at": row.created_at.isoformat(),
            }
            for row in watchlist_rows
        ],
        "neighbors": neighbor_rows,
    }


@app.get('/entity-resolution/candidates')
def entity_resolution_candidates(
    district: str | None = None,
    status: str | None = None,
    entity_id: int | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    rows = db.query(EntityResolutionCandidate).order_by(EntityResolutionCandidate.match_score.desc(), EntityResolutionCandidate.id.desc()).all()
    entity_lookup = entity_lookup_map(db)
    output = []
    for row in rows:
        left_entity = entity_lookup.get(row.left_entity_id)
        right_entity = entity_lookup.get(row.right_entity_id)
        if district and district not in {getattr(left_entity, "district", None), getattr(right_entity, "district", None)}:
            continue
        if status and row.status != status:
            continue
        if entity_id and entity_id not in {row.left_entity_id, row.right_entity_id}:
            continue
        output.append(entity_resolution_candidate_payload(row, entity_lookup))
    return output


@app.get('/entity-resolution/decisions')
def entity_resolution_decisions(
    district: str | None = None,
    candidate_id: int | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    candidate_lookup = {row.id: row for row in db.query(EntityResolutionCandidate).all()}
    entity_lookup = entity_lookup_map(db)
    q = db.query(EntityResolutionDecision)
    if candidate_id:
        q = q.filter(EntityResolutionDecision.candidate_id == candidate_id)
    rows = q.order_by(EntityResolutionDecision.created_at.desc()).all()
    output = []
    for row in rows:
        candidate = candidate_lookup.get(row.candidate_id)
        if not candidate:
            continue
        candidate_payload = entity_resolution_candidate_payload(candidate, entity_lookup)
        if district and district not in {candidate_payload.get("left_district"), candidate_payload.get("right_district")}:
            continue
        output.append(
            {
                "id": row.id,
                "candidate_id": row.candidate_id,
                "decision_status": row.decision_status,
                "decided_by": row.decided_by,
                "notes": row.notes,
                "created_at": row.created_at.isoformat(),
                "left_entity_name": candidate_payload.get("left_entity_name"),
                "right_entity_name": candidate_payload.get("right_entity_name"),
                "cluster_ref": candidate_payload.get("cluster_ref"),
            }
        )
    return output


@app.post('/entity-resolution/resolve')
def entity_resolution_resolve(
    body: EntityResolutionActionCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    candidate = db.query(EntityResolutionCandidate).filter(EntityResolutionCandidate.id == body.candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail='Resolution candidate not found')

    candidate.status = body.decision_status
    decision = EntityResolutionDecision(
        candidate_id=candidate.id,
        decision_status=body.decision_status,
        decided_by=user.username,
        notes=body.notes,
    )
    db.add(decision)

    if body.decision_status == "accepted":
        link_exists = db.query(EntityLink).filter_by(
            source_entity_id=candidate.left_entity_id,
            target_entity_id=candidate.right_entity_id,
            relationship_type="resolved_same_entity",
        ).first()
        if not link_exists:
            db.add(
                EntityLink(
                    source_entity_id=candidate.left_entity_id,
                    target_entity_id=candidate.right_entity_id,
                    relationship_type="resolved_same_entity",
                    weight=max(candidate.match_score, 0.8),
                )
            )

    db.add(
        ProvenanceRecord(
            object_type="resolution_candidate",
            object_id=str(candidate.id),
            district=None,
            source_name="entity_resolution_workbench",
            source_type="analyst_decision",
            source_ref=candidate.cluster_ref or str(candidate.id),
            operation=body.decision_status,
            confidence=candidate.match_score,
            collected_by=user.username,
            notes=body.notes or f"Resolution candidate set to {body.decision_status}.",
        )
    )
    log_action(db, user.username, 'resolve_entity_candidate', 'entity_resolution_candidate', str(candidate.id))
    db.commit()
    return {
        "status": "ok",
        "candidate_id": candidate.id,
        "decision_status": decision.decision_status,
        "decision_id": decision.id,
    }


@app.get('/provenance/records')
def provenance_records(
    object_type: str | None = None,
    object_id: str | None = None,
    district: str | None = None,
    entity_id: int | None = None,
    case_id: int | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    q = db.query(ProvenanceRecord)
    if object_type:
        q = q.filter(ProvenanceRecord.object_type == object_type)
    if object_id:
        q = q.filter(ProvenanceRecord.object_id == object_id)
    if district:
        q = q.filter(ProvenanceRecord.district == district)
    if entity_id:
        q = q.filter(ProvenanceRecord.object_type == "entity", ProvenanceRecord.object_id == str(entity_id))
    if case_id:
        q = q.filter(ProvenanceRecord.object_type == "case", ProvenanceRecord.object_id == str(case_id))
    rows = q.order_by(ProvenanceRecord.observed_at.desc(), ProvenanceRecord.id.desc()).all()
    return [
        {
            "id": row.id,
            "object_type": row.object_type,
            "object_id": row.object_id,
            "district": row.district,
            "source_name": row.source_name,
            "source_type": row.source_type,
            "source_ref": row.source_ref,
            "operation": row.operation,
            "confidence": row.confidence,
            "collected_by": row.collected_by,
            "notes": row.notes,
            "observed_at": row.observed_at.isoformat(),
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


@app.get('/connectors/runs')
def connector_runs(
    connector_name: str | None = None,
    status: str | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    q = db.query(ConnectorRun)
    if connector_name:
        q = q.filter(ConnectorRun.connector_name == connector_name)
    if status:
        q = q.filter(ConnectorRun.status == status)
    rows = q.order_by(ConnectorRun.id.desc()).all()
    return [serialize_connector_run(row) for row in rows]


@app.get('/connectors/artifacts')
def connector_artifacts(
    connector_name: str | None = None,
    district: str | None = None,
    case_id: int | None = None,
    entity_id: int | None = None,
    status: str | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    q = db.query(ConnectorArtifact)
    if connector_name:
        q = q.filter(ConnectorArtifact.connector_name == connector_name)
    if district:
        q = q.filter(ConnectorArtifact.district == district)
    if case_id:
        q = q.filter(ConnectorArtifact.case_id == case_id)
    if entity_id:
        q = q.filter(ConnectorArtifact.entity_id == entity_id)
    if status:
        q = q.filter(ConnectorArtifact.status == status)
    rows = q.order_by(ConnectorArtifact.id.desc()).all()
    entity_lookup = entity_lookup_map(db)
    return [serialize_connector_artifact(row, entity_lookup=entity_lookup) for row in rows]


@app.post('/connectors/runs/trigger')
def trigger_connector_run(
    body: ConnectorRunCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    timestamp_tag = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    run = ConnectorRun(
        connector_name=body.connector_name,
        run_mode=body.run_mode,
        status="completed",
        records_seen=0,
        records_emitted=0,
        latency_ms=420,
        notes=body.notes or f"Manual connector trigger by {user.username}.",
        started_at=datetime.utcnow(),
        finished_at=datetime.utcnow(),
    )
    db.add(run)
    db.flush()

    entity_rows = {row.display_name: row for row in db.query(Entity).all()}
    case_rows = {row.title: row for row in db.query(Case).all()}
    artifact_blueprints = {
        "tn_cctns_citizen_portal": [
            ("complaint", f"CMP-REF-001-RUN-{timestamp_tag}", "Chennai", case_rows.get("Chennai wallet scam cluster"), entity_rows.get("Ravi Kumar"), "Citizen complaint complaint packet synchronized into operations fabric."),
        ],
        "national_cybercrime_portal": [
            ("alias_profile", f"NCCRP-RK-{timestamp_tag}", "Chennai", case_rows.get("Chennai wallet scam cluster"), entity_rows.get("R. Kumar"), "Alias profile artifact synced from cybercrime portal watchlist lane."),
        ],
        "patrol_reporting_ingest": [
            ("patrol_update", f"PATROL-MDU-{timestamp_tag}", "Madurai", case_rows.get("Madurai retaliation watch"), entity_rows.get("Sathish"), "Patrol update ingested for retaliation saturation corridor."),
        ],
        "cctv_event_bridge": [
            ("camera_event", f"CCTV-CHE-{timestamp_tag}", "Chennai", case_rows.get("Chennai wallet scam cluster"), entity_rows.get("IMEI-8899-XX"), "Camera anomaly artifact linked to the active fraud command thread."),
        ],
    }
    blueprints = artifact_blueprints.get(body.connector_name, [
        ("connector_record", f"{simple_slug(body.connector_name).upper()}-{timestamp_tag}", None, None, None, "Connector run completed without a mapped artifact blueprint."),
    ])

    emitted_count = 0
    for record_type, external_ref, artifact_district, artifact_case, artifact_entity, ingest_summary in blueprints:
        db.add(
            ConnectorArtifact(
                connector_run_id=run.id,
                connector_name=body.connector_name,
                record_type=record_type,
                external_ref=external_ref,
                district=artifact_district,
                case_id=None if artifact_case is None else artifact_case.id,
                entity_id=None if artifact_entity is None else artifact_entity.id,
                ingest_summary=ingest_summary,
                status="ingested",
            )
        )
        emitted_count += 1

    run.records_seen = emitted_count + 2
    run.records_emitted = emitted_count
    db.add(
        IngestQueue(
            source_name=body.connector_name,
            payload_ref=f"manual-trigger:{timestamp_tag}",
            status="processed",
            processed_at=datetime.utcnow(),
        )
    )
    db.add(
        NotificationEvent(
            notification_type="connector_run",
            channel="in_app",
            recipient=user.username,
            subject=f"{body.connector_name} connector run completed",
            message=f"Connector run emitted {emitted_count} operational artifact(s).",
            status="queued",
            related_object_type="connector_run",
            related_object_id=str(run.id),
        )
    )
    log_action(db, user.username, 'trigger_connector_run', 'connector_run', str(run.id))
    db.commit()
    return {
        "status": "ok",
        "run": serialize_connector_run(run),
        "artifacts_created": emitted_count,
    }


@app.get('/video/sessions')
def list_video_sessions(
    district: str | None = None,
    status: str | None = None,
    room_name: str | None = None,
    case_id: int | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    q = db.query(VideoSession)
    current_role = role_name(db, user)
    if current_role == "district_sp" and user.district:
        q = q.filter(or_(VideoSession.district == user.district, VideoSession.district == None))
    elif district:
        q = q.filter(or_(VideoSession.district == district, VideoSession.district == None))
    if status:
        q = q.filter(VideoSession.status == status)
    if room_name:
        q = q.filter(VideoSession.room_name == room_name)
    if case_id:
        q = q.filter(VideoSession.case_id == case_id)
    rows = q.order_by(VideoSession.started_at.desc(), VideoSession.id.desc()).all()
    participant_rows = db.query(VideoParticipant).all()
    participant_counts = defaultdict(int)
    hand_raise_counts = defaultdict(int)
    screen_share_counts = defaultdict(int)
    for participant in participant_rows:
        participant_counts[participant.session_id] += 1
        hand_raise_counts[participant.session_id] += 1 if participant.hand_raised else 0
        screen_share_counts[participant.session_id] += 1 if participant.screen_sharing else 0
    output = []
    for row in rows:
        payload = serialize_video_session(row, current_username=user.username)
        payload["participant_count"] = participant_counts.get(row.id, 0)
        payload["raised_hands"] = hand_raise_counts.get(row.id, 0)
        payload["screen_shares"] = screen_share_counts.get(row.id, 0)
        output.append(payload)
    return output


@app.post('/video/sessions')
def create_video_session(
    body: VideoSessionCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    district_scope = body.district or user.district
    session_code_base = f"tn-police-{simple_slug(district_scope or 'statewide')}-{simple_slug(body.room_name)}-{body.case_id or 'ops'}"
    row = db.query(VideoSession).filter(
        VideoSession.session_code == session_code_base,
        VideoSession.status == "active",
    ).first()
    created = False
    if not row:
        row = VideoSession(
            room_name=body.room_name,
            district=district_scope,
            case_id=body.case_id,
            session_code=session_code_base,
            session_mode=body.session_mode,
            status="active",
            notes=body.notes,
            started_by=user.username,
        )
        db.add(row)
        db.flush()
        created = True

    participant = db.query(VideoParticipant).filter(
        VideoParticipant.session_id == row.id,
        VideoParticipant.username == user.username,
    ).first()
    if not participant:
        participant = VideoParticipant(
            session_id=row.id,
            username=user.username,
            role_label=role_name(db, user),
            device_label="Browser console",
            join_state="connected",
            muted=False,
            camera_enabled=True,
            screen_sharing=False,
        )
        db.add(participant)

    db.add(
        NotificationEvent(
            notification_type="video_session",
            channel="in_app",
            recipient=body.room_name,
            subject=f"Video briefing {row.session_code}",
            message=f"{user.username} {'created' if created else 'rejoined'} the video session.",
            status="queued",
            related_object_type="video_session",
            related_object_id=str(row.id),
        )
    )
    log_action(db, user.username, 'create_video_session', 'video_session', str(row.id))
    db.commit()
    payload = serialize_video_session(row, current_username=user.username)
    payload["event_type"] = "session_created" if created else "session_joined"
    dispatch_realtime_payload(video_room_name(row.session_code), payload)
    return {
        "status": "created" if created else "existing",
        "session": serialize_video_session(row, current_username=user.username),
    }


@app.get('/video/sessions/{session_code}/participants')
def list_video_participants(
    session_code: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    session_row = db.query(VideoSession).filter(VideoSession.session_code == session_code).first()
    if not session_row:
        raise HTTPException(status_code=404, detail='Video session not found')
    rows = db.query(VideoParticipant).filter(VideoParticipant.session_id == session_row.id).order_by(VideoParticipant.last_seen_at.desc()).all()
    current_time = datetime.utcnow()
    output = []
    for row in rows:
        payload = serialize_video_participant(row)
        payload["seconds_since_seen"] = int((current_time - row.last_seen_at).total_seconds()) if row.last_seen_at else None
        payload["is_online"] = payload["seconds_since_seen"] is not None and payload["seconds_since_seen"] <= 150
        output.append(payload)
    return output


@app.post('/video/sessions/{session_code}/participant-state')
def update_video_participant_state(
    session_code: str,
    body: VideoParticipantStateCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    session_row = db.query(VideoSession).filter(VideoSession.session_code == session_code).first()
    if not session_row:
        raise HTTPException(status_code=404, detail='Video session not found')
    participant = db.query(VideoParticipant).filter(
        VideoParticipant.session_id == session_row.id,
        VideoParticipant.username == user.username,
    ).first()
    if not participant:
        participant = VideoParticipant(
            session_id=session_row.id,
            username=user.username,
            role_label=role_name(db, user),
        )
        db.add(participant)
    if body.device_label is not None:
        participant.device_label = body.device_label
    if body.join_state is not None:
        participant.join_state = body.join_state
    if body.hand_raised is not None:
        participant.hand_raised = body.hand_raised
    if body.muted is not None:
        participant.muted = body.muted
    if body.camera_enabled is not None:
        participant.camera_enabled = body.camera_enabled
    if body.screen_sharing is not None:
        participant.screen_sharing = body.screen_sharing
    participant.last_seen_at = datetime.utcnow()
    db.commit()
    payload = serialize_video_participant(participant)
    payload["event_type"] = "participant_state"
    payload["session_code"] = session_code
    dispatch_realtime_payload(video_room_name(session_code), payload)
    return {"status": "ok", "participant": payload}


@app.websocket('/video/sessions/{session_code}/ws')
async def video_session_ws(websocket: WebSocket, session_code: str):
    token = websocket.query_params.get("token")
    db = SessionLocal()
    try:
        if not token:
            await websocket.close(code=4401)
            return
        try:
            user = current_user_from_token(token, db)
        except HTTPException:
            await websocket.close(code=4401)
            return
        session_row = db.query(VideoSession).filter(VideoSession.session_code == session_code).first()
        if not session_row:
            await websocket.close(code=4404)
            return
        await realtime_manager.connect(video_room_name(session_code), websocket)
        await websocket.send_json(
            {
                "event_type": "connected",
                "session_code": session_code,
                "room_name": session_row.room_name,
                "username": user.username,
            }
        )
        while True:
            signal_text = await websocket.receive_text()
            await realtime_manager.broadcast(
                video_room_name(session_code),
                {
                    "event_type": "signal",
                    "session_code": session_code,
                    "username": user.username,
                    "payload": signal_text[:500],
                },
            )
    except WebSocketDisconnect:
        realtime_manager.disconnect(video_room_name(session_code), websocket)
    finally:
        db.close()


@app.get('/geo/corridors')
def geo_corridors(
    district: str | None = None,
    corridor_type: str | None = None,
    route_ref: str | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    q = db.query(OperationalCorridor)
    if district:
        q = q.filter(OperationalCorridor.district == district)
    if corridor_type:
        q = q.filter(OperationalCorridor.corridor_type == corridor_type)
    if route_ref:
        q = q.filter(OperationalCorridor.route_ref == route_ref)
    rows = q.order_by(OperationalCorridor.risk_score.desc(), OperationalCorridor.id.desc()).all()
    return [
        {
            "id": row.id,
            "district": row.district,
            "corridor_name": row.corridor_name,
            "corridor_type": row.corridor_type,
            "route_ref": row.route_ref,
            "points": safe_json_list(row.points_json),
            "risk_score": row.risk_score,
            "surveillance_priority": row.surveillance_priority,
            "notes": row.notes,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


@app.get('/workflow/playbooks')
def workflow_playbooks(
    district: str | None = None,
    trigger_type: str | None = None,
    status: str | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    q = db.query(WorkflowPlaybook)
    current_role = role_name(db, user)
    if current_role == "district_sp" and user.district:
        q = q.filter(WorkflowPlaybook.district == user.district)
    elif district:
        q = q.filter(WorkflowPlaybook.district == district)
    if trigger_type:
        q = q.filter(WorkflowPlaybook.trigger_type == trigger_type)
    if status:
        q = q.filter(WorkflowPlaybook.status == status)
    rows = q.order_by(WorkflowPlaybook.district, WorkflowPlaybook.playbook_name).all()
    return [serialize_playbook(row) for row in rows]


@app.post('/workflow/playbooks/{playbook_id}/launch')
def workflow_playbook_launch(
    playbook_id: int,
    body: WorkflowPlaybookLaunchCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    playbook = db.query(WorkflowPlaybook).filter(WorkflowPlaybook.id == playbook_id).first()
    if not playbook:
        raise HTTPException(status_code=404, detail='Playbook not found')

    target_district = body.district or playbook.district
    assigned_unit = body.assigned_unit or playbook.assigned_unit_hint
    action_templates = safe_json_list(playbook.action_template_json)
    created_task_ids: list[int] = []
    created_checkpoint_ids: list[int] = []
    for action_name in action_templates:
        task = create_playbook_task(
            db,
            task_type=simple_slug(action_name),
            district=target_district,
            priority=playbook.default_priority,
            assigned_unit=assigned_unit,
            details=f"{playbook.playbook_name}: {action_name}. {body.notes or ''}".strip(),
            created_by=user.username,
            case_id=body.case_id,
        )
        created_task_ids.append(task.id)

    corridor = db.query(OperationalCorridor).filter(OperationalCorridor.district == target_district).order_by(OperationalCorridor.risk_score.desc()).first()
    if corridor:
        corridor_points = safe_json_list(corridor.points_json)
        first_point = corridor_points[0] if corridor_points else {}
        checkpoint = CheckpointPlan(
            district=target_district,
            checkpoint_name=f"{playbook.playbook_name} Checkpoint",
            checkpoint_type="playbook_lock",
            route_ref=corridor.route_ref,
            status="planned",
            assigned_unit=assigned_unit,
            latitude=first_point.get("latitude"),
            longitude=first_point.get("longitude"),
            case_id=body.case_id,
            notes=f"Checkpoint created from {playbook.playbook_name}. {body.notes or ''}".strip(),
            created_by=user.username,
        )
        db.add(checkpoint)
        db.flush()
        created_checkpoint_ids.append(checkpoint.id)

    if body.case_id:
        add_timeline(db, body.case_id, "playbook_launched", user.username, f"{playbook.playbook_name} launched with {len(created_task_ids)} tasks.")
    db.add(
        NotificationEvent(
            notification_type="workflow_playbook",
            channel="in_app",
            recipient=assigned_unit or target_district,
            subject=f"{playbook.playbook_name} launched",
            message=f"{len(created_task_ids)} tasks and {len(created_checkpoint_ids)} checkpoints created.",
            status="queued",
            related_object_type="workflow_playbook",
            related_object_id=str(playbook.id),
        )
    )
    log_action(db, user.username, 'launch_workflow_playbook', 'workflow_playbook', str(playbook.id))
    db.commit()
    return {
        "status": "ok",
        "playbook_id": playbook.id,
        "task_ids": created_task_ids,
        "checkpoint_ids": created_checkpoint_ids,
    }

@app.get('/geo/geofence-alerts')
def geofence_alerts(district: str | None = None, active: bool | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    q = db.query(GeoFenceAlert)
    if district: q = q.filter(GeoFenceAlert.district == district)
    if active is not None: q = q.filter(GeoFenceAlert.active == active)
    rows = q.order_by(GeoFenceAlert.id.desc()).all()
    return [{"id": r.id, "district": r.district, "zone_name": r.zone_name, "alert_type": r.alert_type, "threshold": r.threshold, "active": r.active, "notes": r.notes} for r in rows]


@app.get('/geo/boundaries')
def geo_boundaries(
    boundary_type: str | None = None,
    district: str | None = None,
    station_name: str | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    q = db.query(GeoBoundary)
    if boundary_type:
        q = q.filter(GeoBoundary.boundary_type == boundary_type)
    if district:
        q = q.filter(GeoBoundary.district == district)
    if station_name:
        q = q.filter(GeoBoundary.station_name == station_name)
    rows = q.order_by(GeoBoundary.boundary_type, GeoBoundary.district, GeoBoundary.zone_name).all()
    return [
        {
            "id": row.id,
            "boundary_type": row.boundary_type,
            "district": row.district,
            "station_name": row.station_name,
            "zone_name": row.zone_name,
            "centroid_latitude": row.centroid_latitude,
            "centroid_longitude": row.centroid_longitude,
            "points": json.loads(row.points_json or "[]"),
            "boundary_rank": row.boundary_rank,
        }
        for row in rows
    ]


@app.get('/geo/geofences')
def geo_geofences(
    district: str | None = None,
    station_name: str | None = None,
    status: str | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    q = db.query(GeofenceZone)
    if district:
        q = q.filter(GeofenceZone.district == district)
    if station_name:
        q = q.filter(GeofenceZone.station_name == station_name)
    if status:
        q = q.filter(GeofenceZone.status == status)
    rows = q.order_by(GeofenceZone.id.desc()).all()
    return [
        {
            "id": row.id,
            "district": row.district,
            "station_name": row.station_name,
            "zone_name": row.zone_name,
            "geofence_type": row.geofence_type,
            "center_latitude": row.center_latitude,
            "center_longitude": row.center_longitude,
            "radius_km": row.radius_km,
            "points": json.loads(row.points_json or "[]"),
            "status": row.status,
            "notes": row.notes,
            "created_by": row.created_by,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


@app.post('/geo/geofences')
def create_geo_geofence(
    body: GeofenceZoneCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    row = GeofenceZone(
        district=body.district,
        station_name=body.station_name,
        zone_name=body.zone_name,
        geofence_type=body.geofence_type,
        center_latitude=body.center_latitude,
        center_longitude=body.center_longitude,
        radius_km=body.radius_km,
        points_json=build_geo_polygon(body.center_latitude, body.center_longitude, body.radius_km, sides=7),
        status=body.status,
        notes=body.notes,
        created_by=user.username,
    )
    db.add(row)
    db.flush()
    log_action(db, user.username, 'create_geofence_zone', 'geofence_zone', str(row.id))
    db.commit()
    return {"status": "created", "geofence_id": row.id}


@app.get('/camera/assets')
def camera_assets(
    district: str | None = None,
    station_id: int | None = None,
    status: str | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    q = db.query(CameraAsset)
    if district:
        q = q.filter(CameraAsset.district == district)
    if station_id:
        q = q.filter(CameraAsset.station_id == station_id)
    if status:
        q = q.filter(CameraAsset.status == status)
    rows = q.order_by(CameraAsset.blind_spot_score.desc(), CameraAsset.health_score.asc()).all()
    return [
        {
            "id": row.id,
            "camera_id": row.camera_id,
            "district": row.district,
            "station_id": row.station_id,
            "zone_name": row.zone_name,
            "camera_type": row.camera_type,
            "status": row.status,
            "health_score": row.health_score,
            "blind_spot_score": row.blind_spot_score,
            "retention_profile": row.retention_profile,
            "owner_unit": row.owner_unit,
            "latitude": row.latitude,
            "longitude": row.longitude,
            "last_heartbeat_at": row.last_heartbeat_at.isoformat() if row.last_heartbeat_at else None,
        }
        for row in rows
    ]


@app.get('/camera/blind-zones')
def camera_blind_zones(
    district: str | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    asset_rows = camera_assets(district=district, user=user, db=db)
    geofence_rows = geo_geofences(district=district, user=user, db=db)
    grouped = defaultdict(lambda: {"camera_count": 0, "blind_spot_score": 0.0, "health_pressure": 0.0, "latitude": None, "longitude": None})
    for row in asset_rows:
        key = str(row.get("district") or "Statewide")
        slot = grouped[key]
        slot["camera_count"] += 1
        slot["blind_spot_score"] += float(row.get("blind_spot_score", 0.0))
        slot["health_pressure"] += max(1.0 - float(row.get("health_score", 0.0)), 0.0)
        if slot["latitude"] is None:
            slot["latitude"] = row.get("latitude")
            slot["longitude"] = row.get("longitude")
    geofence_count = defaultdict(int)
    for row in geofence_rows:
        geofence_count[str(row.get("district") or "Statewide")] += 1
    output = []
    for district_name, slot in grouped.items():
        blind_score = round((slot["blind_spot_score"] / max(slot["camera_count"], 1)) + (geofence_count[district_name] * 0.9) + (slot["health_pressure"] * 2.5), 2)
        output.append(
            {
                "district": district_name,
                "camera_count": slot["camera_count"],
                "blind_spot_score": blind_score,
                "geofence_count": geofence_count[district_name],
                "latitude": slot["latitude"],
                "longitude": slot["longitude"],
                "recommended_action": "Rebalance cameras and patrol watch" if blind_score >= 9 else "Maintain current coverage posture",
            }
        )
    return sorted(output, key=lambda row: row["blind_spot_score"], reverse=True)


@app.get('/camera/assignments')
def camera_assignments(
    district: str | None = None,
    incident_id: int | None = None,
    case_id: int | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    q = db.query(CameraIncidentAssignment, CameraAsset).join(CameraAsset, CameraIncidentAssignment.camera_asset_id == CameraAsset.id)
    if district:
        q = q.filter(CameraAsset.district == district)
    if incident_id:
        q = q.filter(CameraIncidentAssignment.incident_id == incident_id)
    if case_id:
        q = q.filter(CameraIncidentAssignment.case_id == case_id)
    rows = q.order_by(CameraIncidentAssignment.id.desc()).all()
    return [
        {
            "id": assignment.id,
            "camera_asset_id": assignment.camera_asset_id,
            "camera_id": asset.camera_id,
            "district": asset.district,
            "incident_id": assignment.incident_id,
            "case_id": assignment.case_id,
            "assignment_type": assignment.assignment_type,
            "status": assignment.status,
            "notes": assignment.notes,
            "assigned_by": assignment.assigned_by,
            "created_at": assignment.created_at.isoformat(),
        }
        for assignment, asset in rows
    ]


@app.post('/camera/assignments')
def create_camera_assignment(
    body: CameraIncidentAssignmentCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    row = CameraIncidentAssignment(
        camera_asset_id=body.camera_asset_id,
        incident_id=body.incident_id,
        case_id=body.case_id,
        assignment_type=body.assignment_type,
        status=body.status,
        notes=body.notes,
        assigned_by=user.username,
    )
    db.add(row)
    db.flush()
    log_action(db, user.username, 'assign_camera_incident', 'camera_assignment', str(row.id))
    db.commit()
    return {"status": "created", "assignment_id": row.id}



@app.get('/adapter-stubs')
def adapter_stubs(user=Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(AdapterStub).order_by(AdapterStub.id.desc()).all()
    return [{"id": r.id, "adapter_name": r.adapter_name, "source_system": r.source_system, "mode": r.mode, "endpoint_hint": r.endpoint_hint, "last_probe_status": r.last_probe_status} for r in rows]

@app.get('/tasks')
def tasks(case_id: int | None = None, district: str | None = None, status: str | None = None, user=Depends(current_user), db: Session = Depends(get_db)):
    q = db.query(TaskQueue)
    if case_id: q = q.filter(TaskQueue.case_id == case_id)
    if district: q = q.filter(TaskQueue.district == district)
    if status: q = q.filter(TaskQueue.status == status)
    rows = q.order_by(TaskQueue.id.desc()).all()
    return [{"id": r.id, "case_id": r.case_id, "district": r.district, "task_type": r.task_type, "priority": r.priority, "assigned_unit": r.assigned_unit, "status": r.status, "details": r.details, "created_by": r.created_by} for r in rows]


@app.post('/tasks')
def create_task(
    body: TaskCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    row = TaskQueue(
        case_id=body.case_id,
        district=body.district,
        task_type=body.task_type,
        priority=body.priority,
        assigned_unit=body.assigned_unit,
        status=body.status,
        details=body.details,
        created_by=user.username,
    )
    db.add(row)
    db.flush()
    db.add(
        TaskExecution(
            task_id=row.id,
            actor=user.username,
            action="created",
            notes=f"Task created with status {row.status}. Assigned unit: {row.assigned_unit or 'unassigned'}.",
        )
    )
    log_action(db, user.username, 'create_task', 'task_queue', str(row.id))
    db.commit()
    return {"status": "created", "task_id": row.id}

@app.get('/tasks/{task_id}/executions')
def task_executions(task_id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(TaskExecution).filter(TaskExecution.task_id == task_id).order_by(TaskExecution.id.desc()).all()
    return [{"id": r.id, "task_id": r.task_id, "actor": r.actor, "action": r.action, "notes": r.notes, "created_at": r.created_at.isoformat()} for r in rows]


@app.post('/tasks/{task_id}/actions')
def task_action(
    task_id: int,
    body: TaskActionCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    row = db.query(TaskQueue).filter(TaskQueue.id == task_id).first()
    if not row:
        raise HTTPException(status_code=404, detail='Task not found')
    if body.assigned_unit:
        row.assigned_unit = body.assigned_unit
    if body.status:
        row.status = body.status
    db.add(
        TaskExecution(
            task_id=row.id,
            actor=user.username,
            action=body.action,
            notes=body.notes or f"Task action {body.action} recorded.",
        )
    )
    log_action(db, user.username, 'task_action', 'task_queue', str(row.id))
    db.commit()
    return {"status": "ok", "task_id": row.id, "task_status": row.status}

@app.get('/suspect-dossiers')
def suspect_dossiers(district: str | None = None, user=Depends(current_user), db: Session = Depends(get_db)):
    q = db.query(SuspectDossier).join(Entity, SuspectDossier.entity_id == Entity.id)
    if district: q = q.filter(SuspectDossier.district == district)
    rows = q.order_by(SuspectDossier.threat_level.desc(), SuspectDossier.id.desc()).all()
    return [{"id": r.id, "entity_id": r.entity_id, "district": r.district, "threat_level": r.threat_level, "category": r.category, "known_associates": r.known_associates, "known_devices": r.known_devices, "linked_cases": r.linked_cases, "open_alerts": r.open_alerts, "narrative": r.narrative} for r in rows]

@app.get('/graph/insights')
def graph_insights(case_id: int | None = None, district: str | None = None, user=Depends(current_user), db: Session = Depends(get_db)):
    q = db.query(GraphInsight)
    if case_id: q = q.filter(GraphInsight.case_id == case_id)
    if district: q = q.filter(GraphInsight.district == district)
    rows = q.order_by(GraphInsight.score.desc()).all()
    return [{
        "id": r.id,
        "case_id": r.case_id,
        "entity_id": getattr(r, "entity_id", None),
        "district": r.district,
        "insight_type": r.insight_type,
        "score": r.score,
        "headline": r.headline,
        "explanation": r.explanation
    } for r in rows]



@app.get('/court-packet-exports')
def court_packet_exports(case_id: int | None = None, user=Depends(current_user), db: Session = Depends(get_db)):
    q = db.query(CourtPacketExport)
    if case_id: q = q.filter(CourtPacketExport.case_id == case_id)
    rows = q.order_by(CourtPacketExport.id.desc()).all()
    return [{
        "id": r.id,
        "case_id": r.case_id,
        "export_type": r.export_type,
        "export_ref": r.export_ref,
        "generated_by": r.generated_by,
        "generated_at": r.created_at.isoformat(),
    } for r in rows]

@app.get('/evidence-integrity')
def evidence_integrity(case_id: int | None = None, user=Depends(current_user), db: Session = Depends(get_db)):
    q = db.query(EvidenceIntegrityLog).join(EvidenceAttachment, EvidenceIntegrityLog.evidence_id == EvidenceAttachment.id)
    if case_id: q = q.filter(EvidenceAttachment.case_id == case_id)
    rows = q.order_by(EvidenceIntegrityLog.id.desc()).all()
    return [{"id": r.id, "evidence_id": r.evidence_id, "integrity_state": r.integrity_state, "checksum_stub": r.checksum_stub, "verified_by": r.verified_by, "notes": r.notes} for r in rows]

@app.get('/narrative-briefs')
def narrative_briefs(case_id: int | None = None, user=Depends(current_user), db: Session = Depends(get_db)):
    q = db.query(NarrativeBrief)
    if case_id: q = q.filter(NarrativeBrief.case_id == case_id)
    rows = q.order_by(NarrativeBrief.id.desc()).all()
    return [{"id": r.id, "case_id": r.case_id, "brief_type": r.brief_type, "title": r.title, "body": r.body, "created_by": r.created_by} for r in rows]



@app.get('/hotspot-forecasts')
def hotspot_forecasts(district: str | None = None, user=Depends(current_user), db: Session = Depends(get_db)):
    q = db.query(HotspotForecast)
    if district: q = q.filter(HotspotForecast.district == district)
    rows = q.order_by(HotspotForecast.forecast_score.desc()).all()
    return [{"id": r.id, "district": r.district, "zone_name": r.zone_name, "risk_category": r.risk_category, "forecast_score": r.forecast_score, "horizon_days": r.horizon_days, "recommended_action": r.recommended_action} for r in rows]

@app.get('/patrol-coverage')
def patrol_coverage(district: str | None = None, user=Depends(current_user), db: Session = Depends(get_db)):
    q = db.query(PatrolCoverageMetric)
    if district: q = q.filter(PatrolCoverageMetric.district == district)
    rows = q.order_by(PatrolCoverageMetric.coverage_ratio.asc()).all()
    return [{"id": r.id, "district": r.district, "station_id": r.station_id, "beat_name": r.beat_name, "coverage_ratio": r.coverage_ratio, "backlog": r.backlog, "open_incidents": r.open_incidents} for r in rows]

@app.get('/similarity-hits')
def similarity_hits(source_type: str | None = None, user=Depends(current_user), db: Session = Depends(get_db)):
    q = db.query(SimilarityHit)
    if source_type: q = q.filter(SimilarityHit.source_type == source_type)
    rows = q.order_by(SimilarityHit.similarity_score.desc()).all()
    return [{"id": r.id, "source_type": r.source_type, "source_id": r.source_id, "target_type": r.target_type, "target_id": r.target_id, "similarity_score": r.similarity_score, "rationale": r.rationale} for r in rows]


@app.get('/search/unified')
def unified_search(
    q: str = Query(..., min_length=1),
    district: str | None = None,
    case_id: int | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    q_like = f"%{q}%"
    complaints_q = db.query(Complaint).filter(or_(Complaint.description.ilike(q_like), Complaint.complaint_type.ilike(q_like), Complaint.complainant_ref.ilike(q_like)))
    cases_q = db.query(Case).filter(or_(Case.title.ilike(q_like), Case.summary.ilike(q_like), Case.created_by.ilike(q_like)))
    entities_q = db.query(Entity).filter(or_(Entity.display_name.ilike(q_like), Entity.entity_type.ilike(q_like)))
    watchlists_q = db.query(Watchlist).filter(or_(Watchlist.name.ilike(q_like), Watchlist.rationale.ilike(q_like)))
    tasks_q = db.query(TaskQueue).filter(or_(TaskQueue.task_type.ilike(q_like), TaskQueue.details.ilike(q_like), TaskQueue.assigned_unit.ilike(q_like)))
    messages_q = db.query(DepartmentMessage).filter(or_(DepartmentMessage.message_text.ilike(q_like), DepartmentMessage.room_name.ilike(q_like)))
    checkpoints_q = db.query(CheckpointPlan).filter(or_(CheckpointPlan.checkpoint_name.ilike(q_like), CheckpointPlan.notes.ilike(q_like)))
    geofences_q = db.query(GeofenceZone).filter(or_(GeofenceZone.zone_name.ilike(q_like), GeofenceZone.notes.ilike(q_like)))
    cameras_q = db.query(CameraAsset).filter(or_(CameraAsset.camera_id.ilike(q_like), CameraAsset.zone_name.ilike(q_like), CameraAsset.owner_unit.ilike(q_like)))
    connector_artifacts_q = db.query(ConnectorArtifact).filter(or_(ConnectorArtifact.connector_name.ilike(q_like), ConnectorArtifact.external_ref.ilike(q_like), ConnectorArtifact.ingest_summary.ilike(q_like)))
    provenance_q = db.query(ProvenanceRecord).filter(or_(ProvenanceRecord.source_name.ilike(q_like), ProvenanceRecord.source_ref.ilike(q_like), ProvenanceRecord.notes.ilike(q_like), ProvenanceRecord.operation.ilike(q_like)))
    corridors_q = db.query(OperationalCorridor).filter(or_(OperationalCorridor.corridor_name.ilike(q_like), OperationalCorridor.corridor_type.ilike(q_like), OperationalCorridor.notes.ilike(q_like)))
    playbooks_q = db.query(WorkflowPlaybook).filter(or_(WorkflowPlaybook.playbook_name.ilike(q_like), WorkflowPlaybook.trigger_type.ilike(q_like), WorkflowPlaybook.assigned_unit_hint.ilike(q_like)))
    video_sessions_q = db.query(VideoSession).filter(or_(VideoSession.room_name.ilike(q_like), VideoSession.session_code.ilike(q_like), VideoSession.notes.ilike(q_like)))

    if district:
        complaints_q = complaints_q.filter(Complaint.district == district)
        cases_q = cases_q.filter(Case.district == district)
        entities_q = entities_q.filter(Entity.district == district)
        watchlists_q = watchlists_q.filter(or_(Watchlist.district == district, Watchlist.district == None))
        tasks_q = tasks_q.filter(TaskQueue.district == district)
        messages_q = messages_q.filter(or_(DepartmentMessage.district == district, DepartmentMessage.district == None))
        checkpoints_q = checkpoints_q.filter(CheckpointPlan.district == district)
        geofences_q = geofences_q.filter(GeofenceZone.district == district)
        cameras_q = cameras_q.filter(CameraAsset.district == district)
        connector_artifacts_q = connector_artifacts_q.filter(ConnectorArtifact.district == district)
        provenance_q = provenance_q.filter(ProvenanceRecord.district == district)
        corridors_q = corridors_q.filter(OperationalCorridor.district == district)
        playbooks_q = playbooks_q.filter(WorkflowPlaybook.district == district)
        video_sessions_q = video_sessions_q.filter(or_(VideoSession.district == district, VideoSession.district == None))
    if case_id:
        cases_q = cases_q.filter(Case.id == case_id)
        tasks_q = tasks_q.filter(or_(TaskQueue.case_id == case_id, TaskQueue.case_id == None))
        messages_q = messages_q.filter(or_(DepartmentMessage.case_id == case_id, DepartmentMessage.case_id == None))
        checkpoints_q = checkpoints_q.filter(or_(CheckpointPlan.case_id == case_id, CheckpointPlan.case_id == None))
        connector_artifacts_q = connector_artifacts_q.filter(or_(ConnectorArtifact.case_id == case_id, ConnectorArtifact.case_id == None))
        video_sessions_q = video_sessions_q.filter(or_(VideoSession.case_id == case_id, VideoSession.case_id == None))

    similarity_rows = similarity_hits(user=user, db=db)
    similarity_lookup = defaultdict(float)
    for row in similarity_rows:
        similarity_lookup[f"{row['source_type']}:{row['source_id']}"] = max(similarity_lookup[f"{row['source_type']}:{row['source_id']}"], float(row.get("similarity_score", 0.0)))
        similarity_lookup[f"{row['target_type']}:{row['target_id']}"] = max(similarity_lookup[f"{row['target_type']}:{row['target_id']}"], float(row.get("similarity_score", 0.0)))

    entity_lookup = {row.id: row for row in db.query(Entity).all()}
    fact_rows = []
    for row in db.query(EntityAttributeFact).order_by(EntityAttributeFact.confidence.desc()).all():
        entity = entity_lookup.get(row.entity_id)
        searchable = " ".join(
            [
                row.attribute_name or "",
                row.attribute_value or "",
                row.source_name or "",
                row.source_ref or "",
                "" if entity is None else entity.display_name,
            ]
        ).lower()
        if q.lower() not in searchable:
            continue
        if district and entity and entity.district != district:
            continue
        fact_rows.append((row, entity))

    resolution_rows = []
    for row in db.query(EntityResolutionCandidate).order_by(EntityResolutionCandidate.match_score.desc()).all():
        left_entity = entity_lookup.get(row.left_entity_id)
        right_entity = entity_lookup.get(row.right_entity_id)
        searchable = " ".join(
            [
                row.rationale or "",
                row.cluster_ref or "",
                "" if left_entity is None else left_entity.display_name,
                "" if right_entity is None else right_entity.display_name,
            ]
        ).lower()
        if q.lower() not in searchable:
            continue
        if district and district not in {getattr(left_entity, "district", None), getattr(right_entity, "district", None)}:
            continue
        resolution_rows.append((row, left_entity, right_entity))

    def scored_record(record_type: str, record_id: int | None, district_value: str | None, label: str, base_score: float, payload: dict):
        similarity_bonus = similarity_lookup.get(f"{record_type}:{record_id}", 0.0)
        district_bonus = 0.12 if district and district_value == district else 0.0
        fusion_score = round(base_score + similarity_bonus + district_bonus, 3)
        return {
            "record_type": record_type,
            "record_id": record_id,
            "district": district_value,
            "label": label,
            "fusion_score": fusion_score,
            "payload": payload,
        }

    top_hits = []
    for row in complaints_q.limit(12).all():
        top_hits.append(scored_record("complaint", row.id, row.district, f"Complaint {row.id}", 0.42, {"complaint_type": row.complaint_type, "status": row.status, "description": row.description}))
    for row in cases_q.limit(12).all():
        base_score = 0.55 + (0.15 if row.priority in {"high", "critical"} else 0.0)
        top_hits.append(scored_record("case", row.id, row.district, row.title, base_score, {"priority": row.priority, "status": row.status, "summary": row.summary}))
    for row in entities_q.limit(12).all():
        top_hits.append(scored_record("entity", row.id, row.district, row.display_name, 0.48 + (float(row.risk_score or 0.0) * 0.4), {"entity_type": row.entity_type, "risk_score": row.risk_score}))
    for row in watchlists_q.limit(10).all():
        top_hits.append(scored_record("watchlist", row.id, row.district, row.name, 0.58 if row.status == "active" else 0.36, {"watch_type": row.watch_type, "status": row.status, "rationale": row.rationale}))
    for row in tasks_q.limit(10).all():
        top_hits.append(scored_record("task", row.id, row.district, row.task_type, 0.44 + (0.16 if row.status in {"approved", "in_progress"} else 0.0), {"priority": row.priority, "status": row.status, "assigned_unit": row.assigned_unit}))
    for row in messages_q.limit(10).all():
        top_hits.append(scored_record("message", row.id, row.district, row.room_name, 0.34 + (0.2 if any(name == user.username for name in parse_message_mentions_text(row.message_text)) else 0.0), {"priority": row.priority, "room_name": row.room_name, "message_text": row.message_text}))
    for row in checkpoints_q.limit(10).all():
        top_hits.append(scored_record("checkpoint", row.id, row.district, row.checkpoint_name, 0.46 + (0.14 if row.status in {"active", "deployed"} else 0.0), {"checkpoint_type": row.checkpoint_type, "status": row.status, "assigned_unit": row.assigned_unit}))
    for row in geofences_q.limit(10).all():
        top_hits.append(scored_record("geofence", row.id, row.district, row.zone_name, 0.39 + (0.18 if row.status == "active" else 0.0), {"geofence_type": row.geofence_type, "status": row.status, "notes": row.notes}))
    for row in cameras_q.limit(12).all():
        top_hits.append(scored_record("camera", row.id, row.district, row.camera_id, 0.38 + float(row.blind_spot_score or 0.0) / 25.0, {"camera_type": row.camera_type, "status": row.status, "zone_name": row.zone_name}))
    for row in connector_artifacts_q.limit(12).all():
        top_hits.append(scored_record("connector_artifact", row.id, row.district, f"{row.connector_name} | {row.external_ref}", 0.47, {"record_type": row.record_type, "status": row.status, "summary": row.ingest_summary}))
    for row in provenance_q.limit(12).all():
        top_hits.append(scored_record("provenance", row.id, row.district, f"{row.source_name} | {row.object_type}:{row.object_id}", 0.43 + float(row.confidence or 0.0) * 0.2, {"operation": row.operation, "source_ref": row.source_ref, "notes": row.notes}))
    for row in corridors_q.limit(10).all():
        top_hits.append(scored_record("corridor", row.id, row.district, row.corridor_name, 0.5 + float(row.risk_score or 0.0) * 0.2, {"corridor_type": row.corridor_type, "priority": row.surveillance_priority, "route_ref": row.route_ref}))
    for row in playbooks_q.limit(10).all():
        top_hits.append(scored_record("playbook", row.id, row.district, row.playbook_name, 0.54, {"trigger_type": row.trigger_type, "priority": row.default_priority, "assigned_unit_hint": row.assigned_unit_hint}))
    for row in video_sessions_q.limit(10).all():
        top_hits.append(scored_record("video_session", row.id, row.district, row.room_name, 0.41, {"session_code": row.session_code, "status": row.status, "session_mode": row.session_mode}))
    for row, entity in fact_rows[:12]:
        top_hits.append(scored_record("attribute_fact", row.id, None if entity is None else entity.district, f"{row.attribute_name}: {row.attribute_value}", 0.45 + float(row.confidence or 0.0) * 0.25, {"entity_name": None if entity is None else entity.display_name, "source_name": row.source_name, "source_ref": row.source_ref}))
    for row, left_entity, right_entity in resolution_rows[:10]:
        top_hits.append(scored_record("resolution_candidate", row.id, getattr(left_entity, "district", None), f"{getattr(left_entity, 'display_name', 'Left')} ↔ {getattr(right_entity, 'display_name', 'Right')}", 0.56 + float(row.match_score or 0.0) * 0.2, {"status": row.status, "cluster_ref": row.cluster_ref, "rationale": row.rationale}))

    top_hits = sorted(top_hits, key=lambda row: row["fusion_score"], reverse=True)[:25]
    return {
        "query": q,
        "district": district,
        "case_id": case_id,
        "top_hits": top_hits,
        "counts": {
            "complaints": complaints_q.count(),
            "cases": cases_q.count(),
            "entities": entities_q.count(),
            "watchlists": watchlists_q.count(),
            "tasks": tasks_q.count(),
            "messages": messages_q.count(),
            "checkpoints": checkpoints_q.count(),
            "geofences": geofences_q.count(),
            "cameras": cameras_q.count(),
            "attribute_facts": len(fact_rows),
            "resolution_candidates": len(resolution_rows),
            "connector_artifacts": connector_artifacts_q.count(),
            "provenance_records": provenance_q.count(),
            "corridors": corridors_q.count(),
            "playbooks": playbooks_q.count(),
            "video_sessions": video_sessions_q.count(),
        },
    }



@app.get('/timeline-digests')
def timeline_digests(case_id: int | None = None, user=Depends(current_user), db: Session = Depends(get_db)):
    q = db.query(TimelineDigest)
    if case_id: q = q.filter(TimelineDigest.case_id == case_id)
    rows = q.order_by(TimelineDigest.id.desc()).all()
    return [{"id": r.id, "case_id": r.case_id, "digest_title": r.digest_title, "digest_body": r.digest_body, "generated_by": r.generated_by} for r in rows]

@app.get('/export-jobs')
def export_jobs(user=Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(ExportJob).order_by(ExportJob.id.desc()).all()
    return [{"id": r.id, "export_scope": r.export_scope, "object_id": r.object_id, "format": r.format, "status": r.status, "export_ref": r.export_ref, "created_by": r.created_by} for r in rows]

@app.get('/war-room-snapshots')
def war_room_snapshots(district: str | None = None, user=Depends(current_user), db: Session = Depends(get_db)):
    q = db.query(WarRoomSnapshot)
    if district: q = q.filter(WarRoomSnapshot.district == district)
    rows = q.order_by(WarRoomSnapshot.id.desc()).all()
    return [{"id": r.id, "district": r.district, "snapshot_label": r.snapshot_label, "active_cases": r.active_cases, "active_alerts": r.active_alerts, "pending_tasks": r.pending_tasks, "forecast_hotspots": r.forecast_hotspots, "command_summary": r.command_summary} for r in rows]

@app.get('/bookmarks')
def bookmarks(user=Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(ExplorationBookmark).filter(ExplorationBookmark.username == user.username).order_by(ExplorationBookmark.id.desc()).all()
    return [{"id": r.id, "username": r.username, "bookmark_type": r.bookmark_type, "object_ref": r.object_ref, "title": r.title, "notes": r.notes} for r in rows]

@app.post('/bookmarks')
def create_bookmark(payload: dict, user=Depends(current_user), db: Session = Depends(get_db)):
    row = ExplorationBookmark(
        username=user.username,
        bookmark_type=payload.get('bookmark_type', 'generic'),
        object_ref=payload.get('object_ref', ''),
        title=payload.get('title', 'Untitled bookmark'),
        notes=payload.get('notes')
    )
    db.add(row)
    db.commit()
    return {"status": "created", "bookmark_id": row.id}



@app.get('/districts/station-dashboard')
def station_dashboard(district: str | None = None, user=Depends(current_user), db: Session = Depends(get_db)):
    import csv
    from pathlib import Path
    p = Path(__file__).resolve().parents[1] / 'data' / 'station_kpis_seed.csv'
    rows = []
    if p.exists():
        with open(p, newline='', encoding='utf-8') as f:
            for r in csv.DictReader(f):
                if district and r['district'] != district:
                    continue
                rows.append(r)
    return rows

@app.get('/districts/performance-summary')
def district_performance_summary(user=Depends(current_user), db: Session = Depends(get_db)):
    import csv
    from pathlib import Path
    from collections import defaultdict
    p = Path(__file__).resolve().parents[1] / 'data' / 'station_kpis_seed.csv'
    agg = defaultdict(lambda: {'stations':0,'open_cases':0,'breached_sla_cases':0,'active_alerts':0,'complaints_7d':0})
    if p.exists():
        with open(p, newline='', encoding='utf-8') as f:
            for r in csv.DictReader(f):
                a = agg[r['district']]
                a['stations'] += 1
                for k in ['open_cases','breached_sla_cases','active_alerts','complaints_7d']:
                    a[k] += int(float(r[k]))
    return [{'district':k, **v} for k,v in agg.items()]

@app.get('/fusion/clusters')
def fusion_clusters(district: str | None = None, case_id: int | None = None, user=Depends(current_user), db: Session = Depends(get_db)):
    import csv
    from pathlib import Path
    p = Path(__file__).resolve().parents[1] / 'data' / 'entity_fusion_seed.csv'
    rows = []
    if p.exists():
        with open(p, newline='', encoding='utf-8') as f:
            for r in csv.DictReader(f):
                if district and r['district'] != district:
                    continue
                if case_id and int(r['case_id']) != case_id:
                    continue
                rows.append(r)
    return rows

@app.get('/fusion/cluster-summary')
def fusion_cluster_summary(user=Depends(current_user), db: Session = Depends(get_db)):
    import csv
    from pathlib import Path
    from collections import defaultdict
    p = Path(__file__).resolve().parents[1] / 'data' / 'entity_fusion_seed.csv'
    agg = defaultdict(lambda: {'members':0,'avg_signal_strength':0.0,'districts':set(),'cases':set()})
    if p.exists():
        with open(p, newline='', encoding='utf-8') as f:
            for r in csv.DictReader(f):
                a = agg[r['cluster_id']]
                a['members'] += 1
                a['avg_signal_strength'] += float(r['signal_strength'])
                a['districts'].add(r['district'])
                a['cases'].add(r['case_id'])
    out = []
    for cid,a in agg.items():
        out.append({'cluster_id':cid,'members':a['members'],'avg_signal_strength':round(a['avg_signal_strength']/a['members'],3),'districts':sorted(a['districts']),'case_count':len(a['cases'])})
    return out

@app.get('/permissions/matrix')
def permissions_matrix(user=Depends(current_user), db: Session = Depends(get_db)):
    import csv
    from pathlib import Path
    p = Path(__file__).resolve().parents[1] / 'data' / 'permissions_matrix_seed.csv'
    rows = []
    if p.exists():
        with open(p, newline='', encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
    return rows

@app.get('/permissions/effective/{role_name_param}')
def effective_permissions(role_name_param: str, user=Depends(current_user), db: Session = Depends(get_db)):
    import csv
    from pathlib import Path
    p = Path(__file__).resolve().parents[1] / 'data' / 'permissions_matrix_seed.csv'
    if p.exists():
        with open(p, newline='', encoding='utf-8') as f:
            for r in csv.DictReader(f):
                if r['role_name'] == role_name_param:
                    return r
    raise HTTPException(status_code=404, detail='Role not found')

@app.get('/officers/workload')
def officer_workload(district: str | None = None, user=Depends(current_user), db: Session = Depends(get_db)):
    import csv
    from pathlib import Path
    p = Path(__file__).resolve().parents[1] / 'data' / 'officer_workload_seed.csv'
    rows = []
    if p.exists():
        with open(p, newline='', encoding='utf-8') as f:
            for r in csv.DictReader(f):
                if district and r['district'] != district:
                    continue
                rows.append(r)
    return rows

@app.get('/officers/workload-summary')
def officer_workload_summary(user=Depends(current_user), db: Session = Depends(get_db)):
    import csv
    from pathlib import Path
    p = Path(__file__).resolve().parents[1] / 'data' / 'officer_workload_seed.csv'
    rows = []
    if p.exists():
        with open(p, newline='', encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
    if not rows:
        return {'officer_count': 0}
    avg_capacity = sum(float(r['capacity_index']) for r in rows)/len(rows)
    overloaded = sum(1 for r in rows if float(r['capacity_index']) >= 0.85)
    return {'officer_count': len(rows), 'avg_capacity_index': round(avg_capacity, 3), 'overloaded_officers': overloaded}

@app.get('/briefings')
def briefings(district: str | None = None, user=Depends(current_user), db: Session = Depends(get_db)):
    import csv
    from pathlib import Path
    p = Path(__file__).resolve().parents[1] / 'data' / 'briefing_registry_seed.csv'
    rows = []
    if p.exists():
        with open(p, newline='', encoding='utf-8') as f:
            for r in csv.DictReader(f):
                if district and r['district'] not in (district, 'Statewide'):
                    continue
                rows.append(r)
    return rows

@app.get('/briefings/daily-summary')
def briefing_daily_summary(user=Depends(current_user), db: Session = Depends(get_db)):
    return {
        'generated_at': datetime.utcnow().isoformat(),
        'headline': 'Operational pressure remains highest in Chennai, with cyber-fraud, complaint velocity, and SLA breaches driving command attention.',
        'sections': [
            'District pressure is uneven, with a small number of station clusters contributing a disproportionate share of open alerts.',
            'Fusion candidates indicate cross-case overlap in phones, devices, vehicles, and beneficiary entities.',
            'Officer workload shows two stressed stations that require temporary balancing or queue redistribution.'
        ]
    }

@app.get('/operations/command-center')
def operations_command_center(
    district: str | None = None,
    user=Depends(current_user),
    db: Session = Depends(get_db)
):
    current_role = role_name(db, user)
    effective_district = district
    if current_role == 'district_sp' and user.district:
        if district and district != user.district:
            raise HTTPException(status_code=403, detail='District scope exceeded')
        effective_district = user.district

    district_rows = district_performance_summary(user=user, db=db)
    if effective_district:
        district_rows = [row for row in district_rows if row.get("district") == effective_district]

    briefing_summary = briefing_daily_summary(user=user, db=db)
    war_room_rows = war_room_snapshots(district=effective_district, user=user, db=db)
    hotspot_rows = hotspot_forecasts(district=effective_district, user=user, db=db)
    patrol_rows = patrol_coverage(district=effective_district, user=user, db=db)
    task_rows = tasks(district=effective_district, user=user, db=db)
    workload_rows = officer_workload(district=effective_district, user=user, db=db)
    workload_summary = officer_workload_summary(user=user, db=db)
    suspect_rows = suspect_dossiers(district=effective_district, user=user, db=db)
    fusion_rows = fusion_clusters(district=effective_district, user=user, db=db)
    fusion_summary_rows = fusion_cluster_summary(user=user, db=db)
    graph_rows = graph_insights(district=effective_district, user=user, db=db)
    briefing_rows = briefings(district=effective_district, user=user, db=db)
    command_rows = command_board(user=user, db=db)
    notification_rows = notifications(db=db, user=user)

    if effective_district:
        fusion_summary_rows = [
            row for row in fusion_summary_rows
            if effective_district in row.get("districts", [])
        ]
        command_rows = [row for row in command_rows if row.get("district") == effective_district]

    threat_rank = {"high": 3, "medium": 2, "low": 1}
    top_pressure = sorted(
        district_rows,
        key=lambda row: (
            int(row.get("breached_sla_cases", 0)),
            int(row.get("active_alerts", 0)),
            int(row.get("open_cases", 0)),
        ),
        reverse=True,
    )[:5]
    hotspot_rows = sorted(hotspot_rows, key=lambda row: float(row.get("forecast_score", 0)), reverse=True)[:5]
    patrol_rows = sorted(
        patrol_rows,
        key=lambda row: (
            float(row.get("coverage_ratio", 1.0)),
            -int(row.get("backlog", 0)),
            -int(row.get("open_incidents", 0)),
        ),
    )[:5]
    suspect_rows = sorted(
        suspect_rows,
        key=lambda row: (
            threat_rank.get(str(row.get("threat_level", "")).lower(), 0),
            int(row.get("open_alerts", 0)),
            int(row.get("linked_cases", 0)),
        ),
        reverse=True,
    )[:5]
    graph_rows = sorted(graph_rows, key=lambda row: float(row.get("score", 0)), reverse=True)[:5]

    queued_notifications = [row for row in notification_rows if row.get("status") == "queued"][:5]
    queue_rows = [row for row in task_rows if row.get("status") in {"queued", "in_progress"}]
    overview = {
        "district_scope": effective_district or "statewide",
        "active_cases": sum(int(row.get("open_cases", 0)) for row in district_rows),
        "active_alerts": sum(int(row.get("active_alerts", 0)) for row in district_rows),
        "breached_sla_cases": sum(int(row.get("breached_sla_cases", 0)) for row in district_rows),
        "complaints_7d": sum(int(row.get("complaints_7d", 0)) for row in district_rows),
        "queued_tasks": sum(1 for row in task_rows if row.get("status") == "queued"),
        "in_progress_tasks": sum(1 for row in task_rows if row.get("status") == "in_progress"),
        "queued_notifications": len(queued_notifications),
        "overloaded_officers": int(workload_summary.get("overloaded_officers", 0)),
        "fusion_clusters": len(fusion_rows),
    }

    return {
        "overview": overview,
        "daily_briefing": briefing_summary,
        "district_pressure": top_pressure,
        "war_room_snapshots": war_room_rows[:5],
        "hotspot_forecasts": hotspot_rows,
        "patrol_gaps": patrol_rows,
        "task_queue": queue_rows[:6],
        "notification_queue": queued_notifications,
        "workload_summary": workload_summary,
        "officer_workload": workload_rows[:8],
        "suspect_focus": suspect_rows,
        "fusion_cluster_summary": fusion_summary_rows[:5],
        "graph_insights": graph_rows,
        "recent_briefings": briefing_rows[:5],
        "command_board": command_rows[:5],
    }

@app.get('/cases/{case_id}/dossier')
def case_dossier(case_id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail='Case not found')

    current_role = role_name(db, user)
    if current_role == 'district_sp' and user.district and case.district != user.district:
        raise HTTPException(status_code=403, detail='District scope exceeded')

    update_sla_status(case)
    db.commit()

    complaint_link_rows = db.query(ComplaintCaseLink).filter(ComplaintCaseLink.case_id == case_id).all()
    complaint_ids = [row.complaint_id for row in complaint_link_rows]
    complaint_lookup = {}
    if complaint_ids:
        complaint_lookup = {
            row.id: row
            for row in db.query(Complaint).filter(Complaint.id.in_(complaint_ids)).all()
        }
    linked_complaints = [{
        "complaint_id": row.complaint_id,
        "linked_by": row.linked_by,
        "rationale": row.rationale,
        "complaint": None if complaint_lookup.get(row.complaint_id) is None else {
            "id": complaint_lookup[row.complaint_id].id,
            "district": complaint_lookup[row.complaint_id].district,
            "complaint_type": complaint_lookup[row.complaint_id].complaint_type,
            "status": complaint_lookup[row.complaint_id].status,
            "complainant_ref": complaint_lookup[row.complaint_id].complainant_ref,
            "description": complaint_lookup[row.complaint_id].description,
        }
    } for row in complaint_link_rows]

    comment_rows = list_case_comments(case_id=case_id, user=user, db=db)
    assignment_rows = list_case_assignments(case_id=case_id, user=user, db=db)
    timeline_rows = case_timeline(case_id=case_id, user=user, db=db)
    evidence_rows = case_evidence(case_id=case_id, user=user, db=db)
    graph_payload = case_graph(case_id=case_id, db=db, user=user)
    watchlist_rows = list_watchlist_hits(case_id=case_id, user=user, db=db)
    task_rows = tasks(case_id=case_id, user=user, db=db)
    prosecution_rows = [row for row in prosecution_packets(user=user, db=db) if row.get("case_id") == case_id]
    custody_rows = [row for row in custody_logs(user=user, db=db) if row.get("case_id") == case_id]
    medical_rows = [row for row in medical_checks(user=user, db=db) if row.get("case_id") == case_id]
    hearing_rows = court_hearings(case_id=case_id, db=db, user=user)
    prison_rows = prison_movements(case_id=case_id, db=db, user=user)
    document_rows = documents(case_id=case_id, db=db, user=user)
    document_entities_map = {
        str(row["id"]): document_entities(document_id=row["id"], db=db, user=user)
        for row in document_rows
    }
    narrative_rows = narrative_briefs(case_id=case_id, user=user, db=db)
    digest_rows = timeline_digests(case_id=case_id, user=user, db=db)
    integrity_rows = evidence_integrity(case_id=case_id, user=user, db=db)
    court_export_rows = court_packet_exports(case_id=case_id, user=user, db=db)
    export_rows = [
        row for row in export_jobs(user=user, db=db)
        if str(row.get("object_id") or "") in {str(case_id), f"case:{case_id}"}
    ]
    bookmark_rows = [
        row for row in bookmarks(user=user, db=db)
        if row.get("object_ref") == f"case:{case_id}"
    ]

    graph_snapshot = graph_payload.get("snapshot") or {}
    summary = {
        "status": case.status,
        "priority": case.priority,
        "sla_status": case.sla_status,
        "timeline_events": len(timeline_rows),
        "evidence_items": len(evidence_rows),
        "linked_complaints": len(linked_complaints),
        "watchlist_hits": len(watchlist_rows),
        "tasks": len(task_rows),
        "hearings": len(hearing_rows),
        "documents": len(document_rows),
        "graph_nodes": len(graph_payload.get("nodes", [])),
        "graph_edges": len(graph_payload.get("edges", [])),
        "risk_density": graph_snapshot.get("risk_density"),
    }

    return {
        "case": {
            "id": case.id,
            "title": case.title,
            "district": case.district,
            "station_id": case.station_id,
            "priority": case.priority,
            "status": case.status,
            "summary": case.summary,
            "created_by": case.created_by,
            "created_at": case.created_at.isoformat(),
            "response_due_at": case.response_due_at.isoformat() if case.response_due_at else None,
            "resolution_due_at": case.resolution_due_at.isoformat() if case.resolution_due_at else None,
            "sla_status": case.sla_status,
        },
        "summary": summary,
        "linked_complaints": linked_complaints,
        "comments": comment_rows,
        "assignments": assignment_rows,
        "timeline": timeline_rows,
        "timeline_digests": digest_rows,
        "evidence": evidence_rows,
        "evidence_integrity": integrity_rows,
        "graph": graph_payload,
        "watchlist_hits": watchlist_rows,
        "tasks": task_rows,
        "narrative_briefs": narrative_rows,
        "prosecution_packets": prosecution_rows,
        "court_hearings": hearing_rows,
        "custody_logs": custody_rows,
        "medical_checks": medical_rows,
        "prison_movements": prison_rows,
        "documents": document_rows,
        "document_entities": document_entities_map,
        "court_packet_exports": court_export_rows,
        "export_jobs": export_rows,
        "bookmarks": bookmark_rows,
    }
