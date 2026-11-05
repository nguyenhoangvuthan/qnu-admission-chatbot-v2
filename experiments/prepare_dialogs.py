"""Kiểm và dựng hồ sơ duyệt cho bộ hội thoại nhiều lượt của gold v2.

Chạy: `uv run python -m experiments.prepare_dialogs check|packet`. Hồ sơ ở
`benchmarks/v2/multiturn/review/` dùng cùng form tick như gold đơn lượt (`prepare_gold`).
"""

import argparse
import csv
import html
import json
from pathlib import Path

import yaml

from experiments.prepare_gold import (
    REVIEW_BAR,
    REVIEW_CSS,
    REVIEW_FIELDS,
    _existing_reviews,
    digest,
    review_form,
    review_overview,
    review_scripts,
    saved_review,
)

ROOT = Path(__file__).resolve().parents[1]
V2_MULTITURN = ROOT / "benchmarks/v2/multiturn"
V2_DIALOGS = V2_MULTITURN / "dialogs.draft.jsonl"
CATALOG = ROOT / "configs/catalog/qnu-2025.yaml"
CATEGORIES = {
    "inherit", "school", "compare", "clarify", "reply", "loop", "switch", "year", "alias",
    "ambiguous", "across",
}  # fmt: skip
EXPECT_KEYS = {"majors", "year", "standalone", "standalone_ref", "decision"}
DECISIONS = {"proceed", "clarify", "proceed_after_clarify"}


def read_dialogs(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def validate_dialogs(dialogs: list[dict], catalog: Path = CATALOG) -> list[str]:
    majors = {m["id"] for m in yaml.safe_load(catalog.read_text(encoding="utf-8"))["majors"]}
    errors, seen = [], set()
    for d in dialogs:
        if d["id"] in seen:
            errors.append(f"{d['id']}: duplicate dialog id")
        seen.add(d["id"])
        if d.get("category") not in CATEGORIES:
            errors.append(f"{d['id']}: unknown category {d.get('category')!r}")
        if not d.get("turns"):
            errors.append(f"{d['id']}: no turns")
        for n, turn in enumerate(d.get("turns", []), 1):
            expect = turn.get("expect", {})
            if not turn.get("user", "").strip():
                errors.append(f"{d['id']} lượt {n}: empty user text")
            if extra := set(expect) - EXPECT_KEYS:
                errors.append(f"{d['id']} lượt {n}: unknown expect keys {sorted(extra)}")
            if "decision" in expect and expect["decision"] not in DECISIONS:
                errors.append(f"{d['id']} lượt {n}: unknown decision {expect['decision']!r}")
            for major in expect.get("majors", []):
                if major not in majors:
                    errors.append(f"{d['id']} lượt {n}: major {major!r} not in catalog")
    return errors


def _sync_reviews(dialogs: list[dict], csv_path: Path) -> None:
    """Thêm dòng `pending` cho hội thoại mới, cập nhật hash dòng còn `pending`; dòng đã duyệt
    giữ nguyên (hash cũ thì lần chốt sau sẽ bị từ chối, như gold đơn lượt)."""
    rows = list(_existing_reviews(csv_path).values()) if csv_path.exists() else []
    by_id = {row["item_id"]: row for row in rows}
    for d in dialogs:
        row = by_id.get(d["id"])
        if row is None:
            rows.append({"item_id": d["id"], "draft_sha256": digest(d), "decision": "pending"})
        elif row["decision"] == "pending":
            row["draft_sha256"] = digest(d)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _expect_cell(expect: dict) -> str:
    parts = []
    if "majors" in expect:
        parts.append("ngành: " + (", ".join(expect["majors"]) or "(không gắn ngành)"))
    if "year" in expect:
        parts.append(f"năm: {expect['year']}")
    if "decision" in expect:
        parts.append(f"quyết định: {expect['decision']}")
    if "standalone" in expect:
        parts.append(f"câu viết lại: {expect['standalone']!r}")
    if "standalone_ref" in expect:
        parts.append(f"câu viết lại tham khảo (không chấm): {expect['standalone_ref']!r}")
    return html.escape(" · ".join(parts) or "(không kỳ vọng gì ở lượt này)")


def dialog_packet(dialogs: list[dict], output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    csv_path = output / "reviews.csv"
    _sync_reviews(dialogs, csv_path)
    existing = _existing_reviews(csv_path)
    parts = [
        "<!doctype html><html lang='vi'><meta charset='utf-8'>",
        "<title>QNU v2 — duyệt hội thoại nhiều lượt</title>",
        REVIEW_CSS,
        REVIEW_BAR,
        f"<h1>{len(dialogs)} hội thoại — hồ sơ duyệt</h1>",
        review_overview(existing, [d["id"] for d in dialogs]),
        (
            "<p>Mỗi lượt ghi hành vi MONG MUỐN của bước hiểu câu hỏi: ngành và năm được hiểu, "
            "có hỏi lại hay đi tiếp. Không chép kết quả của code. Tick Đạt nếu kỳ vọng đúng với "
            "cách một cán bộ tư vấn sẽ hiểu câu; Cần sửa kèm ghi chú nếu không.</p>"
        ),
        (
            "<p>Quyết định: <b>proceed</b> đi tiếp; <b>clarify</b> hỏi lại ngành; "
            "<b>proceed_after_clarify</b> đi tiếp không gắn ngành sau khi đã hỏi lại một lần.</p>"
        ),
    ]
    for d in dialogs:
        rows = "".join(
            f"<tr><td>{n}</td><td>{html.escape(t['user'])}</td><td>{_expect_cell(t['expect'])}</td></tr>"
            for n, t in enumerate(d["turns"], 1)
        )
        parts.append(
            f"<article id='{html.escape(d['id'])}'><h2>{html.escape(d['id'])} — "
            f"{html.escape(d['category'])}</h2>"
            + (f"<p><b>Cần xem:</b> {html.escape(d['note'])}</p>" if d.get("note") else "")
            + "<table><tr><th>Lượt</th><th>Người dùng</th><th>Kỳ vọng</th></tr>"
            + rows
            + "</table>"
            + saved_review(existing.get(d["id"], {}), digest(d))
            + review_form(d["id"], digest(d))
            + "</article>"
        )
    parts += [*review_scripts(existing, storage_revision=digest(existing)), "</html>"]
    (output / "index.html").write_text("\n".join(parts), encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["check", "packet"])
    parser.add_argument("--draft", type=Path, default=V2_DIALOGS)
    parser.add_argument("--review-dir", type=Path, default=V2_MULTITURN / "review")
    args = parser.parse_args(argv)
    dialogs = read_dialogs(args.draft)
    errors = validate_dialogs(dialogs)
    if errors:
        print("Dialogs blocked:\n" + "\n".join(errors))
        return 2
    if args.action == "packet":
        dialog_packet(dialogs, args.review_dir)
    print(f"{len(dialogs)} dialogs: checks passed; action={args.action}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
