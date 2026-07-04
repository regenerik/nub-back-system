from flask import Blueprint, request

from app.constants import Role
from app.extensions import db
from app.modules.salaries.models import SalaryPayment
from app.security import current_user, roles_required
from app.utils.http import (
    get_json_payload,
    list_response,
    model_to_dict,
    parse_optional_date,
    parse_optional_datetime,
)

admin_salaries_bp = Blueprint("admin_salaries", __name__)


@admin_salaries_bp.get("/salaries")
@roles_required([Role.ADMIN])
def list_salaries():
    query = db.select(SalaryPayment)
    if request.args.get("branch_id"):
        query = query.where(SalaryPayment.branch_id == int(request.args["branch_id"]))
    return list_response(db.session.scalars(query).all())


@admin_salaries_bp.post("/salaries")
@roles_required([Role.ADMIN])
def create_salary():
    payload = get_json_payload()
    user = current_user()
    recipient_type = payload.get("recipient_type", "barbero")
    barber_id = payload.get("barber_id") if recipient_type == "barbero" else None
    recipient_user_id = payload.get("user_id") if recipient_type == "recepcion" else None
    if recipient_type == "barbero" and not barber_id:
        return {"message": "Seleccioná un barbero."}, 400
    if recipient_type == "recepcion" and not recipient_user_id:
        return {"message": "Seleccioná un usuario de recepción."}, 400
    salary = SalaryPayment(
        branch_id=payload.get("branch_id"),
        recipient_type=recipient_type,
        barber_id=barber_id,
        user_id=recipient_user_id,
        amount=payload["amount"],
        period_start=parse_optional_date(payload["period_start"]),
        period_end=parse_optional_date(payload["period_end"]),
        paid_at=parse_optional_datetime(payload.get("paid_at")),
        notes=payload.get("notes"),
        created_by_user_id=user.id if user else None,
    )
    db.session.add(salary)
    db.session.commit()
    return model_to_dict(salary), 201
