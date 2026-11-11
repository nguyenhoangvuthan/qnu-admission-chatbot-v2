# Công cụ chấm, phần A: chạy và chấm một cấu hình

RUNBOOK mục 7. Thiết kế duyệt với Kent ngày 10/11/2026, ba phần: kiến trúc, metric và lỗi, kiểm thử.

## 1. Mục đích và phạm vi

Có số đo phát triển ngay trên kho và bộ câu hỏi hiện có, để thấy lỗi của pipeline sớm. Khi snapshot đề án (mục 5)
và bộ câu hỏi khoá (mục 6) xong thì chỉ đổi đầu vào, không viết lại công cụ.

Mục 7 chia năm phần; spec này chỉ là phần A.

| Phần | Nội dung | Trạng thái |
|---|---|---|
| **A** | Runner, chấm, báo cáo có Wilson 95% | Spec này |
| B | Cấu hình thí nghiệm ba lớp, `matrix`; chỉ tạo file cho cấu hình đã có thành phần thật (R3, Q4, M1, M2, G5) | Spec sau |
| C | McNemar chính xác, Holm, file đăng ký trước | Spec sau |
| D | Test phát lại eval và API | Chờ API (mục 10) |
| E | CI | Spec sau |

Plan P1 của repo cũ (`docs/superpowers/plans/2026-10-03-p1-core-eval.md`) thêm sẵn cờ cho thành phần chưa có code.
v2 không làm vậy (AGENTS.md: chỉ thêm cờ khi có code dùng thật).

## 2. Quyết định đã chốt

| Quyết định | Lý do |
|---|---|
| Tách `run` và `score` | Bộ câu hỏi còn 27 câu cần sửa và 11 câu cần xử lý nguồn; sửa nhãn thì chấm lại vài giây thay vì chạy model lại 10–50 phút |
| Chạy trên kho hiện có, lọc câu | Không đụng core. Runtime chỉ nạp PDF, cấu hình chỉ có Cẩm nang 2025; nạp đủ 19 file của snapshot `v2-2026-10-14` để cho mục 5 |
| Mọi số ghi nhãn "phát triển" | Bộ câu hỏi là nháp, kho chỉ 1 PDF |

Đo ngày 10/11/2026 trên `benchmarks/v2/core.draft.jsonl` và `comparison.draft.jsonl` (126 câu): giữ 56 câu trả lời được
có mọi dẫn chứng trong Cẩm nang 2025, cộng 11 câu phải từ chối; loại 59 câu.

## 3. Kiến trúc

```
bộ câu hỏi nháp ──► cases ──► runner ──► artifacts/runs/<run_id>/
                                            manifest.json, records.jsonl, excluded.jsonl
                                              │
                                              ▼
                                           score ──► report.json, report.md
```

| Module | Việc | Phụ thuộc |
|---|---|---|
| `qnuchat.eval.cases` | Đọc bộ câu hỏi nháp; chọn câu theo nguồn có trong kho | `eval.schema` |
| `qnuchat.eval.runner` | Lắp runtime từ `configs/pipeline/*.yaml`, chạy từng câu, ghi kết quả thô và manifest | `core`, `adapters` |
| `qnuchat.eval.outcome` | Xếp mỗi câu vào một nhóm kết quả | `eval.metrics` |
| `qnuchat.eval.score` | Kiểm hash, tính metric, ghi báo cáo | `eval.*` |
| `qnuchat.eval.stats` | Thêm `wilson_interval` cạnh bootstrap đã có | không |
| `apps/cli/evaluate.py` | Lệnh `run` và `score` | `eval` |

`eval` không import `experiments`; hàm băm file viết lại trong `eval`, không lấy từ `experiments/provenance.py`.

### 3.1. Đọc và chọn câu

Mỗi dòng nháp là `{"item": GoldItem, "task_type": ..., "gold_evidence": [[đường dẫn nguồn, trang], ...], ...}`.
`EvalCase` giữ `item`, `task_type` và `gold_evidence` dạng `(source_id, page)`.

Đường dẫn trong `gold_evidence` được đổi sang `source_id` bằng `corpus.sources[].path` của cấu hình pipeline. Luật chọn:

- `must_abstain = true`: luôn giữ.
- Mọi dẫn chứng thuộc nguồn trong kho: giữ.
- Có dẫn chứng ngoài kho, hoặc `gold_evidence` rỗng mà không phải câu từ chối: loại, ghi vào `excluded.jsonl` kèm lý do
  (`source_not_in_corpus`, `no_gold_evidence`).

### 3.2. Runner

Hai chế độ:

- `full`: lắp `QnuChatPipeline` bằng `build_runtime` và `assemble_pipeline`, gọi vLLM. Trước câu đầu tiên chạy
  `check_served_model`; sai model hoặc không kết nối được thì dừng.
- `retrieval`: chỉ gọi retriever của runtime, không cần vLLM. Dùng cho cấu hình kiểu R3.

`Query.asked_at` lấy từ tham số `--asked-at` (mặc định ngày chạy) và ghi vào manifest, để chạy lại cho cùng kết quả.

`run_id` mặc định là `<YYYYMMDD-HHMM>-<tên cấu hình>-<chế độ>`; truyền `--run-id` để chạy tiếp một lượt cũ.

**`manifest.json`:** `run_id`, `mode`, `label: "phát triển"`, `asked_at`, `pipeline_config_name`, `pipeline_config_hash`,
`snapshot` (id, content_hash, vector_hash), danh sách file bộ câu hỏi kèm SHA-256, số câu giữ và loại, model và revision
của generator và embedding, phiên bản vLLM (chế độ `full`), thiết bị embedding, git commit, `created_at`.

**`records.jsonl`:** một dòng một câu, ghi ngay khi câu xong (`fsync`).

| Trường | Nội dung |
|---|---|
| `id` | ID câu |
| `status` | `ok` hoặc `execution_error` |
| `answer` | `Answer` đầy đủ kèm `Trace` (chế độ `full`, khi `ok`) |
| `passages` | `[{chunk_id, source_id, page, rank}]` của kết quả gộp; chế độ `full` lấy từ trace stage `fusion` |
| `error` | `{stage, cause, message}` khi lỗi |
| `elapsed_ms` | Thời gian chạy câu |

Chạy lại cùng `run_id` chỉ chạy câu chưa có dòng; `--retry-errors` chạy lại cả câu `execution_error`. Dòng mới nhất của
một `id` là kết quả hiện hành.

## 4. Metric

### 4.1. Nhóm kết quả

Mỗi câu thuộc đúng một nhóm.

| Câu | Nhóm | Điều kiện |
|---|---|---|
| Trả lời được | `correct` | Không từ chối; mọi slot kỳ vọng khớp (`key_fact_accuracy = 1`) |
| | `critical_error` | Không từ chối; có claim khớp `subject` và `predicate` của ít nhất một slot kỳ vọng (tính cả synonym), mà không slot nào trong các slot đó có cùng `value` và năm không lệch (năm lệch: cả hai bên đều có `admission_year` mà khác nhau) |
| | `incomplete` | Không từ chối, không `critical_error`, thiếu ít nhất một slot |
| | `abstained` | Từ chối |
| Phải từ chối | `abstained_ok` | Từ chối |
| | `answered_wrongly` | Không từ chối |
| Mọi câu | `execution_error` | `status = execution_error`; không tính là từ chối, không vào mẫu số |

`critical_error` xét trước `incomplete`: câu vừa thiếu slot vừa sai một giá trị là `critical_error`.

Sửa 11/11/2026, Kent đồng ý cùng ngày: bản đầu so claim với từng slot riêng. 5/56 câu trả lời được (vd. `V2-PIL-027` "Kinh tế có hai chuyên ngành
nào?") có nhiều slot cùng `subject` và `predicate`, khác `value`; so riêng thì câu trả lời đúng đủ vẫn thành `critical_error`.
Claim ghi giá trị của điều kiện khác (phương thức, đợt) vẫn là `critical_error`, vì `Claim` không có trường điều kiện để phân
biệt; Task 8 của plan đọc tay các câu này.

Sửa lần hai 11/11/2026, Kent đồng ý cùng ngày (review sau Task 7): khi xét `critical_error`, giá trị của claim và slot
được chuẩn hoá thêm trước khi so: bỏ dấu câu ở cuối, bỏ tiền tố "chuyên ngành", "ngành học", "ngành"; riêng claim
còn bỏ đơn vị của slot (kể cả `unit_synonyms`) nếu nó đứng cuối `value`. Trước đó "138 tín chỉ", "138." và "Chuyên
ngành Kinh tế đầu tư" đều thành `critical_error`, dù giá trị đúng; 80/118 slot có đơn vị, 37/118 slot là chữ. Chuẩn
hoá này chỉ dùng để quyết định `critical_error`: `correct` vẫn so theo `slot_matches`, nên các claim trên thành
`incomplete`. Không chọn cách bỏ hẳn slot chữ khỏi `critical_error`, vì 29/37 giá trị chữ ngắn (≤ 4 từ, vd. "Cử
nhân", "Kỹ sư") và trả nhầm chúng là sai thật.

### 4.2. Số trong báo cáo

Mẫu số N là số câu trả lời được có `status = ok`. Mọi tỷ lệ kèm Wilson 95%.

| Số | Công thức |
|---|---|
| Tỷ lệ đúng | `correct` / N |
| `decision-critical error rate` | `critical_error` / N |
| Lỗi nghiêm trọng theo loại giá trị | Số câu `critical_error` có claim mâu thuẫn với slot số, và số câu chỉ mâu thuẫn với slot chữ, kèm danh sách ID câu chữ để đọc tay. Slot số: `value` sau chuẩn hoá chỉ gồm chữ số và dấu chấm |
| Coverage | (N − `abstained`) / N |
| Từ chối | precision, recall, F1 từ `abstention_scores`; số `answered_wrongly` |
| Truy hồi | R@5, MRR, nDCG@10 trung bình; hit@5 kèm Wilson. So theo cặp `(source_id, page)` |
| Execution error | Số câu theo `cause` |

Tách mọi số theo `task_type`. Tách SQL và RAG khi bộ câu hỏi có nhãn đó.

Metric truy hồi hiện so theo số trang (`eval/metrics/retrieval.py`). Đổi sang cặp `(source_id, page)` như ghi chú §4 của
`docs/architecture/migration-assessment.md`; giữ hàm cũ nếu còn nơi dùng.

`report.md` mở đầu bằng dòng: "Số phát triển: bộ câu hỏi nháp, kho <nguồn>; không dùng để báo cáo."

## 5. Xử lý lỗi

| Tình huống | Xử lý |
|---|---|
| vLLM không chạy hoặc sai model | `run` dừng trước câu đầu, mã thoát khác 0 |
| `PipelineError` ở một câu | Ghi `execution_error` với `stage`, `cause`; chạy câu tiếp |
| Lỗi khác ở một câu | Không bắt; `run` dừng, các câu đã xong vẫn còn trong `records.jsonl` |
| Chạy tiếp mà bộ câu hỏi, cấu hình hoặc kho đổi hash | `run` từ chối, in hash cũ và mới |
| `score` thấy hash bộ câu hỏi khác manifest | Từ chối chấm |
| Câu có `forbidden_claims` khác rỗng | `score` báo lỗi; chưa có metric cho trường này (hiện 126/126 câu để rỗng) |
| Ctrl-C | Dừng; câu đã xong giữ nguyên, chạy lại cùng `run_id` thì làm tiếp |

## 6. Kiểm thử

Không cần GPU hay vLLM: dùng `FakeRetriever`, `FakeGenerator` trong `tests/support/fakes.py`. Test ở `tests/eval/`
và `tests/apps/`.

| Phần | Ca kiểm |
|---|---|
| `cases` | Đọc dạng nháp; loại câu có dẫn chứng ngoài kho kèm lý do; giữ câu phải từ chối |
| Nhóm kết quả | Mỗi nhóm một ca dựng tay, gồm sai giá trị, sai năm, thiếu slot, vừa thiếu vừa sai |
| Truy hồi | Trang 5 nguồn A không khớp trang 5 nguồn B |
| Wilson | 0/n, n/n, 5/10 so với giá trị tính sẵn; n = 0 báo lỗi |
| Runner | `PipelineError` ở một câu không dừng lượt; chạy lại không gọi lại câu đã xong; `--retry-errors` chỉ chạy câu lỗi |
| Hash | Đổi một byte bộ câu hỏi thì `score` từ chối; đổi kho thì `run` tiếp tục bị từ chối |
| `forbidden_claims` | Khác rỗng thì `score` báo lỗi |
| CLI | `run` rồi `score` trên fixture 3 câu ra `report.json` đúng số và `report.md` có dòng nhãn |

Kiểm trên dữ liệu thật sau khi test xanh:

1. `run --mode retrieval` trên 67 câu. Kiểm trang trong `gold_evidence` cùng cách đánh số với trang của `load_pdf_pages`
   (đối chiếu 3 câu bằng mắt).
2. `run --mode full` với vLLM qua `scripts/serve-vllm.sh`.
3. Đọc tay khoảng 10 câu `critical_error`. Metric đếm sai thì sửa metric, không sửa nhãn.

Ràng buộc: `tests/core/test_pilot_parity.py` xanh; `lint-imports` giữ 4/4 contract; không thêm dependency.

## 7. Ngoài phạm vi

McNemar, Holm và file đăng ký trước (phần C); file cấu hình thí nghiệm và `matrix` (phần B); hội thoại nhiều lượt;
faithfulness và completeness (chờ rubric); nạp html, docx vào runtime (mục 5); metric cho `forbidden_claims`.
