from flask import Blueprint

from app.constants import Role
from app.extensions import db
from app.modules.payments.models import Payment
from app.security import roles_required
from app.utils.http import list_response

payments_bp = Blueprint("payments", __name__)


@payments_bp.get("")
@roles_required([Role.ADMIN, Role.RECEPCION])
def list_payments():
    return list_response(db.session.scalars(db.select(Payment)).all())
