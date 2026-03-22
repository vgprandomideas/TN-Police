
from db.models import StationRoutingRule

def pick_station_for_case(db, district: str, complaint_type: str | None = None, incident_category: str | None = None, severity: int = 1):
    q = db.query(StationRoutingRule).filter(
        StationRoutingRule.enabled == True,
        StationRoutingRule.district == district
    )
    candidates = []
    for rule in q.all():
        complaint_match = complaint_type and rule.complaint_type.lower() == complaint_type.lower()
        incident_match = incident_category and rule.incident_category and rule.incident_category.lower() == incident_category.lower()
        severity_match = severity >= (rule.min_severity or 1)
        if severity_match and (complaint_match or incident_match):
            candidates.append(rule)
    candidates.sort(key=lambda r: (r.min_severity or 1), reverse=True)
    return candidates[0] if candidates else None
