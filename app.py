"""
app.py - Điểm khởi chạy ứng dụng chấm KPI đánh giá cán bộ hằng quý (Flask + SQLite).

Chạy thử:
    pip install -r requirements.txt
    python create_admin.py                  # tạo tài khoản quản trị đầu tiên (tự tạo bảng nếu chưa có)
    flask --app app create-period --year 2026 --quarter 4
    flask --app app run --debug
"""
import importlib
import os
import sqlite3

import click
from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from flask_login import LoginManager, current_user, login_required
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

from config import DEFAULT_SECRET_KEY, get_config
from models import (
    CollectiveStatus, Department, EvalStatus, PlanStatus, Indicator, Period, PersonalEvaluation, Rating, Role, User, db,
)
from migrate import upgrade_schema
from permissions import can
from seed import seed_all
from services import dashboard
from services.auth import ValidationError, create_user

csrf = CSRFProtect()
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Vui lòng đăng nhập để tiếp tục."
login_manager.login_message_category = "error"

# Mỗi module khai báo biến `bp`. Module nào chưa có thì bỏ qua (sẽ bổ sung ở các lượt sau).
BLUEPRINT_MODULES = [
    "routes.auth",         # đăng nhập, đăng ký, tài khoản cá nhân
    "routes.users",        # quản lý người dùng
    "routes.admin",        # phòng ban, kỳ đánh giá (sau này: hệ số)
    "routes.collective",   # Mẫu 1, Mẫu 2 - chỉ tiêu và KPI tập thể
    "routes.kpi",          # Mẫu 3, 4, 5 - KPI cá nhân, nhận xét, phê duyệt xếp loại
    "routes.reports",      # Mẫu 6, 7, 8 và xuất Excel (chưa làm)
]

# Trang được phép truy cập khi bị buộc đổi mật khẩu
ALLOWED_WHEN_PASSWORD_EXPIRED = {"auth.change_password", "auth.logout", "static"}


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _record):
    """SQLite mặc định không kiểm tra khóa ngoại; bật lên để ràng buộc dữ liệu."""
    if isinstance(dbapi_connection, sqlite3.Connection):
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


def get_current_period():
    """Kỳ đánh giá đang mở gần nhất (None nếu chưa có hoặc CSDL chưa khởi tạo)."""
    try:
        return (
            Period.query.filter_by(status="open")
            .order_by(Period.year.desc(), Period.quarter.desc())
            .first()
        )
    except OperationalError:
        return None


def create_app(config_name: str | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(get_config(config_name))
    os.makedirs(app.instance_path, exist_ok=True)

    if not app.config.get("SQLALCHEMY_DATABASE_URI"):
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(app.instance_path, "kpi.db")

    if not (app.debug or app.testing) and app.config["SECRET_KEY"] == DEFAULT_SECRET_KEY:
        raise RuntimeError("Chưa đặt SECRET_KEY. Hãy đặt biến môi trường SECRET_KEY trước khi chạy production.")

    db.init_app(app)
    csrf.init_app(app)
    login_manager.init_app(app)

    if not app.testing and app.config.get("AUTO_UPGRADE_DB", True):
        with app.app_context():       # tạo bảng/cột còn thiếu, giữ nguyên dữ liệu cũ
            upgrade_schema()
            seed_all()

    @login_manager.user_loader
    def load_user(user_id: str):
        """Cookie phiên chứa '<id>:<session_token>'; chỉ chấp nhận khi token khớp với CSDL."""
        try:
            uid, token = str(user_id).split(":", 1)
            user = db.session.get(User, int(uid))
        except (ValueError, TypeError):
            return None
        if user is None or not user.is_active:
            return None
        import hmac
        if not hmac.compare_digest(user.session_token, token):
            return None
        return user

    register_blueprints(app)
    register_routes(app)
    register_hooks(app)
    register_errors(app)
    register_cli(app)
    return app


# --------------------------------------------------------------------------- #
def register_blueprints(app: Flask) -> None:
    for module_name in BLUEPRINT_MODULES:
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            if exc.name and module_name.startswith(exc.name):
                continue  # module chưa được viết
            raise
        app.register_blueprint(module.bp)


def register_hooks(app: Flask) -> None:
    @app.before_request
    def force_password_change():
        if (current_user.is_authenticated and current_user.must_change_password
                and request.endpoint not in ALLOWED_WHEN_PASSWORD_EXPIRED):
            flash("Bạn cần đổi mật khẩu trước khi tiếp tục.", "error")
            return redirect(url_for("auth.change_password"))

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if current_user.is_authenticated:
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.context_processor
    def inject_globals():
        period = get_current_period()
        pending = 0
        if current_user.is_authenticated and (can("kpi.review") or can("kpi.approve")) and period:
            from routes.kpi import pending_count
            pending = pending_count(current_user, period.id)
        return {
            "asset_v": _asset_version(app),
            "current_period": period,
            "pending_review": pending,
            "can": can,
            "csrf_meta": True,
            "Role": Role,
            "Rating": Rating,
            "EvalStatus": EvalStatus,
            "CollectiveStatus": CollectiveStatus,
            "PlanStatus": PlanStatus,
        }


def _asset_version(app: Flask) -> str:
    """Phiên bản tệp tĩnh (thời điểm sửa mới nhất) để trình duyệt tải lại CSS/JS sau mỗi lần cập nhật."""
    newest = 0.0
    for root, _dirs, files in os.walk(app.static_folder):
        for name in files:
            newest = max(newest, os.path.getmtime(os.path.join(root, name)))
    return str(int(newest))


def register_routes(app: Flask) -> None:
    @app.route("/")
    @login_required
    def index():
        data = dashboard.build(current_user, get_current_period(), dept_filter=request.args.get("ban", type=int))
        return render_template("index.html", d=data)

    @app.route("/health")
    def health():
        return jsonify(status="ok")


def register_errors(app: Flask) -> None:
    @app.errorhandler(400)
    def bad_request(_e):
        return render_template("error.html", code=400,
                               message="Yêu cầu không hợp lệ hoặc phiên làm việc đã hết hạn. Hãy tải lại trang và thử lại."), 400

    @app.errorhandler(403)
    def forbidden(_e):
        return render_template("error.html", code=403, message="Bạn không có quyền truy cập trang này."), 403

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("error.html", code=404, message="Không tìm thấy trang yêu cầu."), 404

    @app.errorhandler(405)
    def not_allowed(_e):
        return render_template("error.html", code=405, message="Phương thức không được hỗ trợ."), 405


def register_cli(app: Flask) -> None:
    @app.cli.command("init-db")
    def init_db():
        """Tạo các bảng và nạp dữ liệu danh mục mặc định (6 trục, hệ số KPI, tiêu chí chung...)."""
        db.create_all()
        seed_all()
        click.echo("Đã khởi tạo CSDL và nạp dữ liệu danh mục.")

    @app.cli.command("upgrade-db")
    def upgrade_db():
        """Thêm bảng/cột còn thiếu sau khi cập nhật mã nguồn (không mất dữ liệu)."""
        changes = upgrade_schema()
        seed_all()
        click.echo("Đã thêm: " + ", ".join(changes) if changes else "CSDL đã ở phiên bản mới nhất.")

    @app.cli.command("seed")
    def seed():
        """Nạp lại dữ liệu danh mục (chỉ thêm phần còn thiếu)."""
        seed_all()
        click.echo("Đã nạp dữ liệu danh mục.")

    @app.cli.command("create-admin")
    @click.option("--username", prompt=True)
    @click.option("--full-name", prompt="Họ và tên")
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    def create_admin(username, full_name, password):
        """Tạo thêm tài khoản quản trị (tài khoản đầu tiên nên tạo bằng create_admin.py)."""
        try:
            user = create_user(username, full_name, password, role=Role.ADMIN, approved=True)
        except ValidationError as exc:
            raise click.ClickException("\n".join(exc.errors))
        click.echo(f"Đã tạo quản trị viên '{user.username}'.")

    @app.cli.command("create-period")
    @click.option("--year", type=int, prompt=True)
    @click.option("--quarter", type=click.IntRange(1, 4), prompt=True)
    def create_period(year, quarter):
        """Tạo kỳ đánh giá quý kèm các mốc thời hạn (ngày 15 / 18 / 22)."""
        if Period.query.filter_by(year=year, quarter=quarter).first():
            raise click.ClickException("Kỳ đánh giá này đã tồn tại.")
        period = Period.build(year, quarter)
        db.session.add(period)
        db.session.commit()
        click.echo(f"Đã tạo {period.name}: hạn Mẫu 1,3 = {period.deadline_m1_m3}, "
                   f"Mẫu 2 = {period.deadline_m2}, Mẫu 4-8 = {period.deadline_m4_m8}.")


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
