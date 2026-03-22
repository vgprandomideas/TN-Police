from sklearn.ensemble import IsolationForest
from db.models import Incident

CATEGORY_MAP = {
    "cyber fraud": 1,
    "violent crime": 2,
    "protest": 3,
    "traffic disruption": 4,
    "fraud": 5,
    "smuggling": 6,
}

def score_incident_anomalies(db):
    incidents = db.query(Incident).all()
    if len(incidents) < 5:
        for i in incidents:
            i.anomaly_score = round(min(0.95, 0.2 + (i.severity / 10)), 2)
        db.commit()
        return

    X = []
    for i in incidents:
        X.append([
            CATEGORY_MAP.get(i.category.lower(), 0),
            i.severity,
            1 if i.status == "open" else 0,
        ])
    clf = IsolationForest(random_state=42, contamination=0.2)
    preds = clf.fit_predict(X)
    scores = clf.decision_function(X)
    min_score = min(scores)
    max_score = max(scores)
    denom = (max_score - min_score) or 1.0

    for incident, pred, score in zip(incidents, preds, scores):
        normalized = 1 - ((score - min_score) / denom)
        if pred == -1:
            normalized = max(normalized, 0.75)
        incident.anomaly_score = round(float(normalized), 3)
    db.commit()