"""routes/users.py - Danh sách và quản lý người dùng.

  Chỉ Quản trị hệ thống: xem danh sách, thêm, duyệt, sửa thông tin, khóa, đặt lại mật khẩu,
  đăng xuất khỏi mọi thiết bị.
"""
from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user

from models import Department, PositionGroup, Role, User, db
from permissions import permission_required, scope_users_query
from services.auth import (
    EMAIL_RE, ValidationError, active_admin_count, create_user, generate_temp_password,
)

bp = Blueprint("users", __name__, url_prefix="/users")

PER_PAGE = 25


@bp.route("/")
@permission_required("user.list")
def list_users():
    query = scope_users_query(current_user)

    q = request.args.get("q", "").strip()
    if q:
        like = f"%{q}%"
        query = query.filter(User.full_name.ilike(like) | User.username.ilike(like))
    role = request.args.get("role", "")
    if role in Role.RANK:
        query = query.filter(User.role == role)
    status = request.args.get("status", "")
    if status == "pending":
        query = query.filter(User.approved.is_(False))
    elif status == "locked":
        query = query.filter(User.approved.is_(True), User.active.is_(False))
    elif status == "active":
        query = query.filter(User.approved.is_(True), User.active.is_(True))

    page = query.order_by(User.approved.asc(), User.full_name).paginate(
        page=request.args.get("page", 1, type=int), per_page=PER_PAGE, error_out=False
    )
    return render_template("users.html", page=page, q=q, role=role, status=status)


def _user_form(user: User | None):
    departments = Department.query.filter_by(active=True).order_by(Department.name).all()
    groups = PositionGroup.query.filter_by(active=True).order_by(PositionGroup.sort).all()
    is_self = user is not None and user.id == current_user.id

    if request.method == "POST":
        f = request.form
        errors = []
        full_name = f.get("full_name", "").strip()
        email = f.get("email", "").strip() or None
        role = f.get("role", user.role if user else Role.STAFF)
        department_id = f.get("department_id", type=int) or None
        group_id = f.get("position_group_id", type=int) or None

        if not full_name:
            errors.append("Vui lòng nhập họ và tên.")
        if email and not EMAIL_RE.match(email):
            errors.append("Địa chỉ email không hợp lệ.")
        if role not in Role.RANK:
            errors.append("Vai trò không hợp lệ.")
        if department_id and not db.session.get(Department, department_id):
            errors.append("Phòng ban không tồn tại.")
        if role in Role.NEEDS_DEPARTMENT and not department_id:
            errors.append(f"{Role.LABELS[role]} phải được gán Phòng, Ban để xác định người duyệt.")

        if user is not None:
            if is_self and role != user.role:
                errors.append("Không thể tự đổi vai trò của chính mình.")
            if (user.role == Role.ADMIN and role != Role.ADMIN and active_admin_count() <= 1):
                errors.append("Hệ thống phải còn ít nhất một quản trị viên đang hoạt động.")

        if not errors:
            if user is None:
                try:
                    user = create_user(
                        f.get("username"), full_name, f.get("password", ""),
                        role=role, department_id=department_id, email=email,
                        approved=True, must_change_password=True, commit=False,
                    )
                except ValidationError as exc:
                    errors.extend(exc.errors)
            else:
                needs_relogin = (user.role != role or user.department_id != department_id)
                user.full_name, user.email, user.role = full_name, email, role
                user.department_id = department_id
                if needs_relogin:
                    user.rotate_token()   # quyền thay đổi -> buộc đăng nhập lại
            if not errors:
                user.phone = f.get("phone", "").strip() or None
                user.position_group_id = group_id
                user.party_position = f.get("party_position", "").strip() or None
                user.gov_position = f.get("gov_position", "").strip() or None
                user.org_position = f.get("org_position", "").strip() or None
                user.is_head = bool(f.get("is_head"))
                db.session.commit()
                flash("Đã lưu người dùng.", "success")
                return redirect(url_for("users.list_users"))
        db.session.rollback()
        for message in errors:
            flash(message, "error")
        form_user = f
    else:
        form_user = user
    return render_template(
        "user_form.html", user=user, form=form_user, departments=departments,
        groups=groups, is_self=is_self,
    )


@bp.route("/new", methods=["GET", "POST"])
@permission_required("user.manage")
def new_user():
    return _user_form(None)


@bp.route("/<int:uid>/edit", methods=["GET", "POST"])
@permission_required("user.manage")
def edit_user(uid: int):
    return _user_form(db.get_or_404(User, uid))


@bp.route("/<int:uid>/approve", methods=["POST"])
@permission_required("user.manage")
def approve(uid: int):
    user = db.get_or_404(User, uid)
    user.approved = True
    user.active = True
    db.session.commit()
    flash(f"Đã duyệt tài khoản {user.username}. Hãy kiểm tra vai trò và Phòng, Ban của người dùng.", "success")
    return redirect(request.referrer or url_for("users.list_users"))


@bp.route("/<int:uid>/reject", methods=["POST"])
@permission_required("user.manage")
def reject(uid: int):
    user = db.get_or_404(User, uid)
    if user.approved:
        flash("Chỉ có thể từ chối tài khoản đang chờ duyệt.", "error")
    else:
        db.session.delete(user)
        db.session.commit()
        flash(f"Đã từ chối và xóa đăng ký của {user.username}.", "success")
    return redirect(url_for("users.list_users", status="pending"))


@bp.route("/<int:uid>/toggle-lock", methods=["POST"])
@permission_required("user.manage")
def toggle_lock(uid: int):
    user = db.get_or_404(User, uid)
    if user.id == current_user.id:
        flash("Không thể tự khóa tài khoản của chính mình.", "error")
    elif user.active and user.role == Role.ADMIN and active_admin_count() <= 1:
        flash("Không thể khóa quản trị viên cuối cùng.", "error")
    else:
        user.active = not user.active
        user.failed_attempts, user.locked_until = 0, None
        if not user.active:
            user.rotate_token()   # ngắt ngay các phiên đang đăng nhập
        db.session.commit()
        flash(("Đã mở khóa " if user.active else "Đã khóa ") + f"tài khoản {user.username}.", "success")
    return redirect(request.referrer or url_for("users.list_users"))


@bp.route("/<int:uid>/reset-password", methods=["POST"])
@permission_required("user.manage")
def reset_password(uid: int):
    user = db.get_or_404(User, uid)
    if user.id == current_user.id:
        flash("Hãy dùng chức năng Đổi mật khẩu trong trang Tài khoản.", "error")
    else:
        temp = generate_temp_password()
        user.set_password(temp)
        user.must_change_password = True
        user.failed_attempts, user.locked_until = 0, None
        user.rotate_token()
        db.session.commit()
        flash(f"Mật khẩu tạm của {user.username}: {temp} (chỉ hiển thị một lần; người dùng phải đổi khi đăng nhập).",
              "warning")
    return redirect(request.referrer or url_for("users.list_users"))


@bp.route("/<int:uid>/force-logout", methods=["POST"])
@permission_required("user.manage")
def force_logout(uid: int):
    user = db.get_or_404(User, uid)
    user.rotate_token()
    db.session.commit()
    if user.id == current_user.id:
        return redirect(url_for("auth.login"))
    flash(f"Đã đăng xuất {user.username} khỏi mọi thiết bị.", "success")
    return redirect(request.referrer or url_for("users.list_users"))


def kpi_data_of(user: User) -> list[str]:
    """Các loại dữ liệu đánh giá gắn với người dùng (có thì không xóa, để không mất lịch sử)."""
    from models import CollectiveEvaluation, Indicator, PersonalEvaluation, WorkflowLog
    pe, ce = PersonalEvaluation, CollectiveEvaluation
    found = []
    if pe.query.filter_by(user_id=user.id).count():
        found.append("hồ sơ KPI cá nhân")
    if pe.query.filter((pe.reviewed_by_id == user.id) | (pe.approved_by_id == user.id)
                       | (pe.plan_ban_approved_by_id == user.id) | (pe.plan_approved_by_id == user.id)).count():
        found.append("nhận xét, phê duyệt hồ sơ của người khác")
    if ce.query.filter((ce.submitted_by_id == user.id) | (ce.confirmed_by_id == user.id)
                       | (ce.result_submitted_by_id == user.id) | (ce.result_confirmed_by_id == user.id)).count():
        found.append("KPI tập thể")
    if Indicator.query.filter_by(leader_id=user.id).count():
        found.append("phụ trách chỉ tiêu KPI tập thể")
    if WorkflowLog.query.filter_by(user_id=user.id).count():
        found.append("lịch sử xử lý hồ sơ")
    return found


@bp.route("/<int:uid>/delete", methods=["POST"])
@permission_required("user.manage")
def delete_user(uid: int):
    user = db.get_or_404(User, uid)
    if user.id == current_user.id:
        flash("Không thể tự xóa tài khoản của chính mình.", "error")
    elif user.role == Role.ADMIN and user.active and user.approved and active_admin_count() <= 1:
        flash("Không thể xóa quản trị viên cuối cùng.", "error")
    else:
        data = kpi_data_of(user)
        if data:
            flash(f"Không xóa được {user.username} vì đã có dữ liệu đánh giá ({', '.join(data)}). "
                  "Hãy dùng «Khóa» để ngừng sử dụng tài khoản mà vẫn giữ lịch sử.", "error")
        else:
            name = user.username
            db.session.delete(user)
            db.session.commit()
            current_app.logger.warning("Quản trị viên %s đã xóa người dùng %s (id=%s)", current_user.username, name, uid)
            flash(f"Đã xóa người dùng {name}.", "success")
    return redirect(request.referrer or url_for("users.list_users"))
