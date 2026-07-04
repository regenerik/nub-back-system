from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"
    RECEPCION = "recepcion"
    BARBERO = "barbero"
    CLIENTE = "cliente"


class AppointmentStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CHECKED_IN = "checked_in"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"
    RESCHEDULED = "rescheduled"
    PENDING_RESCHEDULE = "pending_reschedule"


class PaymentMethod(StrEnum):
    EFECTIVO = "efectivo"
    TRANSFERENCIA = "transferencia"
    TARJETA_DEBITO = "tarjeta_debito"
    TARJETA_CREDITO = "tarjeta_credito"
    MERCADO_PAGO = "mercado_pago"
    OTRO = "otro"


class SaleStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    PARTIALLY_PAID = "partially_paid"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class ServiceType(StrEnum):
    MAIN = "main"
    EXTRA = "extra"
    BOTH = "both"


class SaleItemKind(StrEnum):
    SERVICE = "service"
    PRODUCT = "product"


class AppointmentSource(StrEnum):
    PUBLIC = "public"
    RECEPTION = "reception"
    ADMIN = "admin"
    CLIENT_PANEL = "client_panel"


class StockMovementType(StrEnum):
    PURCHASE = "purchase"
    SALE = "sale"
    ADJUSTMENT = "adjustment"
    RETURN = "return"
