
from collections import defaultdict
from datetime import datetime
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import or_
from sqlalchemy.orm import Session
from jose import jwt, JWTError

from app.config import JWT_SECRET, JWT_ALGORITHM
from app.schemas import (
    LoginRequest, ComplaintCreate, CaseCreate, CaseCommentCreate,
    CaseAssignCreate, ComplaintCaseLinkCreate, WatchlistCreate, EvidenceCreate,
    DepartmentMessageCreate, DepartmentMessageReadCreate, PresenceHeartbeatCreate, CheckpointPlanCreate
)
from db.database import get_db
from db.models import (
    User, Role, PublicMetric, Complaint, Alert, Entity, EntityLink, Station, AuditLog, Case,
    CaseComment, CaseAssignment, Incident, IngestQueue, ComplaintCaseLink, ConnectorRegistry,
    Watchlist, WatchlistHit, EvidenceAttachment, CaseTimelineEvent, StationRoutingRule,
    ProsecutionPacket, CustodyLog, MedicalCheckLog, EventCommandBoard,
    DocumentIntake, ExtractedEntity, CourtHearing, PrisonMovement, NotificationEvent, DepartmentMessage, DepartmentMessageRead, PersonnelPresence, CheckpointPlan, GraphSnapshot, GeoFenceAlert, AdapterStub, TaskQueue, TaskExecution, SuspectDossier, GraphInsight, CourtPacketExport, EvidenceIntegrityLog, NarrativeBrief, HotspotForecast, PatrolCoverageMetric, SimilarityHit, TimelineDigest, ExportJob, WarRoomSnapshot, ExplorationBookmark
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

def role_name(db: Session, user: User) -> str:
    role = db.query(Role).filter(Role.id == user.role_id).first()
    return role.name if role else "viewer"

def log_action(db: Session, username: str, action: str, object_type: str, object_id: str):
    db.add(AuditLog(username=username, action=action, object_type=object_type, object_id=object_id))

def add_timeline(db: Session, case_id: int, event_type: str, actor: str, details: str):
    db.add(CaseTimelineEvent(case_id=case_id, event_type=event_type, actor=actor, details=details))

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

def serialize_department_message(row: DepartmentMessage, current_username: str, read_lookup: dict[str, int]) -> dict:
    last_read_id = read_lookup.get(row.room_name, 0)
    is_unread = row.sender_username != current_username and row.id > last_read_id
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
    return [
        serialize_department_message(row, user.username, read_lookup)
        for row in rows[: min(limit, 200)]
    ]

@app.post('/internal-comms/messages')
def create_internal_comms_message(
    body: DepartmentMessageCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
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
    log_action(db, user.username, 'create_department_message', 'department_message', str(row.id))
    db.commit()
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

@app.get('/geo/geofence-alerts')
def geofence_alerts(district: str | None = None, active: bool | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    q = db.query(GeoFenceAlert)
    if district: q = q.filter(GeoFenceAlert.district == district)
    if active is not None: q = q.filter(GeoFenceAlert.active == active)
    rows = q.order_by(GeoFenceAlert.id.desc()).all()
    return [{"id": r.id, "district": r.district, "zone_name": r.zone_name, "alert_type": r.alert_type, "threshold": r.threshold, "active": r.active, "notes": r.notes} for r in rows]



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

@app.get('/tasks/{task_id}/executions')
def task_executions(task_id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(TaskExecution).filter(TaskExecution.task_id == task_id).order_by(TaskExecution.id.desc()).all()
    return [{"id": r.id, "task_id": r.task_id, "actor": r.actor, "action": r.action, "notes": r.notes, "created_at": r.created_at.isoformat()} for r in rows]

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
