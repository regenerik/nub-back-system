from flask import Blueprint, request

from app.constants import Role, StockMovementType
from app.extensions import db
from app.modules.expenses.models import Expense
from app.modules.inventory.models import BranchProductStock, StockMovement
from app.modules.products.models import Product
from app.security import current_user, roles_required
from app.utils.http import get_json_payload, list_response, model_to_dict, parse_optional_date

admin_expenses_bp = Blueprint("admin_expenses", __name__)


@admin_expenses_bp.get("/expenses")
@roles_required([Role.ADMIN])
def list_expenses():
    query = db.select(Expense)
    if request.args.get("branch_id"):
        query = query.where(Expense.branch_id == int(request.args["branch_id"]))
    return list_response(db.session.scalars(query).all())


@admin_expenses_bp.get("/expenses/categories")
@roles_required([Role.ADMIN])
def list_expense_categories():
    rows = db.session.scalars(db.select(Expense.category).distinct().order_by(Expense.category)).all()
    return {"items": [{"name": item} for item in rows if item]}


@admin_expenses_bp.post("/expenses")
@roles_required([Role.ADMIN])
def create_expense():
    payload = get_json_payload()
    user = current_user()
    expense = Expense(
        branch_id=payload.get("branch_id"),
        category=payload["category"],
        description=payload.get("description"),
        amount=payload["amount"],
        expense_date=parse_optional_date(payload["expense_date"]),
        created_by_user_id=user.id if user else None,
    )
    db.session.add(expense)
    if payload.get("adds_stock"):
        branch_id = payload.get("branch_id")
        quantity = int(payload.get("stock_quantity") or 0)
        if not branch_id or quantity <= 0:
            db.session.rollback()
            return {"message": "Para agregar stock indicá sucursal y cantidad positiva."}, 400
        product_id = payload.get("product_id")
        if payload.get("stock_mode") == "new":
            product_payload = payload.get("new_product") or {}
            product = Product(
                name=product_payload["name"],
                description=product_payload.get("description"),
                sku=product_payload.get("sku") or None,
                sale_price=product_payload["sale_price"],
                unit_cost=product_payload.get("unit_cost", payload["amount"]),
                image_url=product_payload.get("image_url"),
            )
            db.session.add(product)
            db.session.flush()
            product_id = product.id
        product = db.session.get(Product, int(product_id)) if product_id else None
        if not product:
            db.session.rollback()
            return {"message": "Producto invalido para agregar stock."}, 400
        stock = db.session.scalar(
            db.select(BranchProductStock).where(
                BranchProductStock.branch_id == int(branch_id),
                BranchProductStock.product_id == product.id,
            )
        )
        if not stock:
            stock = BranchProductStock(branch_id=int(branch_id), product_id=product.id)
            db.session.add(stock)
        stock.current_stock += quantity
        db.session.add(
            StockMovement(
                branch_id=int(branch_id),
                product_id=product.id,
                movement_type=StockMovementType.PURCHASE.value,
                quantity=quantity,
                unit_cost=product.unit_cost,
                reason=f"Gasto #{expense.id or ''}: {expense.category}",
                created_by_user_id=user.id if user else None,
            )
        )
    db.session.commit()
    return model_to_dict(expense), 201


@admin_expenses_bp.patch("/expenses/<int:expense_id>")
@roles_required([Role.ADMIN])
def update_expense(expense_id):
    expense = db.session.get(Expense, expense_id)
    if not expense:
        return {"message": "Gasto no encontrado."}, 404
    payload = get_json_payload()
    for field in ("branch_id", "category", "description", "amount", "expense_date"):
        if field in payload:
            setattr(
                expense,
                field,
                parse_optional_date(payload[field]) if field == "expense_date" else payload[field],
            )
    db.session.commit()
    return model_to_dict(expense)


@admin_expenses_bp.delete("/expenses/<int:expense_id>")
@roles_required([Role.ADMIN])
def delete_expense(expense_id):
    expense = db.session.get(Expense, expense_id)
    if not expense:
        return {"message": "Gasto no encontrado."}, 404
    db.session.delete(expense)
    db.session.commit()
    return {"message": "Gasto eliminado."}
