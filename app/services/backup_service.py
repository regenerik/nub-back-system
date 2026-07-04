from app.extensions import db
from app.models import AuditLog
from app.modules.appointments.models import (
    Appointment,
    AppointmentExtraService,
    BarberAvailability,
    ScheduleBlock,
)
from app.modules.auth.models import User
from app.modules.barbers.models import Barber, BarberBranch
from app.modules.branches.models import Branch
from app.modules.clients.models import Client
from app.modules.expenses.models import Expense
from app.modules.inventory.models import BranchProductStock, StockMovement
from app.modules.payments.models import Payment
from app.modules.products.models import Product
from app.modules.salaries.models import SalaryPayment
from app.modules.sales.models import Sale, SaleItem
from app.modules.services.models import BranchService, Service
from app.modules.settings.models import BusinessSetting
from app.utils.http import model_to_dict

BACKUP_MODELS = {
    "branches": Branch,
    "users": User,
    "clients": Client,
    "barbers": Barber,
    "barber_branches": BarberBranch,
    "services": Service,
    "branch_services": BranchService,
    "products": Product,
    "branch_product_stock": BranchProductStock,
    "appointments": Appointment,
    "appointment_extra_services": AppointmentExtraService,
    "barber_availabilities": BarberAvailability,
    "schedule_blocks": ScheduleBlock,
    "sales": Sale,
    "sale_items": SaleItem,
    "payments": Payment,
    "expenses": Expense,
    "salary_payments": SalaryPayment,
    "stock_movements": StockMovement,
    "business_settings": BusinessSetting,
    "audit_logs": AuditLog,
}


def export_full_backup() -> dict:
    return {
        name: [model_to_dict(item) for item in db.session.scalars(db.select(model)).all()]
        for name, model in BACKUP_MODELS.items()
    }


def validate_backup(payload: dict) -> tuple[bool, list[str]]:
    missing = [name for name in BACKUP_MODELS if name not in payload]
    invalid = [name for name in payload if name not in BACKUP_MODELS]
    return not missing and not invalid, missing + invalid


def restore_backup(payload: dict, dry_run: bool = True) -> dict:
    valid, issues = validate_backup(payload)
    if not valid:
        return {"valid": False, "issues": issues}
    if dry_run:
        return {"valid": True, "dry_run": True, "message": "Backup valido."}

    # Full destructive restore should be implemented after an explicit retention policy.
    return {
        "valid": True,
        "dry_run": False,
        "message": "Restauracion completa pendiente de politica de retencion.",
    }
