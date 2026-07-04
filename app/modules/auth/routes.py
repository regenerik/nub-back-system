from flask import Blueprint
from flask_jwt_extended import create_access_token, get_jwt_identity, jwt_required

from app.constants import Role
from app.extensions import db
from app.modules.auth.models import User
from app.modules.barbers.models import Barber
from app.modules.clients.models import Client
from app.utils.http import get_json_payload, model_to_dict

auth_bp = Blueprint("auth", __name__)


def _token_for(user: User) -> str:
    return create_access_token(
        identity=str(user.id),
        additional_claims={
            "role": user.role,
            "branch_id": user.branch_id,
            "permissions": {
                "can_apply_discounts": user.can_apply_discounts,
            },
        },
    )


@auth_bp.post("/login")
def login():
    payload = get_json_payload()
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""

    user = db.session.scalar(db.select(User).where(User.email == email))
    if not user or not user.is_active or not user.check_password(password):
        return {"message": "Credenciales invalidas."}, 401

    return {"access_token": _token_for(user), "user": model_to_dict(user, {"password_hash"})}


@auth_bp.post("/register-client")
def register_client():
    payload = get_json_payload()
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""
    full_name = (payload.get("full_name") or "").strip()
    phone = (payload.get("phone") or "").strip()
    if not email or not password or not full_name:
        return {"message": "Email, password y nombre son obligatorios."}, 400
    if db.session.scalar(db.select(User).where(User.email == email)):
        return {"message": "Ya existe un usuario con ese email."}, 409

    user = User(email=email, full_name=full_name, role=Role.CLIENTE.value)
    user.set_password(password)
    db.session.add(user)
    client = db.session.scalar(db.select(Client).where(Client.email == email))
    if not client:
        db.session.add(Client(full_name=full_name, email=email, phone=phone or ""))
    db.session.commit()
    return {"access_token": _token_for(user), "user": model_to_dict(user, {"password_hash"})}, 201


@auth_bp.post("/google")
def google_login():
    payload = get_json_payload()
    email = (payload.get("email") or "").strip().lower()
    google_account_id = payload.get("google_account_id")
    full_name = payload.get("full_name") or email
    profile_image_url = payload.get("profile_image_url")
    if not email or not google_account_id:
        return {"message": "Email y google_account_id son obligatorios."}, 400
    user = db.session.scalar(db.select(User).where(User.email == email))
    barber = db.session.scalar(db.select(Barber).where(Barber.email == email))
    if not user:
        user = User(
            email=email,
            full_name=full_name,
            role=Role.BARBERO.value if barber else Role.CLIENTE.value,
            google_account_id=google_account_id,
            profile_image_url=profile_image_url,
        )
        db.session.add(user)
        db.session.flush()
    else:
        user.google_account_id = google_account_id
        if profile_image_url:
            user.profile_image_url = profile_image_url
        if user.role in (Role.CLIENTE.value, Role.BARBERO.value):
            user.can_apply_discounts = False
    if barber:
        barber.user_id = user.id
        if profile_image_url and not barber.profile_image_url:
            barber.profile_image_url = profile_image_url
        db.session.commit()
        return {"access_token": _token_for(user), "user": model_to_dict(user, {"password_hash"})}
    client = db.session.scalar(db.select(Client).where(Client.email == email))
    if client:
        client.google_account_id = google_account_id
        if profile_image_url:
            client.profile_image_url = profile_image_url
    else:
        db.session.add(
            Client(
                full_name=full_name,
                email=email,
                phone="",
                google_account_id=google_account_id,
                profile_image_url=profile_image_url,
            )
        )
    db.session.commit()
    return {"access_token": _token_for(user), "user": model_to_dict(user, {"password_hash"})}


@auth_bp.get("/me")
@jwt_required()
def me():
    user = db.session.get(User, int(get_jwt_identity()))
    if not user:
        return {"message": "Usuario no encontrado."}, 404
    return {"user": model_to_dict(user, {"password_hash"})}
