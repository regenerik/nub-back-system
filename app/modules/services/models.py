from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.constants import ServiceType
from app.extensions import db
from app.models import TimestampMixin


class Service(db.Model, TimestampMixin):
    __tablename__ = "services"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    cost_estimate: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    service_type: Mapped[str] = mapped_column(
        String(30), default=ServiceType.MAIN, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class BranchService(db.Model, TimestampMixin):
    __tablename__ = "branch_services"

    id: Mapped[int] = mapped_column(primary_key=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), nullable=False)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
