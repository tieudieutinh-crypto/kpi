"""services/auth.py - Xác thực, chính sách mật khẩu, tạo tài khoản."""
from __future__ import annotations

import re
import secrets
import string
from datetime import datetime, timedelta

from werkzeug.security import check_password_hash, generate_password_hash

from models import Department, Role, User, db

MAX_FAILED_ATTEMPTS = 5      # nhập sai quá 5 lần liên tiếp -> tạm khóa
LOCK_MINUTES = 15

USERNAME_RE = re.compile(r"^[a-z0-9_.-]{3,50}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PASSWORD_MIN, PASSWORD_MAX = 8, 128
WEAK_PASSWORDS = {
    "12345678", "123456789", "1234567890", "password", "password1", "matkhau123",
    "qwerty123", "abc12345", "11111111", "admin123", "admin1234",
}

GENERIC_LOGIN_ERROR = "Tên đăng nhập hoặc mật khẩu không đúng, hoặc tài khoản đang tạm khóa."

# Băm giả để thời gian phản hồi không tiết lộ tên đăng nhập có tồn tại hay không
_DUMMY_HASH = generate_password_hash("mat-khau-gia-de-can-bang-thoi-gian")


class ValidationError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


# --------------------------------------------------------------------------- #
# Kiểm tra dữ liệu đầu vào
# --------------------------------------------------------------------------- #
def normalize_username(username: str | None) -> str:
    return (username or "").strip().lower()


def validate_password(password: str, username: str = "", full_name: str = "") -> list[str]:
    errors = []
    if len(password) < PASSWORD_MIN:
        errors.append(f"Mật khẩu phải có ít nhất {PASSWORD_MIN} ký tự.")
    if len(password) > PASSWORD_MAX:
        errors.append(f"Mật khẩu không được dài quá {PASSWORD_MAX} ký tự.")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        errors.append("Mật khẩu phải gồm cả chữ và số.")
    if password.lower() in WEAK_PASSWORDS:
        errors.append("Mật khẩu quá phổ biến, hãy chọn mật khẩu khác.")
    if username and password.lower() == username.lower():
        errors.append("Mật khẩu không được trùng tên đăng nhập.")
    return errors


def validate_new_user(username: str, full_name: str, email: str | None, password: str) -> list[str]:
    errors = []
    if not USERNAME_RE.match(username):
        errors.append("Tên đăng nhập gồm 3-50 ký tự: chữ thường, số, dấu chấm, gạch dưới hoặc gạch ngang.")
    elif User.query.filter_by(username=username).first():
        errors.append("Tên đăng nhập đã được sử dụng.")
    if not full_name.strip():
        errors.append("Vui lòng nhập họ và tên.")
    if email and not EMAIL_RE.match(email):
        errors.append("Địa chỉ email không hợp lệ.")
    errors.extend(validate_password(password, username, full_name))
    return errors


def generate_temp_password(length: int = 12) -> str:
    alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(length))
        if re.search(r"[A-Za-z]", pw) and re.search(r"\d", pw):
            return pw


# --------------------------------------------------------------------------- #
# Tài khoản
# --------------------------------------------------------------------------- #
def create_user(
    username: str,
    full_name: str,
    password: str,
    *,
    role: str = Role.STAFF,
    department_id: int | None = None,
    email: str | None = None,
    approved: bool = False,
    must_change_password: bool = False,
    commit: bool = True,
) -> User:
    """Tạo tài khoản. Ném ValidationError nếu dữ liệu không hợp lệ."""
    username = normalize_username(username)
    full_name = (full_name or "").strip()
    email = (email or "").strip() or None
    errors = validate_new_user(username, full_name, email, password)
    if role not in Role.RANK:
        errors.append("Vai trò không hợp lệ.")
    if department_id is not None and not db.session.get(Department, department_id):
        errors.append("Phòng ban không tồn tại.")
    if errors:
        raise ValidationError(errors)

    user = User(
        username=username, full_name=full_name, email=email, role=role,
        department_id=department_id, approved=approved, active=True,
        must_change_password=must_change_password,
    )
    user.set_password(password)
    db.session.add(user)
    if commit:
        db.session.commit()
    return user


def active_admin_count() -> int:
    return User.query.filter_by(role=Role.ADMIN, active=True, approved=True).count()


def admin_exists() -> bool:
    return User.query.filter_by(role=Role.ADMIN).first() is not None


def authenticate(username: str, password: str) -> tuple[User | None, str | None]:
    """Kiểm tra đăng nhập. Trả về (user, None) nếu hợp lệ, ngược lại (None, thông báo lỗi).
    Thông báo chung cho sai tên/mật khẩu để tránh dò tìm tài khoản."""
    now = datetime.utcnow()
    password = password or ""
    user = User.query.filter_by(username=normalize_username(username)).first()

    if user is None:
        check_password_hash(_DUMMY_HASH, password)
        return None, GENERIC_LOGIN_ERROR

    if user.locked_until and user.locked_until > now:
        check_password_hash(_DUMMY_HASH, password)
        return None, GENERIC_LOGIN_ERROR

    if not user.check_password(password):
        user.failed_attempts = (user.failed_attempts or 0) + 1
        if user.failed_attempts >= MAX_FAILED_ATTEMPTS:
            user.locked_until = now + timedelta(minutes=LOCK_MINUTES)
            user.failed_attempts = 0
        db.session.commit()
        return None, GENERIC_LOGIN_ERROR

    # Mật khẩu đúng: chỉ lúc này mới nói rõ trạng thái tài khoản
    if not user.approved:
        return None, "Tài khoản đang chờ quản trị viên duyệt."
    if not user.active:
        return None, "Tài khoản đã bị khóa. Vui lòng liên hệ quản trị viên."

    user.failed_attempts = 0
    user.locked_until = None
    user.last_login_at = now
    db.session.commit()
    return user, None
