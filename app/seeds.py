from datetime import date, datetime, time, timedelta
from decimal import Decimal

from app.constants import Role, ServiceType
from app.extensions import db
from app.modules.appointments.models import BarberAvailability
from app.modules.auth.models import User
from app.modules.barbers.models import Barber, BarberBranch
from app.modules.branches.models import Branch
from app.modules.clients.models import Client
from app.modules.expenses.models import Expense
from app.modules.inventory.models import BranchProductStock
from app.modules.products.models import Product
from app.modules.salaries.models import SalaryPayment
from app.modules.services.models import BranchService, Service


def _user(email: str, name: str, role: Role, password: str, discounts=False) -> User:
    user = db.session.scalar(db.select(User).where(User.email == email))
    if user:
        return user
    user = User(
        email=email,
        full_name=name,
        role=role.value,
        can_apply_discounts=discounts,
    )
    user.set_password(password)
    db.session.add(user)
    db.session.flush()
    return user


def seed_initial_data() -> None:
    branch_names = [
        ("Caballito", "Av. Pedro Goyena 123", "1122334455", "NUB Centro"),
        ("Palermo", "Gorriti 456", "1166778899", "NUB Norte"),
    ]
    branches = []
    for name, address, phone, previous_name in branch_names:
        branch = db.session.scalar(db.select(Branch).where(Branch.name.in_([name, previous_name])))
        if not branch:
            branch = Branch(name=name, address=address, phone=phone, is_active=True)
            db.session.add(branch)
            db.session.flush()
        else:
            branch.name = name
            branch.address = address
            branch.phone = phone
        branches.append(branch)

    admin = _user("admin@example.com", "Admin NUB", Role.ADMIN, "Admin123!", True)
    _user("recepcion@example.com", "Recepcion NUB", Role.RECEPCION, "Recepcion123!", True)
    barber_user = _user("barbero@example.com", "Barbero NUB", Role.BARBERO, "Barbero123!")
    _user("cliente@example.com", "Cliente NUB", Role.CLIENTE, "Cliente123!")

    barber_names = ["Tomas Nava", "Leo Barrera", "Mauro Silva"]
    barbers = []
    for index, name in enumerate(barber_names):
        barber = db.session.scalar(db.select(Barber).where(Barber.full_name == name))
        if not barber:
            barber = Barber(
                user_id=barber_user.id if index == 0 else None,
                full_name=name,
                email=f"barbero{index + 1}@example.com",
                commission_percentage=Decimal("40"),
                fixed_salary=Decimal("0"),
                is_active=True,
            )
            db.session.add(barber)
            db.session.flush()
        barbers.append(barber)
        for branch in branches:
            if not db.session.scalar(
                db.select(BarberBranch).where(
                    BarberBranch.barber_id == barber.id,
                    BarberBranch.branch_id == branch.id,
                )
            ):
                db.session.add(BarberBranch(barber_id=barber.id, branch_id=branch.id))
            for weekday in range(0, 6):
                if not db.session.scalar(
                    db.select(BarberAvailability).where(
                        BarberAvailability.barber_id == barber.id,
                        BarberAvailability.branch_id == branch.id,
                        BarberAvailability.weekday == weekday,
                    )
                ):
                    db.session.add(
                        BarberAvailability(
                            barber_id=barber.id,
                            branch_id=branch.id,
                            weekday=weekday,
                            start_time="09:00",
                            end_time="18:00",
                        )
                    )

    services = [
        ("Corte", 45, "7500", ServiceType.MAIN),
        ("Corte + barba", 70, "10500", ServiceType.MAIN),
        ("Barba", 35, "5000", ServiceType.MAIN),
        ("Perfilado", 30, "4200", ServiceType.MAIN),
        ("Color", 90, "16000", ServiceType.MAIN),
        ("Cejas", 15, "2500", ServiceType.EXTRA),
        ("Lavado", 15, "2200", ServiceType.EXTRA),
        ("Tratamiento", 30, "6000", ServiceType.EXTRA),
        ("Diseño", 20, "3500", ServiceType.EXTRA),
        ("Producto aplicado", 10, "1800", ServiceType.EXTRA),
    ]
    for name, duration, price, service_type in services:
        service = db.session.scalar(db.select(Service).where(Service.name == name))
        if not service:
            service = Service(
                name=name,
                duration_minutes=duration,
                price=Decimal(price),
                cost_estimate=Decimal("0"),
                service_type=service_type.value,
            )
            db.session.add(service)
            db.session.flush()
        for branch in branches:
            if not db.session.scalar(
                db.select(BranchService).where(
                    BranchService.branch_id == branch.id,
                    BranchService.service_id == service.id,
                )
            ):
                db.session.add(BranchService(branch_id=branch.id, service_id=service.id))

    for index in range(1, 9):
        product = db.session.scalar(db.select(Product).where(Product.sku == f"NUB-{index:03}"))
        if not product:
            product = Product(
                name=f"Producto {index}",
                sku=f"NUB-{index:03}",
                sale_price=Decimal("4500") + index,
                unit_cost=Decimal("2500") + index,
            )
            db.session.add(product)
            db.session.flush()
        for branch in branches:
            stock = db.session.scalar(
                db.select(BranchProductStock).where(
                    BranchProductStock.branch_id == branch.id,
                    BranchProductStock.product_id == product.id,
                )
            )
            if not stock:
                db.session.add(
                    BranchProductStock(
                        branch_id=branch.id,
                        product_id=product.id,
                        current_stock=20,
                        min_stock=3,
                    )
                )

    if not db.session.scalar(db.select(Client).where(Client.email == "cliente@example.com")):
        db.session.add(
            Client(
                full_name="Cliente Demo",
                first_name="Cliente",
                last_name="Demo",
                email="cliente@example.com",
                phone="1100000000",
                dni="12345678",
            )
        )

    if not db.session.scalar(
        db.select(Expense).where(
            Expense.branch_id == branches[0].id,
            Expense.category == "alquiler",
            Expense.description == "Gasto demo",
        )
    ):
        db.session.add(
            Expense(
                branch_id=branches[0].id,
                category="alquiler",
                description="Gasto demo",
                amount=Decimal("120000"),
                expense_date=date.today(),
                created_by_user_id=admin.id,
            )
        )
    if not db.session.scalar(
        db.select(SalaryPayment).where(
            SalaryPayment.branch_id == branches[0].id,
            SalaryPayment.barber_id == barbers[0].id,
            SalaryPayment.period_start == date.today().replace(day=1),
        )
    ):
        db.session.add(
            SalaryPayment(
                branch_id=branches[0].id,
                barber_id=barbers[0].id,
                amount=Decimal("80000"),
                period_start=date.today().replace(day=1),
                period_end=date.today(),
                paid_at=datetime.combine(date.today(), time(hour=12)),
                created_by_user_id=admin.id,
            )
        )
    db.session.commit()
