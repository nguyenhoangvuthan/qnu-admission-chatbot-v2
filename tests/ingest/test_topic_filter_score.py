import csv
import json

import pytest

from apps.cli.knowledge_base import main
from qnuchat.ingest.topic_filter.ledger import TopicDecision, TopicLedger
from qnuchat.ingest.topic_filter.score import load_labels, score, wilson_upper

HEADER = ["item_id", "url", "sha256", "label", "reviewer", "at"]
IDS = {"filter_id": "p1", "prompt_hash": "p1", "model_revision": "rev"}


def sample_rows(n: int) -> list[dict]:
    return [
        {
            "item_id": f"S{i:03d}",
            "url": f"u{i}",
            "sha256": f"s{i}",
            "kind": "page",
            "host_group": "www",
            "round": 1,
        }
        for i in range(1, n + 1)
    ]


def kent(rows, giu: int) -> list[dict]:
    return [{**r, "label": "giu" if i < giu else "loai"} for i, r in enumerate(rows)]


def ledger_with(tmp_path, rows, model_labels: dict[str, str | None], prompt="p1") -> TopicLedger:
    ledger = TopicLedger(tmp_path / "topic.jsonl", repair=True)
    for r in rows:
        label = model_labels.get(r["item_id"], "giu")
        ledger.append(
            TopicDecision(
                url=r["url"],
                sha256=r["sha256"],
                pass_=1,
                label=label,
                group=None,
                reason=None,
                note="",
                prompt_hash=prompt,
                filter_id=prompt,
                model="m",
                model_revision="rev",
                error_cause=None if label else "timeout",
                decided_by="model",
                at="2026-10-23T01:00:00+07:00",
            )
        )
    return ledger


def report(tmp_path, n, giu, model_labels):
    """Kent gán `giu` cho `giu` mục đầu, `loai` cho phần còn lại;
    model đồng ý với Kent trừ các mục trong `model_labels`."""
    rows = sample_rows(n)
    labels = {**{r["item_id"]: "loai" for r in rows[giu:]}, **model_labels}
    ledger = ledger_with(tmp_path, rows, labels)
    return score(rows, kent(rows, giu), ledger, **IDS)


def test_wilson_upper_matches_the_threshold_boundary():
    assert wilson_upper(0, 73) <= 0.05 < wilson_upper(0, 72)
    assert round(wilson_upper(0, 100), 4) == 0.037
    assert wilson_upper(0, 0) == 1.0


def test_zero_misses_in_100_giu_passes(tmp_path):
    r = report(tmp_path, 200, 100, {})
    assert r.passed and r.kent_giu == 100 and r.model_loai_in_giu == 0 and r.reasons == []


def test_zero_misses_in_60_giu_fails_on_the_upper_bound(tmp_path):
    r = report(tmp_path, 200, 60, {})
    assert not r.passed and r.loai_rate == 0
    assert any("cận trên" in reason for reason in r.reasons)


def test_one_miss_in_100_giu_fails_on_the_upper_bound(tmp_path):
    r = report(tmp_path, 200, 100, {"S001": "loai"})
    assert r.loai_rate == 0.01 and r.loai_upper > 0.05 and not r.passed


def test_khong_chac_above_15_percent_fails(tmp_path):
    r = report(tmp_path, 200, 100, {f"S{i:03d}": "khong_chac" for i in range(1, 32)})
    assert r.khong_chac == 31 and r.khong_chac_rate == 0.155 and not r.passed
    assert any("khong_chac" in reason for reason in r.reasons)


def test_items_with_only_errors_or_no_decision_fail(tmp_path):
    rows = sample_rows(200)
    ledger = ledger_with(tmp_path, rows[:199], {"S001": None})
    r = score(rows, kent(rows, 100), ledger, **IDS)
    assert (r.errors, r.missing) == (1, 1) and not r.passed
    assert any("classify" in reason for reason in r.reasons)


def test_decisions_of_another_filter_are_ignored(tmp_path):
    rows = sample_rows(200)
    ledger = ledger_with(tmp_path, rows, {}, prompt="p2")
    r = score(rows, kent(rows, 100), ledger, **IDS)
    assert r.missing == 200 and not r.passed


def write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=HEADER)
        writer.writeheader()
        writer.writerows(rows)


def csv_rows(rows):
    return [
        {
            "item_id": r["item_id"],
            "url": r["url"],
            "sha256": r["sha256"],
            "label": "giu",
            "reviewer": "Kent",
            "at": "2026-10-23T01:00:00Z",
        }
        for r in rows
    ]


def test_good_labels_csv_loads(tmp_path):
    rows = sample_rows(3)
    write_csv(tmp_path / "labels.csv", csv_rows(rows))
    assert [x["label"] for x in load_labels(tmp_path / "labels.csv", rows)] == ["giu"] * 3


@pytest.mark.parametrize(
    "problem, line",
    [
        ("missing_row", "S003"),
        ("bad_label", "dòng 2"),
        ("unknown_item", "dòng 5"),
        ("duplicate", "dòng 5"),
        ("no_reviewer", "dòng 3"),
        ("wrong_sha", "dòng 2"),
    ],
)
def test_bad_labels_csv_is_refused_naming_the_row(tmp_path, problem, line):
    rows = sample_rows(3)
    data = csv_rows(rows)
    if problem == "missing_row":
        data = data[:2]
    elif problem == "bad_label":
        data[0]["label"] = "khong_chac"
    elif problem == "unknown_item":
        data.append({**data[0], "item_id": "S999"})
    elif problem == "duplicate":
        data.append(dict(data[0]))
    elif problem == "no_reviewer":
        data[1]["reviewer"] = ""
    elif problem == "wrong_sha":
        data[0]["sha256"] = "khac"
    write_csv(tmp_path / "labels.csv", data)
    with pytest.raises(ValueError, match=line):
        load_labels(tmp_path / "labels.csv", rows)


def test_cli_writes_score_json_and_copies_labels(tmp_path, monkeypatch):
    rows = sample_rows(80)
    sample_dir = tmp_path / "sample-1"
    sample_dir.mkdir()
    (sample_dir / "round-1.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )
    write_csv(tmp_path / "labels.csv", csv_rows(rows))
    prompt = tmp_path / "prompt.md"
    prompt.write_text("PROMPT", encoding="utf-8")
    from apps.cli.knowledge_base import KnowledgeBaseSettings, current_filter

    data_dir = tmp_path / "web"
    monkeypatch.setenv("QNUCHAT_CRAWL_DATA_DIR", str(data_dir))
    monkeypatch.setenv("QNUCHAT_TOPIC_PROMPT", str(prompt))
    monkeypatch.setenv("QNUCHAT_TOPIC_FILTER_DIR", str(tmp_path / "out"))
    fid, p_hash, _ = current_filter(KnowledgeBaseSettings())
    ledger_with(data_dir, rows, {}, prompt=fid)
    labels = str(tmp_path / "labels.csv")
    code = main(["topic-score", "--sample", str(sample_dir), "--labels", labels])
    assert code == 0
    out = tmp_path / "out" / fid[:12]
    result = json.loads((out / "score.json").read_text(encoding="utf-8"))
    assert result["passed"] is True and result["filter_id"] == fid
    assert result["prompt_hash"] == p_hash
    assert result["kent_giu"] == 80 and (out / "labels.csv").exists()


def test_sampled_image_on_a_loai_page_counts_as_model_loai(tmp_path):
    rows = sample_rows(200)
    rows[0] = {**rows[0], "kind": "image", "page_url": "trang-cha"}
    ledger = ledger_with(tmp_path, rows[1:], {})
    ledger.append(
        TopicDecision(
            url="trang-cha",
            sha256="sp",
            pass_=1,
            label="loai",
            group=None,
            reason="khong_lien_quan",
            note="",
            prompt_hash="p1",
            filter_id="p1",
            model="m",
            model_revision="rev",
            error_cause=None,
            decided_by="model",
            at="2026-10-23T01:00:00+07:00",
        )
    )
    r = score(rows, kent(rows, 100), ledger, **IDS)
    assert r.missing == 0 and r.model_loai_in_giu == 1
