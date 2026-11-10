import json
from pathlib import Path

import pytest

from qnuchat.ingest.topic_filter.ledger import (
    TopicDecision,
    TopicLedger,
    filter_id,
    load_topic_config,
    load_topic_policy,
    prompt_hash,
)

ROOT = Path(__file__).resolve().parents[2]


def decision(**overrides) -> TopicDecision:
    fields = {
        "url": "u1",
        "sha256": "s1",
        "pass_": 1,
        "label": "giu",
        "group": None,
        "reason": None,
        "note": "",
        "prompt_hash": "p1",
        "filter_id": "f1",
        "model": "Qwen/Qwen3-4B-AWQ",
        "model_revision": "74d4bd2bd4bff9cafc9345221320bffb08b406a3",
        "error_cause": None,
        "decided_by": "model",
        "at": "2026-10-22T10:00:00+07:00",
    }
    fields.update(overrides)
    return TopicDecision(**fields)


def test_latest_line_per_url_and_sha_is_current(tmp_path):
    ledger = TopicLedger(tmp_path / "topic.jsonl", repair=True)
    ledger.append(decision(url="u1", sha256="s1", label="giu"))
    ledger.append(decision(url="u1", sha256="s1", label="loai", decided_by="kent"))
    ledger.append(decision(url="u1", sha256="s2", label="giu"))
    assert ledger.current("u1", "s1").label == "loai"
    assert ledger.current("u1", "s2").label == "giu"
    assert ledger.current("u2", "s1") is None
    assert TopicLedger(tmp_path / "topic.jsonl").current("u1", "s1").decided_by == "kent"


def test_json_uses_pass_not_pass_underscore(tmp_path):
    path = tmp_path / "topic.jsonl"
    TopicLedger(path, repair=True).append(decision(pass_=2))
    row = json.loads(path.read_text(encoding="utf-8"))
    assert row["pass"] == 2 and "pass_" not in row
    assert TopicLedger(path).entries()[0].pass_ == 2


def test_done_ignores_error_lines_and_other_filters(tmp_path):
    ledger = TopicLedger(tmp_path / "topic.jsonl", repair=True)
    ledger.append(decision(label=None, error_cause="timeout", filter_id="f1"))
    assert not ledger.done("u1", "s1", filter_id="f1")
    ledger.append(decision(label="giu", filter_id="f1"))
    assert ledger.done("u1", "s1", filter_id="f1")
    assert not ledger.done("u1", "s1", filter_id="f2")


def test_filter_id_changes_with_model_revision_inputs_and_pass():
    base = {
        "prompt_hash": "p1",
        "model": "Qwen/Qwen3-4B-AWQ",
        "model_revision": "r1",
        "max_chars": 1500,
        "max_tokens": 256,
        "pass_": 1,
    }
    first = filter_id(**base)
    assert first == filter_id(**base) and len(first) == 64
    for key, value in [
        ("model", "khac"),
        ("model_revision", "r2"),
        ("max_chars", 1000),
        ("max_tokens", 128),
        ("pass_", 2),
        ("prompt_hash", "p2"),
    ]:
        assert filter_id(**{**base, key: value}) != first


def test_policy_ignores_loai_of_another_filter_even_with_the_same_prompt(tmp_path):
    ledger = TopicLedger(tmp_path / "topic.jsonl", repair=True)
    ledger.append(decision(label="loai", filter_id="f-model-moi"))
    scores = tmp_path / "scores" / "f1"
    scores.mkdir(parents=True)
    (scores / "score.json").write_text(
        json.dumps({"passed": True, "filter_id": "f1", "prompt_hash": "p1"}), encoding="utf-8"
    )
    policy = load_topic_policy(tmp_path / "topic.jsonl", tmp_path / "scores")
    assert not policy.withdraws("u1", "s1")
    ledger.append(decision(label="loai", filter_id="f1"))
    assert load_topic_policy(tmp_path / "topic.jsonl", tmp_path / "scores").withdraws("u1", "s1")


def test_truncated_last_line_is_skipped(tmp_path):
    path = tmp_path / "topic.jsonl"
    TopicLedger(path, repair=True).append(decision())
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"url": "u2", "sha2')
    ledger = TopicLedger(path)
    assert [d.url for d in ledger.entries()] == ["u1"]
    assert path.read_text(encoding="utf-8").endswith('"sha2')  # người chỉ đọc không sửa file


def test_writer_repairs_a_torn_last_line_before_appending(tmp_path):
    path = tmp_path / "topic.jsonl"
    TopicLedger(path, repair=True).append(decision())
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"url": "u2", "sha2')
    TopicLedger(path, repair=True).append(decision(url="u3"))
    assert [d.url for d in TopicLedger(path).entries()] == ["u1", "u3"]


def test_read_only_ledger_refuses_to_append(tmp_path):
    with pytest.raises(RuntimeError):
        TopicLedger(tmp_path / "topic.jsonl").append(decision())


def test_missing_ledger_file_is_empty(tmp_path):
    assert TopicLedger(tmp_path / "khong-co.jsonl").entries() == []


def test_prompt_hash_is_sha256_of_the_file_bytes(tmp_path):
    path = tmp_path / "p.md"
    path.write_bytes(b"abc")
    assert prompt_hash(path) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_topic_config_rejects_unknown_keys(tmp_path):
    path = tmp_path / "c.yaml"
    text = (ROOT / "configs/knowledge_base/topic_filter.yaml").read_text(encoding="utf-8")
    path.write_text(text + "\nthua: 1\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_topic_config(path)


def test_shipped_topic_config_loads():
    cfg = load_topic_config(ROOT / "configs/knowledge_base/topic_filter.yaml")
    assert (cfg.max_chars, cfg.max_tokens, cfg.sample_size, cfg.sample_seed) == (
        1500,
        256,
        200,
        20261022,
    )
    assert cfg.host_groups["tuyensinh"] == ["tuyensinh"]
    assert "kcntt" in cfg.host_groups["khoa"]
