import json

from flask import Blueprint
from sqlalchemy import func

from app.constants import AppointmentStatus, Role
from app.extensions import db
from app.live import appointment_room, emit_live_event
from app.modules.appointments.models import Appointment
from app.modules.barbers.models import BarberBranch
from app.modules.branches.models import Branch
from app.security import roles_required
from app.utils.http import get_json_payload, list_response, model_to_dict

public_branches_bp = Blueprint("public_branches", __name__)
admin_branches_bp = Blueprint("admin_branches", __name__)

WEEKDAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
REPROGRAM_ON_MIGRATION_STATUSES = {
    AppointmentStatus.PENDING.value,
    AppointmentStatus.CONFIRMED.value,
    AppointmentStatus.CHECKED_IN.value,
    AppointmentStatus.RESCHEDULED.value,
}


def _time_to_minutes(value):
    if not isinstance(value, str) or ":" not in value:
        return None
    try:
        hours, minutes = value.split(":", 1)
        return int(hours) * 60 + int(minutes)
    except (TypeError, ValueError):
        return None


def _branch_schedule(branch):
    if not branch.opening_hours:
        return None
    if isinstance(branch.opening_hours, dict):
        return branch.opening_hours
    try:
        schedule = json.loads(branch.opening_hours)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return schedule if isinstance(schedule, dict) else None


def _outside_branch_hours(appointment, branch):
    schedule = _branch_schedule(branch)
    if not schedule:
        return False
    day_config = schedule.get(WEEKDAY_KEYS[appointment.starts_at.weekday()])
    if not isinstance(day_config, dict) or not day_config.get("enabled"):
        return True
    branch_start = _time_to_minutes(day_config.get("from"))
    branch_end = _time_to_minutes(day_config.get("to"))
    if branch_start is None or branch_end is None:
        return False
    appointment_start = appointment.starts_at.hour * 60 + appointment.starts_at.minute
    appointment_end = appointment.ends_at.hour * 60 + appointment.ends_at.minute
    return appointment_start < branch_start or appointment_end > branch_end


def _append_internal_note(appointment, note):
    appointment.internal_notes = f"{appointment.internal_notes}\n{note}" if appointment.internal_notes else note


def _emit_appointment_updated(appointment, previous_branch_id=None):
    rooms = set(appointment_room(appointment.branch_id, appointment.barber_id, appointment.client_id))
    if previous_branch_id and previous_branch_id != appointment.branch_id:
        rooms.update(appointment_room(previous_branch_id, None, appointment.client_id))
    payload = model_to_dict(appointment)
    for room in rooms:
        emit_live_event("appointment:updated", payload, room=room)


@public_branches_bp.get("/branches")
def public_branches():
    items = db.session.scalars(db.select(Branch).where(Branch.is_active.is_(True))).all()
    return list_response(items)


@admin_branches_bp.get("/branches")
@roles_required([Role.ADMIN])
def admin_branches():
    branches = db.session.scalars(db.select(Branch)).all()
    items = []
    for branch in branches:
        barber_count = db.session.scalar(
            db.select(func.count(BarberBranch.id)).where(
                BarberBranch.branch_id == branch.id,
                BarberBranch.is_active.is_(True),
            )
        )
        appointment_count = db.session.scalar(
            db.select(func.count(Appointment.id)).where(Appointment.branch_id == branch.id)
        )
        items.append(
            model_to_dict(branch)
            | {
                "barber_count": barber_count or 0,
                "appointment_count": appointment_count or 0,
            }
        )
    return {"items": items}


@admin_branches_bp.post("/branches")
@roles_required([Role.ADMIN])
def create_branch():
    payload = get_json_payload()
    existing = db.session.scalar(
        db.select(Branch).where(
            func.lower(Branch.name) == str(payload["name"]).strip().lower(),
            func.lower(Branch.address) == str(payload["address"]).strip().lower(),
            Branch.is_active.is_(True),
        )
    )
    if existing:
        return {"message": "Ya existe una sucursal activa con ese nombre y direccion."}, 409
    branch = Branch(
        name=str(payload["name"]).strip(),
        address=str(payload["address"]).strip(),
        phone=payload.get("phone"),
        email=payload.get("email"),
        description=payload.get("description"),
        image_url=payload.get("image_url"),
        opening_hours=payload.get("opening_hours"),
    )
    db.session.add(branch)
    db.session.commit()
    return model_to_dict(branch), 201


@admin_branches_bp.patch("/branches/<int:branch_id>")
@roles_required([Role.ADMIN])
def update_branch(branch_id):
    branch = db.session.get(Branch, branch_id)
    if not branch:
        return {"message": "Sucursal no encontrada."}, 404
    payload = get_json_payload()
    next_name = str(payload.get("name", branch.name)).strip()
    next_address = str(payload.get("address", branch.address)).strip()
    existing = db.session.scalar(
        db.select(Branch).where(
            Branch.id != branch.id,
            func.lower(Branch.name) == next_name.lower(),
            func.lower(Branch.address) == next_address.lower(),
            Branch.is_active.is_(True),
        )
    )
    if existing:
        return {"message": "Ya existe una sucursal activa con ese nombre y direccion."}, 409
    for field in ("name", "address", "phone", "email", "description", "image_url", "opening_hours"):
        if field in payload:
            setattr(branch, field, payload[field])
    branch.name = next_name
    branch.address = next_address
    db.session.commit()
    return model_to_dict(branch)


@admin_branches_bp.patch("/branches/<int:branch_id>/disable")
@roles_required([Role.ADMIN])
def disable_branch(branch_id):
    branch = db.session.get(Branch, branch_id)
    if not branch:
        return {"message": "Sucursal no encontrada."}, 404
    branch.is_active = False
    db.session.commit()
    return model_to_dict(branch)


@admin_branches_bp.delete("/branches/<int:branch_id>")
@roles_required([Role.ADMIN])
def delete_branch(branch_id):
    branch = db.session.get(Branch, branch_id)
    if not branch:
        return {"message": "Sucursal no encontrada."}, 404
    payload = get_json_payload()
    target_branch_id = payload.get("target_branch_id")
    active_barber_links = db.session.scalars(
        db.select(BarberBranch).where(
            BarberBranch.branch_id == branch_id,
            BarberBranch.is_active.is_(True),
        )
    ).all()
    appointments = db.session.scalars(
        db.select(Appointment).where(Appointment.branch_id == branch_id)
    ).all()

    if (active_barber_links or appointments) and not target_branch_id:
        return {
            "message": "La sucursal tiene barberos o turnos asociados. Migralos a otra sucursal o desasocialos antes de eliminar.",
            "barber_count": len(active_barber_links),
            "appointment_count": len(appointments),
        }, 409

    if target_branch_id:
        target = db.session.get(Branch, int(target_branch_id))
        if not target or not target.is_active or target.id == branch_id:
            return {"message": "Sucursal destino invalida."}, 400
        reprogrammed_count = 0
        for link in active_barber_links:
            existing = db.session.scalar(
                db.select(BarberBranch).where(
                    BarberBranch.barber_id == link.barber_id,
                    BarberBranch.branch_id == target.id,
                )
            )
            if existing:
                existing.is_active = True
            else:
                db.session.add(
                    BarberBranch(
                        barber_id=link.barber_id,
                        branch_id=target.id,
                        is_active=True,
                    )
                )
            link.is_active = False
        touched_appointments = []
        for appointment in appointments:
            previous_branch_id = appointment.branch_id
            appointment.branch_id = target.id
            if (
                appointment.status in REPROGRAM_ON_MIGRATION_STATUSES
                and _outside_branch_hours(appointment, target)
            ):
                appointment.status = AppointmentStatus.PENDING_RESCHEDULE.value
                _append_internal_note(
                    appointment,
                    f"[A reprogramar] Migrado a {target.name}; fuera del horario de la sucursal destino.",
                )
                reprogrammed_count += 1
            touched_appointments.append((appointment, previous_branch_id))
    elif active_barber_links:
        reprogrammed_count = 0
        touched_appointments = []
        for link in active_barber_links:
            link.is_active = False
    else:
        reprogrammed_count = 0
        touched_appointments = []

    branch.is_active = False
    db.session.commit()
    for appointment, previous_branch_id in touched_appointments:
        _emit_appointment_updated(appointment, previous_branch_id)
    return {
        "message": "Sucursal desactivada.",
        "branch": model_to_dict(branch),
        "reprogrammed_count": reprogrammed_count,
    }
