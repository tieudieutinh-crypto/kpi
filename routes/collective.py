"""routes/collective.py - KPI tập thể của Phòng, Ban: chỉ tiêu (Mẫu 1), kết quả (Mẫu 2).
Chỉ Phó Trưởng Ban Thường trực của Ban được lập, sửa, trình; Phó Bí thư Thường trực duyệt cuối."""
from flask import (
    Blueprint, abort, flash, jsonify, redirect, render_template, request, send_file, url_for,
)
from flask_login import current_user

from models import (
    Axis, CollectiveEvaluation, CollectiveStatus, Department, Period, Rating, db,
)
from permissions import (
    can_approve_collective, can_edit_collective, can_view_collective, permission_required,
    viewable_departments,
)
from services import collective as svc
from services.auth import ValidationError
from services.common import WorkflowError
from services.workflow import logs_for

bp = Blueprint("collective", __name__, url_prefix="/collective")


def _flash_errors(exc):
    for message in (exc.messages if isinstance(exc, WorkflowError) else exc.errors):
        flash(message, "error")


def _context(period_id, dept_id):
    period = db.get_or_404(Period, period_id)
    dept = db.get_or_404(Department, dept_id)
    if not can_view_collective(current_user, dept.id):
        abort(403)
    return period, dept


def _editor_ce(period_id, dept_id):
    period, dept = _context(period_id, dept_id)
    ce = CollectiveEvaluation.query.filter_by(period_id=period.id, department_id=dept.id).first()
    if ce is None:
        abort(404)
    return ce


def _run(ce, fn, success, *args):
    try:
        fn(ce, current_user, *args)
        flash(success, "success")
    except (WorkflowError, ValidationError) as exc:
        db.session.rollback()
        _flash_errors(exc)
    return redirect(url_for("collective.view", period_id=ce.period_id, dept_id=ce.department_id))


@bp.route("/")
@permission_required("indicator.view")
def index():
    periods = Period.query.order_by(Period.year.desc(), Period.quarter.desc()).all()
    period_id = request.args.get("period", type=int)
    if period_id is None and periods:
        period_id = ([p for p in periods if p.status == "open"] or periods)[0].id
    depts = viewable_departments(current_user)
    if len(depts) == 1 and period_id and not request.args.get("list"):
        return redirect(url_for("collective.view", period_id=period_id, dept_id=depts[0].id))
    existing = {}
    if period_id:
        existing = {c.department_id: c for c in CollectiveEvaluation.query.filter_by(period_id=period_id)}
    return render_template("collective_list.html", periods=periods, period_id=period_id,
                           depts=depts, existing=existing)


@bp.route("/<int:period_id>/<int:dept_id>")
@permission_required("indicator.view")
def view(period_id, dept_id):
    period, dept = _context(period_id, dept_id)
    open_ = period.status == "open"
    can_edit_dept = can_edit_collective(current_user, dept.id)
    ce = CollectiveEvaluation.query.filter_by(period_id=period.id, department_id=dept.id).first()
    if ce is None:
        if not (can_edit_dept and open_):
            return render_template("collective_edit.html", period=period, dept=dept, ce=None, data=None,
                                   editable=False, can_edit_dept=can_edit_dept)
        ce = svc.get_or_create(period, dept)

    edit_m1 = can_edit_dept and open_ and ce.status == CollectiveStatus.DRAFT
    edit_m2 = can_edit_dept and open_ and ce.result_open and ce.result_status == CollectiveStatus.DRAFT
    editable = edit_m1 or edit_m2
    approver = can_approve_collective(current_user, dept.id)
    data = {
        "col": svc.payload(ce),
        "axes": [{"id": a.id, "number": a.number, "name": a.name} for a in Axis.query.order_by(Axis.number)],
        "leaders": svc.leader_options(dept.id),
        "editable": editable, "editM1": edit_m1, "editM2": edit_m2,
        "saveUrl": url_for("collective.save", period_id=period.id, dept_id=dept.id),
        "saveResultsUrl": url_for("collective.save_results", period_id=period.id, dept_id=dept.id),
    }
    return render_template(
        "collective_edit.html", period=period, dept=dept, ce=ce, data=data, editable=editable,
        can_submit=editable, can_edit_dept=can_edit_dept, edit_m1=edit_m1, edit_m2=edit_m2,
        can_withdraw=can_edit_dept and open_ and ce.status == CollectiveStatus.SUBMITTED,
        can_approve=approver and open_ and ce.status == CollectiveStatus.SUBMITTED,
        can_reopen=approver and open_ and ce.status == CollectiveStatus.APPROVED,
        m2_withdraw=can_edit_dept and open_ and ce.result_open and ce.result_status == CollectiveStatus.SUBMITTED,
        m2_approve=approver and open_ and ce.result_open and ce.result_status == CollectiveStatus.SUBMITTED,
        m2_reopen=approver and open_ and ce.result_status == CollectiveStatus.APPROVED,
        ratings=Rating.CHOICES, logs=logs_for("collective", ce.id),
    )


@bp.route("/<int:period_id>/<int:dept_id>/save", methods=["POST"])
@permission_required("indicator.manage")
def save(period_id, dept_id):
    ce = _editor_ce(period_id, dept_id)
    if not can_edit_collective(current_user, ce.department_id):
        abort(403)
    try:
        svc.save(ce, request.get_json(silent=True))
    except ValidationError as exc:
        db.session.rollback()
        return jsonify(ok=False, errors=exc.errors), 400
    except WorkflowError as exc:
        db.session.rollback()
        return jsonify(ok=False, errors=exc.messages), 409
    return jsonify(ok=True, data=svc.payload(ce))


@bp.route("/<int:period_id>/<int:dept_id>/submit", methods=["POST"])
@permission_required("indicator.manage")
def submit(period_id, dept_id):
    return _run(_editor_ce(period_id, dept_id), svc.submit, "Đã trình Mẫu 1, chờ lãnh đạo cơ quan duyệt.")


@bp.route("/<int:period_id>/<int:dept_id>/withdraw", methods=["POST"])
@permission_required("indicator.manage")
def withdraw(period_id, dept_id):
    return _run(_editor_ce(period_id, dept_id), svc.withdraw, "Đã thu hồi về bản nháp.")


@bp.route("/<int:period_id>/<int:dept_id>/approve", methods=["POST"])
@permission_required("indicator.approve")
def approve(period_id, dept_id):
    return _run(_editor_ce(period_id, dept_id), svc.approve, "Đã duyệt Mẫu 1. Đơn vị có thể nhập kết quả ở Mẫu 2.")


@bp.route("/<int:period_id>/<int:dept_id>/return", methods=["POST"])
@permission_required("indicator.approve")
def return_back(period_id, dept_id):
    return _run(_editor_ce(period_id, dept_id), lambda c, u: svc.return_(c, u, request.form.get("note")),
                "Đã trả lại để đơn vị chỉnh sửa.")


@bp.route("/<int:period_id>/<int:dept_id>/reopen", methods=["POST"])
@permission_required("indicator.approve")
def reopen(period_id, dept_id):
    return _run(_editor_ce(period_id, dept_id), svc.reopen, "Đã mở lại Mẫu 1 để điều chỉnh; Mẫu 2 tạm khóa.")


# --------------------------------------------------------------------------- #
# Mẫu 2: kết quả thực hiện
# --------------------------------------------------------------------------- #
@bp.route("/<int:period_id>/<int:dept_id>/results/save", methods=["POST"])
@permission_required("indicator.manage")
def save_results(period_id, dept_id):
    ce = _editor_ce(period_id, dept_id)
    if not can_edit_collective(current_user, ce.department_id):
        abort(403)
    try:
        svc.save_results(ce, request.get_json(silent=True))
    except ValidationError as exc:
        db.session.rollback()
        return jsonify(ok=False, errors=exc.errors), 400
    except WorkflowError as exc:
        db.session.rollback()
        return jsonify(ok=False, errors=exc.messages), 409
    return jsonify(ok=True, data=svc.payload(ce))


@bp.route("/<int:period_id>/<int:dept_id>/results/submit", methods=["POST"])
@permission_required("indicator.manage")
def submit_results(period_id, dept_id):
    return _run(_editor_ce(period_id, dept_id), svc.submit_results, "Đã trình Mẫu 2, chờ lãnh đạo cơ quan duyệt.")


@bp.route("/<int:period_id>/<int:dept_id>/results/withdraw", methods=["POST"])
@permission_required("indicator.manage")
def withdraw_results(period_id, dept_id):
    return _run(_editor_ce(period_id, dept_id), svc.withdraw_results, "Đã thu hồi Mẫu 2 về bản nháp.")


@bp.route("/<int:period_id>/<int:dept_id>/results/approve", methods=["POST"])
@permission_required("indicator.approve")
def approve_results(period_id, dept_id):
    return _run(_editor_ce(period_id, dept_id),
                lambda c, u: svc.approve_results(c, u, request.form.get("rating")), "Đã duyệt Mẫu 2.")


@bp.route("/<int:period_id>/<int:dept_id>/results/return", methods=["POST"])
@permission_required("indicator.approve")
def return_results(period_id, dept_id):
    return _run(_editor_ce(period_id, dept_id),
                lambda c, u: svc.return_results(c, u, request.form.get("note")), "Đã trả lại Mẫu 2 để chỉnh sửa.")


@bp.route("/<int:period_id>/<int:dept_id>/results/reopen", methods=["POST"])
@permission_required("indicator.approve")
def reopen_results(period_id, dept_id):
    return _run(_editor_ce(period_id, dept_id), svc.reopen_results, "Đã mở lại Mẫu 2 để điều chỉnh.")



@bp.route("/<int:period_id>/<int:dept_id>/export/<form>")
@permission_required("indicator.view")
def export(period_id, dept_id, form):
    """Xuất Mẫu 1, Mẫu 2 của đơn vị ra Excel - cùng quyền với khi xem trang."""
    from services import export_excel as xl
    ce = _editor_ce(period_id, dept_id)
    if form == "m1":
        name, buf = xl.mau1(ce, svc.indicators_of(ce), svc.leader_options(ce.department_id))
    elif form == "m2" and ce.result_open:
        name, buf = xl.mau2(ce, svc.indicators_of(ce))
    else:
        abort(404)
    return send_file(buf, mimetype=xl.XLSX, as_attachment=True, download_name=name)
