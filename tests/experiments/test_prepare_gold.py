import copy
import csv
import json
from datetime import UTC, datetime

import pytest

from experiments.prepare_gold import (
    DRAFT,
    digest,
    promote,
    read_drafts,
    review_packet,
    validate_drafts,
)


@pytest.fixture(scope="module")
def drafts():
    return read_drafts(DRAFT)


def test_bundled_draft_has_source_backed_70_items(drafts):
    assert len(drafts) == 70
    assert validate_drafts(drafts) == []
    assert all(r["item"]["reviewer"] == "" for r in drafts)


def test_source_checks_reject_changed_quotes_and_hashes(drafts):
    altered = copy.deepcopy(drafts)
    altered[0]["evidence"][0]["quote"] = "THIS CLAIM DOES NOT EXIST IN THE SOURCE"
    altered[1]["evidence"][0]["sha256"] = "0" * 64
    errors = validate_drafts(altered)
    assert any("quote not found" in e for e in errors)
    assert any("source hash changed" in e for e in errors)


def test_noisy_variants_cannot_change_expected_facts(drafts):
    altered = copy.deepcopy(drafts)
    altered[-1]["item"]["source_family"] = "independent_but_actually_same_fact"
    assert any("noisy variant changed" in e for e in validate_drafts(altered))


def test_pending_reviews_cannot_create_experiment_gold(drafts, tmp_path):
    review_packet(drafts, tmp_path)
    target = tmp_path / "gold.jsonl"
    with pytest.raises(ValueError, match="pending"):
        promote(drafts, tmp_path / "reviews.csv", target)
    assert not target.exists()


def test_packet_does_not_overwrite_human_review_work(drafts, tmp_path):
    review_packet(drafts, tmp_path)
    csv_path = tmp_path / "reviews.csv"
    csv_path.write_text("manual work")
    review_packet(drafts, tmp_path)
    assert csv_path.read_text() == "manual work"


def _rows(path):
    with path.open(encoding="utf-8", newline="") as handle:
        return {row["item_id"]: row for row in csv.DictReader(handle)}


def test_refresh_pending_rehashes_only_unreviewed_rows(drafts, tmp_path):
    review_packet(drafts, tmp_path)
    csv_path = tmp_path / "reviews.csv"
    rows = _rows(csv_path)
    first, second = drafts[0]["item"]["id"], drafts[1]["item"]["id"]
    rows[first].update(draft_sha256="stale", notes="ghi chú giữ lại")
    rows[second].update(
        draft_sha256="stale-approved",
        decision="approve",
        reviewer="Người duyệt",
        verified_at="2026-10-01T09:00:00+07:00",
    )
    del rows[drafts[2]["item"]["id"]]  # câu nháp chưa có dòng duyệt
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(next(iter(rows.values()))))
        writer.writeheader()
        writer.writerows(rows.values())

    review_packet(drafts, tmp_path, refresh_pending=True)

    after = _rows(csv_path)
    assert after[first]["draft_sha256"] == digest(drafts[0])
    assert after[first]["notes"] == "ghi chú giữ lại"
    assert after[second] == rows[second]  # đã duyệt: không đụng, kể cả hash cũ
    assert after[drafts[2]["item"]["id"]]["decision"] == "pending"
    assert set(after) == {r["item"]["id"] for r in drafts}


def test_refresh_pending_refuses_an_unreadable_review_file(drafts, tmp_path):
    review_packet(drafts, tmp_path)
    (tmp_path / "reviews.csv").write_text("manual work")
    with pytest.raises(ValueError, match="reviews.csv"):
        review_packet(drafts, tmp_path, refresh_pending=True)
    assert (tmp_path / "reviews.csv").read_text() == "manual work"


def signed_reviews(drafts, path):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["item_id", "draft_sha256", "decision", "reviewer", "verified_at", "notes"],
        )
        writer.writeheader()
        for r in drafts:
            writer.writerow(
                {
                    "item_id": r["item"]["id"],
                    "draft_sha256": digest(r),
                    "decision": "approve",
                    "reviewer": "test human reviewer",
                    "verified_at": datetime.now(UTC).isoformat(),
                }
            )


def test_promotion_freezes_gold_and_rejects_overwrite(drafts, tmp_path):
    csv_path = tmp_path / "reviews.csv"
    signed_reviews(drafts, csv_path)
    target = tmp_path / "gold.jsonl"
    promote(drafts, csv_path, target)
    manifest = json.loads(target.with_suffix(".review.json").read_text())
    assert manifest["status"] == "human_reviewed" and manifest["n_items"] == 70
    assert all(
        json.loads(s)["reviewer"] == "test human reviewer" for s in target.read_text().splitlines()
    )
    with pytest.raises(ValueError, match="already exists"):
        promote(drafts, csv_path, target)


def test_editing_a_question_invalidates_its_review(drafts, tmp_path):
    csv_path = tmp_path / "reviews.csv"
    signed_reviews(drafts, csv_path)
    altered = copy.deepcopy(drafts)
    altered[0]["item"]["question"] += " Xin nói rõ."
    with pytest.raises(ValueError, match="stale review"):
        promote(altered, csv_path, tmp_path / "gold.jsonl")



