"""services/dashboard.py - Số liệu cho trang Tổng quan (dashboard).

Mọi con số đều giới hạn theo phạm vi người xem (permissions.scope_users_query):
Quản trị hệ thống và Phó Bí thư Thường trực thấy toàn cơ quan, Phó Trưởng Ban Thường trực thấy Ban của mình,
Phó Trưởng Ban và công chức chỉ thấy hồ sơ của mình. Điểm và xếp loại của người khác chỉ tính khi hồ sơ đã gửi
(không đọc bản nháp của người khác).
"""
from __future__ import annotations

from datetime import date

from models import (
    CollectiveEvaluation, CollectiveStatus, Department, EvalStatus, PersonalEvaluation, PlanStatus, Rating,
    Role, User, WorkflowLog,
)
from permissions import (
    can, can_approve_collective, can_view_evaluation, needs_submission, scope_users_query,
    viewable_departments,
)

PENDING = (EvalStatus.SELF_SCORED, EvalStatus.REVIEWED)
DONE = (EvalStatus.APPROVED, EvalStatus.PUBLISHED)

# Các bước của luồng hồ sơ, theo thứ tự; "none" = chưa lập hồ sơ
STAGES = [("none", "Chưa lập")] + EvalStatus.CHOICES
SCORE_BINS = [("< 50", 0, 50), ("50–70", 50, 70), ("70–80", 70, 80), ("80–90", 80, 90), ("≥ 90", 90, 1000)]


def _pct(part, whole) -> int:
    return round(part * 100 / whole) if whole else 0


def _rating_of(ev) -> str | None:
    """Xếp loại hiện hành: ưu tiên quyết định (Bước 4), rồi đề xuất (Bước 3), rồi tự đề xuất."""
    return ev.final_rating or ev.proposed_rating or ev.self_rating


def _deadlines(period, today):
    rows = [
        ("Mẫu 1, Mẫu 3", "Lập chỉ tiêu, danh mục KPI", period.deadline_m1_m3),
        ("Mẫu 2", "Kết quả KPI tập thể", period.deadline_m2),
        ("Mẫu 4 – 8", "Tự chấm, nhận xét, xếp loại", period.deadline_m4_m8),
    ]
    out, next_found = [], False
    for code, label, d in rows:
        if d is None:
            continue
        days = (d - today).days
        state = "past" if days < 0 else ("next" if not next_found else "future")
        next_found = next_found or days >= 0
        out.append({"code": code, "label": label, "date": d, "days": days, "state": state})
    return out


def build(actor: User, period, today: date | None = None, dept_filter: int | None = None) -> dict:
    today = today or date.today()
    data: dict = {"period": period, "today": today}

    if can("user.manage", actor):
        data["pending_users"] = User.query.filter_by(approved=False).count()
    data["needs_submission"] = needs_submission(actor)

    if not period:
        return data

    data["deadlines"] = _deadlines(period, today)
    total_days = (period.end_date - period.start_date).days or 1
    data["period_progress"] = max(0, min(100, _pct((today - period.start_date).days, total_days)))

    # ---- Hồ sơ của tôi ----
    if can("kpi.self", actor):
        data["my_eval"] = PersonalEvaluation.query.filter_by(user_id=actor.id, period_id=period.id).first()

    # ---- Cán bộ trong phạm vi (không tính quản trị viên: không tham gia đánh giá) ----
    users = (scope_users_query(actor)
             .filter(User.active.is_(True), User.approved.is_(True), User.role != Role.ADMIN).all())
    team_view = can("team.view", actor) and len(users) > (1 if can("kpi.self", actor) else 0)
    data["team_view"] = team_view
    if team_view:
        data.update(_team_stats(actor, period, users))
        data.update(_people(actor, period, users, dept_filter))

    # ---- Việc cần tôi xử lý (Mẫu 3 và Mẫu 5) ----
    if can("kpi.review", actor) or can("kpi.approve", actor):
        from routes.kpi import pending_count
        data["my_queue"] = pending_count(actor, period.id)

    # ---- KPI tập thể ----
    if can("indicator.view", actor):
        data.update(_collective_stats(actor, period))

    data["activity"] = _recent_activity(actor, users) if team_view else []
    return data


def _team_stats(actor, period, users) -> dict:
    user_ids = {u.id for u in users}
    evals = {e.user_id: e for e in PersonalEvaluation.query.filter(
        PersonalEvaluation.period_id == period.id, PersonalEvaluation.user_id.in_(user_ids)).all()}

    stage_count = {code: 0 for code, _ in STAGES}
    scored = []                                       # hồ sơ đã gửi trở lên: được tính điểm, xếp loại
    for u in users:
        ev = evals.get(u.id)
        stage_count[ev.status if ev else "none"] += 1
        if ev and ev.status != EvalStatus.DRAFT:
            scored.append(ev)

    total = len(users)
    submitted = sum(1 for e in evals.values() if e.status != EvalStatus.DRAFT)
    done = sum(1 for e in evals.values() if e.status in DONE)
    plan_done = sum(1 for e in evals.values() if e.plan_status == PlanStatus.APPROVED)

    stages = [{"code": c, "label": l, "count": stage_count[c], "pct": _pct(stage_count[c], total)}
              for c, l in STAGES]

    # Phân bố xếp loại (đã gửi trở lên)
    rating_count = {code: 0 for code, _ in Rating.CHOICES}
    for e in scored:
        r = _rating_of(e)
        if r in rating_count:
            rating_count[r] += 1
    rmax = max(rating_count.values()) or 1
    ratings = [{"code": c, "label": l, "count": rating_count[c], "w": _pct(rating_count[c], rmax),
                "pct": _pct(rating_count[c], len(scored))} for c, l in Rating.CHOICES]
    htt = rating_count[Rating.HTT]
    htxs = sum(1 for e in scored if _rating_of(e) == Rating.HTXS and not (e.user and e.user.is_head))
    htxs_ratio = round(htxs * 100 / htt, 1) if htt else None

    # Phân bố tổng điểm
    bins = []
    for label, lo, hi in SCORE_BINS:
        n = sum(1 for e in scored if lo <= (e.total_score or 0) < hi)
        bins.append({"label": label, "count": n})
    bmax = max((b["count"] for b in bins), default=0) or 1
    for b in bins:
        b["h"] = _pct(b["count"], bmax)

    avg = round(sum(e.total_score or 0 for e in scored) / len(scored), 2) if scored else None

    # Theo phòng ban
    depts = {d.id: d for d in Department.query.all()}
    by_dept: dict = {}
    for u in users:
        row = by_dept.setdefault(u.department_id, {"name": depts[u.department_id].name if u.department_id in depts
                                                   else "Chưa có phòng ban", "total": 0, "submitted": 0,
                                                   "done": 0, "scores": []})
        row["total"] += 1
        ev = evals.get(u.id)
        if ev and ev.status != EvalStatus.DRAFT:
            row["submitted"] += 1
            row["scores"].append(ev.total_score or 0)
        if ev and ev.status in DONE:
            row["done"] += 1
    dept_rows = []
    for row in by_dept.values():
        row["avg"] = round(sum(row["scores"]) / len(row["scores"]), 2) if row["scores"] else None
        row["pct_submitted"] = _pct(row["submitted"], row["total"])
        row["pct_done"] = _pct(row["done"], row["submitted"])
        dept_rows.append(row)
    dept_rows.sort(key=lambda r: (-r["pct_submitted"], r["name"]))

    return {
        "team_total": total, "team_submitted": submitted, "team_done": done, "plan_done": plan_done,
        "pct_submitted": _pct(submitted, total), "pct_done": _pct(done, submitted),
        "pct_plan_done": _pct(plan_done, total),
        "dept_total": len({u.department_id for u in users if u.department_id}),
        "avg_score": avg, "stages": stages, "ratings": ratings, "rated_total": len(scored),
        "htxs": htxs, "htt": htt, "htxs_ratio": htxs_ratio, "score_bins": bins, "dept_rows": dept_rows,
    }


PLAN_LABELS = {PlanStatus.DRAFT: "Đang lập", PlanStatus.SUBMITTED: "Chờ Ban duyệt",
               PlanStatus.BAN_APPROVED: "Chờ duyệt cuối", PlanStatus.APPROVED: "Đã duyệt"}


def _people(actor, period, users, dept_filter) -> dict:
    """Bảng «Tiến độ KPI của các cá nhân»: một dòng cho mỗi cán bộ trong phạm vi, lọc theo Ban."""
    evals = {e.user_id: e for e in PersonalEvaluation.query.filter(
        PersonalEvaluation.period_id == period.id, PersonalEvaluation.user_id.in_([u.id for u in users])).all()}
    dept_ids = {u.department_id for u in users if u.department_id}
    depts = sorted((d for d in Department.query.filter(Department.id.in_(dept_ids)).all()), key=lambda d: d.name) \
        if dept_ids else []
    rows = []
    for u in sorted(users, key=lambda x: ((x.department.name if x.department else "~"), -Role.RANK.get(x.role, 0), x.full_name)):
        if dept_filter and u.department_id != dept_filter:
            continue
        ev = evals.get(u.id)
        own = ev is not None and ev.user_id == actor.id
        visible = ev is not None and can_view_evaluation(actor, ev)
        submitted = ev is not None and ev.status != EvalStatus.DRAFT
        if ev is None:
            plan = "Chưa lập"
        elif ev.plan_status == PlanStatus.APPROVED and not needs_submission(u):
            plan = "Đã chốt"
        else:
            plan = PLAN_LABELS.get(ev.plan_status, ev.plan_status)
        if ev is None or ev.plan_status != PlanStatus.APPROVED:
            result = "Chưa thực hiện"
        elif ev.status == EvalStatus.DRAFT:
            result = "Đang tự chấm" if needs_submission(u) else "Không cần trình"
        else:
            result = EvalStatus.LABELS.get(ev.status, ev.status)
        rows.append({
            "user": u, "ev": ev, "plan": plan, "plan_code": ev.plan_status if ev else "none",
            "result": result, "result_code": ev.status if ev else "none",
            "score": ev.total_score if ev and (submitted or own) else None,
            "rating": (ev.final_rating or ev.proposed_rating or ev.self_rating) if ev and (submitted or own) else None,
            "link": visible,
        })
    return {"people": rows, "people_depts": depts, "dept_filter": dept_filter}


def _collective_stats(actor, period) -> dict:
    """Tình trạng KPI tập thể, tách riêng Mẫu 1 (danh mục) và Mẫu 2 (kết quả)."""
    depts = viewable_departments(actor)
    if not depts:
        return {}
    ces = {c.department_id: c for c in CollectiveEvaluation.query.filter(
        CollectiveEvaluation.period_id == period.id,
        CollectiveEvaluation.department_id.in_([d.id for d in depts])).all()}
    m1 = {"none": 0, **{c: 0 for c, _ in CollectiveStatus.CHOICES}}
    m2 = {"locked": 0, **{c: 0 for c, _ in CollectiveStatus.CHOICES}}
    to_confirm = 0
    for d in depts:
        ce = ces.get(d.id)
        m1[ce.status if ce else "none"] += 1
        m2[ce.result_status if ce and ce.result_open else "locked"] += 1
        if ce and can_approve_collective(actor, d.id):
            to_confirm += int(ce.status == CollectiveStatus.SUBMITTED)
            to_confirm += int(ce.result_open and ce.result_status == CollectiveStatus.SUBMITTED)
    n = len(depts)
    rows = lambda counts, labels: [{"code": c, "label": l, "count": counts[c], "pct": _pct(counts[c], n)}
                                   for c, l in labels]
    return {
        "collective": rows(m1, [("none", "Chưa lập")] + CollectiveStatus.CHOICES),
        "collective_m2": rows(m2, [("locked", "Chưa mở (chờ Mẫu 1)")] + CollectiveStatus.CHOICES),
        "collective_total": n, "collective_to_confirm": to_confirm,
    }


def _recent_activity(actor, users, limit=8) -> list:
    """Thao tác gần đây trên hồ sơ cá nhân của các cán bộ trong phạm vi (bỏ qua bản nháp của người khác)."""
    user_ids = {u.id for u in users}
    rows = (WorkflowLog.query.filter_by(entity_type="personal")
            .order_by(WorkflowLog.created_at.desc(), WorkflowLog.id.desc()).limit(200).all())
    ev_ids = {r.entity_id for r in rows}
    owners = {e.id: e for e in PersonalEvaluation.query.filter(PersonalEvaluation.id.in_(ev_ids)).all()} if ev_ids else {}
    out = []
    for r in rows:
        ev = owners.get(r.entity_id)
        if not ev or ev.user_id not in user_ids:
            continue
        if ev.user_id != actor.id and not can_view_evaluation(actor, ev):
            continue
        out.append({"log": r, "ev": ev})
        if len(out) >= limit:
            break
    return out
