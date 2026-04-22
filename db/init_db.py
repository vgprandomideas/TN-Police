
import csv
import json
import math
from pathlib import Path
from db.database import Base, engine, SessionLocal
from db.models import (
    AlertRule,
    CameraAsset,
    CameraIncidentAssignment,
    Case,
    CaseTimelineEvent,
    CheckpointPlan,
    ConnectorRegistry,
    DepartmentMessage,
    EvidenceAttachment,
    EvidenceIntegrityLog,
    GeoBoundary,
    GeofenceZone,
    GraphSavedView,
    Incident,
    NarrativeBrief,
    NotificationEvent,
    PersonnelPresence,
    Role,
    Station,
    StationRoutingRule,
    TaskExecution,
    TaskQueue,
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


def seed_personnel_presence(db):
    demo_presence = [
        {"username": "admin_tn", "room_name": "State Command Net", "district": None, "status_label": "command"},
        {"username": "cyber_analyst", "room_name": "Cyber Fusion Desk", "district": "Chennai", "status_label": "fusion_watch"},
        {"username": "district_sp", "room_name": "Chennai District Coordination", "district": "Chennai", "status_label": "district_duty"},
        {"username": "viewer", "room_name": "State Command Net", "district": None, "status_label": "observer"},
    ]
    for payload in demo_presence:
        exists = db.query(PersonnelPresence).filter_by(username=payload["username"]).first()
        if exists:
            continue
        db.add(PersonnelPresence(**payload))
    db.commit()


def seed_checkpoint_plans(db):
    demo_checkpoints = [
        {
            "district": "Chennai",
            "checkpoint_name": "OMR Corridor Intercept Grid",
            "checkpoint_type": "vehicle_intercept",
            "route_ref": "vehicle-1",
            "status": "active",
            "assigned_unit": "Traffic Intercept Unit Alpha",
            "latitude": 13.0677,
            "longitude": 80.2787,
            "case_id": 1,
            "notes": "Monitor outbound corridor traffic and ANPR hits during cyber-fraud suspect movement window.",
            "created_by": "admin_tn",
        },
        {
            "district": "Coimbatore",
            "checkpoint_name": "Avinashi Road Tech Sweep",
            "checkpoint_type": "device_screening",
            "route_ref": "suspect-1",
            "status": "planned",
            "assigned_unit": "Cyber Mobile Team 2",
            "latitude": 11.0018,
            "longitude": 76.9638,
            "case_id": 3,
            "notes": "Device screening checkpoint aligned to SIM-swap convergence route.",
            "created_by": "cyber_analyst",
        },
        {
            "district": "Madurai",
            "checkpoint_name": "South Junction Patrol Polygon",
            "checkpoint_type": "perimeter_lock",
            "route_ref": "vehicle-2",
            "status": "planned",
            "assigned_unit": "District Response Team",
            "latitude": 9.9252,
            "longitude": 78.1198,
            "case_id": None,
            "notes": "Temporary perimeter lock for high-severity corridor movement review.",
            "created_by": "district_sp",
        },
    ]
    for payload in demo_checkpoints:
        exists = db.query(CheckpointPlan).filter_by(
            district=payload["district"],
            checkpoint_name=payload["checkpoint_name"],
        ).first()
        if exists:
            continue
        db.add(CheckpointPlan(**payload))
    db.commit()


def build_geo_polygon(center_latitude, center_longitude, radius_lat=0.16, radius_lon=0.18, sides=6, rotation_deg=-30.0):
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


def seed_geo_boundaries_and_geofences(db):
    district_csv_path = Path(__file__).resolve().parents[1] / "data" / "tn_district_coordinates.csv"
    district_rows = []
    if district_csv_path.exists():
        with open(district_csv_path, newline="", encoding="utf-8") as handle:
            district_rows = list(csv.DictReader(handle))

    for row in district_rows:
        district = row["district"]
        latitude = float(row["latitude"])
        longitude = float(row["longitude"])
        district_zone_name = f"{district} District Boundary"
        if not db.query(GeoBoundary).filter_by(boundary_type="district", district=district, zone_name=district_zone_name).first():
            db.add(
                GeoBoundary(
                    boundary_type="district",
                    district=district,
                    zone_name=district_zone_name,
                    centroid_latitude=latitude,
                    centroid_longitude=longitude,
                    points_json=build_geo_polygon(latitude, longitude, radius_lat=0.18, radius_lon=0.2, sides=8),
                    boundary_rank="command",
                )
            )

    station_rows = db.query(Station).order_by(Station.district, Station.station_name).all()
    for index, station in enumerate(station_rows):
        station_zone_name = f"{station.station_name} Station Boundary"
        if not db.query(GeoBoundary).filter_by(boundary_type="station", district=station.district, zone_name=station_zone_name).first():
            db.add(
                GeoBoundary(
                    boundary_type="station",
                    district=station.district,
                    station_name=station.station_name,
                    zone_name=station_zone_name,
                    centroid_latitude=station.latitude,
                    centroid_longitude=station.longitude,
                    points_json=build_geo_polygon(station.latitude, station.longitude, radius_lat=0.038, radius_lon=0.042, sides=6),
                    boundary_rank="station",
                )
            )
        patrol_zone_name = f"{station.station_name} Patrol Sector"
        if not db.query(GeoBoundary).filter_by(boundary_type="patrol_sector", district=station.district, zone_name=patrol_zone_name).first():
            db.add(
                GeoBoundary(
                    boundary_type="patrol_sector",
                    district=station.district,
                    station_name=station.station_name,
                    zone_name=patrol_zone_name,
                    centroid_latitude=station.latitude + (0.01 if index % 2 == 0 else -0.008),
                    centroid_longitude=station.longitude + (0.01 if index % 3 == 0 else -0.006),
                    points_json=build_geo_polygon(station.latitude, station.longitude, radius_lat=0.024, radius_lon=0.028, sides=5),
                    boundary_rank="patrol",
                )
            )

    seeded_geofences = [
        ("Chennai", "North Port Interdiction Ring", "high_watch", "Chennai Central", 13.0922, 80.2911, 4.8, "Cargo interdiction watch around logistics corridor."),
        ("Coimbatore", "Avinashi Device Sweep Zone", "device_sweep", "Coimbatore Central", 11.0174, 76.9691, 3.6, "SIM-swap and handset sweep geofence for corridor screening."),
        ("Madurai", "Temple Corridor Movement Fence", "movement_watch", "Madurai Central", 9.9252, 78.1198, 3.9, "Route interception and crowd-aware movement watch zone."),
        ("Thoothukudi", "Harbor Freight Camera Fence", "camera_priority", "Thoothukudi Central", 8.8053, 78.1511, 4.2, "Camera reinforcement and freight-watch geofence."),
    ]
    for district, zone_name, geofence_type, station_name, latitude, longitude, radius_km, notes in seeded_geofences:
        if not db.query(GeofenceZone).filter_by(district=district, zone_name=zone_name).first():
            db.add(
                GeofenceZone(
                    district=district,
                    station_name=station_name,
                    zone_name=zone_name,
                    geofence_type=geofence_type,
                    center_latitude=latitude,
                    center_longitude=longitude,
                    radius_km=radius_km,
                    points_json=build_geo_polygon(latitude, longitude, radius_lat=radius_km / 95.0, radius_lon=radius_km / 102.0, sides=7),
                    status="active",
                    notes=notes,
                    created_by="admin_tn",
                )
            )

    db.commit()


def seed_camera_assets_and_assignments(db):
    station_rows = db.query(Station).order_by(Station.district, Station.id).all()
    for station_index, station in enumerate(station_rows):
        camera_profiles = [
            ("PTZ", 0.94, 8.2, "90 days"),
            ("ANPR", 0.88, 10.4, "60 days"),
            ("Dome", 0.91, 6.4, "45 days"),
        ]
        for profile_index, (camera_type, health_score, blind_spot_score, retention_profile) in enumerate(camera_profiles, start=1):
            camera_code = f"{station.district[:3].upper()}-{station.id:03d}-{profile_index:02d}"
            if db.query(CameraAsset).filter_by(camera_id=camera_code).first():
                continue
            adjusted_health = max(0.58, round(health_score - ((station_index % 7) * 0.03), 2))
            adjusted_blind = round(blind_spot_score + ((station_index % 5) * 0.8), 2)
            status = "online" if adjusted_health >= 0.82 else "degraded" if adjusted_health >= 0.68 else "maintenance"
            db.add(
                CameraAsset(
                    camera_id=camera_code,
                    district=station.district,
                    station_id=station.id,
                    zone_name=f"{station.station_name} {camera_type} Watch",
                    camera_type=camera_type,
                    status=status,
                    health_score=adjusted_health,
                    blind_spot_score=adjusted_blind,
                    retention_profile=retention_profile,
                    owner_unit=f"{station.station_name} Surveillance Cell",
                    latitude=station.latitude + (0.003 * profile_index),
                    longitude=station.longitude + (0.002 * profile_index),
                )
            )
    db.commit()

    incidents = db.query(Incident).order_by(Incident.created_at.desc()).limit(18).all()
    cameras = db.query(CameraAsset).order_by(CameraAsset.id).all()
    cameras_by_district = {}
    for camera in cameras:
        cameras_by_district.setdefault(camera.district, []).append(camera)

    for incident in incidents:
        district_cameras = cameras_by_district.get(incident.district, [])
        for camera in district_cameras[:2]:
            exists = db.query(CameraIncidentAssignment).filter_by(camera_asset_id=camera.id, incident_id=incident.id).first()
            if exists:
                continue
            db.add(
                CameraIncidentAssignment(
                    camera_asset_id=camera.id,
                    incident_id=incident.id,
                    case_id=None,
                    assignment_type="incident_cover",
                    status="linked",
                    notes=f"Seeded coverage assignment for incident {incident.id} in {incident.district}.",
                    assigned_by="admin_tn",
                )
            )
    db.commit()


def seed_graph_saved_views(db):
    demo_views = [
        {
            "username": "admin_tn",
            "title": "Statewide High-Risk Convergence",
            "district": None,
            "case_id": None,
            "focus_node_id": "entity-1",
            "selected_node_ids_json": json.dumps(["entity-1", "entity-2", "entity-5", "entity-7"]),
            "notes": "High-risk statewide convergence around linked phones, vehicles, and beneficiaries.",
        },
        {
            "username": "cyber_analyst",
            "title": "SIM Swap Cluster Trace",
            "district": "Chennai",
            "case_id": 3,
            "focus_node_id": "entity-3",
            "selected_node_ids_json": json.dumps(["entity-3", "entity-4", "case-3"]),
            "notes": "Focused cyber-fraud trace around case-linked devices and subscriber pivots.",
        },
    ]
    for payload in demo_views:
        if db.query(GraphSavedView).filter_by(username=payload["username"], title=payload["title"]).first():
            continue
        db.add(GraphSavedView(**payload))
    db.commit()


def seed_dispatch_workflow(db):
    demo_tasks = [
        {
            "district": "Chennai",
            "task_type": "corridor_intercept",
            "priority": "high",
            "assigned_unit": "Traffic Intercept Unit Alpha",
            "status": "in_progress",
            "details": "Maintain ANPR-backed corridor intercept coverage around OMR vehicle route.",
            "case_id": 1,
            "created_by": "admin_tn",
            "actions": [
                ("created", "Task opened from corridor route watch.", "Traffic Intercept Unit Alpha", "queued"),
                ("approved", "District command approved intercept posture.", "Traffic Intercept Unit Alpha", "approved"),
                ("deployed", "Field unit deployed to the active corridor.", "Traffic Intercept Unit Alpha", "in_progress"),
            ],
        },
        {
            "district": "Coimbatore",
            "task_type": "device_screening_sweep",
            "priority": "critical",
            "assigned_unit": "Cyber Mobile Team 2",
            "status": "approved",
            "details": "Prepare device screening sweep for the linked SIM-swap route.",
            "case_id": 3,
            "created_by": "cyber_analyst",
            "actions": [
                ("created", "Task created from fusion route convergence.", "Cyber Mobile Team 2", "queued"),
                ("assigned", "Screening unit assigned to field operation.", "Cyber Mobile Team 2", "assigned"),
                ("approved", "Approval granted by command for field execution.", "Cyber Mobile Team 2", "approved"),
            ],
        },
        {
            "district": "Madurai",
            "task_type": "perimeter_lock",
            "priority": "medium",
            "assigned_unit": "District Response Team",
            "status": "completed",
            "details": "Temporary perimeter lock around south-junction corridor with closure report pending.",
            "case_id": None,
            "created_by": "district_sp",
            "actions": [
                ("created", "Perimeter lock drafted from war-room planning.", "District Response Team", "queued"),
                ("executed", "Perimeter lock activated around active junction.", "District Response Team", "in_progress"),
                ("closed", "Action closed after corridor review and debrief.", "District Response Team", "completed"),
            ],
        },
    ]

    for payload in demo_tasks:
        task = db.query(TaskQueue).filter_by(district=payload["district"], task_type=payload["task_type"], details=payload["details"]).first()
        if not task:
            task = TaskQueue(
                district=payload["district"],
                task_type=payload["task_type"],
                priority=payload["priority"],
                assigned_unit=payload["assigned_unit"],
                status=payload["status"],
                details=payload["details"],
                case_id=payload["case_id"],
                created_by=payload["created_by"],
            )
            db.add(task)
            db.flush()

        for action, notes, assigned_unit, resulting_status in payload["actions"]:
            if db.query(TaskExecution).filter_by(task_id=task.id, action=action, notes=notes).first():
                continue
            db.add(
                TaskExecution(
                    task_id=task.id,
                    actor=payload["created_by"],
                    action=action,
                    notes=f"{notes} Assigned unit: {assigned_unit}. Status: {resulting_status}.",
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
        seed_personnel_presence(db)
        seed_checkpoint_plans(db)
        seed_geo_boundaries_and_geofences(db)
        seed_camera_assets_and_assignments(db)
        seed_graph_saved_views(db)
        seed_dispatch_workflow(db)
    finally:
        db.close()

if __name__ == "__main__":
    main()
