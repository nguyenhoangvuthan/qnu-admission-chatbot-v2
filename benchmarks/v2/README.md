# Gold v2 — bản nháp, chờ Kent duyệt

Bộ câu hỏi đánh giá cho các arm R, Q, G, M, S ([spec thực nghiệm paper v2](../../docs/superpowers/specs/2026-10-14-thuc-nghiem-paper-v2-design.md)),
trên snapshot kho `v2-2026-10-14` ([`snapshot.json`](snapshot.json), `uv run python -m experiments.snapshot_v2`). Mọi
file ở đây là **nháp do Claude soạn** (gold pilot do Codex soạn); số đo trên bản nháp là số phát triển, không
phải số báo cáo. Câu tự soạn báo cáo tách riêng với câu thật.

**Đợt duyệt 14/10/2026 — bắt đầu ở [`dot-duyet/index.html`](dot-duyet/index.html)** (lối vào hai hồ sơ dưới đây
và form tick cho quyết định D1–D8). `uv run python -m experiments.review_hub` dựng lại trang này.

**Duyệt đơn lượt 17/10/2026:** Nguyễn Hoàng Vũ Thân đã xem lại và xác nhận kết quả kiểm tra
106 câu: 88 đạt, 18 cần sửa. Giữ nguyên 20 quyết định đã duyệt trước đó; tổng 108 đạt,
18 cần sửa. Xem [nhận xét và hướng sửa](review/review-2026-10-17.md). Chưa `promote`.

**Rà soát lại 18/10/2026:** Codex kiểm lại 126 câu trên bản nháp không đổi: 99 câu chưa
phát hiện vấn đề cần sửa, **27 câu cần sửa** (18 cũ + 9 câu so sánh thiếu đợt tuyển sinh).
Đính chính lý do về slot và quan hệ điều kiện ở PIL-045. Xem
[báo cáo mới và bằng chứng](review/review-2026-10-18.md); phiếu rà soát mới lưu riêng,
giữ nguyên xác nhận lịch sử trong `review/reviews.csv`. Chưa sửa nháp/chưa `promote`.

**Rà nguồn và ý định, hoàn tất 19/10/2026:** đã xem lại cả 126 câu và tìm nguồn web QNU theo
nhóm rủi ro. Ngoài 27 vấn đề trên snapshot, **11 câu cần xử lý thêm về nguồn/hành vi**;
danh sách theo dõi gồm 38 câu, không phải 38 đáp án sai trên snapshot cũ. Xem
[báo cáo và bảng từng câu](review/source-intent-2026-10-19.md). Có phát hiện về nguồn điều kiện
giảng dạy, lịch/nội dung thi, bảng học phí dạng ảnh, KTX và học bổng. Nhãn từ chối của snapshot
không được dùng như kết luận thông tin không tồn tại trên web. Phiếu người duyệt vẫn giữ nguyên.

| File | Mục | Hồ sơ duyệt | Trạng thái |
|---|---:|---|---|
| `comparison.draft.jsonl` | 20 | `review/` | Người dùng đã duyệt 20/20; rà soát 18/10 phát hiện 9 câu cần sửa, 11 câu không có phát hiện mới |
| `core.draft.jsonl` | 106 | `review/` (chung) | Nguyễn Hoàng Vũ Thân xác nhận 17/10: 88 đạt, 18 cần sửa |
| `multiturn/dialogs.draft.jsonl` | 50 hội thoại | `multiturn/review/` | Nguyễn Hoàng Vũ Thân đã duyệt: 48 đạt, 2 cần sửa (`cla-04`, `loop-01`) |

## `core.draft.jsonl` — 106 câu

Sinh bằng `uv run python -m experiments.draft_gold_v2_core`; mỗi trích đoạn được kiểm với nguồn trước khi ghi.

| Mã | Câu | Nội dung |
|---|---:|---|
| `V2-PIL-001…070` trừ 041–062 | 48 | Gold pilot (Cẩm nang 2025) giữ nguyên nội dung, đổi mã, thêm `gold_evidence` |
| `V2-PIL-041…062` | 22 | Câu thử thách pilot gán lại theo snapshot: 15 nay trả lời được (TB1906, bảng ngưỡng 2026, TB141, TB1897), 7 vẫn phải từ chối. 4 câu viết lại câu hỏi (042, 047, 060 và ghi chú ở từng câu) |
| `V2-NEW-001…026` | 26 | Văn bản 2025–2026: lịch, lệ phí, phương thức, chỉ tiêu, ngưỡng, bổ sung 2026, học phí. Có bẫy năm, phiên bản, đợt (xem `review_note`) |
| `V2-ABS-001…004` | 4 | Phải từ chối: năm 2027, ngành không có, ký túc xá 2026-2027, giờ làm việc |
| `V2-NSY-001…006` | 6 | Không dấu/viết tắt của câu `V2-NEW` |

Câu phải từ chối toàn bộ gold v2: 11/126 (8,7%).

## `multiturn/dialogs.draft.jsonl` — 50 hội thoại

34 hội thoại nháp cũ (`benchmarks/multiturn/dialogs.jsonl`, chép nguyên) + 16 mới `v2-01…16`: "ngành này có học
bổng không" (ca thật SP34-K1VD), "ngành đó" qua một lượt cấp trường, sửa lại ngành, năm tương đối ("năm trước"),
mã ngành, câu không dấu nối tiếp. Kiểm và dựng hồ sơ: `uv run python -m experiments.prepare_dialogs check|packet`.

## `comparison.draft.jsonl` — 20 câu so sánh / nhiều thực thể

**Đã duyệt 14/10/2026:** 20/20 `approve` (Nguyễn Hoàng Vũ Thân, `review/reviews.csv`); chưa `promote` (xem
mục Duyệt, bước 5).

**Phát hiện sau duyệt, 18/10:** CMP-010–016, CMP-018 và CMP-020 cần làm rõ đợt tuyển sinh;
CMP-015/CMP-020 còn thiếu phương thức THPT. Phiếu 14/10 là lịch sử; danh sách vấn đề hiện tại
ở [báo cáo rà soát lại](review/review-2026-10-18.md).

Sinh bằng `uv run python -m experiments.draft_gold_v2_comparison`. Số liệu và trích đoạn lấy thẳng từ lớp text
PDF, chênh lệch tính bằng `Decimal`; chạy lại cho đúng cùng file (sha256 `5ebcd997fed4…`).

| Nhóm | Câu | Nguồn | Dùng cho |
|---|---|---|---|
| Hai ngành, chương trình đào tạo | 001–006 | Cẩm nang 2025 | R5 với R8 |
| Ba ngành | 007–008 | Cẩm nang 2025 | R8 (top-k chia cho ba ngành) |
| Hai ngành, điểm chuẩn cùng năm | 009–012 | TB153 (2025) hoặc TB141 (2026) | Q, R8 |
| Một ngành, hai năm | 013–016 | TB153 + TB141 | Lọc năm (R5), Q |
| Một ngành, hai loại văn bản | 017–018 | Cẩm nang + TB153/TB141 | Định tuyến (S3): một phần SQL, một phần văn bản |
| Không dấu / viết tắt | 019–020 | Biến thể của 009, 013 | Câu không dấu |

Không trùng cặp ngành với PIL-021…026 của gold pilot.

## Người duyệt cần xem

1. **Điểm 2026 lấy từ cột "Điểm chuẩn quy đổi (Điểm THPT)"** trong các bảng ĐGNL/học bạ của PDF TB141. Bảng
   THPT gốc chỉ có dạng ảnh; M5 đã đối chiếu 56/56 dòng khớp ảnh. Câu hỏi nói "điểm thi THPT".
2. **Điểm 2025 lấy từ TB153 mục I**, không lấy TB152 (đã bị thay, đổi chỗ CNTT với Trí tuệ nhân tạo).
3. **V2-CMP-016 Khoa học dữ liệu:** TB153/TB141 ghi mã `7460108`, Cẩm nang 2025 ghi `7480109`.
4. **Câu chương trình đào tạo không nêu năm** (001–008), vì học sinh ít khi nêu. Đáp án theo Cẩm nang 2025;
   nếu kho có văn bản năm khác ghi khác thì câu cần sửa.
5. **Slot chênh lệch nhỏ** ("2", "3" điểm/tín chỉ) dễ khớp nhầm khi chấm bằng chuỗi; bộ chấm v2 cần khớp
   kèm đơn vị.

## Khác schema pilot

- `gold_evidence`: danh sách `[nguồn, trang]` (PDF) hoặc `[nguồn, dòng]` (HTML/DOCX, dòng 0-based theo
  `html_lines`/`docx_lines`, gồm cả dòng bảng DOCX). `gold_page_ids` của pilot giả định một PDF nên mơ hồ khi câu
  dùng nhiều văn bản; bộ chấm truy hồi v2 dùng `gold_evidence`.
- `review_note`: điều người duyệt cần xem riêng cho câu đó.
- `prepare_gold --profile v2` bỏ hai luật riêng của pilot (trang loại trừ của Cẩm nang, tỷ lệ 40/22/8) và kiểm
  thêm: câu trả lời được phải có `gold_evidence`, mỗi cặp phải có trích đoạn, `gold_page_ids` khớp trang của
  `gold_evidence`.

## Duyệt

```bash
uv run python -m experiments.prepare_gold packet --profile v2 --render --refresh-pending
```

1. Mở [hồ sơ duyệt](review/index.html) bằng trình duyệt. Mỗi câu có câu trả lời mẫu, ghi chú "Cần xem" (nếu
   có), slot và `gold_evidence`, ảnh trang gốc với dòng trích đoạn **tô vàng** (trích cả trang của gold pilot
   chỉ tô dòng chứa giá trị mong đợi; một ảnh gộp phần tô của mọi câu dẫn tới trang đó). Bằng chứng HTML/DOCX
   hiện theo dòng, không có ảnh.
2. Nhập tên ở thanh trên cùng, rồi tick **Đạt** hoặc **Cần sửa** ở cuối mỗi câu (Cần sửa thì ghi lý do).
   Tick là tự điền tên và giờ có múi giờ (`2026-10-14T11:26:47+07:00`); bỏ tick là về `pending`. Tiến độ
   được giữ trong trình duyệt khi tải lại trang, nhưng chỉ ở trình duyệt đó.
3. Bấm **Xuất reviews.csv**, rồi chép file tải về đè lên [reviews.csv](review/reviews.csv). Hồ sơ dựng lại
   bằng `packet` sẽ hiện lại các quyết định đã có trong `reviews.csv`.
4. Sửa bản nháp sau khi đã có `reviews.csv` thì chạy lại `packet --profile v2 --refresh-pending`: dòng còn
   `pending` được cập nhật hash, dòng đã duyệt giữ nguyên và `promote` sẽ từ chối nếu hash đã cũ.
5. **Chưa `promote`** cho tới khi gold v2 đủ các phần còn lại (câu mô tả, không trả lời được, nhiều lượt):
   `promote` đóng băng `benchmarks/v2/gold.jsonl` và không cho ghi đè.
