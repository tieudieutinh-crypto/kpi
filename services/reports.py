"""services/reports.py - Số liệu cho các mẫu báo cáo tổng hợp (Hướng dẫn 07):

  Mẫu 6: tổng hợp kết quả đánh giá và đề xuất xếp loại từng cán bộ (hồ sơ đã trình).
  Mẫu 7: báo cáo kết quả đánh giá cán bộ lãnh đạo, quản lý cấp xã và tương đương.
  Mẫu 8: báo cáo kết quả đánh giá cán bộ lãnh đạo, quản lý cấp thành phố.

Phạm vi số liệu theo người xem (permissions.scope_users_query). Mẫu 7, 8 chỉ tính hồ sơ đã được quyết định
xếp loại (đã duyệt, đã công bố), phân cột theo nhóm đối tượng (PositionGroup) ghi nhận khi cán bộ trình hồ sơ.
"""
from __future__ import annotations

from models import (
    EvalStatus, PersonalEvaluation, PositionGroup, Rating, ResponseLevel, Role, User, db,
)
from permissions import scope_users_query

DONE = (EvalStatus.APPROVED, EvalStatus.PUBLISHED)


def _scoped_evaluations(actor, period, statuses):
    ids = [u.id for u in scope_users_query(actor).filter(User.role != Role.ADMIN).all()]
    if not ids:
        return []
    return (PersonalEvaluation.query.join(User, User.id == PersonalEvaluation.user_id)
            .filter(PersonalEvaluation.period_id == period.id, PersonalEvaluation.user_id.in_(ids),
                    PersonalEvaluation.status.in_(statuses))
            .order_by(User.full_name).all())


def mau6(actor, period) -> list[dict]:
    """Mẫu 6: (1) STT, (2) Họ và tên, (3) Chức vụ, đơn vị công tác, (4) Cá nhân tự đề xuất,
    (5) Cấp có thẩm quyền đề xuất, (6) Tóm tắt căn cứ, (7) Đề xuất về công tác cán bộ."""
    rows = []
    submitted = [s for s, _ in EvalStatus.CHOICES if s != EvalStatus.DRAFT]
    for ev in _scoped_evaluations(actor, period, submitted):
        u = ev.user
        position = ev.position_title or u.role_label
        unit = ev.department.name if ev.department else (u.department.name if u.department else "")
        rows.append({
            "ev": ev, "name": u.full_name,
            "position": ", ".join(p for p in (position, unit) if p),
            "self": ev.self_rating, "proposed": ev.final_rating or ev.proposed_rating,
            "final": bool(ev.final_rating), "reason": ev.rating_reason or "",
            "personnel": ev.personnel_proposal or "", "status": ev.status,
        })
    return rows


def _group_of(ev):
    return ev.position_group_id or (ev.user.position_group_id if ev.user else None)


def mau78(actor, period, form: str) -> dict:
    """Mẫu 7 (form='M7') hoặc Mẫu 8 (form='M8'): đếm theo nhóm đối tượng (cột) và mức xếp loại (hàng)."""
    groups = PositionGroup.query.filter_by(form=form, active=True).order_by(PositionGroup.sort).all()
    gids = {g.id for g in groups}
    evals = _scoped_evaluations(actor, period, DONE)
    used = [e for e in evals if _group_of(e) in gids]
    missing = [e for e in evals if _group_of(e) is None]

    def count(pred):
        per = {g.id: sum(1 for e in used if _group_of(e) == g.id and pred(e)) for g in groups}
        return {"total": sum(per.values()), "per": per}

    good = count(lambda e: e.final_rating in (Rating.HTXS, Rating.HTT))
    excellent = count(lambda e: e.final_rating == Rating.HTXS)

    def ratio(num, den):
        return round(num * 100 / den, 2) if den else None

    rows = [
        {"no": "", "label": "Tổng số", "cells": count(lambda e: True), "bold": True},
        {"no": "I", "label": "Kết quả xếp loại", "cells": None, "bold": True},
        {"no": "1", "label": "HTTNV trở lên", "cells": good},
        {"no": "", "label": "Trong đó, HTXSNV", "cells": excellent, "italic": True},
        {"no": "", "label": "Tỷ lệ = HTXSNV/HTTNV trở lên*100 (đơn vị tính là %)", "italic": True, "ratio": {
            "total": ratio(excellent["total"], good["total"]),
            "per": {g.id: ratio(excellent["per"][g.id], good["per"][g.id]) for g in groups}}},
        {"no": "2", "label": "HTNV", "cells": count(lambda e: e.final_rating == Rating.HT)},
        {"no": "3", "label": "KHTNV", "cells": count(lambda e: e.final_rating == Rating.KHT)},
        {"no": "II", "label": "Mức độ đáp ứng đối với các mục tiêu, nhiệm vụ then chốt", "cells": None, "bold": True},
    ]
    for code, label in ResponseLevel.CHOICES:
        rows.append({"no": str(code), "label": label, "cells": count(lambda e, c=code: e.response_level == c)})
    over = [g for g in groups
            if excellent["per"][g.id] and good["per"][g.id] and excellent["per"][g.id] * 100 > good["per"][g.id] * 20]
    return {"groups": groups, "rows": rows, "considered": len(used), "missing_group": len(missing),
            "over_quota": over, "small_groups": [g for g in groups if 0 < good["per"][g.id] < 5]}
