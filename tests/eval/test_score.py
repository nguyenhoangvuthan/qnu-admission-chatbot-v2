"""Chấm lượt chạy thành report.json và report.md (spec phần A §4, plan Task 6).

Fixture tự ghi `manifest.json`, `records.jsonl` và file gold nháp, không qua runner. `answer` được
dựng bằng pipeline thật với generator giả, nên luôn đúng contract `Answer` hiện hành.
"""

import json

import pytest

from qnuchat.core.contracts import Claim
from qnuchat.eval.cases import StaleRunError, gold_digests
from qnuchat.eval.schema import ExpectedSlot, GoldItem
from qnuchat.eval.score import ScoreError, rate, render_markdown, score_run, write_report
from qnuchat.eval.stats import wilson_interval
from tests.support.fakes import FakeGenerator, make_output, make_pipeline, make_query

SOURCE_PATH = "data/tuyen-sinh-dai-hoc-chinh-quy/Cẩm Nang Tuyển Sinh Đại Học Năm 2025.pdf"
SOURCES = {SOURCE_PATH: "cam-nang-2025"}
HERE = ("cam-nang-2025", 4)


def gold_row(
    id: str,
    task_type: str = "lookup",
    *,
    value: str = "15",
    must_abstain: bool = False,
    forbidden: tuple[str, ...] = (),
) -> dict:
    slot = ExpectedSlot(
        subject="ngành CNTT", predicate="học phí", value=value, unit="triệu đồng",
        admission_year=2025,
    )
    item = GoldItem(
        id=id, question=f"Học phí ngành CNTT ({id})?", origin="curated", risk="normal",
        admission_year=2025, must_abstain=must_abstain, gold_page_ids=[],
        expected_slots=[] if must_abstain else [slot], required_conditions=[],
        forbidden_claims=list(forbidden), source_family="fam", reviewer="",
    )
    return {
        "item": item.model_dump(mode="json"),
        "task_type": task_type,
        "gold_evidence": [] if must_abstain else [[SOURCE_PATH, 4]],
    }


def answer_json(**overrides) -> dict:
    """`Answer` thật của pipeline; mặc định claim học phí CNTT = 15 triệu đồng, năm 2025."""
    pipeline = make_pipeline(generator=FakeGenerator(make_output(**overrides)))
    return pipeline.answer(make_query()).model_dump(mode="json")


ABSTAIN = {
    "answer": "Tài liệu chưa có thông tin này.",
    "abstain": True,
    "abstain_reason": "MODEL_SELF",
    "claims": [],
    "citation_ids": [],
}


def ok(id: str, answer: dict | None, pages=(HERE,)) -> dict:
    return {
        "id": id,
        "status": "ok",
        "answer": answer,
        "passages": [
            {"chunk_id": f"c{rank}", "source_id": source, "page": page, "rank": rank}
            for rank, (source, page) in enumerate(pages, start=1)
        ],
        "error": None,
        "elapsed_ms": 1.0,
    }


def failed(id: str, cause: str = "timeout") -> dict:
    return {
        "id": id,
        "status": "execution_error",
        "answer": None,
        "passages": [],
        "error": {"stage": "generation", "cause": cause, "message": "vLLM quá 120 giây"},
        "elapsed_ms": 1.0,
    }


def default_rows() -> list[dict]:
    return [
        gold_row("Q1"),                                  # trả lời đúng
        gold_row("Q2", value="16"),                      # claim 15 ≠ gold 16 → critical_error
        gold_row("Q3", "future_year", must_abstain=True),  # từ chối đúng
        gold_row("Q4"),                                  # lỗi chạy
    ]


def default_records() -> list[dict]:
    correct = answer_json()
    return [
        ok("Q1", correct),
        ok("Q2", correct),
        ok("Q3", answer_json(**ABSTAIN), pages=()),
        failed("Q4"),
    ]


def write_records(run_dir, records) -> None:
    text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
    (run_dir / "records.jsonl").write_text(text, encoding="utf-8")


def make_run(tmp_path, rows=None, records=None, mode="full"):
    gold = tmp_path / "gold.jsonl"
    rows = default_rows() if rows is None else rows
    gold.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )
    run_dir = tmp_path / "runs" / "t1"
    run_dir.mkdir(parents=True)
    manifest = {
        "run_id": "t1",
        "mode": mode,
        "label": "phát triển",
        "asked_at": "2026-11-11",
        "sources": SOURCES,
        "gold_files": gold_digests([gold]),
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_records(run_dir, default_records() if records is None else records)
    return run_dir


@pytest.fixture
def run_dir(tmp_path):
    return make_run(tmp_path)


# --- rate ------------------------------------------------------------------


def test_rate_carries_value_and_wilson_interval():
    low, high = wilson_interval(1, 4)
    assert rate(1, 4) == {"k": 1, "n": 4, "value": 0.25, "ci_low": low, "ci_high": high}


def test_rate_of_empty_sample_is_none():
    assert rate(0, 0) is None


# --- score_run -------------------------------------------------------------


def test_report_counts_outcomes_and_rates(run_dir):
    report = score_run(run_dir)  # 1 correct, 1 critical_error, 1 abstained_ok, 1 execution_error
    assert report["overall"]["n"] == 2
    assert report["overall"]["outcomes"] == {
        "correct": 1, "critical_error": 1, "incomplete": 0, "abstained": 0,
        "abstained_ok": 1, "answered_wrongly": 0, "execution_error": 1,
    }
    assert report["overall"]["accuracy"]["value"] == pytest.approx(0.5)
    assert report["overall"]["critical_error_rate"]["k"] == 1
    assert report["overall"]["coverage"]["value"] == pytest.approx(1.0)
    assert report["execution_errors"] == {"timeout": 1}


def _run_with_text_critical(tmp_path):
    """Thêm Q5: slot chữ "Cử nhân", claim giả trả "15" → critical_error ở slot chữ."""
    rows = [*default_rows(), gold_row("Q5", value="Cử nhân")]
    return make_run(tmp_path, rows=rows, records=[*default_records(), ok("Q5", answer_json())])


def test_critical_errors_split_by_value_kind(tmp_path):
    report = score_run(_run_with_text_critical(tmp_path))
    assert report["overall"]["critical_error_kinds"] == {"number": 1, "text": 1}
    assert report["overall"]["critical_error_text_ids"] == ["Q5"]


def test_markdown_lists_text_critical_errors_for_hand_reading(tmp_path):
    markdown = render_markdown(score_run(_run_with_text_critical(tmp_path)))
    assert "| Lỗi nghiêm trọng: slot số | 1 |" in markdown
    assert "| Lỗi nghiêm trọng: chỉ slot chữ | 1 |" in markdown
    assert "Q5" in markdown.split("## Lỗi nghiêm trọng ở slot chữ")[1]


def test_correct_is_scored_on_answer_text_and_claim_match_reported_separately(tmp_path):
    # Q5: claim không ghi năm, unit rỗng, predicate khác gold; câu trả lời chữ vẫn nêu đúng 15.
    rows = [*default_rows(), gold_row("Q5")]
    claim = Claim(subject="ngành CNTT", predicate="mức học phí", value="15", unit="")
    loose = answer_json(claims=[claim])
    run = make_run(tmp_path, rows=rows, records=[*default_records(), ok("Q5", loose)])
    overall = score_run(run)["overall"]
    assert overall["outcomes"]["correct"] == 2  # Q1, Q5
    assert (overall["claim_match"]["k"], overall["claim_match"]["n"]) == (1, 3)  # chỉ Q1
    assert "| Claim khớp | 0,33 [" in render_markdown(score_run(run))


def test_precision_and_f1_are_undefined_when_nothing_was_abstained(tmp_path):
    rows = [gold_row("Q1"), gold_row("Q3", "future_year", must_abstain=True)]
    correct = answer_json()
    run = make_run(tmp_path, rows=rows, records=[ok("Q1", correct), ok("Q3", correct)])
    abstention = score_run(run)["overall"]["abstention"]
    assert abstention["n_abstained"] == 0
    assert abstention["precision"] is None and abstention["f1"] is None
    assert abstention["recall"] == 0.0
    assert "| Từ chối: precision | — |" in render_markdown(score_run(run))


def test_f1_is_undefined_when_group_has_no_must_abstain_case(tmp_path):
    run = make_run(tmp_path, rows=[gold_row("Q1")], records=[ok("Q1", answer_json(**ABSTAIN))])
    abstention = score_run(run)["overall"]["abstention"]
    assert abstention["recall"] is None and abstention["f1"] is None


def test_report_header_fields(run_dir):
    report = score_run(run_dir)
    assert report["label"] == "phát triển"
    assert report["run_id"] == "t1" and report["mode"] == "full"
    assert report["sources"] == ["cam-nang-2025"]
    assert report["missing"] == 0


def test_execution_error_is_not_counted_as_abstention(run_dir):
    abstention = score_run(run_dir)["overall"]["abstention"]
    assert abstention["n_abstained"] == 1  # chỉ Q3; Q4 lỗi chạy không phải từ chối
    assert abstention["precision"] == pytest.approx(1.0)
    assert abstention["recall"] == pytest.approx(1.0)
    assert abstention["answered_wrongly"] == 0


def test_sections_split_by_task_type(run_dir):
    by_type = score_run(run_dir)["by_task_type"]
    assert sorted(by_type) == ["future_year", "lookup"]
    assert by_type["lookup"]["n"] == 2
    assert by_type["lookup"]["outcomes"]["execution_error"] == 1


def test_group_with_only_must_abstain_has_no_rates(run_dir):  # Review Focus 1
    section = score_run(run_dir)["by_task_type"]["future_year"]
    assert section["n"] == 0 and section["accuracy"] is None
    assert section["critical_error_rate"] is None and section["coverage"] is None
    assert section["retrieval"] == {
        "recall_at_5": None, "mrr": None, "ndcg_at_10": None, "hit_at_5": None,
    }
    assert "—" in render_markdown(score_run(run_dir))


def test_incomplete_run_is_flagged(run_dir):  # Review Focus 5
    write_records(run_dir, [r for r in default_records() if r["id"] != "Q2"])
    report = score_run(run_dir)
    assert report["missing"] == 1
    assert report["overall"]["n"] == 1
    assert "**Lượt chưa chạy xong:** 1 câu chưa có kết quả." in render_markdown(report)


def test_finished_run_is_not_flagged(run_dir):
    assert "Lượt chưa chạy xong" not in render_markdown(score_run(run_dir))


def test_changed_gold_byte_refuses_to_score(run_dir):
    gold = run_dir.parents[1] / "gold.jsonl"
    gold.write_bytes(gold.read_bytes() + b"\n")
    with pytest.raises(StaleRunError, match="gold.jsonl"):
        score_run(run_dir)


def test_forbidden_claims_refuses_to_score(tmp_path):
    rows = default_rows()
    rows[1] = gold_row("Q2", value="16", forbidden=("Học phí miễn phí",))
    run_dir = make_run(tmp_path, rows=rows)
    with pytest.raises(ScoreError, match="Q2"):
        score_run(run_dir)


def test_ok_record_without_answer_in_full_mode_is_a_score_error(tmp_path):
    records = default_records()
    records[0] = ok("Q1", None)
    with pytest.raises(ScoreError, match="Q1"):
        score_run(make_run(tmp_path, records=records))


def test_clarification_answer_scores_with_zero_confidence(tmp_path):
    clarification = answer_json()
    clarification.update(
        abstain=False, claims=[], citation_ids=[], confidence=None,
        answer="Bạn muốn hỏi học phí của ngành nào?",
        clarification={"slot": "major", "prompt": "Bạn muốn hỏi ngành nào?", "options": []},
    )
    records = default_records()
    records[0] = ok("Q1", clarification)
    report = score_run(make_run(tmp_path, records=records))
    assert report["overall"]["outcomes"]["incomplete"] == 1


def test_retrieval_uses_source_and_page(tmp_path):
    records = default_records()
    for record in records:
        for passage in record["passages"]:
            passage["source_id"] = "nguon-khac"  # cùng trang 4, khác nguồn
    retrieval = score_run(make_run(tmp_path, records=records))["overall"]["retrieval"]
    assert retrieval["hit_at_5"]["k"] == 0
    assert retrieval["recall_at_5"] == 0.0 and retrieval["mrr"] == 0.0


def test_retrieval_metrics_average_over_answerable_ok_cases(tmp_path):
    records = default_records()
    records[1] = ok("Q2", answer_json(), pages=(("cam-nang-2025", 9), HERE))
    retrieval = score_run(make_run(tmp_path, records=records))["overall"]["retrieval"]
    assert retrieval["hit_at_5"]["k"] == 2 and retrieval["hit_at_5"]["n"] == 2
    assert retrieval["mrr"] == pytest.approx((1.0 + 0.5) / 2)
    assert retrieval["recall_at_5"] == pytest.approx(1.0)


def test_retrieval_mode_has_only_n_and_retrieval(tmp_path):
    records = [ok("Q1", None), ok("Q2", None, pages=()), ok("Q3", None, pages=()), failed("Q4")]
    report = score_run(make_run(tmp_path, records=records, mode="retrieval"))
    assert report["mode"] == "retrieval"
    assert set(report["overall"]) == {"n", "retrieval"}
    assert report["overall"]["n"] == 2
    assert report["overall"]["retrieval"]["hit_at_5"]["k"] == 1
    assert report["execution_errors"] == {"timeout": 1}
    assert render_markdown(report).startswith("Số phát triển:")


# --- render_markdown, write_report -----------------------------------------


def test_markdown_starts_with_development_label(run_dir):
    assert render_markdown(score_run(run_dir)).splitlines()[0] == (
        "Số phát triển: bộ câu hỏi nháp, kho cam-nang-2025; không dùng để báo cáo."
    )


def test_markdown_prints_rates_with_decimal_comma_and_interval(run_dir):
    low, high = wilson_interval(1, 2)
    expected = f"0,50 [{low:.2f}–{high:.2f}]".replace(".", ",")
    markdown = render_markdown(score_run(run_dir))
    assert expected in markdown
    assert "0.50" not in markdown


def test_markdown_lists_execution_errors_by_cause(run_dir):
    assert "| timeout | 1 |" in render_markdown(score_run(run_dir))


def test_write_report_writes_valid_json_and_markdown(run_dir):
    report = score_run(run_dir)
    write_report(run_dir, report)

    def no_nan(constant):
        raise AssertionError(f"report.json có {constant}, không phải JSON hợp lệ")

    text = (run_dir / "report.json").read_text(encoding="utf-8")
    assert "phát triển" in text  # ensure_ascii=False
    assert json.loads(text, parse_constant=no_nan) == report
    assert (run_dir / "report.md").read_text(encoding="utf-8") == render_markdown(report)
