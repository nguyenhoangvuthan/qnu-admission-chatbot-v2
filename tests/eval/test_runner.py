"""Runner chạy từng câu, ghi kết quả thô và chạy tiếp được (spec phần A §3.2, plan Task 5)."""

import json

import pytest

from qnuchat.core.errors import PipelineError
from qnuchat.eval.cases import EvalCase, StaleRunError
from qnuchat.eval.runner import (
    IDENTITY_KEYS,
    answer_full,
    answer_retrieval,
    open_run,
    pending,
    read_records,
    run_cases,
)
from qnuchat.eval.schema import GoldItem
from tests.support.fakes import (
    TODAY,
    FakeGenerator,
    FakeRetriever,
    make_pipeline,
)


def case(id: str, must_abstain: bool = False) -> EvalCase:
    item = GoldItem(
        id=id, question=f"Học phí ngành CNTT ({id})?", origin="curated", risk="normal",
        admission_year=2025, must_abstain=must_abstain, gold_page_ids=[],
        expected_slots=[], required_conditions=[], forbidden_claims=[],
        source_family="fam", reviewer="",
    )
    return EvalCase(item=item, task_type="lookup", gold_evidence=(("cam-nang-2025", 4),))


c1, c2, c3 = case("Q1"), case("Q2"), case("Q3")


class FailFirstGenerator(FakeGenerator):
    """Lần gọi đầu ném PipelineError (vd. vLLM timeout), các lần sau chạy bình thường."""

    def generate(self, question, passages):
        if not self.calls:
            self.calls.append((question, list(passages)))
            raise PipelineError("generation", "timeout", "vLLM quá 120 giây")
        return super().generate(question, passages)


def full_answer(pipeline):
    return lambda c: answer_full(pipeline, c, TODAY)


def manifest(**overrides) -> dict:
    fields = {
        "run_id": "t1",
        "mode": "full",
        "label": "phát triển",
        "asked_at": "2026-11-11",
        "pipeline_config_hash": "h" * 64,
        "snapshot": {"id": "s", "content_hash": "a", "vector_hash": "v"},
        "gold_files": [{"path": "g.jsonl", "sha256": "0" * 64}],
        "created_at": "2026-11-11T15:00:00+07:00",
    }
    fields.update(overrides)
    return fields


def lines(path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]


# --- run_cases -------------------------------------------------------------


def test_pipeline_error_on_one_case_does_not_stop_the_run(tmp_path):
    pipeline = make_pipeline(generator=FailFirstGenerator())
    run_cases([c1, c2], tmp_path, full_answer(pipeline))
    records = read_records(tmp_path / "records.jsonl")
    assert records["Q1"]["status"] == "execution_error"
    assert records["Q1"]["error"] == {
        "stage": "generation", "cause": "timeout", "message": "vLLM quá 120 giây",
    }
    assert records["Q1"]["answer"] is None
    assert records["Q2"]["status"] == "ok"


def test_other_exceptions_stop_the_run_and_keep_finished_cases(tmp_path):
    ok = full_answer(make_pipeline())

    def answer(c):
        if c.item.id == "Q2":
            raise RuntimeError("lỗi lập trình")
        return ok(c)

    with pytest.raises(RuntimeError):
        run_cases([c1, c2, c3], tmp_path, answer)
    assert list(read_records(tmp_path / "records.jsonl")) == ["Q1"]


def test_each_record_has_id_and_elapsed_ms_and_is_reported(tmp_path):
    seen: list[dict] = []
    run_cases([c1, c2], tmp_path, full_answer(make_pipeline()), on_record=seen.append)
    written = lines(tmp_path / "records.jsonl")
    assert [r["id"] for r in written] == ["Q1", "Q2"]
    assert all(r["elapsed_ms"] >= 0 for r in written)
    assert set(written[0]) == {"id", "status", "answer", "passages", "error", "elapsed_ms"}
    assert seen == written


def test_truncated_last_line_is_ignored_and_cut_before_append(tmp_path):  # Review Focus 3
    path = tmp_path / "records.jsonl"
    path.write_text('{"id": "Q1", "status": "ok"}\n{"id": "Q2", "sta', encoding="utf-8")
    assert list(read_records(path)) == ["Q1"]
    run_cases([c2], tmp_path, full_answer(make_pipeline()))
    assert list(read_records(path)) == ["Q1", "Q2"]
    assert [r["id"] for r in lines(path)] == ["Q1", "Q2"]


def test_truncated_only_line_is_cut_to_empty_file(tmp_path):
    path = tmp_path / "records.jsonl"
    path.write_text('{"id": "Q1", "st', encoding="utf-8")
    assert read_records(path) == {}
    run_cases([c2], tmp_path, full_answer(make_pipeline()))
    assert [r["id"] for r in lines(path)] == ["Q2"]


# --- read_records ----------------------------------------------------------


def test_valid_json_last_line_without_newline_is_unfinished(tmp_path):  # Review Focus 3
    # Ghi dở có thể dừng đúng trước "\n": dòng parse được nhưng chưa xong. `read_records` phải
    # hiểu "dòng dở" giống `_cut_partial_tail`, nếu không Q2 bị cắt mà cũng không được chạy lại.
    path = tmp_path / "records.jsonl"
    path.write_text('{"id": "Q1", "status": "ok"}\n{"id": "Q2", "status": "ok"}', encoding="utf-8")
    assert list(read_records(path)) == ["Q1"]
    run_cases([c2], tmp_path, full_answer(make_pipeline()))
    assert [r["id"] for r in lines(path)] == ["Q1", "Q2"]


def test_missing_records_file_is_empty(tmp_path):
    assert read_records(tmp_path / "records.jsonl") == {}


def test_latest_line_of_an_id_wins(tmp_path):
    path = tmp_path / "records.jsonl"
    path.write_text(
        '{"id": "Q1", "status": "execution_error"}\n'
        '{"id": "Q2", "status": "ok"}\n'
        '{"id": "Q1", "status": "ok"}\n',
        encoding="utf-8",
    )
    records = read_records(path)
    assert records["Q1"]["status"] == "ok" and list(records) == ["Q1", "Q2"]


def test_corrupt_middle_line_is_an_error(tmp_path):
    path = tmp_path / "records.jsonl"
    path.write_text('{"id": "Q1", "sta\n{"id": "Q2", "status": "ok"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="dòng 1"):
        read_records(path)


def test_corrupt_last_line_that_was_fully_written_is_an_error(tmp_path):
    # Mỗi dòng ghi một lần kèm "\n"; dòng đã có "\n" mà hỏng không phải do bị cắt giữa chừng.
    path = tmp_path / "records.jsonl"
    path.write_text('{"id": "Q1", "status": "ok"}\n{"id": "Q2", "sta\n', encoding="utf-8")
    with pytest.raises(ValueError, match="dòng 2"):
        read_records(path)


# --- pending ---------------------------------------------------------------

RECORDS = {"Q1": {"status": "ok"}, "Q2": {"status": "execution_error"}}


def test_resume_skips_finished_cases():
    assert [c.item.id for c in pending([c1, c2, c3], RECORDS, retry_errors=False)] == ["Q3"]


def test_retry_errors_reruns_only_errors():
    assert [c.item.id for c in pending([c1, c2, c3], RECORDS, retry_errors=True)] == ["Q2", "Q3"]


def test_resume_does_not_call_finished_cases_again(tmp_path):
    generator = FakeGenerator()
    answer = full_answer(make_pipeline(generator=generator))
    run_cases([c1], tmp_path, answer)
    records = read_records(tmp_path / "records.jsonl")
    run_cases(pending([c1, c2], records, retry_errors=False), tmp_path, answer)
    assert [q for q, _ in generator.calls] == [c1.item.question, c2.item.question]


# --- open_run --------------------------------------------------------------


def test_identity_keys_follow_plan():
    assert IDENTITY_KEYS == ("mode", "asked_at", "pipeline_config_hash", "snapshot", "gold_files")


def test_open_run_creates_directory_and_manifest(tmp_path):
    run_dir = tmp_path / "runs" / "t1"
    assert open_run(run_dir, manifest()) == manifest()
    saved = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert saved == manifest() and saved["label"] == "phát triển"


def test_reopening_with_same_identity_keeps_original_manifest(tmp_path):
    open_run(tmp_path, manifest())
    effective = open_run(tmp_path, manifest(created_at="2026-11-12T09:00:00+07:00"))
    assert effective["created_at"] == "2026-11-11T15:00:00+07:00"


def test_reopening_with_changed_snapshot_is_refused(tmp_path):
    open_run(tmp_path, manifest(snapshot={"content_hash": "a"}))
    with pytest.raises(StaleRunError, match="snapshot"):
        open_run(tmp_path, manifest(snapshot={"content_hash": "b"}))


def test_refusal_names_old_and_new_value(tmp_path):
    open_run(tmp_path, manifest())
    with pytest.raises(StaleRunError, match="2026-11-11.*2026-11-12"):
        open_run(tmp_path, manifest(asked_at="2026-11-12"))


# --- answer_full / answer_retrieval ---------------------------------------


def test_full_mode_record_carries_answer_and_fusion_passages():
    record = answer_full(make_pipeline(), c1, TODAY)
    assert record["id"] == "Q1" and record["status"] == "ok" and record["error"] is None
    assert record["answer"]["claims"][0]["value"] == "15"
    assert record["answer"]["trace"]["asked_at"] == TODAY.isoformat()
    assert record["passages"][0] == {
        "chunk_id": "p004", "source_id": "cam-nang-2025", "page": 4, "rank": 1,
    }
    assert [p["rank"] for p in record["passages"]] == [1, 2]


def test_full_mode_record_is_json_serialisable():
    json.dumps(answer_full(make_pipeline(), c1, TODAY), ensure_ascii=False)


def test_full_mode_error_keeps_passages_reached_before_failure():
    generator = FakeGenerator(error=PipelineError("generation", "bad_json", "x"))
    record = answer_full(make_pipeline(generator=generator), c1, TODAY)
    assert record["status"] == "execution_error" and record["answer"] is None
    assert [p["chunk_id"] for p in record["passages"]] == ["p004", "p005"]


def test_full_mode_error_in_retrieval_has_no_passages():
    retriever = FakeRetriever(error=PipelineError("retrieval", "timeout", "x"))
    record = answer_full(make_pipeline(retriever=retriever), c1, TODAY)
    assert record["status"] == "execution_error" and record["passages"] == []
    assert record["error"]["stage"] == "retrieval"


def test_retrieval_mode_record_has_no_answer():
    retriever = FakeRetriever()
    record = answer_retrieval(retriever, c1)
    assert record["status"] == "ok" and record["answer"] is None and record["error"] is None
    assert record["passages"] == [
        {"chunk_id": "p004", "source_id": "cam-nang-2025", "page": 4, "rank": 1},
        {"chunk_id": "p005", "source_id": "cam-nang-2025", "page": 5, "rank": 2},
    ]
    assert retriever.calls == [c1.item.question]


def test_retrieval_mode_pipeline_error_is_execution_error():
    retriever = FakeRetriever(error=PipelineError("retrieval", "timeout", "embedding quá lâu"))
    record = answer_retrieval(retriever, c1)
    assert record["status"] == "execution_error" and record["passages"] == []
    assert record["error"] == {
        "stage": "retrieval", "cause": "timeout", "message": "embedding quá lâu",
    }


def test_retrieval_mode_other_exception_propagates():
    with pytest.raises(KeyError):
        answer_retrieval(FakeRetriever(error=KeyError("x")), c1)
