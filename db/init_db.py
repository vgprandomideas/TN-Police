
import csv
from pathlib import Path
from db.database import Base, engine, SessionLocal
from db.models import (
    AlertRule,
    Case,
    CaseTimelineEvent,
    ConnectorRegistry,
    DepartmentMessage,
    EvidenceAttachment,
    EvidenceIntegrityLog,
    NarrativeBrief,
    NotificationEvent,
    Role,
    Station,
    StationRoutingRule,
    TimelineDigest,
    User,
)
from services.auth import hash_password
from adapters.sanctioned_connectors import SANCTIONED_CONNECTORS

def seed_roles_users(db):
    roles = ["admin", "cyber_analyst", "district_sp", "viewer"]
    for role_name in roles:
        if not db.query(Role).filter_by(name=role_name).first():
            db.add(Role(name=role_name))
    db.commit()
    role_map = {r.name: r.id for r in db.query(Role).all()}
    users = [
        ("admin_tn", "admin123", "State Admin", "admin", None),
        ("cyber_analyst", "cyber123", "Cyber Analyst", "cyber_analyst", "Chennai"),
        ("district_sp", "district123", "District SP", "district_sp", "Chennai"),
        ("viewer", "viewer123", "Viewer", "viewer", None),
    ]
    for username, pwd, full_name, role_name, district in users:
        if not db.query(User).filter_by(username=username).first():
            db.add(User(
                username=username,
                hashed_password=hash_password(pwd),
                full_name=full_name,
                role_id=role_map[role_name],
                district=district,
                is_active=True,
            ))
    db.commit()

def seed_stations(db):
    csv_path = Path(__file__).resolve().parents[1] / "data" / "station_master_seed.csv"
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            exists = db.query(Station).filter_by(district=row["district"], station_name=row["station_name"]).first()
            if not exists:
                db.add(Station(
                    district=row["district"],
                    station_name=row["station_name"],
                    station_type=row["station_type"],
                    latitude=float(row["latitude"]),
                    longitude=float(row["longitude"]),
                ))
    db.commit()

def seed_alert_rules(db):
    defaults = [("high_murder_count", 1500.0), ("high_cyber_loss", 500.0), ("high_anomaly_incident", 0.8)]
    for name, threshold in defaults:
        if not db.query(AlertRule).filter_by(name=name).first():
            db.add(AlertRule(name=name, threshold=threshold, enabled=True))
    db.commit()

def seed_connectors(db):
    for connector in SANCTIONED_CONNECTORS:
        if not db.query(ConnectorRegistry).filter_by(connector_name=connector["connector_name"]).first():
            db.add(ConnectorRegistry(**connector))
    db.commit()

def seed_routing_rules(db):
    stations = db.query(Station).all()
    station_lookup = {(s.district, s.station_type.lower()): s.id for s in stations}
    rules = [
        ("Chennai", "cyber fraud", None, 1, station_lookup.get(("Chennai", "cyber crime")), "high", "Cyber complaints route to Cyber Crime PS"),
        ("Coimbatore", "cyber fraud", None, 1, station_lookup.get(("Coimbatore", "cyber crime")), "high", "Cyber complaints route to Cyber Crime PS"),
        ("Madurai", "violent crime", "violent crime", 3, station_lookup.get(("Madurai", "central")), "high", "High severity violent crime routes to central station"),
        ("Chennai", "narcotics", "narcotics", 2, station_lookup.get(("Chennai", "central")), "high", "Narcotics cases route to central station in MVP"),
    ]
    for district, complaint_type, incident_category, min_severity, station_id, priority_override, notes in rules:
        if station_id and not db.query(StationRoutingRule).filter_by(
            district=district, complaint_type=complaint_type, station_id=station_id
        ).first():
            db.add(StationRoutingRule(
                district=district,
                complaint_type=complaint_type,
                incident_category=incident_category,
                min_severity=min_severity,
                station_id=station_id,
                priority_override=priority_override,
                enabled=True,
                notes=notes,
            ))
    db.commit()


def seed_case_activity_demo(db):
    demo_cases = {
        3: {
            "timeline": [
                {
                    "event_type": "case_created",
                    "actor": "admin_tn",
                    "details": "Case opened for coordinated SIM swap review across Coimbatore subscriber accounts.",
                },
                {
                    "event_type": "subscriber_pattern_flagged",
                    "actor": "cyber_analyst",
                    "details": "Change-request burst detected across linked numbers with matching IMEI movement.",
                },
                {
                    "event_type": "device_dump_received",
                    "actor": "cyber_analyst",
                    "details": "Forensic device image received from regional cyber lab for handset correlation review.",
                },
            ],
            "evidence": [
                {
                    "attachment_type": "cdr_extract",
                    "file_name": "sim_swap_cdr_extract_case3.csv",
                    "storage_ref": "evidence://case-3/cdr-extract-01",
                    "notes": "Call detail extract for flagged numbers during the SIM replacement window.",
                    "uploaded_by": "cyber_analyst",
                    "integrity_state": "verified",
                    "checksum_stub": "sha256:case3cdr01",
                    "verified_by": "admin_tn",
                },
                {
                    "attachment_type": "forensic_image",
                    "file_name": "device_image_case3.E01",
                    "storage_ref": "evidence://case-3/device-image-01",
                    "notes": "Forensic image of seized handset queued for credential replay analysis.",
                    "uploaded_by": "cyber_analyst",
                    "integrity_state": "sealed",
                    "checksum_stub": "sha256:case3img01",
                    "verified_by": "admin_tn",
                },
            ],
            "digest": {
                "digest_title": "SIM swap escalation window",
                "digest_body": "Three coordinated subscriber change events occurred inside a compressed review window, indicating deliberate account takeover preparation.",
                "generated_by": "cyber_analyst",
            },
            "brief": {
                "brief_type": "investigation_update",
                "title": "Coimbatore SIM swap review brief",
                "body": "Evidence indicates synchronized SIM replacement activity tied to a limited handset cluster and rapid credential recovery attempts.",
                "created_by": "cyber_analyst",
            },
        }
    }

    for case_id, payload in demo_cases.items():
        case = db.query(Case).filter_by(id=case_id).first()
        if not case:
            continue

        for event in payload["timeline"]:
            exists = db.query(CaseTimelineEvent).filter_by(
                case_id=case_id,
                event_type=event["event_type"],
                details=event["details"],
            ).first()
            if not exists:
                db.add(CaseTimelineEvent(case_id=case_id, **event))

        for evidence in payload["evidence"]:
            existing_evidence = db.query(EvidenceAttachment).filter_by(
                case_id=case_id,
                file_name=evidence["file_name"],
            ).first()
            if existing_evidence:
                evidence_row = existing_evidence
            else:
                evidence_row = EvidenceAttachment(
                    case_id=case_id,
                    attachment_type=evidence["attachment_type"],
                    file_name=evidence["file_name"],
                    storage_ref=evidence["storage_ref"],
                    notes=evidence["notes"],
                    uploaded_by=evidence["uploaded_by"],
                )
                db.add(evidence_row)
                db.flush()

            integrity_exists = db.query(EvidenceIntegrityLog).filter_by(
                evidence_id=evidence_row.id,
                checksum_stub=evidence["checksum_stub"],
            ).first()
            if not integrity_exists:
                db.add(
                    EvidenceIntegrityLog(
                        evidence_id=evidence_row.id,
                        integrity_state=evidence["integrity_state"],
                        checksum_stub=evidence["checksum_stub"],
                        verified_by=evidence["verified_by"],
                        notes=f"Seeded demo integrity log for case {case_id}.",
                    )
                )

        digest = payload["digest"]
        if not db.query(TimelineDigest).filter_by(
            case_id=case_id,
            digest_title=digest["digest_title"],
        ).first():
            db.add(TimelineDigest(case_id=case_id, **digest))

        brief = payload["brief"]
        if not db.query(NarrativeBrief).filter_by(
            case_id=case_id,
            title=brief["title"],
        ).first():
            db.add(NarrativeBrief(case_id=case_id, **brief))

    db.commit()


def seed_department_messages(db):
    demo_messages = [
        {
            "sender_username": "admin_tn",
            "recipient_username": None,
            "district": None,
            "room_name": "State Command Net",
            "channel_scope": "statewide",
            "priority": "high",
            "message_text": "Statewide command watch is active. District control rooms will post live field escalations in this channel.",
            "ack_required": True,
            "case_id": None,
        },
        {
            "sender_username": "cyber_analyst",
            "recipient_username": None,
            "district": None,
            "room_name": "Cyber Fusion Desk",
            "channel_scope": "statewide",
            "priority": "routine",
            "message_text": "Cyber fraud cluster review is open. Share device, SIM, and beneficiary overlaps here before opening a new linkage request.",
            "ack_required": False,
            "case_id": 3,
        },
        {
            "sender_username": "district_sp",
            "recipient_username": None,
            "district": "Chennai",
            "room_name": "Chennai District Coordination",
            "channel_scope": "district",
            "priority": "medium",
            "message_text": "Night patrol supervisors should confirm hotspot deployment and CCTV blind-spot coverage around the current priority corridors.",
            "ack_required": True,
            "case_id": None,
        },
        {
            "sender_username": "admin_tn",
            "recipient_username": "viewer",
            "district": None,
            "room_name": "Direct Coordination",
            "channel_scope": "direct",
            "priority": "routine",
            "message_text": "Use the Geo Command workspace to inspect statewide district pressure, then acknowledge the surveillance coverage summary.",
            "ack_required": False,
            "case_id": None,
        },
    ]

    for payload in demo_messages:
        exists = db.query(DepartmentMessage).filter_by(
            sender_username=payload["sender_username"],
            room_name=payload["room_name"],
            message_text=payload["message_text"],
        ).first()
        if exists:
            continue

        message_row = DepartmentMessage(**payload)
        db.add(message_row)
        db.flush()

        recipient = payload["recipient_username"] or payload["room_name"]
        db.add(
            NotificationEvent(
                notification_type="internal_message",
                channel="in_app",
                recipient=recipient,
                subject=f"{payload['room_name']} update",
                message=payload["message_text"],
                status="queued",
                related_object_type="department_message",
                related_object_id=str(message_row.id),
            )
        )

    db.commit()

def main():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_roles_users(db)
        seed_stations(db)
        seed_alert_rules(db)
        seed_connectors(db)
        seed_routing_rules(db)
        seed_case_activity_demo(db)
        seed_department_messages(db)
    finally:
        db.close()

if __name__ == "__main__":
    main()
