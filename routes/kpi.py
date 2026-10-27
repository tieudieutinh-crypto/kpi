"""routes/kpi.py - KPI cá nhân: lập danh mục, tự chấm điểm, gửi, nhận xét, phê duyệt (Mẫu 3, 4, 5)."""
from flask import (
    Blueprint, abort, flash, jsonify, redirect, render_template, request, send_file, url_for,
)
from flask_login import current_user

from models import (
    Axis, CommonCriterion, EvalStatus, Period, PersonalEvaluation, PlanStatus, Rating, ResponseLevel, User, db,
)
from permissions import (
    can, can_approve_user, can_review_user, can_view_evaluation, needs_submission, permission_required,
)
from services import kpi as svc
from services.auth import ValidationError
from services.common import WorkflowError
from services.workflow import logs_for

bp = Blueprint("kpi", __name__, url_prefix="/kpi")

PENDING = (EvalStatus.SELF_SCORED, EvalStatus.REVIEWED)
PLAN_PENDING = (PlanStatus.SUBMITTED, PlanStatus.BAN_APPROVED)


def plan_action_for(actor, ev) -> str | None:
    """Việc actor cần làm với Mẫu 3 của ev: 'ban' (lãnh đạo Ban duyệt), 'final' (duyệt cuối) hoặc None."""
    if ev.plan_status == PlanStatus.SUBMITTED and can_review_user(actor, ev.user):
        return "ban"
    if svc.can_final_approve_plan(ev, actor):
        return "final"
    return None


def eval_action_for(actor, ev) -> bool:
    return ev.status in PENDING and (can_review_user(actor, ev.user) or can_approve_user(actor, ev.user))


def pending_count(actor, period_id) -> int:
    """Số hồ sơ (Mẫu 3 hoặc Mẫu 5) đang chờ actor xử lý trong kỳ."""
    if not (can("kpi.review", actor) or can("kpi.approve", actor)) or not period_id:
        return 0
    evs = PersonalEvaluation.query.filter(
        PersonalEvaluation.period_id == period_id,
        PersonalEvaluation.status.in_(PENDING) | PersonalEvaluation.plan_status.in_(PLAN_PENDING)).all()
    return sum(1 for e in evs if plan_action_for(actor, e) or eval_action_for(actor, e))


def _flash_errors(exc):
    for message in (exc.messages if isinstance(exc, WorkflowError) else exc.errors):
        flash(message, "error")


def _load(eid: int) -> PersonalEvaluation:
    ev = db.get_or_404(PersonalEvaluation, eid)
    if not can_view_evaluation(current_user, ev):
        abort(403)
    return ev


def _owner_only(ev):
    if ev.user_id != current_user.id:
        abort(403)


def _run(ev, fn, success, *args):
    """Chạy một bước của luồng; báo lỗi nếu không hợp lệ; luôn quay về trang hồ sơ."""
    try:
        fn(ev, current_user, *args)
        flash(success, "success")
    except (WorkflowError, ValidationError) as exc:
        db.session.rollback()
        _flash_errors(exc)
    return redirect(url_for("kpi.view", eid=ev.id))


# --------------------------------------------------------------------------- #
@bp.route("/")
@permission_required("kpi.self")
def mine():
    periods = Period.query.order_by(Period.year.desc(), Period.quarter.desc()).all()
    evals = {e.period_id: e for e in PersonalEvaluation.query.filter_by(user_id=current_user.id).all()}
    return render_template("kpi_mine.html", periods=periods, evals=evals)


@bp.route("/start/<int:period_id>", methods=["POST"])
@permission_required("kpi.self")
def start(period_id):
    period = db.get_or_404(Period, period_id)
    if period.status != "open":
        flash(f"{period.name} đã đóng.", "error")
        return redirect(url_for("kpi.mine"))
    ev = svc.get_or_create_evaluation(current_user._get_current_object(), period)
    return redirect(url_for("kpi.view", eid=ev.id))


@bp.route("/queue")
@permission_required("kpi.review", "kpi.approve")
def queue():
    periods = Period.query.order_by(Period.year.desc(), Period.quarter.desc()).all()
    period_id = request.args.get("period", type=int)
    if period_id is None and periods:
        open_ones = [p for p in periods if p.status == "open"]
        period_id = (open_ones or periods)[0].id
    mode = request.args.get("status", "pending")

    query = PersonalEvaluation.query.join(User, User.id == PersonalEvaluation.user_id)
    if period_id:
        query = query.filter(PersonalEvaluation.period_id == period_id)
    rows = []
    if mode == "done":
        for e in query.filter(PersonalEvaluation.status.in_((EvalStatus.APPROVED, EvalStatus.PUBLISHED))) \
                      .order_by(User.full_name).all():
            if can_review_user(current_user, e.user) or can_approve_user(current_user, e.user):
                rows.append({"ev": e, "form": "Mẫu 5", "task": "Đã duyệt"})
    else:
        cands = query.filter(PersonalEvaluation.status.in_(PENDING)
                             | PersonalEvaluation.plan_status.in_(PLAN_PENDING)).order_by(User.full_name).all()
        for e in cands:
            act = plan_action_for(current_user, e)
            if act:
                rows.append({"ev": e, "form": "Mẫu 3",
                             "task": "Duyệt cấp Ban" if act == "ban" else "Duyệt cuối"})
            if eval_action_for(current_user, e):
                rows.append({"ev": e, "form": "Mẫu 5",
                             "task": "Nhận xét" if e.status == EvalStatus.SELF_SCORED and can_review_user(current_user, e.user)
                             else "Quyết định xếp loại"})
    return render_template("kpi_queue.html", rows=rows, periods=periods, period_id=period_id, mode=mode)


@bp.route("/<int:eid>")
@permission_required("kpi.self", "kpi.review", "kpi.approve", "kpi.reopen_plan")
def view(eid):
    ev = _load(eid)
    owner = ev.user
    open_ = ev.period.status == "open"
    is_owner = ev.user_id == current_user.id
    stage = svc.stage(ev)
    editable = is_owner and ev.status == EvalStatus.DRAFT and open_ and stage != "plan_locked"
    reviewer = can_review_user(current_user, owner)
    approver = can_approve_user(current_user, owner)
    plan_act = plan_action_for(current_user, ev) if open_ else None

    data = {
        "eval": svc.evaluation_payload(ev),
        "axes": [{"id": a.id, "number": a.number, "name": a.name} for a in Axis.query.order_by(Axis.number)],
        "criteria": [{"id": c.id, "code": c.code, "group_no": c.group_no, "group_title": c.group_title,
                      "title": c.title, "max_score": c.max_score}
                     for c in CommonCriterion.query.order_by(CommonCriterion.sort)],
        "coef": svc.coefficient_table(),
        "indicators": svc.department_indicators(ev),
        "editable": editable,
        "stage": stage,
        "leadership": owner.has_leadership_kpi,
        "needsSubmission": needs_submission(owner),
        "saveUrl": url_for("kpi.save", eid=ev.id),
        "limits": {"result_max": 70, "common_max": 30, "task_max": 200, "task_std": 100},
    }
    result_hidden = not is_owner and ev.status == EvalStatus.DRAFT
    if result_hidden:                   # Mẫu 4, 5 đang tự chấm: người khác chưa được xem số liệu nháp
        data["eval"] = dict(data["eval"], items=[], axes=[], warnings=[], self_rating="", self_comment="",
                            common=[], totals={"common": 0, "result": 0, "total": 0})
    prev = svc.previous_evaluation(ev)
    return render_template(
        "kpi_edit.html", ev=ev, owner=owner, data=data, editable=editable, is_owner=is_owner, stage=stage,
        result_hidden=result_hidden,
        needs_submission=needs_submission(owner), plan_act=plan_act,
        can_plan_return=bool(plan_act) and open_,
        can_plan_reopen=svc.can_reopen_plan(ev, current_user) and open_,
        PlanStatus=PlanStatus,
        can_withdraw=is_owner and ev.status == EvalStatus.SELF_SCORED and open_,
        can_review=reviewer and ev.status == EvalStatus.SELF_SCORED and open_,
        can_approve=approver and ev.status in PENDING and open_,
        can_return=(reviewer or approver) and ev.status in PENDING and open_,
        can_reopen=approver and ev.status == EvalStatus.APPROVED and open_,
        can_copy=editable and stage == "plan" and not ev.items and svc.previous_evaluation(ev) is not None,
        prev=prev, logs=logs_for("personal", ev.id), warnings=data["eval"]["warnings"],
        ratings=Rating.CHOICES, levels=ResponseLevel.CHOICES, coef=data["coef"],
    )


@bp.route("/<int:eid>/save", methods=["POST"])
@permission_required("kpi.self")
def save(eid):
    ev = _load(eid)
    _owner_only(ev)
    try:
        svc.save_evaluation(ev, request.get_json(silent=True))
    except ValidationError as exc:
        db.session.rollback()
        return jsonify(ok=False, errors=exc.errors), 400
    except WorkflowError as exc:
        db.session.rollback()
        return jsonify(ok=False, errors=exc.messages), 409
    return jsonify(ok=True, data=svc.evaluation_payload(ev))


@bp.route("/<int:eid>/submit", methods=["POST"])
@permission_required("kpi.self")
def submit(eid):
    ev = _load(eid)
    _owner_only(ev)
    return _run(ev, svc.submit_evaluation, "Đã gửi hồ sơ. Chờ cấp có thẩm quyền nhận xét, phê duyệt.")


@bp.route("/<int:eid>/plan/submit", methods=["POST"])
@permission_required("kpi.self")
def plan_submit(eid):
    ev = _load(eid)
    _owner_only(ev)
    return _run(ev, svc.submit_plan, "Đã trình Mẫu 3. Mẫu 3 bị khóa trong khi chờ duyệt.")


@bp.route("/<int:eid>/plan/lock", methods=["POST"])
@permission_required("kpi.self")
def plan_lock(eid):
    ev = _load(eid)
    _owner_only(ev)
    return _run(ev, svc.lock_plan, "Đã chốt Mẫu 3. Bạn có thể chuyển sang Bước 2 · Mẫu 4.")


@bp.route("/<int:eid>/plan/approve", methods=["POST"])
@permission_required("kpi.review", "kpi.approve")
def plan_approve(eid):
    ev = _load(eid)
    act = plan_action_for(current_user, ev)
    if act == "ban":
        return _run(ev, svc.ban_approve_plan, "Đã duyệt Mẫu 3, chuyển lãnh đạo cơ quan duyệt cuối.")
    return _run(ev, svc.approve_plan, "Đã duyệt cuối Mẫu 3. Cán bộ có thể thực hiện Mẫu 4.")


@bp.route("/<int:eid>/plan/return", methods=["POST"])
@permission_required("kpi.review", "kpi.approve")
def plan_return(eid):
    ev = _load(eid)
    return _run(ev, lambda e, u: svc.return_plan(e, u, request.form.get("note")), "Đã trả lại Mẫu 3 để chỉnh sửa.")


@bp.route("/<int:eid>/plan/reopen", methods=["POST"])
@permission_required("kpi.reopen_plan")
def plan_reopen(eid):
    ev = _load(eid)
    return _run(ev, svc.reopen_plan, "Đã mở lại Mẫu 3 để điều chỉnh.")


@bp.route("/<int:eid>/withdraw", methods=["POST"])
@permission_required("kpi.self")
def withdraw(eid):
    ev = _load(eid)
    _owner_only(ev)
    return _run(ev, svc.withdraw_evaluation, "Đã thu hồi hồ sơ về bản nháp.")


@bp.route("/<int:eid>/copy-previous", methods=["POST"])
@permission_required("kpi.self")
def copy_previous(eid):
    ev = _load(eid)
    _owner_only(ev)
    try:
        n = svc.copy_plan_from_previous(ev)
        flash(f"Đã sao chép {n} nhiệm vụ từ quý trước (chỉ phần kế hoạch; hãy nhập lại kết quả thực tế).", "success")
    except WorkflowError as exc:
        _flash_errors(exc)
    return redirect(url_for("kpi.view", eid=ev.id))


@bp.route("/<int:eid>/review", methods=["POST"])
@permission_required("kpi.review")
def review(eid):
    ev = _load(eid)
    return _run(ev, lambda e, u: svc.review_evaluation(e, u, request.form), "Đã nhận xét và chuyển cấp phê duyệt.")


@bp.route("/<int:eid>/approve", methods=["POST"])
@permission_required("kpi.approve")
def approve(eid):
    ev = _load(eid)
    return _run(ev, lambda e, u: svc.approve_evaluation(e, u, request.form), "Đã phê duyệt xếp loại.")


@bp.route("/<int:eid>/return", methods=["POST"])
@permission_required("kpi.review", "kpi.approve")
def return_back(eid):
    ev = _load(eid)
    return _run(ev, lambda e, u: svc.return_evaluation(e, u, request.form.get("note")),
                "Đã trả hồ sơ về cho cán bộ chỉnh sửa.")


@bp.route("/<int:eid>/reopen", methods=["POST"])
@permission_required("kpi.approve")
def reopen(eid):
    ev = _load(eid)
    return _run(ev, svc.reopen_evaluation, "Đã mở lại hồ sơ để điều chỉnh quyết định.")


@bp.route("/<int:eid>/export/<form>")
@permission_required("kpi.self", "kpi.review", "kpi.approve", "kpi.reopen_plan")
def export(eid, form):
    """Xuất Mẫu 3, 4, 5 ra Excel - cùng quyền với khi xem hồ sơ (người khác không xuất được số liệu nháp)."""
    from services import export_excel as xl
    ev = _load(eid)
    if form not in ("m3", "m4", "m5"):
        abort(404)
    if form != "m3":
        if svc.stage(ev) != "result":
            abort(404)
        if ev.user_id != current_user.id and ev.status == EvalStatus.DRAFT:
            abort(403)
    if form == "m3":
        name, buf = xl.mau3(ev, svc.plan_rows(ev))
    elif form == "m4":
        name, buf = xl.mau4(ev)
    else:
        name, buf = xl.mau5(ev)
    return send_file(buf, mimetype=xl.XLSX, as_attachment=True, download_name=name)
