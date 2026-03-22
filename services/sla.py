
from datetime import datetime, timedelta
from db.models import Case

PRIORITY_WINDOWS = {
    "high": {"response_hours": 4, "resolution_hours": 48},
    "medium": {"response_hours": 24, "resolution_hours": 120},
    "low": {"response_hours": 48, "resolution_hours": 240},
}

def apply_case_sla(case: Case):
    windows = PRIORITY_WINDOWS.get((case.priority or "medium").lower(), PRIORITY_WINDOWS["medium"])
    created_at = case.created_at or datetime.utcnow()
    if not case.response_due_at:
        case.response_due_at = created_at + timedelta(hours=windows["response_hours"])
    if not case.resolution_due_at:
        case.resolution_due_at = created_at + timedelta(hours=windows["resolution_hours"])
    update_sla_status(case)
    return case


def update_sla_status(case: Case):
    now = datetime.utcnow()
    if case.status == "closed":
        case.sla_status = "closed"
    elif case.resolution_due_at and now > case.resolution_due_at:
        case.sla_status = "breached"
    elif case.response_due_at and now > case.response_due_at:
        case.sla_status = "at_risk"
    else:
        case.sla_status = "on_track"
    return case.sla_status
