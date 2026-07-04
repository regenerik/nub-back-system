import json

from flask import request

from app.extensions import db
from app.models import AuditLog


def audit(action: str, entity: str, entity_id=None, detail=None, user_id=None) -> None:
    entry = AuditLog(
        user_id=user_id,
        action=action,
        entity=entity,
        entity_id=str(entity_id) if entity_id is not None else None,
        detail=json.dumps(detail, default=str) if detail is not None else None,
        ip=request.remote_addr if request else None,
    )
    db.session.add(entry)
