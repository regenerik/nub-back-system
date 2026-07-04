from flask import Blueprint, request

from app.constants import Role
from app.extensions import db
from app.modules.auth.models import User
from app.security import forbid_reception_admin_creation, roles_required
from app.utils.http import get_json_payload, list_response, model_to_dict

admin_users_bp = Blueprint("admin_users", __name__)


@admin_users_bp.get("/users")
@roles_required([Role.ADMIN])
def list_users():
    query = db.select(User)
    q = (request.args.get("q") or "").strip()
    if q:
        like = f"%{q}%"
        query = query.where(User.full_name.ilike(like) | User.email.ilike(like))
    if request.args.get("role"):
        query = query.where(User.role == request.args["role"])
    if request.args.get("branch_id"):
        query = query.where(User.branch_id == int(request.args["branch_id"]))
    return list_response(db.session.scalars(query.order_by(User.created_at.desc())).all())


@admin_users_bp.post("/users")
@roles_required([Role.ADMIN, Role.RECEPCION])
def create_user():
    payload = get_json_payload()
    forbidden = forbid_reception_admin_creation(payload)
    if forbidden:
        return forbidden
    if db.session.scalar(db.select(User).where(User.email == payload["email"].lower())):
        return {"message": "Email ya registrado."}, 409
    role = (payload.get("role", Role.CLIENTE.value) or Role.CLIENTE.value).lower()
    user = User(
        email=payload["email"].strip().lower(),
        full_name=payload["full_name"],
        role=role,
        branch_id=payload.get("branch_id"),
        can_apply_discounts=bool(payload.get("can_apply_discounts", False))
        if role not in (Role.CLIENTE.value, Role.BARBERO.value)
        else False,
        profile_image_url=payload.get("profile_image_url"),
    )
    if payload.get("password"):
        user.set_password(payload["password"])
    db.session.add(user)
    db.session.commit()
    return model_to_dict(user, {"password_hash"}), 201


@admin_users_bp.patch("/users/<int:user_id>")
@roles_required([Role.ADMIN])
def update_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        return {"message": "Usuario no encontrado."}, 404
    payload = get_json_payload()
    for field in ("full_name", "role", "branch_id", "can_apply_discounts", "google_account_id", "profile_image_url"):
        if field in payload:
            setattr(user, field, payload[field].lower() if field == "role" else payload[field])
    if user.role in (Role.CLIENTE.value, Role.BARBERO.value):
        user.can_apply_discounts = False
    if payload.get("password"):
        user.set_password(payload["password"])
    db.session.commit()
    return model_to_dict(user, {"password_hash"})


@admin_users_bp.patch("/users/<int:user_id>/disable")
@roles_required([Role.ADMIN])
def disable_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        return {"message": "Usuario no encontrado."}, 404
    user.is_active = False
    db.session.commit()
    return model_to_dict(user, {"password_hash"})


@admin_users_bp.patch("/users/<int:user_id>/enable")
@roles_required([Role.ADMIN])
def enable_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        return {"message": "Usuario no encontrado."}, 404
    user.is_active = True
    db.session.commit()
    return model_to_dict(user, {"password_hash"})
