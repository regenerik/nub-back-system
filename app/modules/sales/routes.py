from flask import Blueprint, request

from app.constants import Role, SaleStatus
from app.extensions import db
from app.live import appointment_room, emit_live_event
from app.modules.appointments.models import Appointment
from app.modules.payments.models import Payment
from app.modules.sales.models import Sale
from app.security import current_user, roles_required
from app.services.appointment_auto_complete import auto_complete_appointment_if_ready
from app.services.sales_service import SaleValidationError, create_sale
from app.utils.http import get_json_payload, list_response, model_to_dict

sales_bp = Blueprint("sales", __name__)


@sales_bp.get("")
@roles_required([Role.ADMIN, Role.RECEPCION])
def list_sales():
    user = current_user()
    query = db.select(Sale)
    if user and user.role == Role.RECEPCION.value and user.branch_id:
        query = query.where(Sale.branch_id == user.branch_id)
    elif request.args.get("branch_id"):
        query = query.where(Sale.branch_id == int(request.args["branch_id"]))
    return list_response(db.session.scalars(query).all())


@sales_bp.post("")
@roles_required([Role.ADMIN, Role.RECEPCION])
def post_sale():
    user = current_user()
    payload = get_json_payload()
    if user and user.role == Role.RECEPCION.value and user.branch_id:
        if int(payload.get("branch_id") or 0) != user.branch_id:
            return {"message": "Recepcion solo puede vender en su sucursal."}, 403
    try:
        sale = create_sale(payload, user.id if user else None)
        db.session.commit()
        return model_to_dict(sale), 201
    except PermissionError as exc:
        db.session.rollback()
        return {"message": str(exc)}, 403
    except (KeyError, ValueError, SaleValidationError) as exc:
        db.session.rollback()
        return {"message": str(exc)}, 400


@sales_bp.get("/<int:sale_id>")
@roles_required([Role.ADMIN, Role.RECEPCION])
def get_sale(sale_id):
    sale = db.session.get(Sale, sale_id)
    if not sale:
        return {"message": "Venta no encontrada."}, 404
    return model_to_dict(sale)


@sales_bp.patch("/<int:sale_id>/cancel")
@roles_required([Role.ADMIN, Role.RECEPCION])
def cancel_sale(sale_id):
    sale = db.session.get(Sale, sale_id)
    if not sale:
        return {"message": "Venta no encontrada."}, 404
    sale.status = SaleStatus.CANCELLED.value
    db.session.commit()
    emit_live_event("sale:updated", model_to_dict(sale), room=f"branch:{sale.branch_id}")
    return model_to_dict(sale)


@sales_bp.post("/<int:sale_id>/payments")
@roles_required([Role.ADMIN, Role.RECEPCION])
def add_payment(sale_id):
    sale = db.session.get(Sale, sale_id)
    if not sale:
        return {"message": "Venta no encontrada."}, 404
    payload = get_json_payload()
    user = current_user()
    payment = Payment(
        sale_id=sale.id,
        method=payload["method"],
        amount=payload["amount"],
        reference=payload.get("reference"),
        created_by_user_id=user.id if user else None,
    )
    db.session.add(payment)
    paid_total = sum(
        p.amount for p in db.session.scalars(db.select(Payment).where(Payment.sale_id == sale.id)).all()
    ) + payment.amount
    sale.status = SaleStatus.PAID.value if paid_total >= sale.total else SaleStatus.PARTIALLY_PAID.value
    completed_appointment = None
    if sale.appointment_id:
        appointment = db.session.get(Appointment, sale.appointment_id)
        if auto_complete_appointment_if_ready(appointment):
            completed_appointment = appointment
    db.session.commit()
    emit_live_event("sale:paid", model_to_dict(sale), room=f"branch:{sale.branch_id}")
    if completed_appointment:
        for room in appointment_room(
            completed_appointment.branch_id,
            completed_appointment.barber_id,
            completed_appointment.client_id,
        ):
            emit_live_event("appointment:completed", model_to_dict(completed_appointment), room=room)
    emit_live_event("stats:updated", {"branch_id": sale.branch_id}, room=f"branch:{sale.branch_id}")
    return {"sale": model_to_dict(sale), "payment": model_to_dict(payment)}, 201
