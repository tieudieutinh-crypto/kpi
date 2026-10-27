"""Trang Tổng quan: hiển thị theo vai trò và giới hạn số liệu theo phạm vi."""
from tests.test_kpi import app, client, ids, to_submitted  # noqa: F401  (dùng lại fixture và hàm hỗ trợ)


def page(app, who):
    r = client(app, who).get("/")
    assert r.status_code == 200
    return r.get_data(as_text=True)


def test_dashboard_renders_for_every_role(app):
    for who in ("admin", "leader", "leader_p1", "manager1", "staff1"):
        html = page(app, who)
        assert "Tổng quan" in html and "Mốc thời gian" in html


def test_staff_sees_only_own_profile(app):
    html = page(app, "staff1")
    assert "Hồ sơ của tôi" in html
    assert "Tiến độ KPI của các cá nhân" not in html and "Tiến độ theo Phòng, Ban" not in html


def test_team_numbers_follow_scope(app):
    to_submitted(app, "staff1")
    leader = page(app, "leader")                 # Phó Bí thư: toàn cơ quan
    assert "Tiến độ theo Phòng, Ban" in leader and "Phòng 2" in leader
    assert "Tiến độ KPI của các cá nhân" in leader and "Staff2" in leader
    manager = page(app, "manager1")              # Phó TB Thường trực: chỉ Ban của mình
    assert "Phòng 2" not in manager and "Staff2" not in manager and "Staff1" in manager
    assert "Chờ tôi xử lý" in manager and "đang chờ bạn nhận xét" in manager


def test_people_table_filter_and_links(app):
    c, eid = to_submitted(app, "staff1")
    p2 = ids(app)["p2"]
    html = client(app, "leader").get(f"/?ban={p2}").get_data(as_text=True)
    people = html.split('id="people"', 1)[1]
    assert "Staff2" in people and "Staff1" not in people                    # lọc theo Ban
    html = client(app, "leader").get("/").get_data(as_text=True).split('id="people"', 1)[1]
    assert f'href="/kpi/{eid}"' in html                                      # hồ sơ đã trình: bấm tên mở được
    for tile in ("Phòng, Ban", "Cán bộ, công chức", "Đã gửi hồ sơ", "Đã duyệt hồ sơ", "Điểm trung bình"):
        assert tile in client(app, "leader").get("/").get_data(as_text=True), tile


def test_dashboard_with_own_profile(app):
    to_submitted(app, "staff1")                  # có hồ sơ: thẻ "Hồ sơ của tôi" hiện trạng thái, không lỗi 500
    html = page(app, "staff1")
    assert "Hồ sơ của tôi" in html and "điểm" in html
