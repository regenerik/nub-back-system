from flask import Blueprint, request

from app.constants import Role
from app.extensions import db
from app.modules.branches.models import Branch
from app.modules.services.models import BranchService, Service
from app.security import current_user, roles_required
from app.utils.http import get_json_payload, list_response, model_to_dict

public_services_bp = Blueprint("public_services", __name__)
admin_services_bp = Blueprint("admin_services", __name__)


@public_services_bp.get("/services")
def public_services():
    branch_id = request.args.get("branch_id")
    service_type = request.args.get("type")
    query = db.select(Service).where(Service.is_active.is_(True))
    if branch_id:
        query = query.join(BranchService, BranchService.service_id == Service.id).where(
            BranchService.branch_id == int(branch_id),
            BranchService.is_active.is_(True),
        )
    if service_type:
        query = query.where(Service.service_type.in_((service_type, "both")))
    return list_response(db.session.scalars(query).all())


@admin_services_bp.get("/services")
@roles_required([Role.ADMIN])
def admin_services():
    items = []
    for service in db.session.scalars(db.select(Service)).all():
        branch_ids = db.session.scalars(
            db.select(BranchService.branch_id).where(
                BranchService.service_id == service.id,
                BranchService.is_active.is_(True),
            )
        ).all()
        items.append(model_to_dict(service) | {"branch_ids": branch_ids})
    return {"items": items}


@admin_services_bp.post("/services")
@roles_required([Role.ADMIN])
def create_service():
    payload = get_json_payload()
    service = Service(
        name=payload["name"],
        description=payload.get("description"),
        duration_minutes=int(payload["duration_minutes"]),
        price=payload["price"],
        cost_estimate=payload.get("cost_estimate"),
        image_url=payload.get("image_url"),
        service_type=payload.get("service_type", "main"),
    )
    db.session.add(service)
    db.session.commit()
    return model_to_dict(service), 201


@admin_services_bp.patch("/services/<int:service_id>")
@roles_required([Role.ADMIN])
def update_service(service_id):
    service = db.session.get(Service, service_id)
    if not service:
        return {"message": "Servicio no encontrado."}, 404
    payload = get_json_payload()
    for field in (
        "name",
        "description",
        "duration_minutes",
        "price",
        "cost_estimate",
        "image_url",
        "service_type",
        "is_active",
    ):
        if field in payload:
            setattr(service, field, payload[field])
    db.session.commit()
    return model_to_dict(service)


@admin_services_bp.patch("/services/<int:service_id>/disable")
@roles_required([Role.ADMIN])
def disable_service(service_id):
    service = db.session.get(Service, service_id)
    if not service:
        return {"message": "Servicio no encontrado."}, 404
    service.is_active = False
    db.session.commit()
    return model_to_dict(service)


@admin_services_bp.post("/services/<int:service_id>/branches")
@roles_required([Role.ADMIN])
def assign_service_branch(service_id):
    payload = get_json_payload()
    branch_ids = payload.get("branch_ids")
    if branch_ids is not None:
        existing = db.session.scalars(
            db.select(BranchService).where(BranchService.service_id == service_id)
        ).all()
        by_branch = {item.branch_id: item for item in existing}
        wanted = {int(item) for item in branch_ids}
        for link in existing:
            link.is_active = link.branch_id in wanted
        for branch_id in wanted:
            if branch_id not in by_branch:
                db.session.add(
                    BranchService(
                        service_id=service_id,
                        branch_id=branch_id,
                        is_active=True,
                    )
                )
        db.session.commit()
        return {"items": [model_to_dict(item) for item in db.session.scalars(db.select(BranchService).where(BranchService.service_id == service_id)).all()]}
    assignment = BranchService(
        service_id=service_id,
        branch_id=int(payload["branch_id"]),
        is_active=payload.get("is_active", True),
    )
    db.session.add(assignment)
    db.session.commit()
    return model_to_dict(assignment), 201


@admin_services_bp.post("/services/import-to-branch")
@roles_required([Role.ADMIN, Role.RECEPCION])
def import_services_to_branch():
    payload = get_json_payload()
    branch_id = int(payload["branch_id"])
    service_ids = [int(item) for item in payload.get("service_ids", []) if item]
    if not service_ids:
        return {"message": "Selecciona al menos un servicio."}, 400
    branch = db.session.get(Branch, branch_id)
    if not branch or not branch.is_active:
        return {"message": "Sucursal no encontrada o inactiva."}, 404
    user = current_user()
    if user and user.role == Role.RECEPCION.value and user.branch_id and user.branch_id != branch_id:
        return {"message": "Recepcion solo puede importar servicios a su sucursal."}, 403

    imported = []
    existing = db.session.scalars(
        db.select(BranchService).where(
            BranchService.branch_id == branch_id,
            BranchService.service_id.in_(service_ids),
        )
    ).all()
    by_service = {item.service_id: item for item in existing}
    for service_id in service_ids:
        service = db.session.get(Service, service_id)
        if not service or not service.is_active:
            return {"message": "Uno de los servicios no existe o esta inactivo."}, 400
        link = by_service.get(service_id)
        if link:
            link.is_active = True
        else:
            link = BranchService(branch_id=branch_id, service_id=service_id, is_active=True)
            db.session.add(link)
        imported.append(model_to_dict(service))
    db.session.commit()
    return {"items": imported}
