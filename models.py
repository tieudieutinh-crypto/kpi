"""
models.py - Mô hình dữ liệu hệ thống chấm KPI đánh giá cán bộ hằng quý
(theo Hướng dẫn 07-HD/BTCTU ngày 09/6/2026 và Phụ lục 1, 2).

Nhóm bảng:
  Danh mục     : departments, position_groups, axes, kpi_coefficients, common_criteria
  Người dùng   : users
  Kỳ đánh giá  : periods
  Chỉ tiêu     : indicators                  (Mẫu 1 - danh mục nhiệm vụ của cơ quan)
  KPI tập thể  : collective_kpis             (Mẫu 2 - kết quả theo chỉ tiêu)
                 collective_evaluations      (Mẫu 2 - tổng hợp, xếp loại tập thể)
  KPI cá nhân  : personal_evaluations        (Mẫu 5, 6 - hồ sơ đánh giá của 1 cán bộ / 1 quý)
                 personal_kpi_items          (Mẫu 3, 4 - từng sản phẩm/công việc)
                 personal_axis_results       (điểm KPI A,B,C,D theo từng trục)
                 personal_common_scores      (Mẫu 5 - phần A, tiêu chí chung 30 điểm)
"""
from __future__ import annotations

import calendar
import secrets
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import CheckConstraint, UniqueConstraint
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()


# --------------------------------------------------------------------------- #
# Hằng số / lựa chọn
# --------------------------------------------------------------------------- #
class Role:
    """Vai trò theo file «Xây dựng Webapp» và «dieuchinh2». Phân quyền chi tiết xem permissions.py.

    Văn phòng và Ủy ban Kiểm tra là các đơn vị ngang Ban trong danh mục Phòng, Ban; quyền của chức danh
    lấy theo nhóm: lãnh đạo đơn vị (cấp Thường trực) như Phó Trưởng Ban Thường trực, cấp phó như Phó Trưởng Ban.
    """
    ADMIN = "admin"                     # Quản trị hệ thống (không chấm/duyệt KPI)
    PBT = "pho_bi_thu"                  # Phó Bí thư Thường trực Đảng ủy: lãnh đạo cơ quan, duyệt cuối
    PTBTT = "pho_truong_ban_tt"         # Phó Trưởng Ban Thường trực
    PCVPTT = "pho_chanh_vp_tt"          # Phó Chánh Văn phòng Thường trực
    PCNTT = "pho_chu_nhiem_ubkt_tt"     # Phó Chủ nhiệm Ủy ban Kiểm tra Thường trực
    PTB = "pho_truong_ban"              # Phó Trưởng Ban
    PCVP = "pho_chanh_vp"               # Phó Chánh Văn phòng
    PCN = "pho_chu_nhiem_ubkt"          # Phó Chủ nhiệm Ủy ban Kiểm tra
    UVCT = "uy_vien_ct_ubkt"            # Ủy viên Chuyên trách Ủy ban Kiểm tra
    CC = "cong_chuc"                    # Công chức không giữ chức vụ lãnh đạo, quản lý (không có chỉ số D)

    # Tên cũ (trước 25/10/2026) giữ làm bí danh để mã cũ và dữ liệu cũ dùng tiếp
    LEADER, MANAGER, STAFF = PBT, PTBTT, CC
    LEGACY = {"lanh_dao": PBT, "truong_phong": PTBTT, "nhan_vien": CC}

    CHOICES = [
        (ADMIN, "Quản trị hệ thống"),
        (PBT, "Phó Bí thư Thường trực Đảng ủy"),
        (PTBTT, "Phó Trưởng Ban Thường trực"),
        (PCVPTT, "Phó Chánh Văn phòng Thường trực"),
        (PCNTT, "Phó Chủ nhiệm Ủy ban Kiểm tra Thường trực"),
        (PTB, "Phó Trưởng Ban"),
        (PCVP, "Phó Chánh Văn phòng"),
        (PCN, "Phó Chủ nhiệm Ủy ban Kiểm tra"),
        (UVCT, "Ủy viên Chuyên trách Ủy ban Kiểm tra"),
        (CC, "Công chức không giữ chức vụ lãnh đạo, quản lý"),
    ]
    LABELS = dict(CHOICES)
    SHORT = {ADMIN: "Quản trị", PBT: "Phó Bí thư TT", PTBTT: "Phó TB Thường trực", PCVPTT: "Phó CVP Thường trực",
             PCNTT: "Phó CN UBKT Thường trực", PTB: "Phó Trưởng Ban", PCVP: "Phó Chánh VP", PCN: "Phó CN UBKT",
             UVCT: "Ủy viên CT UBKT", CC: "Công chức"}

    # Nhóm quyền
    UNIT_LEADERS = frozenset({PTBTT, PCVPTT, PCNTT})       # lãnh đạo đơn vị: lập KPI tập thể, duyệt cấp đơn vị
    DEPUTIES = frozenset({PTB, PCVP, PCN, UVCT})            # cấp phó: tự lập, tự chấm, có chỉ số D
    UNIT_MEMBERS = UNIT_LEADERS | DEPUTIES | {CC}           # thuộc một Phòng, Ban
    EVALUATED = UNIT_MEMBERS | {PBT}                        # có hồ sơ KPI cá nhân
    WITH_LEADERSHIP = UNIT_LEADERS | DEPUTIES | {PBT}       # có chỉ số D (lãnh đạo, chỉ đạo, điều hành)
    NEEDS_DEPARTMENT = UNIT_MEMBERS
    SELF_REGISTER = UNIT_MEMBERS                            # được chọn khi tự đăng ký (trừ Admin, Phó Bí thư)

    RANK = {CC: 1, UVCT: 2, PCN: 2, PCVP: 2, PTB: 2, PCNTT: 3, PCVPTT: 3, PTBTT: 3, PBT: 4, ADMIN: 5}
    ORDER = [code for code, _ in CHOICES]

    @classmethod
    def choices_for(cls, roles) -> list:
        return [(c, l) for c, l in cls.CHOICES if c in roles]


class Rating:
    """04 mức xếp loại (Bước 3, mục III)."""
    HTXS = "HTXS"   # Hoàn thành xuất sắc nhiệm vụ
    HTT = "HTT"     # Hoàn thành tốt nhiệm vụ
    HT = "HT"       # Hoàn thành nhiệm vụ
    KHT = "KHT"     # Không hoàn thành nhiệm vụ

    CHOICES = [
        (HTXS, "Hoàn thành xuất sắc nhiệm vụ"),
        (HTT, "Hoàn thành tốt nhiệm vụ"),
        (HT, "Hoàn thành nhiệm vụ"),
        (KHT, "Không hoàn thành nhiệm vụ"),
    ]


class ResponseLevel:
    """03 mức đáp ứng đối với nhiệm vụ trọng tâm, then chốt."""
    CHU_DONG = 1    # Chủ động tiếp cận, giải quyết hiệu quả vấn đề, có kết quả cụ thể
    CO_BAN = 2      # Cơ bản đáp ứng yêu cầu nhưng còn hạn chế, cần tiếp tục hoàn thiện
    KHONG_DAT = 3   # Không đáp ứng yêu cầu nhiệm vụ

    CHOICES = [
        (CHU_DONG, "Chủ động tiếp cận, giải quyết hiệu quả vấn đề, có kết quả cụ thể"),
        (CO_BAN, "Cơ bản đáp ứng yêu cầu nhưng còn hạn chế, cần tiếp tục hoàn thiện"),
        (KHONG_DAT, "Không đáp ứng yêu cầu nhiệm vụ"),
    ]


class TaskGroup:
    """Nhóm nhiệm vụ trong mỗi trục (Mẫu 1, Mẫu 3)."""
    THUONG_XUYEN = "thuong_xuyen"
    TRONG_TAM = "trong_tam"

    CHOICES = [
        (THUONG_XUYEN, "Nhóm nhiệm vụ thường xuyên"),
        (TRONG_TAM, "Nhóm nhiệm vụ trọng tâm, then chốt"),
    ]


class EvalStatus:
    """Luồng xử lý 5 bước (mục III)."""
    DRAFT = "draft"              # Bước 1: cá nhân lập danh mục (Mẫu 3)
    SELF_SCORED = "self_scored"  # Bước 2: cá nhân tự chấm, đề xuất xếp loại (Mẫu 4, 5)
    REVIEWED = "reviewed"        # Bước 3: cấp sử dụng cán bộ nhận xét, đề xuất
    APPROVED = "approved"        # Bước 4: cấp có thẩm quyền quyết định
    PUBLISHED = "published"      # Bước 5: thông báo công khai, lưu trữ

    CHOICES = [
        (DRAFT, "Nháp"),
        (SELF_SCORED, "Đã gửi"),
        (REVIEWED, "Đã nhận xét, chờ duyệt"),
        (APPROVED, "Đã duyệt"),
        (PUBLISHED, "Đã công bố"),
    ]
    LABELS = dict(CHOICES)
    ORDER = [DRAFT, SELF_SCORED, REVIEWED, APPROVED, PUBLISHED]


class PlanStatus:
    """Luồng của Bước 1 (Mẫu 3 - danh mục sản phẩm, công việc chuẩn và quy đổi)."""
    DRAFT = "draft"                 # đang lập
    SUBMITTED = "submitted"         # đã trình lãnh đạo Ban
    BAN_APPROVED = "ban_approved"   # lãnh đạo Ban đã duyệt, chờ lãnh đạo cơ quan duyệt cuối
    APPROVED = "approved"           # lãnh đạo cơ quan đã duyệt cuối (hoặc Phó Bí thư tự chốt)

    CHOICES = [
        (DRAFT, "Đang lập"),
        (SUBMITTED, "Đã trình, chờ lãnh đạo Ban duyệt"),
        (BAN_APPROVED, "Lãnh đạo Ban đã duyệt, chờ duyệt cuối"),
        (APPROVED, "Đã duyệt"),
    ]
    LABELS = dict(CHOICES)
    LOCKED = (SUBMITTED, BAN_APPROVED, APPROVED)


class CollectiveStatus:
    """Luồng của KPI tập thể, dùng riêng cho Mẫu 1 (status) và Mẫu 2 (result_status): nháp -> trình -> duyệt."""
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"

    CHOICES = [(DRAFT, "Nháp"), (SUBMITTED, "Đã gửi"), (APPROVED, "Đã duyệt")]
    LABELS = dict(CHOICES)


class KpiCategory:
    QUALITY = "quality"        # KPI chất lượng
    PROGRESS = "progress"      # KPI tiến độ
    LEADERSHIP = "leadership"  # KPI lãnh đạo, chỉ đạo, điều hành

    CHOICES = [
        (QUALITY, "KPI chất lượng"),
        (PROGRESS, "KPI tiến độ"),
        (LEADERSHIP, "KPI lãnh đạo, chỉ đạo, điều hành"),
    ]


# --------------------------------------------------------------------------- #
# Tiện ích
# --------------------------------------------------------------------------- #
def _dec(value) -> Decimal:
    return Decimal(repr(float(value))) if not isinstance(value, Decimal) else value


def r2(value) -> float:
    """Làm tròn 2 chữ số thập phân kiểu 'half up' (0,5 trở lên làm tròn lên)."""
    if value is None:
        return 0.0
    return float(_dec(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def round_half_up(value: float) -> int:
    """Làm tròn số nguyên: từ 0,5 trở lên làm tròn lên 1 (dùng cho tỷ lệ HTXS)."""
    return int(_dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


class TimestampMixin:
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


# --------------------------------------------------------------------------- #
# Danh mục: phòng ban, nhóm đối tượng, trục kết quả, tiêu chí chung, hệ số
# --------------------------------------------------------------------------- #
class Department(TimestampMixin, db.Model):
    """Phòng, Ban của cơ quan (chỉ cấp thành phố; cột level, parent_id giữ lại cho dữ liệu cũ)."""
    __tablename__ = "departments"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(255), nullable=False)
    level = db.Column(db.String(20), nullable=False, default="thanh_pho")  # thanh_pho | xa_phuong
    parent_id = db.Column(db.Integer, db.ForeignKey("departments.id"))
    active = db.Column(db.Boolean, default=True, nullable=False)

    parent = db.relationship("Department", remote_side=[id], backref="children")
    users = db.relationship("User", back_populates="department")

    def __repr__(self):
        return f"<Department {self.code}>"


class PositionGroup(db.Model):
    """Nhóm đối tượng có vị trí, vai trò tương đồng - cột của Mẫu 7 / Mẫu 8.
    Dùng để áp tỷ lệ HTXS (<= 20% số HTT, mỗi nhóm tối thiểu 5 cán bộ)."""
    __tablename__ = "position_groups"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(30), unique=True, nullable=False)
    name = db.Column(db.String(400), nullable=False)
    form = db.Column(db.String(2), nullable=False)       # "M7" (cấp xã) | "M8" (cấp thành phố)
    sort = db.Column(db.Integer, default=0, nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)

    users = db.relationship("User", back_populates="position_group")


class Axis(db.Model):
    """06 trục kết quả trọng tâm (mục I)."""
    __tablename__ = "axes"

    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.Integer, unique=True, nullable=False)   # 1..6
    name = db.Column(db.String(500), nullable=False)

    @property
    def label(self) -> str:
        return f"Trục {self.number}"


class CommonCriterion(db.Model):
    """Tiêu chí chung (Quy định 89-QĐ/TU) - Mẫu 5 phần A, tổng 30 điểm."""
    __tablename__ = "common_criteria"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(10), unique=True, nullable=False)  # 1.1 ... 3.4
    group_no = db.Column(db.Integer, nullable=False)              # 1, 2, 3
    group_title = db.Column(db.String(300), nullable=False)
    title = db.Column(db.Text, nullable=False)
    max_score = db.Column(db.Float, nullable=False)
    sort = db.Column(db.Integer, default=0, nullable=False)


class KpiCoefficient(TimestampMixin, db.Model):
    """Bảng hệ số KPI (Phụ lục 2) - cho phép điều chỉnh hệ số theo hướng dẫn mới.

    category = quality | progress | leadership
    value       : hệ số KPI (1; 0,9; 0,8; 0,7)
    bonus_value : hệ số vượt (0,1) - chỉ ghi nhận để xét mức nổi trội, KHÔNG cộng vào KPI
    """
    __tablename__ = "kpi_coefficients"
    __table_args__ = (UniqueConstraint("category", "code", name="uq_coef_category_code"),)

    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(20), nullable=False)
    code = db.Column(db.Integer, nullable=False)       # mức (1) .. (4)
    label = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text)
    value = db.Column(db.Float, nullable=False)
    bonus_value = db.Column(db.Float)                  # None với nhóm leadership
    active = db.Column(db.Boolean, default=True, nullable=False)

    @classmethod
    def as_lookup(cls) -> dict:
        """{category: {code: (value, bonus_value)}} để tính điểm nhanh."""
        out: dict = {}
        for c in cls.query.filter_by(active=True).all():
            out.setdefault(c.category, {})[c.code] = (c.value, c.bonus_value or 0.0)
        return out


# --------------------------------------------------------------------------- #
# Người dùng
# --------------------------------------------------------------------------- #
class User(UserMixin, TimestampMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(150), nullable=False)
    birth_date = db.Column(db.Date)
    email = db.Column(db.String(150))
    phone = db.Column(db.String(30))

    # Thông tin cho Mẫu 5
    party_position = db.Column(db.String(200))   # Chức vụ Đảng
    gov_position = db.Column(db.String(200))     # Chức vụ chính quyền
    org_position = db.Column(db.String(200))     # Chức vụ đoàn thể

    role = db.Column(db.String(30), nullable=False, default=Role.STAFF)
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id"))
    position_group_id = db.Column(db.Integer, db.ForeignKey("position_groups.id"))
    is_head = db.Column(db.Boolean, default=False, nullable=False)  # người đứng đầu (không tính vào tỷ lệ HTXS)

    # Trạng thái tài khoản
    approved = db.Column(db.Boolean, default=False, nullable=False)  # quản trị viên đã duyệt (đăng ký mới = False)
    active = db.Column(db.Boolean, default=True, nullable=False)     # False = bị khóa

    # Bảo mật phiên đăng nhập
    session_token = db.Column(
        db.String(64), nullable=False, default=lambda: secrets.token_hex(32)
    )  # đổi giá trị -> mọi phiên đăng nhập cũ hết hiệu lực
    must_change_password = db.Column(db.Boolean, default=False, nullable=False)
    failed_attempts = db.Column(db.Integer, default=0, nullable=False)
    locked_until = db.Column(db.DateTime)            # tạm khóa do nhập sai mật khẩu nhiều lần
    last_login_at = db.Column(db.DateTime)
    password_changed_at = db.Column(db.DateTime)

    department = db.relationship("Department", back_populates="users")
    position_group = db.relationship("PositionGroup", back_populates="users")
    evaluations = db.relationship(
        "PersonalEvaluation", back_populates="user",
        foreign_keys="PersonalEvaluation.user_id", cascade="all, delete-orphan",
    )

    # --- Flask-Login ---
    def get_id(self) -> str:
        """Định danh lưu trong cookie phiên: '<id>:<session_token>'.
        Khi session_token đổi (đổi mật khẩu, khóa, đổi vai trò, đăng xuất mọi thiết bị),
        các phiên cũ không còn khớp và bị từ chối."""
        return f"{self.id}:{self.session_token}"

    @property
    def is_active(self) -> bool:  # type: ignore[override]
        return bool(self.active and self.approved)

    def rotate_token(self) -> None:
        self.session_token = secrets.token_hex(32)

    # --- Mật khẩu (băm bằng werkzeug: scrypt + salt ngẫu nhiên, không lưu mật khẩu gốc) ---
    def set_password(self, raw: str) -> None:
        self.password_hash = generate_password_hash(raw)
        self.password_changed_at = datetime.utcnow()

    def check_password(self, raw: str) -> bool:
        return check_password_hash(self.password_hash, raw)

    # --- Vai trò ---
    @property
    def is_admin(self) -> bool:
        return self.role == Role.ADMIN

    @property
    def role_label(self) -> str:
        return Role.LABELS.get(self.role, self.role)

    @property
    def role_short(self) -> str:
        return Role.SHORT.get(self.role, self.role)

    @property
    def has_leadership_kpi(self) -> bool:
        """Có chỉ số D (lãnh đạo, chỉ đạo, điều hành) trong Mẫu 4 hay không."""
        return self.role in Role.WITH_LEADERSHIP

    def has_role(self, *roles: str) -> bool:
        return self.role in roles

    @property
    def is_temporarily_locked(self) -> bool:
        return bool(self.locked_until and self.locked_until > datetime.utcnow())

    def __repr__(self):
        return f"<User {self.username}>"


# --------------------------------------------------------------------------- #
# Kỳ đánh giá (quý)
# --------------------------------------------------------------------------- #
class Period(TimestampMixin, db.Model):
    """Kỳ đánh giá hằng quý và các mốc thời hạn nộp biểu mẫu (mục V.2)."""
    __tablename__ = "periods"
    __table_args__ = (
        UniqueConstraint("year", "quarter", name="uq_period_year_quarter"),
        CheckConstraint("quarter BETWEEN 1 AND 4", name="ck_period_quarter"),
    )

    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, nullable=False)
    quarter = db.Column(db.Integer, nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(10), nullable=False, default="open")  # open | closed

    # Mẫu 1, Mẫu 3: trước ngày 15 tháng đầu quý
    deadline_m1_m3 = db.Column(db.Date)
    # Mẫu 2: trước ngày 18 tháng cuối quý
    deadline_m2 = db.Column(db.Date)
    # Mẫu 4,5,6,7,8: trước ngày 22 tháng cuối quý
    deadline_m4_m8 = db.Column(db.Date)

    @property
    def name(self) -> str:
        return f"Quý {['I', 'II', 'III', 'IV'][self.quarter - 1]}/{self.year}"

    @classmethod
    def build(cls, year: int, quarter: int) -> "Period":
        """Tạo kỳ đánh giá kèm mốc thời hạn mặc định theo Hướng dẫn 07."""
        first_month = (quarter - 1) * 3 + 1
        last_month = first_month + 2
        return cls(
            year=year,
            quarter=quarter,
            start_date=date(year, first_month, 1),
            end_date=date(year, last_month, calendar.monthrange(year, last_month)[1]),
            deadline_m1_m3=date(year, first_month, 15),
            deadline_m2=date(year, last_month, 18),
            deadline_m4_m8=date(year, last_month, 22),
        )

    def __repr__(self):
        return f"<Period {self.name}>"


# --------------------------------------------------------------------------- #
# Chỉ tiêu (Mẫu 1) và KPI tập thể (Mẫu 2)
# --------------------------------------------------------------------------- #
class Indicator(TimestampMixin, db.Model):
    """Chỉ tiêu / nhiệm vụ của cơ quan, đơn vị trong quý - 1 dòng của Mẫu 1."""
    __tablename__ = "indicators"

    id = db.Column(db.Integer, primary_key=True)
    period_id = db.Column(db.Integer, db.ForeignKey("periods.id"), nullable=False, index=True)
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id"), nullable=False, index=True)
    axis_id = db.Column(db.Integer, db.ForeignKey("axes.id"), nullable=False)
    task_group = db.Column(db.String(20), nullable=False, default=TaskGroup.THUONG_XUYEN)

    content = db.Column(db.Text, nullable=False)          # (2) Nội dung/Nhiệm vụ/Chỉ tiêu
    product = db.Column(db.String(300))                   # (3) Sản phẩm
    unit = db.Column(db.String(50))                       # Đơn vị tính (Mẫu 2)
    annual_target = db.Column(db.Float)                   # (4) Chỉ tiêu năm
    quarter_target = db.Column(db.Float)                  # (5) Chỉ tiêu quý
    difficulty = db.Column(db.Text)                       # (6) Độ khó, mới, phức tạp; phạm vi tác động
    lead_agency = db.Column(db.String(255))               # (7) Cơ quan chủ trì
    support_agency = db.Column(db.String(255))            # (8) Cơ quan phối hợp
    leader_id = db.Column(db.Integer, db.ForeignKey("users.id"))  # (9) Lãnh đạo trực tiếp phụ trách
    deadline_text = db.Column(db.String(200))             # (10) Thời gian hoàn thành (diễn giải)
    deadline_date = db.Column(db.Date)
    note = db.Column(db.Text)
    sort = db.Column(db.Integer, default=0, nullable=False)

    period = db.relationship("Period")
    department = db.relationship("Department")
    axis = db.relationship("Axis")
    leader = db.relationship("User", foreign_keys=[leader_id])
    collective_kpi = db.relationship(
        "CollectiveKPI", back_populates="indicator", uselist=False, cascade="all, delete-orphan"
    )


class CollectiveKPI(TimestampMixin, db.Model):
    """Kết quả thực hiện của tập thể theo từng chỉ tiêu - 1 dòng của Mẫu 2, phần I."""
    __tablename__ = "collective_kpis"

    id = db.Column(db.Integer, primary_key=True)
    indicator_id = db.Column(
        db.Integer, db.ForeignKey("indicators.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    result = db.Column(db.Float)                          # (7) Kết quả thực hiện quý
    actual_date = db.Column(db.Date)                      # (11) Thời gian hoàn thành thực tế
    note = db.Column(db.Text)

    indicator = db.relationship("Indicator", back_populates="collective_kpi")

    @property
    def pct_quarter(self):
        """(8) = (7)/(6)*100"""
        t = self.indicator.quarter_target
        return r2(self.result / t * 100) if t and self.result is not None else None

    @property
    def pct_year(self):
        """(9) = (7)/(5)*100"""
        t = self.indicator.annual_target
        return r2(self.result / t * 100) if t and self.result is not None else None

    @property
    def on_time(self):
        d = self.indicator.deadline_date
        if d and self.actual_date:
            return self.actual_date <= d
        return None


class CollectiveEvaluation(TimestampMixin, db.Model):
    """Tổng hợp kết quả của tập thể / cơ quan, đơn vị trong quý (Mẫu 2, phần II, III)."""
    __tablename__ = "collective_evaluations"
    __table_args__ = (UniqueConstraint("period_id", "department_id", name="uq_coll_eval"),)

    id = db.Column(db.Integer, primary_key=True)
    period_id = db.Column(db.Integer, db.ForeignKey("periods.id"), nullable=False)
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id"), nullable=False)
    other_key_tasks = db.Column(db.Text)       # II. Một số nhiệm vụ trọng tâm khác
    innovative_models = db.Column(db.Text)     # III. Mô hình hay, cách làm sáng tạo
    rating = db.Column(db.String(10))          # xếp loại tập thể (Rating.*), quyết định khi duyệt Mẫu 2
    status = db.Column(db.String(12), default="draft", nullable=False)  # Mẫu 1: draft | submitted | approved
    # Mẫu 2: chỉ mở khi Mẫu 1 đã duyệt; luồng riêng
    result_status = db.Column(db.String(12), default="draft", nullable=False)
    result_submitted_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    result_submitted_at = db.Column(db.DateTime)
    result_return_note = db.Column(db.Text)
    result_confirmed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    result_confirmed_at = db.Column(db.DateTime)
    submitted_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    submitted_at = db.Column(db.DateTime)
    returned_at = db.Column(db.DateTime)
    return_note = db.Column(db.Text)
    confirmed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))   # người phê duyệt
    confirmed_at = db.Column(db.DateTime)

    period = db.relationship("Period")
    department = db.relationship("Department")
    confirmed_by = db.relationship("User", foreign_keys=[confirmed_by_id])
    submitted_by = db.relationship("User", foreign_keys=[submitted_by_id])
    result_confirmed_by = db.relationship("User", foreign_keys=[result_confirmed_by_id])

    @property
    def result_open(self) -> bool:
        """Mẫu 2 chỉ mở khi Mẫu 1 đã được duyệt."""
        return self.status == "approved"


# --------------------------------------------------------------------------- #
# KPI cá nhân
# --------------------------------------------------------------------------- #
class PersonalEvaluation(TimestampMixin, db.Model):
    """Hồ sơ đánh giá của 1 cán bộ trong 1 quý (Mẫu 5 + tổng hợp Mẫu 6)."""
    __tablename__ = "personal_evaluations"
    __table_args__ = (UniqueConstraint("user_id", "period_id", name="uq_personal_eval"),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    period_id = db.Column(db.Integer, db.ForeignKey("periods.id"), nullable=False, index=True)
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id"))  # đơn vị tại thời điểm đánh giá
    position_group_id = db.Column(db.Integer, db.ForeignKey("position_groups.id"))  # nhóm đối tượng tại thời điểm đánh giá
    position_title = db.Column(db.String(300))     # chức vụ tại thời điểm đánh giá

    status = db.Column(db.String(15), nullable=False, default=EvalStatus.DRAFT, index=True)

    # Bước 1 - Mẫu 3: trạng thái riêng, bản chụp danh mục khi trình (Mẫu 3 không đổi khi sửa Mẫu 4)
    plan_status = db.Column(db.String(15), nullable=False, default="draft")
    plan_snapshot = db.Column(db.Text)              # JSON: danh sách nhiệm vụ của Mẫu 3 tại lúc trình
    plan_submitted_at = db.Column(db.DateTime)
    plan_ban_approved_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    plan_ban_approved_at = db.Column(db.DateTime)
    plan_approved_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    plan_approved_at = db.Column(db.DateTime)
    plan_return_note = db.Column(db.Text)

    # Điểm (thang 100): A = tiêu chí chung (tối đa 30) + B = kết quả nhiệm vụ (tối đa 70)
    common_score = db.Column(db.Float, default=0.0, nullable=False)
    result_score = db.Column(db.Float, default=0.0, nullable=False)
    total_score = db.Column(db.Float, default=0.0, nullable=False)

    # Xếp loại qua các bước
    self_rating = db.Column(db.String(10))         # Bước 2: cá nhân đề xuất
    proposed_rating = db.Column(db.String(10))     # Bước 3: cấp sử dụng cán bộ đề xuất
    final_rating = db.Column(db.String(10))        # Bước 4: cấp có thẩm quyền quyết định
    response_level = db.Column(db.Integer)         # mức đáp ứng nhiệm vụ then chốt (1-3)

    self_comment = db.Column(db.Text)
    reviewer_comment = db.Column(db.Text)          # Mẫu 5, mục III - nhận xét của cấp có thẩm quyền
    reviewer_score = db.Column(db.Float)           # Mẫu 5, mục III - điểm do cấp có thẩm quyền chấm
    rating_reason = db.Column(db.Text)             # Mẫu 6 cột (6) - căn cứ khi đề xuất HTXS/KHT
    personnel_proposal = db.Column(db.Text)        # Mẫu 6 cột (7) - đề xuất công tác cán bộ

    # Các trường hợp đặc biệt (mục IV)
    force_majeure = db.Column(db.Boolean, default=False, nullable=False)
    force_majeure_note = db.Column(db.Text)        # lý do khách quan, bất khả kháng được xác nhận
    deferred = db.Column(db.Boolean, default=False, nullable=False)  # chuyển sang quý sau (IV.1.2)
    deferred_reason = db.Column(db.String(300))
    months_in_role = db.Column(db.Float)           # số tháng giữ chức vụ trong quý (IV.1.1: 02 tháng)

    submitted_at = db.Column(db.DateTime)
    reviewed_at = db.Column(db.DateTime)
    returned_at = db.Column(db.DateTime)
    return_note = db.Column(db.Text)               # lý do trả lại để chỉnh sửa
    # Có tính chỉ số D (lãnh đạo, chỉ đạo, điều hành) hay không. Mặc định True theo đúng công thức
    # KPI = (A+B+C+D)/4; bỏ chọn cho cán bộ không có nhiệm vụ lãnh đạo -> KPI = (A+B+C)/3.
    use_leadership = db.Column(db.Boolean, default=True, nullable=False)
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    approved_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    approved_at = db.Column(db.DateTime)
    published_at = db.Column(db.DateTime)

    user = db.relationship("User", back_populates="evaluations", foreign_keys=[user_id])
    period = db.relationship("Period")
    department = db.relationship("Department")
    position_group = db.relationship("PositionGroup")
    reviewed_by = db.relationship("User", foreign_keys=[reviewed_by_id])
    approved_by = db.relationship("User", foreign_keys=[approved_by_id])
    plan_ban_approved_by = db.relationship("User", foreign_keys=[plan_ban_approved_by_id])
    plan_approved_by = db.relationship("User", foreign_keys=[plan_approved_by_id])

    items = db.relationship(
        "PersonalKPIItem", back_populates="evaluation",
        order_by="PersonalKPIItem.sort, PersonalKPIItem.id", cascade="all, delete-orphan",
    )
    axis_results = db.relationship(
        "PersonalAxisResult", back_populates="evaluation",
        order_by="PersonalAxisResult.axis_id", cascade="all, delete-orphan",
    )
    common_scores = db.relationship(
        "PersonalCommonScore", back_populates="evaluation", cascade="all, delete-orphan"
    )

    COMMON_MAX = 30.0
    RESULT_MAX = 70.0

    def recompute(self, coef: dict | None = None) -> "PersonalEvaluation":
        """Tính lại toàn bộ: từng dòng -> từng trục -> tổng điểm (Phụ lục 2)."""
        coef = coef or KpiCoefficient.as_lookup()
        for it in self.items:
            it.compute(coef)
        by_axis: dict[int, list] = {}
        for it in self.items:
            by_axis.setdefault(it.axis_id, []).append(it)
        for ar in self.axis_results:
            ar.recompute(by_axis.get(ar.axis_id, []), use_leadership=self.use_leadership)
        self.common_score = r2(sum(cs.score or 0 for cs in self.common_scores))
        self.result_score = r2(sum(ar.score for ar in self.axis_results))
        self.total_score = r2(self.common_score + self.result_score)
        return self

    def qty_completion_pct(self):
        """Tỷ lệ hoàn thành số lượng bình quân gia quyền theo hệ số quy đổi (toàn hồ sơ), None nếu chưa có dòng nào."""
        total = sum(it.conversion_coef or 0.0 for it in self.items)
        if total <= 0:
            return None
        return r2(sum(it.qty_conv or 0.0 for it in self.items) / total * 100)

    def __repr__(self):
        return f"<PersonalEvaluation user={self.user_id} period={self.period_id}>"


class PersonalKPIItem(TimestampMixin, db.Model):
    """Một sản phẩm/công việc của cá nhân: gộp Mẫu 3 (kế hoạch) và Mẫu 4 (thực tế, KPI)."""
    __tablename__ = "personal_kpi_items"

    id = db.Column(db.Integer, primary_key=True)
    evaluation_id = db.Column(
        db.Integer, db.ForeignKey("personal_evaluations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    axis_id = db.Column(db.Integer, db.ForeignKey("axes.id"), nullable=False)
    task_group = db.Column(db.String(20), nullable=False, default=TaskGroup.THUONG_XUYEN)
    indicator_id = db.Column(db.Integer, db.ForeignKey("indicators.id"))  # liên kết chỉ tiêu của cơ quan (nếu có)
    sort = db.Column(db.Integer, default=0, nullable=False)

    # --- Mẫu 3: kế hoạch ---
    task = db.Column(db.Text, nullable=False)              # nhiệm vụ
    product = db.Column(db.String(300))                    # sản phẩm
    difficulty = db.Column(db.Text)                        # độ khó, mới, phức tạp; phạm vi tác động
    planned_qty = db.Column(db.Float, default=1.0)         # số lượng kế hoạch
    deadline_text = db.Column(db.String(200))              # tiến độ (diễn giải)
    deadline_date = db.Column(db.Date)
    task_score = db.Column(db.Float, default=100.0)        # điểm chấm công việc cụ thể (chuẩn = 100, tối đa 200)
    conversion_coef = db.Column(db.Float, default=1.0)     # hệ số quy đổi = task_score / 100
    is_standard = db.Column(db.Boolean, default=False, nullable=False)  # công việc chuẩn
    from_plan = db.Column(db.Boolean, default=False, nullable=False)    # nhiệm vụ đã có trong Mẫu 3 được duyệt
    note = db.Column(db.Text)

    # --- Mẫu 4: thực tế triển khai ---
    actual_qty = db.Column(db.Float)                       # (7) số lượng thực tế hoàn thành
    actual_date = db.Column(db.Date)                       # (12) thời điểm thực tế hoàn thành
    quality_code = db.Column(db.Integer)                   # mức chất lượng 1..4 -> kpi_coefficients
    progress_code = db.Column(db.Integer)                  # mức tiến độ 1..4
    leadership_code = db.Column(db.Integer)                # mức lãnh đạo, chỉ đạo, điều hành 1..4
    quality_exceeded = db.Column(db.Boolean, default=False, nullable=False)   # nổi trội, được công nhận
    progress_exceeded = db.Column(db.Boolean, default=False, nullable=False)  # vượt tiến độ, được công nhận

    result_note = db.Column(db.Text)                       # kết quả sản phẩm thực tế (diễn giải, Mẫu 5 phần B)

    # --- Kết quả tính (lưu lại để không đổi khi hệ số thay đổi sau này) ---
    kpi_qty = db.Column(db.Float, default=0.0)             # (8) hệ số KPI số lượng, tối đa 1
    qty_conv = db.Column(db.Float, default=0.0)            # (9) = (8) x (6)
    quality_value = db.Column(db.Float, default=0.0)       # (10)
    quality_conv = db.Column(db.Float, default=0.0)        # (11)
    progress_value = db.Column(db.Float, default=0.0)      # (13)
    progress_conv = db.Column(db.Float, default=0.0)       # (14)
    leadership_value = db.Column(db.Float, default=0.0)    # (15)
    leadership_conv = db.Column(db.Float, default=0.0)     # (16)
    over_qty = db.Column(db.Float, default=0.0)            # (17) hệ số vượt số lượng
    over_quality = db.Column(db.Float, default=0.0)        # (18)
    over_progress = db.Column(db.Float, default=0.0)       # (19)

    evaluation = db.relationship("PersonalEvaluation", back_populates="items")
    axis = db.relationship("Axis")
    indicator = db.relationship("Indicator")

    def set_score(self, task_score: float) -> None:
        """Hệ số quy đổi = điểm công việc cụ thể / điểm công việc chuẩn (100)."""
        self.task_score = task_score
        self.conversion_coef = r2(task_score / 100.0)

    def _ratio(self) -> float:
        planned = self.planned_qty or 0.0
        actual = self.actual_qty or 0.0
        if planned <= 0:
            return 1.0 if actual > 0 else 0.0
        return r2(actual / planned)

    def compute(self, coef: dict) -> "PersonalKPIItem":
        conv = self.conversion_coef if self.conversion_coef is not None else 1.0

        ratio = self._ratio()
        self.kpi_qty = min(ratio, 1.0)
        self.over_qty = r2(max(ratio - 1.0, 0.0))
        self.qty_conv = r2(self.kpi_qty * conv)

        q_val, q_bonus = coef.get(KpiCategory.QUALITY, {}).get(self.quality_code, (0.0, 0.0))
        p_val, p_bonus = coef.get(KpiCategory.PROGRESS, {}).get(self.progress_code, (0.0, 0.0))
        l_val, _ = coef.get(KpiCategory.LEADERSHIP, {}).get(self.leadership_code, (0.0, 0.0))

        self.quality_value, self.quality_conv = q_val, r2(q_val * conv)
        self.progress_value, self.progress_conv = p_val, r2(p_val * conv)
        self.leadership_value, self.leadership_conv = l_val, r2(l_val * conv)
        self.over_quality = q_bonus if self.quality_exceeded else 0.0
        self.over_progress = p_bonus if self.progress_exceeded else 0.0
        return self


class PersonalAxisResult(db.Model):
    """Điểm KPI và điểm kết quả của cá nhân theo từng trục.

    A = Σ(9)/Σ(6) x 100 ; B = Σ(11)/Σ(6) x 100 ; C = Σ(14)/Σ(6) x 100 ; D = Σ(16)/Σ(6) x 100
    KPI = (A+B+C+D)/4 ; Điểm trục = KPI x max_score / 100
    Tổng max_score các trục = 70 (cá nhân tự phân bổ tỷ trọng; trục chính cao hơn trục phụ).
    """
    __tablename__ = "personal_axis_results"
    __table_args__ = (UniqueConstraint("evaluation_id", "axis_id", name="uq_axis_result"),)

    id = db.Column(db.Integer, primary_key=True)
    evaluation_id = db.Column(
        db.Integer, db.ForeignKey("personal_evaluations.id", ondelete="CASCADE"), nullable=False
    )
    axis_id = db.Column(db.Integer, db.ForeignKey("axes.id"), nullable=False)
    is_main = db.Column(db.Boolean, default=False, nullable=False)   # trục chính/chủ yếu hay phụ/phối hợp
    max_score = db.Column(db.Float, default=0.0, nullable=False)     # điểm tối đa của trục
    goals = db.Column(db.Text)                                       # Mẫu 5 B (3): mục tiêu, nhiệm vụ đề ra
    results = db.Column(db.Text)                                     # Mẫu 5 B (4): kết quả sản phẩm thực tế
    note = db.Column(db.Text)                                        # Mẫu 5 B (8): ghi chú

    total_conv = db.Column(db.Float, default=0.0)   # Σ hệ số quy đổi (cột 6)
    kpi_a = db.Column(db.Float, default=0.0)        # % số lượng
    kpi_b = db.Column(db.Float, default=0.0)        # % chất lượng
    kpi_c = db.Column(db.Float, default=0.0)        # % tiến độ
    kpi_d = db.Column(db.Float, default=0.0)        # % lãnh đạo, chỉ đạo, điều hành
    kpi_total = db.Column(db.Float, default=0.0)    # %
    score = db.Column(db.Float, default=0.0)        # điểm đạt của trục
    over_qty = db.Column(db.Float, default=0.0)    # Σ hệ số vượt - cơ sở xét mức nổi trội
    over_quality = db.Column(db.Float, default=0.0)
    over_progress = db.Column(db.Float, default=0.0)

    evaluation = db.relationship("PersonalEvaluation", back_populates="axis_results")
    axis = db.relationship("Axis")

    def recompute(self, items: list, use_leadership: bool = True) -> "PersonalAxisResult":
        total = sum(it.conversion_coef or 0.0 for it in items)
        self.total_conv = r2(total)

        def pct(attr: str) -> Decimal:
            if total <= 0:
                return Decimal("0.00")
            s = sum(_dec(getattr(it, attr) or 0.0) for it in items)
            return (s / _dec(total) * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        a, b, c, d = pct("qty_conv"), pct("quality_conv"), pct("progress_conv"), pct("leadership_conv")
        self.kpi_a, self.kpi_b, self.kpi_c, self.kpi_d = float(a), float(b), float(c), float(d)
        parts = [a, b, c, d] if use_leadership else [a, b, c]
        kpi = (sum(parts) / len(parts)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if not use_leadership:
            self.kpi_d = 0.0
        self.kpi_total = float(kpi)
        self.score = r2(kpi * _dec(self.max_score or 0.0) / 100)
        self.over_qty = r2(sum(it.over_qty or 0.0 for it in items))
        self.over_quality = r2(sum(it.over_quality or 0.0 for it in items))
        self.over_progress = r2(sum(it.over_progress or 0.0 for it in items))
        return self


class PersonalCommonScore(db.Model):
    """Điểm tiêu chí chung của cá nhân (Mẫu 5, phần A). Đảm bảo = điểm tối đa, không đảm bảo = 0."""
    __tablename__ = "personal_common_scores"
    __table_args__ = (UniqueConstraint("evaluation_id", "criterion_id", name="uq_common_score"),)

    id = db.Column(db.Integer, primary_key=True)
    evaluation_id = db.Column(
        db.Integer, db.ForeignKey("personal_evaluations.id", ondelete="CASCADE"), nullable=False
    )
    criterion_id = db.Column(db.Integer, db.ForeignKey("common_criteria.id"), nullable=False)
    satisfied = db.Column(db.Boolean)        # True = Đảm bảo, False = Không đảm bảo
    score = db.Column(db.Float, default=0.0)
    note = db.Column(db.Text)

    evaluation = db.relationship("PersonalEvaluation", back_populates="common_scores")
    criterion = db.relationship("CommonCriterion")

    def apply(self, satisfied) -> None:
        """satisfied: True = đảm bảo (chấm tối đa), False = không đảm bảo (0 điểm), None = chưa chấm."""
        self.satisfied = satisfied
        self.score = self.criterion.max_score if satisfied else 0.0


class WorkflowLog(db.Model):
    """Nhật ký thao tác trên luồng nháp - gửi - duyệt (dùng chung cho KPI cá nhân và KPI tập thể)."""
    __tablename__ = "workflow_logs"
    __table_args__ = (db.Index("ix_workflow_entity", "entity_type", "entity_id"),)

    id = db.Column(db.Integer, primary_key=True)
    entity_type = db.Column(db.String(20), nullable=False)    # "personal" | "collective"
    entity_id = db.Column(db.Integer, nullable=False)
    action = db.Column(db.String(20), nullable=False)         # submit | withdraw | review | approve | return
    from_status = db.Column(db.String(15))
    to_status = db.Column(db.String(15))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    note = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship("User")

    ACTION_LABELS = {
        "submit": "Gửi duyệt", "withdraw": "Thu hồi về nháp", "review": "Nhận xét, chuyển duyệt",
        "approve": "Phê duyệt", "return": "Trả lại để chỉnh sửa", "reopen": "Mở lại để điều chỉnh",
        "plan_submit": "Trình Mẫu 3", "plan_ban_approve": "Lãnh đạo Ban duyệt Mẫu 3",
        "plan_approve": "Duyệt cuối Mẫu 3", "plan_return": "Trả lại Mẫu 3", "plan_reopen": "Mở lại Mẫu 3",
        "plan_lock": "Chốt Mẫu 3",
        "m2_submit": "Trình Mẫu 2", "m2_withdraw": "Thu hồi Mẫu 2", "m2_approve": "Duyệt Mẫu 2",
        "m2_return": "Trả lại Mẫu 2", "m2_reopen": "Mở lại Mẫu 2", "m2_lock": "Khóa Mẫu 2 (Mẫu 1 mở lại)",
    }

    @property
    def action_label(self) -> str:
        return self.ACTION_LABELS.get(self.action, self.action)
