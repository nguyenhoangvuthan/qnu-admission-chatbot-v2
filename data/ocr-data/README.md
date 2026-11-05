# Dữ liệu chuyển từ kết quả dự án cũ

Nguồn: `/home/kent/KentProject/qnu-admission-chatbot/results`.
Đích: `/home/kent/KentProject/qnu-admission-chatbot-v2/data/ocr-data`.

Đã kiểm kê 2.336 file. Bộ chính có **89 trang/ảnh, 11.918 dòng OCR, thuộc 24 tài liệu**. Bảng dữ liệu có **503 bản ghi điểm chuẩn/chỉ tiêu**. Đây là bản chuyển đổi dữ liệu đã có, không chạy lại OCR, không tự sửa nội dung hoặc xác nhận mọi con số là đúng.

## File dùng để bắt đầu

| File | Nội dung và cách dùng |
| --- | --- |
| `corpus.json` | Mảng 89 trang/ảnh đã chọn và bỏ trùng theo hash tài liệu + số trang. Dùng `text` để xử lý văn bản/chia chunk; giữ `source_document`, `source_document_sha256`, `page`, `source_file` để truy nguồn. |
| `corpus.csv` | Cùng 89 bản ghi, thuận tiện kiểm tra bằng Excel. |
| `documents.json` | Danh mục 24 tài liệu, các trang được xuất, đường dẫn nguồn khớp hash và file TXT tương ứng. |
| `text/*.txt` | Văn bản theo tài liệu, có dấu phân cách trang để đọc trực tiếp. Tên file dùng 16 ký tự đầu của hash; tên tài liệu có trong `documents.json`. |
| `tables/admission_records.json` và `.csv` | 503 bản ghi trích từ `data-inventory/d1/inventory.json`, giữ nguyên loại bảng, năm, đợt/loại chỉ tiêu, mã ngành, giá trị và văn bản nguồn. |

JSON dùng UTF-8; CSV dùng UTF-8 có BOM. Khi nhập CSV, đặt các cột mã ngành, văn bản và giá trị gốc thành Text để tránh tự đổi kiểu. Cột có cấu trúc danh sách/đối tượng được lưu dưới dạng chuỗi JSON trong CSV.

## Phạm vi và chất lượng

- Ưu tiên `cur_rotgate` theo quyết định lưu trong `results/preprocess-bench/m8/scores.json` và README M8. Chọn run1 khi cùng tài liệu/trang có nhiều lần chạy; đây là quy tắc chọn ổn định, không phải khẳng định run1 tốt hơn run2.
- 88 trang/ảnh lấy từ M8 `cur_rotgate`; một ảnh bảng Cẩm nang lấy từ M1 `paddle_vietocr` vì không nằm trong M8. Hai ảnh S3 cũng có ở S4 được gộp theo hash tài liệu/trang. Trang bảng Cẩm nang được ánh xạ về trang 2 dựa trên `ocr/p0-01/raw.json` và cùng ảnh nhúng mà `experiments/bench_ocr.py:prepare` dùng.
- Bỏ đầu ra lỗi thực thi, không có chữ, sinh chưa hoàn tất (`finish_reason=length`), hoặc ảnh S2 cố tình làm nhiễu. Không đưa đáp án chuẩn benchmark, câu trả lời LLM thử nghiệm, số đo hiệu năng hay log vào corpus.
- Ba trang có đầu ra rỗng ở cấu hình đã chọn được ghi trong danh sách kiểm kê: TB152 trang 3, TB4229 trang 4, TB1687 trang 4. Không tự kết luận đó là trang trắng, cũng không lấy chữ từ cấu hình khác để lấp vào.
- Chỉ xuất phần có trong kết quả. Ví dụ Cẩm nang chỉ có ảnh bảng trang 2, không phải toàn bộ tài liệu. `exported_pages` trong `documents.json` cho biết phạm vi chính xác.
- `quality_status=ocr_unverified` nghĩa là đã kiểm tra định dạng, nguồn và tính nguyên vẹn khi chuyển đổi; văn bản và số liệu OCR chưa được duyệt từng dòng. Cần đối chiếu bản gốc trước khi dùng các con số làm câu trả lời chính thức.
- `result` trong `corpus.json` giữ nguyên dữ liệu OCR gốc, bao gồm `lines`, `box`, rotation và thông tin lần chạy. Tọa độ của trang đã xoay thuộc ảnh sau xoay. Với các bản VLM trong thư mục reference, `coordinate_space=synthetic_line_order` cho biết box chỉ biểu diễn thứ tự dòng, không phải tọa độ nhận diện thật.

## Bảng điểm chuẩn/chỉ tiêu

Giữ nguyên `table`, `year`, `round`, `code`, `value`, `doc`. `round` có thể là đợt tuyển sinh hoặc trạng thái chỉ tiêu (dự kiến/chính thức/báo cáo/đăng ký), tùy `table`. Không gộp các giá trị chỉ dựa vào mã ngành.

`source_group_check` lưu kết quả kiểm tổng/số dòng có sẵn trong D1; thiếu check là `null`, không phải đã đạt. `method=null` vì bản xuất D1 không có trường phương thức. Không suy diễn phương thức từ điểm số. `quality_status=extracted_requires_context_review` nhắc giữ đủ ngữ cảnh trước khi đưa vào bảng nghiệp vụ. Dữ liệu 2023–2024 có phần được TB71 năm 2025 dẫn lại; chưa đối chiếu với văn bản gốc. Bản xuất này giữ nguyên năm lịch sử.

## Đối chiếu và rà soát

- `reference/ocr_candidates.jsonl`: 1.663 đầu ra OCR có chữ, đủ định dạng, kết thúc bình thường, trên ảnh không thuộc S2. Chứa nhiều engine/run và có thể có lỗi nhận dạng hoặc số bịa; chỉ dùng đối chiếu, không nạp đồng thời với corpus. Mỗi dòng giữ nguyên `result` và nguồn; chưa loại trùng giữa các engine.
- `review/handbook_rows.json` và `.csv`: 52 dòng ngành từ P0-01, kèm trạng thái cần rà soát. JSON còn có báo cáo validation gốc: tên ngành rỗng ở STT 42, mã lặp, các chênh lệch giữa engine và lỗi tổ hợp môn. Không đưa bảng này vào bộ dữ liệu nghiệp vụ đã xác minh.
- `audit/file_inventory.csv`: liệt kê toàn bộ 2.336 file đã quét, kích thước, SHA-256, trạng thái chọn/xuất/đối chiếu/bỏ qua và lý do. File báo cáo, manifest, log, notebook, SQLite kiểm toán và các kết quả đánh giá đã được phân loại; không coi chúng là nội dung tuyển sinh.
- `audit/source_metadata.json`: cấu hình OCR, kết quả chọn engine, kiểm tra D1 và validation P0 để truy lại căn cứ.
- `audit/summary.json`: số lượng và quy tắc xuất; `audit/verification.json`: kết quả đối chiếu dữ liệu sau khi xuất.

File `ocr_results.json` đã có từ lần xuất trước được giữ nguyên. File đó chứa cả dữ liệu lặp và S2; **bộ chính của lần này là `corpus.json`**. Chọn rõ file đầu vào, không nạp đệ quy tất cả JSON trong thư mục này.

## Tạo lại

```bash
python3 data/ocr-data/export_results.py
python3 data/ocr-data/verify_export.py
```

Chạy từ thư mục gốc dự án v2. Script chỉ đọc dự án cũ, ghi đè các file do nó tạo trong `ocr-data`; không thay đổi `ocr_results.json` đã có. Có thể dùng `--source /duong/dan/results --destination /duong/dan/xuat` để xuất sang thư mục khác. Các đường dẫn `source_locations` là vị trí cục bộ đã đối chiếu hash tại thời điểm xuất; khi chuyển máy, tra lại tài liệu theo hash.
