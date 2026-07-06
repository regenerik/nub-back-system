import json
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import and_, func, or_

from app.constants import AppointmentSource, AppointmentStatus, ServiceType
from app.extensions import db
from app.live import appointment_room, emit_live_event
from app.modules.appointments.models import (
    Appointment,
    AppointmentExtraService,
    BarberAvailability,
    BranchDateClosure,
    ScheduleBlock,
)
from app.modules.barbers.models import Barber, BarberBranch
from app.modules.branches.models import Branch
from app.modules.clients.models import Client
from app.modules.services.models import BranchService, Service
from app.utils.http import model_to_dict, parse_date_time

BLOCKING_STATUSES = (
    AppointmentStatus.PENDING.value,
    AppointmentStatus.CONFIRMED.value,
    AppointmentStatus.CHECKED_IN.value,
    AppointmentStatus.RESCHEDULED.value,
)
WEEKDAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DEFAULT_BRANCH_SCHEDULE = {
    key: {"enabled": key != "sun", "from": "09:00", "to": "20:00"}
    for key in WEEKDAY_KEYS
}


class AppointmentConflict(Exception):
    pass


class AppointmentValidationError(Exception):
    pass


class MissingBranchServices(AppointmentValidationError):
    def __init__(self, services: list[dict]):
        super().__init__("El servicio no esta disponible en la nueva sucursal.")
        self.services = services


def _active_branch(branch_id: int) -> Branch:
    branch = db.session.get(Branch, branch_id)
    if not branch or not branch.is_active:
        raise AppointmentValidationError("La sucursal no existe o esta inactiva.")
    return branch


def _branch_service(service_id: int, branch_id: int, allowed_types: tuple[str, ...]) -> Service:
    service = db.session.get(Service, service_id)
    if not service or not service.is_active:
        raise AppointmentValidationError("El servicio no existe o esta inactivo.")
    if service.service_type not in allowed_types:
        raise AppointmentValidationError("El tipo de servicio no corresponde.")
    link = db.session.scalar(
        db.select(BranchService).where(
            BranchService.branch_id == branch_id,
            BranchService.service_id == service_id,
            BranchService.is_active.is_(True),
        )
    )
    if not link:
        raise AppointmentValidationError("El servicio no esta disponible en esa sucursal.")
    return service


def _missing_branch_services(branch_id: int, service_rules: list[tuple[int, tuple[str, ...]]]) -> list[dict]:
    missing = []
    for service_id, allowed_types in service_rules:
        service = db.session.get(Service, service_id)
        if not service or not service.is_active:
            raise AppointmentValidationError("El servicio no existe o esta inactivo.")
        if service.service_type not in allowed_types:
            raise AppointmentValidationError("El tipo de servicio no corresponde.")
        link = db.session.scalar(
            db.select(BranchService).where(
                BranchService.branch_id == branch_id,
                BranchService.service_id == service_id,
                BranchService.is_active.is_(True),
            )
        )
        if not link:
            missing.append(model_to_dict(service))
    return missing


def _barber_works_in_branch(barber_id: int, branch_id: int) -> bool:
    barber = db.session.get(Barber, barber_id)
    if not barber or not barber.is_active:
        return False
    return bool(
        db.session.scalar(
            db.select(BarberBranch).where(
                BarberBranch.barber_id == barber_id,
                BarberBranch.branch_id == branch_id,
                BarberBranch.is_active.is_(True),
            )
        )
    )


def _overlaps(barber_id: int, starts_at: datetime, ends_at: datetime, exclude_appointment_id: int | None = None) -> bool:
    query = db.select(Appointment.id).where(
        Appointment.barber_id == barber_id,
        Appointment.status.in_(BLOCKING_STATUSES),
        Appointment.starts_at < ends_at,
        Appointment.ends_at > starts_at,
    )
    if exclude_appointment_id:
        query = query.where(Appointment.id != exclude_appointment_id)
    return bool(db.session.scalar(query))


def _has_block(branch_id: int, barber_id: int, starts_at: datetime, ends_at: datetime) -> bool:
    return bool(
        db.session.scalar(
            db.select(ScheduleBlock.id).where(
                ScheduleBlock.branch_id == branch_id,
                or_(ScheduleBlock.barber_id.is_(None), ScheduleBlock.barber_id == barber_id),
                ScheduleBlock.starts_at < ends_at,
                ScheduleBlock.ends_at > starts_at,
            )
        )
    )


def _date_is_closed(branch_id: int, starts_at: datetime) -> bool:
    return bool(
        db.session.scalar(
            db.select(BranchDateClosure.id).where(
                BranchDateClosure.branch_id == branch_id,
                BranchDateClosure.date == starts_at.date(),
                BranchDateClosure.is_active.is_(True),
            )
        )
    )


def _ceil_to_quarter(value: datetime) -> datetime:
    if value.minute % 15 == 0 and value.second == 0 and value.microsecond == 0:
        return value
    minutes_to_add = 15 - (value.minute % 15)
    return (value + timedelta(minutes=minutes_to_add)).replace(second=0, microsecond=0)


def _floor_to_quarter(value: datetime) -> datetime:
    return value.replace(minute=(value.minute // 15) * 15, second=0, microsecond=0)


def _branch_day_window(branch: Branch, target_date) -> tuple[datetime, datetime] | None:
    schedule = DEFAULT_BRANCH_SCHEDULE
    if branch.opening_hours:
        try:
            parsed = json.loads(branch.opening_hours)
            if isinstance(parsed, dict):
                schedule = parsed
        except (TypeError, ValueError, json.JSONDecodeError):
            schedule = DEFAULT_BRANCH_SCHEDULE
    day = schedule.get(WEEKDAY_KEYS[target_date.weekday()])
    if not isinstance(day, dict) or not day.get("enabled", True):
        return None
    start_time = day.get("from")
    end_time = day.get("to")
    if not start_time or not end_time:
        return None
    start = datetime.fromisoformat(f"{target_date}T{start_time}")
    end = datetime.fromisoformat(f"{target_date}T{end_time}")
    return (start, end) if end > start else None


def _within_availability(
    branch_id: int, barber_id: int, starts_at: datetime, ends_at: datetime
) -> bool:
    start_text = starts_at.strftime("%H:%M")
    end_text = ends_at.strftime("%H:%M")
    availabilities = db.session.scalars(
        db.select(BarberAvailability).where(
            BarberAvailability.branch_id == branch_id,
            BarberAvailability.barber_id == barber_id,
            BarberAvailability.weekday == starts_at.weekday(),
            BarberAvailability.is_active.is_(True),
        )
    ).all()
    if availabilities:
        return any(
            availability.start_time <= start_text and availability.end_time >= end_text
            for availability in availabilities
        )
    branch = db.session.get(Branch, branch_id)
    branch_window = _branch_day_window(branch, starts_at.date()) if branch else None
    return bool(branch_window and branch_window[0] <= starts_at and branch_window[1] >= ends_at)


def barber_is_available(
    branch_id: int,
    barber_id: int,
    starts_at: datetime,
    ends_at: datetime,
    exclude_appointment_id: int | None = None,
) -> bool:
    return (
        _barber_works_in_branch(barber_id, branch_id)
        and not _date_is_closed(branch_id, starts_at)
        and _within_availability(branch_id, barber_id, starts_at, ends_at)
        and not _has_block(branch_id, barber_id, starts_at, ends_at)
        and not _overlaps(barber_id, starts_at, ends_at, exclude_appointment_id)
    )


def _candidate_barbers(branch_id: int) -> list[int]:
    rows = db.session.scalars(
        db.select(BarberBranch.barber_id).join(Barber, Barber.id == BarberBranch.barber_id).where(
            BarberBranch.branch_id == branch_id,
            BarberBranch.is_active.is_(True),
            Barber.is_active.is_(True),
        )
    ).all()
    return list(rows)


def _choose_any_barber(branch_id: int, starts_at: datetime, ends_at: datetime) -> int:
    candidates = [
        barber_id
        for barber_id in _candidate_barbers(branch_id)
        if barber_is_available(branch_id, barber_id, starts_at, ends_at)
    ]
    if not candidates:
        raise AppointmentConflict("No hay barberos disponibles para ese horario.")

    day_start = starts_at.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    scores = {}
    for barber_id in candidates:
        scores[barber_id] = db.session.scalar(
            db.select(func.count(Appointment.id)).where(
                Appointment.barber_id == barber_id,
                Appointment.starts_at >= day_start,
                Appointment.starts_at < day_end,
                Appointment.status.in_(BLOCKING_STATUSES),
            )
        )
    return min(candidates, key=lambda barber_id: scores[barber_id])


def get_public_availability(payload: dict) -> dict:
    branch_id = int(payload["branch_id"])
    service_id = int(payload["service_id"])
    extra_ids = [int(item) for item in payload.get("extra_service_ids", []) if item]
    target_date = datetime.fromisoformat(payload["date"]).date()

    branch = _active_branch(branch_id)
    if _date_is_closed(branch_id, datetime.fromisoformat(f"{target_date}T00:00:00")):
        return {"items": [], "closed": True, "message": "La fecha esta dada de baja."}
    branch_window = _branch_day_window(branch, target_date)
    if not branch_window:
        return {"items": []}
    missing_services = _missing_branch_services(
        branch_id,
        [(service_id, (ServiceType.MAIN.value, ServiceType.EXTRA.value, ServiceType.BOTH.value))]
        + [(extra_id, (ServiceType.EXTRA.value, ServiceType.BOTH.value)) for extra_id in extra_ids],
    )
    if missing_services:
        raise MissingBranchServices(missing_services)
    primary = db.session.get(Service, service_id)
    extras = [db.session.get(Service, extra_id) for extra_id in extra_ids]
    duration = primary.duration_minutes + sum(extra.duration_minutes for extra in extras)
    exclude_appointment_id = int(payload["exclude_appointment_id"]) if payload.get("exclude_appointment_id") else None

    barber_id = payload.get("barber_id")
    barber_ids = (
        [int(barber_id)]
        if barber_id and barber_id != "any"
        else _candidate_barbers(branch_id)
    )
    slots = []
    for candidate_id in barber_ids:
        availabilities = db.session.scalars(
            db.select(BarberAvailability).where(
                BarberAvailability.branch_id == branch_id,
                BarberAvailability.barber_id == candidate_id,
                BarberAvailability.weekday == target_date.weekday(),
                BarberAvailability.is_active.is_(True),
            )
        ).all()
        availability_windows = [
            (
                datetime.fromisoformat(f"{target_date}T{availability.start_time}"),
                datetime.fromisoformat(f"{target_date}T{availability.end_time}"),
            )
            for availability in availabilities
        ] or ([branch_window] if branch_window else [])
        for availability_start, availability_end in availability_windows:
            if branch_window:
                availability_start = max(availability_start, branch_window[0])
                availability_end = min(availability_end, branch_window[1])
            cursor = _ceil_to_quarter(availability_start)
            end_limit = _floor_to_quarter(availability_end)
            while cursor + timedelta(minutes=duration) <= end_limit:
                slot_end = cursor + timedelta(minutes=duration)
                if barber_is_available(branch_id, candidate_id, cursor, slot_end, exclude_appointment_id):
                    slots.append(
                        {
                            "barber_id": candidate_id,
                            "starts_at": cursor.isoformat(),
                            "ends_at": slot_end.isoformat(),
                        }
                    )
                cursor += timedelta(minutes=15)
    return {"items": slots}


def get_public_availability_summary(payload: dict) -> dict:
    month_value = payload["month"]
    month_start = datetime.fromisoformat(f"{month_value}-01").date()
    if month_start.month == 12:
        next_month = month_start.replace(year=month_start.year + 1, month=1)
    else:
        next_month = month_start.replace(month=month_start.month + 1)

    today = datetime.utcnow().date()
    days = []
    cursor = month_start
    while cursor < next_month:
        key = cursor.isoformat()
        if cursor < today:
            days.append({"date": key, "count": 0})
            cursor += timedelta(days=1)
            continue
        availability = get_public_availability(payload | {"date": key})
        days.append(
            {
                "date": key,
                "count": len(availability.get("items", [])),
                "closed": availability.get("closed", False),
            }
        )
        cursor += timedelta(days=1)
    return {"items": days}


def create_appointment_atomic(
    payload: dict,
    created_by_user_id: int | None = None,
    allow_force_unavailable: bool = False,
) -> Appointment:
    branch_id = int(payload["branch_id"])
    primary_service_id = int(payload["primary_service_id"])
    extra_ids = [int(item) for item in payload.get("extra_service_ids", []) if item]
    starts_at = parse_date_time(payload)

    _active_branch(branch_id)
    if _date_is_closed(branch_id, starts_at):
        raise AppointmentValidationError("La fecha esta dada de baja y no permite nuevos turnos.")
    primary = _branch_service(
        primary_service_id,
        branch_id,
        (ServiceType.MAIN.value, ServiceType.EXTRA.value, ServiceType.BOTH.value),
    )
    extras = [
        _branch_service(extra_id, branch_id, (ServiceType.EXTRA.value, ServiceType.BOTH.value))
        for extra_id in extra_ids
    ]
    total_duration = primary.duration_minutes + sum(extra.duration_minutes for extra in extras)
    total_estimated = Decimal(primary.price) + sum(Decimal(extra.price) for extra in extras)
    ends_at = starts_at + timedelta(minutes=total_duration)

    barber_value = payload.get("barber_id")
    if barber_value and barber_value != "any":
        barber_id = int(barber_value)
        if not barber_is_available(branch_id, barber_id, starts_at, ends_at):
            can_force = (
                allow_force_unavailable
                and payload.get("force_unavailable")
                and _barber_works_in_branch(barber_id, branch_id)
                and not _date_is_closed(branch_id, starts_at)
                and not _has_block(branch_id, barber_id, starts_at, ends_at)
            )
            if not can_force:
                raise AppointmentConflict("El barbero no esta disponible en ese horario.")
    else:
        barber_id = _choose_any_barber(branch_id, starts_at, ends_at)

    email = (payload.get("email") or "").strip().lower()
    phone = (payload.get("phone") or "").strip()
    if not email or not phone:
        raise AppointmentValidationError("Email y telefono son obligatorios.")

    client = db.session.scalar(
        db.select(Client).where(or_(Client.email == email, Client.phone == phone))
    )
    if client is None:
        first_name = (payload.get("first_name") or "").strip()
        last_name = (payload.get("last_name") or "").strip()
        full_name = (payload.get("full_name") or f"{first_name} {last_name}").strip()
        client = Client(
            full_name=full_name,
            first_name=first_name or None,
            last_name=last_name or None,
            email=email,
            phone=phone,
            dni=payload.get("dni"),
        )
        db.session.add(client)
        db.session.flush()

    if _overlaps(barber_id, starts_at, ends_at):
        raise AppointmentConflict("Ese horario acaba de ser reservado. Elegi otro turno.")

    appointment = Appointment(
        branch_id=branch_id,
        client_id=client.id,
        barber_id=barber_id,
        primary_service_id=primary.id,
        starts_at=starts_at,
        ends_at=ends_at,
        status=AppointmentStatus.PENDING.value,
        source=payload.get("source", AppointmentSource.PUBLIC.value),
        customer_comment=payload.get("customer_comment"),
        internal_notes=payload.get("internal_notes"),
        total_estimated=total_estimated,
        created_by_user_id=created_by_user_id,
    )
    db.session.add(appointment)
    db.session.flush()

    for extra in extras:
        db.session.add(
            AppointmentExtraService(
                appointment_id=appointment.id,
                service_id=extra.id,
                price_at_booking=extra.price,
                duration_minutes_at_booking=extra.duration_minutes,
            )
        )

    for room in appointment_room(branch_id, barber_id, appointment.client_id):
        emit_live_event("appointment:created", model_to_dict(appointment), room=room)

    return appointment
