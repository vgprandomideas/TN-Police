from collections import defaultdict
from db.models import Entity, EntityLink

def recompute_entity_scores(db):
    entities = {e.id: e for e in db.query(Entity).all()}
    degree = defaultdict(float)
    for link in db.query(EntityLink).all():
        degree[link.source_entity_id] += link.weight
        degree[link.target_entity_id] += link.weight * 0.8
    max_score = max(degree.values()) if degree else 1.0
    for entity_id, entity in entities.items():
        raw = degree.get(entity_id, 0.0)
        entity.risk_score = round((raw / max_score) * 100, 2)
    db.commit()