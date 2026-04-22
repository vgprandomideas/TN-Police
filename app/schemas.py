
from pydantic import BaseModel, Field

class LoginRequest(BaseModel):
    username: str
    password: str

class ComplaintCreate(BaseModel):
    district: str
    complaint_type: str
    channel: str = "public_portal"
    complainant_ref: str | None = None
    description: str | None = None

class CaseCreate(BaseModel):
    title: str
    district: str
    station_id: int | None = None
    priority: str = "medium"
    summary: str | None = None

class CaseCommentCreate(BaseModel):
    comment_text: str

class CaseAssignCreate(BaseModel):
    assignee_username: str
    role_label: str | None = None

class ComplaintCaseLinkCreate(BaseModel):
    complaint_id: int
    case_id: int
    rationale: str | None = None

class WatchlistCreate(BaseModel):
    name: str
    district: str | None = None
    watch_type: str = "person"
    rationale: str | None = None

class EvidenceCreate(BaseModel):
    attachment_type: str = "document"
    file_name: str
    storage_ref: str
    notes: str | None = None


class MessageAttachmentCreate(BaseModel):
    attachment_name: str
    attachment_type: str = "document"
    storage_ref: str


class DepartmentMessageCreate(BaseModel):
    room_name: str
    message_text: str
    channel_scope: str = "statewide"
    district: str | None = None
    recipient_username: str | None = None
    priority: str = "routine"
    ack_required: bool = False
    case_id: int | None = None
    attachments: list[MessageAttachmentCreate] = Field(default_factory=list)


class DepartmentMessageReadCreate(BaseModel):
    room_name: str
    last_read_message_id: int | None = None


class PresenceHeartbeatCreate(BaseModel):
    room_name: str | None = None
    district: str | None = None
    status_label: str = "active"


class TypingHeartbeatCreate(BaseModel):
    room_name: str
    district: str | None = None
    case_id: int | None = None
    is_typing: bool = True


class CheckpointPlanCreate(BaseModel):
    district: str
    checkpoint_name: str
    checkpoint_type: str = "vehicle_intercept"
    route_ref: str | None = None
    status: str = "planned"
    assigned_unit: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    case_id: int | None = None
    notes: str | None = None


class GraphSavedViewCreate(BaseModel):
    title: str
    district: str | None = None
    case_id: int | None = None
    focus_node_id: str | None = None
    selected_node_ids: list[str] = Field(default_factory=list)
    notes: str | None = None


class GeofenceZoneCreate(BaseModel):
    district: str
    zone_name: str
    geofence_type: str = "watch_zone"
    station_name: str | None = None
    center_latitude: float
    center_longitude: float
    radius_km: float = 3.0
    status: str = "active"
    notes: str | None = None


class CameraIncidentAssignmentCreate(BaseModel):
    camera_asset_id: int
    incident_id: int | None = None
    case_id: int | None = None
    assignment_type: str = "primary_coverage"
    status: str = "linked"
    notes: str | None = None


class TaskCreate(BaseModel):
    district: str
    task_type: str
    priority: str = "medium"
    assigned_unit: str | None = None
    status: str = "queued"
    details: str | None = None
    case_id: int | None = None


class TaskActionCreate(BaseModel):
    action: str
    notes: str | None = None
    assigned_unit: str | None = None
    status: str | None = None
