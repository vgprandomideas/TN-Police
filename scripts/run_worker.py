from datetime import datetime
from db.database import SessionLocal
from db.models import IngestQueue, AuditLog
from services.anomaly import score_incident_anomalies
from services.alerts import rebuild_alerts

def main():
    db = SessionLocal()
    queued = db.query(IngestQueue).filter(IngestQueue.status == "queued").all()
    for row in queued:
        row.status = "processed"
        row.processed_at = datetime.utcnow()
        db.add(AuditLog(username="worker", action="ingest_processed", object_type="ingest_queue", object_id=str(row.id)))
    db.commit()
    score_incident_anomalies(db)
    rebuild_alerts(db)
    db.close()
    print(f"Processed {len(queued)} queued rows")

if __name__ == "__main__":
    main()