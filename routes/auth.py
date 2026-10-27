"""routes/auth.py - Đăng nhập, đăng ký, đăng xuất, thông tin cá nhân, đổi mật khẩu."""
from datetime import datetime
from urllib.parse import urlparse

from flask import (
    Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for,
)
from flask_login import current_user, login_required, login_user, logout_user

from models import Department, Role, db
from permissions import permission_required
from services.auth import (
    EMAIL_RE, ValidationError, authenticate, create_user, validate_password,
)

bp = Blueprint("auth", __name__)


def _is_safe_next(target: str | None) -> bool:
    if not target or not target.startswith("/") or target.startswith("//"):
        return False
    parsed = urlparse(target)
    return not parsed.netloc and not parsed.scheme


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    if request.method == "POST":
        user, error = authenticate(request.form.get("username"), request.form.get("password"))
        if user:
            session.clear()  # tránh giữ lại dữ liệu phiên cũ
            login_user(user, remember=bool(request.form.get("remember")))
            session.permanent = True
            if user.must_change_password:
                return redirect(url_for("auth.change_password"))
            nxt = request.args.get("next")
            return redirect(nxt if _is_safe_next(nxt) else url_for("index"))
        flash(error, "error")
    return render_template("login.html", username=request.form.get("username", ""))


@bp.route("/register", methods=["GET", "POST"])
def register():
    if not current_app.config.get("REGISTRATION_ENABLED", True):
        abort(404)
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    departments = Department.query.filter_by(active=True).order_by(Department.name).all()
    form = request.form
    if request.method == "POST":
        # Ô bẫy dành cho bot: người thật không nhìn thấy nên không điền
        if form.get("website"):
            return redirect(url_for("auth.login"))

        errors = []
        password = form.get("password", "")
        if password != form.get("confirm_password", ""):
            errors.append("Mật khẩu nhập lại không khớp.")
        department_id = form.get("department_id", type=int)
        if not department_id:
            errors.append("Vui lòng chọn Phòng, Ban.")
        elif not any(d.id == department_id for d in departments):
            errors.append("Phòng, Ban không hợp lệ.")
        role = form.get("role", "")
        if role not in Role.SELF_REGISTER:          # không cho tự đăng ký Quản trị hệ thống, Phó Bí thư
            errors.append("Vui lòng chọn vai trò hợp lệ.")
        try:
            if not errors:
                # Vai trò do người đăng ký chọn trong danh sách cho phép; tài khoản chưa được duyệt,
                # Quản trị hệ thống kiểm tra (và sửa nếu cần) vai trò trước khi duyệt.
                create_user(
                    form.get("username"), form.get("full_name"), password,
                    role=role, department_id=department_id or None,
                    email=form.get("email"), approved=False,
                )
                flash("Đăng ký thành công. Tài khoản cần được quản trị viên duyệt trước khi đăng nhập.", "success")
                return redirect(url_for("auth.login"))
        except ValidationError as exc:
            errors.extend(exc.errors)
        for message in errors:
            flash(message, "error")
    return render_template("register.html", departments=departments, form=form,
                           roles=Role.choices_for(Role.SELF_REGISTER))


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    session.clear()
    flash("Bạn đã đăng xuất.", "success")
    return redirect(url_for("auth.login"))


@bp.route("/account", methods=["GET", "POST"])
@permission_required("account.manage")
def account():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip() or None
        errors = []
        if not full_name:
            errors.append("Vui lòng nhập họ và tên.")
        if email and not EMAIL_RE.match(email):
            errors.append("Địa chỉ email không hợp lệ.")
        birth_date = None
        raw_birth = request.form.get("birth_date", "").strip()
        if raw_birth:
            try:
                birth_date = datetime.strptime(raw_birth, "%Y-%m-%d").date()
            except ValueError:
                errors.append("Ngày sinh không hợp lệ.")
        if errors:
            for message in errors:
                flash(message, "error")
        else:
            current_user.full_name = full_name
            current_user.email = email
            current_user.phone = request.form.get("phone", "").strip() or None
            current_user.birth_date = birth_date
            current_user.party_position = request.form.get("party_position", "").strip() or None
            current_user.gov_position = request.form.get("gov_position", "").strip() or None
            current_user.org_position = request.form.get("org_position", "").strip() or None
            db.session.commit()
            flash("Đã cập nhật thông tin cá nhân.", "success")
            return redirect(url_for("auth.account"))
    return render_template("account.html")


@bp.route("/account/password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        current = request.form.get("current_password", "")
        new = request.form.get("new_password", "")
        errors = []
        if not current_user.check_password(current):
            errors.append("Mật khẩu hiện tại không đúng.")
        if new != request.form.get("confirm_password", ""):
            errors.append("Mật khẩu mới nhập lại không khớp.")
        if current and new == current:
            errors.append("Mật khẩu mới phải khác mật khẩu hiện tại.")
        errors.extend(validate_password(new, current_user.username, current_user.full_name))
        if errors:
            for message in errors:
                flash(message, "error")
        else:
            user = current_user._get_current_object()
            user.set_password(new)
            user.must_change_password = False
            user.rotate_token()                  # đăng xuất mọi thiết bị khác
            db.session.commit()
            login_user(user)                     # cấp lại phiên cho thiết bị hiện tại
            session.permanent = True
            flash("Đã đổi mật khẩu. Các thiết bị khác đã bị đăng xuất.", "success")
            return redirect(url_for("index"))
    return render_template("change_password.html")


@bp.route("/account/logout-all", methods=["POST"])
@login_required
def logout_all():
    """Đăng xuất mọi thiết bị khác (giữ lại phiên hiện tại)."""
    user = current_user._get_current_object()
    user.rotate_token()
    db.session.commit()
    login_user(user)
    session.permanent = True
    flash("Đã đăng xuất khỏi các thiết bị khác.", "success")
    return redirect(url_for("auth.account"))
