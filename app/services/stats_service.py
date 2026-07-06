from sqlalchemy import func

from app.constants import AppointmentStatus, SaleStatus
from app.extensions import db
from app.modules.appointments.models import Appointment
from app.modules.barbers.models import Barber
from app.modules.branches.models import Branch
from app.modules.clients.models import Client
from app.modules.expenses.models import Expense
from app.modules.inventory.models import BranchProductStock
from app.modules.payments.models import Payment
from app.modules.products.models import Product
from app.modules.salaries.models import SalaryPayment
from app.modules.sales.models import Sale, SaleItem
from app.modules.services.models import Service
from app.utils.http import serialize_value


def _filters(query, model, filters):
    if filters.get("branch_id") and hasattr(model, "branch_id"):
        query = query.where(model.branch_id == int(filters["branch_id"]))
    if filters.get("from") and hasattr(model, "created_at"):
        query = query.where(model.created_at >= filters["from"])
    if filters.get("to") and hasattr(model, "created_at"):
        query = query.where(model.created_at <= filters["to"])
    return query


def overview(filters: dict) -> dict:
    sales_query = _filters(db.select(Sale), Sale, filters)
    sales = db.session.scalars(sales_query).all()
    sale_ids = [sale.id for sale in sales]

    appointments_query = _filters(db.select(Appointment), Appointment, filters)
    if filters.get("barber_id"):
        appointments_query = appointments_query.where(
            Appointment.barber_id == int(filters["barber_id"])
        )
    if filters.get("service_id"):
        appointments_query = appointments_query.where(
            Appointment.primary_service_id == int(filters["service_id"])
        )
    appointments = db.session.scalars(appointments_query).all()

    revenue_total = sum(sale.total for sale in sales if sale.status != SaleStatus.CANCELLED.value)
    discount_total = sum(sale.discount_amount for sale in sales if sale.status != SaleStatus.CANCELLED.value)
    sales_count = len(sales)
    paid_sales = [sale for sale in sales if sale.status == SaleStatus.PAID.value]
    average_ticket = revenue_total / len(paid_sales) if paid_sales else 0

    product_cost_total = 0
    if sale_ids:
        product_cost_total = db.session.scalar(
            db.select(func.coalesce(func.sum(SaleItem.total_cost), 0)).where(
                SaleItem.sale_id.in_(sale_ids)
            )
        )

    expense_query = db.select(func.coalesce(func.sum(Expense.amount), 0))
    salary_query = db.select(func.coalesce(func.sum(SalaryPayment.amount), 0))
    stock_value_query = (
        db.select(func.coalesce(func.sum(BranchProductStock.current_stock * Product.unit_cost), 0))
        .join(Product, Product.id == BranchProductStock.product_id)
    )
    if filters.get("branch_id"):
        branch_id = int(filters["branch_id"])
        expense_query = expense_query.where(Expense.branch_id == branch_id)
        salary_query = salary_query.where(SalaryPayment.branch_id == branch_id)
        stock_value_query = stock_value_query.where(BranchProductStock.branch_id == branch_id)

    total_expenses = db.session.scalar(expense_query)
    total_salaries = db.session.scalar(salary_query)
    stock_value_total = db.session.scalar(stock_value_query)
    gross_profit = revenue_total - product_cost_total
    net_profit = gross_profit - total_expenses - total_salaries

    return {
        "revenue_total": serialize_value(revenue_total),
        "discount_total": serialize_value(discount_total),
        "sales_count": sales_count,
        "appointments_total": len(appointments),
        "appointments_completed": sum(
            1 for item in appointments if item.status == AppointmentStatus.COMPLETED.value
        ),
        "appointments_cancelled": sum(
            1 for item in appointments if item.status == AppointmentStatus.CANCELLED.value
        ),
        "no_show_count": sum(
            1 for item in appointments if item.status == AppointmentStatus.NO_SHOW.value
        ),
        "clients_total": db.session.scalar(db.select(func.count(Client.id))),
        "new_clients": db.session.scalar(db.select(func.count(Client.id))),
        "average_ticket": serialize_value(average_ticket),
        "gross_profit": serialize_value(gross_profit),
        "net_profit": serialize_value(net_profit),
        "total_expenses": serialize_value(total_expenses),
        "total_salaries": serialize_value(total_salaries),
        "product_cost_total": serialize_value(product_cost_total),
        "stock_value_total": serialize_value(stock_value_total),
    }


def charts(filters: dict) -> dict:
    sales_by_day = db.session.execute(
        db.select(func.date(Sale.created_at), func.sum(Sale.total))
        .group_by(func.date(Sale.created_at))
        .order_by(func.date(Sale.created_at))
    ).all()
    payment_methods = db.session.execute(
        db.select(Payment.method, func.sum(Payment.amount)).group_by(Payment.method)
    ).all()
    weekday_expr = func.extract("dow", Appointment.starts_at)
    hour_expr = func.extract("hour", Appointment.starts_at)
    appointments_by_weekday = db.session.execute(
        db.select(weekday_expr, func.count(Appointment.id)).group_by(weekday_expr)
    ).all()
    appointments_by_hour = db.session.execute(
        db.select(hour_expr, func.count(Appointment.id)).group_by(hour_expr)
    ).all()
    top_products = db.session.execute(
        db.select(Product.name, func.sum(SaleItem.quantity), func.sum(SaleItem.total_price))
        .join(SaleItem, SaleItem.product_id == Product.id)
        .group_by(Product.name)
        .order_by(func.sum(SaleItem.quantity).desc())
        .limit(10)
    ).all()
    top_services = db.session.execute(
        db.select(Service.name, func.sum(SaleItem.quantity), func.sum(SaleItem.total_price))
        .join(SaleItem, SaleItem.service_id == Service.id)
        .group_by(Service.name)
        .order_by(func.sum(SaleItem.quantity).desc())
        .limit(10)
    ).all()
    top_barbers_by_appointments = db.session.execute(
        db.select(Barber.full_name, func.count(Appointment.id))
        .join(Appointment, Appointment.barber_id == Barber.id)
        .group_by(Barber.full_name)
        .order_by(func.count(Appointment.id).desc())
        .limit(10)
    ).all()
    top_clients_by_visits = db.session.execute(
        db.select(Client.full_name, func.count(Appointment.id))
        .join(Appointment, Appointment.client_id == Client.id)
        .group_by(Client.full_name)
        .order_by(func.count(Appointment.id).desc())
        .limit(10)
    ).all()
    branch_comparison = db.session.execute(
        db.select(Branch.name, func.coalesce(func.sum(Sale.total), 0))
        .join(Sale, Sale.branch_id == Branch.id)
        .group_by(Branch.name)
    ).all()
    stock_value_by_branch = db.session.execute(
        db.select(
            Branch.name,
            func.coalesce(func.sum(BranchProductStock.current_stock * Product.unit_cost), 0),
        )
        .join(BranchProductStock, BranchProductStock.branch_id == Branch.id)
        .join(Product, Product.id == BranchProductStock.product_id)
        .group_by(Branch.name)
    ).all()

    return {
        "sales_by_day": [{"date": row[0], "total": serialize_value(row[1])} for row in sales_by_day],
        "sales_by_month": [],
        "payment_method_distribution": [
            {"method": row[0], "total": serialize_value(row[1])} for row in payment_methods
        ],
        "appointments_by_weekday": [
            {"weekday": row[0], "total": row[1]} for row in appointments_by_weekday
        ],
        "appointments_by_hour": [
            {"hour": row[0], "total": row[1]} for row in appointments_by_hour
        ],
        "top_products": [
            {"name": row[0], "quantity": serialize_value(row[1]), "revenue": serialize_value(row[2])}
            for row in top_products
        ],
        "top_services": [
            {"name": row[0], "quantity": serialize_value(row[1]), "revenue": serialize_value(row[2])}
            for row in top_services
        ],
        "top_barbers_by_revenue": [],
        "top_barbers_by_appointments": [
            {"name": row[0], "appointments": row[1]} for row in top_barbers_by_appointments
        ],
        "top_clients_by_visits": [
            {"name": row[0], "visits": row[1]} for row in top_clients_by_visits
        ],
        "top_clients_by_revenue": [],
        "client_recency_buckets": [],
        "birthday_month_distribution": [],
        "branch_comparison": [
            {"branch": row[0], "revenue": serialize_value(row[1])} for row in branch_comparison
        ],
        "stock_value_by_branch": [
            {"branch": row[0], "stock_value": serialize_value(row[1])}
            for row in stock_value_by_branch
        ],
    }
