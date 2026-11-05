"""Trang tổng của đợt duyệt 14/10/2026: lối vào hai hồ sơ gold v2 và form tick cho quyết định D1–D8.

Chạy: `uv run python -m experiments.review_hub` → `benchmarks/v2/dot-duyet/`. Quyết định đọc
từ bảng §9 của spec thực nghiệm v2, không chép lại nội dung.
"""

import csv
import html
import os
import re
from collections import Counter
from pathlib import Path

from experiments.prepare_dialogs import _sync_reviews
from experiments.prepare_gold import (
    REVIEW_BAR,
    REVIEW_CSS,
    _existing_reviews,
    digest,
    review_form,
    review_scripts,
)

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "docs/superpowers/specs/2026-10-14-thuc-nghiem-paper-v2-design.md"
HUB = ROOT / "benchmarks/v2/dot-duyet"
PACKETS = [
    ("Gold đơn lượt", ROOT / "benchmarks/v2/review"),
    ("Hội thoại nhiều lượt", ROOT / "benchmarks/v2/multiturn/review"),
]
_FORM = re.compile(r'data-item="([^"]+)" data-hash="([0-9a-f]{64})"')
_ROW = re.compile(r"^\| (D\d+) \| (.+?) \| (.+?) \|$")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def read_decisions(spec: Path) -> list[dict]:
    return [
        {"id": m.group(1), "question": m.group(2).strip(), "recommendation": m.group(3).strip()}
        for line in spec.read_text(encoding="utf-8").splitlines()
        if (m := _ROW.match(line))
    ]


def _markdown(text: str, spec: Path, output: Path) -> str:
    """Ô bảng Markdown → HTML: escape, giữ link (tính lại theo thư mục trang) và `code`."""
    parts, last = [], 0
    for m in _LINK.finditer(text):
        parts.append(html.escape(text[last : m.start()]))
        target = os.path.relpath((spec.parent / m.group(2)).resolve(), output.resolve())
        parts.append(f"<a href='{html.escape(target)}'>{html.escape(m.group(1))}</a>")
        last = m.end()
    parts.append(html.escape(text[last:]))
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", "".join(parts))


def _progress(packet: Path) -> str:
    csv_path = packet / "reviews.csv"
    if not csv_path.exists():
        return "chưa dựng hồ sơ"
    index = packet / "index.html"
    current = dict(_FORM.findall(index.read_text(encoding="utf-8"))) if index.exists() else {}
    counts: Counter[str] = Counter()
    with csv_path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            stale = row["decision"] != "pending" and current.get(row["item_id"]) not in (
                None,
                row["draft_sha256"],
            )
            counts["stale" if stale else row["decision"]] += 1
    total = sum(counts.values())
    done = counts["approve"] + counts["reject"]
    text = (
        f"{done}/{total} đã có quyết định trong reviews.csv ({counts['approve']} đạt, "
        f"{counts['reject']} cần sửa"
    )
    if counts["stale"]:
        text += f"; {counts['stale']} cần duyệt lại vì nội dung đã đổi"
    return text + ")"


def build_hub(output: Path = HUB, spec: Path = SPEC) -> None:
    output.mkdir(parents=True, exist_ok=True)
    decisions = read_decisions(spec)
    csv_path = output / "reviews.csv"
    _sync_reviews(decisions, csv_path)
    existing = _existing_reviews(csv_path)
    labels = {"approve": "Đạt", "reject": "Cần sửa", "pending": "Chưa duyệt"}
    counts = Counter(existing[d["id"]]["decision"] for d in decisions)
    spec_link = os.path.relpath(spec, output)
    parts = [
        "<!doctype html><html lang='vi'><meta charset='utf-8'>",
        "<title>Đợt duyệt 14/10/2026</title>",
        REVIEW_CSS,
        (
            "<style>.saved-review{border-left:4px solid #64748b;background:#f3f5f7;"
            "padding:1em;margin:1em 0}.saved-review p{white-space:pre-wrap;margin:.4em 0}"
            ".saved-review.reject{border-color:#c62828}.saved-review.approve{border-color:#1a7f37}"
            "nav a{display:inline-block;margin:.2em .8em .2em 0}</style>"
        ),
        REVIEW_BAR,
        "<h1>Đợt duyệt 14/10/2026</h1>",
        "<section id='review-summary'><h2>Kết quả kiểm tra đã lưu</h2>",
        (
            f"<p><b>{counts['approve']} đạt · {counts['reject']} cần sửa · "
            f"{counts['pending']} chưa duyệt</b></p>"
        ),
        (
            "<p>Kết quả dưới đây lấy từ reviews.csv; tên người duyệt ghi ở từng mục. "
            "Các ô tick bên dưới cho phép xem lại và đổi quyết định. "
            "Kết quả duyệt câu gold và hội thoại nằm trong hai hồ sơ ở mục 1.</p>"
        ),
        "<nav aria-label='Đi tới quyết định'>"
        + " ".join(
            f"<a href='#{d['id']}'>{d['id']}: {labels[existing[d['id']]['decision']]}</a>"
            for d in decisions
        )
        + "</nav></section>",
        *(
            f"<p><a href='{html.escape(r.name, quote=True)}'>"
            f"Báo cáo kiểm tra {html.escape(r.stem)}</a></p>"
            for r in sorted(output.glob("review-*.md"))
        ),
        "<h2>1. Dữ liệu đánh giá</h2><ul>",
        *(
            f"<li><a href='{html.escape(os.path.relpath(p / 'index.html', output))}'>{label}</a> — "
            f"{_progress(p)}. Mỗi hồ sơ có nút <b>Xuất reviews.csv</b> riêng; lưu đè vào "
            f"<code>{html.escape(str((p / 'reviews.csv').relative_to(ROOT)))}</code>.</li>"
            for label, p in PACKETS
        ),
        "</ul>",
        "<h2>2. Quyết định</h2>",
        (
            f"<p>Chi tiết ở <a href='{html.escape(spec_link)}'>spec thực nghiệm paper v2</a> §9. "
            "Tick <b>Đạt</b> nếu đồng ý với đề xuất của Claude; <b>Cần sửa</b> kèm ghi chú nếu "
            "chọn khác. Xuất reviews.csv của trang này lưu đè vào "
            "<code>benchmarks/v2/dot-duyet/reviews.csv</code>.</p>"
        ),
    ]
    for d in decisions:
        row = existing[d["id"]]
        result = (
            f"<aside class='saved-review {html.escape(row['decision'])}'>"
            f"<b>Kết quả đã lưu: {labels[row['decision']]}</b>"
            f"<p>{html.escape(row.get('reviewer', ''))} · "
            f"{html.escape(row.get('verified_at', ''))}</p>"
            f"<p>{html.escape(row.get('notes', ''))}</p></aside>"
        )
        parts.append(
            f"<article id='{d['id']}'><h2>{d['id']}</h2>"
            f"<p>{_markdown(d['question'], spec, output)}</p>"
            f"<p><b>Đề xuất của Claude:</b> {_markdown(d['recommendation'], spec, output)}</p>"
            + result
            + review_form(d["id"], digest(d))
            + "</article>"
        )
    # CSV đổi thì dùng vùng lưu nháp mới; không xoá bản nháp cũ trong trình duyệt.
    parts += [*review_scripts(existing, storage_revision=digest(existing)), "</html>"]
    (output / "index.html").write_text("\n".join(parts), encoding="utf-8")


def main() -> None:
    build_hub()
    print(f"-> {(HUB / 'index.html').relative_to(ROOT)}")


if __name__ == "__main__":
    main()
