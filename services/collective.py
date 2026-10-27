"""
services/collective.py - KPI tập thể của phòng ban / cơ quan, đơn vị (Mẫu 1 chỉ tiêu + Mẫu 2 kết quả).

Hai giai đoạn, mỗi giai đoạn một luồng riêng: draft --trình--> submitted --duyệt--> approved
        (thu hồi: submitted -> draft) (trả lại: submitted -> draft) (mở lại: approved -> draft)
  Mẫu 1 (status)        : danh mục chỉ tiêu, nhiệm vụ đầu quý.
  Mẫu 2 (result_status) : chỉ mở khi Mẫu 1 đã duyệt; dòng lấy từ Mẫu 1 (chỉ xem), chỉ nhập cột kết quả.
                          Mẫu 1 mở lại thì Mẫu 2 khóa (về nháp), kết quả đã nhập giữ nguyên theo từng dòng.
Người lập, trình: lãnh đạo đơn vị cấp Thường trực (Phó TB TT, Phó CVP TT, Phó CN UBKT TT) của đơn vị đó.
Người duyệt cuối: Phó Bí thư Thường trực Đảng ủy (lãnh đạo cơ quan).
"""
from __future__ import annotations

from datetime import datetime

from models import (
    Axis, CollectiveEvaluation, CollectiveKPI, CollectiveStatus, Indicator, PersonalKPIItem, Rating,
    Role, TaskGroup, User, db, r2,
)
from permissions import can_approve_collective, can_edit_collective
from services.auth import ValidationError
from services.common import (
    WorkflowError, clean_text, iso, parse_bool, parse_choice, parse_date, parse_float,
)
from services.workflow import log_action, require_open_period

RATINGS = {code for code, _ in Rating.CHOICES}
TASK_GROUPS = {code for code, _ in TaskGroup.CHOICES}


def get_or_create(period, department) -> CollectiveEvaluation:
    ce = CollectiveEvaluation.query.filter_by(period_id=period.id, department_id=department.id).first()
    if ce is None:
        ce = CollectiveEvaluation(period_id=period.id, department_id=department.id,
                                  status=CollectiveStatus.DRAFT)
        db.session.add(ce)
        db.session.commit()
    return ce


def indicators_of(ce) -> list[Indicator]:
    return (Indicator.query.filter_by(period_id=ce.period_id, department_id=ce.department_id)
            .order_by(Indicator.axis_id, Indicator.task_group, Indicator.sort, Indicator.id).all())


def leader_options(department_id) -> list[dict]:
    """Lãnh đạo Ban có thể được giao trực tiếp phụ trách chỉ tiêu (cột 9 Mẫu 1)."""
    users = (User.query.filter(User.department_id == department_id, User.active.is_(True),
                               User.approved.is_(True), User.role.in_(tuple(Role.UNIT_LEADERS | Role.DEPUTIES)))
             .order_by(User.full_name).all())
    return [{"id": u.id, "name": u.full_name} for u in users]


def serialize_indicator(ind: Indicator) -> dict:
    r = ind.collective_kpi
    return {
        "id": ind.id, "axis_id": ind.axis_id, "task_group": ind.task_group, "content": ind.content,
        "product": ind.product or "", "unit": ind.unit or "", "annual_target": ind.annual_target,
        "quarter_target": ind.quarter_target, "difficulty": ind.difficulty or "",
        "lead_agency": ind.lead_agency or "", "support_agency": ind.support_agency or "",
        "leader_id": ind.leader_id, "deadline_text": ind.deadline_text or "",
        "deadline_date": iso(ind.deadline_date), "note": ind.note or "",
        "result": r.result if r else None, "actual_date": iso(r.actual_date) if r else "",
        "result_note": (r.note or "") if r else "",
        "pct_quarter": r.pct_quarter if r else None, "pct_year": r.pct_year if r else None,
        "on_time": r.on_time if r else None,
    }


def summarize(ce) -> dict:
    """Tổng hợp tham khảo (Hướng dẫn 07 không quy định công thức điểm cho tập thể)."""
    rows = indicators_of(ce)
    with_result = [i for i in rows if i.collective_kpi and i.collective_kpi.pct_quarter is not None]
    capped = [min(i.collective_kpi.pct_quarter, 100.0) for i in with_result]
    return {
        "total": len(rows),
        "with_result": len(with_result),
        "achieved": sum(1 for i in with_result if i.collective_kpi.pct_quarter >= 100),
        "on_time": sum(1 for i in with_result if i.collective_kpi.on_time),
        "avg_pct": r2(sum(capped) / len(capped)) if capped else None,
    }


def payload(ce) -> dict:
    return {
        "status": ce.status, "result_status": ce.result_status, "result_open": ce.result_open,
        "other_key_tasks": ce.other_key_tasks or "",
        "innovative_models": ce.innovative_models or "",
        "indicators": [serialize_indicator(i) for i in indicators_of(ce)],
        "summary": summarize(ce),
    }


def save(ce: CollectiveEvaluation, data) -> CollectiveEvaluation:
    """Lưu Mẫu 1 (danh mục chỉ tiêu). Cột kết quả của Mẫu 2 không đổi."""
    if ce.status != CollectiveStatus.DRAFT:
        raise WorkflowError("Mẫu 1 không ở trạng thái nháp nên không thể sửa.")
    require_open_period(ce.period)
    if not isinstance(data, dict):
        raise ValidationError(["Dữ liệu gửi lên không hợp lệ."])

    errors: list[str] = []
    axes = {a.id for a in Axis.query.all()}
    leaders = {u["id"] for u in leader_options(ce.department_id)}
    existing = {i.id: i for i in indicators_of(ce)}
    raw_rows = data.get("indicators") or []
    if not isinstance(raw_rows, list) or len(raw_rows) > 300:
        raise ValidationError(["Danh sách chỉ tiêu không hợp lệ (tối đa 300 dòng)."])

    cleaned, seen = [], set()
    for idx, raw in enumerate(raw_rows, start=1):
        if not isinstance(raw, dict):
            errors.append(f"Dòng {idx}: dữ liệu không hợp lệ.")
            continue
        content = clean_text(raw.get("content"), "x", [], max_len=100000) or ""
        label = f"«{content[:40]}»" if content else f"Dòng {idx}"
        e: list[str] = []
        d = {
            "id": None,
            "content": clean_text(raw.get("content"), f"{label} - Nội dung", e, max_len=2000, required=True),
            "product": clean_text(raw.get("product"), f"{label} - Sản phẩm", e, max_len=300),
            "unit": clean_text(raw.get("unit"), f"{label} - Đơn vị tính", e, max_len=50),
            "difficulty": clean_text(raw.get("difficulty"), f"{label} - Độ khó", e, max_len=1000),
            "lead_agency": clean_text(raw.get("lead_agency"), f"{label} - Cơ quan chủ trì", e, max_len=255),
            "support_agency": clean_text(raw.get("support_agency"), f"{label} - Cơ quan phối hợp", e, max_len=255),
            "deadline_text": clean_text(raw.get("deadline_text"), f"{label} - Thời gian hoàn thành", e, max_len=200),
            "note": clean_text(raw.get("note"), f"{label} - Ghi chú", e, max_len=1000),
            "result_note": clean_text(raw.get("result_note"), f"{label} - Ghi chú kết quả", e, max_len=1000),
            "axis_id": parse_choice(raw.get("axis_id"), f"{label} - Trục", e, axes, required=True),
            "task_group": parse_choice(raw.get("task_group") or TaskGroup.THUONG_XUYEN,
                                       f"{label} - Nhóm nhiệm vụ", e, TASK_GROUPS, required=True),
            "annual_target": parse_float(raw.get("annual_target"), f"{label} - Chỉ tiêu năm", e, minimum=0, maximum=1e12),
            "quarter_target": parse_float(raw.get("quarter_target"), f"{label} - Chỉ tiêu quý", e, minimum=0, maximum=1e12),
            "result": parse_float(raw.get("result"), f"{label} - Kết quả thực hiện", e, minimum=0, maximum=1e12),
            "deadline_date": parse_date(raw.get("deadline_date"), f"{label} - Hạn hoàn thành", e),
            "actual_date": parse_date(raw.get("actual_date"), f"{label} - Ngày hoàn thành thực tế", e),
            "leader_id": parse_choice(raw.get("leader_id"), f"{label} - Lãnh đạo phụ trách", e, leaders),
        }
        rid = raw.get("id")
        if rid not in (None, ""):
            try:
                rid = int(rid)
            except (TypeError, ValueError):
                rid = None
            if rid not in existing or rid in seen:
                e.append(f"{label}: dòng không thuộc KPI tập thể này.")
            else:
                d["id"] = rid
                seen.add(rid)
        errors.extend(e)
        cleaned.append(d)

    if errors:
        raise ValidationError(errors)

    for ind_id, ind in existing.items():
        if ind_id not in seen:
            PersonalKPIItem.query.filter_by(indicator_id=ind_id).update({"indicator_id": None})
            db.session.delete(ind)
    order: dict = {}
    for d in cleaned:
        ind = existing.get(d["id"]) if d["id"] else None
        if ind is None:
            ind = Indicator(period_id=ce.period_id, department_id=ce.department_id)
            db.session.add(ind)
        for f in ("axis_id", "task_group", "content", "product", "unit", "annual_target", "quarter_target",
                  "difficulty", "lead_agency", "support_agency", "leader_id", "deadline_text",
                  "deadline_date", "note"):
            setattr(ind, f, d[f])
        key = (d["axis_id"], d["task_group"])
        order[key] = order.get(key, 0) + 1
        ind.sort = order[key]
    db.session.commit()
    return ce


def save_results(ce: CollectiveEvaluation, data) -> CollectiveEvaluation:
    """Lưu Mẫu 2: chỉ cột kết quả của các dòng đã có trong Mẫu 1 đã duyệt, cùng mục II, III."""
    if not ce.result_open:
        raise WorkflowError("Mẫu 2 mở sau khi Mẫu 1 được duyệt.")
    if ce.result_status != CollectiveStatus.DRAFT:
        raise WorkflowError("Mẫu 2 không ở trạng thái nháp nên không thể sửa.")
    require_open_period(ce.period)
    if not isinstance(data, dict):
        raise ValidationError(["Dữ liệu gửi lên không hợp lệ."])
    errors: list[str] = []
    existing = {i.id: i for i in indicators_of(ce)}
    rows = data.get("indicators") or []
    if not isinstance(rows, list):
        raise ValidationError(["Danh sách kết quả không hợp lệ."])
    cleaned = {}
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        try:
            rid = int(raw.get("id"))
        except (TypeError, ValueError):
            rid = None
        if rid not in existing:
            errors.append("Có dòng kết quả không thuộc Mẫu 1 đã duyệt.")
            continue
        label = f"«{existing[rid].content[:40]}»"
        cleaned[rid] = {
            "result": parse_float(raw.get("result"), f"{label} - Kết quả thực hiện", errors, minimum=0, maximum=1e12),
            "actual_date": parse_date(raw.get("actual_date"), f"{label} - Ngày hoàn thành thực tế", errors),
            "note": clean_text(raw.get("result_note"), f"{label} - Ghi chú kết quả", errors, max_len=1000),
        }
    other = clean_text(data.get("other_key_tasks"), "Nhiệm vụ trọng tâm khác", errors, max_len=10000)
    models = clean_text(data.get("innovative_models"), "Mô hình hay, cách làm sáng tạo", errors, max_len=10000)
    if errors:
        raise ValidationError(errors)
    ce.other_key_tasks, ce.innovative_models = other, models
    for rid, d in cleaned.items():
        ind = existing[rid]
        if d["result"] is not None or d["actual_date"] or d["note"]:
            r = ind.collective_kpi or CollectiveKPI()
            r.result, r.actual_date, r.note = d["result"], d["actual_date"], d["note"]
            ind.collective_kpi = r
        elif ind.collective_kpi is not None:
            ind.collective_kpi = None
    db.session.commit()
    return ce


def validate_for_submit(ce) -> list[str]:
    """Mẫu 1: đủ danh mục, chỉ tiêu quý."""
    errors = []
    rows = indicators_of(ce)
    if not rows:
        errors.append("Chưa có chỉ tiêu, nhiệm vụ nào.")
    for i in rows:
        if i.quarter_target is None:
            errors.append(f"«{i.content[:40]}»: chưa nhập chỉ tiêu quý.")
    return errors


def validate_results(ce) -> list[str]:
    errors = []
    for i in indicators_of(ce):
        if i.collective_kpi is None or i.collective_kpi.result is None:
            errors.append(f"«{i.content[:40]}»: chưa nhập kết quả thực hiện quý.")
    return errors


def _move(ce, actor, action, to_status, note=None):
    log_action("collective", ce.id, action, ce.status, to_status, actor, note)
    ce.status = to_status


def submit(ce, actor):
    if not can_edit_collective(actor, ce.department_id):
        raise WorkflowError("Bạn không có quyền trình Mẫu 1 của đơn vị này.")
    if ce.status != CollectiveStatus.DRAFT:
        raise WorkflowError("Mẫu 1 không ở trạng thái nháp.")
    require_open_period(ce.period)
    errors = validate_for_submit(ce)
    if errors:
        raise WorkflowError(errors)
    ce.submitted_by_id, ce.submitted_at = actor.id, datetime.utcnow()
    ce.return_note, ce.returned_at = None, None
    _move(ce, actor, "submit", CollectiveStatus.SUBMITTED)
    db.session.commit()


def withdraw(ce, actor):
    if not can_edit_collective(actor, ce.department_id):
        raise WorkflowError("Bạn không có quyền thu hồi KPI tập thể của đơn vị này.")
    if ce.status != CollectiveStatus.SUBMITTED:
        raise WorkflowError("Chỉ thu hồi được KPI tập thể đã gửi và chưa duyệt.")
    require_open_period(ce.period)
    _move(ce, actor, "withdraw", CollectiveStatus.DRAFT)
    db.session.commit()


def approve(ce, actor):
    if not can_approve_collective(actor, ce.department_id):
        raise WorkflowError("Bạn không có quyền duyệt KPI tập thể của đơn vị này.")
    if ce.status != CollectiveStatus.SUBMITTED:
        raise WorkflowError("Chỉ duyệt được Mẫu 1 đã trình.")
    require_open_period(ce.period)
    ce.confirmed_by_id, ce.confirmed_at = actor.id, datetime.utcnow()
    _move(ce, actor, "approve", CollectiveStatus.APPROVED)
    db.session.commit()


def return_(ce, actor, note):
    if not can_approve_collective(actor, ce.department_id):
        raise WorkflowError("Bạn không có quyền trả lại KPI tập thể của đơn vị này.")
    if ce.status != CollectiveStatus.SUBMITTED:
        raise WorkflowError("Chỉ trả lại được KPI tập thể đã gửi.")
    errors: list[str] = []
    note = clean_text(note, "Lý do trả lại", errors, max_len=2000, required=True)
    if errors:
        raise WorkflowError(errors)
    require_open_period(ce.period)
    ce.return_note, ce.returned_at = note, datetime.utcnow()
    _move(ce, actor, "return", CollectiveStatus.DRAFT, note)
    db.session.commit()


def reopen(ce, actor):
    """Mở lại Mẫu 1 để đơn vị điều chỉnh; Mẫu 2 khóa lại (về nháp) cho tới khi Mẫu 1 được duyệt lại."""
    if not can_approve_collective(actor, ce.department_id):
        raise WorkflowError("Bạn không có quyền mở lại KPI tập thể của đơn vị này.")
    if ce.status != CollectiveStatus.APPROVED:
        raise WorkflowError("Mẫu 1 chưa được duyệt.")
    require_open_period(ce.period)
    ce.confirmed_by_id, ce.confirmed_at = None, None
    if ce.result_status != CollectiveStatus.DRAFT:
        log_action("collective", ce.id, "m2_lock", ce.result_status, CollectiveStatus.DRAFT, actor)
        ce.result_status = CollectiveStatus.DRAFT
        ce.rating, ce.result_confirmed_by_id, ce.result_confirmed_at = None, None, None
    _move(ce, actor, "reopen", CollectiveStatus.DRAFT)
    db.session.commit()


# --------------------------------------------------------------------------- #
# Mẫu 2: trình - duyệt riêng
# --------------------------------------------------------------------------- #
def _move_result(ce, actor, action, to_status, note=None):
    log_action("collective", ce.id, action, ce.result_status, to_status, actor, note)
    ce.result_status = to_status


def submit_results(ce, actor):
    if not can_edit_collective(actor, ce.department_id):
        raise WorkflowError("Bạn không có quyền trình Mẫu 2 của đơn vị này.")
    if not ce.result_open or ce.result_status != CollectiveStatus.DRAFT:
        raise WorkflowError("Mẫu 2 chưa mở hoặc không ở trạng thái nháp.")
    require_open_period(ce.period)
    errors = validate_results(ce)
    if errors:
        raise WorkflowError(errors)
    ce.result_submitted_by_id, ce.result_submitted_at, ce.result_return_note = actor.id, datetime.utcnow(), None
    _move_result(ce, actor, "m2_submit", CollectiveStatus.SUBMITTED)
    db.session.commit()


def withdraw_results(ce, actor):
    if not can_edit_collective(actor, ce.department_id):
        raise WorkflowError("Bạn không có quyền thu hồi Mẫu 2 của đơn vị này.")
    if ce.result_status != CollectiveStatus.SUBMITTED:
        raise WorkflowError("Chỉ thu hồi được Mẫu 2 đã trình và chưa duyệt.")
    require_open_period(ce.period)
    _move_result(ce, actor, "m2_withdraw", CollectiveStatus.DRAFT)
    db.session.commit()


def approve_results(ce, actor, rating=None):
    if not can_approve_collective(actor, ce.department_id):
        raise WorkflowError("Bạn không có quyền duyệt Mẫu 2 của đơn vị này.")
    if not ce.result_open or ce.result_status != CollectiveStatus.SUBMITTED:
        raise WorkflowError("Chỉ duyệt được Mẫu 2 đã trình.")
    require_open_period(ce.period)
    errors: list[str] = []
    rating = parse_choice(rating, "Xếp loại tập thể", errors, RATINGS)
    if errors:
        raise WorkflowError(errors)
    ce.rating, ce.result_confirmed_by_id, ce.result_confirmed_at = rating, actor.id, datetime.utcnow()
    _move_result(ce, actor, "m2_approve", CollectiveStatus.APPROVED)
    db.session.commit()


def return_results(ce, actor, note):
    if not can_approve_collective(actor, ce.department_id):
        raise WorkflowError("Bạn không có quyền trả lại Mẫu 2 của đơn vị này.")
    if ce.result_status != CollectiveStatus.SUBMITTED:
        raise WorkflowError("Chỉ trả lại được Mẫu 2 đã trình.")
    errors: list[str] = []
    note = clean_text(note, "Lý do trả lại", errors, max_len=2000, required=True)
    if errors:
        raise WorkflowError(errors)
    require_open_period(ce.period)
    ce.result_return_note = note
    _move_result(ce, actor, "m2_return", CollectiveStatus.DRAFT, note)
    db.session.commit()


def reopen_results(ce, actor):
    if not can_approve_collective(actor, ce.department_id):
        raise WorkflowError("Bạn không có quyền mở lại Mẫu 2 của đơn vị này.")
    if ce.result_status != CollectiveStatus.APPROVED:
        raise WorkflowError("Mẫu 2 chưa được duyệt.")
    require_open_period(ce.period)
    ce.rating, ce.result_confirmed_by_id, ce.result_confirmed_at = None, None, None
    _move_result(ce, actor, "m2_reopen", CollectiveStatus.DRAFT)
    db.session.commit()
