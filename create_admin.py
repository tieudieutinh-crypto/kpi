#!/usr/bin/env python3
"""
create_admin.py - Tạo tài khoản quản trị ĐẦU TIÊN.

Cách dùng (tương tác, khuyên dùng):
    python create_admin.py

Không tương tác (CI, Docker): đặt mật khẩu qua biến môi trường, KHÔNG truyền qua tham số dòng lệnh
(tham số hiện trong lịch sử lệnh và danh sách tiến trình):
    KPI_ADMIN_PASSWORD='MatKhau-Manh-123' python create_admin.py --username admin --full-name "Quản trị viên"

Script tự tạo bảng và nạp dữ liệu danh mục nếu CSDL chưa có. Nếu đã có quản trị viên thì từ chối,
trừ khi dùng --force (để thêm quản trị viên khác).
"""
import argparse
import getpass
import os
import sys

from models import Role, db
from seed import seed_all
from services.auth import (
    ValidationError, admin_exists, normalize_username, validate_password,
)


def _ask_password(username: str, full_name: str) -> str:
    for _ in range(3):
        password = getpass.getpass("Mật khẩu: ")
        errors = validate_password(password, username, full_name)
        if errors:
            print("\n".join(f"  - {e}" for e in errors))
            continue
        if password != getpass.getpass("Nhập lại mật khẩu: "):
            print("  - Mật khẩu nhập lại không khớp.")
            continue
        return password
    raise SystemExit("Nhập sai quá 3 lần, thoát.")


def main(argv=None, app=None) -> int:
    parser = argparse.ArgumentParser(description="Tạo tài khoản quản trị đầu tiên.")
    parser.add_argument("--username", help="Tên đăng nhập")
    parser.add_argument("--full-name", help="Họ và tên")
    parser.add_argument("--email", help="Email (không bắt buộc)")
    parser.add_argument("--force", action="store_true", help="Tạo thêm quản trị viên dù đã có sẵn")
    args = parser.parse_args(argv)

    if app is None:
        from app import create_app
        app = create_app()

    with app.app_context():
        db.create_all()
        seed_all()

        if admin_exists() and not args.force:
            print("Đã có tài khoản quản trị. Dùng --force nếu muốn tạo thêm.", file=sys.stderr)
            return 1

        username = normalize_username(args.username or input("Tên đăng nhập: "))
        full_name = (args.full_name or input("Họ và tên: ")).strip()
        email = args.email or None

        password = os.environ.get("KPI_ADMIN_PASSWORD")
        if password is None:
            password = _ask_password(username, full_name)

        from services.auth import create_user
        try:
            user = create_user(
                username, full_name, password,
                role=Role.ADMIN, email=email, approved=True, must_change_password=False,
            )
        except ValidationError as exc:
            print("Không tạo được tài khoản:", file=sys.stderr)
            for message in exc.errors:
                print(f"  - {message}", file=sys.stderr)
            return 1

        print(f"Đã tạo quản trị viên '{user.username}'. Đăng nhập tại /login.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
