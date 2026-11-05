# Gold pilot — trạng thái và quy trình

Đã có **70 câu nháp từ nguồn** trong [gold.draft.jsonl](gold.draft.jsonl).
Chưa có `gold.jsonl` được người duyệt; không dùng draft làm kết quả benchmark đã
xác minh. LLM soạn nháp và kiểm trích đoạn; người duyệt vẫn cần kiểm tính đúng
ngữ nghĩa, phạm vi câu hỏi và rubric trên nguồn gốc.

## Thành phần

| Nhóm | Số câu | Nội dung |
|---|---:|---|
| Curated | 40 | 12 tra cứu số, 8 nhiều slot, 6 so sánh hai ngành chỉ định, 9 semantic, 1 mốc tầm nhìn, 4 điều kiện |
| Future-year | 12 | Hỏi thông tin 2026 ngoài phạm vi cẩm nang 2025 |
| Fanpage-unverified | 10 | Câu hỏi dựng từ DOCX 2026, không có nguồn chính thức tương ứng trong corpus |
| Noisy | 8 | Biến thể không dấu/viết tắt của câu curated, giữ nguyên fact family và rubric |

Bộ này có 42 `source_family`. Các câu curated dùng chung trang bằng chứng được
nhóm cùng family; các cặp so sánh nối các family liên quan. Số câu không phải số
quan sát độc lập. Nhóm fanpage năng khiếu và sư phạm cũng được gộp theo chủ đề.

## Phạm vi và giới hạn

Chỉ dùng text trích trực tiếp từ PDF cẩm nang 2025; loại trang 1, 2, 3, 107, 108.
Không sử dụng bảng 52 ngành, mã ngành, tổ hợp xét tuyển từ ảnh. Câu hỏi về một
chương trình được mô tả bằng text vẫn hợp lệ; câu so sánh chỉ giới hạn ở hai ngành
được gọi tên, không yêu cầu liệt kê toàn bộ danh mục.

Không gán thông tin trên fanpage là sai nếu chưa có nguồn chính thức đối chiếu.
Mười câu fanpage chỉ kiểm từ chối khi thiếu bằng chứng, **không đo khả năng xử lý
xung đột thẩm quyền** vì DOCX không được đưa vào index. Các con số/đáp án fanpage
không được chép vào câu hỏi để tránh đo hành vi lặp lại câu hỏi.

Text hiện có thiên về thời lượng đào tạo, tín chỉ, bằng cấp, nghề nghiệp. Các giá
trị 4/4,5 năm và 135/138/150 tín chỉ lặp nhiều. Chưa đủ đo đại diện học phí, điểm
chuẩn, lịch/điều kiện xét tuyển. Chỉ có bốn câu curated `risk=high` về điều kiện
ở trang 4 và 66; một noisy biến thể dùng cùng điều kiện trang 66. Không được suy
primary high-risk error trên bộ này thành độ an toàn tổng thể của chatbot.

Slots có subject/predicate/value/unit/year; synonyms là danh sách tương đương
được duyệt trước khi chạy. Đây là chấm tất định, vẫn có thể bỏ sót cách diễn đạt
đúng; không sửa rubric sau khi nhìn output rồi báo như run cũ. Bộ này không có
LLM judge. Source year 2025 được đưa vào header chunk; không suy năm từ câu hỏi.

## Duyệt và đóng băng

```bash
uv run python -m experiments.prepare_gold check
uv run python -m experiments.prepare_gold packet --render
```

Mở [hồ sơ duyệt](review/index.html), kiểm từng câu và ảnh PDF. Điền
[reviews.csv](review/reviews.csv): `decision=approve`, tên người duyệt,
`verified_at` theo ISO 8601 có múi giờ. Không đổi hash của item.

```bash
uv run python -m experiments.prepare_gold promote
uv run python -m pytest tests/test_gold_validity.py -q
```

Lệnh promote chỉ tạo gold khi mọi review khớp bản nháp và nguồn. Nó ghi thêm
`gold.review.json` với SHA-256 gold, nguồn và reviews, không tự tạo chữ ký người.
Commit/tag gold trước run đầu tiên. Gold thay đổi phải tạo phiên bản mới và chạy
lại tất cả arm. `packet` không ghi đè CSV đã tồn tại; lưu bản duyệt cũ, dùng
`--review-dir` mới nếu dựng lại bộ review.

Pilot được phép dùng để phát triển; **không tái dùng item hoặc biến thể của item
cho locked test**. Không dùng output B0–B3 làm nguồn tạo gold.

Hướng dẫn generator, preflight và thực nghiệm: [runbook](../../docs/RUNBOOK-server.md).
