import sys
from pathlib import Path
from datetime import datetime
import csv
import json

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from db.database import SessionLocal
from db.models import (
    PublicMetric, Entity, EntityLink, Incident, Station, IngestQueue, Case, CaseComment,
    CaseAssignment, Complaint, ComplaintCaseLink, Watchlist, WatchlistHit,
    EvidenceAttachment, CaseTimelineEvent, ProsecutionPacket, CustodyLog, MedicalCheckLog,
    EventCommandBoard, DocumentIntake, ExtractedEntity, CourtHearing, PrisonMovement,
    NotificationEvent, GraphSnapshot, GeoFenceAlert, AdapterStub, TaskQueue, TaskExecution,
    SuspectDossier, GraphInsight, CourtPacketExport, EvidenceIntegrityLog, NarrativeBrief,
    HotspotForecast, PatrolCoverageMetric, SimilarityHit, TimelineDigest, ExportJob,
    WarRoomSnapshot, ExplorationBookmark, OntologyClass, OntologyRelationType, EntityAttributeFact,
    EntityResolutionCandidate, EntityResolutionDecision, ProvenanceRecord, ConnectorRun, ConnectorArtifact,
    VideoParticipant, VideoSession, OperationalCorridor, WorkflowPlaybook
)
from services.graph_scoring import recompute_entity_scores
from services.anomaly import score_incident_anomalies
from services.alerts import rebuild_alerts
from services.sla import apply_case_sla

DATA = ROOT / "data"


def main():
    db = SessionLocal()

    with open(DATA / "public_metrics_seed.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            exists = db.query(PublicMetric).filter_by(year=int(row["year"]), district=row["district"], metric_name=row["metric_name"]).first()
            if not exists:
                db.add(PublicMetric(
                    year=int(row["year"]), district=row["district"], metric_name=row["metric_name"],
                    metric_value=float(row["metric_value"]), unit=row["unit"], provenance=row["provenance"], notes=row["notes"],
                ))
    db.commit()

    entities = [
        ("suspect", "Ravi Kumar", "Chennai"), ("device", "IMEI-8899-XX", "Chennai"), ("vehicle", "TN01AB1234", "Chennai"),
        ("account", "Acct-Ref-77", "Madurai"), ("suspect", "Sathish", "Madurai"), ("device", "IMEI-4455-ZZ", "Madurai"),
        ("wallet", "UPI-WALLET-443", "Coimbatore"), ("phone", "+91-9XXXXXX123", "Chennai"),
        ("suspect", "R. Kumar", "Chennai"), ("device", "IMEI-8899-XX-ALT", "Chennai"), ("account", "Acct-Ref-77 ALT", "Madurai"),
    ]
    for etype, name, district in entities:
        if not db.query(Entity).filter_by(display_name=name).first():
            db.add(Entity(entity_type=etype, display_name=name, district=district))
    db.commit()

    entity_map = {e.display_name: e.id for e in db.query(Entity).all()}

    links = [(entity_map["Ravi Kumar"],entity_map["IMEI-8899-XX"],"uses",3.0),
             (entity_map["Ravi Kumar"],entity_map["TN01AB1234"],"travels_in",2.5),
             (entity_map["IMEI-8899-XX"],entity_map["Acct-Ref-77"],"linked_transfer",1.5),
             (entity_map["Sathish"],entity_map["IMEI-4455-ZZ"],"uses",2.0),
             (entity_map["IMEI-8899-XX"],entity_map["+91-9XXXXXX123"],"registered_to",1.2),
             (entity_map["R. Kumar"],entity_map["IMEI-8899-XX-ALT"],"uses",2.7),
             (entity_map["IMEI-8899-XX-ALT"],entity_map["+91-9XXXXXX123"],"registered_to",1.1),
             (entity_map["IMEI-8899-XX-ALT"],entity_map["Acct-Ref-77 ALT"],"linked_transfer",1.3)]
    for src, tgt, rel, weight in links:
        if not db.query(EntityLink).filter_by(source_entity_id=src, target_entity_id=tgt, relationship_type=rel).first():
            db.add(EntityLink(source_entity_id=src, target_entity_id=tgt, relationship_type=rel, weight=weight))
    db.commit()

    stations = db.query(Station).all()
    station_map = {}
    for s in stations:
        station_map.setdefault(s.district, []).append(s.id)

    incidents = [
        ("Chennai", "cyber fraud", 4, "open", "Wallet scam cluster pattern in complaint intake", "synthetic_demo"),
        ("Chennai", "protest", 3, "open", "Social media activity indicates possible protest mobilisation", "synthetic_demo"),
        ("Madurai", "violent crime", 5, "open", "Retaliation risk after local gang arrest", "synthetic_demo"),
        ("Coimbatore", "fraud", 3, "open", "UPI mule account complaint correlation", "synthetic_demo"),
        ("Tiruchirappalli", "traffic disruption", 2, "open", "Procession route congestion risk", "synthetic_demo"),
        ("Thoothukudi", "smuggling", 5, "open", "Cargo anomaly reported near port-linked logistics corridor", "synthetic_demo"),
        ("Salem", "cyber fraud", 4, "open", "Phishing complaints concentrated in one ward", "synthetic_demo"),
        ("Erode", "fraud", 2, "open", "Finance complaint pattern with repeat device identifiers", "synthetic_demo"),
        ("Chennai", "cyber fraud", 5, "open", "Citizen portal complaint references Ravi Kumar and same wallet handle", "public_portal_bridge"),
    ]
    for idx, (district, category, severity, status, desc, source_type) in enumerate(incidents):
        sid = station_map[district][idx % len(station_map[district])]
        if not db.query(Incident).filter_by(district=district, category=category, description=desc).first():
            db.add(Incident(district=district, station_id=sid, category=category, severity=severity, status=status, description=desc, source_type=source_type))
    db.commit()

    for src in ["tn_cctns_citizen_portal", "national_cybercrime_portal", "patrol_reporting_ingest", "cctv_event_bridge"]:
        if not db.query(IngestQueue).filter_by(source_name=src).first():
            db.add(IngestQueue(source_name=src, payload_ref="public_probe_or_demo", status="queued"))
    db.commit()

    complaints_seed = [
        ("public_portal", "Chennai", "cyber fraud", "CMP-REF-001", "Victim reports Ravi Kumar wallet scam tied to mobile number and UPI handle."),
        ("cyber_portal", "Madurai", "financial fraud", "MDU-REF-022", "Multiple small-value unauthorized transfers observed after phishing call."),
        ("public_portal", "Coimbatore", "identity misuse", "CBE-REF-017", "SIM swap suspicion with repeated OTP intercept complaints."),
    ]
    for channel, district, ctype, cref, desc in complaints_seed:
        if not db.query(Complaint).filter_by(complainant_ref=cref).first():
            db.add(Complaint(channel=channel, district=district, complaint_type=ctype, complainant_ref=cref, description=desc))
    db.commit()

    cases_needed = {
        "Chennai wallet scam cluster": ("Chennai", station_map["Chennai"][1], "high", "Cross-link cyber complaints, device identifiers, and payment accounts.", "admin_tn"),
        "Madurai retaliation watch": ("Madurai", station_map["Madurai"][0], "high", "Monitor likely retaliatory violence after gang detention.", "district_sp"),
        "Coimbatore SIM swap review": ("Coimbatore", station_map["Coimbatore"][0], "medium", "Correlate telecom complaints and beneficiary account patterns.", "cyber_analyst"),
    }
    for title, (district, station_id, priority, summary, created_by) in cases_needed.items():
        if not db.query(Case).filter_by(title=title).first():
            c = Case(title=title, district=district, station_id=station_id, priority=priority, status="open", summary=summary, created_by=created_by)
            apply_case_sla(c)
            db.add(c)
    db.commit()

    cases = {c.title: c for c in db.query(Case).all()}

    if not db.query(CaseComment).first():
        db.add(CaseComment(case_id=cases["Chennai wallet scam cluster"].id, username="cyber_analyst", comment_text="Need bank freeze request workflow in next version."))
        db.add(CaseComment(case_id=cases["Madurai retaliation watch"].id, username="district_sp", comment_text="Increase night patrol around repeat hotspots."))
        db.add(CaseAssignment(case_id=cases["Chennai wallet scam cluster"].id, assignee_username="cyber_analyst", assigned_by="admin_tn", role_label="lead analyst"))
        db.add(CaseAssignment(case_id=cases["Madurai retaliation watch"].id, assignee_username="district_sp", assigned_by="admin_tn", role_label="district lead"))
    db.commit()

    complaints = {c.complainant_ref: c.id for c in db.query(Complaint).all()}
    links_seed = [
        (complaints.get("CMP-REF-001"), cases["Chennai wallet scam cluster"].id, "Same wallet pattern and handset description."),
        (complaints.get("MDU-REF-022"), cases["Madurai retaliation watch"].id, "Linked only as a monitoring placeholder for cross-district suspicious transfers."),
        (complaints.get("CBE-REF-017"), cases["Coimbatore SIM swap review"].id, "Telecom complaint cluster routed into cyber review case."),
    ]
    for complaint_id, case_id, rationale in links_seed:
        if complaint_id and case_id and not db.query(ComplaintCaseLink).filter_by(complaint_id=complaint_id, case_id=case_id).first():
            db.add(ComplaintCaseLink(complaint_id=complaint_id, case_id=case_id, linked_by="admin_tn", rationale=rationale))
    db.commit()

    watchlists = [
        ("Ravi Kumar", "Chennai", "person", "Repeatedly mentioned in cyber-fraud complaints", "admin_tn"),
        ("UPI-WALLET-443", "Coimbatore", "wallet", "High-risk payment handle", "cyber_analyst"),
    ]
    for name, district, watch_type, rationale, created_by in watchlists:
        if not db.query(Watchlist).filter_by(name=name).first():
            db.add(Watchlist(name=name, district=district, watch_type=watch_type, rationale=rationale, created_by=created_by))
    db.commit()

    watch_map = {w.name: w.id for w in db.query(Watchlist).all()}
    incident_map = {i.description: i.id for i in db.query(Incident).all()}
    hits = [
        (watch_map.get("Ravi Kumar"), entity_map.get("Ravi Kumar"), cases["Chennai wallet scam cluster"].id, incident_map.get("Citizen portal complaint references Ravi Kumar and same wallet handle"), "Name match in complaint text and linked entity", 0.91),
        (watch_map.get("UPI-WALLET-443"), entity_map.get("UPI-WALLET-443"), cases["Coimbatore SIM swap review"].id, None, "Wallet linked through prior complaint graph", 0.74),
    ]
    for watchlist_id, entity_id, case_id, incident_id, reason, confidence in hits:
        if watchlist_id and not db.query(WatchlistHit).filter_by(watchlist_id=watchlist_id, case_id=case_id, hit_reason=reason).first():
            db.add(WatchlistHit(watchlist_id=watchlist_id, entity_id=entity_id, case_id=case_id, incident_id=incident_id, hit_reason=reason, confidence=confidence))
    db.commit()

    evidence = [
        (cases["Chennai wallet scam cluster"].id, "document", "wallet-freeze-note.pdf", "demo://evidence/wallet-freeze-note.pdf", "Draft freeze note", "cyber_analyst"),
        (cases["Madurai retaliation watch"].id, "image", "hotspot-map.png", "demo://evidence/hotspot-map.png", "Night patrol map snapshot", "district_sp"),
    ]
    for case_id, att_type, file_name, storage_ref, notes, uploaded_by in evidence:
        if not db.query(EvidenceAttachment).filter_by(case_id=case_id, file_name=file_name).first():
            db.add(EvidenceAttachment(case_id=case_id, attachment_type=att_type, file_name=file_name, storage_ref=storage_ref, notes=notes, uploaded_by=uploaded_by))
    db.commit()

    timeline_seed = [
        (cases["Chennai wallet scam cluster"].id, "case_created", "admin_tn", "Case opened for multi-complaint wallet scam cluster."),
        (cases["Chennai wallet scam cluster"].id, "complaint_linked", "admin_tn", "Complaint CMP-REF-001 linked into case."),
        (cases["Chennai wallet scam cluster"].id, "watchlist_hit", "system", "Watchlist hit on Ravi Kumar at 0.91 confidence."),
        (cases["Chennai wallet scam cluster"].id, "evidence_added", "cyber_analyst", "wallet-freeze-note.pdf attached."),
        (cases["Madurai retaliation watch"].id, "case_created", "district_sp", "Case opened after violent retaliation risk flagged."),
    ]
    for case_id, event_type, actor, details in timeline_seed:
        if not db.query(CaseTimelineEvent).filter_by(case_id=case_id, event_type=event_type, details=details).first():
            db.add(CaseTimelineEvent(case_id=case_id, event_type=event_type, actor=actor, details=details))
    db.commit()

    recompute_entity_scores(db)
    score_incident_anomalies(db)
    rebuild_alerts(db)
    for c in db.query(Case).all():
        apply_case_sla(c)
    db.commit()


    # v13 seed extensions
    cw = cases.get("Chennai wallet scam cluster")
    mr = cases.get("Madurai retaliation watch")
    if cw and not db.query(ProsecutionPacket).filter_by(case_id=cw.id).first():
        db.add(ProsecutionPacket(case_id=cw.id, packet_status="draft", summary_note="Assemble complaint linkage, entity graph, and evidence chain for fraud prosecution review.", court_name="Chennai Economic Offences Court", created_by="cyber_analyst"))
    if mr and not db.query(CustodyLog).filter_by(case_id=mr.id, person_ref="Sathish").first():
        db.add(CustodyLog(case_id=mr.id, person_ref="Sathish", action="detained_for_questioning", location="Madurai Central Station", officer="district_sp"))
    if mr and not db.query(MedicalCheckLog).filter_by(case_id=mr.id, person_ref="Sathish").first():
        db.add(MedicalCheckLog(case_id=mr.id, person_ref="Sathish", facility_name="Govt Rajaji Hospital", status="scheduled", notes="Pre-remand medical placeholder"))
    if not db.query(EventCommandBoard).filter_by(event_name="Chennai Protest Monitoring").first():
        db.add(EventCommandBoard(district="Chennai", event_name="Chennai Protest Monitoring", event_type="protest", risk_level="high", status="monitoring", command_notes="Blend social chatter, complaint spikes, and patrol saturation."))
    if not db.query(EventCommandBoard).filter_by(event_name="Madurai Temple Festival").first():
        db.add(EventCommandBoard(district="Madurai", event_name="Madurai Temple Festival", event_type="festival", risk_level="medium", status="preparedness", command_notes="Crowd flow, traffic diversion, and anti-theft watch."))
    db.commit()


    # v14+ document intake and hearings
    if not db.query(DocumentIntake).count():
        docs = [
            DocumentIntake(case_id=1, district='Chennai', source_name='Citizen Portal', document_type='complaint_pdf', file_name='complaint_001.pdf', intake_status='parsed', uploaded_by='admin_tn', summary='Cyber fraud complaint with bank references and phone numbers.', extracted_text='Customer reports Rs 4.5 lakh fraud. Accused used phone 9876543210 and mule account AXIS-1882.'),
            DocumentIntake(case_id=2, district='Coimbatore', source_name='District Upload', document_type='seizure_memo', file_name='seizure_memo_014.pdf', intake_status='parsed', uploaded_by='district_sp', summary='Seizure memo linking vehicle and warehouse references.', extracted_text='Vehicle TN09AB1234 and warehouse SIDCO Yard referenced.'),
        ]
        db.add_all(docs); db.commit()
        db.add_all([
            ExtractedEntity(document_id=1, entity_label='PHONE', entity_value='9876543210', confidence=0.96, linked_entity_id=1),
            ExtractedEntity(document_id=1, entity_label='ACCOUNT', entity_value='AXIS-1882', confidence=0.88, linked_entity_id=2),
            ExtractedEntity(document_id=2, entity_label='VEHICLE', entity_value='TN09AB1234', confidence=0.92, linked_entity_id=3),
            ExtractedEntity(document_id=2, entity_label='LOCATION', entity_value='SIDCO Yard', confidence=0.75, linked_entity_id=4),
        ])
        db.add_all([
            CourtHearing(case_id=1, court_name='Special Court for Cyber Cases, Chennai', hearing_date=datetime(2026,3,18,10,30), hearing_stage='bail', outcome='scheduled', next_action='File status note and bank-freeze update', prosecutor='A. Kumar'),
            CourtHearing(case_id=2, court_name='Judicial Magistrate Court, Coimbatore', hearing_date=datetime(2026,3,20,11,0), hearing_stage='remand extension', outcome='scheduled', next_action='Escort production and seizure inventory filing', prosecutor='P. Devi'),
        ])

    # v15+ prison movement bridge and notifications
    if not db.query(PrisonMovement).count():
        db.add_all([
            PrisonMovement(case_id=2, person_ref='ACC-COIM-02', district='Coimbatore', prison_name='Coimbatore Central Prison', movement_type='admission', movement_time=datetime(2026,3,12,8,30), escort_unit='Q Branch Escort 2', notes='Admitted after remand order'),
            PrisonMovement(case_id=1, person_ref='ACC-CHE-01', district='Chennai', prison_name='Puzhal Central Prison', movement_type='court_production', movement_time=datetime(2026,3,14,6,45), escort_unit='Cyber Wing Escort', notes='Production for bail hearing'),
        ])
        db.add_all([
            NotificationEvent(notification_type='hearing_reminder', channel='in_app', recipient='district_sp', subject='Upcoming hearing for Case 1', message='Prepare status note before 18 Mar hearing.', status='queued', related_object_type='case', related_object_id='1'),
            NotificationEvent(notification_type='sla_warning', channel='email_stub', recipient='cyber_analyst', subject='Case 2 nearing SLA breach', message='Resolution SLA due within 24 hours.', status='queued', related_object_type='case', related_object_id='2'),
        ])

    # v16+ graph snapshots and geofence alerts
    if not db.query(GraphSnapshot).count():
        db.add_all([
            GraphSnapshot(case_id=1, node_count=14, edge_count=18, risk_density=0.73, summary='Dense cyber-fraud network linking mule accounts, devices, and complaint clusters.'),
            GraphSnapshot(case_id=2, node_count=9, edge_count=11, risk_density=0.58, summary='Moderate logistics-linked graph around vehicle, warehouse, and consignee nodes.'),
        ])
        db.add_all([
            GeoFenceAlert(district='Chennai', zone_name='T Nagar Commercial Belt', alert_type='crowd_pressure', threshold=0.72, active=True, notes='Raise command-room review when anomaly density crosses threshold.'),
            GeoFenceAlert(district='Coimbatore', zone_name='Gandhipuram Bus Corridor', alert_type='repeat_theft_cluster', threshold=0.61, active=True, notes='Monitor evening repeat-offender movement against incident clusters.'),
        ])


    db.commit()



    # v17+ adapter stubs, task orchestration, suspect dossiers, graph insights
    if not db.query(AdapterStub).count():
        db.add_all([
            AdapterStub(adapter_name='cctns_fir_adapter_stub', source_system='CCTNS/FIR', mode='stub', endpoint_hint='public citizen portal status forms', sample_payload='{"fir_no":"optional","district":"Chennai"}', last_probe_status='ready'),
            AdapterStub(adapter_name='patrol_mobile_adapter_stub', source_system='Patrol Reporting', mode='stub', endpoint_hint='mobile patrol upload placeholder', sample_payload='{"beat":"T Nagar","shift":"night"}', last_probe_status='ready'),
            AdapterStub(adapter_name='cctv_event_adapter_stub', source_system='CCTV/Event Bridge', mode='stub', endpoint_hint='camera event webhook placeholder', sample_payload='{"camera_id":"CBE-22","event":"crowd_anomaly"}', last_probe_status='ready'),
        ])
    if not db.query(TaskQueue).count():
        db.add_all([
            TaskQueue(case_id=1, district='Chennai', task_type='bank_freeze_followup', priority='high', assigned_unit='Cyber Cell Chennai', status='queued', details='Confirm beneficiary accounts and freeze trail within 6 hours.', created_by='admin_tn'),
            TaskQueue(case_id=1, district='Chennai', task_type='device_correlation', priority='high', assigned_unit='Digital Forensics Desk', status='in_progress', details='Correlate handset, SIM, and complaint references.', created_by='cyber_analyst'),
            TaskQueue(case_id=2, district='Madurai', task_type='night_patrol_saturation', priority='high', assigned_unit='District Patrol Unit', status='queued', details='Increase patrol around retaliation-risk hotspots.', created_by='district_sp'),
        ])
        db.commit()
        task_ids = [t.id for t in db.query(TaskQueue).all()]
        db.add_all([
            TaskExecution(task_id=task_ids[0], actor='cyber_analyst', action='created_checklist', notes='Freeze letter, bank nodal contact, and victim statement collected.'),
            TaskExecution(task_id=task_ids[1], actor='cyber_analyst', action='ran_link_analysis', notes='Same IMEI appears in two complaint narratives.'),
            TaskExecution(task_id=task_ids[2], actor='district_sp', action='briefed_patrol', notes='Night route plan issued to two mobile units.'),
        ])
    if not db.query(SuspectDossier).count():
        rk = db.query(Entity).filter(Entity.display_name == 'Ravi Kumar').first()
        st = db.query(Entity).filter(Entity.display_name == 'Sathish').first()
        if rk:
            db.add(SuspectDossier(entity_id=rk.id, district='Chennai', threat_level='high', category='cyber_fraud_operator', known_associates=4, known_devices=2, linked_cases=1, open_alerts=2, narrative='Recurring mention across complaint text, device links, and wallet path indicators.'))
        if st:
            db.add(SuspectDossier(entity_id=st.id, district='Madurai', threat_level='medium', category='violent_network_associate', known_associates=3, known_devices=1, linked_cases=1, open_alerts=1, narrative='Appears in retaliation-risk monitoring after local detention events.'))
    if not db.query(GraphInsight).count():
        db.add_all([
            GraphInsight(case_id=1, district='Chennai', insight_type='hub_entity', score=0.89, headline='Ravi Kumar sits at center of the highest-density wallet/device cluster', explanation='Entity graph shows above-average connectivity between complaint text, phone references, device nodes, and payment paths.'),
            GraphInsight(case_id=1, district='Chennai', insight_type='convergence', score=0.77, headline='Two complaints converge on same handset-account corridor', explanation='The same device and transfer references recur across separate complaint entries.'),
            GraphInsight(case_id=2, district='Madurai', insight_type='retaliation_signal', score=0.68, headline='Violence watch case linked to repeat movement corridor', explanation='Open incidents and event notes show concentration in same patrol zone during night hours.'),
        ])
    db.commit()



    # v18+ court packet exports, evidence integrity, narrative briefs
    if not db.query(CourtPacketExport).count():
        db.add_all([
            CourtPacketExport(case_id=1, export_type='prosecution_packet', export_ref='demo://exports/case_1_packet_v1.json', generated_by='cyber_analyst'),
            CourtPacketExport(case_id=2, export_type='remand_note', export_ref='demo://exports/case_2_remand_note_v1.json', generated_by='district_sp'),
        ])
    if not db.query(EvidenceIntegrityLog).count():
        for ev in db.query(EvidenceAttachment).all():
            db.add(EvidenceIntegrityLog(evidence_id=ev.id, integrity_state='verified', checksum_stub=f'SHA256-STUB-{ev.id:04d}', verified_by='admin_tn', notes='MVP chain-of-custody checksum placeholder.'))
    if not db.query(NarrativeBrief).count():
        db.add_all([
            NarrativeBrief(case_id=1, brief_type='executive_summary', title='Case 1 executive narrative', body='Cyber-fraud case with clustered complaints, payment-handle overlap, and repeated handset references. Immediate priority is account freezing, device correlation, and complaint expansion.', created_by='cyber_analyst'),
            NarrativeBrief(case_id=1, brief_type='court_note', title='Case 1 court-facing narrative', body='The complaint cluster indicates a consistent wallet and device corridor. Evidence currently consists of intake narratives, graph correlation, and freeze-note draft.', created_by='cyber_analyst'),
            NarrativeBrief(case_id=2, brief_type='district_brief', title='Case 2 district watch brief', body='Retaliation-risk violence watch remains active with patrol saturation recommended near recurring locations.', created_by='district_sp'),
        ])
    db.commit()



    # v19+ hotspot forecasts, patrol coverage, similarity hits
    if not db.query(HotspotForecast).count():
        db.add_all([
            HotspotForecast(district='Chennai', zone_name='T Nagar Commercial Belt', risk_category='cyber fraud / crowd pressure', forecast_score=0.81, horizon_days=7, recommended_action='Boost patrol visibility, freeze-response desk, and crowd camera review.'),
            HotspotForecast(district='Madurai', zone_name='North Mobility Corridor', risk_category='retaliatory violence', forecast_score=0.69, horizon_days=5, recommended_action='Night patrol saturation and station-level watch brief.'),
            HotspotForecast(district='Coimbatore', zone_name='Gandhipuram Bus Corridor', risk_category='repeat theft cluster', forecast_score=0.63, horizon_days=10, recommended_action='Plainclothes deployment during evening peak.'),
        ])
    if not db.query(PatrolCoverageMetric).count():
        sample_stations = db.query(Station).limit(5).all()
        for idx, s in enumerate(sample_stations, start=1):
            db.add(PatrolCoverageMetric(district=s.district, station_id=s.id, beat_name=f'{s.station_name} Beat-{idx}', coverage_ratio=0.55 + idx*0.05, backlog=max(0,4-idx), open_incidents=idx+2))
    if not db.query(SimilarityHit).count():
        db.add_all([
            SimilarityHit(source_type='complaint', source_id=1, target_type='complaint', target_id=2, similarity_score=0.61, rationale='Overlap in transfer-loss pattern and repeated urgency wording.'),
            SimilarityHit(source_type='entity', source_id=1, target_type='watchlist', target_id=1, similarity_score=0.94, rationale='Direct name and graph-neighborhood match.'),
            SimilarityHit(source_type='incident', source_id=1, target_type='geofence', target_id=1, similarity_score=0.58, rationale='Incident category and zone alert align with same commercial belt.'),
        ])
    db.commit()



    # v20+ timeline digests, export jobs, war-room snapshots, bookmarks
    if not db.query(TimelineDigest).count():
        db.add_all([
            TimelineDigest(case_id=1, digest_title='Case 1 compressed timeline', digest_body='Complaint intake, case creation, watchlist hit, evidence addition, and bank-freeze follow-up task all occurred inside a compact response window.', generated_by='system'),
            TimelineDigest(case_id=2, digest_title='Case 2 compressed timeline', digest_body='Risk alert, case opening, patrol briefing, and command-board linkage define the current investigation path.', generated_by='system'),
        ])
    if not db.query(ExportJob).count():
        db.add_all([
            ExportJob(export_scope='case', object_id='1', format='json', status='ready', export_ref='demo://exports/case_1_full.json', created_by='admin_tn'),
            ExportJob(export_scope='district_snapshot', object_id='Chennai', format='csv', status='ready', export_ref='demo://exports/chennai_snapshot.csv', created_by='admin_tn'),
        ])
    if not db.query(WarRoomSnapshot).count():
        db.add_all([
            WarRoomSnapshot(district='Chennai', snapshot_label='Morning Command Snapshot', active_cases=4, active_alerts=3, pending_tasks=2, forecast_hotspots=2, command_summary='Cyber-fraud remains dominant. Focus on freeze workflow and T Nagar pressure zone.'),
            WarRoomSnapshot(district='Madurai', snapshot_label='Evening Risk Snapshot', active_cases=2, active_alerts=2, pending_tasks=1, forecast_hotspots=1, command_summary='Retaliation watch and crowd-flow control remain the key concerns.'),
        ])
    if not db.query(ExplorationBookmark).count():
        db.add_all([
            ExplorationBookmark(username='admin_tn', bookmark_type='case', object_ref='case:1', title='Wallet scam master case', notes='Primary demo case for cyber workflow.'),
            ExplorationBookmark(username='cyber_analyst', bookmark_type='graph', object_ref='graph:case:1', title='Dense fraud graph', notes='Useful for briefing and demo walkthrough.'),
        ])
    db.commit()

    # v21+ ontology, provenance, resolution, connectors, and native video scaffolding
    if not db.query(EntityAttributeFact).count():
        attribute_facts = [
            (entity_map["Ravi Kumar"], "full_name", "Ravi Kumar", "string", 0.97, "tn_cctns_citizen_portal", "CMP-REF-001"),
            (entity_map["Ravi Kumar"], "phone", "+91-9XXXXXX123", "phone", 0.91, "national_cybercrime_portal", "NCCRP-RK-22"),
            (entity_map["R. Kumar"], "alias_name", "R. Kumar", "string", 0.84, "field_interview_card", "FIC-CHE-14"),
            (entity_map["IMEI-8899-XX"], "imei", "IMEI-8899-XX", "imei", 0.99, "device_seizure_memo", "SEIZ-CHE-09"),
            (entity_map["IMEI-8899-XX-ALT"], "imei", "IMEI-8899-XX", "imei", 0.86, "cdr_device_correlation", "CDR-ALT-12"),
            (entity_map["Acct-Ref-77"], "account_no", "Acct-Ref-77", "account", 0.88, "bank_freeze_note", "BNK-FRZ-77"),
            (entity_map["Acct-Ref-77 ALT"], "account_alias", "Acct-Ref-77", "account", 0.74, "beneficiary_review", "BEN-REV-77A"),
            (entity_map["TN01AB1234"], "registration_no", "TN01AB1234", "vehicle", 0.96, "vehicle_registry_bridge", "VREG-CHE-01"),
            (entity_map["UPI-WALLET-443"], "wallet_id", "UPI-WALLET-443", "wallet", 0.93, "wallet_risk_feed", "WALLET-443"),
        ]
        for entity_id, attribute_name, attribute_value, value_type, confidence, source_name, source_ref in attribute_facts:
            exists = db.query(EntityAttributeFact).filter_by(entity_id=entity_id, attribute_name=attribute_name, attribute_value=attribute_value).first()
            if not exists:
                db.add(
                    EntityAttributeFact(
                        entity_id=entity_id,
                        attribute_name=attribute_name,
                        attribute_value=attribute_value,
                        value_type=value_type,
                        confidence=confidence,
                        source_name=source_name,
                        source_ref=source_ref,
                    )
                )
    db.commit()

    if not db.query(EntityResolutionCandidate).count():
        resolution_candidates = [
            (entity_map["Ravi Kumar"], entity_map["R. Kumar"], 0.94, "Alias, phone overlap, and complaint-text similarity indicate the same suspect identity.", "accepted", "cluster-person-rk"),
            (entity_map["IMEI-8899-XX"], entity_map["IMEI-8899-XX-ALT"], 0.89, "IMEI normalization and phone registration overlap indicate a duplicate device identity.", "accepted", "cluster-device-imei-8899"),
            (entity_map["Acct-Ref-77"], entity_map["Acct-Ref-77 ALT"], 0.76, "Bank-freeze note and beneficiary review suggest an account alias needing analyst confirmation.", "review", "cluster-account-77"),
        ]
        for left_entity_id, right_entity_id, match_score, rationale, status, cluster_ref in resolution_candidates:
            candidate = db.query(EntityResolutionCandidate).filter_by(left_entity_id=left_entity_id, right_entity_id=right_entity_id).first()
            if not candidate:
                db.add(
                    EntityResolutionCandidate(
                        left_entity_id=left_entity_id,
                        right_entity_id=right_entity_id,
                        match_score=match_score,
                        rationale=rationale,
                        status=status,
                        cluster_ref=cluster_ref,
                    )
                )
    db.commit()

    if not db.query(EntityResolutionDecision).count():
        candidate_lookup = {
            (row.left_entity_id, row.right_entity_id): row
            for row in db.query(EntityResolutionCandidate).all()
        }
        seeded_decisions = [
            (candidate_lookup.get((entity_map["Ravi Kumar"], entity_map["R. Kumar"])), "accepted", "admin_tn", "Alias consolidated into the same investigation cluster."),
            (candidate_lookup.get((entity_map["IMEI-8899-XX"], entity_map["IMEI-8899-XX-ALT"])), "accepted", "cyber_analyst", "Normalized duplicate IMEI variant to a shared device cluster."),
        ]
        for candidate, decision_status, decided_by, notes in seeded_decisions:
            if not candidate:
                continue
            exists = db.query(EntityResolutionDecision).filter_by(candidate_id=candidate.id).first()
            if not exists:
                db.add(
                    EntityResolutionDecision(
                        candidate_id=candidate.id,
                        decision_status=decision_status,
                        decided_by=decided_by,
                        notes=notes,
                    )
                )
    db.commit()

    if not db.query(ProvenanceRecord).count():
        provenance_records = [
            ("case", str(cases["Chennai wallet scam cluster"].id), "Chennai", "tn_cctns_citizen_portal", "complaint_feed", "CMP-REF-001", "case_created", 0.94, "admin_tn", "Primary complaint created the fraud investigation lens."),
            ("entity", str(entity_map["Ravi Kumar"]), "Chennai", "national_cybercrime_portal", "entity_extraction", "NCCRP-RK-22", "entity_linked", 0.91, "cyber_analyst", "Suspect extracted from cross-portal complaint review."),
            ("entity", str(entity_map["IMEI-8899-XX"]), "Chennai", "device_seizure_memo", "forensic_extract", "SEIZ-CHE-09", "observed", 0.98, "cyber_analyst", "IMEI captured during forensic intake."),
            ("incident", str(incident_map.get("Citizen portal complaint references Ravi Kumar and same wallet handle")), "Chennai", "public_portal_bridge", "citizen_complaint", "CMP-REF-001", "incident_ingested", 0.87, "system", "Incident created from citizen complaint bridge."),
            ("connector_artifact", "CMP-REF-001", "Chennai", "tn_cctns_citizen_portal", "connector_run", "artifact:CMP-REF-001", "artifact_synced", 0.92, "system", "Artifact synchronized from sanctioned complaint connector."),
            ("resolution_candidate", "cluster-person-rk", "Chennai", "entity_resolution_engine", "fusion_score", "cluster-person-rk", "candidate_scored", 0.94, "system", "Alias-confidence threshold exceeded for suspect cluster."),
        ]
        for object_type, object_id, district, source_name, source_type, source_ref, operation, confidence, collected_by, notes in provenance_records:
            exists = db.query(ProvenanceRecord).filter_by(object_type=object_type, object_id=object_id, source_name=source_name, source_ref=source_ref).first()
            if not exists:
                db.add(
                    ProvenanceRecord(
                        object_type=object_type,
                        object_id=object_id,
                        district=district,
                        source_name=source_name,
                        source_type=source_type,
                        source_ref=source_ref,
                        operation=operation,
                        confidence=confidence,
                        collected_by=collected_by,
                        notes=notes,
                    )
                )
    db.commit()

    connector_runs = {row.connector_name: row for row in db.query(ConnectorRun).order_by(ConnectorRun.id.desc()).all()}
    if connector_runs:
        connector_artifact_specs = [
            ("tn_cctns_citizen_portal", "complaint", "CMP-REF-001", "Chennai", cases["Chennai wallet scam cluster"].id, entity_map["Ravi Kumar"], "Wallet fraud complaint synchronized into the case fabric."),
            ("national_cybercrime_portal", "entity", "NCCRP-RK-22", "Chennai", cases["Chennai wallet scam cluster"].id, entity_map["Ravi Kumar"], "Cybercrime portal alias artifact linked to suspect cluster."),
            ("patrol_reporting_ingest", "patrol_update", "PATROL-NIGHT-22", "Madurai", cases["Madurai retaliation watch"].id, entity_map["Sathish"], "Night patrol update linked to retaliation watch posture."),
        ]
        for connector_name, record_type, external_ref, district, case_id, entity_id, ingest_summary in connector_artifact_specs:
            run = connector_runs.get(connector_name)
            if not run:
                continue
            exists = db.query(ConnectorArtifact).filter_by(connector_run_id=run.id, external_ref=external_ref).first()
            if not exists:
                db.add(
                    ConnectorArtifact(
                        connector_run_id=run.id,
                        connector_name=connector_name,
                        record_type=record_type,
                        external_ref=external_ref,
                        district=district,
                        case_id=case_id,
                        entity_id=entity_id,
                        ingest_summary=ingest_summary,
                        status="ingested",
                    )
                )
    db.commit()

    session = db.query(VideoSession).filter(VideoSession.session_code == "tn-police-state-command-ops").first()
    if session and not db.query(VideoParticipant).filter(VideoParticipant.session_id == session.id).count():
        video_participants = [
            ("admin_tn", "admin", "Command bridge workstation", "connected", False, False, True, True),
            ("cyber_analyst", "cyber_analyst", "Fusion desk node", "connected", False, True, True, False),
            ("district_sp", "district_sp", "District command tablet", "connected", True, False, False, False),
        ]
        for username, role_label, device_label, join_state, hand_raised, muted, camera_enabled, screen_sharing in video_participants:
            db.add(
                VideoParticipant(
                    session_id=session.id,
                    username=username,
                    role_label=role_label,
                    device_label=device_label,
                    join_state=join_state,
                    hand_raised=hand_raised,
                    muted=muted,
                    camera_enabled=camera_enabled,
                    screen_sharing=screen_sharing,
                )
            )
    db.commit()

    if db.query(WorkflowPlaybook).count():
        playbook_notes = {
            "Cyber Fraud Freeze Playbook": "Escalate bank-freeze and wallet-trace actions with cyber-fusion oversight.",
            "SIM Swap Sweep Playbook": "Coordinate telecom and checkpoint actions around device swap indicators.",
            "Retaliation Patrol Saturation": "Push district patrol saturation and corridor watch around hotspot surge.",
        }
        for row in db.query(WorkflowPlaybook).all():
            if row.action_template_json:
                continue
            row.action_template_json = json.dumps([
                "raise war room briefing",
                "create task bundle",
                "attach corridor watch",
                playbook_notes.get(row.playbook_name, "Issue command briefing"),
            ])
    db.commit()
    db.commit()
    db.close()
    print("Seeded demo data")

if __name__ == "__main__":
    main()
