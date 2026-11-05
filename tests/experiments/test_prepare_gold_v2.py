"""Hồ sơ duyệt cho gold v2: nhiều văn bản nguồn, `gold_evidence` theo (nguồn, trang)."""

import copy
import csv
import json
import re
import shutil
import subprocess
from datetime import UTC, datetime, timedelta

import pymupdf
import pytest

from experiments.prepare_gold import (
    REVIEW_FIELDS,
    V2_DRAFT,
    digest,
    highlight_rects,
    promote,
    read_drafts,
    resolve_source,
    review_packet,
    validate_drafts,
)
from experiments.prepare_gold import ROOT as REPO


@pytest.fixture(scope="module")
def drafts():
    return read_drafts(V2_DRAFT)


def test_v2_draft_passes_source_checks_without_pilot_rules(drafts):
    # Luật riêng của pilot (trang loại trừ của Cẩm nang, tỷ lệ 40/22/8) không áp cho v2.
    assert validate_drafts(drafts, profile="v2") == []


def test_v2_quote_checks_still_apply(drafts):
    altered = copy.deepcopy(drafts)
    altered[0]["evidence"][0]["quote"] = "CÂU NÀY KHÔNG CÓ TRONG NGUỒN"
    assert any("quote not found" in e for e in validate_drafts(altered, profile="v2"))


def test_v2_gold_evidence_must_be_backed_by_a_quote(drafts):
    altered = copy.deepcopy(drafts)
    source = altered[0]["evidence"][0]["source"]
    altered[0]["gold_evidence"].append([source, 50])
    errors = validate_drafts(altered, profile="v2")
    assert any("gold_evidence" in e for e in errors)


def test_v2_packet_renders_one_image_per_source_page(drafts, tmp_path):
    review_packet(drafts, tmp_path, render=True, profile="v2")
    pairs = {(e["source"], e["page"]) for r in drafts for e in r["evidence"]}
    images = list((tmp_path / "pages").glob("*.png"))
    # TB153 trang 1 và TB141 trang 1 không được ghi đè lên nhau.
    assert len(images) == len(pairs)
    index = (tmp_path / "index.html").read_text(encoding="utf-8")
    for image in images:
        assert f"pages/{image.name}" in index
    assert f"{len(drafts)} câu — hồ sơ duyệt v2" in index
    note = next(r["review_note"] for r in drafts if "review_note" in r)
    assert note in index


def _centre_y(rect):
    return (rect.y0 + rect.y1) / 2


def test_highlight_marks_the_quoted_row_not_other_rows():
    source = (
        "data/tuyen-sinh-dai-hoc-chinh-quy/"
        "TB153 - Điểm chuẩn trúng tuyển năm 2025 theo phương thức.pdf"
    )
    with pymupdf.open(resolve_source(REPO, source)) as doc:
        rects = highlight_rects(doc[1], "Kỹ thuật phần mềm 7480103 19,5")
    # "19,5" còn ở dòng Toán ứng dụng; chỉ được tô dòng Kỹ thuật phần mềm.
    assert len(rects) >= 2
    ys = [_centre_y(r) for r in rects]
    assert max(ys) - min(ys) < 15


def test_highlight_marks_each_line_of_a_multiline_quote():
    source = "data/tuyen-sinh-dai-hoc-chinh-quy/Cẩm Nang Tuyển Sinh Đại Học Năm 2025.pdf"
    quote = "Thời gian đào tạo: 4,5 năm\nKhối lượng kiến thức: 150 tín chỉ\nBằng tốt nghiệp: Kỹ sư"
    with pymupdf.open(resolve_source(REPO, source)) as doc:
        rects = highlight_rects(doc[71], quote)
    assert len({round(_centre_y(r)) for r in rects}) == 3


def test_v2_promote_keeps_gold_evidence(drafts, tmp_path):
    csv_path = tmp_path / "reviews.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
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
    target = tmp_path / "gold.jsonl"
    promote(drafts, csv_path, target, profile="v2")
    rows = [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines()]
    assert [row["gold_evidence"] for row in rows] == [r["gold_evidence"] for r in drafts]


# ---------------------------------------------------------------- form duyệt trong hồ sơ HTML


def _review_lib(index: str) -> str:
    match = re.search(r'<script id="review-lib">(.*?)</script>', index, re.DOTALL)
    assert match, "hồ sơ duyệt thiếu thư viện form"
    return match.group(1)


def test_packet_has_one_tickbox_form_per_item_bound_to_its_hash(drafts, tmp_path):
    review_packet(drafts, tmp_path, profile="v2")
    index = (tmp_path / "index.html").read_text(encoding="utf-8")
    forms = dict(re.findall(r'data-item="([^"]+)" data-hash="([0-9a-f]{64})"', index))
    assert forms == {r["item"]["id"]: digest(r) for r in drafts}
    assert index.count('type="checkbox"') == 2 * len(drafts)  # Đạt / Cần sửa


def test_packet_embeds_review_work_already_in_csv(drafts, tmp_path):
    review_packet(drafts, tmp_path, profile="v2")
    csv_path = tmp_path / "reviews.csv"
    rows = _read_rows(csv_path)
    first = drafts[0]["item"]["id"]
    rows[first].update(decision="approve", reviewer="Kent", verified_at="2026-10-14T11:30:00+07:00")
    _write_rows(csv_path, rows)
    review_packet(drafts, tmp_path, profile="v2")
    index = (tmp_path / "index.html").read_text(encoding="utf-8")
    pattern = r'<script id="review-rows" type="application/json"[^>]*>(.*?)</script>'
    embedded = json.loads(re.search(pattern, index, re.DOTALL).group(1).replace("<\\/", "</"))
    assert embedded[first]["decision"] == "approve"
    assert embedded[first]["reviewer"] == "Kent"
    # Quyết định đã lưu hiện ngay trên trang, không phụ thuộc bản nháp của trình duyệt.
    assert "Kết quả đã lưu: Đạt" in index
    assert "1 đạt · 0 cần sửa" in index


def _read_rows(path):
    with path.open(encoding="utf-8", newline="") as handle:
        return {row["item_id"]: row for row in csv.DictReader(handle)}


def _write_rows(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(next(iter(rows.values()))))
        writer.writeheader()
        writer.writerows(rows.values())


@pytest.mark.skipif(shutil.which("node") is None, reason="cần node để chạy JS của hồ sơ duyệt")
def test_exported_csv_round_trips_and_timestamp_has_timezone(drafts, tmp_path):
    review_packet(drafts, tmp_path, profile="v2")
    lib = _review_lib((tmp_path / "index.html").read_text(encoding="utf-8"))
    harness = (
        lib
        + """
const rows = [
  {item_id: "A", draft_sha256: "h", decision: "approve", reviewer: "Kent",
   verified_at: isoLocal(new Date()), notes: 'số "19,5" đúng,\\nđã xem trang 2'},
  {item_id: "B", draft_sha256: "h2", decision: "pending"},
];
process.stdout.write(toCsv(FIELDS, rows));
"""
    )
    out = subprocess.run(
        ["node", "-e", harness],
        capture_output=True,
        text=True,
        check=True,
        env={"TZ": "Asia/Ho_Chi_Minh"},
    ).stdout
    path = tmp_path / "exported.csv"
    path.write_text(out, encoding="utf-8")
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == REVIEW_FIELDS
        rows = list(reader)
    assert rows[0]["notes"] == 'số "19,5" đúng,\nđã xem trang 2'
    assert rows[1]["decision"] == "pending" and rows[1]["reviewer"] == ""
    when = datetime.fromisoformat(rows[0]["verified_at"])
    assert when.utcoffset() == timedelta(hours=7)


# ---------------------------------------------------------------- bằng chứng HTML/DOCX theo dòng

TB1906 = "data/tuyen-sinh-dai-hoc-chinh-quy/TB1906 - Thông tin tuyển sinh đại học năm 2026.html"
NGUONG_2026 = (
    "data/tuyen-sinh-dai-hoc-chinh-quy/"
    "Ngưỡng bảo đảm chất lượng đầu vào tuyển sinh đại học chính quy năm 2026.docx"
)


def _line_record(source, line, quote):
    from experiments.provenance import sha256_file

    return {
        "item": {
            "id": "T-LINE",
            "question": "Năm 2026 thi năng khiếu Giáo dục mầm non vào ngày nào?",
            "origin": "curated",
            "risk": "normal",
            "admission_year": 2026,
            "must_abstain": False,
            "gold_page_ids": [],
            "expected_slots": [
                {"subject": "thi năng khiếu", "predicate": "ngày thi", "value": "19, 20, 21/6/2026"}
            ],
            "required_conditions": [],
            "forbidden_claims": [],
            "source_family": "t",
            "reviewer": "",
        },
        "task_type": "lookup",
        "reference_answer": "Thi vào các ngày 19, 20, 21/6/2026.",
        "evidence": [
            {
                "source": source,
                "sha256": sha256_file(resolve_source(REPO, source)),
                "line": line,
                "quote": quote,
            }
        ],
        "gold_evidence": [[source, line]],
    }


def test_v2_accepts_html_evidence_located_by_line():
    quote = (
        "Thi năng khiếu Giáo dục mầm non, Giáo dục thể chất: thi vào các ngày 19, 20, 21/6/2026."
    )
    assert validate_drafts([_line_record(TB1906, 650, quote)], profile="v2") == []


def test_v2_reads_docx_table_rows_by_line():
    quote = "6 | 7140209 | Sư phạm Toán học | 20 | – | – | 20"
    assert validate_drafts([_line_record(NGUONG_2026, 21, quote)], profile="v2") == []


def test_v2_rejects_a_quote_on_the_wrong_line():
    quote = (
        "Thi năng khiếu Giáo dục mầm non, Giáo dục thể chất: thi vào các ngày 19, 20, 21/6/2026."
    )
    errors = validate_drafts([_line_record(TB1906, 649, quote)], profile="v2")
    assert any("quote not found" in e for e in errors)


def test_v2_packet_shows_line_evidence_without_page_image(tmp_path):
    quote = (
        "Thi năng khiếu Giáo dục mầm non, Giáo dục thể chất: thi vào các ngày 19, 20, 21/6/2026."
    )
    review_packet([_line_record(TB1906, 650, quote)], tmp_path, render=True, profile="v2")
    index = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "dòng 650" in index
    assert not list((tmp_path / "pages").glob("*.png"))


def test_long_page_quotes_are_narrowed_to_lines_with_expected_values():
    from experiments.prepare_gold import focus_quote

    page = "\n".join(["GIỚI THIỆU", "Ngành học thú vị", "Thời gian đào tạo: 4 năm"] * 3)
    page += "\nKhối lượng kiến thức: 138 tín chỉ\nBằng tốt nghiệp: Cử nhân"
    assert focus_quote(page, ["138"]) == "Khối lượng kiến thức: 138 tín chỉ"


def test_short_quotes_are_kept_whole():
    from experiments.prepare_gold import focus_quote

    quote = "Kỹ thuật phần mềm 7480103 19,5"
    assert focus_quote(quote, ["19,5"]) == quote


def test_v2_packet_reads_every_draft_file_in_the_folder():
    from experiments.prepare_gold import V2, read_v2_drafts

    records = read_v2_drafts()
    files = sorted(V2.glob("*.draft.jsonl"))
    assert len(files) >= 2
    assert len(records) == sum(len(read_drafts(f)) for f in files)
    assert len({r["item"]["id"] for r in records}) == len(records)


def test_saved_decision_of_changed_content_is_not_prefilled(drafts, tmp_path):
    # Quyết định trong CSV gắn với hash cũ thì form không được tick sẵn theo nó.
    review_packet(drafts, tmp_path, profile="v2")
    index = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "saved[id] && saved[id].draft_sha256 === hash ? saved[id] : null" in index
