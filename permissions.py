"""
permissions.py - Phân quyền theo trang (capability) và phạm vi dữ liệu theo Phòng, Ban.

Mỗi trang/chức năng gắn với 1 "quyền" (capability) trong CAPABILITIES; route dùng
@permission_required("tên.quyền"). Khi thêm trang mới chỉ cần thêm 1 dòng vào CAPABILITIES.

Cơ cấu phẳng (chỉ cấp thành phố): cơ quan gồm các Phòng, Ban ngang nhau.
  - Quản trị hệ thống (admin)      : người dùng, Phòng Ban, kỳ đánh giá; KHÔNG chấm, duyệt KPI.
  - Phó Bí thư Thường trực (PBT)   : lãnh đạo cơ quan; xem toàn bộ; duyệt cuối KPI tập thể của mọi Ban,
                                     duyệt cuối Mẫu 3 và quyết định xếp loại (Mẫu 5) của mọi cán bộ.
                                     Tự lập KPI cá nhân nhưng không trình ai.
  - Lãnh đạo đơn vị (Phó Trưởng Ban TT, Phó Chánh Văn phòng TT, Phó Chủ nhiệm UBKT TT):
                                     lập, trình KPI tập thể của đơn vị; duyệt Mẫu 3 và nhận xét Mẫu 5 của
                                     cấp phó, công chức trong đơn vị.
  - Cấp phó (Phó Trưởng Ban, Phó Chánh VP, Phó Chủ nhiệm UBKT, Ủy viên CT UBKT), Công chức:
                                     chỉ hồ sơ của chính mình.

Chuỗi trình duyệt KPI cá nhân:
  Công chức, cấp phó  ->  lãnh đạo đơn vị (cấp Thường trực) cùng đơn vị  ->  Phó Bí thư duyệt cuối
  Lãnh đạo đơn vị     ->  Phó Bí thư duyệt cuối
  Phó Bí thư                 :  chỉ lưu, không trình
"""
from __future__ import annotations

from functools import wraps

from flask import abort
from flask_login import current_user

from models import Department, PlanStatus, Role, User

A, PBT, CC = Role.ADMIN, Role.PBT, Role.CC
LEADERS = set(Role.UNIT_LEADERS)        # lãnh đạo đơn vị (Phó TB TT, Phó CVP TT, Phó CN UBKT TT)
DEPUTIES = set(Role.DEPUTIES)           # cấp phó (Phó TB, Phó CVP, Phó CN UBKT, Ủy viên CT UBKT)
EVALUATORS = set(Role.EVALUATED)
EVERYONE = EVALUATORS | {A}

# quyền -> các vai trò được phép
CAPABILITIES: dict[str, set[str]] = {
    # --- Chung ---
    "dashboard.view":      EVERYONE,
    "account.manage":      EVERYONE,
    "team.view":           {A, PBT} | LEADERS,     # số liệu, tiến độ của cán bộ trong phạm vi (dashboard)

    # --- Quản trị hệ thống ---
    "user.list":           {A},                    # menu Người dùng
    "user.manage":         {A},                    # thêm, sửa, khóa, đặt lại mật khẩu, đăng xuất thiết bị
    "department.manage":   {A},                    # Phòng, Ban
    "period.manage":       {A},                    # Kỳ đánh giá
    "coefficient.manage":  {A},                    # Bảng hệ số KPI

    # --- KPI tập thể (Mẫu 1, 2) ---
    "indicator.view":      EVERYONE,
    "indicator.manage":    LEADERS,                # chỉ lãnh đạo đơn vị (cấp Thường trực) của chính đơn vị
    "indicator.approve":   {PBT},                  # lãnh đạo cơ quan duyệt cuối

    # --- KPI cá nhân (Mẫu 3, 4, 5) ---
    "kpi.self":            EVALUATORS,
    "kpi.review":          LEADERS,                # duyệt Mẫu 3 cấp đơn vị, nhận xét Mẫu 5
    "kpi.approve":         {PBT},                  # duyệt cuối Mẫu 3, quyết định xếp loại
    "kpi.reopen_plan":     {A, PBT},               # mở lại Mẫu 3 đã trình

    "report.view":         {A, PBT} | LEADERS,
    "report.export":       {A, PBT},
}


def can(capability: str, user=None) -> bool:
    user = user or current_user
    if not getattr(user, "is_authenticated", False):
        return False
    return user.role in CAPABILITIES.get(capability, set())


def permission_required(*capabilities: str):
    """Yêu cầu đăng nhập và có ÍT NHẤT MỘT trong các quyền; chưa đăng nhập -> chuyển tới trang đăng nhập."""
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                return current_app_login_manager().unauthorized()
            if not any(can(c) for c in capabilities):
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


def current_app_login_manager():
    from flask import current_app
    return current_app.login_manager  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- #
# Phạm vi người dùng
# --------------------------------------------------------------------------- #
def department_subtree_ids(department_id: int | None) -> set[int]:
    """Cơ cấu phẳng: một Ban chỉ gồm chính nó (giữ hàm để mã cũ gọi được)."""
    return set() if department_id is None else {department_id}


def scope_users_query(actor: User):
    """Truy vấn người dùng mà `actor` được phép xem."""
    if actor.role == A:
        return User.query
    own = User.id == actor.id
    if actor.role == PBT:
        return User.query.filter(User.role != A)
    if actor.role in LEADERS and actor.department_id:
        return User.query.filter(own | ((User.department_id == actor.department_id)
                                        & User.role.in_(tuple(Role.UNIT_MEMBERS))))
    return User.query.filter(own)


def can_view_user(actor: User, target: User) -> bool:
    if actor.id == target.id or actor.role == A:
        return True
    if actor.role == PBT:
        return target.role != A
    if actor.role in LEADERS:
        return (actor.department_id is not None and target.department_id == actor.department_id
                and target.role in Role.UNIT_MEMBERS)
    return False


def can_review_user(actor: User, target: User) -> bool:
    """Lãnh đạo đơn vị: duyệt Mẫu 3 cấp đơn vị, nhận xét Mẫu 5 của cấp phó, công chức cùng đơn vị."""
    if actor.id == target.id or actor.role not in LEADERS or actor.department_id is None:
        return False
    return target.department_id == actor.department_id and (target.role in DEPUTIES or target.role == CC)


def can_approve_user(actor: User, target: User) -> bool:
    """Lãnh đạo cơ quan: duyệt cuối Mẫu 3, quyết định xếp loại cho mọi cán bộ (trừ chính mình)."""
    return actor.role == PBT and actor.id != target.id and target.role in Role.UNIT_MEMBERS


def needs_submission(user: User) -> bool:
    """Phó Bí thư chỉ lưu hồ sơ của mình, không trình ai."""
    return user.role != PBT


# --------------------------------------------------------------------------- #
# KPI tập thể
# --------------------------------------------------------------------------- #
def can_edit_collective(actor: User, department_id: int) -> bool:
    """Lập chỉ tiêu (Mẫu 1), nhập kết quả (Mẫu 2), trình: Phó TB Thường trực của chính Ban đó."""
    return (can("indicator.manage", actor) and department_id is not None
            and actor.department_id == department_id)


def can_approve_collective(actor: User, department_id: int) -> bool:
    return can("indicator.approve", actor) and department_id is not None


def can_view_collective(actor: User, department_id: int) -> bool:
    if department_id is None or not can("indicator.view", actor):
        return False
    return actor.role in (A, PBT) or actor.department_id == department_id


def viewable_departments(actor: User) -> list[Department]:
    """Các Phòng, Ban mà `actor` được xem KPI tập thể."""
    query = Department.query.filter_by(active=True).order_by(Department.name)
    if actor.role in (A, PBT):
        return query.all()
    return [d for d in query.all() if d.id == actor.department_id]


# --------------------------------------------------------------------------- #
# Hồ sơ KPI cá nhân
# --------------------------------------------------------------------------- #
def can_view_evaluation(actor: User, evaluation) -> bool:
    """Chủ hồ sơ luôn xem được. Người khác chỉ xem khi hồ sơ đã trình (Mẫu 3 hoặc Mẫu 5), không xem bản đang lập.
    Quản trị hệ thống xem được hồ sơ đã trình để mở lại Mẫu 3 khi cần."""
    if actor.id == evaluation.user_id:
        return True
    submitted = evaluation.plan_status in PlanStatus.LOCKED or evaluation.status != "draft"
    if not submitted:
        return False
    if actor.role == A:
        return evaluation.user.role != A
    return can_review_user(actor, evaluation.user) or can_approve_user(actor, evaluation.user)
