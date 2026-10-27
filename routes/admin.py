"""routes/admin.py - Quản trị danh mục: Phòng, Ban (chỉ cấp thành phố, không có cấp xã, phường);
kỳ đánh giá (quý). (Bảng hệ số KPI sẽ bổ sung ở lượt sau, dùng quyền coefficient.manage.)"""
from flask import Blueprint, flash, redirect, render_template, request, url_for

from models import Department, Period, User, db
from permissions import permission_required
from services.common import parse_date

bp = Blueprint("admin", __name__, url_prefix="/admin")

@bp.route("/departments")
@permission_required("department.manage")
def departments():
    items = Department.query.order_by(Department.name).all()
    edit_id = request.args.get("edit", type=int)
    editing = db.session.get(Department, edit_id) if edit_id else None
    counts = dict(db.session.query(User.department_id, db.func.count(User.id))
                  .filter(User.active.is_(True), User.approved.is_(True)).group_by(User.department_id).all())
    return render_template("departments.html", items=items, editing=editing, counts=counts)


@bp.route("/departments/save", methods=["POST"])
@permission_required("department.manage")
def save_department():
    f = request.form
    dept_id = f.get("id", type=int)
    dept = db.get_or_404(Department, dept_id) if dept_id else Department()

    code = f.get("code", "").strip().upper()
    name = f.get("name", "").strip()

    errors = []
    if not code or not name:
        errors.append("Vui lòng nhập mã và tên Phòng, Ban.")
    if len(code) > 50 or len(name) > 255:
        errors.append("Mã tối đa 50 ký tự, tên tối đa 255 ký tự.")
    other = Department.query.filter_by(code=code).first()
    if other and other.id != dept.id:
        errors.append("Mã Phòng, Ban đã tồn tại.")

    if errors:
        for message in errors:
            flash(message, "error")
        return redirect(url_for("admin.departments", edit=dept.id) if dept.id else url_for("admin.departments"))

    dept.code, dept.name = code, name
    dept.level, dept.parent_id = "thanh_pho", None          # hệ thống chỉ có cấp thành phố
    dept.active = bool(f.get("active")) if dept.id else True
    db.session.add(dept)
    db.session.commit()
    flash("Đã lưu Phòng, Ban.", "success")
    return redirect(url_for("admin.departments"))


# --------------------------------------------------------------------------- #
# Kỳ đánh giá
# --------------------------------------------------------------------------- #
@bp.route("/periods")
@permission_required("period.manage")
def periods():
    items = Period.query.order_by(Period.year.desc(), Period.quarter.desc()).all()
    return render_template("periods.html", items=items)


@bp.route("/periods/create", methods=["POST"])
@permission_required("period.manage")
def create_period():
    year = request.form.get("year", type=int)
    quarter = request.form.get("quarter", type=int)
    if not year or not 2020 <= year <= 2100 or quarter not in (1, 2, 3, 4):
        flash("Năm (2020-2100) hoặc quý (1-4) không hợp lệ.", "error")
    elif Period.query.filter_by(year=year, quarter=quarter).first():
        flash("Kỳ đánh giá này đã tồn tại.", "error")
    else:
        db.session.add(Period.build(year, quarter))
        db.session.commit()
        flash(f"Đã tạo Quý {quarter}/{year} với các mốc hạn mặc định (ngày 15, 18, 22).", "success")
    return redirect(url_for("admin.periods"))


@bp.route("/periods/<int:pid>/deadlines", methods=["POST"])
@permission_required("period.manage")
def period_deadlines(pid):
    period = db.get_or_404(Period, pid)
    errors: list[str] = []
    values = {
        "deadline_m1_m3": parse_date(request.form.get("deadline_m1_m3"), "Hạn Mẫu 1, 3", errors),
        "deadline_m2": parse_date(request.form.get("deadline_m2"), "Hạn Mẫu 2", errors),
        "deadline_m4_m8": parse_date(request.form.get("deadline_m4_m8"), "Hạn Mẫu 4-8", errors),
    }
    if errors:
        for message in errors:
            flash(message, "error")
    else:
        for field, value in values.items():
            setattr(period, field, value)
        db.session.commit()
        flash("Đã cập nhật các mốc thời hạn.", "success")
    return redirect(url_for("admin.periods"))


@bp.route("/periods/<int:pid>/toggle", methods=["POST"])
@permission_required("period.manage")
def toggle_period(pid):
    period = db.get_or_404(Period, pid)
    period.status = "closed" if period.status == "open" else "open"
    db.session.commit()
    flash(f"{period.name} đã {'mở' if period.status == 'open' else 'đóng'}. "
          + ("" if period.status == "open" else "Mọi thao tác chỉnh sửa, gửi, duyệt trong kỳ này bị khóa."), "success")
    return redirect(url_for("admin.periods"))
