from datetime import datetime

from flask import Blueprint

from app.constants import AppointmentStatus, Role, StockMovementType
from app.extensions import db
from app.modules.appointments.models import Appointment, BarberAvailability, ScheduleBlock
from app.modules.barbers.models import Barber, BarberBranch
from app.modules.branches.models import Branch
from app.modules.inventory.models import BranchProductStock, StockMovement
from app.modules.products.models import Product
from app.modules.services.models import BranchService, Service
from app.security import roles_required
from app.services.appointment_service import barber_is_available
from app.utils.http import get_json_payload, model_to_dict

admin_migrations_bp = Blueprint("admin_migrations", __name__)

ACTIVE_STATUSES = (
    AppointmentStatus.PENDING.value,
    AppointmentStatus.CONFIRMED.value,
    AppointmentStatus.CHECKED_IN.value,
    AppointmentStatus.RESCHEDULED.value,
)


def _append_note(appointment: Appointment, note: str) -> None:
    previous = (appointment.internal_notes or "").strip()
    appointment.internal_notes = f"{previous}\n{note}".strip() if previous else note


def _set_branch_link(model, entity_field: str, entity_id: int, branch_id: int, active: bool = True):
    link = db.session.scalar(
        db.select(model).where(
            getattr(model, entity_field) == entity_id,
            model.branch_id == branch_id,
        )
    )
    if link:
        link.is_active = active
    else:
        link = model(**{entity_field: entity_id, "branch_id": branch_id, "is_active": active})
        db.session.add(link)
    return link


def _branch_schedule_to_availability(branch: Branch, barber_id: int) -> None:
    # If the barber has no explicit hours in the target branch, the app uses the
    # branch schedule as fallback. These rows make that default visible/editable.
    existing = db.session.scalar(
        db.select(BarberAvailability.id).where(
            BarberAvailability.branch_id == branch.id,
            BarberAvailability.barber_id == barber_id,
            BarberAvailability.is_active.is_(True),
        )
    )
    if existing:
        return
    import json

    weekdays = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    try:
        schedule = json.loads(branch.opening_hours or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        schedule = {}
    for weekday, key in enumerate(weekdays):
        day = schedule.get(key)
        if not isinstance(day, dict) or not day.get("enabled", True):
            continue
        start_time = day.get("from")
        end_time = day.get("to")
        if not start_time or not end_time:
            continue
        db.session.add(
            BarberAvailability(
                barber_id=barber_id,
                branch_id=branch.id,
                weekday=weekday,
                start_time=start_time,
                end_time=end_time,
                is_active=True,
            )
        )


@admin_migrations_bp.get("/migrations")
@roles_required([Role.ADMIN])
def migration_overview():
    branches = db.session.scalars(db.select(Branch).where(Branch.is_active.is_(True))).all()
    items = []
    for branch in branches:
        barbers = db.session.execute(
            db.select(Barber)
            .join(BarberBranch, BarberBranch.barber_id == Barber.id)
            .where(BarberBranch.branch_id == branch.id, BarberBranch.is_active.is_(True), Barber.is_active.is_(True))
        ).scalars().all()
        services = db.session.execute(
            db.select(Service)
            .join(BranchService, BranchService.service_id == Service.id)
            .where(BranchService.branch_id == branch.id, BranchService.is_active.is_(True), Service.is_active.is_(True))
        ).scalars().all()
        product_rows = db.session.execute(
            db.select(Product, BranchProductStock)
            .join(BranchProductStock, BranchProductStock.product_id == Product.id)
            .where(BranchProductStock.branch_id == branch.id, Product.is_active.is_(True))
        ).all()
        items.append(
            model_to_dict(branch)
            | {
                "barbers": [model_to_dict(item) for item in barbers],
                "services": [model_to_dict(item) for item in services],
                "products": [
                    model_to_dict(product) | {"stock": model_to_dict(stock)}
                    for product, stock in product_rows
                ],
            }
        )
    return {"items": items}


@admin_migrations_bp.post("/migrations/services")
@roles_required([Role.ADMIN])
def migrate_service():
    payload = get_json_payload()
    service_id = int(payload["service_id"])
    target_branch_id = int(payload["target_branch_id"])
    service = db.session.get(Service, service_id)
    target = db.session.get(Branch, target_branch_id)
    if not service or not service.is_active or not target or not target.is_active:
        return {"message": "Servicio o sucursal invalida."}, 400
    link = _set_branch_link(BranchService, "service_id", service_id, target_branch_id, True)
    db.session.commit()
    return {"message": "Servicio asociado.", "already_existed": link.created_at != link.updated_at}


@admin_migrations_bp.post("/migrations/products")
@roles_required([Role.ADMIN])
def migrate_product():
    payload = get_json_payload()
    product_id = int(payload["product_id"])
    target_branch_id = int(payload["target_branch_id"])
    initial_stock = int(payload.get("initial_stock", 0))
    product = db.session.get(Product, product_id)
    target = db.session.get(Branch, target_branch_id)
    if not product or not product.is_active or not target or not target.is_active:
        return {"message": "Producto o sucursal invalida."}, 400
    stock = db.session.scalar(
        db.select(BranchProductStock).where(
            BranchProductStock.branch_id == target_branch_id,
            BranchProductStock.product_id == product_id,
        )
    )
    already = bool(stock)
    if not stock:
        stock = BranchProductStock(branch_id=target_branch_id, product_id=product_id, current_stock=initial_stock)
        db.session.add(stock)
        if initial_stock:
            db.session.add(
                StockMovement(
                    branch_id=target_branch_id,
                    product_id=product_id,
                    movement_type=StockMovementType.ADJUSTMENT.value,
                    quantity=initial_stock,
                    reason="Stock inicial por migracion",
                )
            )
    db.session.commit()
    return {"message": "Producto asociado.", "already_existed": already, "stock": model_to_dict(stock)}


@admin_migrations_bp.post("/migrations/barbers")
@roles_required([Role.ADMIN])
def migrate_barber():
    payload = get_json_payload()
    barber_id = int(payload["barber_id"])
    source_branch_id = int(payload["source_branch_id"])
    target_branch_id = int(payload["target_branch_id"])
    mode = payload.get("mode", "with_turns")
    turn_action = payload.get("turn_action", "reprogram_source")
    target_barber_id = int(payload["target_barber_id"]) if payload.get("target_barber_id") else None
    barber = db.session.get(Barber, barber_id)
    target = db.session.get(Branch, target_branch_id)
    if not barber or not barber.is_active or not target or not target.is_active or source_branch_id == target_branch_id:
        return {"message": "Migracion invalida."}, 400

    _set_branch_link(BarberBranch, "barber_id", barber_id, target_branch_id, True)
    source_link = db.session.scalar(
        db.select(BarberBranch).where(BarberBranch.barber_id == barber_id, BarberBranch.branch_id == source_branch_id)
    )
    if source_link:
        source_link.is_active = False
    _branch_schedule_to_availability(target, barber_id)

    future = db.session.scalars(
        db.select(Appointment).where(
            Appointment.branch_id == source_branch_id,
            Appointment.barber_id == barber_id,
            Appointment.starts_at >= datetime.utcnow(),
            Appointment.status.in_(ACTIVE_STATUSES),
        )
    ).all()

    moved = 0
    reprogrammed = 0
    transferred = 0
    for appointment in future:
        duration_end = appointment.ends_at
        if mode == "with_turns":
            appointment.branch_id = target_branch_id
            if barber_is_available(target_branch_id, barber_id, appointment.starts_at, duration_end, appointment.id):
                moved += 1
            else:
                appointment.status = AppointmentStatus.PENDING_RESCHEDULE.value
                _append_note(appointment, "[A reprogramar] Migracion de barbero: horario no disponible en destino.")
                reprogrammed += 1
            continue

        if turn_action == "reprogram_target":
            appointment.branch_id = target_branch_id
            appointment.status = AppointmentStatus.PENDING_RESCHEDULE.value
            _append_note(appointment, "[A reprogramar] Barbero migrado sin turnos; pendiente en sucursal destino.")
            reprogrammed += 1
        elif turn_action == "transfer" and target_barber_id:
            if barber_is_available(source_branch_id, target_barber_id, appointment.starts_at, duration_end, appointment.id):
                appointment.barber_id = target_barber_id
                transferred += 1
            else:
                appointment.status = AppointmentStatus.PENDING_RESCHEDULE.value
                _append_note(appointment, "[A reprogramar] Transferencia fallida por disponibilidad del barbero destino.")
                reprogrammed += 1
        else:
            appointment.status = AppointmentStatus.PENDING_RESCHEDULE.value
            _append_note(appointment, "[A reprogramar] Barbero migrado sin turnos; pendiente en sucursal original.")
            reprogrammed += 1

    db.session.commit()
    return {"message": "Barbero migrado.", "moved": moved, "reprogrammed": reprogrammed, "transferred": transferred}


@admin_migrations_bp.post("/migrations/barbers/preview")
@roles_required([Role.ADMIN])
def preview_barber_migration():
    payload = get_json_payload()
    barber_id = int(payload["barber_id"])
    source_branch_id = int(payload["source_branch_id"])
    target_branch_id = int(payload["target_branch_id"])
    future = db.session.scalars(
        db.select(Appointment).where(
            Appointment.branch_id == source_branch_id,
            Appointment.barber_id == barber_id,
            Appointment.starts_at >= datetime.utcnow(),
            Appointment.status.in_(ACTIVE_STATUSES),
        )
    ).all()
    movable = 0
    conflicts = []
    for appointment in future:
        if barber_is_available(target_branch_id, barber_id, appointment.starts_at, appointment.ends_at, appointment.id):
            movable += 1
        else:
            conflicts.append(model_to_dict(appointment))
    return {"future_count": len(future), "movable_count": movable, "conflict_count": len(conflicts), "conflicts": conflicts}


@admin_migrations_bp.get("/barber-availabilities")
@roles_required([Role.ADMIN, Role.RECEPCION])
def list_barber_availabilities():
    from flask import request

    branch_id = request.args.get("branch_id", type=int)
    barber_id = request.args.get("barber_id", type=int)
    query = db.select(BarberAvailability).where(BarberAvailability.is_active.is_(True))
    if branch_id:
        query = query.where(BarberAvailability.branch_id == branch_id)
    if barber_id:
        query = query.where(BarberAvailability.barber_id == barber_id)
    rows = db.session.scalars(query).all()
    return {"items": [model_to_dict(item) for item in rows]}


@admin_migrations_bp.post("/barbers/<int:barber_id>/availability")
@roles_required([Role.ADMIN])
def set_barber_availability(barber_id):
    payload = get_json_payload()
    branch_id = int(payload["branch_id"])
    existing = db.session.scalars(
        db.select(BarberAvailability).where(
            BarberAvailability.barber_id == barber_id,
            BarberAvailability.branch_id == branch_id,
        )
    ).all()
    for row in existing:
        row.is_active = False
    if not payload.get("use_full_schedule"):
        for item in payload.get("items", []):
            if not item.get("enabled", True):
                continue
            db.session.add(
                BarberAvailability(
                    barber_id=barber_id,
                    branch_id=branch_id,
                    weekday=int(item["weekday"]),
                    start_time=item["start_time"],
                    end_time=item["end_time"],
                    is_active=True,
                )
            )
    db.session.commit()
    return list_barber_availabilities()


@admin_migrations_bp.get("/schedule-blocks")
@roles_required([Role.ADMIN, Role.RECEPCION])
def list_schedule_blocks():
    from flask import request

    branch_id = request.args.get("branch_id", type=int)
    query = db.select(ScheduleBlock)
    if branch_id:
        query = query.where(ScheduleBlock.branch_id == branch_id)
    blocks = db.session.scalars(query.order_by(ScheduleBlock.starts_at)).all()
    return {"items": [model_to_dict(item) for item in blocks]}


@admin_migrations_bp.post("/schedule-blocks")
@roles_required([Role.ADMIN])
def create_schedule_block():
    payload = get_json_payload()
    branch_id = int(payload["branch_id"])
    barber_id = int(payload["barber_id"]) if payload.get("barber_id") else None
    starts_at = datetime.fromisoformat(payload["starts_at"])
    ends_at = datetime.fromisoformat(payload["ends_at"])
    if ends_at <= starts_at:
        return {"message": "El fin del bloqueo debe ser posterior al inicio."}, 400
    block = ScheduleBlock(
        branch_id=branch_id,
        barber_id=barber_id,
        starts_at=starts_at,
        ends_at=ends_at,
        reason=payload.get("reason"),
    )
    db.session.add(block)
    query = db.select(Appointment).where(
        Appointment.branch_id == branch_id,
        Appointment.starts_at < ends_at,
        Appointment.ends_at > starts_at,
        Appointment.status.in_(ACTIVE_STATUSES),
    )
    if barber_id:
        query = query.where(Appointment.barber_id == barber_id)
    affected = db.session.scalars(query).all()
    for appointment in affected:
        appointment.status = AppointmentStatus.PENDING_RESCHEDULE.value
        _append_note(appointment, f"[A reprogramar] Bloqueo de agenda: {payload.get('reason') or 'sin motivo'}.")
    db.session.commit()
    return {"block": model_to_dict(block), "affected_count": len(affected)}
