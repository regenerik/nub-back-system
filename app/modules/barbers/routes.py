from flask import Blueprint, request

from app.constants import Role
from app.extensions import db
from app.modules.barbers.models import Barber, BarberBranch
from app.security import roles_required
from app.utils.http import get_json_payload, list_response, model_to_dict

public_barbers_bp = Blueprint("public_barbers", __name__)
barbers_bp = Blueprint("barbers", __name__)
admin_barbers_bp = Blueprint("admin_barbers", __name__)


@public_barbers_bp.get("/barbers")
def public_barbers():
    branch_id = request.args.get("branch_id")
    query = db.select(Barber).where(Barber.is_active.is_(True))
    if branch_id:
        query = query.join(BarberBranch, BarberBranch.barber_id == Barber.id).where(
            BarberBranch.branch_id == int(branch_id),
            BarberBranch.is_active.is_(True),
        )
    return list_response(db.session.scalars(query).all())


@barbers_bp.get("")
@roles_required([Role.ADMIN, Role.RECEPCION])
def list_barbers():
    items = []
    for barber in db.session.scalars(db.select(Barber)).all():
        branch_ids = db.session.scalars(
            db.select(BarberBranch.branch_id).where(
                BarberBranch.barber_id == barber.id,
                BarberBranch.is_active.is_(True),
            )
        ).all()
        items.append(model_to_dict(barber) | {"branch_ids": branch_ids})
    return {"items": items}


@barbers_bp.get("/<int:barber_id>")
@roles_required([Role.ADMIN, Role.RECEPCION, Role.BARBERO])
def get_barber(barber_id):
    barber = db.session.get(Barber, barber_id)
    if not barber:
        return {"message": "Barbero no encontrado."}, 404
    return model_to_dict(barber)


@admin_barbers_bp.post("/barbers")
@roles_required([Role.ADMIN])
def create_barber():
    payload = get_json_payload()
    barber = Barber(
        user_id=payload.get("user_id"),
        full_name=payload["full_name"],
        email=payload.get("email"),
        phone=payload.get("phone"),
        address=payload.get("address"),
        bio=payload.get("bio"),
        profile_image_url=payload.get("profile_image_url"),
        commission_percentage=payload.get("commission_percentage"),
        fixed_salary=payload.get("fixed_salary"),
    )
    db.session.add(barber)
    db.session.commit()
    return model_to_dict(barber), 201


@admin_barbers_bp.patch("/barbers/<int:barber_id>")
@roles_required([Role.ADMIN])
def update_barber(barber_id):
    barber = db.session.get(Barber, barber_id)
    if not barber:
        return {"message": "Barbero no encontrado."}, 404
    payload = get_json_payload()
    for field in (
        "full_name",
        "email",
        "phone",
        "address",
        "bio",
        "profile_image_url",
        "commission_percentage",
        "fixed_salary",
        "is_active",
    ):
        if field in payload:
            setattr(barber, field, payload[field])
    db.session.commit()
    return model_to_dict(barber)


@admin_barbers_bp.patch("/barbers/<int:barber_id>/disable")
@roles_required([Role.ADMIN])
def disable_barber(barber_id):
    barber = db.session.get(Barber, barber_id)
    if not barber:
        return {"message": "Barbero no encontrado."}, 404
    barber.is_active = False
    db.session.commit()
    return model_to_dict(barber)


@admin_barbers_bp.post("/barbers/<int:barber_id>/branches")
@roles_required([Role.ADMIN])
def assign_barber_branch(barber_id):
    payload = get_json_payload()
    branch_ids = payload.get("branch_ids")
    if branch_ids is not None:
        existing = db.session.scalars(
            db.select(BarberBranch).where(BarberBranch.barber_id == barber_id)
        ).all()
        by_branch = {item.branch_id: item for item in existing}
        wanted = {int(item) for item in branch_ids}
        for link in existing:
            link.is_active = link.branch_id in wanted
        for branch_id in wanted:
            if branch_id not in by_branch:
                db.session.add(
                    BarberBranch(
                        barber_id=barber_id,
                        branch_id=branch_id,
                        is_active=True,
                    )
                )
        db.session.commit()
        return {"items": [model_to_dict(item) for item in db.session.scalars(db.select(BarberBranch).where(BarberBranch.barber_id == barber_id)).all()]}
    assignment = BarberBranch(
        barber_id=barber_id,
        branch_id=int(payload["branch_id"]),
        is_active=payload.get("is_active", True),
    )
    db.session.add(assignment)
    db.session.commit()
    return model_to_dict(assignment), 201
