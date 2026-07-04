from flask import Blueprint, request

from app.constants import Role, StockMovementType
from app.extensions import db
from app.modules.inventory.models import BranchProductStock, StockMovement
from app.modules.products.models import Product
from app.security import current_user, roles_required
from app.utils.http import get_json_payload, list_response, model_to_dict

admin_products_bp = Blueprint("admin_products", __name__)


@admin_products_bp.get("/products")
@roles_required([Role.ADMIN, Role.RECEPCION])
def admin_products():
    user = current_user()
    branch_id = request.args.get("branch_id")
    if user and user.role == Role.RECEPCION.value and user.branch_id:
        branch_id = str(user.branch_id)
    if not branch_id:
        return list_response(db.session.scalars(db.select(Product)).all())
    rows = db.session.execute(
        db.select(Product, BranchProductStock).join(
            BranchProductStock, BranchProductStock.product_id == Product.id
        ).where(BranchProductStock.branch_id == int(branch_id))
    ).all()
    return {
        "items": [
            {
                **model_to_dict(product),
                "stock": model_to_dict(stock),
            }
            for product, stock in rows
        ]
    }


@admin_products_bp.post("/products")
@roles_required([Role.ADMIN])
def create_product():
    payload = get_json_payload()
    product = Product(
        name=payload["name"],
        description=payload.get("description"),
        sku=payload.get("sku") or None,
        sale_price=payload["sale_price"],
        unit_cost=payload["unit_cost"],
        image_url=payload.get("image_url"),
    )
    db.session.add(product)
    db.session.commit()
    return model_to_dict(product), 201


@admin_products_bp.patch("/products/<int:product_id>")
@roles_required([Role.ADMIN])
def update_product(product_id):
    product = db.session.get(Product, product_id)
    if not product:
        return {"message": "Producto no encontrado."}, 404
    payload = get_json_payload()
    for field in ("name", "description", "sku", "sale_price", "unit_cost", "image_url", "is_active"):
        if field in payload:
            setattr(product, field, payload[field])
    db.session.commit()
    return model_to_dict(product)


@admin_products_bp.patch("/products/<int:product_id>/disable")
@roles_required([Role.ADMIN])
def disable_product(product_id):
    product = db.session.get(Product, product_id)
    if not product:
        return {"message": "Producto no encontrado."}, 404
    product.is_active = False
    db.session.commit()
    return model_to_dict(product)


@admin_products_bp.post("/products/<int:product_id>/stock-adjustment")
@roles_required([Role.ADMIN])
def stock_adjustment(product_id):
    payload = get_json_payload()
    branch_id = int(payload["branch_id"])
    quantity = int(payload["quantity"])
    stock = db.session.scalar(
        db.select(BranchProductStock).where(
            BranchProductStock.branch_id == branch_id,
            BranchProductStock.product_id == product_id,
        )
    )
    if not stock:
        stock = BranchProductStock(branch_id=branch_id, product_id=product_id)
        db.session.add(stock)
    if stock.current_stock + quantity < 0:
        return {"message": "El ajuste deja el stock en negativo."}, 400
    stock.current_stock += quantity
    movement = StockMovement(
        branch_id=branch_id,
        product_id=product_id,
        movement_type=StockMovementType.ADJUSTMENT.value,
        quantity=quantity,
        reason=payload.get("reason", "Ajuste manual"),
    )
    db.session.add(movement)
    db.session.commit()
    return {"stock": model_to_dict(stock), "movement": model_to_dict(movement)}
