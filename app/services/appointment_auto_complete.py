from sqlalchemy import func

from app.constants import AppointmentStatus, SaleStatus
from app.extensions import db
from app.modules.appointments.models import Appointment
from app.modules.payments.models import Payment
from app.modules.sales.models import Sale


def appointment_is_paid(appointment: Appointment) -> bool:
    sale = db.session.scalar(db.select(Sale).where(Sale.appointment_id == appointment.id))
    if not sale or sale.status == SaleStatus.CANCELLED.value:
        return False
    paid_total = db.session.scalar(
        db.select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.sale_id == sale.id)
    )
    return bool(paid_total is not None and paid_total >= sale.total)


def auto_complete_appointment_if_ready(appointment: Appointment | None) -> bool:
    if not appointment or appointment.status != AppointmentStatus.CHECKED_IN.value:
        return False
    if not appointment_is_paid(appointment):
        return False
    appointment.status = AppointmentStatus.COMPLETED.value
    return True
