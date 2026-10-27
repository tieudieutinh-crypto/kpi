# Webapp chấm KPI cán bộ lãnh đạo, quản lý hằng quý

Flask + SQLite, theo Hướng dẫn 07-HD/BTCTU (Ban Tổ chức Thành ủy Cần Thơ) và Phụ lục 1, 2.

## Chạy thử

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python create_admin.py                              # tạo bảng + tài khoản quản trị đầu tiên (hỏi mật khẩu ẩn)
flask --app app create-period --year 2026 --quarter 4
flask --app app run --debug
```

Mở http://127.0.0.1:5000, đăng nhập bằng tài khoản vừa tạo, vào **Phòng ban** để tạo cơ cấu tổ chức, sau đó người dùng tự đăng ký tại `/register` và quản trị viên duyệt ở **Người dùng**.

> Nếu bạn đã chạy bản trước (lượt 1): xóa `instance/kpi.db` rồi chạy lại `create_admin.py`, vì bảng `users` có thêm cột và vai trò đổi tên.

Kiểm thử: `pip install pytest && pytest -q` (24 test: đăng ký, đăng nhập, khóa tài khoản, token phiên, phân quyền, CSRF, script tạo admin).

### Tạo admin không tương tác (Docker, CI)
```bash
KPI_ADMIN_PASSWORD='mat-khau-manh-123' python create_admin.py --username admin --full-name "Quản trị viên"
```
Không truyền mật khẩu qua tham số dòng lệnh. Script từ chối nếu đã có admin, trừ khi thêm `--force`.

## Bảo mật

| Hạng mục | Cách làm |
|---|---|
| Mật khẩu | Băm scrypt + salt ngẫu nhiên (werkzeug), không lưu mật khẩu gốc. Tối thiểu 8 ký tự, có chữ và số, chặn mật khẩu phổ biến |
| Phiên đăng nhập | Cookie ký bằng `SECRET_KEY`, HttpOnly, SameSite=Lax, hết hạn sau 8 giờ (nhớ đăng nhập: 7 ngày) |
| Token phiên | Mỗi tài khoản có `session_token` trong CSDL, cookie chứa `<id>:<token>`. Token đổi khi: đổi mật khẩu, khóa, đổi vai trò/phòng ban, admin đặt lại mật khẩu hoặc đăng xuất thiết bị -> mọi phiên cũ mất hiệu lực ngay |
| Đăng nhập sai | 5 lần liên tiếp -> tạm khóa 15 phút; thông báo lỗi chung, không lộ tên đăng nhập có tồn tại hay không |
| Đăng ký | Người đăng ký chọn vai trò trong danh sách cho phép (không gồm Quản trị hệ thống, Phó Bí thư Thường trực; máy chủ kiểm tra lại, giá trị khác bị từ chối); tài khoản **chờ admin duyệt**, admin kiểm tra vai trò trước khi duyệt; có ô bẫy bot. Tắt hẳn bằng `REGISTRATION_ENABLED=0` |
| CSRF | Mọi form POST có token (Flask-WTF); đăng xuất chỉ nhận POST |
| Khác | Chặn open-redirect ở `?next=`, header `X-Frame-Options`, `nosniff`, `Cache-Control: no-store`; production bắt buộc đặt `SECRET_KEY` |

Khi chạy qua HTTPS đặt `COOKIE_SECURE=1`.

## Vai trò và phân quyền (điều chỉnh v2, 25/10/2026)

Chi tiết: [docs/dieu-chinh-v2.md](docs/dieu-chinh-v2.md).

| Chức năng | Admin | Phó Bí thư TT | Phó TB Thường trực | Phó Trưởng Ban | Công chức |
|---|:-:|:-:|:-:|:-:|:-:|
| Dashboard, tài khoản | ✔ | ✔ | ✔ | ✔ | ✔ |
| Người dùng, Phòng Ban, Kỳ đánh giá | ✔ | ✘ | ✘ | ✘ | ✘ |
| Xem KPI tập thể | mọi Ban | mọi Ban | Ban mình | Ban mình | Ban mình |
| Lập, trình KPI tập thể | ✘ | ✘ | Ban mình | ✘ | ✘ |
| Duyệt cuối KPI tập thể | ✘ | ✔ | ✘ | ✘ | ✘ |
| Lập, tự chấm KPI cá nhân | ✘ | ✔ (không trình) | ✔ | ✔ | ✔ |
| Chỉ số D (lãnh đạo, điều hành) | – | ✔ | ✔ | ✔ | ✘ |
| Duyệt Mẫu 3 cấp Ban, nhận xét Mẫu 5 | ✘ | ✘ | PTB, công chức cùng Ban | ✘ | ✘ |
| Duyệt cuối Mẫu 3, quyết định xếp loại | ✘ | ✔ | ✘ | ✘ | ✘ |
| Mở lại Mẫu 3 đã trình | ✔ | ✔ | ✘ | ✘ | ✘ |

Vai trò cũ tự chuyển khi khởi động: Lãnh đạo → Phó Bí thư TT, Trưởng phòng → Phó TB Thường trực, Nhân viên → Công chức.

## Cấu trúc

```
kpi_app/
├── app.py            # create_app, kiểm tra token phiên, CSRF, lệnh CLI
├── create_admin.py   # script tạo admin đầu tiên
├── models.py         # toàn bộ bảng dữ liệu + công thức tính KPI
├── permissions.py    # ma trận quyền, phạm vi dữ liệu theo phòng ban
├── seed.py           # dữ liệu danh mục mặc định
├── config.py
├── services/auth.py  # xác thực, chính sách mật khẩu, tạo tài khoản
├── routes/           # auth.py, users.py, admin.py  (sau này: indicators, kpi, review, reports)
├── templates/  static/  tests/  instance/
```

## Các bảng (tóm tắt)

`users`, `departments`, `position_groups`, `axes`, `periods`, `indicators` (Mẫu 1), `collective_kpis` và `collective_evaluations` (Mẫu 2), `kpi_coefficients` (Phụ lục 2), `common_criteria`, `personal_evaluations` (Mẫu 5, 6), `personal_kpi_items` (Mẫu 3, 4), `personal_axis_results`, `personal_common_scores`.

## Công thức (Phụ lục 2)

- Hệ số quy đổi = điểm công việc cụ thể / 100
- KPI số lượng = thực tế / kế hoạch (tối đa 1, phần vượt ghi vào hệ số vượt)
- A, B, C, D = Σ(cột quy đổi) / Σ(hệ số quy đổi) × 100
- KPI = (A + B + C + D) / 4; điểm trục = KPI × điểm tối đa của trục / 100
- Tổng điểm = tiêu chí chung (tối đa 30) + kết quả nhiệm vụ (tối đa 70)

## KPI cá nhân và KPI tập thể (lượt 3)

### Luồng xử lý
KPI cá nhân, 3 bước trên cùng một trang `/kpi/<id>`:
1. **Mẫu 3** (`plan_status`): Đang lập → Trình → Phó TB TT duyệt → Phó Bí thư duyệt cuối. Đã trình thì khóa;
   người duyệt trả lại được; Admin hoặc Phó Bí thư mở lại. Khi trình lưu bản chụp để Mẫu 3 không đổi về sau.
2. **Mẫu 4**: mở khi Mẫu 3 đã duyệt cuối; nhiệm vụ của Mẫu 3 giữ nguyên, chỉnh hệ số quy đổi, thêm nhiệm vụ mới.
3. **Mẫu 5** (`status`): Nháp → Trình → Phó TB TT nhận xét → Phó Bí thư quyết định xếp loại (có thu hồi, trả lại, mở lại).
Phó TB Thường trực trình thẳng Phó Bí thư; Phó Bí thư chỉ lưu, không trình.

KPI tập thể (theo Ban): `Nháp → Trình → Phó Bí thư duyệt`, có thu hồi, trả lại, mở lại.

### Trang
| Đường dẫn | Chức năng |
|---|---|
| `/kpi/` | KPI của tôi theo kỳ |
| `/kpi/<id>` | Nhập mục tiêu, kết quả; xem trước điểm; nhận xét/duyệt |
| `/kpi/queue` | Hồ sơ cần nhận xét/phê duyệt |
| `/collective/` | Danh sách và nhập KPI tập thể (Mẫu 1, Mẫu 2) |
| `/admin/periods` | Quản lý kỳ đánh giá và hạn nộp |

Điểm được tính ngay trên trình duyệt để xem trước; khi lưu, máy chủ tính lại và là kết quả chính thức.

### Nâng cấp CSDL cũ
Khi khởi động, ứng dụng tự thêm bảng/cột còn thiếu mà không xóa dữ liệu. Chạy tay: `flask --app app upgrade-db`.

### Kiểm thử
`python -m pytest` (68 bài kiểm tra, gồm ví dụ Phụ lục 2: KPI 96,24; tổng 97,37).

### Chưa có
Công bố kết quả, báo cáo Mẫu 6–8 và xuất Excel, hạn mức HTXS 20%, giao diện sửa bảng hệ số.
