from flask import Blueprint, request

from app.constants import Role
from app.extensions import db
from app.security import current_user, roles_required
from app.services.audit_service import audit
from app.services.backup_service import export_full_backup, restore_backup, validate_backup
from app.utils.http import get_json_payload

admin_backup_bp = Blueprint("admin_backup", __name__)


@admin_backup_bp.get("/backup/full")
@roles_required([Role.ADMIN])
def export_backup():
    return export_full_backup()


@admin_backup_bp.post("/backup/validate")
@roles_required([Role.ADMIN])
def validate_backup_payload():
    valid, issues = validate_backup(get_json_payload())
    return {"valid": valid, "issues": issues}


@admin_backup_bp.post("/backup/restore")
@roles_required([Role.ADMIN])
def restore_backup_payload():
    user = current_user()
    result = restore_backup(
        get_json_payload(),
        dry_run=request.args.get("dry_run", "true").lower() == "true",
    )
    audit(
        "backup.restore",
        "backup",
        detail={"dry_run": result.get("dry_run"), "valid": result.get("valid")},
        user_id=user.id if user else None,
    )
    db.session.commit()
    return result, 202
