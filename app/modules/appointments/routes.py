from datetime import date, datetime, timedelta
from decimal import Decimal

from flask import Blueprint, Response, request
from sqlalchemy import func

from app.constants import AppointmentStatus, Role
from app.extensions import db
from app.live import appointment_room, emit_live_event
from app.modules.appointments.models import Appointment, AppointmentExtraService, BranchDateClosure, ScheduleBlock
from app.modules.barbers.models import Barber
from app.modules.branches.models import Branch
from app.modules.clients.models import Client
from app.modules.payments.models import Payment
from app.modules.sales.models import Sale
from app.modules.services.models import BranchService, Service
from app.security import current_user, login_required, roles_required
from app.services.appointment_service import (
    AppointmentConflict,
    AppointmentValidationError,
    MissingBranchServices,
    barber_is_available,
    create_appointment_atomic,
    get_public_availability,
    get_public_availability_summary,
)
from app.services.appointment_auto_complete import auto_complete_appointment_if_ready
from app.utils.http import get_json_payload, list_response, model_to_dict, parse_date_time

public_availability_bp = Blueprint("public_availability", __name__)
public_appointments_bp = Blueprint("public_appointments", __name__)
appointments_bp = Blueprint("appointments", __name__)
barber_me_bp = Blueprint("barber_me", __name__)
client_me_bp = Blueprint("client_me", __name__)


def date_closure_to_dict(closure: BranchDateClosure) -> dict:
    return model_to_dict(closure)


def appointment_to_dict(appointment: Appointment) -> dict:
    data = model_to_dict(appointment)
    branch = db.session.get(Branch, appointment.branch_id)
    if branch:
        data["branch"] = model_to_dict(branch)
    client = db.session.get(Client, appointment.client_id)
    if client:
        data["client"] = model_to_dict(client)
    barber = db.session.get(Barber, appointment.barber_id)
    if barber:
        data["barber"] = model_to_dict(barber)
    primary = db.session.get(Service, appointment.primary_service_id)
    if primary:
        data["primary_service"] = model_to_dict(primary)
    extras = db.session.execute(
        db.select(AppointmentExtraService, Service)
        .join(Service, Service.id == AppointmentExtraService.service_id)
        .where(AppointmentExtraService.appointment_id == appointment.id)
    ).all()
    data["extra_services"] = [
        model_to_dict(extra)
        | {
            "service": model_to_dict(service),
            "name": service.name,
            "price": float(extra.price_at_booking),
            "duration_minutes": extra.duration_minutes_at_booking,
        }
        for extra, service in extras
    ]
    sale = db.session.scalar(db.select(Sale).where(Sale.appointment_id == appointment.id))
    if sale:
        paid_total = db.session.scalar(
            db.select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.sale_id == sale.id)
        )
        data["sale"] = model_to_dict(sale)
        data["payment_status"] = sale.status
        data["paid_total"] = float(paid_total or 0)
        data["payment_pending"] = max(0, float(sale.total) - float(paid_total or 0))
        data["tip_amount"] = max(0, float(paid_total or 0) - float(sale.total))
    else:
        data["sale"] = None
        data["payment_status"] = "unpaid"
        data["paid_total"] = 0
        data["payment_pending"] = float(appointment.total_final or appointment.total_estimated or 0)
        data["tip_amount"] = 0
    return data


def emit_appointment_event(
    event_name: str,
    appointment: Appointment,
    previous_branch_id: int | None = None,
    previous_barber_id: int | None = None,
) -> None:
    rooms = set(appointment_room(appointment.branch_id, appointment.barber_id, appointment.client_id))
    if previous_branch_id and previous_branch_id != appointment.branch_id:
        rooms.update(appointment_room(previous_branch_id, None, appointment.client_id))
    if previous_barber_id and previous_barber_id != appointment.barber_id:
        rooms.add(f"barber:{previous_barber_id}")
    payload = appointment_to_dict(appointment)
    for room in rooms:
        emit_live_event(event_name, payload, room=room)


def appointment_overlaps(appointment_id: int, barber_id: int, starts_at: datetime, ends_at: datetime) -> list[Appointment]:
    return db.session.scalars(
        db.select(Appointment).where(
            Appointment.id != appointment_id,
            Appointment.barber_id == barber_id,
            Appointment.status.in_(scheduled_statuses()),
            Appointment.starts_at < ends_at,
            Appointment.ends_at > starts_at,
        )
    ).all()


def has_schedule_block(branch_id: int, barber_id: int, starts_at: datetime, ends_at: datetime) -> bool:
    return bool(
        db.session.scalar(
            db.select(ScheduleBlock.id).where(
                ScheduleBlock.branch_id == branch_id,
                (ScheduleBlock.barber_id.is_(None)) | (ScheduleBlock.barber_id == barber_id),
                ScheduleBlock.starts_at < ends_at,
                ScheduleBlock.ends_at > starts_at,
            )
        )
    )


def scheduled_statuses() -> list[str]:
    return [
        AppointmentStatus.PENDING.value,
        AppointmentStatus.CONFIRMED.value,
        AppointmentStatus.CHECKED_IN.value,
        AppointmentStatus.RESCHEDULED.value,
    ]


def append_internal_note(appointment: Appointment, note: str) -> None:
    previous = (appointment.internal_notes or "").strip()
    appointment.internal_notes = f"{previous}\n{note}".strip() if previous else note


def branch_service_or_error(branch_id: int, service_id: int) -> Service:
    service = db.session.get(Service, service_id)
    if not service or not service.is_active:
        raise ValueError("Servicio invalido.")
    link = db.session.scalar(
        db.select(BranchService).where(
            BranchService.branch_id == branch_id,
            BranchService.service_id == service_id,
            BranchService.is_active.is_(True),
        )
    )
    if not link:
        raise ValueError("El servicio no esta disponible en esa sucursal.")
    return service


def can_manage_branch(branch_id: int) -> bool:
    user = current_user()
    return not (user and user.role == Role.RECEPCION.value and user.branch_id and branch_id != user.branch_id)


def find_date_closure(branch_id: int, target_date: date) -> BranchDateClosure | None:
    return db.session.scalar(
        db.select(BranchDateClosure).where(
            BranchDateClosure.branch_id == branch_id,
            BranchDateClosure.date == target_date,
        )
    )


def active_date_closures_query(branch_id: int | None = None):
    query = db.select(BranchDateClosure).where(BranchDateClosure.is_active.is_(True))
    if branch_id:
        query = query.where(BranchDateClosure.branch_id == branch_id)
    return query.order_by(BranchDateClosure.date)


@public_availability_bp.get("/availability")
def availability():
    payload = request.args.to_dict()
    payload["extra_service_ids"] = request.args.getlist("extra_service_ids")
    try:
        return get_public_availability(payload)
    except MissingBranchServices as exc:
        return {
            "message": str(exc),
            "code": "service_missing_in_branch",
            "missing_services": exc.services,
        }, 409
    except (KeyError, ValueError, AppointmentValidationError) as exc:
        return {"message": str(exc)}, 400


@public_availability_bp.get("/availability-summary")
def availability_summary():
    payload = request.args.to_dict()
    payload["extra_service_ids"] = request.args.getlist("extra_service_ids")
    try:
        return get_public_availability_summary(payload)
    except MissingBranchServices as exc:
        return {
            "message": str(exc),
            "code": "service_missing_in_branch",
            "missing_services": exc.services,
        }, 409
    except (KeyError, ValueError, AppointmentValidationError) as exc:
        return {"message": str(exc)}, 400


@public_availability_bp.get("/date-closures")
def public_date_closures():
    branch_id = request.args.get("branch_id", type=int)
    if not branch_id:
        return {"items": []}
    items = db.session.scalars(active_date_closures_query(branch_id)).all()
    return {"items": [date_closure_to_dict(item) for item in items]}


@public_appointments_bp.post("/appointments")
def public_create_appointment():
    payload = get_json_payload()
    try:
        appointment = create_appointment_atomic(payload)
        db.session.commit()
        return {"appointment": appointment_to_dict(appointment)}, 201
    except AppointmentConflict as exc:
        db.session.rollback()
        return {"message": str(exc)}, 409
    except (KeyError, ValueError, AppointmentValidationError) as exc:
        db.session.rollback()
        return {"message": str(exc)}, 400


@appointments_bp.get("")
@roles_required([Role.ADMIN, Role.RECEPCION, Role.BARBERO])
def list_appointments():
    user = current_user()
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    overdue = db.session.scalars(
        db.select(Appointment).where(
            Appointment.ends_at < today_start,
            Appointment.status.in_(
                [
                    AppointmentStatus.PENDING.value,
                    AppointmentStatus.CONFIRMED.value,
                ]
            ),
        )
    ).all()
    for appointment in overdue:
        appointment.status = AppointmentStatus.NO_SHOW.value
    if overdue:
        db.session.commit()
    query = db.select(Appointment)
    if request.args.get("branch_id"):
        query = query.where(Appointment.branch_id == int(request.args["branch_id"]))
    elif user and user.role == Role.RECEPCION.value and user.branch_id:
        query = query.where(Appointment.branch_id == user.branch_id)
    if request.args.get("barber_id"):
        query = query.where(Appointment.barber_id == int(request.args["barber_id"]))
    if request.args.get("status"):
        query = query.where(Appointment.status == request.args["status"])
    if request.args.get("from"):
        query = query.where(Appointment.starts_at >= datetime.fromisoformat(request.args["from"]))
    if request.args.get("to"):
        query = query.where(Appointment.starts_at <= datetime.fromisoformat(request.args["to"]))
    return {"items": [appointment_to_dict(item) for item in db.session.scalars(query.order_by(Appointment.starts_at)).all()]}


@appointments_bp.get("/reprogramming")
@roles_required([Role.ADMIN, Role.RECEPCION])
def list_reprogramming():
    user = current_user()
    query = db.select(Appointment).where(Appointment.status == AppointmentStatus.PENDING_RESCHEDULE.value)
    if request.args.get("branch_id"):
        branch_id = int(request.args["branch_id"])
        if not can_manage_branch(branch_id):
            return {"message": "Recepcion solo puede ver su sucursal."}, 403
        query = query.where(Appointment.branch_id == branch_id)
    elif user and user.role == Role.RECEPCION.value and user.branch_id:
        query = query.where(Appointment.branch_id == user.branch_id)
    return {"items": [appointment_to_dict(item) for item in db.session.scalars(query.order_by(Appointment.starts_at)).all()]}


@appointments_bp.get("/date-closures")
@roles_required([Role.ADMIN, Role.RECEPCION])
def list_date_closures():
    user = current_user()
    branch_id = request.args.get("branch_id", type=int)
    if branch_id and not can_manage_branch(branch_id):
        return {"message": "Recepcion solo puede ver su sucursal."}, 403
    if not branch_id and user and user.role == Role.RECEPCION.value:
        branch_id = user.branch_id
    items = db.session.scalars(active_date_closures_query(branch_id)).all()
    return {"items": [date_closure_to_dict(item) for item in items]}


@appointments_bp.patch("/date-closures/reopen")
@roles_required([Role.ADMIN, Role.RECEPCION])
def reopen_date_closure():
    payload = get_json_payload()
    branch_id = int(payload.get("branch_id") or 0)
    if not branch_id:
        return {"message": "Sucursal requerida."}, 400
    if not can_manage_branch(branch_id):
        return {"message": "Recepcion solo puede habilitar fechas de su sucursal."}, 403
    try:
        target_date = date.fromisoformat(payload["date"])
    except (KeyError, ValueError):
        return {"message": "Fecha invalida."}, 400
    closure = find_date_closure(branch_id, target_date)
    if closure:
        closure.is_active = False
    restored = []
    if payload.get("restore_pending"):
        day_start = datetime.combine(target_date, datetime.min.time())
        day_end = day_start + timedelta(days=1)
        restored = db.session.scalars(
            db.select(Appointment).where(
                Appointment.branch_id == branch_id,
                Appointment.starts_at >= day_start,
                Appointment.starts_at < day_end,
                Appointment.status == AppointmentStatus.PENDING_RESCHEDULE.value,
            )
        ).all()
        for appointment in restored:
            appointment.status = AppointmentStatus.CONFIRMED.value
            append_internal_note(appointment, f"[Fecha habilitada] Vuelve a agenda: {target_date.isoformat()}.")
    db.session.commit()
    for appointment in restored:
        emit_appointment_event("appointment:updated", appointment)
    return {"closure": date_closure_to_dict(closure) if closure else None, "restored_count": len(restored)}


@appointments_bp.post("/reprogram-date")
@roles_required([Role.ADMIN, Role.RECEPCION])
def reprogram_date():
    payload = get_json_payload()
    branch_id = int(payload.get("branch_id") or 0)
    if not branch_id:
        return {"message": "Sucursal requerida."}, 400
    if not can_manage_branch(branch_id):
        return {"message": "Recepcion solo puede dar de baja fechas de su sucursal."}, 403
    try:
        target_date = date.fromisoformat(payload["date"])
        day_start = datetime.combine(target_date, datetime.min.time())
    except (KeyError, ValueError):
        return {"message": "Fecha invalida."}, 400
    day_end = day_start + timedelta(days=1)
    closure = find_date_closure(branch_id, target_date)
    if closure:
        closure.is_active = True
        closure.reason = payload.get("reason") or closure.reason or "Fecha dada de baja desde recepcion."
    else:
        db.session.add(
            BranchDateClosure(
                branch_id=branch_id,
                date=target_date,
                reason=payload.get("reason") or "Fecha dada de baja desde recepcion.",
                is_active=True,
                created_by_user_id=current_user().id if current_user() else None,
            )
        )
    barber_ids = [int(item) for item in payload.get("barber_ids") or []]
    query = db.select(Appointment).where(
        Appointment.branch_id == branch_id,
        Appointment.starts_at >= day_start,
        Appointment.starts_at < day_end,
        Appointment.status.in_(scheduled_statuses()),
    )
    if barber_ids:
        query = query.where(Appointment.barber_id.in_(barber_ids))
    appointments = db.session.scalars(query.order_by(Appointment.starts_at)).all()
    note = f"[A reprogramar] Fecha dada de baja: {payload['date']}."
    for appointment in appointments:
        appointment.status = AppointmentStatus.PENDING_RESCHEDULE.value
        append_internal_note(appointment, note)
    db.session.commit()
    for appointment in appointments:
        emit_appointment_event("appointment:updated", appointment)
    return {"count": len(appointments), "items": [appointment_to_dict(item) for item in appointments]}


@appointments_bp.post("")
@roles_required([Role.ADMIN, Role.RECEPCION])
def create_appointment():
    payload = get_json_payload()
    user = current_user()
    if user and user.role == Role.RECEPCION.value and user.branch_id:
        if int(payload.get("branch_id") or 0) != user.branch_id:
            return {"message": "Recepcion solo puede crear turnos en su sucursal."}, 403
    try:
        appointment = create_appointment_atomic(
            payload | {"source": "reception"},
            created_by_user_id=user.id if user else None,
            allow_force_unavailable=True,
        )
        db.session.commit()
        return {"appointment": appointment_to_dict(appointment)}, 201
    except AppointmentConflict as exc:
        db.session.rollback()
        return {"message": str(exc)}, 409
    except (KeyError, ValueError, AppointmentValidationError) as exc:
        db.session.rollback()
        return {"message": str(exc)}, 400


@appointments_bp.patch("/<int:appointment_id>")
@roles_required([Role.ADMIN, Role.RECEPCION])
def update_appointment(appointment_id):
    appointment = db.session.get(Appointment, appointment_id)
    if not appointment:
        return {"message": "Turno no encontrado."}, 404
    payload = get_json_payload()
    for field in ("status", "customer_comment", "internal_notes", "total_final"):
        if field in payload:
            setattr(appointment, field, payload[field])
    db.session.commit()
    emit_appointment_event("appointment:updated", appointment)
    return appointment_to_dict(appointment)


@appointments_bp.patch("/<int:appointment_id>/items")
@roles_required([Role.ADMIN, Role.RECEPCION])
def update_appointment_items(appointment_id):
    appointment = db.session.get(Appointment, appointment_id)
    if not appointment:
        return {"message": "Turno no encontrado."}, 404
    payload = get_json_payload()
    service_ids = [int(item) for item in payload.get("service_ids") or [] if item]
    if not service_ids:
        return {"message": "El turno debe tener al menos un servicio."}, 400
    user = current_user()
    if user and user.role == Role.RECEPCION.value and user.branch_id and appointment.branch_id != user.branch_id:
        return {"message": "Recepcion solo puede editar turnos de su sucursal."}, 403
    try:
        services = [branch_service_or_error(appointment.branch_id, service_id) for service_id in service_ids]
    except ValueError as exc:
        return {"message": str(exc)}, 400

    duration = sum(service.duration_minutes for service in services)
    new_ends_at = appointment.starts_at + timedelta(minutes=duration)
    if has_schedule_block(appointment.branch_id, appointment.barber_id, appointment.starts_at, new_ends_at):
        return {"message": "El nuevo tiempo del turno pisa un bloqueo de agenda."}, 409
    overlaps = appointment_overlaps(appointment.id, appointment.barber_id, appointment.starts_at, new_ends_at)
    if overlaps:
        return {
            "message": "El nuevo tiempo del turno se superpone con otro turno existente.",
            "code": "appointment_overlap",
            "overlaps": [appointment_to_dict(item) for item in overlaps],
        }, 409
    if not barber_is_available(
        appointment.branch_id,
        appointment.barber_id,
        appointment.starts_at,
        new_ends_at,
        appointment.id,
    ):
        return {"message": "El nuevo tiempo del turno queda fuera de la disponibilidad del barbero o sucursal."}, 409

    appointment.primary_service_id = services[0].id
    total = sum(Decimal(str(service.price)) for service in services)
    total_final = Decimal(str(payload.get("total_final", total)))
    if total_final < total and not (user and (user.role == Role.ADMIN.value or user.can_apply_discounts)):
        return {"message": "No tenes permiso para aplicar descuentos."}, 403
    appointment.ends_at = new_ends_at
    appointment.total_estimated = total
    appointment.total_final = total_final

    existing = db.session.scalars(
        db.select(AppointmentExtraService).where(AppointmentExtraService.appointment_id == appointment.id)
    ).all()
    for extra in existing:
        db.session.delete(extra)
    db.session.flush()
    for service in services[1:]:
        db.session.add(
            AppointmentExtraService(
                appointment_id=appointment.id,
                service_id=service.id,
                price_at_booking=service.price,
                duration_minutes_at_booking=service.duration_minutes,
            )
        )
    db.session.commit()
    emit_appointment_event("appointment:updated", appointment)
    return appointment_to_dict(appointment)


@appointments_bp.patch("/<int:appointment_id>/reschedule")
@roles_required([Role.ADMIN, Role.RECEPCION])
def reschedule_appointment(appointment_id):
    appointment = db.session.get(Appointment, appointment_id)
    if not appointment:
        return {"message": "Turno no encontrado."}, 404
    payload = get_json_payload()
    user = current_user()
    starts_at = parse_date_time(payload)
    duration = appointment.ends_at - appointment.starts_at
    previous_branch_id = appointment.branch_id
    previous_barber_id = appointment.barber_id
    barber_id = int(payload.get("barber_id") or appointment.barber_id)
    branch_id = int(payload.get("branch_id") or appointment.branch_id)
    if user and user.role == Role.RECEPCION.value and user.branch_id:
        if appointment.branch_id != user.branch_id or branch_id != user.branch_id:
            return {"message": "Recepcion solo puede mover turnos dentro de su sucursal."}, 403
    if has_schedule_block(branch_id, barber_id, starts_at, starts_at + duration):
        return {"message": "Ese horario tiene un bloqueo real de agenda."}, 409
    overlaps = appointment_overlaps(appointment.id, barber_id, starts_at, starts_at + duration)
    if overlaps and not payload.get("force_overlap"):
        return {
            "message": "Este turno se superpone con otro turno existente. ¿Querés confirmar igual o volver atrás?",
            "code": "appointment_overlap",
            "overlaps": [appointment_to_dict(item) for item in overlaps],
        }, 409
    if not payload.get("force_overlap") and not barber_is_available(
        branch_id,
        barber_id,
        starts_at,
        starts_at + duration,
        appointment.id,
    ):
        return {"message": "Ese horario no esta disponible para el barbero y sucursal seleccionados."}, 409
    appointment.branch_id = branch_id
    appointment.barber_id = barber_id
    appointment.starts_at = starts_at
    appointment.ends_at = starts_at + duration
    appointment.status = AppointmentStatus.RESCHEDULED.value
    db.session.commit()
    emit_appointment_event("appointment:rescheduled", appointment, previous_branch_id, previous_barber_id)
    return appointment_to_dict(appointment)


@appointments_bp.patch("/<int:appointment_id>/reprogram")
@roles_required([Role.ADMIN, Role.RECEPCION])
def reprogram_appointment(appointment_id):
    appointment = db.session.get(Appointment, appointment_id)
    if not appointment:
        return {"message": "Turno no encontrado."}, 404
    payload = get_json_payload()
    user = current_user()
    starts_at = parse_date_time(payload)
    duration = appointment.ends_at - appointment.starts_at
    previous_branch_id = appointment.branch_id
    previous_barber_id = appointment.barber_id
    barber_id = int(payload.get("barber_id") or appointment.barber_id)
    branch_id = int(payload.get("branch_id") or appointment.branch_id)
    if user and user.role == Role.RECEPCION.value and user.branch_id:
        if appointment.branch_id != user.branch_id or branch_id != user.branch_id:
            return {"message": "Recepcion solo puede reprogramar turnos dentro de su sucursal."}, 403
    if has_schedule_block(branch_id, barber_id, starts_at, starts_at + duration):
        return {"message": "Ese horario tiene un bloqueo real de agenda."}, 409
    overlaps = appointment_overlaps(appointment.id, barber_id, starts_at, starts_at + duration)
    if overlaps and not payload.get("force_overlap"):
        return {
            "message": "Este turno se superpone con otro turno existente.",
            "code": "appointment_overlap",
            "overlaps": [appointment_to_dict(item) for item in overlaps],
        }, 409
    if not payload.get("force_overlap") and not barber_is_available(
        branch_id,
        barber_id,
        starts_at,
        starts_at + duration,
        appointment.id,
    ):
        return {"message": "Ese horario no esta disponible para el barbero y sucursal seleccionados."}, 409
    if payload.get("internal_notes"):
        append_internal_note(appointment, f"[Reprogramacion] {payload['internal_notes']}")
    appointment.branch_id = branch_id
    appointment.barber_id = barber_id
    appointment.starts_at = starts_at
    appointment.ends_at = starts_at + duration
    appointment.status = AppointmentStatus.RESCHEDULED.value
    db.session.commit()
    emit_appointment_event("appointment:rescheduled", appointment, previous_branch_id, previous_barber_id)
    return appointment_to_dict(appointment)


@appointments_bp.patch("/<int:appointment_id>/check-in")
@roles_required([Role.ADMIN, Role.RECEPCION, Role.BARBERO])
def check_in_appointment(appointment_id):
    appointment = db.session.get(Appointment, appointment_id)
    if not appointment:
        return {"message": "Turno no encontrado."}, 404
    appointment.status = AppointmentStatus.CHECKED_IN.value
    completed = auto_complete_appointment_if_ready(appointment)
    db.session.commit()
    if completed:
        emit_appointment_event("appointment:completed", appointment)
    else:
        emit_appointment_event("appointment:updated", appointment)
    return appointment_to_dict(appointment)


@appointments_bp.patch("/<int:appointment_id>/no-show")
@roles_required([Role.ADMIN, Role.RECEPCION])
def no_show_appointment(appointment_id):
    appointment = db.session.get(Appointment, appointment_id)
    if not appointment:
        return {"message": "Turno no encontrado."}, 404
    appointment.status = AppointmentStatus.NO_SHOW.value
    db.session.commit()
    emit_appointment_event("appointment:updated", appointment)
    return appointment_to_dict(appointment)


@appointments_bp.patch("/<int:appointment_id>/cancel")
@roles_required([Role.ADMIN, Role.RECEPCION])
def cancel_appointment(appointment_id):
    appointment = db.session.get(Appointment, appointment_id)
    if not appointment:
        return {"message": "Turno no encontrado."}, 404
    appointment.status = AppointmentStatus.CANCELLED.value
    appointment.cancellation_reason = get_json_payload().get("cancellation_reason")
    db.session.commit()
    emit_appointment_event("appointment:cancelled", appointment)
    return appointment_to_dict(appointment)


@appointments_bp.patch("/<int:appointment_id>/complete")
@roles_required([Role.ADMIN, Role.RECEPCION, Role.BARBERO])
def complete_appointment(appointment_id):
    appointment = db.session.get(Appointment, appointment_id)
    if not appointment:
        return {"message": "Turno no encontrado."}, 404
    appointment.status = AppointmentStatus.COMPLETED.value
    db.session.commit()
    emit_appointment_event("appointment:completed", appointment)
    return appointment_to_dict(appointment)


@barber_me_bp.get("/me/appointments")
@roles_required([Role.BARBERO])
def barber_me_appointments():
    user = current_user()
    if not user:
        return {"items": []}
    # The user_id to barber_id mapping is direct in this initial schema.
    barber = db.session.scalar(db.select(Barber).where(Barber.user_id == user.id))
    if not barber:
        return {"items": []}
    items = db.session.scalars(
        db.select(Appointment).where(Appointment.barber_id == barber.id)
    ).all()
    return {"items": [appointment_to_dict(item) for item in items]}


@client_me_bp.get("/me/appointments")
@login_required
def client_me_appointments():
    user = current_user()
    if not user:
        return {"items": []}
    client_query = db.select(Client).where(Client.email == user.email)
    if user.google_account_id:
        client_query = db.select(Client).where(
            (Client.email == user.email) | (Client.google_account_id == user.google_account_id)
        )
    client = db.session.scalar(client_query)
    if not client:
        return {"items": []}
    items = db.session.scalars(db.select(Appointment).where(Appointment.client_id == client.id)).all()
    return {"items": [appointment_to_dict(item) for item in items]}


@client_me_bp.patch("/me/appointments/<int:appointment_id>/cancel")
@login_required
def client_cancel_appointment(appointment_id):
    user = current_user()
    if not user:
        return {"message": "Usuario no encontrado."}, 404
    client_query = db.select(Client).where(Client.email == user.email)
    if user.google_account_id:
        client_query = db.select(Client).where(
            (Client.email == user.email) | (Client.google_account_id == user.google_account_id)
        )
    client = db.session.scalar(client_query)
    if not client:
        return {"message": "Cliente no encontrado."}, 404
    appointment = db.session.get(Appointment, appointment_id)
    if not appointment or appointment.client_id != client.id:
        return {"message": "Turno no encontrado."}, 404
    if appointment.status in (
        AppointmentStatus.COMPLETED.value,
        AppointmentStatus.CANCELLED.value,
        AppointmentStatus.NO_SHOW.value,
    ):
        return {"message": "Este turno ya no se puede cancelar."}, 409
    appointment.status = AppointmentStatus.CANCELLED.value
    appointment.cancellation_reason = "Cancelado por el cliente desde su panel."
    append_internal_note(appointment, "[Cancelacion cliente] Cancelado desde panel cliente.")
    db.session.commit()
    emit_appointment_event("appointment:cancelled", appointment)
    return appointment_to_dict(appointment)


@appointments_bp.get("/<int:appointment_id>/calendar.ics")
def calendar_ics(appointment_id):
    appointment = db.session.get(Appointment, appointment_id)
    if not appointment:
        return {"message": "Turno no encontrado."}, 404
    body = "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//NUB System//Appointments//ES",
            "BEGIN:VEVENT",
            f"UID:nub-appointment-{appointment.id}",
            f"DTSTART:{appointment.starts_at.strftime('%Y%m%dT%H%M%S')}",
            f"DTEND:{appointment.ends_at.strftime('%Y%m%dT%H%M%S')}",
            "SUMMARY:Turno NUB System",
            "END:VEVENT",
            "END:VCALENDAR",
        ]
    )
    return Response(body, mimetype="text/calendar")
