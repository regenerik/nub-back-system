from functools import wraps

from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required

from app.constants import Role
from app.extensions import db
from app.modules.auth.models import User


def _role_value(role):
    return getattr(role, "value", role)


def current_user():
    user_id = get_jwt_identity()
    if not user_id:
        return None
    return db.session.get(User, int(user_id))


def login_required(fn):
    @wraps(fn)
    @jwt_required()
    def wrapper(*args, **kwargs):
        return fn(*args, **kwargs)

    return wrapper


def roles_required(roles):
    def decorator(fn):
        @wraps(fn)
        @jwt_required()
        def wrapper(*args, **kwargs):
            claims = get_jwt()
            allowed = {_role_value(role) for role in roles}
            role = claims.get("role")
            if role == Role.ADMIN.value or role in allowed:
                return fn(*args, **kwargs)
            return {"message": "No tenes permisos para esta accion."}, 403

        return wrapper

    return decorator


def require_roles(*roles):
    return roles_required(roles)


def permission_required(permission_name):
    def decorator(fn):
        @wraps(fn)
        @jwt_required()
        def wrapper(*args, **kwargs):
            claims = get_jwt()
            if claims.get("role") == Role.ADMIN.value:
                return fn(*args, **kwargs)
            permissions = claims.get("permissions", {})
            if not permissions.get(permission_name):
                return {"message": "Permiso insuficiente."}, 403
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def require_permission(permission_name):
    return permission_required(permission_name)


def forbid_reception_admin_creation(payload):
    claims = get_jwt()
    requested_role = (payload.get("role") or "").lower()
    if claims.get("role") == Role.RECEPCION.value and requested_role == Role.ADMIN.value:
        return {"message": "No tenes permisos para esta accion."}, 403
    return None
