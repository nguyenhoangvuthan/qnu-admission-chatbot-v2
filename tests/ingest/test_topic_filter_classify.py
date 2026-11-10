from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from qnuchat.ingest.topic_filter.classifier import TopicExecutionError, TopicVerdict
from qnuchat.ingest.topic_filter.classify import run_classify
from qnuchat.ingest.topic_filter.ledger import TopicDecision, TopicLedger
from tests.support.webstore import W, WebStore, png_bytes

TZ = ZoneInfo("Asia/Ho_Chi_Minh")
NEWS = f"{W}/vi/tin/hoi-thao"
FEES = f"{W}/vi/hoc-phi"
U2 = f"{W}/vi/tin/khac"
IMG_NEWS = f"{W}/Temp/hoi-thao.jpg"
IMG_FEES = f"{W}/Temp/hoc-phi.jpg"
PDF_NEWS = f"{W}/Resources/Docs/de-an-tuyen-sinh.pdf"


class FakeClassifier:
    def __init__(self, labels: dict[str, str], errors: dict[str, str] | None = None):
        self.labels = labels
        self.errors = dict(errors or {})
        self.calls: list[str] = []

    def classify(self, inp):
        self.calls.append(inp.url)
        if inp.url in self.errors:
            raise TopicExecutionError(self.errors.pop(inp.url))
        label = self.labels.get(inp.url, "giu")
        return TopicVerdict(label, None, "khong_lien_quan" if label == "loai" else None, "ghi chú")


@pytest.fixture
def kb_store(tmp_path):
    web = WebStore(tmp_path)
    for url in (NEWS, FEES, U2):
        web.put(url, title=url)
    web.put(IMG_NEWS, kind="image", page_url=NEWS, data=png_bytes(10, 10), quarantine=True)
    web.put(IMG_FEES, kind="image", page_url=FEES, data=png_bytes(11, 11), quarantine=True)
    web.put(PDF_NEWS, kind="file", page_url=NEWS, data=b"%PDF-1", quarantine=True)
    return web, TopicLedger(tmp_path / "topic.jsonl", repair=True)


def run(web, ledger, classifier, **kwargs):
    current = web.current()
    order = [current[u] for u in (FEES, NEWS, U2, PDF_NEWS, IMG_FEES, IMG_NEWS)]
    return run_classify(
        current=current,
        candidates=order,
        classifier=classifier,
        ledger=ledger,
        blobs=web.blobs,
        prompt_hash="p1",
        filter_id="f1",
        model="Qwen/Qwen3-4B-AWQ",
        model_revision="rev",
        max_chars=1500,
        now=lambda: datetime(2026, 10, 23, 1, 0, tzinfo=TZ),
        out=lambda line: None,
        **kwargs,
    )


def test_each_candidate_gets_one_model_decision_with_prompt_hash(kb_store):
    web, ledger = kb_store
    classifier = FakeClassifier({})
    counts = run(web, ledger, classifier)
    assert len(classifier.calls) == 6 and counts["giu"] == 6
    current = web.current()
    d = ledger.current(FEES, current[FEES].sha256)
    assert (d.label, d.pass_, d.filter_id, d.decided_by, d.model_revision) == (
        "giu",
        1,
        "f1",
        "model",
        "rev",
    )
    assert d.at == "2026-10-23T01:00:00+07:00"


def test_rerun_skips_done_items_and_retries_errors(kb_store):
    web, ledger = kb_store
    run(web, ledger, FakeClassifier({}, errors={U2: "timeout"}))
    d = ledger.current(U2, web.current()[U2].sha256)
    assert d.label is None and d.error_cause == "timeout"
    again = FakeClassifier({})
    run(web, ledger, again)
    assert again.calls == [U2]


def test_images_on_a_loai_page_are_not_sent_to_the_model_but_files_are(kb_store):
    web, ledger = kb_store
    classifier = FakeClassifier({NEWS: "loai"})
    counts = run(web, ledger, classifier)
    assert IMG_NEWS not in classifier.calls and PDF_NEWS in classifier.calls
    assert IMG_FEES in classifier.calls
    assert counts["follows_page"] == 1
    assert ledger.current(IMG_NEWS, web.current()[IMG_NEWS].sha256) is None


def test_blob_missing_is_recorded_as_error_not_loai(kb_store):
    web, ledger = kb_store
    sha = web.current()[U2].sha256
    web.blobs.delete(sha)
    classifier = FakeClassifier({})
    counts = run(web, ledger, classifier)
    d = ledger.current(U2, sha)
    assert d.label is None and d.error_cause == "blob_missing"
    assert U2 not in classifier.calls and counts["error"] == 1


def test_limit_stops_after_n_model_calls(kb_store):
    web, ledger = kb_store
    classifier = FakeClassifier({})
    run(web, ledger, classifier, limit=2)
    assert classifier.calls == [FEES, NEWS]


def test_classify_walks_candidates_through_the_progress_tracker(kb_store):
    web, ledger = kb_store
    tracked = []

    def track(items):
        tracked.extend(items)
        return iter(items)

    run(web, ledger, FakeClassifier({}), track=track)
    assert len(tracked) == 6


def test_model_never_overrides_a_kent_label(kb_store):
    web, ledger = kb_store
    entry = web.current()[NEWS]
    ledger.append(
        TopicDecision(
            url=NEWS,
            sha256=entry.sha256,
            pass_=1,
            label="giu",
            group=None,
            reason=None,
            note="",
            prompt_hash="",
            filter_id="kent",
            model="",
            model_revision="",
            error_cause=None,
            decided_by="kent",
            at="2026-11-06T01:00:00+07:00",
        )
    )
    classifier = FakeClassifier({NEWS: "loai"})
    counts = run(web, ledger, classifier)
    assert NEWS not in classifier.calls and counts["skipped_kent"] == 1
    assert ledger.current(NEWS, entry.sha256).label == "giu"
