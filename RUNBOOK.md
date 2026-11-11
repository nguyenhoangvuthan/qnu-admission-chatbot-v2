# Chạy dự án từ đầu

> **Cập nhật:** 06/11/2026. Hạn duy nhất: nộp đề án **12/04/2027**.

File này gộp mọi thứ cần để đi từ máy trống tới bảng kết quả của đề án và chatbot chạy thật. Chạy các lệnh từ thư mục gốc
repo, theo thứ tự ở mục 0.

Mỗi mục có một nhãn:

- **Chạy được:** code đã có trong repo này.
- **Chưa có code:** việc phải làm trước. Lệnh ghi trong mục đó là lệnh dự kiến, gõ bây giờ sẽ lỗi. Đường dẫn trong mục là nơi
  code sẽ nằm, theo [cấu trúc thư mục](docs/architecture/folder-structure.md).

Lệnh viết cho bash. File `.sh` gọi thẳng được từ fish; lệnh có `set -a; source .env` thì gõ `bash` trước.

**Từ dùng trong file này:**

| Từ | Nghĩa |
|---|---|
| Bộ câu hỏi chấm điểm | Câu hỏi kèm đáp án đúng do người duyệt, dùng để chấm chatbot. Phiên bản 2 nằm ở `benchmarks/v2/` |
| Kho web | Trang và file quét từ `*.qnu.edu.vn`, nằm ở `data/web/` |
| Snapshot đề án | Bản dữ liệu chốt cứng để mọi số liệu trong đề án chạy trên cùng một nguồn |
| Cấu hình thí nghiệm | Một tổ hợp cách truy hồi và cách trả lời được đem đo; có mã như R5, G1 |
| Baseline | Cấu hình thắng sau khi đo, dùng cho chatbot thật |
| RAG | Tìm đoạn văn liên quan rồi cho model viết câu trả lời từ các đoạn đó |
| OCR | Đọc chữ từ ảnh hoặc bản scan |

## 0. Bản đồ

| Mục | Việc | Trạng thái | GPU | Dùng mạng | Thời gian máy |
|---|---|---|---|---|---|
| 2 | Dựng máy | Chạy được | Không | **Nhiều**, khoảng 15–20 GB, chỉ lần đầu | Phần lớn là tải model và thư viện |
| 3 | Chạy thử pipeline với vLLM | Chạy được | Có | Không | Vài phút |
| 4.1 | **Quét kho web, làm đầu tiên** | Chạy được | Không | **Vừa**, đo được khoảng 300 MB mỗi lần | Đo được khoảng 4 phút |
| 4.2 | Xét trang không có ngày đăng | Chạy được | Không | Không | Vài giây |
| 4.3 | Kent duyệt danh sách trang của snapshot đề án | Chờ Kent | Không | Không | Việc người làm, 71 trang |
| 5 | Bảy bảng số, snapshot đề án | Chưa có code | Có (embedding) | Không | 10–30 phút |
| 6 | Bộ câu hỏi chấm điểm phiên bản 2 | Công cụ chạy được, nội dung chưa sửa | Không | Không | Việc người làm |
| 7 | Công cụ chấm | Phần A chạy được | Có, chế độ `full` | Không | `retrieval` vài phút; `full` 10–50 phút |
| 8 | Router, SQL, cổng từ chối | Chưa có code | Không | Không | — |
| 9 | Chạy 17 cấu hình thí nghiệm, chọn baseline | Chưa chạy được | Có | **Nhiều**, khoảng 3,4 GB model, chỉ lần đầu | 2–4 giờ |
| 10 | Chuyển web app, bàn giao, nghiệm thu live | Chưa có code | Có | **Vừa**, thư viện giao diện, chỉ lần đầu | 1–2 giờ |
| 11.1 | Model hiểu câu | Chưa có code | Có | Không | Nhiều giờ |
| 11.2 | Xoá ảnh người trong `quarantine/` | Chưa có code | Có | **Nhiều**, model đọc ảnh vài GB, chỉ lần đầu | Khoảng 0,8 giây/ảnh |
| 11.3 | Lọc chủ đề kho web bằng model | Chạy được | Có, nếu dùng model | Không | Khoảng 2 phút chạy model; Kent gán nhãn 95 mục |
| 11.4 | OCR ảnh web | Chạy được | Có | **Nhiều**, môi trường OCR 12 GB, chỉ lần đầu | Khoảng 2,2 giây/trang; kho hiện tại 5 phút |
| 11.5 | Giao diện | Chưa có code | Không | Ít | — |
| 12 | Mở cho người dùng thật | Chưa có code, chờ trường | Có | **Vừa**, quét định kỳ mỗi ngày | — |

**Mức dùng mạng:** Không; Ít (dưới 100 MB); Vừa (100 MB tới 2 GB); Nhiều (trên 2 GB). Số của mục 4.1 là số đo ngày 06/11/2026.
Các số còn lại là ước lượng từ dung lượng model và thư viện đã có trên máy. Mục ghi "chỉ lần đầu" thì lần sau không tải nữa.
Mục ghi Nhiều thì không nên chạy trên mạng di động.

**Thứ tự làm:**

1. Quét kho web (4.1).
2. Làm song song: công cụ chấm (7), sửa bộ câu hỏi chấm điểm (6), xét trang không có ngày đăng (4.2), Kent duyệt danh sách
   trang (4.3).
3. Bảy bảng số (5), Kent duyệt dòng OCR.
4. Router, SQL, cổng từ chối (8).
5. Cổng dữ liệu đạt (mục 5), khoá dữ liệu, chạy baseline (9).
6. Bàn giao (10).
7. Sau baseline: phần còn lại của mục 11.

Giao diện không vướng logic (11.5) làm lúc nào cũng được.

Tình trạng máy này khi kiểm 06/11/2026: có `.venv`, `environments/vllm/.venv`, `Qwen3-4B-AWQ` và `bge-m3`. Chưa có
database, web app, giao diện, router SQL, công cụ chấm. Kho web đã có ở `data/web/`, OCR xong
(mục 11.4), `quarantine/` trống. `environments/ocr` đã dựng.
Test đạt (11/11/2026): 1080 passed, 7 skipped; ruff sạch trên `src tests experiments apps`; 4/4 contract import giữ.

**Luật GPU:** laptop chỉ có 6 GB, mỗi lúc một việc dùng GPU. vLLM chiếm GPU, nên embedding GPU và OCR phải chạy khi vLLM đã tắt.

**Theo dõi tiến độ:**

| Lệnh | Hiện gì |
|---|---|
| `scripts/quet-web.sh` | Số mục đã xử lý trên tổng đã thấy, trang mới, file mới, lỗi. Tổng tăng dần khi gặp link mới |
| `scripts/quet-web.sh log` | Như trên cho lần quét nền, một dòng mỗi 30 giây |
| `scripts/thuc-nghiem-live.sh` | Trạng thái khởi động vLLM mỗi 30 giây, rồi kết quả từng câu |

Log ghi vào `artifacts/logs/crawler.log`.

## 1. Hệ thống đích

Chatbot tư vấn tuyển sinh tiếng Việt của Trường Đại học Quy Nhơn dựa trên RAG, tự host trên GPU 6 GB. Đề án so RAG chuẩn
với RAG có lọc ngành và năm, có cổng từ chối tất định, và định tuyến một nhóm hẹp câu số liệu sang bảng SQL. Thước đo
chính là tỷ lệ trả sai mà vẫn tự tin trên toàn bộ câu hỏi (`decision-critical error rate`), báo cùng tỷ lệ đúng và
tỷ lệ câu được trả lời (`coverage`). Baseline chính là RAG chuẩn.

| Thành phần | Giá trị |
|---|---|
| Generator | `Qwen/Qwen3-4B-AWQ`, revision `74d4bd2bd4bff9cafc9345221320bffb08b406a3`; model duy nhất |
| Embedding | `BAAI/bge-m3`, revision `5617a9f61b028005a4858fdac845db406aefb181` |
| Serve | vLLM 0.33.0 trong `environments/vllm`, `max-model-len` 8192, chỉ nghe 127.0.0.1 |
| Cố định ở mọi cấu hình thí nghiệm | top-k 5, temperature 0, seed 42, `max_tokens` 2048 (4096 nếu đo đạt), cùng prompt và JSON schema |
| Database (chưa có) | PostgreSQL 18 + pgvector 0.8.7 trong Docker, cấu hình ở `infra/` |
| Giao diện (chưa có) | React trong `apps/web/`, FastAPI trong `apps/api/` phục vụ tại `/app/` |
| Máy chạy số chính thức | Laptop RTX 4050 6 GB |

**Phân vai:**

| | SQL | RAG |
|---|---|---|
| Loại câu | Điểm chuẩn, chỉ tiêu, tổ hợp, ngưỡng đầu vào, học phí, ký túc xá | Ngành học gì, việc làm, chương trình đào tạo, thủ tục, học bổng, đời sống sinh viên; số tín chỉ |
| Nguồn | Bảy bảng, mỗi dòng có `source_id`, trang, trạng thái duyệt | Cẩm nang, đề án, trang giới thiệu ngành trên web trường |
| Không có dữ liệu | Từ chối, không lùi về RAG | Từ chối |

Câu dạng "em X điểm có đậu không" luôn nhận đúng một câu cố định: *"Tôi không thể trả lời câu hỏi này vì không dự đoán
được kết quả trúng tuyển."*

**Mặc định khi câu hỏi thiếu thông tin:**

| Tình huống | Xử lý |
|---|---|
| Hỏi điểm chuẩn không nêu đợt | Mặc định đợt 1, nói rõ, nhắc có đợt bổ sung |
| Chỉ tiêu có nhiều phiên bản | Theo văn bản trường công bố cho thí sinh, nêu tên và ngày văn bản. Năm 2025: Thông báo 112 cho sư phạm, Thông báo 71 cho ngành khác. Năm 2026: Thông báo 1906 |
| Hỏi điểm không nêu phương thức | Hỏi lại người dùng |

**Bất biến của code:**

- `qnuchat.core` không import `qnuchat.adapters`, `qnuchat.ingest`, `qnuchat.eval` hay `apps`.
- Bộ câu hỏi chấm điểm, nhãn, rubric không vào core.
- Lỗi hạ tầng (timeout, JSON hỏng) là execution error, không thành từ chối.
- Bước dựng dữ liệu không áp chính sách đang đem đo; mọi chính sách chạy lúc truy vấn.
- Prompt lắp từ mảnh theo cờ; hướng dẫn tự từ chối giống nhau ở mọi cấu hình thí nghiệm.
- Bộ đọc kết quả từ chối lần chạy có môi trường hoặc hash lệch.

## 2. Dựng máy — chạy được

Cần có sẵn: `uv`, driver NVIDIA. Docker và Node chỉ cần từ mục 10.

```bash
uv sync                                     # .venv: lõi, công cụ kiểm tra, quét web
uv run hf download BAAI/bge-m3 --revision 5617a9f61b028005a4858fdac845db406aefb181
uv run hf download Qwen/Qwen3-4B-AWQ --revision 74d4bd2bd4bff9cafc9345221320bffb08b406a3
uv sync --locked --project environments/vllm   # vLLM riêng, khoảng 9 GB
uv run pytest -q
```

`scripts/serve-vllm.sh` đặt `HF_HUB_OFFLINE=1`, nên model phải tải xong trước khi serve.

**`.env`:**

| Khoá | Dùng cho |
|---|---|
| `QNUCHAT_CRAWL_CONTACT_EMAIL` | Quét web, gửi trong User-Agent để site trường biết ai đang quét |
| `QNUCHAT_CONTACT_PHONE`, `_EMAIL`, `_WEBSITE` | Khung từ chối, dùng từ khi có web app (mục 10) |

```bash
printf "QNUCHAT_CRAWL_CONTACT_EMAIL='<email liên hệ>'\n" >> .env
```

Không ghi liên hệ hay mật khẩu vào file được commit.

## 3. Chạy thử pipeline với vLLM — chạy được

Bản hiện tại trả lời từ **Cẩm nang 2025**, cấu hình `configs/pipeline/b3-qwen3-4b-awq.yaml`, chưa dùng kho web, bảng số hay
router. Chưa có web app, nên chạy qua script thực nghiệm. Chất lượng chưa đo, không trích số từ bản này.

```bash
./scripts/thuc-nghiem-live.sh 20     # 20 câu; tự bật vLLM, xong tự tắt, server đã chạy thì dùng lại
```

Kết quả ở `artifacts/runs/live-<thời gian>/`: `report.md`, `rows.jsonl`, `run.log`, `vllm.log`. Chỉ cần bật vLLM thì chạy
`./scripts/serve-vllm.sh` và giữ terminal mở, Ctrl-C để tắt.

Embedding chạy trên CPU (`EMBEDDING_DEVICE=cpu`) vì bge-m3 không nằm chung được với vLLM trên 6 GB. Không mở cổng 8000 ra mạng,
vì vLLM không có API key.

## 4. Kho web

Chỉ giữ dữ liệu từ 01/01/2024 (`min_year: 2024`). Mốc này chỉ áp cho dữ liệu quét web, không áp cho tài liệu bàn giao trong
`data/`. Chỉ lấy thông tin tuyển sinh đại học chính quy, học phí, miễn giảm, học bổng, ký túc xá và trang giới thiệu ngành:
`topic_gate` trong `configs/crawl/qnu.yaml` lọc theo URL và tiêu đề ngay lúc quét, nên không tải phần ngoài chủ đề. Ảnh chỉ lấy
từ trang bài, không lấy từ trang chuyên mục.

### 4.1. Quét — chạy được

Không cần GPU, không cần database, nên chạy song song với việc khác được. Cần `QNUCHAT_CRAWL_CONTACT_EMAIL` (mục 2).

```bash
./scripts/quet-web.sh check     # chỉ kiểm điều kiện: email, crawler khác, ổ đĩa, kết nối
./scripts/quet-web.sh           # quét trong terminal này, có thanh tiến độ
./scripts/quet-web.sh start     # hoặc quét nền, đóng terminal vẫn chạy
./scripts/quet-web.sh log       # xem lần quét nền; Ctrl-C chỉ thôi xem
./scripts/quet-web.sh stop      # dừng lần quét nền
./scripts/quet-web.sh status    # các lần quét gần nhất, lượng tải, dung lượng kho
./scripts/quet-web.sh prune     # áp lại min_year và danh sách chặn lên kho, xoá blob đã rút
```

- **Số đo 06/11/2026:** 484 mục, 572 request, 300 MB tải, 4 phút 16 giây; kho sau quét 257 MB, 318 file.
  Crawler tải 1 yêu cầu/giây/host, 4 host song song. Số này đo trước lần siết `topic_gate` cuối cùng cùng ngày, và thay đổi theo `topic_gate`.
- **Dừng giữa chừng được.** Ctrl-C hay `stop` lưu `last_checked.json` và `frontier.jsonl`, thoát mã 130; chạy lại thì làm tiếp.
- **Quét lại:** mục đã có chỉ kiểm lại sau 30 ngày (`recheck_days`), nên lần sau tải ít hơn.
- **Script từ chối chạy** khi đang có crawler khác trên máy, vì site trường sẽ nhận gấp đôi tải.
- **Mã thoát:** 0 xong, 1 lỗi (xem `status`), 2 thiếu biến môi trường, 3 đang có lần quét khác, 130 bị dừng.
- **Log lần quét** ở `data/web/crawl_runs.jsonl` và `data/web/fetch_log/`, không cần database.
- `data/web/` không commit, kể cả `people.jsonl`: ghi chú trong sổ có tên người thật, mà repo này public. File chờ OCR nằm ở `data/web/quarantine/`.
- Đổi `min_year` hay danh sách chặn thì chạy `prune`, rồi quét, rồi `prune` lại.
- **Đổi `topic_gate` thì xoá `data/web/frontier.jsonl` và `data/web/last_checked.json` trước khi quét:** hàng đợi cũ đi vòng qua
  cổng mới.

### 4.2. Xét trang không có ngày đăng — chạy được

```bash
uv run python -m apps.cli.crawl undated     # ghi undated.csv và undated.html ở artifacts/knowledge_base/, không sửa kho
./scripts/quet-web.sh prune                 # rút trang chỉ hiện hành trước mốc, trừ trang được miễn
```

CSV có cột `url`, `title`, `exempt` (hạt giống, tầng A, hub: `prune` không bao giờ rút), `decision` (`keep`, `remove`,
`review`), `year`, `evidence` (các cụm đã dùng để quyết). Trang được miễn vẫn mang `decision` của nó: miễn chỉ giữ trang
trong kho để crawler đi tiếp tới bài mới, không cho trang vào snapshot (xem 4.3). Luật chỉ áp cho trang không suy được năm:

1. Có ngày đăng, hoặc năm trong URL hay tiêu đề, thì quyết theo đó.
2. Không suy được thì đọc phần nội dung chính, bỏ menu, cột bên, link, URL và giá trị mặc định của template. Thẻ
   `<time>01/01/2024</time>` ở cột bên trang ngành là giá trị mặc định, không phải ngày đăng.
3. Thời điểm hiện hành lấy từ chữ: năm tuyển sinh, năm học, khoá áp dụng, "áp dụng từ", "có hiệu lực từ". Năm của văn bản
   được dẫn không tính.
4. Hiện hành từ 01/01/2024 thì giữ và ghi năm đó. Chỉ hiện hành trước mốc thì xoá.
5. Không có dấu hiệu thì không tự giữ, không tự xoá: đưa vào danh sách Kent duyệt.

Cách code đọc dấu hiệu (`qnuchat.ingest.dating.date_from_body`):

- Chỉ tin năm đi kèm cụm chỉ thời điểm: "năm học", "năm tuyển sinh", "áp dụng cho khoá", "tuyển sinh / xét tuyển / điểm
  chuẩn / chỉ tiêu / học phí / đại học / THPT … năm X". Năm đứng một mình là nhiễu: menu lọt vào nội dung ("KIỂM ĐỊNH CTĐT
  NGÀNH LUẬT 2025" ở 5 trang khoa), chân trang, ngày của template, câu kể lịch sử.
- "Từ năm học X", "áp dụng từ", "có hiệu lực từ" là hiện hành **từ** X trở đi. X trước mốc thì không tự xoá mà đưa vào
  danh sách duyệt, vì quy định có thể vẫn hiệu lực (ký túc xá: "Từ năm học 2020-2021, nhà trường sẽ trang bị…").
- Bỏ năm có "ban hành", "quyết định", "thông tư", "nghị định", "công văn", "căn cứ", "số …" ngay trước.
- Giới hạn đã thấy: "Đại học Limoges, Pháp – năm 2020" bị đọc là năm của trang (trang đó được miễn nên không bị rút).

**Số đo 10/11/2026 trên kho 464 mục:** 101 trang không có ngày đăng; giữ 19, chỉ hiện hành trước 2024 có 11 (cả 11 được
miễn nên `prune` không rút trang nào, nhưng cả 11 không vào snapshot), cần duyệt 71, gồm cả 54 trang ngành tuyensinh: chữ
trang ngành không có dấu hiệu thời điểm. Phần lớn 11 trang là chuyên mục tuyển sinh của khoa: chữ là danh sách tiêu đề bài
cũ ("TUYỂN SINH ĐẠI HỌC QUY NHƠN NĂM 2021").

### 4.3. Kent duyệt danh sách trang của snapshot đề án

Làm sau 4.2, vì danh sách cần duyệt sinh ra từ luật đó. Mở `artifacts/knowledge_base/undated.html` trong trình duyệt: mỗi
trang có chữ đã bỏ rác template, menu gập lại, dấu hiệu năm tô vàng. Chọn **Đưa vào snapshot** hoặc **Không đưa vào** cho 71
trang "cần duyệt", rồi bấm **Xuất undated-review.csv** (cột `url`, `sha256`, `exempt`, `auto_decision`, `label`, `note`,
`reviewer`, `at`). Lựa chọn lưu theo từng trình duyệt; sang trình duyệt hay máy khác thì bấm **Nhập file đã xuất** để làm tiếp.
Không duyệt trong cửa sổ trình duyệt do Playwright điều khiển: file tải về rơi vào `.playwright-mcp/`, không vào `~/Downloads`.

**Đã duyệt 10/11/2026:** `artifacts/knowledge_base/undated-review.csv`, 69 trang: 63 đưa vào, 6 không.

| Nhóm | Xử lý |
|---|---|
| Trang ngành `tuyensinh.qnu.edu.vn/vi/tong-hop-nganh-dao-tao/` | Đưa vào. **Nguồn ưu tiên đầu tiên** cho thông tin và chương trình đào tạo các ngành: có ở đây thì dùng trước trang khoa (Kent 10/11/2026). Trả lời kèm link trang |
| PDF CTĐT link từ thân trang ngành tuyensinh (34 file, 2022–2023) | Đưa vào dù trước 2024 (`attachments_always_from`). Trả lời ghi năm của CTĐT và dẫn URL file (Kent 10/11/2026) |
| Trang khoa giới thiệu ngành, chương trình đào tạo | Đưa vào, gắn năm đăng, chỉ từ 01/01/2024 |
| PDF CTĐT khác, mọi tài liệu trước 01/01/2024 | Không đưa vào |
| Trang được miễn (`exempt = yes`) có `decision = remove` | Giữ trong kho, không đưa vào snapshot (Kent chốt 10/11/2026) |
| Trang được miễn có `decision = review` | Kent duyệt như trang thường; quyết định chỉ áp cho snapshot, `prune` vẫn không rút |

**Luật trả lời rút từ ghi chú duyệt** (cho mục 5 và 8, chưa có code):

- Trang không có ngày đăng mà các trang con có ngày dưới tiêu đề (`pdt…/tuyen-sinh-*`, `ns…/nganh-dao-tao-1103`, trang ngành
  kgdctqlnn): năm của trang lấy theo ngày dưới tiêu đề của trang con.
- Trang đưa vào mà không có thời gian (`kktcn…/gioi-thieu-nganh-ky-thuat-dien-1`, `math…/nganh-su-pham-toan-hoc`): trả lời
  kèm link trang và câu "Để có thêm thông tin chi tiết cho năm nay bạn hãy liên hệ với phòng đào tạo nhé".
- Trang ngành tuyensinh và trang ký túc xá: trả lời kèm link trang.

Trang được miễn có hai vai: đường để crawler tìm bài mới, và nội dung để chatbot trích. Miễn `prune` chỉ giữ vai thứ nhất.
Chữ của trang chuyên mục thường là tiêu đề bài cũ, nên cho vào snapshot thì chatbot có thể trả lời bằng tin năm 2021.

## 5. Bảng số và snapshot đề án — chưa có code

Snapshot đề án gồm: file bàn giao trong `data/` (trừ `kind: faq_seed`), kết quả OCR trong `data/ocr-data/`, bảy bảng số, nhóm
trang web ở 4.3.

**Cần viết:** database và lịch sử migration trong `migrations/` (schema `knowledge_base`, bảy bảng số), màn duyệt trong trang
quản trị, `corpus.snapshot` cho pipeline, retriever PostgreSQL trong `src/qnuchat/adapters/storage/`.

**Bảy bảng:** `nganh`, `diem_chuan`, `chi_tieu`, `to_hop`, `nguong_dau_vao`, `hoc_phi`, `ky_tuc_xa`. Mọi bảng có
`snapshot_id`, `source_id`, `page`, `extraction`, `raw`, `review_status`. Hai văn bản ghi hai con số khác nhau thì giữ cả
hai; văn bản nào hiệu lực là nhãn `superseded_by`, chọn lúc truy vấn. Tiền chuẩn hoá về số nguyên đồng. Mã ngành có hậu
tố giữ nguyên chuỗi.

**Trích bảng từ PDF phải kiểm lại trước khi dùng.** Sau khi nâng PyMuPDF từ 1.28 lên 2.1, chữ trang giữ nguyên trên cả 269 trang
PDF, nhưng `find_tables` cho kết quả khác trên 130 trang. Chưa rõ bản mới tốt hơn hay kém hơn. Kiểm bằng số tổng ở cổng dữ liệu
trước khi tin bảng trích ra.

**OCR không chạy lại:** dùng thẳng `data/ocr-data/corpus.json` (89 trang và ảnh, 24 tài liệu; xem
[data/ocr-data/README.md](data/ocr-data/README.md)), kiểm hash với `documents.json`. Trường `quality_status` đang là
`ocr_unverified`: chữ chưa duyệt từng dòng. Dòng từ OCR bắt đầu ở `pending` và Kent duyệt; dòng từ lớp chữ hoặc HTML qua kiểm
tự động là `auto_checked`.

Lệnh dự kiến:

```bash
uv run python -m apps.cli.knowledge_base build --sources <cấu hình>
uv run python -m apps.cli.knowledge_base publish <id>
uv run python -m apps.cli.knowledge_base status
```

`publish` chỉ thành công khi không còn dòng `pending`, kiểm số tổng đạt, mọi chunk có vector đúng chiều và `content_hash`
khớp.

**Cổng dữ liệu, phải đạt trước khi khoá:** bảy bảng có dữ liệu 2025 và 2026 (2024: phần đã có); mọi dòng có nguồn, trang và
qua kiểm số tổng; dòng OCR đã duyệt; mặc định đợt, phiên bản, phương thức đã chốt (mục 1); bộ câu hỏi chấm điểm phiên bản 2
đã duyệt.

**Dữ liệu còn xin:**

| Câu hỏi | Ai trả lời | Ảnh hưởng |
|---|---|---|
| Kế toán lệch 30 chỉ tiêu ở cả 2025 và 2026: Thông báo 1897 có gộp ACCA không? | Trường | `chi_tieu` |
| Ngưỡng đầu vào 2024 | Trường | `nguong_dau_vao` |
| Bản gốc có ký của Thông báo 1906, 121, 1886 (chỉ có trên eoffice) | Trường | Thay bản HTML, DOCX chép tay |
| Giáo dục Mầm non, Giáo dục Thể chất 2026 có xét điểm đánh giá năng lực Sư phạm Hà Nội không? Thông báo 1906 ghi chỉ phương thức 5 | Trường | `diem_chuan`, `nguong_dau_vao` |
| Điểm 2023 ở Đề án 2024 lệch Thông báo 71 ở Sư phạm Toán, Sư phạm Lịch sử – Địa lý, Công nghệ kỹ thuật ô tô | Trường | `diem_chuan` 2023 |
| Bảng học bạ, đánh giá năng lực của Thông báo 158 mục II và Thông báo 151 mục II | Kent tải lại hoặc trường | `diem_chuan` 2026 bổ sung |
| Điểm chuẩn 2024 bản gốc (Thông báo 90, link Drive đã hỏng); xác nhận thứ bậc nguồn | Giáo viên hướng dẫn | `diem_chuan` 2024 |

## 6. Bộ câu hỏi chấm điểm phiên bản 2 — công cụ chạy được, nội dung chưa sửa

Hiện có nháp `benchmarks/v2/core.draft.jsonl` (106 câu), `comparison.draft.jsonl` (20 câu),
`multiturn/dialogs.draft.jsonl` (50 hội thoại). Đích khoảng 160 câu.

**Việc phải làm trên nháp:**

- Sửa chín câu so sánh thiếu đợt: ghi "đợt 1", thêm "xét điểm thi THPT" ở CMP-015 và CMP-020, đáp án kiểm chiều tăng/giảm.
- Soạn bản sửa 18 câu ở [rà soát 18/10](benchmarks/v2/review/review-2026-10-18.md), 11 câu ở
  [rà soát nguồn 19/10](benchmarks/v2/review/source-intent-2026-10-19.md), hai hội thoại `cla-04`, `loop-01`.
- Thêm khoảng 20 câu phải từ chối, câu dạng "có đậu không", câu mô tả hỏi vào trang ngành.
- Gắn mỗi câu thuộc SQL hay RAG. Khai trước tỷ lệ câu số.
- Một sinh viên không đọc code soạn ít nhất 30 câu, không biết có khuôn SQL nào. Chưa có người cụ thể.

```bash
uv run python -m experiments.prepare_gold check --profile v2       # đã kiểm 06/11/2026: 126 câu đạt
uv run python -m experiments.prepare_dialogs check                 # đã kiểm 06/11/2026: 50 hội thoại đạt
uv run python -m experiments.prepare_gold packet --profile v2 --render --refresh-pending
uv run python -m experiments.prepare_dialogs packet
```

Mở `benchmarks/v2/review/index.html`, nhập tên, tick **Đạt** hoặc **Cần sửa** từng câu, bấm **Xuất reviews.csv**, chép đè lên
`benchmarks/v2/review/reviews.csv`. Tiến độ chỉ lưu trong trình duyệt đó.

Sau khi đã có snapshot đề án thì rà lại nhãn trên snapshot đó, rồi đóng băng:

```bash
uv run python -m experiments.prepare_gold promote --profile v2     # ghi gold.jsonl, không cho ghi đè
```

## 7. Công cụ chấm — phần A chạy được

Thiết kế: [spec phần A](docs/superpowers/specs/2026-11-10-eval-phan-a-design.md). Đã có trong `src/qnuchat/eval/`: schema
và đọc bộ câu hỏi, chọn câu theo nguồn trong kho (`cases`), nhóm kết quả (`outcome`), runner chạy một cấu hình qua pipeline
(`runner`), chấm và báo cáo có Wilson 95% (`score`), metric truy hồi theo cặp nguồn và trang, từ chối, so khớp giá trị,
thống kê. Lệnh ở `apps/cli/evaluate.py`:

```bash
# Chỉ truy hồi, không cần vLLM
uv run python -m apps.cli.evaluate run --mode retrieval --run-id dev-r3-retrieval
# Cả pipeline; bật vLLM trước bằng ./scripts/serve-vllm.sh
uv run python -m apps.cli.evaluate run --mode full --run-id dev-b3-full
# Chấm lại kết quả đã ghi, không gọi model
uv run python -m apps.cli.evaluate score dev-b3-full
```

Kết quả nằm ở `artifacts/runs/<run_id>/`: `manifest.json`, `records.jsonl`, `excluded.jsonl`, `report.json`, `report.md`.
Mặc định chạy `configs/pipeline/b3-qwen3-4b-awq.yaml` trên `benchmarks/v2/core.draft.jsonl` và
`comparison.draft.jsonl`; câu có dẫn chứng ngoài kho của cấu hình bị loại và ghi lý do vào `excluded.jsonl`. Mọi số là số
phát triển, `report.md` ghi rõ ở dòng đầu.

Ctrl-C thì câu đã xong giữ nguyên; chạy lại cùng `--run-id` để làm tiếp, `asked_at` lấy theo lượt cũ. `--retry-errors`
chạy lại cả câu `execution_error`. Bộ câu hỏi, cấu hình hoặc kho đổi hash thì `run` từ chối chạy tiếp và `score` từ chối
chấm. Mã thoát: 0 xong; 1 hash lệch hoặc lỗi chấm; 2 vLLM không chạy hoặc sai model; 130 Ctrl-C.

Còn thiếu:

- Cấu hình ba lớp và file cấu hình 17 cấu hình thí nghiệm ở `configs/experiments/`.
- Thống kê McNemar, Holm cho luật chọn ở mục 9.
- Test phát lại: cùng câu hỏi qua đường chấm và đường API phải cho cùng kết quả.
- CI ở `.github/workflows/`.
- Đọc tập câu SQL và RAG; `OracleRetriever` cho cấu hình G5; embedder Qwen3 cho cấu hình R5q; runner hội thoại cho nhóm viết
  lại câu.

Lệnh dự kiến của phần B (cấu hình thí nghiệm, chưa có code):

```bash
uv run python -m qnuchat.core matrix configs/experiments/baseline-gs.yaml
uv run python -m qnuchat.eval.runner configs/experiments/<baseline-r|q|gs|m>.yaml <run_id>
```

## 8. Router, SQL, cổng từ chối — chưa có code

Cần mục 5 (bảng số) và mục 7 (cờ cấu hình, kiểm cấu hình). Chưa có spec; đầu vào là mục 1 của file này.

- Router phân câu SQL và RAG; câu hỗn hợp tách hai phần, model viết một câu trả lời từ cả hai ngữ cảnh.
- Lọc ngành và năm.
- Cổng từ chối tất định: năm ngoài kho, SQL rỗng, câu dự đoán trúng tuyển, kèm câu cố định ở mục 1.
- Mặc định đợt, phiên bản, phương thức ở mục 1.
- Danh mục ngành 2024–2026: Kinh tế số, chương trình tiếng Anh, ACCA, mã đổi của Khoa học dữ liệu và Trí tuệ nhân tạo.
  Hiện `configs/catalog/qnu-2025.yaml` chỉ có năm 2025.

## 9. Chạy baseline — chưa chạy được

Cần mục 5, 6, 7, 8. **Snapshot hoặc bộ câu hỏi đổi sau khi đã chạy thì phải chạy lại cả lượt.**

**Khoá, đúng thứ tự:** khoá snapshot → gán lại nhãn bộ câu hỏi → khoá bộ câu hỏi → commit file đăng ký trước.

**Đo `max_tokens`** 2048 và 4096 trên khoảng 30 câu dài, đo thời gian sinh và VRAM.

**17 cấu hình, 10 cấu hình gọi model.** Chạy nhóm truy hồi → số liệu → sinh câu trả lời, rồi nhóm so hệ thống và nhóm viết lại câu.
Mỗi nhóm giữ cấu hình tốt nhất của nhóm trước.

| Nhóm | Cấu hình | Gọi model | Thời gian |
|---|---|---:|---|
| Truy hồi (mã R) | R3: BM25 + dense. R4: R3 + lọc ngành. R5: R3 + lọc ngành + năm. R5q: R5 với Qwen3-Embedding-0.6B. R6: R5 + reranker | 0 | 15–40 phút |
| Số liệu (mã Q) | Q1: SQL. Q2: dòng bảng + lọc năm. Q4: văn bản không lọc | 3 | 10–15 phút |
| Sinh câu trả lời (mã G) | G0: không đưa tài liệu. G1: hệ thống đầy đủ. G1ng: G1 không có cổng từ chối. G5: đưa thẳng đúng đoạn bằng chứng | 4 | 35–50 phút |
| So hệ thống (mã S) | S1: tài liệu nguyên trang, không chia đoạn, BM25 + dense. S2: truy hồi tốt nhất, không định tuyến. S3: chính là G1, không chạy lại | 2 | 25–40 phút |
| Viết lại câu nhiều lượt (mã M) | M1: không viết lại. M2: `query_rewrite` theo luật. M3: model hiểu câu, chạy sau mục 11.1 | 1 | 15–25 phút |

Thời gian là ước lượng, chưa đo. Cộng dựng index embedding 10–30 phút, đo `max_tokens` 10–20 phút, chạy lại câu lỗi dưới 10 phút.
Cấu hình R5q và R6 cần tải thêm `Qwen/Qwen3-Embedding-0.6B` (1,2 GB) và `BAAI/bge-reranker-v2-m3` (2,2 GB).

**Luật chọn, commit trước khi chạy; kết quả ra sao thì luật tự quyết:**

| Nhóm | Luật |
|---|---|
| Truy hồi | Tỷ lệ tìm thấy đoạn đúng trong 5 kết quả đầu (R@5) cao nhất. Chênh không quá 1 câu thì chọn cấu hình rẻ hơn. Đoạn sai năm không nhiều hơn R4 |
| Số liệu | `decision-critical error rate` thấp nhất. Q1 thắng nếu số câu đúng không kém Q2 quá 1 câu |
| Cổng từ chối | Bật nếu lỗi nghiêm trọng giảm và câu trả lời được mà bị từ chối nhầm tăng không quá 2 câu |
| Báo cáo | Tỷ lệ đúng và `decision-critical error rate`, kèm `coverage`; toàn bộ bộ câu hỏi trước, rồi tách SQL và RAG |

**So cặp:** McNemar chính xác, hiệu chỉnh Holm, đúng sáu cặp:

| Cặp | Trả lời câu hỏi |
|---|---|
| Q1 với Q4 | SQL có hơn văn bản không lọc không |
| R5 với R4 | Lọc năm có giúp không |
| G1 với G1ng | Cổng từ chối có giúp không |
| S3 với S2 | Định tuyến có giúp không |
| S3 với S1 | Hệ thống đầy đủ có hơn cách lấy nguyên trang không |
| M3 với M2 | Model hiểu câu có hơn viết lại theo luật không |

Thống kê: Wilson 95% cho tỷ lệ; bootstrap theo `source_family` khi một nhóm dữ kiện có nhiều câu. Mỗi lần chạy ghi manifest
gồm snapshot, bộ câu hỏi, cấu hình, model, môi trường, vào `artifacts/runs/<run_id>/`.

**Kent kiểm tay** khoảng 20 câu mỗi cấu hình gọi model, tổng khoảng 200 câu.

**Đầu ra:** `configs/pipeline/baseline-final.yaml` có hash.

## 10. Web app, bàn giao và nghiệm thu live — chưa có code

Repo này chưa có web app, database, giao diện. Phải chuyển trước theo [cấu trúc thư mục](docs/architecture/folder-structure.md):
API vào `apps/api/`, giao diện React vào `apps/web/`, migration vào `migrations/`, Docker Compose vào `infra/`.

**Chạy app sau khi chuyển.** Ba terminal:

```bash
# 1. Database
docker compose -f infra/compose.yaml up -d db

# 2. vLLM, giữ terminal mở
./scripts/serve-vllm.sh

# 3. App
until curl -sf localhost:8000/v1/models >/dev/null; do sleep 5; done
uv run python -m apps.api
curl -s localhost:8080/readyz | python3 -m json.tool      # "ready": true, đủ bốn checks
```

| Địa chỉ | Dùng cho |
|---|---|
| `http://127.0.0.1:8080/app/` | Chat |
| `http://127.0.0.1:8080/app/?mode=research` | Xem trace từng lượt |
| `http://127.0.0.1:8080/app/admin/conversations` | Quản trị: hội thoại, lượt, prompt gửi model |
| `http://127.0.0.1:8080/app/admin/perf`, `/canary`, `/feedback` | Hiệu năng, canary, phản hồi |
| `http://127.0.0.1:8080/docs` | Tài liệu API |

Giới hạn cần giữ: app chạy đúng một tiến trình, không `--workers`. Không đặt app sau reverse proxy cùng máy khi chưa có
xác thực, vì khu quản trị chỉ kiểm IP.

**Bàn giao:**

1. `configs/pipeline/b3-chat.yaml` đổi sang `extends: baseline-final.yaml`.
2. Retriever PostgreSQL phải cho cùng top-5 với đường hiện tại.
3. Chạy app như trên, sau `(cd apps/web && pnpm build)`.
4. Hỏi 3 câu gợi ý và "Học phí ngành Công nghệ thông tin năm 2025 là bao nhiêu?". Ghi thời gian từ lúc hiện nguồn tới lúc có
   câu trả lời.
5. Hỏi một câu, tắt Wi-Fi khi đang "Đang viết câu trả lời…", bật lại trong 60 giây: phải thấy câu đã lưu, không có lượt trùng.
6. Ba kịch bản nhiều lượt:
   - "Ngành Kỹ thuật phần mềm học mấy năm?" rồi "Ra trường làm gì?" trả lời về Kỹ thuật phần mềm.
   - "Học phí bao nhiêu?" hiện thẻ hỏi lại, bấm gợi ý thì trả lời theo ngành.
   - "Trường có ký túc xá không?" sau câu về Kỹ thuật phần mềm không bị gắn ngành.
7. Trang quản trị hiện "Prompt gửi LLM" và có dòng mới trong `artifacts/logs/llm_requests.jsonl`.
8. Vào `/app/admin/canary`, bấm "Chạy lại canary" một lần.
9. Đo lại generator cho môi trường mới; không sửa báo cáo hay hash cho khớp.
10. Ghi kết quả vào báo cáo nghiệm thu, tách rõ với kết quả backend giả.

## 11. Phần sau baseline

### 11.1. Model hiểu câu — chưa có code

Chưa có spec. Phân loại ý định bằng model (tra cứu, trò chuyện, sửa sai), kế thừa ngành và năm do model hiểu, danh mục chỉ là
danh sách giá trị hợp lệ. Xong thì chạy cấu hình M3.

Tám hành vi sau đang chạy bằng luật trong `query_rewrite`, thành ca kiểm thử cho phần này:

1. Câu chạm chủ đề cấp trường (ký túc xá, địa chỉ…) không đổi ngành kế thừa: "Ngành KTPM có ký túc xá không?" không đặt Kỹ
   thuật phần mềm cho lượt sau.
2. Bí danh mơ hồ ("tiếng Anh" khớp hai ngành) thì hỏi lại, trừ khi ngành kế thừa là một trong các ứng viên.
3. Năm kế thừa được ghép " năm 2024" vào mọi câu sau, kể cả câu cấp trường; có thể nhiễu truy hồi.
4. Với danh mục một năm, mọi câu trả lời hiện "Hiểu là: … năm 2025 (mặc định)"; có thể gây nhiễu.
5. Sau thẻ hỏi lại, câu từ 4 từ trở xuống, không "?", không từ để hỏi mà không hiểu được thì coi là câu trả lời, chạy câu treo;
   còn lại là câu hỏi mới.
6. Câu hỏi giữa các ngành ("Ngành nào…", "Những ngành…", "Các ngành…") hoặc bắt đầu bằng "Trường có…" không hỏi và không kế
   thừa ngành; "chuyên ngành nào" vẫn là câu về ngành đang nói.
7. Trả lời thẻ hỏi ngành bằng bí danh khớp từ 3 ngành trở xuống ("tiếng Anh") thì liệt kê cả các ngành đó, không hỏi lần hai.
8. Chỉ số 2015–2035 được hiểu là năm: "chỉ tiêu có 2000 không" không đặt năm 2000.

Thêm hai ca từ hội thoại thật: "ngành này có học bổng không" phải kế thừa Sư phạm Tiếng Anh; câu phàn nàn "Tôi đang hỏi ngành
sư phạm tiếng Anh tại sao bạn lại trả lời ngành Nông" là câu sửa sai.

### 11.2. Xoá ảnh người trong `quarantine/` — chưa có code

Cần kho web. Tắt vLLM cổng 8000 trước. Sổ `data/web/people.jsonl` đã có và khoá theo sha256, nên chỉ ảnh mới được gọi model
`Qwen/Qwen3-VL-2B-Instruct`. Lệnh dự kiến:

```bash
systemd-run --user --unit qnu-vllm-people --same-dir --collect --setenv=PATH="$PATH" scripts/serve-vllm-people.sh
uv run python -m apps.cli.knowledge_base people-scan --limit 20     # thử
uv run python -m apps.cli.knowledge_base people-scan                # khoảng 0,8 giây/ảnh; Ctrl-C rồi chạy lại được
systemctl --user stop qnu-vllm-people
uv run python -m apps.cli.crawl prune-people                        # chạy thử, ghi trang duyệt
xdg-open artifacts/knowledge_base/people/review.html
uv run python -m apps.cli.crawl prune-people --apply                # xoá thật
```

**Xem tay trang duyệt trước khi `--apply`.** Nhãn `anh_nguoi` gán cả poster tuyển sinh có người ở góc: ngày 06/11/2026 có 3 trên 4
ảnh bị gán sai, gồm poster quy đổi điểm và poster ngành Quản lý đất đai.

### 11.3. Lọc chủ đề kho web bằng model — chạy được

Lọc mịn hơn `topic_gate` của mục 4: model đọc từng mục rồi gán nhãn. Tầng A, hạt giống, trang hub và favicon không qua bộ lọc. Đầu vào
gồm metadata và 1.500 ký tự đầu của chữ; file và ảnh đã OCR dùng chữ OCR. Phải bốc mẫu bằng seed mới **trước** khi model chạy.

**Kho hiện nhỏ:** 95 mục cần lọc (60 trang, 31 ảnh, 4 file), nên mẫu chính là cả 95 mục, không phải 200. Có hai cách, đều bắt đầu bằng bước
0–2. Cách A nhanh và chắc hơn ở quy mô này: nhãn của Kent phủ cả kho nên không còn gì để suy từ mẫu ra.

| Bước | Lệnh | Ghi chú |
|---|---|---|
| 0 | `scripts/run_topic.sh status` | |
| 1 | `scripts/run_topic.sh sample <seed mới>` rồi `check-sample` | Phải in "mẫu khớp kho" |
| 2 | Mở `artifacts/knowledge_base/topic-filter/sample-<seed>/index.html`, gán nhãn, xuất `labels.csv` | **Kent** |
| A3 | `scripts/run_topic.sh labels ~/Downloads/labels.csv` | Áp thẳng nhãn của Kent, không cần model hay GPU |
| B3 | `scripts/run_topic.sh vllm`, rồi `try` (5 mục), rồi `start` | GPU phải rảnh; khoảng 2 phút; `log`, `stop` |
| B4 | `scripts/run_topic.sh score ~/Downloads/labels.csv` | In `ĐẠT` hoặc `KHÔNG ĐẠT: <lý do>` |
| 5 | `scripts/run_topic.sh pending` | Xem mục sẽ bị rút; chưa đổi gì |
| 6 | `scripts/run_topic.sh prune` | In lại danh sách; gõ xác nhận; **xoá blob và chữ OCR vĩnh viễn** |
| 7 | `scripts/run_topic.sh vllm-stop` | Nếu đã bật ở B3 |

**Nhãn:** `giu` là cần cho tư vấn tuyển sinh đại học chính quy cho học sinh THPT. `loai` là sau đại học, vừa làm vừa học,
từ xa, liên thông, văn bằng 2, khoá ngắn hạn, tin hoạt động, hội thảo, đoàn thể.

| `score` báo | Làm gì |
|---|---|
| Mục chưa có nhãn model | `scripts/run_topic.sh start` rồi đo lại |
| Cận Wilson vượt 5% với 0 mục loại nhầm | Thiếu mục `giu` (cần ít nhất 73). Mẫu đã là cả kho nên `topup` không còn mục để bốc: dùng cách A |
| Model loại nhầm, hoặc `khong_chac` vượt 15% | Không xoá. Sửa `configs/knowledge_base/topic_prompt.md` một lần, bốc mẫu mới, gán lại, chạy lại. Vẫn không đạt thì dùng cách A |

Chạy thử 12 mục ngày 06/11/2026 trên bản sao: 4 mục `loai` đều là thông báo ký túc xá, lý do `khoa_ngan_han`, trái prompt. Chưa đo, chưa sửa
prompt; nhiều khả năng cách B không đạt ở lần đầu.

Mục Kent gán nhãn thì model không ghi đè. `prune` chỉ áp nhãn của Kent, hoặc nhãn của phiên bản bộ lọc có `score.json` đạt. Không chạy
bước 1, B3, 6 khi kho đang quét.

### 11.4. OCR ảnh web — chạy được

Cấu hình `cur_rotgate`: PP-OCRv6 medium det, VietOCR `vgg_transformer`, `fix_combo_codes`, 300 dpi, cổng xoay trang. Đây là cấu
hình đã thắng khi thí nghiệm chọn OCR. Worker ở `src/qnuchat/ingest/ocr/worker.py`, chạy trong `environments/ocr`. Chỉ chạy GPU,
tắt vLLM trước.

```bash
./scripts/chay-ocr.sh setup     # lần đầu: môi trường 12 GB và trọng số, có kiểm hash
./scripts/chay-ocr.sh verify    # OCR lại 88 trang chuẩn, phải giống data/ocr-data từng dòng; khoảng 4 phút
./scripts/chay-ocr.sh           # OCR quarantine/; hoặc `start` để chạy nền, `log`, `stop`, `status`
./scripts/chay-ocr.sh review    # file nào giữ, file nào là danh sách người; chưa đổi kho
./scripts/chay-ocr.sh apply     # Kent xem review rồi mới chạy
./scripts/chay-ocr.sh remove <sha256>...   # xoá hẳn file, lần quét sau không tải lại
```

`run` từ chối chạy khi `worker.py` hoặc `environments/ocr/uv.lock` đã đổi mà chưa `verify` lại. Trang lỗi là execution error, không
thành trang rỗng; hết bộ nhớ GPU ở vài ảnh lớn thì `./scripts/chay-ocr.sh run --retry-errors`. Chỉ OCR trang PDF không có lớp chữ
và ảnh đã có nhãn `co_chu` hoặc `khong_nguoi` trong `data/web/people.jsonl`; ảnh chưa có nhãn hiện ở `review`, chờ nhãn.

`apply` chuyển file sạch từ `quarantine/` vào `blobs/`, ghi chữ ở `data/web/ocr/documents/`. File là danh sách người thì **xoá** cả bản
gốc lẫn chữ đã OCR. File không có chữ, lỗi, thiếu trang ở lại `quarantine/`.

**Giới hạn của lớp lọc người:** chỉ bắt danh sách (tiêu đề có từ hai cột như họ tên, ngày sinh, mã sinh viên, hoặc từ 5 hàng). OCR đọc sai
tiêu đề thì chỉ còn luật theo hàng. Một người đơn lẻ không bị bắt, nên `review` không thay được việc đọc lại. Trang cần bỏ thì thêm vào
`configs/ocr/excluded-pages.yaml` theo sha256 của file: trang đó không OCR, không vào kho; bản PDF gốc vẫn còn trang đó.

**Kết quả 06/11/2026:** 69 file, 121 trang, 5 phút, 2 ảnh hết bộ nhớ GPU qua được khi chạy lại. `review`: giữ 67, danh sách người 0. Đối chứng bằng danh sách giả qua OCR thật: bắt được cả có và không có tiêu đề, bỏ sót danh sách 3 hàng không tiêu đề.
Kent cho bỏ Phụ lục 3 tra cứu mã BHXH của ba bản hướng dẫn nhập học (HD2659 trang 9–10, HD2699 trang 8, HD2611 trang 9): ngoài phạm vi
tuyển sinh và có ảnh kết quả của một người. Ghi ở `configs/ocr/excluded-pages.yaml`. HD2611 có lớp chữ nên không qua OCR: bước dựng kho
chữ (mục 5) phải đọc file này. Hai ảnh ký túc xá không có chữ đã xoá bằng `remove`.
Đã `apply`: 67 file, 125 trang vào kho, `quarantine/` trống. Lọc chủ đề trên chữ OCR ở mục 11.3.

### 11.5. Giao diện

| Việc | Phụ thuộc |
|---|---|
| Câu hỏi liên quan (không gợi ý câu "có đậu không"), xem trang gốc PDF, chip và khung nguồn mức cả câu trả lời | Web app ở mục 10 |
| Hỏi trong một văn bản | `baseline-final.yaml` |
| Chip nguồn web, lịch quét, trang quản trị Nguồn web | Kho web |

## 12. Mở cho người dùng thật — chưa có code, chờ trường

Cần mục 10. Trước khi mở công khai:

1. Phòng tuyển sinh duyệt câu chữ khối `consent` trong `configs/product.yaml`. Sửa chữ nào thì `consent_version` đổi và người
   dùng phải đồng ý lại.
2. `retention_until` đặt 2027-12-31.
3. `log_llm_requests: false`.
4. Đặt `public_origin: "https://<tên miền>"`, không thì mọi POST công khai bị 403.
5. Thay liên hệ trong `.env` bằng liên hệ chính thức của trường.
6. Database trên server dùng `LC_CTYPE` UTF-8.
7. Xin trường đặt link chatbot trong đợt 18/01 – 21/03/2027 và dùng tin nhắn fanpage đã ẩn danh.

**Xoá theo yêu cầu:** `/app/admin/conversations`, tìm theo mã `XXXX-XXXX` hoặc nội dung, mở hội thoại, "Xoá hội thoại".

**Review hằng tuần:** `/app/admin/feedback`.

**Quét định kỳ** (02:00 hằng ngày). Chỉ bật sau khi đã khoá snapshot đề án. Chưa có file timer; lệnh dự kiến:

```bash
mkdir -p ~/.config/systemd/user && cp infra/systemd/qnu-crawl.* ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now qnu-crawl.timer
loginctl enable-linger "$USER"
```

**Xoá dữ liệu khi tới mốc.** Không hoàn tác được: xuất dữ liệu ẩn danh trước, đối chiếu số đếm rồi mới xoá.

```bash
uv run python -m apps.api.store.purge --dry-run
uv run python -m apps.api.store.purge
```

## 13. Kiểm thử

```bash
uv run pytest -q                                   # không cần GPU, database, mạng
uv run ruff check src tests experiments apps
uv run lint-imports
```

Khi đã chuyển web app:

```bash
set -a; source .env; set +a
DATABASE_URL_TEST="$DATABASE_URL" uv run pytest -q -m db                # PostgreSQL thật
QNUCHAT_LIVE=1 uv run pytest tests/api/test_web_live.py -m live -v      # vLLM và database thật
(cd apps/web && pnpm test && pnpm lint && pnpm exec tsc -b && pnpm check:api)
(cd apps/web && pnpm build && pnpm e2e)                                 # backend giả, cần Chrome
```

## 14. Sự cố

| Triệu chứng | Xử lý |
|---|---|
| `quet-web.sh` báo thiếu `QNUCHAT_CRAWL_CONTACT_EMAIL` | Thêm vào `.env` (mục 2) |
| `quet-web.sh` báo đang có crawler khác | Chờ lần đó xong, hoặc dừng nó; không chạy hai crawler cùng lúc |
| `quet-web.sh` báo không kết nối được | Kiểm mạng rồi chạy lại; hàng đợi vẫn còn |
| `status` có lần quét kẹt `running` | Tiến trình đã bị giết cứng; chạy lại quét, dòng cũ giữ nguyên |
| `nvidia-smi` lỗi driver hoặc `Driver/library version mismatch` | Khởi động lại máy |
| vLLM `CUDA out of memory` lúc nạp | `nvidia-smi` tìm và tắt tiến trình đang giữ VRAM |
| vLLM lỗi warmup nhắc `nvcc` | Dùng `scripts/serve-vllm.sh`, script đã đặt `VLLM_USE_FLASHINFER_SAMPLER=0` |
| vLLM báo không tìm thấy model | Chưa tải model: chạy `hf download` ở mục 2 |
| `thuc-nghiem-live.sh` báo GPU không đủ | Tắt app đang dùng GPU rồi chạy lại |
| Muốn embedding lại corpus | Xoá `artifacts/cache/embeddings/` |

Khi đã chuyển web app:

| Triệu chứng | Xử lý |
|---|---|
| App thoát `SchemaMismatch` | Chạy migration trong `migrations/` |
| App thoát `ValidationError … contact` hoặc `database_url` | Thiếu khoá trong `.env` |
| App thoát `vLLM không phục vụ 'Qwen/Qwen3-4B-AWQ'` | vLLM chưa nạp xong; dùng `scripts/serve-vllm.sh` |
| App thoát `Canary hỏng … finish_reason_stop` | vLLM thiếu `disable_any_whitespace`; serve lại bằng script |
| `alembic upgrade` dừng `Cần PostgreSQL >= 18` | Dùng `infra/compose.yaml` |
| Giao diện báo bận (503) | Bình thường trên laptop, `max_concurrency: 1` |
| Giao diện báo lỗi (502) | Xem `/readyz` và `/app/admin/turns/{id}` |
| `/readyz` 503, `"db": false` | `docker compose -f infra/compose.yaml up -d db` |
| `/app/` trả 404, log `web_ui_dist_missing` | `(cd apps/web && pnpm build)` rồi khởi động lại app |
| `/app/admin` báo không có quyền | Mở từ chính máy chạy app bằng `127.0.0.1` hoặc `localhost` |
