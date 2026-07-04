from flask import Blueprint

from app.constants import Role
from app.security import require_roles

inventory_bp = Blueprint("inventory", __name__)


@inventory_bp.get("")
@require_roles(Role.ADMIN, Role.RECEPCION)
def list_stock_movements():
    return {"items": [], "message": "Modulo de inventario preparado."}
