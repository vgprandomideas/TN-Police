from db.models import PublicMetric, Alert, AlertRule, Incident

def rebuild_alerts(db):
    db.query(Alert).delete()
    rules = {r.name: r for r in db.query(AlertRule).filter_by(enabled=True).all()}
    metrics = db.query(PublicMetric).all()
    for m in metrics:
        if m.metric_name == "cybercrime_complaints" and "Cyber Complaints Spike" in rules:
            if m.metric_value >= rules["Cyber Complaints Spike"].threshold:
                db.add(Alert(
                    district=m.district,
                    alert_type="cyber_spike",
                    severity=4,
                    message=f"{m.district}: {int(m.metric_value)} cyber complaints in {m.year}",
                ))
        if m.metric_name == "murders" and "High Murder Count" in rules:
            if m.metric_value >= rules["High Murder Count"].threshold:
                db.add(Alert(
                    district=m.district,
                    alert_type="murder_threshold",
                    severity=5,
                    message=f"{m.district}: murder count {int(m.metric_value)} in {m.year}",
                ))
    for incident in db.query(Incident).all():
        if incident.anomaly_score >= 0.75:
            db.add(Alert(
                district=incident.district,
                alert_type="incident_anomaly",
                severity=min(5, max(3, incident.severity)),
                message=f"Incident {incident.id} anomaly score {incident.anomaly_score:.2f}: {incident.category}",
            ))
    db.commit()