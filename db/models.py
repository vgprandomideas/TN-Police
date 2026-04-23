
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Float, Text, Boolean
from db.database import Base

class Role(Base):
    __tablename__ = "roles"
    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True, nullable=False)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(80), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(120))
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=False)
    district = Column(String(80))
    is_active = Column(Boolean, default=True)

class Station(Base):
    __tablename__ = "stations"
    id = Column(Integer, primary_key=True)
    district = Column(String(80), nullable=False)
    station_name = Column(String(120), nullable=False)
    station_type = Column(String(50), default="Police Station")
    latitude = Column(Float)
    longitude = Column(Float)

class PublicMetric(Base):
    __tablename__ = "public_metrics"
    id = Column(Integer, primary_key=True)
    year = Column(Integer, nullable=False)
    district = Column(String(80), default="Tamil Nadu")
    metric_name = Column(String(120), nullable=False)
    metric_value = Column(Float, nullable=False)
    unit = Column(String(30), default="count")
    provenance = Column(String(50), default="public")
    notes = Column(Text)

class Incident(Base):
    __tablename__ = "incidents"
    id = Column(Integer, primary_key=True)
    district = Column(String(80), nullable=False)
    station_id = Column(Integer, ForeignKey("stations.id"))
    category = Column(String(80), nullable=False)
    severity = Column(Integer, default=1)
    status = Column(String(50), default="open")
    description = Column(Text)
    anomaly_score = Column(Float, default=0.0)
    source_type = Column(String(50), default="synthetic_demo")
    created_at = Column(DateTime, default=datetime.utcnow)

class Complaint(Base):
    __tablename__ = "complaints"
    id = Column(Integer, primary_key=True)
    channel = Column(String(50), default="public_portal")
    district = Column(String(80), nullable=False)
    complaint_type = Column(String(80), nullable=False)
    complainant_ref = Column(String(120))
    description = Column(Text)
    status = Column(String(50), default="received")
    created_at = Column(DateTime, default=datetime.utcnow)

class Entity(Base):
    __tablename__ = "entities"
    id = Column(Integer, primary_key=True)
    entity_type = Column(String(50), nullable=False)
    display_name = Column(String(120), nullable=False)
    district = Column(String(80))
    risk_score = Column(Float, default=0.0)

class EntityLink(Base):
    __tablename__ = "entity_links"
    id = Column(Integer, primary_key=True)
    source_entity_id = Column(Integer, ForeignKey("entities.id"), nullable=False)
    target_entity_id = Column(Integer, ForeignKey("entities.id"), nullable=False)
    relationship_type = Column(String(80), nullable=False)
    weight = Column(Float, default=1.0)

class AlertRule(Base):
    __tablename__ = "alert_rules"
    id = Column(Integer, primary_key=True)
    name = Column(String(120), unique=True, nullable=False)
    threshold = Column(Float, nullable=False)
    enabled = Column(Boolean, default=True)

class Alert(Base):
    __tablename__ = "alerts"
    id = Column(Integer, primary_key=True)
    district = Column(String(80), nullable=False)
    alert_type = Column(String(80), nullable=False)
    severity = Column(Integer, default=1)
    message = Column(Text)
    status = Column(String(50), default="open")
    created_at = Column(DateTime, default=datetime.utcnow)

class IngestQueue(Base):
    __tablename__ = "ingest_queue"
    id = Column(Integer, primary_key=True)
    source_name = Column(String(120), nullable=False)
    payload_ref = Column(String(255))
    status = Column(String(50), default="queued")
    created_at = Column(DateTime, default=datetime.utcnow)
    processed_at = Column(DateTime)

class Case(Base):
    __tablename__ = "cases"
    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    district = Column(String(80), nullable=False)
    station_id = Column(Integer, ForeignKey("stations.id"))
    priority = Column(String(30), default="medium")
    status = Column(String(50), default="open")
    summary = Column(Text)
    created_by = Column(String(80), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    response_due_at = Column(DateTime)
    resolution_due_at = Column(DateTime)
    sla_status = Column(String(30), default="on_track")

class CaseComment(Base):
    __tablename__ = "case_comments"
    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=False)
    username = Column(String(80), nullable=False)
    comment_text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class CaseAssignment(Base):
    __tablename__ = "case_assignments"
    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=False)
    assignee_username = Column(String(80), nullable=False)
    assigned_by = Column(String(80), nullable=False)
    role_label = Column(String(80))
    created_at = Column(DateTime, default=datetime.utcnow)

class ComplaintCaseLink(Base):
    __tablename__ = "complaint_case_links"
    id = Column(Integer, primary_key=True)
    complaint_id = Column(Integer, ForeignKey("complaints.id"), nullable=False)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=False)
    linked_by = Column(String(80), nullable=False)
    rationale = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

class ConnectorRegistry(Base):
    __tablename__ = "connector_registry"
    id = Column(Integer, primary_key=True)
    connector_name = Column(String(120), unique=True, nullable=False)
    source_type = Column(String(80), nullable=False)
    base_url = Column(String(255))
    sanctioned = Column(Boolean, default=True)
    access_mode = Column(String(50), default="public_web")
    notes = Column(Text)

class StationRoutingRule(Base):
    __tablename__ = "station_routing_rules"
    id = Column(Integer, primary_key=True)
    district = Column(String(80), nullable=False)
    complaint_type = Column(String(80), nullable=False)
    incident_category = Column(String(80))
    min_severity = Column(Integer, default=1)
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=False)
    priority_override = Column(String(30))
    enabled = Column(Boolean, default=True)
    notes = Column(Text)

class Watchlist(Base):
    __tablename__ = "watchlists"
    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    district = Column(String(80))
    watch_type = Column(String(50), default="person")
    rationale = Column(Text)
    status = Column(String(30), default="active")
    created_by = Column(String(80), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class WatchlistHit(Base):
    __tablename__ = "watchlist_hits"
    id = Column(Integer, primary_key=True)
    watchlist_id = Column(Integer, ForeignKey("watchlists.id"), nullable=False)
    entity_id = Column(Integer, ForeignKey("entities.id"))
    case_id = Column(Integer, ForeignKey("cases.id"))
    incident_id = Column(Integer, ForeignKey("incidents.id"))
    hit_reason = Column(Text)
    confidence = Column(Float, default=0.5)
    created_at = Column(DateTime, default=datetime.utcnow)

class EvidenceAttachment(Base):
    __tablename__ = "evidence_attachments"
    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=False)
    attachment_type = Column(String(50), default="document")
    file_name = Column(String(180), nullable=False)
    storage_ref = Column(String(255), nullable=False)
    notes = Column(Text)
    uploaded_by = Column(String(80), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class CaseTimelineEvent(Base):
    __tablename__ = "case_timeline_events"
    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=False)
    event_type = Column(String(80), nullable=False)
    actor = Column(String(80), nullable=False)
    details = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True)
    username = Column(String(80), nullable=False)
    action = Column(String(120), nullable=False)
    object_type = Column(String(80))
    object_id = Column(String(80))
    created_at = Column(DateTime, default=datetime.utcnow)



class ProsecutionPacket(Base):
    __tablename__ = "prosecution_packets"
    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=False)
    packet_status = Column(String(40), default="draft")
    summary_note = Column(Text)
    court_name = Column(String(160))
    created_by = Column(String(80), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class CustodyLog(Base):
    __tablename__ = "custody_logs"
    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=False)
    person_ref = Column(String(120), nullable=False)
    action = Column(String(80), nullable=False)
    location = Column(String(160))
    officer = Column(String(80))
    created_at = Column(DateTime, default=datetime.utcnow)

class MedicalCheckLog(Base):
    __tablename__ = "medical_check_logs"
    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=False)
    person_ref = Column(String(120), nullable=False)
    facility_name = Column(String(160))
    status = Column(String(80), default="scheduled")
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

class EventCommandBoard(Base):
    __tablename__ = "event_command_board"
    id = Column(Integer, primary_key=True)
    district = Column(String(80), nullable=False)
    event_name = Column(String(160), nullable=False)
    event_type = Column(String(80), nullable=False)
    risk_level = Column(String(30), default="medium")
    status = Column(String(40), default="monitoring")
    command_notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)




class DocumentIntake(Base):
    __tablename__ = "document_intake"
    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=True)
    district = Column(String(80), nullable=False)
    source_name = Column(String(120), nullable=False)
    document_type = Column(String(80), nullable=False)
    file_name = Column(String(180), nullable=False)
    intake_status = Column(String(40), default="received")
    extracted_text = Column(Text)
    summary = Column(Text)
    uploaded_by = Column(String(80), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class ExtractedEntity(Base):
    __tablename__ = "extracted_entities"
    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("document_intake.id"), nullable=False)
    entity_label = Column(String(50), nullable=False)
    entity_value = Column(String(180), nullable=False)
    confidence = Column(Float, default=0.7)
    linked_entity_id = Column(Integer, ForeignKey("entities.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class CourtHearing(Base):
    __tablename__ = "court_hearings"
    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=False)
    court_name = Column(String(180), nullable=False)
    hearing_date = Column(DateTime, nullable=False)
    hearing_stage = Column(String(80), default="mention")
    outcome = Column(String(120), default="scheduled")
    next_action = Column(Text)
    prosecutor = Column(String(120))
    created_at = Column(DateTime, default=datetime.utcnow)

class PrisonMovement(Base):
    __tablename__ = "prison_movements"
    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=True)
    person_ref = Column(String(120), nullable=False)
    district = Column(String(80), nullable=False)
    prison_name = Column(String(180), nullable=False)
    movement_type = Column(String(80), nullable=False)
    movement_time = Column(DateTime, nullable=False)
    escort_unit = Column(String(120))
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

class NotificationEvent(Base):
    __tablename__ = "notification_events"
    id = Column(Integer, primary_key=True)
    notification_type = Column(String(80), nullable=False)
    channel = Column(String(40), default="in_app")
    recipient = Column(String(120), nullable=False)
    subject = Column(String(180), nullable=False)
    message = Column(Text, nullable=False)
    status = Column(String(40), default="queued")
    related_object_type = Column(String(80))
    related_object_id = Column(String(80))
    created_at = Column(DateTime, default=datetime.utcnow)
    sent_at = Column(DateTime)

class DepartmentMessage(Base):
    __tablename__ = "department_messages"
    id = Column(Integer, primary_key=True)
    sender_username = Column(String(80), nullable=False)
    recipient_username = Column(String(80))
    district = Column(String(80))
    room_name = Column(String(120), nullable=False)
    channel_scope = Column(String(40), default="statewide")
    priority = Column(String(30), default="routine")
    message_text = Column(Text, nullable=False)
    ack_required = Column(Boolean, default=False)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class DepartmentMessageRead(Base):
    __tablename__ = "department_message_reads"
    id = Column(Integer, primary_key=True)
    username = Column(String(80), nullable=False)
    room_name = Column(String(120), nullable=False)
    last_read_message_id = Column(Integer, nullable=False, default=0)
    read_at = Column(DateTime, default=datetime.utcnow)

class MessageAttachment(Base):
    __tablename__ = "message_attachments"
    id = Column(Integer, primary_key=True)
    message_id = Column(Integer, ForeignKey("department_messages.id"), nullable=False)
    attachment_name = Column(String(180), nullable=False)
    attachment_type = Column(String(60), default="document")
    storage_ref = Column(String(255), nullable=False)
    uploaded_by = Column(String(80), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class RoomTypingSignal(Base):
    __tablename__ = "room_typing_signals"
    id = Column(Integer, primary_key=True)
    username = Column(String(80), nullable=False)
    room_name = Column(String(120), nullable=False)
    district = Column(String(80))
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=True)
    typing_until = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class PersonnelPresence(Base):
    __tablename__ = "personnel_presence"
    id = Column(Integer, primary_key=True)
    username = Column(String(80), nullable=False)
    room_name = Column(String(120))
    district = Column(String(80))
    status_label = Column(String(40), default="available")
    last_seen_at = Column(DateTime, default=datetime.utcnow)

class CheckpointPlan(Base):
    __tablename__ = "checkpoint_plans"
    id = Column(Integer, primary_key=True)
    district = Column(String(80), nullable=False)
    checkpoint_name = Column(String(160), nullable=False)
    checkpoint_type = Column(String(60), default="vehicle_intercept")
    route_ref = Column(String(120))
    status = Column(String(40), default="planned")
    assigned_unit = Column(String(120))
    latitude = Column(Float)
    longitude = Column(Float)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=True)
    notes = Column(Text)
    created_by = Column(String(80), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class GraphSavedView(Base):
    __tablename__ = "graph_saved_views"
    id = Column(Integer, primary_key=True)
    username = Column(String(80), nullable=False)
    title = Column(String(180), nullable=False)
    district = Column(String(80))
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=True)
    focus_node_id = Column(String(120))
    selected_node_ids_json = Column(Text)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

class GeoBoundary(Base):
    __tablename__ = "geo_boundaries"
    id = Column(Integer, primary_key=True)
    boundary_type = Column(String(60), nullable=False)
    district = Column(String(80), nullable=False)
    station_name = Column(String(160))
    zone_name = Column(String(180), nullable=False)
    centroid_latitude = Column(Float)
    centroid_longitude = Column(Float)
    points_json = Column(Text, nullable=False)
    boundary_rank = Column(String(40), default="operational")
    created_at = Column(DateTime, default=datetime.utcnow)

class GeofenceZone(Base):
    __tablename__ = "geofence_zones"
    id = Column(Integer, primary_key=True)
    district = Column(String(80), nullable=False)
    station_name = Column(String(160))
    zone_name = Column(String(180), nullable=False)
    geofence_type = Column(String(80), default="watch_zone")
    center_latitude = Column(Float, nullable=False)
    center_longitude = Column(Float, nullable=False)
    radius_km = Column(Float, default=3.0)
    points_json = Column(Text, nullable=False)
    status = Column(String(40), default="active")
    notes = Column(Text)
    created_by = Column(String(80), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class CameraAsset(Base):
    __tablename__ = "camera_assets"
    id = Column(Integer, primary_key=True)
    camera_id = Column(String(120), unique=True, nullable=False)
    district = Column(String(80), nullable=False)
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=True)
    zone_name = Column(String(180))
    camera_type = Column(String(80), default="PTZ")
    status = Column(String(40), default="online")
    health_score = Column(Float, default=0.0)
    blind_spot_score = Column(Float, default=0.0)
    retention_profile = Column(String(60), default="60 days")
    owner_unit = Column(String(120))
    latitude = Column(Float)
    longitude = Column(Float)
    last_heartbeat_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)

class CameraIncidentAssignment(Base):
    __tablename__ = "camera_incident_assignments"
    id = Column(Integer, primary_key=True)
    camera_asset_id = Column(Integer, ForeignKey("camera_assets.id"), nullable=False)
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=True)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=True)
    assignment_type = Column(String(80), default="primary_coverage")
    status = Column(String(40), default="linked")
    notes = Column(Text)
    assigned_by = Column(String(80), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class OntologyClass(Base):
    __tablename__ = "ontology_classes"
    id = Column(Integer, primary_key=True)
    class_name = Column(String(80), unique=True, nullable=False)
    display_name = Column(String(120), nullable=False)
    description = Column(Text)
    category = Column(String(80), default="core")
    attribute_schema_json = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

class OntologyRelationType(Base):
    __tablename__ = "ontology_relation_types"
    id = Column(Integer, primary_key=True)
    relation_name = Column(String(80), unique=True, nullable=False)
    source_class = Column(String(80), nullable=False)
    target_class = Column(String(80), nullable=False)
    description = Column(Text)
    directionality = Column(String(40), default="directed")
    confidence_band = Column(String(40), default="medium")
    created_at = Column(DateTime, default=datetime.utcnow)

class EntityAttributeFact(Base):
    __tablename__ = "entity_attribute_facts"
    id = Column(Integer, primary_key=True)
    entity_id = Column(Integer, ForeignKey("entities.id"), nullable=False)
    attribute_name = Column(String(120), nullable=False)
    attribute_value = Column(String(255), nullable=False)
    value_type = Column(String(60), default="string")
    confidence = Column(Float, default=0.0)
    source_name = Column(String(120))
    source_ref = Column(String(180))
    observed_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)

class EntityResolutionCandidate(Base):
    __tablename__ = "entity_resolution_candidates"
    id = Column(Integer, primary_key=True)
    left_entity_id = Column(Integer, ForeignKey("entities.id"), nullable=False)
    right_entity_id = Column(Integer, ForeignKey("entities.id"), nullable=False)
    match_score = Column(Float, default=0.0)
    rationale = Column(Text)
    status = Column(String(40), default="pending")
    cluster_ref = Column(String(120))
    created_at = Column(DateTime, default=datetime.utcnow)

class EntityResolutionDecision(Base):
    __tablename__ = "entity_resolution_decisions"
    id = Column(Integer, primary_key=True)
    candidate_id = Column(Integer, ForeignKey("entity_resolution_candidates.id"), nullable=False)
    decision_status = Column(String(40), default="accepted")
    decided_by = Column(String(80), nullable=False)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

class ProvenanceRecord(Base):
    __tablename__ = "provenance_records"
    id = Column(Integer, primary_key=True)
    object_type = Column(String(80), nullable=False)
    object_id = Column(String(120), nullable=False)
    district = Column(String(80))
    source_name = Column(String(120), nullable=False)
    source_type = Column(String(80), nullable=False)
    source_ref = Column(String(180))
    operation = Column(String(80), default="observed")
    confidence = Column(Float, default=0.0)
    collected_by = Column(String(80))
    notes = Column(Text)
    observed_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)

class ConnectorRun(Base):
    __tablename__ = "connector_runs"
    id = Column(Integer, primary_key=True)
    connector_name = Column(String(120), nullable=False)
    run_mode = Column(String(60), default="poll")
    status = Column(String(40), default="completed")
    records_seen = Column(Integer, default=0)
    records_emitted = Column(Integer, default=0)
    latency_ms = Column(Integer, default=0)
    notes = Column(Text)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime)

class ConnectorArtifact(Base):
    __tablename__ = "connector_artifacts"
    id = Column(Integer, primary_key=True)
    connector_run_id = Column(Integer, ForeignKey("connector_runs.id"), nullable=False)
    connector_name = Column(String(120), nullable=False)
    record_type = Column(String(80), nullable=False)
    external_ref = Column(String(180))
    district = Column(String(80))
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=True)
    entity_id = Column(Integer, ForeignKey("entities.id"), nullable=True)
    ingest_summary = Column(Text)
    status = Column(String(40), default="ingested")
    created_at = Column(DateTime, default=datetime.utcnow)

class VideoSession(Base):
    __tablename__ = "video_sessions"
    id = Column(Integer, primary_key=True)
    room_name = Column(String(120), nullable=False)
    district = Column(String(80))
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=True)
    session_code = Column(String(160), unique=True, nullable=False)
    session_mode = Column(String(60), default="webrtc_mesh")
    status = Column(String(40), default="active")
    notes = Column(Text)
    started_by = Column(String(80), nullable=False)
    started_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime)

class VideoParticipant(Base):
    __tablename__ = "video_participants"
    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("video_sessions.id"), nullable=False)
    username = Column(String(80), nullable=False)
    role_label = Column(String(80))
    device_label = Column(String(120))
    join_state = Column(String(40), default="connected")
    hand_raised = Column(Boolean, default=False)
    muted = Column(Boolean, default=False)
    camera_enabled = Column(Boolean, default=True)
    screen_sharing = Column(Boolean, default=False)
    joined_at = Column(DateTime, default=datetime.utcnow)
    last_seen_at = Column(DateTime, default=datetime.utcnow)

class OperationalCorridor(Base):
    __tablename__ = "operational_corridors"
    id = Column(Integer, primary_key=True)
    district = Column(String(80), nullable=False)
    corridor_name = Column(String(160), nullable=False)
    corridor_type = Column(String(80), default="movement")
    route_ref = Column(String(120))
    points_json = Column(Text, nullable=False)
    risk_score = Column(Float, default=0.0)
    surveillance_priority = Column(String(40), default="medium")
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

class WorkflowPlaybook(Base):
    __tablename__ = "workflow_playbooks"
    id = Column(Integer, primary_key=True)
    district = Column(String(80), nullable=False)
    playbook_name = Column(String(160), nullable=False)
    trigger_type = Column(String(80), nullable=False)
    default_priority = Column(String(40), default="medium")
    assigned_unit_hint = Column(String(120))
    action_template_json = Column(Text)
    status = Column(String(40), default="active")
    created_at = Column(DateTime, default=datetime.utcnow)

class GraphSnapshot(Base):
    __tablename__ = "graph_snapshots"
    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=False)
    node_count = Column(Integer, default=0)
    edge_count = Column(Integer, default=0)
    risk_density = Column(Float, default=0.0)
    summary = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

class GeoFenceAlert(Base):
    __tablename__ = "geofence_alerts"
    id = Column(Integer, primary_key=True)
    district = Column(String(80), nullable=False)
    zone_name = Column(String(160), nullable=False)
    alert_type = Column(String(80), nullable=False)
    threshold = Column(Float, default=0.0)
    active = Column(Boolean, default=True)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)



class TimelineDigest(Base):
    __tablename__ = "timeline_digests"
    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=False)
    digest_title = Column(String(180), nullable=False)
    digest_body = Column(Text, nullable=False)
    generated_by = Column(String(80), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class ExportJob(Base):
    __tablename__ = "export_jobs"
    id = Column(Integer, primary_key=True)
    export_scope = Column(String(80), nullable=False)
    object_id = Column(String(80))
    format = Column(String(30), default="json")
    status = Column(String(40), default="ready")
    export_ref = Column(String(255))
    created_by = Column(String(80), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class WarRoomSnapshot(Base):
    __tablename__ = "war_room_snapshots"
    id = Column(Integer, primary_key=True)
    district = Column(String(80), nullable=False)
    snapshot_label = Column(String(180), nullable=False)
    active_cases = Column(Integer, default=0)
    active_alerts = Column(Integer, default=0)
    pending_tasks = Column(Integer, default=0)
    forecast_hotspots = Column(Integer, default=0)
    command_summary = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

class ExplorationBookmark(Base):
    __tablename__ = "exploration_bookmarks"
    id = Column(Integer, primary_key=True)
    username = Column(String(80), nullable=False)
    bookmark_type = Column(String(80), nullable=False)
    object_ref = Column(String(180), nullable=False)
    title = Column(String(180), nullable=False)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class AdapterStub(Base):
    __tablename__ = "adapter_stubs"
    id = Column(Integer, primary_key=True)
    adapter_name = Column(String(120), unique=True, nullable=False)
    source_system = Column(String(120), nullable=False)
    mode = Column(String(40), default="stub")
    endpoint_hint = Column(String(255))
    sample_payload = Column(Text)
    last_probe_status = Column(String(40), default="ready")
    created_at = Column(DateTime, default=datetime.utcnow)

class TaskQueue(Base):
    __tablename__ = "task_queue"
    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=True)
    district = Column(String(80), nullable=False)
    task_type = Column(String(120), nullable=False)
    priority = Column(String(30), default="medium")
    assigned_unit = Column(String(120))
    status = Column(String(40), default="queued")
    details = Column(Text)
    created_by = Column(String(80), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class TaskExecution(Base):
    __tablename__ = "task_executions"
    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey("task_queue.id"), nullable=False)
    actor = Column(String(80), nullable=False)
    action = Column(String(120), nullable=False)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

class SuspectDossier(Base):
    __tablename__ = "suspect_dossiers"
    id = Column(Integer, primary_key=True)
    entity_id = Column(Integer, ForeignKey("entities.id"), nullable=False)
    district = Column(String(80), nullable=False)
    threat_level = Column(String(30), default="medium")
    category = Column(String(120))
    known_associates = Column(Integer, default=0)
    known_devices = Column(Integer, default=0)
    linked_cases = Column(Integer, default=0)
    open_alerts = Column(Integer, default=0)
    narrative = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

class GraphInsight(Base):
    __tablename__ = "graph_insights"
    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=False)
    district = Column(String(80), nullable=False)
    insight_type = Column(String(80), nullable=False)
    score = Column(Float, default=0.0)
    headline = Column(String(255), nullable=False)
    explanation = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

class CourtPacketExport(Base):
    __tablename__ = "court_packet_exports"
    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=False)
    export_type = Column(String(80), nullable=False)
    export_ref = Column(String(255), nullable=False)
    generated_by = Column(String(80), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class EvidenceIntegrityLog(Base):
    __tablename__ = "evidence_integrity_logs"
    id = Column(Integer, primary_key=True)
    evidence_id = Column(Integer, ForeignKey("evidence_attachments.id"), nullable=False)
    integrity_state = Column(String(40), default="verified")
    checksum_stub = Column(String(255))
    verified_by = Column(String(80))
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

class NarrativeBrief(Base):
    __tablename__ = "narrative_briefs"
    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=True)
    brief_type = Column(String(80), nullable=False)
    title = Column(String(180), nullable=False)
    body = Column(Text, nullable=False)
    created_by = Column(String(80), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class HotspotForecast(Base):
    __tablename__ = "hotspot_forecasts"
    id = Column(Integer, primary_key=True)
    district = Column(String(80), nullable=False)
    zone_name = Column(String(160), nullable=False)
    risk_category = Column(String(120), nullable=False)
    forecast_score = Column(Float, default=0.0)
    horizon_days = Column(Integer, default=7)
    recommended_action = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

class PatrolCoverageMetric(Base):
    __tablename__ = "patrol_coverage_metrics"
    id = Column(Integer, primary_key=True)
    district = Column(String(80), nullable=False)
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=False)
    beat_name = Column(String(120), nullable=False)
    coverage_ratio = Column(Float, default=0.0)
    backlog = Column(Integer, default=0)
    open_incidents = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

class SimilarityHit(Base):
    __tablename__ = "similarity_hits"
    id = Column(Integer, primary_key=True)
    source_type = Column(String(80), nullable=False)
    source_id = Column(Integer, nullable=False)
    target_type = Column(String(80), nullable=False)
    target_id = Column(Integer, nullable=False)
    similarity_score = Column(Float, default=0.0)
    rationale = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
