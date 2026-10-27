"""Kiểm thử đăng nhập, đăng ký, token phiên và phân quyền.  Chạy: pytest -q

Lưu ý: fixture KHÔNG giữ app context mở trong lúc gửi request, để mỗi request có context
(và đối tượng g, phiên CSDL) riêng như khi chạy thật. Truy cập CSDL trực tiếp trong test
phải đặt trong `with app.app_context():`.
"""
import pytest

from app import create_app
from models import Department, Role, User, db
from seed import seed_all
from services.auth import MAX_FAILED_ATTEMPTS, create_user, validate_password

PW = "CanTho2026kpi"


@pytest.fixture
def app():
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        seed_all()
        root = Department(code="TU", name="Thành ủy")
        p1 = Department(code="P1", name="Phòng 1", parent=root)
        p2 = Department(code="P2", name="Phòng 2", parent=root)
        db.session.add_all([root, p1, p2])
        db.session.flush()
        for username, role, dept in [
            ("admin", Role.ADMIN, None),
            ("leader", Role.LEADER, root.id),
            ("manager1", Role.MANAGER, p1.id),
            ("staff1", Role.STAFF, p1.id),
            ("staff2", Role.STAFF, p2.id),
        ]:
            create_user(username, username.title(), PW, role=role, department_id=dept, approved=True)
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


def login(client, username, password=PW):
    return client.post("/login", data={"username": username, "password": password})


def logged_in(app, username):
    c = app.test_client()
    assert login(c, username).status_code == 302
    return c


def info(app, username):
    """Đọc nhanh vài thuộc tính của người dùng từ CSDL."""
    with app.app_context():
        u = User.query.filter_by(username=username).first()
        return dict(id=u.id, role=u.role, active=u.active, approved=u.approved,
                    full_name=u.full_name, department_id=u.department_id,
                    must_change=u.must_change_password)


# --------------------------- đăng ký / mật khẩu --------------------------- #
def test_password_is_hashed(app):
    with app.app_context():
        u = User.query.filter_by(username="staff1").first()
        assert u.password_hash != PW and PW not in u.password_hash
        assert u.check_password(PW) and not u.check_password("sai")


def test_password_policy():
    assert validate_password("abc123") != []          # quá ngắn
    assert validate_password("chuyenchu") != []       # thiếu số
    assert validate_password("12345678") != []        # thiếu chữ
    assert validate_password("Matkhau123") != []      # mật khẩu phổ biến
    assert validate_password(PW) == []


def test_register_role_whitelist_and_pending(app):
    c = app.test_client()
    html = c.get("/register").get_data(as_text=True)
    assert 'name="role"' in html and "Phó Chánh Văn phòng" in html
    assert 'value="admin"' not in html and 'value="pho_bi_thu"' not in html
    for bad in ("admin", "pho_bi_thu", "", "khong_co"):                 # bị từ chối dù gửi thẳng lên
        r = c.post("/register", data={"username": "bad" + (bad or "x")[:5], "full_name": "X", "password": PW,
                                      "confirm_password": PW, "role": bad})
        assert r.status_code == 200, bad
    with app.app_context():
        assert User.query.filter(User.username.like("bad%")).count() == 0
    base = {"username": "NewUser", "full_name": "Người Mới", "password": PW,
            "confirm_password": PW, "role": Role.PCVP, "approved": "1"}
    r = c.post("/register", data=base)                                         # thiếu Phòng, Ban
    assert r.status_code == 200 and "Vui lòng chọn Phòng, Ban" in r.get_data(as_text=True)
    assert 'value="Người Mới"' in r.get_data(as_text=True)                      # giữ lại dữ liệu đã nhập
    r = c.post("/register", data=dict(base, department_id="99999"))           # Phòng, Ban không tồn tại
    assert r.status_code == 200 and "Phòng, Ban không hợp lệ" in r.get_data(as_text=True)
    with app.app_context():
        assert User.query.filter_by(username="newuser").first() is None
        dept = Department.query.filter_by(code="P1").first().id
    r = c.post("/register", data=dict(base, department_id=str(dept)))
    assert r.status_code == 302
    u = info(app, "newuser")
    assert u["role"] == Role.PCVP and u["approved"] is False and u["department_id"] == dept   # vẫn chờ duyệt
    users_page = logged_in(app, "admin").get("/users/?status=pending").get_data(as_text=True)
    assert "Phó Chánh Văn phòng" in users_page and "cần kiểm tra trước khi duyệt" in users_page
    # chưa duyệt thì không đăng nhập được
    r = login(c, "newuser")
    assert r.status_code == 200 and "chờ quản trị viên duyệt" in r.get_data(as_text=True)


def test_register_rejects_duplicate_and_mismatch(app):
    c = app.test_client()
    r = c.post("/register", data={"username": "staff1", "full_name": "X", "password": PW, "confirm_password": PW})
    assert r.status_code == 200
    r = c.post("/register", data={"username": "abc", "full_name": "X", "password": PW, "confirm_password": "khac1234"})
    assert r.status_code == 200
    with app.app_context():
        assert User.query.filter_by(username="staff1").count() == 1
        assert User.query.filter_by(username="abc").first() is None


def test_register_honeypot(app):
    c = app.test_client()
    c.post("/register", data={"username": "botuser", "full_name": "Bot", "password": PW, "role": Role.CC,
                              "confirm_password": PW, "website": "http://spam"})
    with app.app_context():
        assert User.query.filter_by(username="botuser").first() is None


# --------------------------- đăng nhập / phiên --------------------------- #
def test_login_logout_flow(app):
    c = app.test_client()
    assert c.get("/").status_code == 302
    assert login(c, "staff1").status_code == 302
    assert c.get("/").status_code == 200
    assert c.get("/logout").status_code == 405           # đăng xuất chỉ nhận POST
    assert c.post("/logout").status_code == 302
    assert c.get("/").status_code == 302


def test_wrong_password_generic_message_and_lockout(app):
    c = app.test_client()
    for _ in range(MAX_FAILED_ATTEMPTS):
        assert login(c, "staff1", "Sai12345").status_code == 200
    # đã bị tạm khóa: đúng mật khẩu cũng không vào được
    assert login(c, "staff1").status_code == 200
    # tên đăng nhập không tồn tại cho cùng thông báo
    assert "không đúng" in login(c, "khongco", "Sai12345").get_data(as_text=True)


def test_open_redirect_blocked(app):
    r = app.test_client().post("/login?next=https://evil.example", data={"username": "staff1", "password": PW})
    assert "evil" not in r.headers["Location"]
    r = app.test_client().post("/login?next=//evil.example", data={"username": "staff1", "password": PW})
    assert "evil" not in r.headers["Location"]


def test_session_token_rotation_invalidates_old_session(app):
    c = logged_in(app, "staff1")
    assert c.get("/").status_code == 200
    with app.app_context():
        u = User.query.filter_by(username="staff1").first()
        u.rotate_token()
        db.session.commit()
    assert c.get("/").status_code == 302                  # phiên cũ bị từ chối


def test_change_password_logs_out_other_devices(app):
    c1, c2 = logged_in(app, "staff1"), logged_in(app, "staff1")
    r = c1.post("/account/password", data={
        "current_password": PW, "new_password": "MoiMoi9999", "confirm_password": "MoiMoi9999"})
    assert r.status_code == 302
    assert c1.get("/").status_code == 200                 # thiết bị đổi mật khẩu vẫn đăng nhập
    assert c2.get("/").status_code == 302                 # thiết bị khác bị đăng xuất
    assert login(app.test_client(), "staff1", "MoiMoi9999").status_code == 302
    assert login(app.test_client(), "staff1", PW).status_code == 200


def test_logout_all_keeps_current_device(app):
    c1, c2 = logged_in(app, "staff1"), logged_in(app, "staff1")
    assert c1.post("/account/logout-all").status_code == 302
    assert c1.get("/").status_code == 200
    assert c2.get("/").status_code == 302


def test_locked_user_is_kicked_out(app):
    c = logged_in(app, "staff1")
    admin = logged_in(app, "admin")
    assert admin.post(f"/users/{info(app, 'staff1')['id']}/toggle-lock").status_code == 302
    assert c.get("/").status_code == 302
    assert "bị khóa" in login(app.test_client(), "staff1").get_data(as_text=True)


def test_must_change_password_redirect(app):
    admin = logged_in(app, "admin")
    uid = info(app, "staff1")["id"]
    admin.post(f"/users/{uid}/reset-password")
    assert info(app, "staff1")["must_change"] is True
    with app.app_context():                               # đặt lại mật khẩu đã biết để đăng nhập thử
        u = db.session.get(User, uid)
        u.set_password(PW)
        db.session.commit()
    c = app.test_client()
    assert login(c, "staff1").headers["Location"].endswith("/account/password")
    assert c.get("/").headers["Location"].endswith("/account/password")


# --------------------------- phân quyền --------------------------- #
def test_page_permissions(app):
    expect = {          # vai trò -> (/users/, /users/new, /admin/departments)
        "admin":    (200, 200, 200),
        "leader":   (403, 403, 403),       # menu Người dùng, Phòng Ban chỉ dành cho Admin
        "manager1": (403, 403, 403),
        "staff1":   (403, 403, 403),
    }
    for username, codes in expect.items():
        c = logged_in(app, username)
        got = tuple(c.get(p).status_code for p in ("/users/", "/users/new", "/admin/departments"))
        assert got == codes, username
        assert c.get("/account").status_code == 200       # trang chung


def test_anonymous_redirected_to_login(app):
    c = app.test_client()
    for path in ("/", "/users/", "/admin/departments", "/account"):
        r = c.get(path)
        assert r.status_code == 302 and "/login" in r.headers["Location"], path


def test_user_list_admin_only(app):
    html = logged_in(app, "admin").get("/users/").get_data(as_text=True)
    assert {n for n in ("Admin", "Leader", "Manager1", "Staff1", "Staff2") if f"<b>{n}</b>" in html} == \
        {"Admin", "Leader", "Manager1", "Staff1", "Staff2"}
    for username in ("leader", "manager1", "staff1"):
        assert logged_in(app, username).get("/users/").status_code == 403, username


def test_sidebar_menu_by_role(app):
    def menu(username):
        html = logged_in(app, username).get("/").get_data(as_text=True)
        nav = html.split('class="side-nav"', 1)[1].split("</nav>", 1)[0]
        return {label for label in ("Dashboard", "Người dùng", "Phòng, Ban", "KPI tập thể", "KPI cá nhân",
                                    "Duyệt KPI", "Kỳ đánh giá", "Báo cáo") if label in nav}
    assert menu("admin") == {"Dashboard", "Người dùng", "Phòng, Ban", "KPI tập thể", "Kỳ đánh giá", "Báo cáo"}
    assert menu("leader") == {"Dashboard", "KPI tập thể", "KPI cá nhân", "Duyệt KPI", "Báo cáo"}
    assert menu("manager1") == {"Dashboard", "KPI tập thể", "KPI cá nhân", "Duyệt KPI", "Báo cáo"}
    assert menu("staff1") == {"Dashboard", "KPI tập thể", "KPI cá nhân"}
    login_page = app.test_client().get("/login").get_data(as_text=True)
    assert 'class="sidebar"' not in login_page and 'class="sidebar"' not in app.test_client().get("/register").get_data(as_text=True)


def test_non_admin_cannot_manage_users(app):
    target = info(app, "staff2")["id"]
    for username in ("leader", "manager1", "staff1"):
        c = logged_in(app, username)
        for action in ("approve", "reject", "toggle-lock", "reset-password", "force-logout"):
            assert c.post(f"/users/{target}/{action}").status_code == 403, (username, action)
        assert c.post(f"/users/{target}/edit", data={"full_name": "x"}).status_code == 403


def test_admin_guards(app):
    c = logged_in(app, "admin")
    me = info(app, "admin")["id"]
    c.post(f"/users/{me}/toggle-lock")
    assert info(app, "admin")["active"] is True           # không tự khóa mình
    c.post(f"/users/{me}/edit", data={"full_name": "Admin", "role": Role.STAFF})
    assert info(app, "admin")["role"] == Role.ADMIN       # không tự hạ quyền


def test_admin_approve_and_reject(app):
    c = app.test_client()
    with app.app_context():
        dept = Department.query.filter_by(code="P1").first().id
    for name in ("p1user", "p2user"):
        c.post("/register", data={"username": name, "full_name": name, "password": PW, "confirm_password": PW,
                                  "role": Role.CC, "department_id": dept})
    admin = logged_in(app, "admin")
    admin.post(f"/users/{info(app, 'p1user')['id']}/approve")
    admin.post(f"/users/{info(app, 'p2user')['id']}/reject")
    assert login(app.test_client(), "p1user").status_code == 302
    with app.app_context():
        assert User.query.filter_by(username="p2user").first() is None


def test_admin_edit_role_forces_relogin(app):
    admin = logged_in(app, "admin")
    staff = logged_in(app, "staff1")
    u = info(app, "staff1")
    admin.post(f"/users/{u['id']}/edit", data={
        "full_name": u["full_name"], "role": Role.MANAGER, "department_id": u["department_id"]})
    assert info(app, "staff1")["role"] == Role.MANAGER
    assert staff.get("/").status_code == 302              # quyền đổi -> phiên cũ bị thu hồi


def test_ban_roles_need_department(app):
    admin = logged_in(app, "admin")
    u = info(app, "staff1")
    for role in (Role.PTB, Role.PTBTT, Role.CC):
        admin.post(f"/users/{u['id']}/edit", data={"full_name": u["full_name"], "role": role, "department_id": ""})
        assert info(app, "staff1")["role"] == Role.STAFF and info(app, "staff1")["department_id"] is not None
    admin.post(f"/users/{u['id']}/edit", data={"full_name": u["full_name"], "role": Role.PBT, "department_id": ""})
    assert info(app, "staff1")["role"] == Role.PBT                      # lãnh đạo cơ quan không bắt buộc thuộc Ban


def test_legacy_roles_migrated(app):
    from sqlalchemy import text
    from migrate import upgrade_schema
    with app.app_context():
        db.session.execute(text("UPDATE users SET role='lanh_dao' WHERE username='leader'"))
        db.session.execute(text("UPDATE users SET role='truong_phong' WHERE username='manager1'"))
        db.session.execute(text("UPDATE users SET role='nhan_vien' WHERE username='staff1'"))
        db.session.commit()
        changes = upgrade_schema()
        assert any("lanh_dao->pho_bi_thu" in c for c in changes)
    assert (info(app, "leader")["role"], info(app, "manager1")["role"], info(app, "staff1")["role"]) == \
        (Role.PBT, Role.PTBTT, Role.CC)
    assert login(app.test_client(), "manager1").status_code == 302      # tài khoản cũ vẫn đăng nhập được


def test_department_is_flat(app):
    admin = logged_in(app, "admin")
    with app.app_context():
        root = Department.query.filter_by(code="TU").first()
        child = Department.query.filter_by(code="P1").first()
        root_id, child_id = root.id, child.id
    admin.post("/admin/departments/save", data={
        "id": root_id, "code": "TU", "name": "Thành ủy", "level": "thanh_pho", "parent_id": child_id, "active": "1"})
    with app.app_context():
        assert db.session.get(Department, root_id).parent_id is None


def test_csrf_enforced_when_enabled(app):
    app.config["WTF_CSRF_ENABLED"] = True
    c = app.test_client()
    assert c.post("/login", data={"username": "staff1", "password": PW}).status_code == 400


# --------------------------- script tạo admin --------------------------- #
def test_create_admin_script(monkeypatch):
    import create_admin
    app = create_app("testing")
    monkeypatch.setenv("KPI_ADMIN_PASSWORD", PW)
    assert create_admin.main(["--username", "Root", "--full-name", "Root"], app=app) == 0
    with app.app_context():
        u = User.query.filter_by(username="root").first()
        assert u.role == Role.ADMIN and u.approved and u.check_password(PW)
    assert create_admin.main(["--username", "root2", "--full-name", "R2"], app=app) == 1   # đã có admin
    assert create_admin.main(["--username", "root2", "--full-name", "R2", "--force"], app=app) == 0
    monkeypatch.setenv("KPI_ADMIN_PASSWORD", "yeu")
    assert create_admin.main(["--username", "root3", "--full-name", "R3", "--force"], app=app) == 1
    with app.app_context():
        db.session.remove()
        db.drop_all()


def test_password_toggle_on_auth_pages(app):
    c = app.test_client()
    for path in ("/login", "/register"):
        assert "password_toggle.js" in c.get(path).get_data(as_text=True), path
    js = open("static/js/password_toggle.js", encoding="utf-8").read()
    assert 'input[type="password"]' in js and "Hiện mật khẩu" in js and "aria-pressed" in js


def test_register_unavailable_without_departments(app):
    with app.app_context():
        for d in Department.query.all():
            d.active = False
        db.session.commit()
    html = app.test_client().get("/register").get_data(as_text=True)
    assert "chưa tạo Phòng, Ban" in html and 'name="password"' not in html


def test_admin_delete_user_rules(app):
    admin = logged_in(app, "admin")
    with app.app_context():
        create_user("fresh", "Fresh O'Neil", PW, role=Role.CC, approved=True)
    fresh = info(app, "fresh")["id"]
    page = admin.get("/users/").get_data(as_text=True)
    assert f"/users/{fresh}/delete" in page and "Fresh O\\u0027Neil" in page            # tên có dấu nháy vẫn an toàn
    assert logged_in(app, "leader").post(f"/users/{fresh}/delete").status_code == 403    # không phải Admin
    admin.post(f"/users/{fresh}/delete")
    with app.app_context():
        assert User.query.filter_by(username="fresh").first() is None
    me = info(app, "admin")["id"]
    admin.post(f"/users/{me}/delete")                                                    # không tự xóa
    with app.app_context():
        assert db.session.get(User, me) is not None
        from models import Period, PersonalEvaluation
        p = Period.build(2026, 4); db.session.add(p); db.session.flush()
        staff = User.query.filter_by(username="staff1").first()
        db.session.add(PersonalEvaluation(user_id=staff.id, period_id=p.id)); db.session.commit()
    r = admin.post(f"/users/{info(app, 'staff1')['id']}/delete", follow_redirects=True)
    assert "đã có dữ liệu đánh giá" in r.get_data(as_text=True)
    with app.app_context():
        assert User.query.filter_by(username="staff1").first() is not None
        create_user("admin2", "Admin 2", PW, role=Role.ADMIN, approved=True)
    a2 = logged_in(app, "admin2")
    a2.post(f"/users/{me}/delete")                                                       # còn admin2 -> xóa được admin
    with app.app_context():
        assert db.session.get(User, me) is None
    with app.app_context():
        create_user("admin3", "Admin 3", PW, role=Role.ADMIN, approved=True)
        u2 = User.query.filter_by(username="admin2").first(); u2.active = False; db.session.commit()
    logged_in(app, "admin3").post(f"/users/{info(app, 'admin2')['id']}/delete")          # admin2 bị khóa: xóa được
    with app.app_context():
        assert User.query.filter_by(username="admin2").first() is None
        admin3 = User.query.filter_by(username="admin3").first().id
    c3 = logged_in(app, "admin3")
    c3.post(f"/users/{admin3}/delete")                                                   # admin cuối cùng / tự xóa
    with app.app_context():
        assert db.session.get(User, admin3) is not None
