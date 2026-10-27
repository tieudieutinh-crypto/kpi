"""
migrate.py - Nâng cấp CSDL SQLite tại chỗ, KHÔNG mất dữ liệu.

Mỗi lần models.py thêm bảng hoặc cột, hàm upgrade_schema() sẽ:
  1. tạo các bảng còn thiếu (db.create_all);
  2. thêm các cột còn thiếu vào bảng đã có (ALTER TABLE ... ADD COLUMN).
Không xóa hay đổi kiểu cột đã có. Ứng dụng tự gọi hàm này khi khởi động; cũng có thể chạy tay:
    flask --app app upgrade-db
"""
from sqlalchemy import inspect, text

from models import Role, db


def _literal(value) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"


def upgrade_schema() -> list[str]:
    """Trả về danh sách các thay đổi đã áp dụng (rỗng nếu CSDL đã mới nhất)."""
    db.create_all()
    engine = db.engine
    inspector = inspect(engine)
    changes: list[str] = []

    # Đọc cấu trúc hiện tại TRƯỚC khi mở giao dịch ghi (inspector tự mở/đóng kết nối riêng).
    missing = []
    for table in db.metadata.sorted_tables:
        existing = {c["name"] for c in inspector.get_columns(table.name)}
        missing.extend((table, col) for col in table.columns if col.name not in existing)

    with engine.begin() as conn:
        for table, col in missing:
            ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {col.type.compile(engine.dialect)}'
            default = col.default
            backfill = None
            if not col.nullable and default is not None:
                if getattr(default, "is_scalar", False):
                    ddl += f" NOT NULL DEFAULT {_literal(default.arg)}"
                elif getattr(default, "is_callable", False):
                    backfill = default.arg      # thêm cột cho phép NULL, rồi điền từng dòng
            conn.execute(text(ddl))
            if backfill is not None:
                rows = conn.execute(text(f'SELECT rowid FROM "{table.name}"')).fetchall()
                for (rowid,) in rows:
                    conn.execute(
                        text(f'UPDATE "{table.name}" SET "{col.name}" = :v WHERE rowid = :r'),
                        {"v": backfill(None), "r": rowid},
                    )
            changes.append(f"{table.name}.{col.name}")

        # Hồ sơ cũ (trước khi Mẫu 3 có luồng duyệt riêng) đã trình Mẫu 5: coi Mẫu 3 là đã duyệt
        if "personal_evaluations.plan_status" in changes:
            conn.execute(text("UPDATE personal_evaluations SET plan_status = 'approved' WHERE status != 'draft'"))
            conn.execute(text("UPDATE personal_kpi_items SET from_plan = 1 WHERE evaluation_id IN "
                              "(SELECT id FROM personal_evaluations WHERE plan_status = 'approved')"))

        # KPI tập thể tách 2 giai đoạn: bản ghi cũ đã duyệt = Mẫu 1 đã duyệt; Mẫu 2 coi là đã duyệt khi
        # mọi chỉ tiêu đều có kết quả (luồng cũ chỉ cho trình khi đủ kết quả), giữ nguyên người duyệt, xếp loại.
        if "collective_evaluations.result_status" in changes:
            conn.execute(text(
                "UPDATE collective_evaluations SET result_status = 'approved', "
                "result_confirmed_by_id = confirmed_by_id, result_confirmed_at = confirmed_at "
                "WHERE status = 'approved' AND NOT EXISTS (SELECT 1 FROM indicators i "
                "LEFT JOIN collective_kpis k ON k.indicator_id = i.id "
                "WHERE i.period_id = collective_evaluations.period_id "
                "AND i.department_id = collective_evaluations.department_id AND k.result IS NULL)"))

        # Đổi tên vai trò cũ sang 5 vai trò mới (25/10/2026); tài khoản không đổi gì khác.
        for old, new in Role.LEGACY.items():
            n = conn.execute(text("UPDATE users SET role = :new WHERE role = :old"), {"new": new, "old": old}).rowcount
            if n:
                changes.append(f"users.role {old}->{new} ({n})")
    return changes
