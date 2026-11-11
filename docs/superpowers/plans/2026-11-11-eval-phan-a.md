# Công cụ chấm phần A — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lệnh `run` chạy một cấu hình pipeline trên bộ câu hỏi nháp và ghi kết quả thô; lệnh `score` chấm lại kết quả đó thành
`report.json` và `report.md` có Wilson 95%.

**Architecture:** `qnuchat.eval` có thêm bốn module thuần (`cases`, `outcome`, `runner`, `score`) chỉ phụ thuộc `core` và
`eval`. Dòng lệnh `apps/cli/evaluate.py` dựng runtime thật bằng `qnuchat.adapters.runtime.build_runtime` rồi đưa pipeline
hoặc retriever vào runner, nên test thay runtime bằng fake mà không cần GPU hay vLLM. Kết quả nằm ở `artifacts/runs/<run_id>/`.

**Tech Stack:** Python 3.12, pydantic 2, numpy (đã có), pytest, argparse. Không thêm dependency.

**Spec:** `docs/superpowers/specs/2026-11-10-eval-phan-a-design.md` (Kent duyệt 11/11/2026)

## Global Constraints

- Không thêm dependency; không sửa `src/qnuchat/core/` (spec §2: "Không đụng core").
- `eval` không import `experiments`; hàm băm file viết lại trong `eval`.
- `uv run lint-imports` giữ 4/4 contract; `tests/core/test_pilot_parity.py` xanh.
- `report.md` mở đầu đúng dòng: `Số phát triển: bộ câu hỏi nháp, kho <nguồn>; không dùng để báo cáo.` `<nguồn>` là các
  `source_id` của manifest, nối bằng `, `.
- `manifest.json` có `label: "phát triển"`.
- `PipelineError` là `execution_error`: không tính là từ chối, không vào mẫu số.
- Mã thoát của `apps.cli.evaluate`: 0 xong; 1 từ chối vì hash lệch hoặc lỗi chấm; 2 vLLM không chạy hoặc sai model; 130 Ctrl-C.
- Chuỗi thông báo, docstring, comment bằng tiếng Việt như phần còn lại của repo.
- AGENTS.md: chỉ commit khi Kent đã cho phép trong phiên; nếu chưa, bước Commit chỉ chạy kiểm tra rồi dừng.
- Mỗi task kết thúc bằng `uv run pytest -q`, `uv run ruff check src tests experiments apps`, `uv run lint-imports`.
- Chưa có nhãn SQL/RAG trong bộ câu hỏi nên không tách theo nhãn đó (spec §4.2 "khi bộ câu hỏi có nhãn đó").

## Review Focus

1. **Nhóm `task_type` có N = 0.** `future_year` và `fanpage_unverified` chỉ có câu phải từ chối. Mọi tỷ lệ tính trên N của nhóm
   đó là `None`, `report.md` in `—`, không gọi `wilson_interval(0, 0)`. Test ở Task 6.
2. **Chạy tiếp hôm sau mà không truyền `--asked-at`.** Phải lấy `asked_at` từ manifest cũ, không lấy ngày hôm nay. Nếu không,
   lượt bị từ chối vì lệch identity, hoặc tệ hơn là trộn hai ngày hỏi. Test ở Task 7.
3. **Dòng cuối `records.jsonl` bị cắt dở** (mất điện, kill -9). `read_records` bỏ qua dòng cuối không parse được, và lần ghi
   sau cắt phần dở đó trước khi nối. Dòng hỏng ở giữa file thì báo lỗi. Test ở Task 5.
4. **Model trả hai claim cho cùng slot, một đúng một sai** (ví dụ hai phương thức xét tuyển). Theo luật spec §4.1 đây là
   `critical_error`. Test ghim hành vi này để lần đọc tay ở Task 8 có mốc so; nếu đọc tay thấy sai thì sửa metric.
5. **`score` trên lượt chưa chạy xong** (Ctrl-C). Báo cáo ghi `missing` = số câu đã giữ mà chưa có dòng, và `report.md` ghi
   rõ lượt chưa xong; không trình bày như lượt đủ. Test ở Task 6.

---

### Task 1: Wilson 95%

**Files:**
- Modify: `src/qnuchat/eval/stats.py`
- Test: `tests/eval/test_stats.py`

**Interfaces:**
- Produces: `wilson_interval(successes: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]`

- [ ] **Step 1: Viết test hỏng**

```python
def test_wilson_matches_precomputed_values():
    assert wilson_interval(0, 10) == pytest.approx((0.0, 0.2775328), abs=1e-6)
    assert wilson_interval(10, 10) == pytest.approx((0.7224672, 1.0), abs=1e-6)
    assert wilson_interval(5, 10) == pytest.approx((0.2365931, 0.7634069), abs=1e-6)

def test_wilson_refuses_empty_sample():
    with pytest.raises(ValueError):
        wilson_interval(0, 0)

def test_wilson_refuses_successes_outside_sample():
    with pytest.raises(ValueError):
        wilson_interval(11, 10)
```

- [ ] **Step 2:** `uv run pytest tests/eval/test_stats.py -q` → FAIL, `ImportError: wilson_interval`.
- [ ] **Step 3:** Viết `wilson_interval` trong `stats.py`. Công thức điểm Wilson; cắt hai đầu về `[0, 1]`.
- [ ] **Step 4:** `uv run pytest tests/eval/test_stats.py -q` → PASS.
- [ ] **Step 5: Commit** `git add src/qnuchat/eval/stats.py tests/eval/test_stats.py` — "Thêm khoảng Wilson 95% cho tỷ lệ (chấm phần A)".

---

### Task 2: Metric truy hồi theo cặp `(source_id, page)`

Spec §4.2: trang 5 nguồn A không được khớp trang 5 nguồn B. Hàm cũ chỉ có test dùng, nên thay chữ ký, không giữ song song.

**Files:**
- Modify: `src/qnuchat/eval/metrics/retrieval.py`
- Modify: `tests/eval/test_retrieval.py`

**Interfaces:**
- Produces, trong `qnuchat.eval.metrics.retrieval`:
  - `PageKey = tuple[str, int]`
  - `recall_at_k(retrieved: Sequence[PageKey], gold: Collection[PageKey], k: int) -> float`
  - `reciprocal_rank(retrieved: Sequence[PageKey], gold: Collection[PageKey]) -> float`
  - `ndcg_at_k(retrieved: Sequence[PageKey], gold: Collection[PageKey], k: int) -> float`
  - `hit_at_k(retrieved: Sequence[PageKey], gold: Collection[PageKey], k: int) -> bool`
- `retrieved` là cặp theo thứ hạng, có thể lặp khi một trang tách nhiều passage. `gold` rỗng thì `recall` và `ndcg` là `nan`
  như hiện tại.

- [ ] **Step 1: Sửa test.** Đổi helper `hits(...)` thành danh sách cặp. Giữ nguyên ý của mọi test cũ: khử lặp trang, cắt `k`,
  `nan` khi gold rỗng, nDCG thưởng thứ hạng cao. Thêm:

```python
def test_same_page_number_in_another_source_is_not_a_hit():
    retrieved = [("nguon-b", 5)]
    assert recall_at_k(retrieved, {("nguon-a", 5)}, k=5) == 0.0
    assert reciprocal_rank(retrieved, {("nguon-a", 5)}) == 0.0
    assert hit_at_k(retrieved, {("nguon-a", 5)}, k=5) is False

def test_hit_at_k_is_true_when_any_gold_page_in_top_k():
    assert hit_at_k([("a", 1), ("a", 9)], {("a", 9), ("a", 3)}, k=2) is True
```

- [ ] **Step 2:** `uv run pytest tests/eval/test_retrieval.py -q` → FAIL.
- [ ] **Step 3:** Viết lại bốn hàm trên cặp `PageKey`. Module không còn import `Hit`.
- [ ] **Step 4:** `uv run pytest tests/eval -q` → PASS.
- [ ] **Step 5: Commit** — "Metric truy hồi so theo cặp nguồn và trang".

---

### Task 3: Đọc và chọn câu (`qnuchat.eval.cases`)

**Files:**
- Create: `src/qnuchat/eval/cases.py`
- Test: `tests/eval/test_cases.py`

**Interfaces:**
- Consumes: `GoldItem` (`qnuchat.eval.schema`), `PageKey` (Task 2).
- Produces:
  - `class StaleRunError(RuntimeError)`: dữ liệu hiện tại không khớp dữ liệu đã sinh ra lượt chạy.
  - `@dataclass(frozen=True) class EvalCase: item: GoldItem; task_type: str; gold_evidence: tuple[PageKey, ...]`
  - `read_rows(paths: Sequence[Path]) -> list[dict]`: mọi dòng không rỗng của các file, theo thứ tự file. `id` trùng giữa các
    dòng → `ValueError` nêu id.
  - `select_cases(rows: Sequence[dict], sources: Mapping[str, str]) -> tuple[list[EvalCase], list[dict]]`. `sources` ánh xạ
    đường dẫn nguồn (`Path(p).as_posix()`) sang `source_id`. Phần tử thứ hai là danh sách loại
    `{"id", "reason", "gold_evidence"}`, với `reason` thuộc `source_not_in_corpus` hoặc `no_gold_evidence`.
  - `gold_digests(paths: Sequence[Path]) -> list[dict]`: `[{"path": p.as_posix(), "sha256": hex}]`.
  - `check_gold_unchanged(recorded: Sequence[dict]) -> None`: băm lại từng `path`; lệch thì `StaleRunError` có tên file, hash
    cũ và hash mới (12 ký tự đầu).

Luật chọn (spec §3.1): `must_abstain` luôn giữ, `gold_evidence` để rỗng; mọi dẫn chứng thuộc `sources` thì giữ, đổi sang
`(source_id, page)`; còn lại loại.

- [ ] **Step 1: Viết test hỏng.** Dựng dòng nháp tối thiểu bằng helper `row(id, must_abstain=False, evidence=[...])`, `item` đủ
  trường bắt buộc của `GoldItem`.

```python
SOURCES = {"data/a.pdf": "nguon-a"}

def test_keeps_case_whose_evidence_is_all_in_corpus():
    cases, excluded = select_cases([row("Q1", evidence=[["data/a.pdf", 4]])], SOURCES)
    assert [c.gold_evidence for c in cases] == [(("nguon-a", 4),)] and excluded == []

def test_excludes_case_with_evidence_outside_corpus_with_reason():
    _, excluded = select_cases([row("Q2", evidence=[["data/a.pdf", 4], ["data/b.pdf", 1]])], SOURCES)
    assert excluded[0]["id"] == "Q2" and excluded[0]["reason"] == "source_not_in_corpus"

def test_excludes_answerable_case_without_evidence():
    _, excluded = select_cases([row("Q3", evidence=[])], SOURCES)
    assert excluded[0]["reason"] == "no_gold_evidence"

def test_keeps_must_abstain_case_even_without_evidence():
    cases, _ = select_cases([row("Q4", must_abstain=True, evidence=[])], SOURCES)
    assert cases[0].item.must_abstain and cases[0].gold_evidence == ()

def test_duplicate_id_across_files_is_refused(tmp_path): ...  # hai file cùng id "Q1" → ValueError khớp "Q1"

def test_changed_gold_file_is_refused(tmp_path):
    path = tmp_path / "g.jsonl"; path.write_text("{}\n", encoding="utf-8")
    recorded = gold_digests([path]); path.write_text("{} \n", encoding="utf-8")
    with pytest.raises(StaleRunError, match="g.jsonl"):
        check_gold_unchanged(recorded)
```

- [ ] **Step 2:** `uv run pytest tests/eval/test_cases.py -q` → FAIL, module chưa có.
- [ ] **Step 3:** Viết `cases.py` theo Interfaces.
- [ ] **Step 4:** `uv run pytest tests/eval/test_cases.py -q` → PASS. Kiểm thêm trên dữ liệu thật:

```bash
uv run python -c "
from pathlib import Path
from qnuchat.eval.cases import read_rows, select_cases
rows = read_rows([Path('benchmarks/v2/core.draft.jsonl'), Path('benchmarks/v2/comparison.draft.jsonl')])
p = 'data/tuyen-sinh-dai-hoc-chinh-quy/Cẩm Nang Tuyển Sinh Đại Học Năm 2025.pdf'
cases, ex = select_cases(rows, {p: 'cam-nang-2025'})
print(len(cases), sum(not c.item.must_abstain for c in cases), len(ex))"
```

Kết quả mong đợi: `67 56 59`.

- [ ] **Step 5: Commit** — "Đọc bộ câu hỏi nháp và chọn câu theo nguồn trong kho".

---

### Task 4: Nhóm kết quả (`qnuchat.eval.outcome`)

**Files:**
- Create: `src/qnuchat/eval/outcome.py`
- Test: `tests/eval/test_outcome.py`

**Interfaces:**
- Consumes: `entity_matches`, `normalise_value`, `slot_matches` (`eval.metrics.slots`); `ScoredAnswer`, `GoldItem`,
  `ExpectedSlot` (`eval.schema`); `Claim` (`core.contracts`).
- Produces:
  - `Outcome = Literal["correct", "critical_error", "incomplete", "abstained", "abstained_ok", "answered_wrongly", "execution_error"]`
  - `contradicts(claim: Claim, slots: Sequence[ExpectedSlot]) -> bool`. Gọi `same` là các slot mà claim khớp `subject` và
    `predicate` (tính synonym). `same` rỗng thì `False`. Ngược lại, claim **không** mâu thuẫn khi có một slot `s` trong
    `same` thoả cả hai: `normalise_value(claim.value)` thuộc `{s.value, *s.value_synonyms}` đã chuẩn hoá, và năm không lệch
    (`claim.admission_year` hoặc `s.admission_year` là `None`, hoặc hai năm bằng nhau). Không có slot nào như vậy thì `True`.
    Không xét `unit`.
  - `classify(item: GoldItem, answer: ScoredAnswer | None) -> Outcome`. `None` nghĩa là `execution_error`.

Thứ tự xét cho câu trả lời được: `abstained` → `critical_error` (có claim mà `contradicts(claim, item.expected_slots)`) →
`correct` (mọi slot có claim `slot_matches`) → `incomplete`.

Vì sao xét cả danh sách slot (sửa spec §4.1 ngày 11/11/2026): 5/56 câu trả lời được, như `V2-PIL-027` "Kinh tế có hai
chuyên ngành nào?", có nhiều slot cùng `subject` và `predicate` nhưng khác `value`. Nếu so từng slot riêng, claim đúng
"Kinh tế đầu tư" mâu thuẫn với slot "Kinh tế phát triển", nên câu trả lời hoàn hảo vẫn bị tính `critical_error`.

- [ ] **Step 1: Viết test hỏng.** Một slot `S = (ngành CNTT, học phí, 15, triệu đồng, 2025)`; helper `answered(*claims)`.

```python
def test_all_slots_matched_is_correct(): assert classify(item([S]), answered(claim_of(S))) == "correct"
def test_wrong_value_is_critical(): assert classify(item([S]), answered(claim_of(S, value="16"))) == "critical_error"
def test_wrong_year_is_critical(): assert classify(item([S]), answered(claim_of(S, admission_year=2024))) == "critical_error"
def test_missing_year_on_claim_is_not_critical_but_incomplete():
    assert classify(item([S]), answered(claim_of(S, admission_year=None))) == "incomplete"
def test_missing_slot_is_incomplete(): assert classify(item([S, S2]), answered(claim_of(S))) == "incomplete"
def test_missing_and_wrong_is_critical():
    assert classify(item([S, S2]), answered(claim_of(S, value="16"))) == "critical_error"
def test_claim_about_other_subject_is_not_critical():
    assert classify(item([S]), answered(claim_of(S, subject="Luật", value="16"))) == "incomplete"
def test_one_right_one_wrong_claim_for_same_slot_is_critical():  # Review Focus 4
    assert classify(item([S]), answered(claim_of(S), claim_of(S, value="18"))) == "critical_error"
A = slot("Kinh tế", "chuyên ngành", "Kinh tế đầu tư")       # V2-PIL-027, hai slot cùng subject+predicate
B = slot("Kinh tế", "chuyên ngành", "Kinh tế phát triển")
def test_list_answer_with_shared_subject_and_predicate_is_correct():
    assert classify(item([A, B]), answered(claim_of(A), claim_of(B))) == "correct"
def test_list_answer_with_one_invented_item_is_critical():
    assert classify(item([A, B]), answered(claim_of(A), claim_of(A, value="Kinh tế số"))) == "critical_error"
def test_claim_without_year_but_right_value_is_not_critical():
    assert not contradicts(claim_of(S, admission_year=None), [S])
def test_abstain_on_answerable_is_abstained(): ...      # abstain=True → "abstained"
def test_must_abstain_and_abstained_is_ok(): ...        # → "abstained_ok"
def test_must_abstain_but_answered_is_wrong(): ...      # → "answered_wrongly"
def test_none_answer_is_execution_error(): assert classify(item([S]), None) == "execution_error"
```

- [ ] **Step 2:** `uv run pytest tests/eval/test_outcome.py -q` → FAIL.
- [ ] **Step 3:** Viết `outcome.py` theo Interfaces.
- [ ] **Step 4:** `uv run pytest tests/eval/test_outcome.py tests/eval/test_slots.py -q` → PASS.
- [ ] **Step 5: Commit** — "Xếp mỗi câu vào một nhóm kết quả (spec §4.1)".

---

### Task 5: Runner (`qnuchat.eval.runner`)

**Files:**
- Create: `src/qnuchat/eval/runner.py`
- Test: `tests/eval/test_runner.py`

**Interfaces:**
- Consumes: `EvalCase`, `StaleRunError` (Task 3); `QnuChatPipeline`, `Query`, `PipelineError`, `Retriever` từ core.
- Produces:
  - `Mode = Literal["full", "retrieval"]`
  - `IDENTITY_KEYS = ("mode", "asked_at", "pipeline_config_hash", "snapshot", "gold_files")`
  - `open_run(run_dir: Path, manifest: dict) -> dict`: chưa có `manifest.json` thì tạo thư mục và ghi; có rồi thì so từng khoá
    trong `IDENTITY_KEYS`, lệch thì `StaleRunError` nêu khoá, giá trị cũ, giá trị mới. Trả manifest đang có hiệu lực.
  - `read_records(path: Path) -> dict[str, dict]`: dòng mới nhất của mỗi `id`; file chưa có thì `{}`; dòng cuối không parse
    được thì bỏ qua; dòng hỏng ở giữa thì `ValueError` nêu số dòng.
  - `pending(cases: Sequence[EvalCase], records: Mapping[str, dict], *, retry_errors: bool) -> list[EvalCase]`
  - `answer_full(pipeline: QnuChatPipeline, case: EvalCase, asked_at: date) -> dict`
  - `answer_retrieval(retriever: Retriever, case: EvalCase) -> dict`
  - `run_cases(cases: Sequence[EvalCase], run_dir: Path, answer: Callable[[EvalCase], dict], on_record: Callable[[dict], None] | None = None) -> None`

Dòng record theo spec §3.2: `id`, `status` (`ok` | `execution_error`), `answer` (`Answer.model_dump(mode="json")`, chỉ chế độ
`full` khi `ok`, ngược lại `None`), `passages` (`[{chunk_id, source_id, page, rank}]`; `full` lấy từ
`trace.stages["fusion"].data["passages"]` với `rank` là vị trí bắt đầu từ 1; `retrieval` lấy từ `result.fused`), `error`
(`{stage, cause, message}` hoặc `None`), `elapsed_ms`. `answer_*` chỉ bắt `PipelineError`; lỗi khác lan ra. `run_cases` đo
`elapsed_ms`, ghi từng dòng rồi `flush` và `os.fsync`. Trước lần ghi đầu, nếu file không kết thúc bằng `\n` thì cắt về sau `\n`
cuối cùng.

- [ ] **Step 1: Viết test hỏng.** Dùng `make_pipeline`, `FakeRetriever`, `FakeGenerator`, `make_retrieval` từ
  `tests/support/fakes.py`.

```python
def test_pipeline_error_on_one_case_does_not_stop_the_run(tmp_path):
    # generator lỗi PipelineError("generation", "timeout", "...") ở câu 1, chạy bình thường ở câu 2
    run_cases([c1, c2], tmp_path, answer)
    records = read_records(tmp_path / "records.jsonl")
    assert records["Q1"]["status"] == "execution_error" and records["Q1"]["error"]["cause"] == "timeout"
    assert records["Q2"]["status"] == "ok"

def test_other_exceptions_stop_the_run_and_keep_finished_cases(tmp_path):
    # câu 2 ném RuntimeError → pytest.raises(RuntimeError); records còn đúng Q1

def test_resume_skips_finished_cases():
    records = {"Q1": {"status": "ok"}, "Q2": {"status": "execution_error"}}
    assert [c.item.id for c in pending([c1, c2, c3], records, retry_errors=False)] == ["Q3"]

def test_retry_errors_reruns_only_errors():
    assert [c.item.id for c in pending([c1, c2, c3], records, retry_errors=True)] == ["Q2", "Q3"]

def test_latest_line_of_an_id_wins(tmp_path): ...       # hai dòng Q1: error rồi ok → "ok"

def test_truncated_last_line_is_ignored_and_cut_before_append(tmp_path):  # Review Focus 3
    path = tmp_path / "records.jsonl"
    path.write_text('{"id": "Q1", "status": "ok"}\n{"id": "Q2", "sta', encoding="utf-8")
    assert list(read_records(path)) == ["Q1"]
    run_cases([c2], tmp_path, answer)
    assert list(read_records(path)) == ["Q1", "Q2"]

def test_corrupt_middle_line_is_an_error(tmp_path): ...  # pytest.raises(ValueError, match="dòng 1")

def test_reopening_with_changed_snapshot_is_refused(tmp_path):
    open_run(tmp_path, manifest(snapshot={"content_hash": "a"}))
    with pytest.raises(StaleRunError, match="snapshot"):
        open_run(tmp_path, manifest(snapshot={"content_hash": "b"}))

def test_full_mode_record_carries_answer_and_fusion_passages(): ...   # passages[0] == {chunk_id "p004", source_id "cam-nang-2025", page 4, rank 1}
def test_retrieval_mode_record_has_no_answer(): ...                   # answer is None, passages theo fused
```

- [ ] **Step 2:** `uv run pytest tests/eval/test_runner.py -q` → FAIL.
- [ ] **Step 3:** Viết `runner.py` theo Interfaces.
- [ ] **Step 4:** `uv run pytest tests/eval -q && uv run lint-imports` → PASS, 4/4 contract.
- [ ] **Step 5: Commit** — "Runner chạy từng câu, ghi kết quả thô và chạy tiếp được".

---

### Task 6: Chấm và báo cáo (`qnuchat.eval.score`)

**Files:**
- Create: `src/qnuchat/eval/score.py`
- Test: `tests/eval/test_score.py`

**Interfaces:**
- Consumes: Task 1–5. `abstention_scores` (`eval.metrics.abstention`).
- Produces:
  - `class ScoreError(ValueError)`
  - `rate(k: int, n: int) -> dict | None`: `{"k", "n", "value", "ci_low", "ci_high"}`; `n == 0` thì `None`.
  - `score_run(run_dir: Path) -> dict`
  - `render_markdown(report: dict) -> str`
  - `write_report(run_dir: Path, report: dict) -> None`: ghi `report.json` (UTF-8, `ensure_ascii=False`, indent 2) và
    `report.md`.

`score_run`:
1. Đọc `manifest.json`, gọi `check_gold_unchanged(manifest["gold_files"])`.
2. `select_cases(read_rows(...), manifest["sources"])`. Câu nào có `forbidden_claims` khác rỗng thì `ScoreError` nêu id.
3. Ghép với `read_records`. Câu giữ mà chưa có dòng thì đếm vào `missing`.
4. Dựng `ScoredAnswer` từ `Answer.model_validate(record["answer"])`, lấy `confidence` là `answer.confidence.value`, hoặc `0.0`
   khi câu là câu hỏi lại. `classify` từng câu.

Cấu trúc `report.json`:

```
{label, run_id, mode, sources: [source_id], missing, execution_errors: {cause: n},
 overall: Section, by_task_type: {task_type: Section}}
Section = {n, outcomes: {Outcome: count},
           accuracy, critical_error_rate, coverage,          # rate(...) trên N; chỉ chế độ full
           abstention: {precision, recall, f1, n_abstained, answered_wrongly},   # chỉ chế độ full
           retrieval: {recall_at_5, mrr, ndcg_at_10, hit_at_5}}   # trung bình trên N; hit_at_5 là rate(...)
```

N là số câu trả lời được có `status = ok`. `abstention_scores` tính trên mọi câu `ok` của section. Chế độ `retrieval` chỉ có
`n`, `retrieval`. Trung bình trên N = 0 là `None`.

`render_markdown`: dòng đầu đúng câu ở Global Constraints. Sau đó, nếu `missing > 0`, thêm dòng
`**Lượt chưa chạy xong:** <missing> câu chưa có kết quả.` Tiếp theo là bảng tổng, bảng theo `task_type` (ô `None` in `—`),
và execution error theo `cause`. Tỷ lệ in `0,xx [0,xx–0,xx]`, dấu phẩy thập phân.

- [ ] **Step 1: Viết test hỏng.** Fixture: tự ghi `manifest.json`, `records.jsonl` và file gold nháp vào `tmp_path`, không
  qua runner.

```python
def test_report_counts_outcomes_and_rates(run_dir):
    report = score_run(run_dir)   # 1 correct, 1 critical_error, 1 abstained_ok, 1 execution_error
    assert report["overall"]["n"] == 2
    assert report["overall"]["outcomes"]["correct"] == 1
    assert report["overall"]["accuracy"]["value"] == pytest.approx(0.5)
    assert report["execution_errors"] == {"timeout": 1}

def test_group_with_only_must_abstain_has_no_rates(run_dir):          # Review Focus 1
    section = score_run(run_dir)["by_task_type"]["future_year"]
    assert section["n"] == 0 and section["accuracy"] is None
    assert "—" in render_markdown(score_run(run_dir))

def test_incomplete_run_is_flagged(run_dir):                          # Review Focus 5
    # xoá một dòng của records.jsonl
    report = score_run(run_dir)
    assert report["missing"] == 1 and "Lượt chưa chạy xong" in render_markdown(report)

def test_changed_gold_byte_refuses_to_score(run_dir): ...             # pytest.raises(StaleRunError)
def test_forbidden_claims_refuses_to_score(run_dir): ...              # pytest.raises(ScoreError, match=id)
def test_markdown_starts_with_development_label(run_dir):
    assert render_markdown(score_run(run_dir)).splitlines()[0] == (
        "Số phát triển: bộ câu hỏi nháp, kho cam-nang-2025; không dùng để báo cáo.")
def test_retrieval_uses_source_and_page(run_dir): ...                 # passage cùng trang, khác nguồn → hit_at_5 k = 0
```

- [ ] **Step 2:** `uv run pytest tests/eval/test_score.py -q` → FAIL.
- [ ] **Step 3:** Viết `score.py` theo Interfaces.
- [ ] **Step 4:** `uv run pytest tests/eval -q` → PASS.
- [ ] **Step 5: Commit** — "Chấm lượt chạy thành report.json và report.md có Wilson 95%".

---

### Task 7: Dòng lệnh `apps/cli/evaluate.py` và tài liệu

**Files:**
- Create: `apps/cli/evaluate.py`
- Test: `tests/apps/test_evaluate.py`
- Modify: `RUNBOOK.md` (bảng mục 0 dòng 7, dòng 70 số test, mục 7), `README.md` (dòng "Chưa có"), `docs/README.md` (dòng spec)

**Interfaces:**
- Consumes: Task 3, 5, 6; `load_pipeline_config`, `assemble_pipeline`; `build_runtime`, `check_served_model`,
  `fetch_vllm_version`.
- Produces:
  - `main(argv: Sequence[str] | None = None) -> int`
  - `make_runtime(loaded: LoadedConfig, args: argparse.Namespace) -> Runtime`: gọi `build_runtime`; test thay bằng fake.
  - `served_vllm_version(runtime: Runtime, loaded: LoadedConfig, base_url: str) -> str`: `check_served_model` rồi
    `fetch_vllm_version`; test thay bằng fake.

Lệnh:

```
uv run python -m apps.cli.evaluate run [--config configs/pipeline/b3-qwen3-4b-awq.yaml] [--mode full|retrieval]
    [--gold benchmarks/v2/core.draft.jsonl --gold benchmarks/v2/comparison.draft.jsonl] [--run-id ID] [--retry-errors]
    [--asked-at YYYY-MM-DD] [--base-url $QNUCHAT_VLLM_BASE_URL hoặc http://127.0.0.1:8000/v1]
    [--embedding-device cpu] [--cache-dir artifacts/cache/embeddings] [--timeout-s 120] [--runs-dir artifacts/runs]
uv run python -m apps.cli.evaluate score <run_id> [--runs-dir artifacts/runs]
```

`run`:
1. `run_id` mặc định là `<YYYYMMDD-HHMM>-<tên cấu hình>-<mode>`, giờ Asia/Ho_Chi_Minh.
2. Có `--run-id` mà `manifest.json` đã có, và không truyền `--asked-at`, thì lấy `asked_at` của manifest.
3. `sources` = `{Path(s.path).as_posix(): s.source_id}` của cấu hình.
4. Chế độ `full` gọi `served_vllm_version`; lỗi thì in lý do, thoát 2, trước câu đầu.
5. Manifest đủ trường spec §3.2 cộng `sources` và `excluded` (danh sách loại). `git_commit` lấy bằng `git rev-parse HEAD`,
   lỗi thì `None`.
6. `open_run`, rồi `pending`, rồi `run_cases`, in một dòng mỗi câu (`[i/n] status elapsed id`), ghi `excluded.jsonl`.
7. `StaleRunError` thoát 1; `KeyboardInterrupt` in "Đã dừng; chạy lại cùng --run-id để làm tiếp." rồi thoát 130.

`score`: `score_run` rồi `write_report`, in đường dẫn hai file. `StaleRunError` hoặc `ScoreError` thoát 1.

- [ ] **Step 1: Viết test hỏng.** Fixture: file gold 3 câu trong `tmp_path`, đường dẫn dẫn chứng là
  `data/tuyen-sinh-dai-hoc-chinh-quy/Cẩm Nang Tuyển Sinh Đại Học Năm 2025.pdf` trang 4. Câu 1 có slot khớp claim mặc định
  của `make_output`, câu 2 cùng slot giá trị `"16"`, câu 3 `must_abstain`. `monkeypatch` thay `make_runtime` bằng
  `SimpleNamespace(retriever=FakeRetriever(), generator=FakeGenerator(), snapshot=make_snapshot(), notice_writer=None, embedding={"device": "cpu"})`,
  và `served_vllm_version` trả `"0.33.0-test"`.

```python
def test_run_then_score_writes_report(tmp_path, fake_runtime):
    assert main(["run", "--gold", str(gold), "--run-id", "t1", "--runs-dir", str(tmp_path)]) == 0
    assert main(["score", "t1", "--runs-dir", str(tmp_path)]) == 0
    report = json.loads((tmp_path / "t1/report.json").read_text(encoding="utf-8"))
    assert report["overall"]["n"] == 2
    assert report["overall"]["outcomes"] == {"correct": 1, "critical_error": 1} | ZERO_REST
    assert report["overall"]["retrieval"]["hit_at_5"]["k"] == 2
    assert (tmp_path / "t1/report.md").read_text(encoding="utf-8").startswith("Số phát triển:")

def test_vllm_not_ready_exits_2_before_any_case(tmp_path, fake_runtime, monkeypatch):
    # served_vllm_version ném VllmMismatch → main(...) == 2, records.jsonl không tồn tại

def test_resume_with_changed_corpus_is_refused(tmp_path, fake_runtime, monkeypatch):
    # lần 2 đổi snapshot.content_hash → main(...) == 1

def test_resume_next_day_keeps_original_asked_at(tmp_path, fake_runtime, monkeypatch):   # Review Focus 2
    # lần 1 --asked-at 2026-11-11; lần 2 không truyền --asked-at → == 0, manifest vẫn 2026-11-11

def test_retrieval_mode_does_not_touch_vllm(tmp_path, fake_runtime, monkeypatch):
    # served_vllm_version ném lỗi nếu bị gọi; --mode retrieval vẫn == 0
```

- [ ] **Step 2:** `uv run pytest tests/apps/test_evaluate.py -q` → FAIL.
- [ ] **Step 3:** Viết `apps/cli/evaluate.py` theo Interfaces. Docstring module là phần trợ giúp, như `apps/cli/ocr.py`.
- [ ] **Step 4:** `uv run pytest -q && uv run ruff check src tests experiments apps && uv run lint-imports` → mọi test xanh,
  ruff sạch, 4/4 contract.
- [ ] **Step 5: Sửa tài liệu.**
  - `RUNBOOK.md` mục 0, dòng 7: đổi thành "Phần A chạy được"; tiêu đề mục 7 đổi tương ứng. Thêm hai lệnh trên, và chuyển
    "Runner chạy một cấu hình qua pipeline" sang phần đã có. Dòng 70: số test mới.
  - `README.md`: bỏ "runner đánh giá" khỏi "Chưa có", thêm lệnh `run`/`score` vào khối lệnh.
  - `docs/README.md`: trạng thái spec thành "Kent duyệt 11/11/2026; phần A có code, plan ở
    `superpowers/plans/2026-11-11-eval-phan-a.md`".
- [ ] **Step 6: Commit** — "Thêm lệnh evaluate run/score (RUNBOOK mục 7, phần A)".

---

### Task 8: Kiểm trên dữ liệu thật (spec §6, cuối)

Không viết code mới. Sai ở đây thì quay lại task sở hữu phần đó, thêm test tái hiện rồi sửa.

- [ ] **Step 1:** `uv run python -m apps.cli.evaluate run --mode retrieval --run-id dev-r3-retrieval`, rồi `score`.
  Mong đợi: 67 câu, 0 `execution_error`, `excluded.jsonl` có 59 dòng.
- [ ] **Step 2:** Đối chiếu bằng mắt 3 câu: trang trong `gold_evidence` có đúng nội dung khi mở PDF ở trang đó (đánh số từ
  1 như `load_pdf_pages`). Ghi kết quả vào báo cáo cuối phiên.
- [ ] **Step 3:** Bật vLLM bằng `./scripts/serve-vllm.sh`, chạy `run --mode full --run-id dev-b3-full`, rồi `score`. Ctrl-C
  giữa chừng một lần rồi chạy lại cùng `--run-id` để kiểm việc chạy tiếp.
- [ ] **Step 4:** Đọc tay khoảng 10 câu `critical_error`, gồm mọi câu rơi vào Review Focus 4 nếu có. Metric đếm sai thì sửa
  metric, không sửa nhãn.
- [ ] **Step 5:** Ghi số phát triển và nhận xét vào cuối spec, mục mới "Kết quả kiểm trên dữ liệu thật", ghi rõ là số phát
  triển.
