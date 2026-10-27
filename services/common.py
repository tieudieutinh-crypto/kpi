"""services/common.py - Đọc và kiểm tra dữ liệu gửi lên (form / JSON)."""
from __future__ import annotations

import math
from datetime import datetime


class WorkflowError(Exception):
    """Thao tác không hợp lệ với trạng thái hiện tại, hoặc hồ sơ chưa đủ điều kiện."""

    def __init__(self, messages):
        self.messages = [messages] if isinstance(messages, str) else list(messages)
        super().__init__("; ".join(self.messages))


def parse_float(value, label, errors, *, minimum=None, maximum=None, default=None):
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    if isinstance(value, bool):
        errors.append(f"{label}: giá trị không phải là số.")
        return default
    try:
        number = float(value.strip().replace(",", ".")) if isinstance(value, str) else float(value)
    except (TypeError, ValueError):
        errors.append(f"{label}: giá trị không phải là số.")
        return default
    if math.isnan(number) or math.isinf(number):
        errors.append(f"{label}: giá trị không hợp lệ.")
        return default
    if minimum is not None and number < minimum:
        errors.append(f"{label}: không được nhỏ hơn {minimum:g}.")
        return default
    if maximum is not None and number > maximum:
        errors.append(f"{label}: không được lớn hơn {maximum:g}.")
        return default
    return number


def parse_date(value, label, errors):
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        return datetime.strptime(str(value).strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        errors.append(f"{label}: ngày không hợp lệ.")
        return None


def parse_choice(value, label, errors, allowed, *, required=False):
    """Trả về giá trị nếu nằm trong `allowed`; rỗng -> None (báo lỗi nếu required)."""
    if value is None or value == "":
        if required:
            errors.append(f"{label}: vui lòng chọn.")
        return None
    try:
        value = type(next(iter(allowed)))(value)
    except (TypeError, ValueError, StopIteration):
        pass
    if value not in allowed:
        errors.append(f"{label}: lựa chọn không hợp lệ.")
        return None
    return value


def parse_bool(value, default=False) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "on", "yes")
    return bool(value)


def clean_text(value, label, errors, *, max_len=2000, required=False):
    text = ("" if value is None else str(value)).strip()
    if required and not text:
        errors.append(f"{label}: không được để trống.")
    if len(text) > max_len:
        errors.append(f"{label}: tối đa {max_len} ký tự.")
        text = text[:max_len]
    return text or None


def iso(d):
    return d.isoformat() if d else ""
