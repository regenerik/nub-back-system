from datetime import date, datetime, time
from decimal import Decimal

from flask import request


def get_json_payload() -> dict:
    return request.get_json(silent=True) or {}


def parse_iso_datetime(value: str) -> datetime:
    if not value:
        raise ValueError("Fecha/hora requerida.")
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


def parse_optional_date(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def parse_optional_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    return parse_iso_datetime(value)


def parse_date_time(payload: dict) -> datetime:
    starts_at = payload.get("starts_at")
    if starts_at:
        parsed = parse_iso_datetime(starts_at)
        validate_quarter_hour(parsed)
        return parsed
    date_value = payload.get("date")
    time_value = payload.get("time")
    if not date_value or not time_value:
        raise ValueError("Enviar starts_at o date/time.")
    parsed_date = date.fromisoformat(date_value)
    parsed_time = time.fromisoformat(time_value)
    parsed = datetime.combine(parsed_date, parsed_time)
    validate_quarter_hour(parsed)
    return parsed


def validate_quarter_hour(value: datetime):
    if value.minute % 15 != 0 or value.second != 0 or value.microsecond != 0:
        raise ValueError("Los turnos solo se pueden guardar en horarios de 15 minutos: 00, 15, 30 o 45.")


def serialize_value(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def model_to_dict(model, exclude: set[str] | None = None) -> dict:
    exclude = exclude or set()
    return {
        column.name: serialize_value(getattr(model, column.name))
        for column in model.__table__.columns
        if column.name not in exclude
    }


def list_response(items):
    return {"items": [model_to_dict(item) for item in items]}


def validation_error(message: str, status: int = 400):
    return {"message": message}, status
