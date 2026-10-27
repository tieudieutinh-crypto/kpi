# Điều chỉnh hệ thống chấm KPI theo file "Xây dựng Webapp" (25/10/2026)

Nguồn: file «Xây dựng Webapp» của người dùng (mục tiêu: chấm KPI hằng quý cán bộ, công chức cơ quan
Đảng ủy các cơ quan Đảng thành phố Cần Thơ; căn cứ Hướng dẫn 07-HD/BTCTU ngày 09/6/2026).

## 1. Giao diện chung: menu dọc bên trái
- Sidebar cố định bên trái: Dashboard, Người dùng (chỉ Admin), Phòng, Ban (chỉ Admin), KPI tập thể, KPI cá nhân,
  Duyệt KPI (người có quyền nhận xét/duyệt, kèm số hồ sơ chờ), Kỳ đánh giá (chỉ Admin).
- Cuối sidebar: tên, vai trò, Tài khoản, Đăng xuất. Màn hình hẹp (< 900px): sidebar thu thành nút ☰.
- Trang Đăng nhập, Đăng ký không có sidebar.

## 2. Vai trò (5 vai trò)
| Mã | Tên | Quyền chính |
|---|---|---|
| admin | Quản trị hệ thống | Người dùng, Phòng Ban, kỳ đánh giá; không chấm/duyệt KPI; mở lại Mẫu 3 |
| pho_bi_thu | Phó Bí thư Thường trực Đảng ủy | Lãnh đạo cơ quan: duyệt cuối KPI tập thể và cá nhân mọi Ban; tự lập KPI nhưng không trình |
| pho_truong_ban_tt | Phó Trưởng Ban Thường trực | Lãnh đạo Ban: lập, trình KPI tập thể của Ban; duyệt Mẫu 3, nhận xét Mẫu 5 của cán bộ trong Ban |
| pho_truong_ban | Phó Trưởng Ban | Tự lập, tự chấm KPI, có chỉ số D |
| cong_chuc | Công chức không giữ chức vụ lãnh đạo, quản lý | Tự lập, tự chấm KPI, không có chỉ số D |

- Dữ liệu cũ tự chuyển khi khởi động: lanh_dao → pho_bi_thu, truong_phong → pho_truong_ban_tt, nhan_vien → cong_chuc.
- Đăng ký mới: cong_chuc, chờ Admin duyệt.
- Chuỗi trình duyệt: cong_chuc, pho_truong_ban → Phó TB TT cùng Ban → Phó Bí thư duyệt cuối;
  pho_truong_ban_tt → Phó Bí thư; pho_bi_thu chỉ lưu (dashboard ghi «Không cần trình»).

## 3. Phòng, Ban
- Chỉ cấp thành phố; form chỉ có Mã, Tên (cột level/parent_id giữ trong CSDL, đặt mặc định). Phạm vi theo Ban phẳng.

## 4. KPI tập thể (Mẫu 1, Mẫu 2)
- Tên Phòng, Ban ở đầu trang. Chỉ Phó TB TT của Ban được thêm/sửa, lưu, trình; Phó Bí thư duyệt cuối, trả lại, mở lại.
- Bảng theo hàng, cột Mẫu 1, nhóm theo 6 trục × 2 nhóm nhiệm vụ, nút «+ Thêm nhiệm vụ» ở từng nhóm.
- Mẫu 2 (kết quả) nhập cuối quý, cùng luồng trình.

## 5. KPI cá nhân: 3 bước, dữ liệu riêng từng người
- Đầu trang: thông tin cá nhân và thanh bước 1-2-3.
- Bước 1 · Mẫu 3: lập → trình → Phó TB TT duyệt → Phó Bí thư duyệt cuối. Đã trình thì khóa; chỉ Admin hoặc
  Phó Bí thư mở lại; người duyệt trả lại kèm lý do. Trạng thái riêng `plan_status`, có nhật ký.
- Bước 2 · Mẫu 4: mở khi Mẫu 3 đã duyệt cuối (Phó Bí thư: khi đã chốt Mẫu 3). Lấy dữ liệu từ Mẫu 3; Mẫu 3 giữ
  nguyên (bản chụp `plan_snapshot`, cờ `from_plan`). Được điều chỉnh hệ số quy đổi, thêm nhiệm vụ mới.
  Công chức: không có chỉ số D (KPI = (A+B+C)/3).
- Bước 3 · Mẫu 5: tỷ lệ % KPI từng trục, điểm đạt / điểm phân bổ; tiêu chí chung 30 điểm; tự đề xuất xếp loại;
  trình → nhận xét → duyệt cuối.
- Không bắt buộc đủ 6 trục; khi trình chỉ yêu cầu trục có nhiệm vụ có điểm tối đa > 0 và tổng = 70.

## 6. Dashboard
- Thẻ: Phòng, Ban; cán bộ, công chức; Đã gửi hồ sơ (số/tổng, %); Đã duyệt hồ sơ (duyệt/gửi, %); điểm TB; chờ tôi xử lý.
- Tiến độ theo Phòng, Ban; mốc thời gian; biểu đồ; KPI tập thể; hoạt động gần đây.
- Bảng «Tiến độ KPI của các cá nhân»: họ tên, Ban, chức vụ, trạng thái Mẫu 3, Mẫu 4-5, điểm, xếp loại; lọc theo Ban.

## Cách hiểu đã chọn khi làm (cần người dùng xác nhận nếu khác)
1. Phó Bí thư chốt Mẫu 3 của mình bằng nút «Chốt Mẫu 3» (không phải trình); muốn sửa lại thì tự «Mở lại».
2. Ban chưa có Phó TB Thường trực: Phó Bí thư được duyệt cuối Mẫu 3 ngay từ trạng thái «Đã trình».
3. Mẫu 4: nhiệm vụ lấy từ Mẫu 3 không sửa nội dung, không xóa (nhập số lượng thực tế 0 nếu không làm); chỉ sửa
   điểm công việc (hệ số quy đổi) và nhập kết quả.
4. Người duyệt chỉ thấy số liệu Mẫu 4, 5 khi hồ sơ đã trình Mẫu 5.
5. KPI tập thể giữ một luồng trình chung cho Mẫu 1 và Mẫu 2 (trình khi đã có kết quả cuối quý).
6. Thứ tự, số hiệu cột trong các bảng theo chú thích cột trong mã nguồn (Mẫu 1: (1)-(10); Mẫu 4: (1)-(19));
   cần đối chiếu lại với file biểu mẫu gốc.

---

# Điều chỉnh lần 3 (26/10/2026) theo file «dieuchinh2»

1. **Hiện / ẩn mật khẩu**: mọi ô mật khẩu (đăng nhập, đăng ký, đổi mật khẩu) có nút hình con mắt
   (`static/js/password_toggle.js`, có nhãn cho trình đọc màn hình; khi gửi biểu mẫu luôn chuyển về dạng ẩn).
2. **Chọn vai trò khi đăng ký**: danh sách gồm mọi vai trò trừ Quản trị hệ thống và Phó Bí thư Thường trực.
   Máy chủ kiểm tra lại (giá trị khác bị từ chối). Tài khoản vẫn chờ Admin duyệt; danh sách Người dùng ghi rõ
   «vai trò tự chọn khi đăng ký, cần kiểm tra trước khi duyệt».
   **Phòng, Ban bắt buộc khi đăng ký** (người dùng xác nhận 26/10/2026): phải chọn một Phòng, Ban đang hoạt động,
   máy chủ từ chối giá trị trống hoặc không tồn tại và giữ lại dữ liệu đã nhập. Chưa có Phòng, Ban nào thì trang
   Đăng ký báo tạm chưa đăng ký được. Admin vẫn điều chỉnh được Phòng, Ban khi duyệt.
3. **Thêm 5 vai trò**, Văn phòng và Ủy ban Kiểm tra là đơn vị ngang Ban trong danh mục Phòng, Ban:
   | Vai trò | Nhóm quyền |
   |---|---|
   | Phó Chánh Văn phòng Thường trực | lãnh đạo đơn vị (như Phó Trưởng Ban Thường trực) |
   | Phó Chủ nhiệm Ủy ban Kiểm tra Thường trực | lãnh đạo đơn vị |
   | Phó Chánh Văn phòng | cấp phó (như Phó Trưởng Ban: có chỉ số D, không duyệt) |
   | Phó Chủ nhiệm Ủy ban Kiểm tra | cấp phó |
   | Ủy viên Chuyên trách Ủy ban Kiểm tra | cấp phó, tương đương Phó Trưởng Ban (người dùng xác nhận 26/10/2026): có chỉ số D, không có quyền duyệt |
   Quyền dùng chung theo nhóm `Role.UNIT_LEADERS`, `Role.DEPUTIES` (models.py). Thứ tự trong các danh sách chọn:
   Admin, Phó Bí thư TT, các lãnh đạo đơn vị cấp Thường trực, các cấp phó, Công chức.
4. **KPI tập thể tách 2 giai đoạn**:
   - Mẫu 1 (`status`): lập → trình → Phó Bí thư duyệt (trả lại, thu hồi, mở lại về nháp).
   - Mẫu 2 (`result_status`): chỉ mở khi Mẫu 1 đã duyệt; dòng lấy từ Mẫu 1 (chỉ xem), chỉ nhập cột kết quả và
     mục II, III; trình riêng → Phó Bí thư duyệt (kèm xếp loại tập thể), trả lại, mở lại.
   - Mở lại Mẫu 1: Mẫu 2 về nháp và khóa cho tới khi Mẫu 1 được duyệt lại; kết quả đã nhập giữ theo từng dòng.
   - Dữ liệu cũ: bản ghi đã duyệt được coi là Mẫu 1 đã duyệt; nếu mọi chỉ tiêu đã có kết quả thì Mẫu 2 cũng
     coi là đã duyệt (luồng cũ chỉ cho trình khi đủ kết quả).
   - Dashboard và danh sách KPI tập thể hiện trạng thái Mẫu 1, Mẫu 2 riêng.

## Mở rộng vùng nội dung trang KPI (26/10/2026)
- Trang KPI cá nhân (Mẫu 3, 4, 5) và KPI tập thể (Mẫu 1, 2) dùng hết bề ngang bên cạnh menu; các trang khác giữ độ rộng cũ.
- Nút «Thu gọn menu» ở menu trái (ghi nhớ trên trình duyệt); bấm ☰ ở thanh trên để mở lại.
- Bảng nhập liệu: cột Nhiệm vụ rộng hơn (≥ 320px), ô số, ngày, lựa chọn rộng vừa nội dung; ô văn bản tự giãn theo nội dung.
- Khi bảng vẫn rộng hơn màn hình (Mẫu 4 có 19 cột): cuộn ngang trong bảng, cột STT và Nhiệm vụ đứng yên;
  tên trục, nhóm nhiệm vụ, dòng «Cộng trục» và nút «+ Thêm nhiệm vụ» luôn hiện.
- Ảnh sau khi điều chỉnh (1920px): docs/kpi-ca-nhan-rong.png.

## Bố cục biểu mẫu theo file «4. Mau 2,4,5,6,7,8.xlsx» (26/10/2026)
Tin nhắn yêu cầu không kèm được file; đã dùng file `~/Downloads/4. Mau 2,4,5,6,7,8.xlsx` (sheet M2, M4–M8).
- **Mẫu 2** (KPI tập thể, kết quả): 11 cột đúng mẫu (1)…(11), cột (2) «Trục/Nhóm nhiệm vụ» gộp ô theo nhóm,
  (8)=(7)/(6)*100, (9)=(7)/(5)*100; mục I, II, III. Bỏ 2 cột không có trong mẫu (Đúng hạn, Ghi chú kết quả).
- **Mẫu 4** (tự chấm): 19 cột, tiêu đề 3 tầng như mẫu (NHIỆM VỤ ĐỀ RA KẾ HOẠCH / THỰC TẾ TRIỂN KHAI /
  Hệ số KPI vượt), cột (6) nhập trực tiếp hệ số quy đổi, cột (17)(18)(19) tách riêng, dòng «Cộng trục» và «TỔNG».
  Công chức: cột (15)(16) hiện «—». Giữ thêm các dòng tên trục, nhóm nhiệm vụ và nút «+ Thêm nhiệm vụ»
  (yêu cầu thêm nhiệm vụ theo từng trục, nhóm). Cột «Kết quả sản phẩm thực tế» chuyển sang Mẫu 5 phần B.
- **Mẫu 5**: thông tin cá nhân (họ tên, ngày sinh, chức vụ Đảng, chính quyền, đoàn thể, đơn vị công tác);
  I. A (7 cột, nhóm tiêu chí có điểm tối đa và điểm đạt, «Tổng (A) =»), B (8 cột: Tiêu chí – Mục tiêu, nhiệm vụ
  đề ra – Kết quả sản phẩm thực tế – Điểm KPI (%) – Điểm tối đa – Điểm đạt – Ghi chú; «TỔNG (B) =»,
  «TỔNG (A + B) =»); II. Tự đề xuất xếp loại; III. Nhận xét, đánh giá của cấp có thẩm quyền.
  Cột (3), (4) phần B lưu theo từng trục (mới), tự điền sẵn từ Mẫu 4 và sửa được.
- **Mẫu 6, 7, 8**: trang mới «Báo cáo» (menu trái; Admin, Phó Bí thư, lãnh đạo đơn vị), có nút In.
  Mẫu 6 liệt kê hồ sơ đã trình; Mẫu 7, 8 đếm hồ sơ đã quyết định xếp loại theo «Nhóm đối tượng (Mẫu 7, 8)» gán
  trong trang Người dùng (hồ sơ chưa gán nhóm được báo riêng). Mẫu 7 dành cho cấp xã nên với cơ quan cấp thành
  phố thường để trống.
- Tệp CSS/JS có số phiên bản để trình duyệt luôn tải bản mới sau khi cập nhật.

## Mẫu 4 vừa khung nội dung (26/10/2026)
- Bảng Mẫu 4: chữ 12px (tiêu đề 11px), các cột chia theo tỉ lệ cố định nên cả 19 cột nằm gọn trong khung,
  không phải cuộn ngang ở màn hình 1366px khi menu đang mở (đã kiểm tra 1366, 1440, 1920px).
- Ô số không còn mũi tên tăng/giảm; ô ngày nhập dạng dd/mm/yyyy (báo đỏ nếu sai); danh sách mức KPI chỉ hiện
  hệ số (1; 0,9; …), rê chuột để xem diễn giải đầy đủ. Cột (17), (18), (19) ghi gọn «KPI (SL)/(CL)/(TĐ)».
- Màn hình hẹp hơn 1000px vẫn cuộn ngang được trong bảng. Ảnh: docs/mau4-vua-khung.png (1366px).

## Người dùng: Xóa, căn thẳng nút; Xuất Excel (26/10/2026)
- **Xóa người dùng** (chỉ Admin, có hộp xác nhận ghi rõ tên): không tự xóa mình, không xóa quản trị viên
  đang hoạt động cuối cùng. Tài khoản đã có dữ liệu đánh giá (hồ sơ KPI, đã nhận xét/duyệt hồ sơ người khác,
  KPI tập thể, phụ trách chỉ tiêu, lịch sử xử lý) **không xóa** mà báo dùng «Khóa», để không mất lịch sử.
  Việc xóa được ghi vào nhật ký máy chủ.
- Trang Người dùng: nới cột Họ và tên, Trạng thái; các nút Sửa, Khóa, Đặt lại MK, Đăng xuất, Xóa cùng một
  hàng, cùng chiều cao. Ảnh: docs/users-page.png.
- **Xuất Excel** (services/export_excel.py, openpyxl): Mẫu 1, 2 (trang KPI tập thể), Mẫu 3, 4, 5 (trang KPI
  cá nhân), Mẫu 6, 7, 8 (trang Báo cáo). Bố cục theo các tệp mẫu (quốc hiệu, tiêu đề, ô gộp tiêu đề nhiều
  tầng, số hiệu cột, dòng trục/nhóm, dòng tổng, khối ký), Times New Roman, kẻ khung, A4 ngang (Mẫu 5 dọc),
  lặp dòng tiêu đề khi in. Quyền xuất như quyền xem: người duyệt không xuất được Mẫu 4, 5 khi chưa trình.
  Mẫu 3 theo tệp «6. Mau 1, Mau 3 (so, nganh).xlsx» (9 cột, cột «Cấp trình» để trống vì hệ thống chưa có
  trường này); Mẫu 1 theo bố cục 10 cột đang dùng trên màn hình.
- Lưu ý: tệp mẫu Mẫu 1, Mẫu 3 chia 3 nhóm nhiệm vụ (thường xuyên; đột xuất, phát sinh; trọng tâm, then chốt),
  hệ thống hiện có 2 nhóm (chưa có «đột xuất, phát sinh»).
