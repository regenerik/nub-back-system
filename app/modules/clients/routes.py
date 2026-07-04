from flask import Blueprint, request

from app.constants import Role
from app.extensions import db
from app.modules.clients.models import Client
from app.security import current_user, login_required, roles_required
from app.utils.http import get_json_payload, list_response, model_to_dict, parse_optional_date

clients_bp = Blueprint("clients", __name__)
client_profile_bp = Blueprint("client_profile", __name__)


def _current_client():
    user = current_user()
    if not user:
        return None
    query = db.select(Client).where(Client.email == user.email)
    if user.google_account_id:
        query = db.select(Client).where(
            (Client.email == user.email) | (Client.google_account_id == user.google_account_id)
        )
    client = db.session.scalar(query)
    if client:
        return client
    client = Client(
        full_name=user.full_name,
        email=user.email,
        phone="",
        google_account_id=user.google_account_id,
    )
    db.session.add(client)
    db.session.commit()
    return client


@client_profile_bp.get("/me/profile")
@login_required
def my_profile():
    client = _current_client()
    if not client:
        return {"message": "Cliente no encontrado."}, 404
    return model_to_dict(client)


@client_profile_bp.patch("/me/profile")
@login_required
def update_my_profile():
    client = _current_client()
    if not client:
        return {"message": "Cliente no encontrado."}, 404
    payload = get_json_payload()
    for field in (
        "full_name",
        "first_name",
        "last_name",
        "phone",
        "dni",
        "birth_date",
        "notes",
        "profile_image_url",
    ):
        if field in payload:
            setattr(
                client,
                field,
                parse_optional_date(payload[field]) if field == "birth_date" else payload[field],
            )
    db.session.commit()
    return model_to_dict(client)


@clients_bp.get("")
@roles_required([Role.ADMIN, Role.RECEPCION])
def list_clients():
    return list_response(db.session.scalars(db.select(Client).where(Client.is_active.is_(True))).all())


@clients_bp.get("/search")
@roles_required([Role.ADMIN, Role.RECEPCION])
def search_clients():
    q = f"%{(request.args.get('q') or '').strip()}%"
    items = db.session.scalars(
        db.select(Client).where(
            Client.is_active.is_(True),
            Client.full_name.ilike(q)
            | Client.email.ilike(q)
            | Client.phone.ilike(q)
            | Client.dni.ilike(q)
        )
    ).all()
    return list_response(items)


@clients_bp.get("/<int:client_id>")
@roles_required([Role.ADMIN, Role.RECEPCION])
def get_client(client_id):
    client = db.session.get(Client, client_id)
    if not client:
        return {"message": "Cliente no encontrado."}, 404
    return model_to_dict(client)


@clients_bp.post("")
@roles_required([Role.ADMIN, Role.RECEPCION])
def create_client():
    payload = get_json_payload()
    client = Client(
        full_name=payload["full_name"],
        first_name=payload.get("first_name"),
        last_name=payload.get("last_name"),
        email=(payload.get("email") or "").lower(),
        phone=payload.get("phone") or "",
        dni=payload.get("dni"),
        birth_date=parse_optional_date(payload.get("birth_date")),
        notes=payload.get("notes"),
        profile_image_url=payload.get("profile_image_url"),
    )
    db.session.add(client)
    db.session.commit()
    return model_to_dict(client), 201


@clients_bp.patch("/<int:client_id>")
@roles_required([Role.ADMIN, Role.RECEPCION])
def update_client(client_id):
    client = db.session.get(Client, client_id)
    if not client:
        return {"message": "Cliente no encontrado."}, 404
    payload = get_json_payload()
    for field in (
        "full_name",
        "first_name",
        "last_name",
        "email",
        "phone",
        "dni",
        "birth_date",
        "notes",
        "profile_image_url",
        "is_active",
    ):
        if field in payload:
            setattr(
                client,
                field,
                parse_optional_date(payload[field]) if field == "birth_date" else payload[field],
            )
    db.session.commit()
    return model_to_dict(client)


@clients_bp.delete("/<int:client_id>")
@roles_required([Role.ADMIN, Role.RECEPCION])
def delete_client(client_id):
    client = db.session.get(Client, client_id)
    if not client:
        return {"message": "Cliente no encontrado."}, 404
    client.is_active = False
    db.session.commit()
    return model_to_dict(client)
