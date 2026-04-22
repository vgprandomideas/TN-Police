
from pydantic import BaseModel

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


class DepartmentMessageCreate(BaseModel):
    room_name: str
    message_text: str
    channel_scope: str = "statewide"
    district: str | None = None
    recipient_username: str | None = None
    priority: str = "routine"
    ack_required: bool = False
    case_id: int | None = None
