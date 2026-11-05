"""Trang tổng của đợt duyệt 14/10/2026: quyết định D1–D8 đọc từ bảng §9 của spec thực nghiệm v2."""

import re

import pytest

from experiments.prepare_gold import digest
from experiments.review_hub import PACKETS, SPEC, build_hub, read_decisions

needs_spec = pytest.mark.skipif(
    not SPEC.exists(), reason="review_hub đọc spec paper v2, tài liệu này chưa có trong v2"
)


@needs_spec
def test_decisions_are_read_from_the_spec_table():
    decisions = read_decisions(SPEC)
    assert [d["id"] for d in decisions] == [f"D{i}" for i in range(1, 9)]
    assert all(d["question"] and d["recommendation"] for d in decisions)


@needs_spec
def test_hub_has_a_tickbox_form_per_decision_and_links_both_packets(tmp_path):
    build_hub(tmp_path)
    index = (tmp_path / "index.html").read_text(encoding="utf-8")
    forms = dict(re.findall(r'data-item="([^"]+)" data-hash="([0-9a-f]{64})"', index))
    assert forms == {d["id"]: digest(d) for d in read_decisions(SPEC)}
    hrefs = {(tmp_path / h).resolve() for h in re.findall(r"href='([^']+index\.html)'", index)}
    assert {(packet / "index.html").resolve() for _, packet in PACKETS} <= hrefs
    assert (tmp_path / "reviews.csv").exists()


def test_progress_counts_reviews_of_changed_content_as_needing_review(tmp_path):
    from experiments.review_hub import _progress

    (tmp_path / "index.html").write_text(
        '<fieldset data-item="a" data-hash="' + "1" * 64 + '"></fieldset>'
        '<fieldset data-item="b" data-hash="' + "2" * 64 + '"></fieldset>',
        encoding="utf-8",
    )
    (tmp_path / "reviews.csv").write_text(
        "item_id,draft_sha256,decision,reviewer,verified_at,notes\n"
        f"a,{'1' * 64},approve,Kent,2026-10-16T15:00:00+07:00,\n"
        f"b,{'9' * 64},approve,Kent,2026-10-16T15:00:00+07:00,\n",
        encoding="utf-8",
    )
    text = _progress(tmp_path)
    assert text.startswith("1/2 đã có quyết định")
    assert "1 cần duyệt lại vì nội dung đã đổi" in text
