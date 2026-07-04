from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.constants import AppointmentSource, AppointmentStatus
from app.extensions import db
from app.models import TimestampMixin


class Appointment(db.Model, TimestampMixin):
    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(primary_key=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), nullable=False)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False)
    barber_id: Mapped[int] = mapped_column(ForeignKey("barbers.id"), nullable=False)
    primary_service_id: Mapped[int] = mapped_column(
        ForeignKey("services.id"), nullable=False
    )
    starts_at: Mapped[datetime] = mapped_column(nullable=False, index=True)
    ends_at: Mapped[datetime] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), default=AppointmentStatus.PENDING, nullable=False
    )
    source: Mapped[str] = mapped_column(
        String(40), default=AppointmentSource.PUBLIC, nullable=False
    )
    customer_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    internal_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_estimated: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    total_final: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )


class AppointmentExtraService(db.Model):
    __tablename__ = "appointment_extra_services"

    id: Mapped[int] = mapped_column(primary_key=True)
    appointment_id: Mapped[int] = mapped_column(
        ForeignKey("appointments.id"), nullable=False
    )
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"), nullable=False)
    price_at_booking: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    duration_minutes_at_booking: Mapped[int] = mapped_column(Integer, nullable=False)


class BarberAvailability(db.Model):
    __tablename__ = "barber_availabilities"

    id: Mapped[int] = mapped_column(primary_key=True)
    barber_id: Mapped[int] = mapped_column(ForeignKey("barbers.id"), nullable=False)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), nullable=False)
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time: Mapped[str] = mapped_column(String(5), nullable=False)
    end_time: Mapped[str] = mapped_column(String(5), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ScheduleBlock(db.Model, TimestampMixin):
    __tablename__ = "schedule_blocks"

    id: Mapped[int] = mapped_column(primary_key=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), nullable=False)
    barber_id: Mapped[int | None] = mapped_column(ForeignKey("barbers.id"), nullable=True)
    starts_at: Mapped[datetime] = mapped_column(nullable=False, index=True)
    ends_at: Mapped[datetime] = mapped_column(nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )


class BranchDateClosure(db.Model, TimestampMixin):
    __tablename__ = "branch_date_closures"
    __table_args__ = (UniqueConstraint("branch_id", "date", name="uq_branch_date_closure"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
