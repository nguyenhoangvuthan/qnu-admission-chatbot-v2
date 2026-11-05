"""Snapshot kho của gold v2 và các arm: danh sách file có lớp chữ trong data/, khoá theo SHA-256."""

import json

from experiments.prepare_gold import read_v2_drafts
from experiments.snapshot_v2 import SNAPSHOT, build_snapshot


def test_snapshot_file_matches_a_fresh_build():
    assert json.loads(SNAPSHOT.read_text(encoding="utf-8")) == build_snapshot()


def test_snapshot_excludes_superseded_scanned_and_image_files():
    files = {f["file"]: f for f in build_snapshot()["files"]}
    assert not any("TB152" in name for name in files)  # đã bị TB153 thay
    assert not any(name.endswith(".png") for name in files)
    assert not any("Đề Án Tuyển Sinh Đại Học Năm 2024" in name for name in files)  # bản scan


def test_every_gold_v2_source_is_in_the_snapshot():
    snapshot = {f"data/{f['file']}": f["sha256"] for f in build_snapshot()["files"]}
    for record in read_v2_drafts():
        for evidence in record["evidence"]:
            assert snapshot.get(evidence["source"]) == evidence["sha256"], (
                record["item"]["id"],
                evidence["source"],
            )
