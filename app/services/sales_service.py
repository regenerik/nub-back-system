from decimal import Decimal

from flask_jwt_extended import get_jwt

from app.constants import PaymentMethod, SaleItemKind, SaleStatus, StockMovementType
from app.extensions import db
from app.live import appointment_room, emit_live_event
from app.modules.inventory.models import BranchProductStock, StockMovement
from app.modules.appointments.models import Appointment
from app.modules.payments.models import Payment
from app.modules.products.models import Product
from app.modules.sales.models import Sale, SaleItem
from app.modules.services.models import Service
from app.utils.http import model_to_dict
from app.services.appointment_auto_complete import auto_complete_appointment_if_ready


class SaleValidationError(Exception):
    pass


def _can_discount(discount_amount: Decimal) -> bool:
    if discount_amount <= 0:
        return True
    claims = get_jwt()
    return claims.get("role") == "admin" or claims.get("permissions", {}).get(
        "can_apply_discounts"
    )


def create_sale(payload: dict, created_by_user_id: int | None = None) -> Sale:
    branch_id = int(payload["branch_id"])
    discount_amount = Decimal(str(payload.get("discount_amount", 0)))
    if not _can_discount(discount_amount):
        raise PermissionError("No tenes permiso para aplicar descuentos.")

    sale = Sale(
        branch_id=branch_id,
        client_id=payload.get("client_id"),
        appointment_id=payload.get("appointment_id"),
        created_by_user_id=created_by_user_id,
        subtotal=Decimal("0"),
        discount_amount=discount_amount,
        total=Decimal("0"),
        status=SaleStatus.PENDING.value,
    )
    db.session.add(sale)
    db.session.flush()

    subtotal = Decimal("0")
    for item in payload.get("items", []):
        item_type = item.get("item_type")
        quantity = int(item.get("quantity", 1))
        if quantity <= 0:
            raise SaleValidationError("La cantidad debe ser positiva.")

        if item_type == SaleItemKind.SERVICE.value:
            service = db.session.get(Service, int(item["service_id"]))
            if not service or not service.is_active:
                raise SaleValidationError("Servicio invalido.")
            unit_price = Decimal(str(item.get("unit_price", service.price)))
            unit_cost = Decimal(str(item.get("unit_cost", service.cost_estimate or 0)))
            description = item.get("description", service.name)
            sale_item = SaleItem(
                sale_id=sale.id,
                item_type=item_type,
                service_id=service.id,
                description=description,
                quantity=quantity,
                unit_price=unit_price,
                unit_cost=unit_cost,
                total_price=unit_price * quantity,
                total_cost=unit_cost * quantity,
            )
        elif item_type == SaleItemKind.PRODUCT.value:
            product = db.session.get(Product, int(item["product_id"]))
            if not product or not product.is_active:
                raise SaleValidationError("Producto invalido.")
            stock = db.session.scalar(
                db.select(BranchProductStock).where(
                    BranchProductStock.branch_id == branch_id,
                    BranchProductStock.product_id == product.id,
                )
            )
            if not stock or stock.current_stock < quantity:
                raise SaleValidationError("Stock insuficiente.")
            unit_price = Decimal(str(item.get("unit_price", product.sale_price)))
            unit_cost = Decimal(str(item.get("unit_cost", product.unit_cost)))
            description = item.get("description", product.name)
            sale_item = SaleItem(
                sale_id=sale.id,
                item_type=item_type,
                product_id=product.id,
                description=description,
                quantity=quantity,
                unit_price=unit_price,
                unit_cost=unit_cost,
                total_price=unit_price * quantity,
                total_cost=unit_cost * quantity,
            )
            stock.current_stock -= quantity
            db.session.add(
                StockMovement(
                    branch_id=branch_id,
                    product_id=product.id,
                    movement_type=StockMovementType.SALE.value,
                    quantity=-quantity,
                    unit_cost=unit_cost,
                    reason="Venta",
                    created_by_user_id=created_by_user_id,
                )
            )
            emit_live_event(
                "stock:updated",
                {"branch_id": branch_id, "product_id": product.id, "stock": stock.current_stock},
                room=f"branch:{branch_id}",
            )
        else:
            raise SaleValidationError("Tipo de item invalido.")

        subtotal += sale_item.total_price
        db.session.add(sale_item)
        db.session.flush()

    sale.subtotal = subtotal
    sale.total = max(Decimal("0"), subtotal - discount_amount)

    completed_appointment = None
    payment_payload = payload.get("payment")
    if payment_payload:
        payment_amount = Decimal(str(payment_payload.get("amount", sale.total)))
        db.session.add(
            Payment(
                sale_id=sale.id,
                method=payment_payload.get("method", PaymentMethod.EFECTIVO.value),
                amount=payment_amount,
                reference=payment_payload.get("reference"),
                created_by_user_id=created_by_user_id,
            )
        )
        sale.status = (
            SaleStatus.PAID.value
            if payment_amount >= sale.total
            else SaleStatus.PARTIALLY_PAID.value
        )
        if sale.appointment_id:
            appointment = db.session.get(Appointment, sale.appointment_id)
            if auto_complete_appointment_if_ready(appointment):
                completed_appointment = appointment

    emit_live_event("sale:created", model_to_dict(sale), room=f"branch:{branch_id}")
    if completed_appointment:
        for room in appointment_room(
            completed_appointment.branch_id,
            completed_appointment.barber_id,
            completed_appointment.client_id,
        ):
            emit_live_event("appointment:completed", model_to_dict(completed_appointment), room=room)
    emit_live_event("stats:updated", {"branch_id": branch_id}, room=f"branch:{branch_id}")
    return sale
