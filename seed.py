"""
seed.py - Nạp dữ liệu danh mục mặc định (idempotent: chạy nhiều lần không bị trùng).

Nguồn: Hướng dẫn 07-HD/BTCTU (mục I), Phụ lục 2 (hệ số KPI), Mẫu 5 (tiêu chí chung),
Mẫu 7, Mẫu 8 (nhóm đối tượng).
Lưu ý: tiêu đề tiêu chí chung ở đây là bản rút gọn; nội dung đầy đủ nên nạp từ Quy định 89-QĐ/TU.
"""
from models import (
    Axis, CommonCriterion, KpiCategory, KpiCoefficient, PositionGroup, db,
)

AXES = [
    (1, "Thực hiện mục tiêu phát triển kinh tế - xã hội và nhiệm vụ chính trị được giao"),
    (2, "Hoàn thiện thể chế, đẩy mạnh phân cấp, phân quyền gắn với kiểm tra, giám sát"),
    (3, "Thúc đẩy phát triển khoa học, công nghệ, đổi mới sáng tạo và chuyển đổi số"),
    (4, "Xây dựng Đảng và hệ thống chính trị trong sạch, vững mạnh; giữ gìn đoàn kết, thống nhất nội bộ; "
        "phòng, chống tham nhũng, lãng phí, tiêu cực"),
    (5, "Phát triển văn hóa, con người, bảo đảm an sinh xã hội, nâng cao đời sống nhân dân"),
    (6, "Củng cố quốc phòng, an ninh, giữ vững ổn định chính trị - xã hội, nâng cao hiệu quả đối ngoại "
        "và hội nhập quốc tế"),
]

# (category, code, label, value, bonus_value, description)
COEFFICIENTS = [
    (KpiCategory.QUALITY, 1, "Hoàn thành xuất sắc", 1.0, 0.1,
     "Sản phẩm bảo đảm chất lượng, không có sai sót"),
    (KpiCategory.QUALITY, 2, "Hoàn thành tốt", 0.9, 0.1,
     "Có sai sót nhỏ nhưng không ảnh hưởng đến kết quả thực hiện nhiệm vụ"),
    (KpiCategory.QUALITY, 3, "Hoàn thành", 0.8, 0.1,
     "Có sai sót phải chỉnh sửa, bổ sung nhưng vẫn bảo đảm yêu cầu"),
    (KpiCategory.QUALITY, 4, "Hoàn thành nhưng còn nhiều hạn chế", 0.7, 0.1,
     "Phải chỉnh sửa nhiều lần hoặc ảnh hưởng đến chất lượng sản phẩm"),

    (KpiCategory.PROGRESS, 1, "Đúng hạn", 1.0, 0.1,
     "Hoàn thành đầy đủ chỉ tiêu, nhiệm vụ đúng hạn"),
    (KpiCategory.PROGRESS, 2, "Một số nhiệm vụ chậm", 0.9, 0.1,
     "Hoàn thành đầy đủ nhưng một số chỉ tiêu, nhiệm vụ hoàn thành chậm so với thời hạn"),
    (KpiCategory.PROGRESS, 3, "Chưa hoàn thành đầy đủ", 0.8, 0.1,
     "Chưa hoàn thành đầy đủ chỉ tiêu, nhiệm vụ; có chỉ tiêu, nhiệm vụ còn chậm tiến độ"),
    (KpiCategory.PROGRESS, 4, "Chưa hoàn thành phần lớn", 0.7, 0.1,
     "Chưa hoàn thành phần lớn chỉ tiêu, nhiệm vụ hoặc chậm tiến độ ảnh hưởng đến kết quả"),

    (KpiCategory.LEADERSHIP, 1, "Chủ động, quyết liệt, kịp thời", 1.0, None,
     "Lãnh đạo, chỉ đạo, điều hành chủ động, quyết liệt, kịp thời; bảo đảm số lượng, chất lượng, tiến độ"),
    (KpiCategory.LEADERSHIP, 2, "Thực hiện đầy đủ trách nhiệm", 0.9, None,
     "Thực hiện đầy đủ trách nhiệm; có nhiệm vụ chưa bảo đảm về số lượng, chất lượng hoặc tiến độ"),
    (KpiCategory.LEADERSHIP, 3, "Có hạn chế", 0.8, None,
     "Có hạn chế trong lãnh đạo, chỉ đạo, điều hành; chưa bảo đảm cả số lượng, chất lượng và tiến độ"),
    (KpiCategory.LEADERSHIP, 4, "Còn nhiều hạn chế", 0.7, None,
     "Còn nhiều hạn chế, ảnh hưởng đến kết quả nhiệm vụ hoặc hoạt động của đơn vị, bộ phận phụ trách"),
]

G1 = "Phẩm chất chính trị, đạo đức, lối sống, thực hiện trách nhiệm nêu gương"
G2 = "Tư duy đổi mới, chiến lược, khát vọng cống hiến, dám nghĩ, dám làm"
G3 = "Tự phê bình và phê bình, tự soi, tự sửa, khắc phục hạn chế, khuyết điểm"

# (code, group_no, group_title, title(rút gọn), max_score)  -> 18 + 4 + 8 = 30 điểm
COMMON_CRITERIA = [
    ("1.1", 1, G1, "Trung thành với Đảng, Tổ quốc, Nhân dân; lập trường, bản lĩnh chính trị vững vàng", 2),
    ("1.2", 1, G1, "Yêu nước, tận tụy phục vụ Nhân dân; đặt lợi ích chung lên trên lợi ích cá nhân", 2),
    ("1.3", 1, G1, "Chấp hành nghiêm chủ trương, nghị quyết, nguyên tắc tổ chức, kỷ luật của Đảng, pháp luật; "
                   "chấp hành sự phân công của tổ chức", 2),
    ("1.4", 1, G1, "Tự giác học tập lý luận chính trị, nghị quyết, chỉ thị; cập nhật kiến thức mới", 2),
    ("1.5", 1, G1, "Đạo đức, lối sống trong sáng; chuẩn mực đạo đức cách mạng; trách nhiệm nêu gương", 2),
    ("1.6", 1, G1, "Không tham vọng quyền lực, không tham nhũng, lãng phí, lợi ích nhóm; không có biểu hiện suy thoái", 2),
    ("1.7", 1, G1, "Có uy tín, là trung tâm đoàn kết, thương yêu đồng chí, đồng nghiệp", 2),
    ("1.8", 1, G1, "Chủ động, đổi mới sáng tạo; phấn đấu vì mục tiêu phát triển của cơ quan, đơn vị", 2),
    ("1.9", 1, G1, "Kê khai, công khai tài sản, thu nhập; báo cáo đầy đủ, trung thực, chính xác khi được yêu cầu", 2),
    ("2.1", 2, G2, "Tư duy đổi mới, tầm nhìn chiến lược, phương pháp làm việc khoa học; năng lực cụ thể hóa", 1),
    ("2.2", 2, G2, "Bám sát thực tiễn, nhiều cách làm hay, sáng tạo, hiệu quả cao", 1),
    ("2.3", 2, G2, "Nói đi đôi với làm, dám nghĩ, dám làm, dám chịu trách nhiệm; phân tích, dự báo, đề xuất giải pháp", 1),
    ("2.4", 2, G2, "Khát vọng cống hiến; quy tụ và phát huy sức mạnh của tập thể", 1),
    ("3.1", 3, G3, "Chủ động, nghiêm túc tự phê bình và phê bình; cầu thị, tiếp thu phản biện, góp ý", 2),
    ("3.2", 3, G3, "Có kế hoạch rõ ràng, quyết liệt khắc phục hạn chế, khuyết điểm đã được chỉ ra", 2),
    ("3.3", 3, G3, "Kết quả khắc phục đạt từ 80% nội dung trở lên, tiến bộ rõ; không để tái diễn", 2),
    ("3.4", 3, G3, "Tự soi, tự sửa với trách nhiệm chính trị cao, không né tránh, không đổ lỗi", 2),
]

# (code, form, name) - theo thứ tự cột Mẫu 7 / Mẫu 8
POSITION_GROUPS = [
    ("M7-UVBTV", "M7", "Ủy viên Ban Thường vụ Đảng ủy xã, phường, Đảng ủy trực thuộc Thành ủy "
                       "(không gồm Bí thư và các Phó Bí thư)"),
    ("M7-UVBCH", "M7", "Ủy viên Ban Chấp hành Đảng bộ xã, phường, Đảng ủy trực thuộc Thành ủy "
                       "(không gồm Bí thư, Phó Bí thư, Ủy viên Ban Thường vụ)"),
    ("M7-TRUONG", "M7", "Cấp trưởng ban, phòng và tương đương cấp xã (không là Ủy viên BCH Đảng bộ)"),
    ("M7-PHO", "M7", "Cấp phó trưởng phòng, ban và tương đương cấp xã (không là Ủy viên BCH Đảng bộ)"),
    ("M7-KHAC", "M7", "Cán bộ lãnh đạo, quản lý khác cấp xã"),

    ("M8-SO-TRUONG", "M8", "Cấp trưởng các sở, ban, ngành, đơn vị sự nghiệp và tương đương thuộc HĐND, UBND thành phố"),
    ("M8-SO-PHO", "M8", "Cấp phó các sở, ban, ngành, đơn vị sự nghiệp và tương đương thuộc HĐND, UBND thành phố"),
    ("M8-TU-PHO", "M8", "Cấp phó cơ quan tham mưu, giúp việc, đơn vị sự nghiệp trực thuộc Thành ủy"),
    ("M8-CA-QS", "M8", "Phó Giám đốc Công an thành phố, Phó Chỉ huy trưởng, Phó Chính ủy BCHQS thành phố"),
    ("M8-UBKT", "M8", "Ủy viên Ủy ban Kiểm tra Thành ủy"),
    ("M8-MT-PHO", "M8", "Cấp phó cơ quan Ủy ban Mặt trận Tổ quốc Việt Nam thành phố"),
    ("M8-CTXH-TRUONG", "M8", "Cấp trưởng các tổ chức chính trị - xã hội cấp thành phố"),
    ("M8-HOI-TRUONG", "M8", "Cấp trưởng các Hội quần chúng do Đảng, Nhà nước giao nhiệm vụ"),
    ("M8-CTXH-PHO", "M8", "Cấp phó các tổ chức chính trị - xã hội cấp thành phố"),
    ("M8-PHONG-TRUONG", "M8", "Cấp trưởng phòng, ban và tương đương thuộc các cơ quan, đơn vị cấp thành phố"),
    ("M8-PHONG-PHO", "M8", "Cấp phó trưởng phòng, ban và tương đương thuộc các cơ quan, đơn vị cấp thành phố"),
    ("M8-KHAC", "M8", "Cán bộ lãnh đạo, quản lý khác cấp thành phố"),
]


def seed_axes() -> None:
    for number, name in AXES:
        if not Axis.query.filter_by(number=number).first():
            db.session.add(Axis(number=number, name=name))


def seed_coefficients() -> None:
    for category, code, label, value, bonus, desc in COEFFICIENTS:
        if not KpiCoefficient.query.filter_by(category=category, code=code).first():
            db.session.add(KpiCoefficient(
                category=category, code=code, label=label, value=value,
                bonus_value=bonus, description=desc,
            ))


def seed_common_criteria() -> None:
    for i, (code, group_no, group_title, title, max_score) in enumerate(COMMON_CRITERIA, start=1):
        if not CommonCriterion.query.filter_by(code=code).first():
            db.session.add(CommonCriterion(
                code=code, group_no=group_no, group_title=group_title,
                title=title, max_score=max_score, sort=i,
            ))


def seed_position_groups() -> None:
    for i, (code, form, name) in enumerate(POSITION_GROUPS, start=1):
        if not PositionGroup.query.filter_by(code=code).first():
            db.session.add(PositionGroup(code=code, form=form, name=name, sort=i))


def seed_all() -> None:
    seed_axes()
    seed_coefficients()
    seed_common_criteria()
    seed_position_groups()
    db.session.commit()
