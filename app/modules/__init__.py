from app.modules.appointments.routes import (
    appointments_bp,
    barber_me_bp,
    client_me_bp,
    public_appointments_bp,
    public_availability_bp,
)
from app.modules.auth.routes import auth_bp
from app.modules.backups.routes import admin_backup_bp
from app.modules.barbers.routes import admin_barbers_bp, barbers_bp, public_barbers_bp
from app.modules.branches.routes import admin_branches_bp, public_branches_bp
from app.modules.clients.routes import client_profile_bp, clients_bp
from app.modules.expenses.routes import admin_expenses_bp
from app.modules.health.routes import health_bp
from app.modules.migrations.routes import admin_migrations_bp
from app.modules.payments.routes import payments_bp
from app.modules.products.routes import admin_products_bp
from app.modules.salaries.routes import admin_salaries_bp
from app.modules.sales.routes import sales_bp
from app.modules.services.routes import admin_services_bp, public_services_bp
from app.modules.stats.routes import admin_stats_bp
from app.modules.uploads.routes import uploads_bp
from app.modules.users.routes import admin_users_bp

# Imported so Flask-Migrate can discover SQLAlchemy models.
import app.models as audit_models  # noqa: F401
from app.modules.appointments import models as appointment_models  # noqa: F401
from app.modules.auth import models as auth_models  # noqa: F401
from app.modules.barbers import models as barber_models  # noqa: F401
from app.modules.branches import models as branch_models  # noqa: F401
from app.modules.clients import models as client_models  # noqa: F401
from app.modules.expenses import models as expense_models  # noqa: F401
from app.modules.inventory import models as inventory_models  # noqa: F401
from app.modules.payments import models as payment_models  # noqa: F401
from app.modules.products import models as product_models  # noqa: F401
from app.modules.salaries import models as salary_models  # noqa: F401
from app.modules.sales import models as sale_models  # noqa: F401
from app.modules.services import models as service_models  # noqa: F401
from app.modules.settings import models as setting_models  # noqa: F401


def register_blueprints(app):
    app.register_blueprint(health_bp, url_prefix="/api")
    app.register_blueprint(auth_bp, url_prefix="/api/auth")

    app.register_blueprint(public_branches_bp, url_prefix="/api/public")
    app.register_blueprint(public_barbers_bp, url_prefix="/api/public")
    app.register_blueprint(public_services_bp, url_prefix="/api/public")
    app.register_blueprint(public_availability_bp, url_prefix="/api/public")
    app.register_blueprint(public_appointments_bp, url_prefix="/api/public")

    app.register_blueprint(admin_branches_bp, url_prefix="/api/admin")
    app.register_blueprint(admin_users_bp, url_prefix="/api/admin")
    app.register_blueprint(admin_barbers_bp, url_prefix="/api/admin")
    app.register_blueprint(admin_services_bp, url_prefix="/api/admin")
    app.register_blueprint(admin_products_bp, url_prefix="/api/admin")
    app.register_blueprint(admin_expenses_bp, url_prefix="/api/admin")
    app.register_blueprint(admin_salaries_bp, url_prefix="/api/admin")
    app.register_blueprint(admin_stats_bp, url_prefix="/api/admin")
    app.register_blueprint(admin_backup_bp, url_prefix="/api/admin")
    app.register_blueprint(admin_migrations_bp, url_prefix="/api/admin")

    app.register_blueprint(clients_bp, url_prefix="/api/clients")
    app.register_blueprint(client_profile_bp, url_prefix="/api/client")
    app.register_blueprint(barbers_bp, url_prefix="/api/barbers")
    app.register_blueprint(appointments_bp, url_prefix="/api/appointments")
    app.register_blueprint(barber_me_bp, url_prefix="/api/barber")
    app.register_blueprint(client_me_bp, url_prefix="/api/client")
    app.register_blueprint(sales_bp, url_prefix="/api/sales")
    app.register_blueprint(payments_bp, url_prefix="/api/payments")
    app.register_blueprint(uploads_bp, url_prefix="/api/uploads")
