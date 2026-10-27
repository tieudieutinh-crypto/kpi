"""routes/reports.py - Báo cáo tổng hợp theo Mẫu 6, Mẫu 7, Mẫu 8 (Hướng dẫn 07)."""
from flask import Blueprint, abort, render_template, request, send_file
from flask_login import current_user

from models import Period, Rating
from permissions import permission_required
from services import reports as svc

bp = Blueprint("reports", __name__, url_prefix="/reports")

FORMS = {"m6": "Mẫu 6", "m7": "Mẫu 7", "m8": "Mẫu 8"}


def _period(periods):
    period_id = request.args.get("period", type=int)
    return next((p for p in periods if p.id == period_id), None) or \
        next((p for p in periods if p.status == "open"), None) or (periods[0] if periods else None)


@bp.route("/<form>/export")
@permission_required("report.view")
def export(form):
    from services import export_excel as xl
    if form not in FORMS:
        abort(404)
    period = _period(Period.query.order_by(Period.year.desc(), Period.quarter.desc()).all())
    if period is None:
        abort(404)
    if form == "m6":
        name, buf = xl.mau6(svc.mau6(current_user, period), period)
    else:
        name, buf = xl.mau78(svc.mau78(current_user, period, form.upper()), period, form)
    return send_file(buf, mimetype=xl.XLSX, as_attachment=True, download_name=name)


@bp.route("/")
@bp.route("/<form>")
@permission_required("report.view")
def index(form="m6"):
    if form not in FORMS:
        abort(404)
    periods = Period.query.order_by(Period.year.desc(), Period.quarter.desc()).all()
    period_id = request.args.get("period", type=int)
    period = next((p for p in periods if p.id == period_id), None) or \
        next((p for p in periods if p.status == "open"), None) or (periods[0] if periods else None)
    data = None
    if period:
        data = svc.mau6(current_user, period) if form == "m6" else svc.mau78(current_user, period, form.upper())
    return render_template("reports.html", form=form, forms=FORMS, periods=periods, period=period, data=data,
                           rating_labels=dict(Rating.CHOICES))
