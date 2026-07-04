from flask import Blueprint

health_bp = Blueprint("health", __name__)


@health_bp.get("/health")
def healthcheck():
    return {
        "status": "ok",
        "service": "nub-back-system",
        "version": "0.1.0",
    }
