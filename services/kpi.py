"""
services/kpi.py - KPI cá nhân theo 3 bước, mỗi người một hồ sơ riêng cho mỗi quý.

Bước 1 · Mẫu 3 (plan_status): draft --trình--> submitted --lãnh đạo Ban duyệt--> ban_approved
                              --lãnh đạo cơ quan duyệt cuối--> approved
        Phó TB Thường trực trình thẳng lãnh đạo cơ quan. Phó Bí thư không trình: tự chốt (draft -> approved).
        Đã trình thì khóa; người duyệt trả lại được (về draft); Quản trị hoặc Phó Bí thư «Mở lại».
        Khi trình, lưu bản chụp danh mục (plan_snapshot) để Mẫu 3 luôn hiển thị đúng như đã trình.
Bước 2 · Mẫu 4: mở khi Mẫu 3 đã duyệt cuối. Nhiệm vụ của Mẫu 3 giữ nguyên (chỉ điều chỉnh được hệ số quy
        đổi, nhập kết quả), được thêm nhiệm vụ mới. Công chức không có chỉ số D.
Bước 3 · Mẫu 5 (status): draft --submit--> self_scored --review--> reviewed --approve--> approved
        (withdraw: self_scored -> draft) (return: self_scored/reviewed -> draft) (reopen: approved -> reviewed)
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime

from flask import current_app

from models import (
    Axis, CommonCriterion, EvalStatus, Indicator, KpiCoefficient, Period, PersonalAxisResult,
    PersonalCommonScore, PersonalEvaluation, PersonalKPIItem, PlanStatus, Rating, ResponseLevel, Role,
    TaskGroup, User, db,
)
from permissions import can, can_approve_user, can_review_user, needs_submission
from services.auth import ValidationError
from services.common import (
    WorkflowError, clean_text, iso, parse_bool, parse_choice, parse_date, parse_float,
)
from services.workflow import log_action, require_open_period

CODES = (1, 2, 3, 4)
RATINGS = {code for code, _ in Rating.CHOICES}
TASK_GROUPS = {code for code, _ in TaskGroup.CHOICES}
LEVELS = {code for code, _ in ResponseLevel.CHOICES}


# --------------------------------------------------------------------------- #
# Tạo hồ sơ
# --------------------------------------------------------------------------- #
def _position_title(user) -> str | None:
    parts = [p for p in (user.party_position, user.gov_position, user.org_position) if p]
    return "; ".join(parts) or None


def get_or_create_evaluation(user, period) -> PersonalEvaluation:
    ev = PersonalEvaluation.query.filter_by(user_id=user.id, period_id=period.id).first()
    if ev:
        return ev
    ev = PersonalEvaluation(
        user_id=user.id, period_id=period.id, department_id=user.department_id,
        position_group_id=user.position_group_id, position_title=_position_title(user),
        status=EvalStatus.DRAFT, plan_status=PlanStatus.DRAFT, use_leadership=user.has_leadership_kpi,
    )
    for c in CommonCriterion.query.order_by(CommonCriterion.sort).all():
        ev.common_scores.append(PersonalCommonScore(criterion_id=c.id, satisfied=None, score=0.0))
    db.session.add(ev)
    db.session.commit()
    return ev


def previous_evaluation(ev) -> PersonalEvaluation | None:
    """Hồ sơ của cùng người ở kỳ liền trước (nếu có)."""
    cur = ev.period
    return (PersonalEvaluation.query.join(Period)
            .filter(PersonalEvaluation.user_id == ev.user_id,
                    (Period.year < cur.year) | ((Period.year == cur.year) & (Period.quarter < cur.quarter)))
            .order_by(Period.year.desc(), Period.quarter.desc()).first())


def copy_plan_from_previous(ev) -> int:
    """Sao chép phần KẾ HOẠCH (Mẫu 3) từ quý trước; không chép kết quả thực tế. Trả về số dòng đã chép."""
    if ev.status != EvalStatus.DRAFT or ev.plan_status != PlanStatus.DRAFT:
        raise WorkflowError("Chỉ sao chép được khi Mẫu 3 đang lập.")
    if ev.items:
        raise WorkflowError("Hồ sơ đã có nhiệm vụ, không thể sao chép đè lên.")
    prev = previous_evaluation(ev)
    if not prev or not prev.items:
        raise WorkflowError("Không có hồ sơ quý trước để sao chép.")
    axes_seen = set()
    for src in prev.items:
        ev.items.append(PersonalKPIItem(
            axis_id=src.axis_id, task_group=src.task_group, sort=src.sort, task=src.task,
            product=src.product, difficulty=src.difficulty, planned_qty=src.planned_qty,
            deadline_text=src.deadline_text, task_score=src.task_score,
            conversion_coef=src.conversion_coef, is_standard=src.is_standard,
        ))
        axes_seen.add(src.axis_id)
    old = {ar.axis_id: ar for ar in prev.axis_results}
    for axis_id in axes_seen:
        ev.axis_results.append(PersonalAxisResult(
            axis_id=axis_id, is_main=old[axis_id].is_main if axis_id in old else False,
            max_score=old[axis_id].max_score if axis_id in old else 0.0))
    ev.use_leadership = ev.user.has_leadership_kpi
    ev.recompute()
    db.session.commit()
    return len(prev.items)


# --------------------------------------------------------------------------- #
# Bước hiện tại, bản chụp Mẫu 3
# --------------------------------------------------------------------------- #
def stage(ev) -> str:
    """plan = đang lập Mẫu 3; plan_locked = Mẫu 3 đã trình, chờ duyệt; result = đang ở Mẫu 4, 5."""
    if ev.plan_status == PlanStatus.DRAFT:
        return "plan"
    if ev.plan_status in (PlanStatus.SUBMITTED, PlanStatus.BAN_APPROVED):
        return "plan_locked"
    return "result"


PLAN_FIELDS = ("axis_id", "task_group", "indicator_id", "task", "product", "difficulty", "planned_qty",
               "deadline_text", "deadline_date", "note", "is_standard")
RESULT_FIELDS = ("actual_qty", "actual_date", "quality_code", "progress_code", "leadership_code",
                 "quality_exceeded", "progress_exceeded", "result_note")


def _snapshot(ev) -> str:
    rows = []
    for it in ev.items:
        rows.append({
            "axis_id": it.axis_id, "task_group": it.task_group, "task": it.task, "product": it.product or "",
            "difficulty": it.difficulty or "", "planned_qty": it.planned_qty,
            "deadline_text": it.deadline_text or "", "deadline_date": iso(it.deadline_date),
            "task_score": it.task_score, "conversion_coef": it.conversion_coef, "note": it.note or "",
        })
    return json.dumps(rows, ensure_ascii=False)


def plan_rows(ev) -> list[dict]:
    """Danh mục Mẫu 3 để hiển thị: bản chụp nếu đã trình, ngược lại là dữ liệu đang lập."""
    if ev.plan_status != PlanStatus.DRAFT and ev.plan_snapshot:
        try:
            return json.loads(ev.plan_snapshot)
        except ValueError:
            pass
    return json.loads(_snapshot(ev))


# --------------------------------------------------------------------------- #
# Chuyển dữ liệu cho giao diện
# --------------------------------------------------------------------------- #
def coefficient_table() -> dict:
    """{'quality': {1: {value, bonus, label}}, ...} cho giao diện và cho tính nhanh phía trình duyệt."""
    out: dict = {}
    for c in KpiCoefficient.query.filter_by(active=True).order_by(KpiCoefficient.code).all():
        out.setdefault(c.category, {})[c.code] = {
            "value": c.value, "bonus": c.bonus_value or 0.0, "label": c.label, "description": c.description or "",
        }
    return out


def serialize_item(it: PersonalKPIItem) -> dict:
    return {
        "id": it.id, "axis_id": it.axis_id, "task_group": it.task_group, "indicator_id": it.indicator_id,
        "task": it.task, "product": it.product or "", "difficulty": it.difficulty or "",
        "planned_qty": it.planned_qty, "deadline_text": it.deadline_text or "",
        "deadline_date": iso(it.deadline_date), "task_score": it.task_score,
        "conversion_coef": it.conversion_coef, "is_standard": bool(it.is_standard), "note": it.note or "",
        "from_plan": bool(it.from_plan),
        "actual_qty": it.actual_qty, "actual_date": iso(it.actual_date),
        "quality_code": it.quality_code, "progress_code": it.progress_code,
        "leadership_code": it.leadership_code,
        "quality_exceeded": bool(it.quality_exceeded), "progress_exceeded": bool(it.progress_exceeded),
        "result_note": it.result_note or "",
        "kpi_qty": it.kpi_qty, "qty_conv": it.qty_conv, "quality_value": it.quality_value,
        "quality_conv": it.quality_conv, "progress_value": it.progress_value,
        "progress_conv": it.progress_conv, "leadership_value": it.leadership_value,
        "leadership_conv": it.leadership_conv, "over_qty": it.over_qty,
        "over_quality": it.over_quality, "over_progress": it.over_progress,
    }


def serialize_axis(ar: PersonalAxisResult) -> dict:
    return {
        "axis_id": ar.axis_id, "is_main": bool(ar.is_main), "max_score": ar.max_score,
        "goals": ar.goals or "", "results": ar.results or "", "note": ar.note or "",
        "total_conv": ar.total_conv, "kpi_a": ar.kpi_a, "kpi_b": ar.kpi_b, "kpi_c": ar.kpi_c,
        "kpi_d": ar.kpi_d, "kpi_total": ar.kpi_total, "score": ar.score,
        "over_qty": ar.over_qty, "over_quality": ar.over_quality, "over_progress": ar.over_progress,
    }


def evaluation_payload(ev: PersonalEvaluation) -> dict:
    """Trạng thái hồ sơ gửi cho trình duyệt (cũng là phản hồi sau khi lưu)."""
    return {
        "stage": stage(ev),
        "plan_status": ev.plan_status,
        "status": ev.status,
        "plan": plan_rows(ev),
        "use_leadership": bool(ev.use_leadership),
        "self_comment": ev.self_comment or "",
        "self_rating": ev.self_rating or "",
        "items": [serialize_item(i) for i in ev.items],
        "axes": [serialize_axis(a) for a in ev.axis_results],
        "common": [
            {"criterion_id": cs.criterion_id, "satisfied": cs.satisfied, "score": cs.score, "note": cs.note or ""}
            for cs in ev.common_scores
        ],
        "totals": {"common": ev.common_score, "result": ev.result_score, "total": ev.total_score},
        "warnings": consistency_warnings(ev),
    }


def department_indicators(ev: PersonalEvaluation) -> list[dict]:
    """Chỉ tiêu của đơn vị trong kỳ (Mẫu 1) để cá nhân chọn nhanh khi lập danh mục."""
    if not ev.department_id:
        return []
    rows = (Indicator.query.filter_by(period_id=ev.period_id, department_id=ev.department_id)
            .order_by(Indicator.axis_id, Indicator.task_group, Indicator.sort, Indicator.id).all())
    return [{
        "id": r.id, "axis_id": r.axis_id, "task_group": r.task_group, "content": r.content,
        "product": r.product or "", "difficulty": r.difficulty or "",
        "deadline_text": r.deadline_text or "", "deadline_date": iso(r.deadline_date),
        "quarter_target": r.quarter_target,
    } for r in rows]


# --------------------------------------------------------------------------- #
# Lưu nháp
# --------------------------------------------------------------------------- #
def save_evaluation(ev: PersonalEvaluation, payload) -> PersonalEvaluation:
    """Kiểm tra toàn bộ dữ liệu; chỉ ghi vào CSDL khi không có lỗi. Chấp nhận hồ sơ chưa đầy đủ (nháp)."""
    if ev.status != EvalStatus.DRAFT:
        raise WorkflowError("Hồ sơ không ở trạng thái nháp nên không thể sửa.")
    st = stage(ev)
    if st == "plan_locked":
        raise WorkflowError("Mẫu 3 đã trình, đang chờ duyệt nên không thể sửa.")
    require_open_period(ev.period)
    if not isinstance(payload, dict):
        raise ValidationError(["Dữ liệu gửi lên không hợp lệ."])

    errors: list[str] = []
    cfg = current_app.config
    axes_by_id = {a.id: a for a in Axis.query.all()}
    criteria = {c.id: c for c in CommonCriterion.query.all()}
    existing = {it.id: it for it in ev.items}

    # --- các dòng sản phẩm/công việc ---
    raw_items = payload.get("items") or []
    if not isinstance(raw_items, list) or len(raw_items) > 300:
        raise ValidationError(["Danh sách nhiệm vụ không hợp lệ (tối đa 300 dòng)."])
    cleaned, seen_ids = [], set()
    for idx, raw in enumerate(raw_items, start=1):
        if not isinstance(raw, dict):
            errors.append(f"Dòng {idx}: dữ liệu không hợp lệ.")
            continue
        task = clean_text(raw.get("task"), "x", [], max_len=100000) or ""
        label = f"«{task[:40]}»" if task else f"Dòng {idx}"
        e: list[str] = []
        d = {
            "id": None,
            "task": clean_text(raw.get("task"), f"{label} - Nhiệm vụ", e, max_len=2000, required=True),
            "product": clean_text(raw.get("product"), f"{label} - Sản phẩm", e, max_len=300),
            "difficulty": clean_text(raw.get("difficulty"), f"{label} - Độ khó", e, max_len=1000),
            "deadline_text": clean_text(raw.get("deadline_text"), f"{label} - Tiến độ", e, max_len=200),
            "note": clean_text(raw.get("note"), f"{label} - Ghi chú", e, max_len=1000),
            "result_note": clean_text(raw.get("result_note"), f"{label} - Kết quả thực tế", e, max_len=1000),
            "axis_id": parse_choice(raw.get("axis_id"), f"{label} - Trục", e, set(axes_by_id), required=True),
            "task_group": parse_choice(raw.get("task_group") or TaskGroup.THUONG_XUYEN,
                                       f"{label} - Nhóm nhiệm vụ", e, TASK_GROUPS, required=True),
            "planned_qty": parse_float(raw.get("planned_qty"), f"{label} - Số lượng kế hoạch", e,
                                       minimum=0, maximum=1e9, default=1.0),
            "task_score": parse_float(raw.get("task_score"), f"{label} - Điểm chấm công việc", e,
                                      minimum=1, maximum=cfg["MAX_TASK_SCORE"],
                                      default=float(cfg["STANDARD_TASK_SCORE"])),
            "deadline_date": parse_date(raw.get("deadline_date"), f"{label} - Hạn hoàn thành", e),
            "actual_qty": parse_float(raw.get("actual_qty"), f"{label} - Số lượng thực tế", e,
                                      minimum=0, maximum=1e9),
            "actual_date": parse_date(raw.get("actual_date"), f"{label} - Ngày hoàn thành thực tế", e),
            "quality_code": parse_choice(raw.get("quality_code"), f"{label} - Chất lượng", e, set(CODES)),
            "progress_code": parse_choice(raw.get("progress_code"), f"{label} - Tiến độ", e, set(CODES)),
            "leadership_code": parse_choice(raw.get("leadership_code"), f"{label} - Lãnh đạo", e, set(CODES)),
            "quality_exceeded": parse_bool(raw.get("quality_exceeded")),
            "progress_exceeded": parse_bool(raw.get("progress_exceeded")),
            "is_standard": parse_bool(raw.get("is_standard")),
            "indicator_id": None,
        }
        rid = raw.get("id")
        if rid not in (None, ""):
            try:
                rid = int(rid)
            except (TypeError, ValueError):
                rid = None
            if rid not in existing or rid in seen_ids:
                e.append(f"{label}: dòng không thuộc hồ sơ này.")
            else:
                d["id"] = rid
                seen_ids.add(rid)
        iid = raw.get("indicator_id")
        if iid not in (None, ""):
            ind = db.session.get(Indicator, iid) if str(iid).isdigit() else None
            if (ind is None or ind.period_id != ev.period_id
                    or ind.department_id != ev.department_id):
                e.append(f"{label}: chỉ tiêu của đơn vị không hợp lệ.")
            else:
                d["indicator_id"] = ind.id
        errors.extend(e)
        cleaned.append(d)

    if st == "plan":
        for d in cleaned:                       # Bước 1: chỉ nhận phần kế hoạch, giữ nguyên kết quả đã có
            it = existing.get(d["id"]) if d["id"] else None
            for f in RESULT_FIELDS:
                d[f] = getattr(it, f) if it is not None else (False if f.endswith("_exceeded") else None)
    else:                                       # Bước 2, 3: nhiệm vụ của Mẫu 3 giữ nguyên
        for item_id, it in existing.items():
            if it.from_plan and item_id not in seen_ids:
                errors.append(f"«{it.task[:40]}»: nhiệm vụ đã duyệt trong Mẫu 3, không được xóa "
                              "(nhập số lượng thực tế 0 nếu không thực hiện).")
        for d in cleaned:
            it = existing.get(d["id"]) if d["id"] else None
            if it is not None and it.from_plan:
                for f in PLAN_FIELDS:
                    d[f] = getattr(it, f)

    # --- điểm tối đa của từng trục ---
    axes_in: dict[int, dict] = {}
    raw_axes = payload.get("axes") or []
    if not isinstance(raw_axes, list):
        raw_axes = []
    for raw in raw_axes:
        if not isinstance(raw, dict):
            continue
        e: list[str] = []
        axis_id = parse_choice(raw.get("axis_id"), "Trục", e, set(axes_by_id), required=True)
        number = axes_by_id[axis_id].number if axis_id else "?"
        max_score = parse_float(raw.get("max_score"), f"Trục {number} - Điểm tối đa", e,
                                minimum=0, maximum=cfg["RESULT_MAX_SCORE"], default=0.0)
        errors.extend(e)
        if axis_id:
            axes_in[axis_id] = {
                "is_main": parse_bool(raw.get("is_main")), "max_score": max_score or 0.0,
                "goals": clean_text(raw.get("goals"), f"Trục {number} - Mục tiêu, nhiệm vụ đề ra", errors, max_len=5000),
                "results": clean_text(raw.get("results"), f"Trục {number} - Kết quả sản phẩm thực tế", errors, max_len=5000),
                "note": clean_text(raw.get("note"), f"Trục {number} - Ghi chú", errors, max_len=1000),
            }
    if sum(a["max_score"] for a in axes_in.values()) > cfg["RESULT_MAX_SCORE"] + 1e-9:
        errors.append(f"Tổng điểm tối đa các trục vượt {cfg['RESULT_MAX_SCORE']:g} điểm.")

    # --- tiêu chí chung ---
    common_in: dict[int, dict] = {}
    for raw in payload.get("common") or []:
        if not isinstance(raw, dict):
            continue
        e: list[str] = []
        cid = parse_choice(raw.get("criterion_id"), "Tiêu chí chung", e, set(criteria), required=True)
        sat = raw.get("satisfied")
        if sat not in (True, False, None):
            e.append("Tiêu chí chung: giá trị Đảm bảo/Không đảm bảo không hợp lệ.")
        errors.extend(e)
        if cid:
            common_in[cid] = {"satisfied": sat, "note": clean_text(raw.get("note"), "Ghi chú tiêu chí", errors, max_len=500)}

    self_rating = parse_choice(payload.get("self_rating"), "Tự đề xuất xếp loại", errors, RATINGS)
    self_comment = clean_text(payload.get("self_comment"), "Tự nhận xét", errors, max_len=5000)

    if errors:
        raise ValidationError(errors)

    # --- ghi vào CSDL ---
    ev.use_leadership = ev.user.has_leadership_kpi      # theo vai trò, không cho tự chọn
    if st == "result":
        ev.self_rating, ev.self_comment = self_rating, self_comment

    keep = {d["id"] for d in cleaned if d["id"]}
    for item_id, it in existing.items():
        if item_id not in keep:
            ev.items.remove(it)
    order: dict = defaultdict(int)
    for d in cleaned:
        it = existing.get(d["id"]) if d["id"] else None
        if it is None:
            it = PersonalKPIItem(from_plan=False)
            ev.items.append(it)
        for f in ("axis_id", "task_group", "task", "product", "difficulty", "planned_qty", "deadline_text",
                  "deadline_date", "note", "actual_qty", "actual_date", "quality_code", "progress_code",
                  "leadership_code", "quality_exceeded", "progress_exceeded", "result_note",
                  "is_standard", "indicator_id"):
            setattr(it, f, d[f])
        it.set_score(d["task_score"])
        order[(d["axis_id"], d["task_group"])] += 1
        it.sort = order[(d["axis_id"], d["task_group"])]

    needed = (set(axes_in) if st == "result" else {ar.axis_id for ar in ev.axis_results if ar.max_score}) \
        | {d["axis_id"] for d in cleaned}
    results = {ar.axis_id: ar for ar in ev.axis_results}
    for axis_id, ar in results.items():
        if axis_id not in needed:
            ev.axis_results.remove(ar)
    for axis_id in needed:
        ar = results.get(axis_id)
        if ar is None:
            ar = PersonalAxisResult(axis_id=axis_id)
            ev.axis_results.append(ar)
        if axis_id in axes_in and st == "result":
            d = axes_in[axis_id]
            ar.is_main, ar.max_score = d["is_main"], d["max_score"]
            ar.goals, ar.results, ar.note = d["goals"], d["results"], d["note"]

    scores = {cs.criterion_id: cs for cs in ev.common_scores}
    for cid, c in criteria.items():
        cs = scores.get(cid)
        if cs is None:
            cs = PersonalCommonScore(criterion=c)
            ev.common_scores.append(cs)
        if cid in common_in and st == "result":
            cs.apply(common_in[cid]["satisfied"])
            cs.note = common_in[cid]["note"]

    ev.recompute()
    db.session.commit()
    return ev


# --------------------------------------------------------------------------- #
# Kiểm tra trước khi gửi, cảnh báo nhất quán
# --------------------------------------------------------------------------- #
def validate_for_submit(ev: PersonalEvaluation) -> list[str]:
    cfg = current_app.config
    errors = []
    if not ev.user.department_id:
        errors.append("Tài khoản chưa được gán phòng ban nên chưa có người nhận xét. Hãy liên hệ quản trị viên.")
    if not ev.items:
        errors.append("Chưa có sản phẩm/công việc nào trong phần kết quả thực hiện nhiệm vụ.")
    for it in ev.items:
        name = f"«{it.task[:40]}»"
        if not it.planned_qty or it.planned_qty <= 0:
            errors.append(f"{name}: số lượng kế hoạch phải lớn hơn 0.")
        if it.actual_qty is None:
            errors.append(f"{name}: chưa nhập số lượng thực tế (nhập 0 nếu chưa làm).")
        if it.quality_code is None:
            errors.append(f"{name}: chưa chọn mức chất lượng.")
        if it.progress_code is None:
            errors.append(f"{name}: chưa chọn mức tiến độ.")
        if ev.use_leadership and it.leadership_code is None:
            errors.append(f"{name}: chưa chọn mức lãnh đạo, chỉ đạo, điều hành (hoặc bỏ chọn chỉ số D).")
    unanswered = [cs for cs in ev.common_scores if cs.satisfied is None]
    if unanswered:
        errors.append(f"Còn {len(unanswered)} tiêu chí chung chưa chọn Đảm bảo / Không đảm bảo.")
    if ev.plan_status != PlanStatus.APPROVED:
        errors.insert(0, "Mẫu 3 chưa được duyệt cuối nên chưa trình được Mẫu 5.")
    for ar in ev.axis_results:
        has_items = any(i.axis_id == ar.axis_id for i in ev.items)
        if ar.max_score <= 0 and has_items:
            errors.append(f"Trục {ar.axis.number}: chưa phân bổ điểm tối đa.")
        if ar.max_score > 0 and not has_items:
            errors.append(f"Trục {ar.axis.number}: có điểm tối đa nhưng chưa có nhiệm vụ nào.")
    total_max = sum(ar.max_score for ar in ev.axis_results)
    if abs(total_max - cfg["RESULT_MAX_SCORE"]) > 0.005:
        errors.append(f"Tổng điểm tối đa các trục là {total_max:g}, phải bằng {cfg['RESULT_MAX_SCORE']:g}.")
    if ev.self_rating not in RATINGS:
        errors.append("Chưa chọn mức tự đề xuất xếp loại.")
    return errors


def consistency_warnings(ev: PersonalEvaluation) -> list[str]:
    """Nhắc nhở theo mục 'Một số lưu ý' của Phụ lục 2: KPI chất lượng, tiến độ, lãnh đạo phải phù hợp với số lượng.
    Chỉ là cảnh báo, không chặn lưu hay gửi."""
    out = []
    for it in ev.items:
        name = f"«{it.task[:40]}»"
        short = it.actual_qty is not None and (it.kpi_qty or 0) < 1
        if short and it.quality_code == 1:
            out.append(f"{name}: chưa đủ số lượng nhưng chất lượng chấm mức 1 (không sai sót).")
        if short and it.progress_code == 1:
            out.append(f"{name}: chưa đủ số lượng nhưng tiến độ chấm mức 1 (đúng hạn).")
        if it.actual_date and it.deadline_date and it.actual_date > it.deadline_date and it.progress_code == 1:
            out.append(f"{name}: hoàn thành sau hạn nhưng tiến độ chấm mức 1 (đúng hạn).")
        if (ev.use_leadership and it.leadership_code == 1
                and (short or (it.quality_code or 1) > 1 or (it.progress_code or 1) > 1)):
            out.append(f"{name}: lãnh đạo, chỉ đạo, điều hành chấm mức 1 nhưng số lượng, chất lượng hoặc tiến độ chưa đạt mức 1.")
    pct = ev.qty_completion_pct()
    if pct is not None and pct < 100:
        out.append(f"Hoàn thành {pct:g}% số lượng nhiệm vụ. Theo Hướng dẫn 07, mục IV.2: hoàn thành dưới 100% nhiệm vụ "
                   "thì xếp loại «Không hoàn thành nhiệm vụ», trừ trường hợp khách quan, bất khả kháng được cấp có thẩm quyền xác nhận.")
    return out


# --------------------------------------------------------------------------- #
# Chuyển trạng thái
# --------------------------------------------------------------------------- #
def _move(ev, actor, action, to_status, note=None):
    log_action("personal", ev.id, action, ev.status, to_status, actor, note)
    ev.status = to_status


def submit_evaluation(ev, actor):
    if actor.id != ev.user_id:
        raise WorkflowError("Chỉ chủ hồ sơ mới được gửi.")
    if not needs_submission(ev.user):
        raise WorkflowError("Hồ sơ của Phó Bí thư Thường trực không cần trình.")
    if ev.status != EvalStatus.DRAFT:
        raise WorkflowError("Hồ sơ không ở trạng thái nháp.")
    require_open_period(ev.period)
    ev.use_leadership = ev.user.has_leadership_kpi
    ev.recompute()
    errors = validate_for_submit(ev)
    if errors:
        raise WorkflowError(errors)
    ev.department_id, ev.position_group_id = ev.user.department_id, ev.user.position_group_id
    ev.position_title = _position_title(ev.user) or ev.position_title
    ev.submitted_at, ev.return_note, ev.returned_at = datetime.utcnow(), None, None
    _move(ev, actor, "submit", EvalStatus.SELF_SCORED)
    db.session.commit()


def withdraw_evaluation(ev, actor):
    if actor.id != ev.user_id:
        raise WorkflowError("Chỉ chủ hồ sơ mới được thu hồi.")
    if ev.status != EvalStatus.SELF_SCORED:
        raise WorkflowError("Chỉ thu hồi được hồ sơ đã gửi và chưa được nhận xét.")
    require_open_period(ev.period)
    _move(ev, actor, "withdraw", EvalStatus.DRAFT)
    db.session.commit()


def _parse_decision(form, ev, rating_field: str):
    """Đọc phần nhận xét / đề xuất của cấp duyệt (Mẫu 5 mục III, Mẫu 6)."""
    errors: list[str] = []
    rating = parse_choice(form.get(rating_field), "Mức xếp loại", errors, RATINGS, required=True)
    has_key_tasks = any(i.task_group == TaskGroup.TRONG_TAM for i in ev.items)
    level = parse_choice(form.get("response_level"), "Mức độ đáp ứng nhiệm vụ then chốt", errors, LEVELS,
                         required=has_key_tasks)
    data = {
        "rating": rating, "response_level": level,
        "reviewer_score": parse_float(form.get("reviewer_score"), "Điểm chấm", errors, minimum=0, maximum=100),
        "reviewer_comment": clean_text(form.get("reviewer_comment"), "Nhận xét", errors, max_len=5000),
        "rating_reason": clean_text(form.get("rating_reason"), "Căn cứ xếp loại", errors, max_len=5000,
                                    required=rating in (Rating.HTXS, Rating.KHT)),
        "personnel_proposal": clean_text(form.get("personnel_proposal"), "Đề xuất công tác cán bộ", errors, max_len=2000),
        "force_majeure": parse_bool(form.get("force_majeure")),
        "force_majeure_note": clean_text(form.get("force_majeure_note"), "Lý do khách quan", errors, max_len=2000),
    }
    if data["force_majeure"] and not data["force_majeure_note"]:
        errors.append("Lý do khách quan, bất khả kháng: cần nêu cụ thể.")
    if errors:
        raise WorkflowError(errors)
    return data


def _apply_review(ev, actor, d):
    ev.response_level, ev.reviewer_score = d["response_level"], d["reviewer_score"]
    ev.reviewer_comment, ev.rating_reason = d["reviewer_comment"], d["rating_reason"]
    ev.personnel_proposal = d["personnel_proposal"]
    ev.force_majeure, ev.force_majeure_note = d["force_majeure"], d["force_majeure_note"]


def review_evaluation(ev, actor, form):
    """Bước 3: cấp sử dụng cán bộ nhận xét, đề xuất xếp loại."""
    if not can_review_user(actor, ev.user):
        raise WorkflowError("Bạn không có quyền nhận xét hồ sơ này.")
    if ev.status != EvalStatus.SELF_SCORED:
        raise WorkflowError("Chỉ nhận xét được hồ sơ ở trạng thái «Đã gửi».")
    require_open_period(ev.period)
    d = _parse_decision(form, ev, "proposed_rating")
    _apply_review(ev, actor, d)
    ev.proposed_rating, ev.reviewed_by_id, ev.reviewed_at = d["rating"], actor.id, datetime.utcnow()
    _move(ev, actor, "review", EvalStatus.REVIEWED, d["reviewer_comment"])
    db.session.commit()


def approve_evaluation(ev, actor, form):
    """Bước 4: cấp có thẩm quyền quyết định mức xếp loại."""
    if not can_approve_user(actor, ev.user):
        raise WorkflowError("Bạn không có quyền phê duyệt hồ sơ này.")
    if ev.status not in (EvalStatus.SELF_SCORED, EvalStatus.REVIEWED):
        raise WorkflowError("Chỉ phê duyệt được hồ sơ đã gửi hoặc đã nhận xét.")
    require_open_period(ev.period)
    d = _parse_decision(form, ev, "final_rating")
    now = datetime.utcnow()
    _apply_review(ev, actor, d)
    if ev.status == EvalStatus.SELF_SCORED:       # phê duyệt thẳng: đồng thời ghi nhận bước nhận xét
        ev.proposed_rating, ev.reviewed_by_id, ev.reviewed_at = d["rating"], actor.id, now
    ev.final_rating, ev.approved_by_id, ev.approved_at = d["rating"], actor.id, now
    _move(ev, actor, "approve", EvalStatus.APPROVED, d["reviewer_comment"])
    db.session.commit()


def return_evaluation(ev, actor, note):
    """Trả lại cho chủ hồ sơ chỉnh sửa."""
    if not (can_review_user(actor, ev.user) or can_approve_user(actor, ev.user)):
        raise WorkflowError("Bạn không có quyền trả lại hồ sơ này.")
    if ev.status not in (EvalStatus.SELF_SCORED, EvalStatus.REVIEWED):
        raise WorkflowError("Chỉ trả lại được hồ sơ đã gửi hoặc đã nhận xét.")
    errors: list[str] = []
    note = clean_text(note, "Lý do trả lại", errors, max_len=2000, required=True)
    if errors:
        raise WorkflowError(errors)
    require_open_period(ev.period)
    ev.return_note, ev.returned_at = note, datetime.utcnow()
    ev.proposed_rating = ev.final_rating = None
    _move(ev, actor, "return", EvalStatus.DRAFT, note)
    db.session.commit()


def reopen_evaluation(ev, actor):
    """Mở lại hồ sơ đã phê duyệt (về «Đã nhận xét») để cấp duyệt điều chỉnh quyết định."""
    if not can_approve_user(actor, ev.user):
        raise WorkflowError("Bạn không có quyền mở lại hồ sơ này.")
    if ev.status != EvalStatus.APPROVED:
        raise WorkflowError("Hồ sơ chưa được phê duyệt.")
    require_open_period(ev.period)
    ev.final_rating, ev.approved_by_id, ev.approved_at = None, None, None
    _move(ev, actor, "reopen", EvalStatus.REVIEWED)
    db.session.commit()


# --------------------------------------------------------------------------- #
# Bước 1 · Mẫu 3: trình - duyệt - trả lại - mở lại
# --------------------------------------------------------------------------- #
def _plan_move(ev, actor, action, to_status, note=None):
    log_action("personal", ev.id, action, ev.plan_status, to_status, actor, note)
    ev.plan_status = to_status


def validate_plan(ev) -> list[str]:
    errors = []
    if needs_submission(ev.user) and not ev.user.department_id:
        errors.append("Tài khoản chưa được gán Phòng, Ban nên chưa có lãnh đạo duyệt. Hãy liên hệ quản trị viên.")
    if not ev.items:
        errors.append("Mẫu 3 chưa có sản phẩm, công việc nào.")
    for it in ev.items:
        if not it.planned_qty or it.planned_qty <= 0:
            errors.append(f"«{it.task[:40]}»: số lượng kế hoạch phải lớn hơn 0.")
    return errors


def _finalize_plan(ev):
    for it in ev.items:
        it.from_plan = True
    ev.plan_snapshot = _snapshot(ev)


def ban_has_leader(department_id) -> bool:
    return department_id is not None and User.query.filter_by(
        department_id=department_id, active=True, approved=True).filter(User.role.in_(tuple(Role.UNIT_LEADERS))).count() > 0


def submit_plan(ev, actor):
    if actor.id != ev.user_id:
        raise WorkflowError("Chỉ chủ hồ sơ mới được trình Mẫu 3.")
    if not needs_submission(ev.user):
        raise WorkflowError("Phó Bí thư Thường trực không trình Mẫu 3; hãy dùng «Chốt Mẫu 3».")
    if ev.plan_status != PlanStatus.DRAFT or ev.status != EvalStatus.DRAFT:
        raise WorkflowError("Mẫu 3 không ở trạng thái đang lập.")
    require_open_period(ev.period)
    errors = validate_plan(ev)
    if errors:
        raise WorkflowError(errors)
    ev.plan_snapshot = _snapshot(ev)
    ev.plan_submitted_at, ev.plan_return_note = datetime.utcnow(), None
    _plan_move(ev, actor, "plan_submit", PlanStatus.SUBMITTED)
    db.session.commit()


def lock_plan(ev, actor):
    """Phó Bí thư tự chốt Mẫu 3 của mình (không cần trình) để chuyển sang Mẫu 4."""
    if actor.id != ev.user_id or needs_submission(ev.user):
        raise WorkflowError("Chỉ Phó Bí thư Thường trực tự chốt Mẫu 3 của mình.")
    if ev.plan_status != PlanStatus.DRAFT:
        raise WorkflowError("Mẫu 3 đã được chốt.")
    require_open_period(ev.period)
    errors = validate_plan(ev)
    if errors:
        raise WorkflowError(errors)
    _finalize_plan(ev)
    ev.plan_approved_by_id, ev.plan_approved_at = actor.id, datetime.utcnow()
    _plan_move(ev, actor, "plan_lock", PlanStatus.APPROVED)
    db.session.commit()


def ban_approve_plan(ev, actor):
    if not can_review_user(actor, ev.user):
        raise WorkflowError("Bạn không có quyền duyệt Mẫu 3 của cán bộ này.")
    if ev.plan_status != PlanStatus.SUBMITTED:
        raise WorkflowError("Mẫu 3 không ở trạng thái chờ lãnh đạo Ban duyệt.")
    require_open_period(ev.period)
    ev.plan_ban_approved_by_id, ev.plan_ban_approved_at = actor.id, datetime.utcnow()
    _plan_move(ev, actor, "plan_ban_approve", PlanStatus.BAN_APPROVED)
    db.session.commit()


def can_final_approve_plan(ev, actor) -> bool:
    if not can_approve_user(actor, ev.user):
        return False
    if ev.plan_status == PlanStatus.BAN_APPROVED:
        return True
    # Phó TB Thường trực trình thẳng; Ban chưa có Phó TB Thường trực thì lãnh đạo cơ quan duyệt luôn
    return ev.plan_status == PlanStatus.SUBMITTED and (
        ev.user.role in Role.UNIT_LEADERS or not ban_has_leader(ev.user.department_id))


def approve_plan(ev, actor):
    if not can_approve_user(actor, ev.user):
        raise WorkflowError("Bạn không có quyền duyệt cuối Mẫu 3 của cán bộ này.")
    if not can_final_approve_plan(ev, actor):
        raise WorkflowError("Mẫu 3 cần được lãnh đạo Ban duyệt trước khi duyệt cuối.")
    require_open_period(ev.period)
    _finalize_plan(ev)
    ev.plan_approved_by_id, ev.plan_approved_at = actor.id, datetime.utcnow()
    _plan_move(ev, actor, "plan_approve", PlanStatus.APPROVED)
    db.session.commit()


def return_plan(ev, actor, note):
    reviewer = can_review_user(actor, ev.user) and ev.plan_status == PlanStatus.SUBMITTED
    approver = can_approve_user(actor, ev.user) and ev.plan_status in (PlanStatus.SUBMITTED, PlanStatus.BAN_APPROVED)
    if not (reviewer or approver):
        raise WorkflowError("Bạn không thể trả lại Mẫu 3 này.")
    errors: list[str] = []
    note = clean_text(note, "Lý do trả lại", errors, max_len=2000, required=True)
    if errors:
        raise WorkflowError(errors)
    require_open_period(ev.period)
    ev.plan_return_note = note
    ev.plan_ban_approved_by_id = ev.plan_ban_approved_at = None
    _plan_move(ev, actor, "plan_return", PlanStatus.DRAFT, note)
    db.session.commit()


def can_reopen_plan(ev, actor) -> bool:
    if ev.plan_status not in PlanStatus.LOCKED or ev.status != EvalStatus.DRAFT:
        return False
    if actor.role == Role.ADMIN:
        return True
    return actor.role == Role.PBT and (actor.id == ev.user_id or can_approve_user(actor, ev.user))


def reopen_plan(ev, actor):
    if not can("kpi.reopen_plan", actor) or not (actor.role == Role.ADMIN or actor.role == Role.PBT):
        raise WorkflowError("Chỉ Quản trị hệ thống hoặc Phó Bí thư Thường trực được mở lại Mẫu 3.")
    if ev.status != EvalStatus.DRAFT:
        raise WorkflowError("Mẫu 5 đã trình; cần trả lại Mẫu 5 trước khi mở lại Mẫu 3.")
    if not can_reopen_plan(ev, actor):
        raise WorkflowError("Không thể mở lại Mẫu 3 này.")
    require_open_period(ev.period)
    for it in ev.items:
        it.from_plan = False
    ev.plan_ban_approved_by_id = ev.plan_ban_approved_at = None
    ev.plan_approved_by_id = ev.plan_approved_at = None
    _plan_move(ev, actor, "plan_reopen", PlanStatus.DRAFT)
    db.session.commit()
