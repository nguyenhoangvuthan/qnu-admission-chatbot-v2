import hashlib
import io
import json
import stat
import sys
from datetime import date, datetime
from pathlib import Path

import pymupdf
import pytest
from PIL import Image

from qnuchat.ingest.crawl_job import _crawl_lock
from qnuchat.ingest.manifest import Manifest, ManifestEntry
from qnuchat.ingest.ocr import job, worker

TODAY = date(2026, 11, 6)
NOW = datetime(2026, 11, 6, 10, 0)
LONG_TEXT = "Thông báo về việc xét tuyển đại học chính quy năm 2026 của Trường Đại học Quy Nhơn"
PEOPLE_ROWS = [("STT", 10), ("Họ và tên", 100), ("Ngày sinh", 300), ("Mã sinh viên", 500)]


def pdf_bytes(*texts):
    doc = pymupdf.open()
    for text in texts:
        page = doc.new_page()
        if text:
            page.insert_text((50, 100), text)
    return doc.tobytes()


def png_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), "white").save(buf, format="PNG")
    return buf.getvalue()


class Store:
    def __init__(self, root: Path):
        self.root = root
        (root / "quarantine").mkdir(parents=True)
        self.manifest = Manifest(root / "manifest.jsonl")

    def add(self, name, data, *, mime, kind="file", tier="A", label=None):
        sha = hashlib.sha256(data).hexdigest()
        (self.root / "quarantine" / sha).write_bytes(data)
        self.manifest.append(
            ManifestEntry(
                url=f"https://qnu.edu.vn/{name}",
                source_id=f"w-{name}",
                page_url=None,
                kind=kind,
                title=name,
                published=None,
                retrieved_at="2026-11-06T01:00:00+07:00",
                sha256=sha,
                mime=mime,
                bytes=len(data),
                host="qnu.edu.vn",
                tier=tier,
                text_status="needs_ocr",
                reason=None,
                crawl_run="r1",
                config_hash="h",
                sources_yaml_ref=None,
            )
        )
        if label:
            with (self.root / "people.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"sha256": sha, "label": label}) + "\n")
        return sha

    def ocr(self, sha, page, lines, rotation=0):
        out = job.pages_dir(self.root)
        out.mkdir(parents=True, exist_ok=True)
        rec = {
            "id": job.page_id(sha, page),
            "image_sha256": "anh",
            "lines": lines,
            "rotation": rotation,
            "config": worker.CONFIG,
            "env_sha256": "env",
        }
        (out / f"{job.page_id(sha, page)}.json").write_text(json.dumps(rec), encoding="utf-8")

    def failed(self, sha, page):
        out = job.pages_dir(self.root)
        out.mkdir(parents=True, exist_ok=True)
        rec = {"id": "x", "image_sha256": "anh", "error": {"kind": "cuda_oom", "message": "m"}}
        (out / f"{job.page_id(sha, page)}.json").write_text(json.dumps(rec), encoding="utf-8")

    def reload(self):
        return Manifest(self.root / "manifest.jsonl", repair=False)


def line(text, x=0, y=0):
    return {"text": text, "box": [x, y, x + 80, y + 20]}


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "web")


def fake_worker(tmp_path, body):
    script = tmp_path / "fake_worker.py"
    script.write_text(body, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return (sys.executable, str(script))


def test_plan_ocrs_only_pdf_pages_without_a_text_layer(store):
    sha = store.add("a.pdf", pdf_bytes(LONG_TEXT, ""), mime="application/pdf")
    plan = job.build_plan(store.root)
    assert [(d.sha256, d.pages) for d in plan.documents] == [(sha, (2,))]


def test_plan_groups_urls_sharing_one_file(store):
    data = pdf_bytes("")
    store.add("a.pdf", data, mime="application/pdf")
    store.add("b.pdf", data, mime="application/pdf")
    (doc,) = job.build_plan(store.root).documents
    assert len(doc.entries) == 2


@pytest.mark.parametrize(
    ("label", "planned"),
    [("co_chu", 1), ("khong_nguoi", 1), ("anh_nguoi", 0), (None, 0)],
)
def test_images_need_a_label_saying_they_are_not_people_photos(store, label, planned):
    store.add("a.png", png_bytes(), mime="image/png", kind="image", label=label)
    plan = job.build_plan(store.root)
    assert len(plan.documents) == planned
    assert len(plan.waiting_label) == 1 - planned


def test_last_label_wins_because_corrections_are_appended(store):
    sha = store.add("a.png", png_bytes(), mime="image/png", kind="image", label="anh_nguoi")
    with (store.root / "people.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"sha256": sha, "label": "co_chu"}) + "\n")
    assert len(job.build_plan(store.root).documents) == 1


def test_items_render_pdf_pages_and_keep_image_bytes_under_a_named_suffix(store, tmp_path):
    pdf = store.add("a.pdf", pdf_bytes(""), mime="application/pdf")
    png = store.add("a.png", png_bytes(), mime="image/png", kind="image", label="co_chu")
    items = job.prepare_items(job.build_plan(store.root).documents, store.root, tmp_path / "img")
    by_id = {item["id"]: item for item in items}
    assert Path(by_id[job.page_id(pdf, 1)]["path"]).read_bytes().startswith(b"\x89PNG")
    native = by_id[job.page_id(png, 1)]
    assert native["path"].endswith(".png") and native["sha256"] == png


def test_worker_events_reach_the_caller_and_noise_is_dropped(tmp_path):
    command = fake_worker(
        tmp_path,
        "print('rác của engine')\n"
        f'print({worker.PREFIX!r} + \'{{"event": "image", "ok": true}}\', flush=True)\n',
    )
    events = []
    code = job.run_worker([], tmp_path / "out", command=command, on_event=events.append)
    assert code == 0 and events == [{"event": "image", "ok": True}]


def test_worker_exit_code_is_returned(tmp_path):
    command = fake_worker(tmp_path, "raise SystemExit(4)\n")
    assert job.run_worker([], tmp_path / "out", command=command) == 4


def test_second_run_is_refused_while_the_lock_is_held(tmp_path):
    with job.ocr_lock(tmp_path), pytest.raises(job.OcrBusy), job.ocr_lock(tmp_path):
        pass


def test_assemble_keeps_text_layer_pages_and_fills_scanned_ones(store):
    sha = store.add("a.pdf", pdf_bytes(LONG_TEXT, ""), mime="application/pdf")
    store.ocr(sha, 2, [line("Học phí DO1")], rotation=270)
    (doc,) = job.build_plan(store.root).documents
    result = job.assemble(doc, store.root, today=TODAY)
    first, second = result.pages
    assert result.outcome == "text"
    assert first["source"] == "text_layer" and "chính quy" in first["text"]
    assert second["source"] == "ocr" and second["text"] == "Học phí D01"
    assert second["rotation"] == 270 and second["env_sha256"] == "env"


def test_list_of_people_found_only_after_ocr_is_flagged(store):
    sha = store.add("a.pdf", pdf_bytes(""), mime="application/pdf")
    store.ocr(sha, 1, [line(text, x=x, y=100) for text, x in PEOPLE_ROWS])
    (doc,) = job.build_plan(store.root).documents
    assert job.assemble(doc, store.root, today=TODAY).outcome == "pii"


def test_people_rows_are_flagged_even_when_the_header_was_misread(store):
    sha = store.add("a.pdf", pdf_bytes(""), mime="application/pdf")
    people = ["Nguyễn Văn An", "Trần Thị Bình", "Lê Minh Cường", "Phạm Thu Dung", "Võ Ngọc Hà"]
    lines = [line("Horten", x=100), line("Giortinin", x=300)]
    for number, name in enumerate(people, start=1):
        y = 40 * number
        lines += [line(name, x=100, y=y), line(f"0{number}/02/2005", x=300, y=y)]
    store.ocr(sha, 1, lines)
    (doc,) = job.build_plan(store.root).documents
    assert job.assemble(doc, store.root, today=TODAY).outcome == "pii"


def exclude(tmp_path, sha, *pages):
    path = tmp_path / "excluded-pages.yaml"
    path.write_text(json.dumps({sha: {"pages": list(pages), "reason": "x"}}), encoding="utf-8")
    return path


def test_excluded_page_is_not_ocred(store, tmp_path):
    sha = store.add("a.pdf", pdf_bytes("", ""), mime="application/pdf")
    (doc,) = job.build_plan(store.root, exclude(tmp_path, sha, 2)).documents
    assert doc.pages == (1,)


def test_excluded_page_stays_out_even_with_an_earlier_checkpoint(store, tmp_path):
    sha = store.add("a.pdf", pdf_bytes("", ""), mime="application/pdf")
    store.ocr(sha, 1, [line("Học phí")])
    store.ocr(sha, 2, [line("thông tin cá nhân")])
    (doc,) = job.build_plan(store.root, exclude(tmp_path, sha, 2)).documents
    result = job.assemble(doc, store.root, today=TODAY)
    assert [p["page"] for p in result.pages] == [1]


def test_excluded_text_layer_page_stays_out(store, tmp_path):
    sha = store.add("a.pdf", pdf_bytes(LONG_TEXT, ""), mime="application/pdf")
    store.ocr(sha, 2, [line("Học phí")])
    (doc,) = job.build_plan(store.root, exclude(tmp_path, sha, 1)).documents
    assert [p["page"] for p in job.assemble(doc, store.root, today=TODAY).pages] == [2]


def test_apply_deletes_the_ocr_text_of_an_excluded_page(store, tmp_path):
    sha = store.add("a.pdf", pdf_bytes("", ""), mime="application/pdf")
    store.ocr(sha, 1, [line("Học phí")])
    store.ocr(sha, 2, [line("thông tin cá nhân")])
    excluded = exclude(tmp_path, sha, 2)
    job.apply_results(store.root, today=TODAY, now=NOW, excluded_pages=excluded)
    saved = (store.root / "ocr/documents" / f"{sha}.json").read_text(encoding="utf-8")
    assert "thông tin cá nhân" not in saved
    assert not (job.pages_dir(store.root) / f"{job.page_id(sha, 2)}.json").exists()


def test_file_deleted_by_hand_is_reported_instead_of_crashing_the_plan(store):
    sha = store.add("a.pdf", pdf_bytes(""), mime="application/pdf")
    (store.root / "quarantine" / sha).unlink()
    plan = job.build_plan(store.root)
    assert plan.documents == () and plan.missing == (sha,)


def test_remove_drops_file_and_ocr_text_and_every_url_sharing_it(store):
    data = png_bytes()
    sha = store.add("a.png", data, mime="image/png", kind="image", label="co_chu")
    store.add("b.png", data, mime="image/png", kind="image", label="co_chu")
    store.ocr(sha, 1, [line("x")])
    assert job.remove_files(store.root, [sha], now=NOW) == 2
    manifest = store.reload()
    assert manifest.current() == {}
    assert manifest.latest("https://qnu.edu.vn/a.png").reason == "operator_removed"
    assert not (store.root / "quarantine" / sha).exists()
    assert list(job.pages_dir(store.root).glob(f"{sha}-p*.json")) == []
    assert job.build_plan(store.root).documents == ()


def test_remove_waits_for_a_running_crawl(store):
    with _crawl_lock(store.root) as held:
        assert held
        with pytest.raises(job.OcrBusy):
            job.remove_files(store.root, ["x"], now=NOW)


def test_failed_page_gives_no_verdict_on_the_file(store):
    sha = store.add("a.pdf", pdf_bytes("", ""), mime="application/pdf")
    store.ocr(sha, 1, [line("sạch")])
    store.failed(sha, 2)
    (doc,) = job.build_plan(store.root).documents
    assert job.assemble(doc, store.root, today=TODAY).outcome == "error"


def test_page_not_yet_ocred_gives_no_verdict_on_the_file(store):
    sha = store.add("a.pdf", pdf_bytes("", ""), mime="application/pdf")
    store.ocr(sha, 1, [line("sạch")])
    (doc,) = job.build_plan(store.root).documents
    assert job.assemble(doc, store.root, today=TODAY).outcome == "missing"


def test_apply_moves_clean_file_into_the_store_with_its_text(store):
    sha = store.add("a.pdf", pdf_bytes(""), mime="application/pdf", tier="B")
    store.ocr(sha, 1, [line("Học phí")])
    counts = job.apply_results(store.root, today=TODAY, now=NOW)
    entry = store.reload().latest("https://qnu.edu.vn/a.pdf")
    assert counts["text"] == 1
    assert entry.text_status == "text" and entry.reason == "ocr" and entry.sha256 == sha
    assert (store.root / "blobs" / "B" / sha).exists()
    assert not (store.root / "quarantine" / sha).exists()
    saved = json.loads((store.root / "ocr/documents" / f"{sha}.json").read_text(encoding="utf-8"))
    assert saved["pages"][0]["text"] == "Học phí"
    assert job.build_plan(store.root).documents == ()


def test_apply_removes_people_list_with_its_ocr_text(store):
    sha = store.add("a.pdf", pdf_bytes(""), mime="application/pdf")
    store.ocr(sha, 1, [line(text, x=x, y=100) for text, x in PEOPLE_ROWS])
    counts = job.apply_results(store.root, today=TODAY, now=NOW)
    manifest = store.reload()
    entry = manifest.latest("https://qnu.edu.vn/a.pdf")
    assert counts["pii"] == 1
    assert entry.text_status == "skipped_pii" and entry.sha256 is None
    assert entry.reason.startswith("ocr:header:")
    assert "https://qnu.edu.vn/a.pdf" not in manifest.current()
    assert not (store.root / "quarantine" / sha).exists()
    assert list(job.pages_dir(store.root).glob(f"{sha}-p*.json")) == []


def test_apply_leaves_failed_and_empty_files_in_quarantine(store):
    failed = store.add("a.pdf", pdf_bytes(""), mime="application/pdf")
    empty = store.add("b.pdf", pdf_bytes("", ""), mime="application/pdf")
    store.failed(failed, 1)
    store.ocr(empty, 1, [])
    store.ocr(empty, 2, [])
    counts = job.apply_results(store.root, today=TODAY, now=NOW)
    assert counts["error"] == 1 and counts["empty"] == 1
    assert (store.root / "quarantine" / failed).exists()
    assert (store.root / "quarantine" / empty).exists()


def test_apply_waits_for_a_running_crawl(store):
    with _crawl_lock(store.root) as held:
        assert held
        with pytest.raises(job.OcrBusy):
            job.apply_results(store.root, today=TODAY, now=NOW)


def corpus_record(tmp_path, lines, *, rotation=0, image_sha="anh"):
    source = tmp_path / "data" / "a.png"
    source.parent.mkdir(exist_ok=True)
    source.write_bytes(png_bytes())
    return {
        "record_id": "r1",
        "source_document": "a.png",
        "source_document_sha256": worker.sha256_file(source),
        "page": "1",
        "engine": worker.CONFIG,
        "result": {"image_sha256": image_sha, "lines": lines, "rotation": rotation},
    }


def write_output(out, lines, *, rotation=0, image_sha="anh"):
    out.mkdir(parents=True, exist_ok=True)
    rec = {"image_sha256": image_sha, "lines": lines, "rotation": rotation}
    (out / "r1.json").write_text(json.dumps(rec), encoding="utf-8")


def test_verification_passes_only_on_identical_lines_and_rotation(tmp_path):
    record = corpus_record(tmp_path, [line("a")])
    write_output(tmp_path / "out", [line("a")])
    assert job.compare_outputs([record], tmp_path / "out").passed


@pytest.mark.parametrize("output", [{"lines": [line("b")]}, {"lines": [line("a")], "rotation": 90}])
def test_any_difference_fails_verification(tmp_path, output):
    record = corpus_record(tmp_path, [line("a")])
    write_output(tmp_path / "out", **output)
    result = job.compare_outputs([record], tmp_path / "out")
    assert not result.passed and len(result.differences) == 1


def test_another_input_image_is_reported_apart_from_ocr_differences(tmp_path):
    record = corpus_record(tmp_path, [line("a")])
    write_output(tmp_path / "out", [line("a")], image_sha="khac")
    result = job.compare_outputs([record], tmp_path / "out")
    assert not result.passed and len(result.render_mismatches) == 1


def test_missing_output_fails_verification(tmp_path):
    record = corpus_record(tmp_path, [line("a")])
    assert not job.compare_outputs([record], tmp_path / "empty").passed


def test_nothing_compared_is_not_a_pass():
    assert not job.Verification(0, 0, (), ()).passed


def test_gate_opens_only_for_the_verified_worker_and_lock(tmp_path):
    lock = tmp_path / job.ENV_LOCK
    lock.parent.mkdir(parents=True)
    lock.write_text("v1", encoding="utf-8")
    gate = tmp_path / "passed.json"
    assert not job.is_verified(gate, tmp_path)
    worker.atomic_write_json(gate, job.fingerprint(tmp_path))
    assert job.is_verified(gate, tmp_path)
    lock.write_text("v2", encoding="utf-8")
    assert not job.is_verified(gate, tmp_path)


def test_sample_verification_does_not_open_or_close_the_gate(tmp_path):
    record = corpus_record(tmp_path, [line("a")], image_sha="x")
    corpus = tmp_path / "corpus.json"
    corpus.write_text(json.dumps([record]), encoding="utf-8")
    body = f"""
import json, sys
from pathlib import Path
out = Path(sys.argv[sys.argv.index("--out") + 1])
rec = {{"image_sha256": "x", "lines": {[line("a")]!r}, "rotation": 0}}
(out / "r1.json").write_text(json.dumps(rec))
"""
    root = tmp_path / "verify"
    code, result = job.run_verify(
        corpus, tmp_path / "data", root, limit=1, command=fake_worker(tmp_path, body)
    )
    assert code == 0 and result.passed
    assert not (root / "passed.json").exists()
