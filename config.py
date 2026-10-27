"""config.py - Cấu hình ứng dụng (đọc từ biến môi trường / file .env)."""
import os
from datetime import timedelta

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DEFAULT_SECRET_KEY = "doi-khoa-bi-mat-nay-khi-trien-khai"


def _flag(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", DEFAULT_SECRET_KEY)
    # Nếu không đặt DATABASE_URL, app.py sẽ dùng instance/kpi.db
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JSON_AS_ASCII = False

    # --- Phiên đăng nhập ---
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # Đặt COOKIE_SECURE=1 khi chạy qua HTTPS
    SESSION_COOKIE_SECURE = _flag("COOKIE_SECURE")
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = _flag("COOKIE_SECURE")
    REMEMBER_COOKIE_DURATION = timedelta(days=7)
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)

    # --- Đăng ký tài khoản ---
    REGISTRATION_ENABLED = _flag("REGISTRATION_ENABLED", "1")

    # Thang điểm theo Phụ lục 2 (Quy định 89-QĐ/TU)
    COMMON_MAX_SCORE = 30
    RESULT_MAX_SCORE = 70
    STANDARD_TASK_SCORE = 100   # điểm của sản phẩm/công việc chuẩn
    MAX_TASK_SCORE = 200        # điểm chấm công việc cụ thể tối đa
    EXCELLENT_MAX_RATIO = 0.20  # HTXS không vượt quá 20% số HTT (Quy định 89-QĐ/TU)
    MIN_GROUP_SIZE = 5          # mỗi nhóm đối tượng tối thiểu 5 cán bộ


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False


CONFIGS = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}


def get_config(name: str | None = None):
    return CONFIGS.get(name or os.environ.get("FLASK_ENV", "development"), DevelopmentConfig)
