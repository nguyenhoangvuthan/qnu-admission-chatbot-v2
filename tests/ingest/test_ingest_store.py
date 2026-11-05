from datetime import date

import pytest

from qnuchat.ingest.blobs import BlobStore
from qnuchat.ingest.manifest import Manifest, ManifestEntry, load_sources_index
from qnuchat.ingest.state import CheckState

URL = "https://www.qnu.edu.vn/vi/dai-hoc-chinh-quy-1764/tb141"


def entry(**overrides) -> ManifestEntry:
    base = {
        "url": URL,
        "source_id": "w-0123456789abcdef",
        "page_url": None,
        "kind": "page",
        "title": "TB141",
        "published": "2026-08-09",
        "retrieved_at": "2026-10-12T02:00:00+07:00",
        "sha256": "a" * 64,
        "mime": "text/html",
        "bytes": 10,
        "host": "www.qnu.edu.vn",
        "tier": "A",
        "text_status": "text",
        "reason": None,
        "crawl_run": "run-1",
        "config_hash": "h",
        "sources_yaml_ref": None,
    }
    base.update(overrides)
    return ManifestEntry(**base)


def test_append_then_reload_keeps_every_line(tmp_path):
    path = tmp_path / "manifest.jsonl"
    Manifest(path).append(entry())
    Manifest(path).append(entry(sha256="b" * 64))
    reloaded = Manifest(path)
    assert [e.sha256[0] for e in reloaded.entries()] == ["a", "b"]
    assert reloaded.latest(URL).sha256 == "b" * 64


def test_current_is_the_latest_usable_version(tmp_path):
    manifest = Manifest(tmp_path / "m.jsonl")
    manifest.append(entry(sha256="a" * 64))
    manifest.append(entry(sha256="b" * 64))
    assert manifest.current()[URL].sha256 == "b" * 64


def test_gone_and_skipped_remove_the_document_from_current(tmp_path):
    manifest = Manifest(tmp_path / "m.jsonl")
    manifest.append(entry())
    manifest.append(entry(sha256=None, text_status="failed", reason="gone"))
    assert URL not in manifest.current()
    manifest.append(entry(url=URL + "x"))
    manifest.append(entry(url=URL + "x", sha256=None, text_status="skipped_pii", reason="rows"))
    assert URL + "x" not in manifest.current()


def test_a_permanent_failure_other_than_gone_keeps_the_previous_version(tmp_path):
    manifest = Manifest(tmp_path / "m.jsonl")
    manifest.append(entry())
    manifest.append(entry(sha256=None, text_status="failed", reason="too_large"))
    assert manifest.current()[URL].sha256 == "a" * 64


def test_truncated_last_line_is_dropped_and_appending_continues(tmp_path):
    path = tmp_path / "m.jsonl"
    Manifest(path).append(entry())
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"url": "https://www.qnu.edu.vn/dang-do')
    manifest = Manifest(path)
    assert len(manifest.entries()) == 1
    manifest.append(entry(sha256="c" * 64))
    assert [e.sha256[0] for e in Manifest(path).entries()] == ["a", "c"]


def test_a_corrupt_middle_line_is_an_error(tmp_path):
    path = tmp_path / "m.jsonl"
    path.write_text('{"broken": \n' + "{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="dòng 1"):
        Manifest(path)


def test_favicon_lookup_by_host(tmp_path):
    manifest = Manifest(tmp_path / "m.jsonl")
    manifest.append(
        entry(url="https://www.qnu.edu.vn/favicon.ico", kind="favicon", mime="image/png")
    )
    assert manifest.favicon("www.qnu.edu.vn").kind == "favicon"
    assert manifest.favicon("kcntt.qnu.edu.vn") is None


def test_sources_index_maps_sha_to_file(tmp_path):
    path = tmp_path / "sources.yaml"
    path.write_text("sources:\n  - file: a/b.pdf\n    sha256: " + "d" * 64 + "\n", encoding="utf-8")
    assert load_sources_index(path) == {"d" * 64: "a/b.pdf"}


def test_blob_store_places_by_tier_and_quarantine(tmp_path):
    store = BlobStore(tmp_path)
    sha_a = store.put(b"tang A", tier="A")
    sha_q = store.put(b"cho OCR", tier="A", quarantine=True)
    assert store.path(sha_a) == tmp_path / "blobs" / "A" / sha_a
    assert store.path(sha_q) == tmp_path / "quarantine" / sha_q
    sha_b = store.put(b"tang B", tier="B")
    assert store.path(sha_b) == tmp_path / "blobs" / "B" / sha_b


def test_tier_a_wins_when_the_same_content_is_in_both_tiers(tmp_path):
    store = BlobStore(tmp_path)
    sha = store.put(b"giong nhau", tier="B")
    assert store.put(b"giong nhau", tier="A") == sha
    assert store.path(sha) == tmp_path / "blobs" / "A" / sha
    assert not (tmp_path / "blobs" / "B" / sha).exists()


def test_delete_removes_every_copy(tmp_path):
    store = BlobStore(tmp_path)
    sha = store.put(b"x", tier="A", quarantine=True)
    store.delete(sha)
    assert store.path(sha) is None


def test_check_state_due_and_hub(tmp_path):
    state = CheckState(tmp_path / "last_checked.json")
    assert state.due(URL, date(2026, 10, 12), 30)
    state.mark(URL, date(2026, 10, 12), hub=True)
    state.save()
    reloaded = CheckState(tmp_path / "last_checked.json")
    assert not reloaded.due(URL, date(2026, 11, 10), 30)
    assert reloaded.due(URL, date(2026, 11, 11), 30)
    assert reloaded.is_hub(URL)
    reloaded.mark(URL, date(2026, 11, 11))
    assert reloaded.is_hub(URL)


def test_a_title_with_unicode_line_separator_round_trips(tmp_path):
    path = tmp_path / "m.jsonl"
    title = "Thông báo tuyển sinh đợt 1\x85"
    Manifest(path).append(entry(title=title))
    reloaded = Manifest(path)
    assert len(reloaded.entries()) == 1
    assert reloaded.entries()[0].title == title


def test_b_put_after_a_does_not_write_a_b_copy(tmp_path):
    store = BlobStore(tmp_path)
    sha = store.put(b"da co A", tier="A")
    assert store.put(b"da co A", tier="B") == sha
    assert store.path(sha) == tmp_path / "blobs" / "A" / sha
    assert not (tmp_path / "blobs" / "B" / sha).exists()


def test_concurrent_a_put_after_b_leaves_only_the_a_copy(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    store = BlobStore(tmp_path)
    data = b"dong thoi"
    sha = store.put(data, tier="B")
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: store.put(data, tier="A"), range(8)))
    assert results == [sha] * 8
    assert (tmp_path / "blobs" / "A" / sha).exists()
    assert not (tmp_path / "blobs" / "B" / sha).exists()


# ---------------------------------------------------------------- đợt sửa lỗi nhỏ 3 (kho)


def test_blob_put_rejects_an_unknown_tier(tmp_path):
    store = BlobStore(tmp_path)
    with pytest.raises(ValueError, match="tier"):
        store.put(b"x", tier="C")
    with pytest.raises(ValueError, match="tier"):
        store.put(b"x", tier="a", quarantine=True)
    assert not (tmp_path / "blobs").exists() and not (tmp_path / "quarantine").exists()


def test_failed_blob_write_leaves_no_temp_file(tmp_path, monkeypatch):
    import qnuchat.ingest.blobs as blobs_module

    def boom(src, dst):
        raise OSError("đĩa đầy")

    monkeypatch.setattr(blobs_module.os, "replace", boom)
    store = BlobStore(tmp_path)
    with pytest.raises(OSError, match="đĩa đầy"):
        store.put(b"ghi loi", tier="A")
    assert list(tmp_path.rglob(".tmp-*")) == []
    assert store.path(blobs_module.hashlib.sha256(b"ghi loi").hexdigest()) is None


def test_blob_is_fsynced_before_it_is_moved_into_place(tmp_path, monkeypatch):
    import qnuchat.ingest.blobs as blobs_module

    calls: list[str] = []
    real_fsync, real_replace = blobs_module.os.fsync, blobs_module.os.replace
    monkeypatch.setattr(
        blobs_module.os, "fsync", lambda fd: (calls.append("fsync"), real_fsync(fd))[1]
    )
    monkeypatch.setattr(
        blobs_module.os,
        "replace",
        lambda src, dst: (calls.append("replace"), real_replace(src, dst))[1],
    )
    BlobStore(tmp_path).put(b"ben vung", tier="B")
    assert calls == ["fsync", "replace"]


def test_corrupt_check_state_starts_empty_with_a_warning(tmp_path, caplog, monkeypatch):
    import logging

    # Test khác cấu hình logging (dictConfig) có thể đã tắt logger này.
    monkeypatch.setattr(logging.getLogger("qnuchat.ingest.state"), "disabled", False)
    path = tmp_path / "last_checked.json"
    path.write_text('{"https://www.qnu.edu.vn/": {"checked": "2026-', encoding="utf-8")
    with caplog.at_level("WARNING", logger="qnuchat.ingest.state"):
        state = CheckState(path)
    assert state.due(URL, date(2026, 10, 12), 30)
    assert any("last_checked" in r.getMessage() for r in caplog.records)
    state.mark(URL, date(2026, 10, 12))
    state.save()
    assert not CheckState(path).due(URL, date(2026, 10, 12), 30)


def test_check_state_save_holds_its_lock_while_writing(tmp_path, monkeypatch):
    import qnuchat.ingest.state as state_module

    state = CheckState(tmp_path / "last_checked.json")
    state.mark(URL, date(2026, 10, 12))
    held: list[bool] = []
    real_replace = state_module.os.replace

    def replace(src, dst):
        held.append(state._lock.locked())
        real_replace(src, dst)

    monkeypatch.setattr(state_module.os, "replace", replace)
    state.save()
    assert held == [True]


def test_manifest_without_repair_skips_the_partial_last_line_but_keeps_the_file(tmp_path):
    path = tmp_path / "m.jsonl"
    Manifest(path).append(entry())
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"url": "https://www.qnu.edu.vn/dang-do')
    before = path.read_bytes()
    reader = Manifest(path, repair=False)
    assert len(reader.entries()) == 1 and reader.latest(URL).sha256 == "a" * 64
    assert path.read_bytes() == before


def test_robots_disallowed_removes_the_document_from_current(tmp_path):
    manifest = Manifest(tmp_path / "m.jsonl")
    manifest.append(entry())
    manifest.append(entry(sha256=None, text_status="failed", reason="robots_disallowed"))
    assert URL not in manifest.current()
