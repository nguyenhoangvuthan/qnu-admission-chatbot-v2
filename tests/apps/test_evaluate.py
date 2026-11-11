"""Lệnh `evaluate run` và `evaluate score` (spec phần A, plan Task 7).

Runtime thật (BGE-M3, vLLM) được thay bằng fake qua `make_runtime` và `served_vllm_version`, nên
test chạy không cần GPU hay mạng.
"""

import json
from types import SimpleNamespace

import pytest

from apps.cli import evaluate
from apps.cli.evaluate import main
from qnuchat.adapters.generation.vllm_checks import VllmMismatch
from qnuchat.eval.schema import ExpectedSlot, GoldItem
from qnuchat.eval.score import OUTCOMES
from tests.support.fakes import FakeGenerator, FakeRetriever, make_snapshot

SOURCE_PATH = "data/tuyen-sinh-dai-hoc-chinh-quy/Cẩm Nang Tuyển Sinh Đại Học Năm 2025.pdf"
ZERO = dict.fromkeys(OUTCOMES, 0)


def gold_row(id: str, *, value: str = "15", must_abstain: bool = False, source=SOURCE_PATH):
    slot = ExpectedSlot(
        subject="ngành CNTT", predicate="học phí", value=value, unit="triệu đồng",
        admission_year=2025,
    )
    item = GoldItem(
        id=id, question=f"Học phí ngành CNTT ({id})?", origin="curated", risk="normal",
        admission_year=2025, must_abstain=must_abstain, gold_page_ids=[],
        expected_slots=[] if must_abstain else [slot], required_conditions=[],
        forbidden_claims=[], source_family="fam", reviewer="",
    )
    return {
        "item": item.model_dump(mode="json"),
        "task_type": "future_year" if must_abstain else "lookup",
        "gold_evidence": [] if must_abstain else [[source, 4]],
    }


def write_gold(path, rows) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")


@pytest.fixture
def gold(tmp_path):
    """Ba câu: claim của `make_output` khớp câu 1, sai giá trị câu 2; câu 3 phải từ chối."""
    path = tmp_path / "gold.draft.jsonl"
    rows = [gold_row("Q1"), gold_row("Q2", value="16"), gold_row("Q3", must_abstain=True)]
    write_gold(path, rows)
    return path


def fake_runtime_for(generator=None, snapshot=None):
    return SimpleNamespace(
        retriever=FakeRetriever(),
        generator=generator or FakeGenerator(),
        snapshot=snapshot or make_snapshot(),
        notice_writer=None,
        embedding={"device": "cpu"},
    )


@pytest.fixture
def fake_runtime(monkeypatch):
    runtime = fake_runtime_for()
    monkeypatch.setattr(evaluate, "make_runtime", lambda loaded, args: runtime)
    monkeypatch.setattr(evaluate, "served_vllm_version", lambda runtime, loaded, url: "0.33.0-test")
    return runtime


def run_args(gold, tmp_path, *extra: str) -> list[str]:
    return ["run", "--gold", str(gold), "--run-id", "t1", "--runs-dir", str(tmp_path), *extra]


def read_manifest(tmp_path) -> dict:
    return json.loads((tmp_path / "t1/manifest.json").read_text(encoding="utf-8"))


def test_run_then_score_writes_report(tmp_path, gold, fake_runtime):
    assert main(run_args(gold, tmp_path)) == 0
    assert main(["score", "t1", "--runs-dir", str(tmp_path)]) == 0
    report = json.loads((tmp_path / "t1/report.json").read_text(encoding="utf-8"))
    assert report["overall"]["n"] == 2
    # Generator giả trả cùng một claim cho mọi câu, nên câu phải từ chối bị trả lời.
    assert report["overall"]["outcomes"] == ZERO | {
        "correct": 1, "critical_error": 1, "answered_wrongly": 1,
    }
    assert report["overall"]["retrieval"]["hit_at_5"]["k"] == 2
    assert (tmp_path / "t1/report.md").read_text(encoding="utf-8").startswith("Số phát triển:")


def test_manifest_records_identity_and_provenance(tmp_path, gold, fake_runtime):
    assert main(run_args(gold, tmp_path, "--asked-at", "2026-11-11")) == 0
    manifest = read_manifest(tmp_path)
    assert manifest["label"] == "phát triển"
    assert manifest["run_id"] == "t1" and manifest["mode"] == "full"
    assert manifest["asked_at"] == "2026-11-11"
    assert manifest["pipeline_config_name"] == "b3-qwen3-4b-awq"
    assert len(manifest["pipeline_config_hash"]) == 64
    assert manifest["snapshot"] == make_snapshot().model_dump(mode="json")
    assert manifest["gold_files"][0]["path"] == gold.as_posix()
    assert manifest["sources"] == {SOURCE_PATH: "cam-nang-2025"}
    assert manifest["cases"] == {"kept": 3, "excluded": 0}
    assert manifest["vllm_version"] == "0.33.0-test"
    assert manifest["embedding"]["device"] == "cpu"
    assert manifest["generator"]["model"] == "Qwen/Qwen3-4B-AWQ"


def test_excluded_cases_are_written_with_reason(tmp_path, gold, fake_runtime):
    rows = [json.loads(line) for line in gold.read_text(encoding="utf-8").splitlines()]
    write_gold(gold, [*rows, gold_row("Q4", source="data/khac.pdf")])
    assert main(run_args(gold, tmp_path)) == 0
    lines = (tmp_path / "t1/excluded.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["id"] for line in lines] == ["Q4"]
    assert json.loads(lines[0])["reason"] == "source_not_in_corpus"
    assert read_manifest(tmp_path)["excluded"][0]["id"] == "Q4"


def test_vllm_not_ready_exits_2_before_any_case(tmp_path, gold, fake_runtime, monkeypatch):
    def not_ready(runtime, loaded, url):
        raise VllmMismatch("vLLM không phục vụ 'Qwen/Qwen3-4B-AWQ'")

    monkeypatch.setattr(evaluate, "served_vllm_version", not_ready)
    assert main(run_args(gold, tmp_path)) == 2
    assert not (tmp_path / "t1/records.jsonl").exists()
    assert fake_runtime.generator.calls == []


def test_resume_with_changed_corpus_is_refused(tmp_path, gold, fake_runtime, monkeypatch):
    assert main(run_args(gold, tmp_path)) == 0
    changed = make_snapshot().model_copy(update={"content_hash": "d" * 64})
    monkeypatch.setattr(
        evaluate, "make_runtime", lambda loaded, args: fake_runtime_for(snapshot=changed)
    )
    assert main(run_args(gold, tmp_path)) == 1


def test_resume_next_day_keeps_original_asked_at(tmp_path, gold, fake_runtime):
    # Ngày đã qua: nếu lượt sau lấy ngày hôm nay thì identity lệch và lượt bị từ chối.
    assert main(run_args(gold, tmp_path, "--asked-at", "2020-01-01")) == 0
    assert main(run_args(gold, tmp_path)) == 0
    assert read_manifest(tmp_path)["asked_at"] == "2020-01-01"


def test_resume_runs_only_unfinished_cases(tmp_path, gold, fake_runtime):
    assert main(run_args(gold, tmp_path)) == 0
    calls = len(fake_runtime.generator.calls)
    assert main(run_args(gold, tmp_path)) == 0
    assert len(fake_runtime.generator.calls) == calls


def test_retrieval_mode_does_not_touch_vllm(tmp_path, gold, fake_runtime, monkeypatch):
    def must_not_call(runtime, loaded, url):
        raise AssertionError("chế độ retrieval không được gọi vLLM")

    monkeypatch.setattr(evaluate, "served_vllm_version", must_not_call)
    assert main(run_args(gold, tmp_path, "--mode", "retrieval")) == 0
    assert fake_runtime.generator.calls == []
    assert main(["score", "t1", "--runs-dir", str(tmp_path)]) == 0
    report = json.loads((tmp_path / "t1/report.json").read_text(encoding="utf-8"))
    assert report["mode"] == "retrieval" and report["overall"]["retrieval"]["hit_at_5"]["k"] == 2


def test_ctrl_c_exits_130_and_keeps_finished_cases(tmp_path, gold, monkeypatch, capsys):
    runtime = fake_runtime_for(generator=FakeGenerator(error=KeyboardInterrupt()))
    monkeypatch.setattr(evaluate, "make_runtime", lambda loaded, args: runtime)
    monkeypatch.setattr(evaluate, "served_vllm_version", lambda runtime, loaded, url: "0.33.0-test")
    assert main(run_args(gold, tmp_path)) == 130
    assert "chạy lại cùng --run-id" in capsys.readouterr().err
    assert (tmp_path / "t1/manifest.json").exists()


def test_unexpected_error_wrapped_by_core_stops_the_run(tmp_path, gold, monkeypatch, capsys):
    # Core bọc mọi Exception thành PipelineError(cause="error"); đó là bug, không phải lỗi tạm như
    # timeout, nên lượt dừng ngay (spec §5) thay vì ghi execution_error cho mọi câu còn lại.
    runtime = fake_runtime_for(generator=FakeGenerator(error=RuntimeError("bug trong stage")))
    monkeypatch.setattr(evaluate, "make_runtime", lambda loaded, args: runtime)
    monkeypatch.setattr(evaluate, "served_vllm_version", lambda runtime, loaded, url: "0.33.0-test")
    assert main(run_args(gold, tmp_path)) == 1
    assert len(runtime.generator.calls) == 1
    records = (tmp_path / "t1/records.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["error"]["cause"] for line in records] == ["error"]
    err = capsys.readouterr().err
    assert "bug trong stage" in err and "--retry-errors" in err


def test_score_refuses_changed_gold(tmp_path, gold, fake_runtime):
    assert main(run_args(gold, tmp_path)) == 0
    gold.write_text(gold.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert main(["score", "t1", "--runs-dir", str(tmp_path)]) == 1
    assert not (tmp_path / "t1/report.json").exists()


def test_default_run_id_names_config_and_mode(tmp_path, gold, fake_runtime):
    runs = tmp_path / "runs"
    assert main(["run", "--gold", str(gold), "--runs-dir", str(runs), "--mode", "retrieval"]) == 0
    (run_dir,) = list(runs.iterdir())
    assert run_dir.name.endswith("-b3-qwen3-4b-awq-retrieval")
