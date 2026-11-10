import json
from datetime import UTC, date, datetime

import pytest

from apps.cli.knowledge_base import main
from qnuchat.ingest import crawl_job as job
from qnuchat.ingest.config import CrawlConfig, Limits
from qnuchat.ingest.manifest import Manifest
from qnuchat.ingest.state import CheckState
from qnuchat.ingest.topic_filter.ledger import TopicDecision, TopicLedger, load_topic_policy
from tests.support.webstore import W, WebStore, png_bytes

SEED = f"{W}/vi/tuyen-sinh"
NEWS = f"{W}/vi/tin/hoi-thao"
FEES = f"{W}/vi/hoc-phi"
IMG = f"{W}/Temp/hoi-thao.jpg"
KEPT_IMG = f"{W}/Temp/bang-diem.jpg"
NOW = datetime(2026, 11, 6, 2, 0, tzinfo=UTC)
CFG = CrawlConfig(
    seeds=[SEED],
    host_suffix=".qnu.edu.vn",
    tier_a=[SEED],
    pii_title_skip=[],
    limits=Limits(rps_per_host=1000, hosts_parallel=2, max_file_mb=5, timeout_s=5, retries=0),
    user_agent="UA {contact}",
)


@pytest.fixture
def web(tmp_path):
    store = WebStore(tmp_path)
    store.put(SEED, title="Tuyển sinh", tier="A")
    store.put(NEWS, title="Hội thảo")
    store.put(FEES, title="Học phí")
    store.put(IMG, kind="image", page_url=NEWS, data=png_bytes(10, 10), text_status="text")
    store.put(KEPT_IMG, kind="image", page_url=NEWS, data=png_bytes(11, 11), text_status="text")
    return store


def decide(web, url, label, *, filter_id="f1", decided_by="model", error=None):
    ledger = TopicLedger(web.root / "topic.jsonl", repair=True)
    ledger.append(
        TopicDecision(
            url=url,
            sha256=web.current()[url].sha256,
            pass_=1,
            label=label,
            group=None,
            reason=None,
            note="",
            prompt_hash="p",
            filter_id=filter_id,
            model="m",
            model_revision="r",
            error_cause=error,
            decided_by=decided_by,
            at="2026-11-06T01:00:00+07:00",
        )
    )


def approve(web, filter_id="f1"):
    path = web.root / "scores" / filter_id
    path.mkdir(parents=True, exist_ok=True)
    (path / "score.json").write_text(
        json.dumps({"passed": True, "filter_id": filter_id}), encoding="utf-8"
    )


def prune(web):
    topic = load_topic_policy(web.root / "topic.jsonl", web.root / "scores")
    job.prune(
        data_dir=web.root,
        cfg=CFG,
        config_hash="h",
        today=date(2026, 11, 6),
        now=lambda: NOW,
        topic=topic,
        out=lambda line: None,
    )
    return Manifest(web.root / "manifest.jsonl", repair=False)


def test_loai_of_an_approved_filter_is_withdrawn_with_its_images(web):
    sha = web.current()[NEWS].sha256
    decide(web, NEWS, "loai")
    approve(web)
    manifest = prune(web)
    assert manifest.latest(NEWS).reason == "off_topic"
    assert manifest.latest(IMG).reason == "off_topic"
    assert FEES in manifest.current()
    assert web.blobs.path(sha) is None


def test_image_labelled_giu_survives_its_page(web):
    decide(web, NEWS, "loai")
    decide(web, KEPT_IMG, "giu")
    approve(web)
    assert KEPT_IMG in prune(web).current()


def test_unmeasured_filter_removes_nothing(web):
    decide(web, NEWS, "loai")
    assert NEWS in prune(web).current()


def test_kent_label_is_applied_without_a_measured_filter(web):
    decide(web, NEWS, "loai", filter_id="kent", decided_by="kent")
    assert NEWS not in prune(web).current()


def test_execution_error_never_removes_an_item(web):
    decide(web, NEWS, None, error="timeout")
    approve(web)
    assert NEWS in prune(web).current()


def test_tier_a_is_exempt_even_when_labelled_loai(web):
    decide(web, SEED, "loai")
    approve(web)
    assert SEED in prune(web).current()


def test_prune_deletes_the_ocr_text_of_a_withdrawn_item(web):
    sha = web.current()[IMG].sha256
    documents = web.root / "ocr" / "documents"
    pages = web.root / "ocr" / "pages"
    documents.mkdir(parents=True)
    pages.mkdir(parents=True)
    (documents / f"{sha}.json").write_text("{}", encoding="utf-8")
    (pages / f"{sha}-p0001.json").write_text("{}", encoding="utf-8")
    decide(web, NEWS, "loai")
    approve(web)
    prune(web)
    assert list(documents.iterdir()) == [] and list(pages.iterdir()) == []


def test_preview_lists_what_prune_will_withdraw(web):
    decide(web, NEWS, "loai")
    approve(web)
    topic = load_topic_policy(web.root / "topic.jsonl", web.root / "scores")
    state = CheckState(web.root / "last_checked.json")
    exempt = job.prune_exempt(CFG)
    chosen = job.topic_withdrawals(web.current(), topic, exempt=exempt, state=state)
    assert {e.url for e in chosen} == {NEWS, IMG, KEPT_IMG}
    current = prune(web).current()
    assert not {e.url for e in chosen} & set(current)


def test_cli_labels_write_kent_decisions_that_prune_applies(web, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("QNUCHAT_CRAWL_DATA_DIR", str(web.root))
    sample = tmp_path / "sample"
    sample.mkdir()
    row = {"item_id": "S001", "url": NEWS, "sha256": web.current()[NEWS].sha256, "round": 1}
    (sample / "round-1.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    labels = tmp_path / "labels.csv"
    labels.write_text(
        f"item_id,url,sha256,label,reviewer,at\nS001,{NEWS},{row['sha256']},loai,Kent,2026-11-06\n",
        encoding="utf-8",
    )
    code = main(["topic-labels", "--sample", str(sample), "--labels", str(labels)])
    assert code == 0 and "1 loai" in capsys.readouterr().out
    assert NEWS not in prune(web).current()
