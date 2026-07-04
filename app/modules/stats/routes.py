from io import BytesIO

from flask import Blueprint, request, send_file
from openpyxl import Workbook

from app.constants import Role
from app.security import roles_required
from app.services.stats_service import charts, overview

admin_stats_bp = Blueprint("admin_stats", __name__)


@admin_stats_bp.get("/stats/overview")
@roles_required([Role.ADMIN])
def stats_overview():
    return overview(request.args.to_dict())


@admin_stats_bp.get("/stats/charts")
@roles_required([Role.ADMIN])
def stats_charts():
    return charts(request.args.to_dict())


@admin_stats_bp.get("/stats/export.json")
@roles_required([Role.ADMIN])
def export_stats_json():
    filters = request.args.to_dict()
    return {"overview": overview(filters), "charts": charts(filters)}


@admin_stats_bp.get("/stats/export.xlsx")
@roles_required([Role.ADMIN])
def export_stats_xlsx():
    data = overview(request.args.to_dict())
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "NUB Stats"
    sheet.append(["metric", "value"])
    for key, value in data.items():
        sheet.append([key, value])
    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return send_file(
        buffer,
        as_attachment=True,
        download_name="nub-stats.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
