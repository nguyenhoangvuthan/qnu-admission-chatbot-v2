"""Validate source-backed drafts, render review packets, promote signed reviews.

No reviewer is invented. A draft is never written to the experiment gold path
until each item has an explicit, hash-bound human review in reviews.csv.
"""

import argparse
import csv
import hashlib
import html
import json
import os
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path

import pymupdf
from docx import Document

from experiments.doc_lines import docx_lines, html_lines
from experiments.provenance import sha256_file
from experiments.sources import source_path
from qnuchat.eval.schema import GoldItem

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "benchmarks/pilot"
DRAFT = PILOT / "gold.draft.jsonl"
# Gold v2: nhiều văn bản nguồn; truy hồi chấm theo `gold_evidence` = [nguồn, trang].
V2 = ROOT / "benchmarks/v2"
V2_DRAFT = V2 / "comparison.draft.jsonl"
PROFILES = ("pilot", "v2")
# Trang Cẩm nang 2025 gần như không có lớp chữ; pilot không được lấy làm bằng chứng.
PILOT_EXCLUDED_PAGES = frozenset({1, 2, 3, 107, 108})
REVIEW_FIELDS = ["item_id", "draft_sha256", "decision", "reviewer", "verified_at", "notes"]


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def normalise(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split())


def read_drafts(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def read_v2_drafts() -> list[dict]:
    """Mọi file nháp của gold v2 (`benchmarks/v2/*.draft.jsonl`) để duyệt trong một hồ sơ."""
    return [r for path in sorted(V2.glob("*.draft.jsonl")) for r in read_drafts(path)]


def resolve_source(root: Path, source: str) -> Path:
    """Gold ghi đường dẫn lúc tạo (data/<file>); file nay nằm trong thư mục chủ đề của data/."""
    path = root / source
    return path if path.exists() else source_path(path.name, root / "data")


def _locator(evidence: dict):
    return evidence.get("page", evidence.get("paragraph", evidence.get("line")))


def _source_texts(path: Path, by_line: bool) -> dict[int, str]:
    """Text theo chỗ định vị: trang PDF (1-based), đoạn DOCX, hoặc dòng (0-based) của HTML/DOCX
    như `html_lines`/`docx_lines` đọc — dòng DOCX gồm cả dòng bảng."""
    if by_line:
        if path.suffix == ".html":
            return dict(enumerate(html_lines(path.read_text(encoding="utf-8", errors="replace"))))
        if path.suffix == ".docx":
            return dict(enumerate(docx_lines(path)))
    elif path.suffix == ".pdf":
        with pymupdf.open(path) as doc:
            return {i + 1: page.get_text() for i, page in enumerate(doc)}
    elif path.suffix == ".docx":
        return {i: p.text for i, p in enumerate(Document(path).paragraphs)}
    raise ValueError(f"Unsupported source: {path.name}")


def validate_drafts(records: list[dict], root: Path = ROOT, profile: str = "pilot") -> list[str]:
    """Kiểm nguồn của bản nháp. `profile="v2"` bỏ hai luật riêng của pilot (trang loại trừ của
    Cẩm nang, tỷ lệ 40/22/8) và kiểm `gold_evidence` thay cho `gold_page_ids` một PDF."""
    if profile not in PROFILES:
        raise ValueError(f"profile phải là một trong {PROFILES}")
    errors = []
    sources = {}
    ids = set()
    questions = set()
    for record in records:
        item = GoldItem.model_validate(record["item"])
        if item.id in ids or normalise(item.question).casefold() in questions:
            errors.append(f"{item.id}: duplicate ID/question")
        ids.add(item.id)
        questions.add(normalise(item.question).casefold())
        if item.reviewer:
            errors.append(f"{item.id}: draft must not claim human review")
        if item.must_abstain:
            if item.expected_slots or item.gold_page_ids:
                errors.append(f"{item.id}: unanswerable item has positive slots/pages")
            if not record.get("abstention_rationale"):
                errors.append(f"{item.id}: missing abstention rationale")
        elif not item.expected_slots or (profile == "pilot" and not item.gold_page_ids):
            errors.append(f"{item.id}: answerable item needs slots and pages")
        if profile == "pilot" and set(item.gold_page_ids) & PILOT_EXCLUDED_PAGES:
            errors.append(f"{item.id}: cites excluded page")
        if not record.get("reference_answer") or not record.get("evidence"):
            errors.append(f"{item.id}: missing reference answer/evidence")
        if set(item.condition_synonyms) - set(item.required_conditions):
            errors.append(f"{item.id}: synonym key is not a required condition")
        for condition in item.required_conditions:
            variants = [condition, *item.condition_synonyms.get(condition, [])]
            if not any(v.lower() in record["reference_answer"].lower() for v in variants):
                errors.append(f"{item.id}: reference answer misses condition {condition!r}")
        pages = set()
        for evidence in record["evidence"]:
            source = evidence["source"]
            key = (source, "line" in evidence)
            if key not in sources:
                path = resolve_source(root, source)
                sources[key] = (sha256_file(path), _source_texts(path, by_line=key[1]))
            actual_hash, texts = sources[key]
            locator = _locator(evidence)
            if actual_hash != evidence["sha256"]:
                errors.append(f"{item.id}: source hash changed: {source}")
            if not evidence["quote"].strip() or normalise(evidence["quote"]) not in normalise(
                texts.get(locator, "")
            ):
                errors.append(f"{item.id}: quote not found at {source}:{locator}")
            if source.endswith(".pdf"):
                pages.add(locator)
        if not set(item.gold_page_ids) <= pages:
            errors.append(f"{item.id}: gold pages lack source excerpts")
        if profile == "v2":
            errors += _check_gold_evidence(record)
    counts = Counter(r["item"]["origin"] for r in records)
    if profile == "pilot" and counts != {"curated": 40, "challenge": 22, "noisy": 8}:
        errors.append(f"Expected 40 curated / 22 challenge / 8 noisy, got {dict(counts)}")
    by_id = {r["item"]["id"]: r for r in records}
    for r in records:
        if r["item"]["origin"] != "noisy":
            continue
        parent = by_id.get(r.get("variant_of"))
        if not parent or parent["item"]["origin"] != "curated":
            errors.append(f"{r['item']['id']}: missing curated parent")
            continue
        for field in (
            "expected_slots",
            "source_family",
            "gold_page_ids",
            "required_conditions",
            "must_abstain",
            "admission_year",
            "risk",
        ):
            if r["item"][field] != parent["item"][field]:
                errors.append(f"{r['item']['id']}: noisy variant changed {field}")
    return errors


def _check_gold_evidence(record: dict) -> list[str]:
    item = record["item"]
    gold = {tuple(pair) for pair in record.get("gold_evidence", [])}
    quoted = {(e["source"], _locator(e)) for e in record["evidence"]}
    errors = []
    if not item["must_abstain"] and not gold:
        errors.append(f"{item['id']}: answerable v2 item needs gold_evidence")
    if gold - quoted:
        errors.append(
            f"{item['id']}: gold_evidence without source excerpt: {sorted(gold - quoted)}"
        )
    if {loc for src, loc in gold if src.endswith(".pdf")} != set(item["gold_page_ids"]):
        errors.append(f"{item['id']}: gold_page_ids do not match gold_evidence pages")
    return errors


def highlight_rects(page, quote: str) -> list:
    """Vùng cần tô trên trang cho một trích đoạn.

    Dòng trích tìm thấy nguyên văn thì tô cả dòng. Dòng trải qua nhiều cột của bảng (tên ngành,
    mã, điểm) thì tô từng từ, chọn chỗ xuất hiện gần dòng của từ chỉ xuất hiện một lần trên trang
    (thường là mã ngành), để số trùng ở dòng khác không bị tô.
    """
    rects = []
    for line in (ln.strip() for ln in quote.splitlines()):
        if not line:
            continue
        found = page.search_for(line)
        if found:
            rects += found
            continue
        hits = {token: page.search_for(token) for token in line.split()}
        anchors = [found[0] for found in hits.values() if len(found) == 1]
        if not anchors:
            continue
        anchor = anchors[0]
        centre = (anchor.y0 + anchor.y1) / 2
        tolerance = anchor.height
        for found in hits.values():
            if not found:
                continue
            best = min(found, key=lambda r: abs((r.y0 + r.y1) / 2 - centre))
            if abs((best.y0 + best.y1) / 2 - centre) <= tolerance:
                rects.append(best)
    return rects


FOCUS_MAX_LINES = 6


def focus_quote(quote: str, values: list[str]) -> str:
    """Phần trích đoạn cần tô. Trích đoạn ngắn giữ nguyên; trích cả trang (gold pilot) chỉ giữ
    các dòng chứa giá trị mong đợi, để ảnh không bị tô kín."""
    lines = [ln for ln in quote.splitlines() if ln.strip()]
    if len(lines) <= FOCUS_MAX_LINES:
        return quote
    wanted = [normalise(v) for v in values if v.strip()]
    return "\n".join(ln for ln in lines if any(v in normalise(ln) for v in wanted))


def _image_name(source: str, page: int, profile: str) -> str:
    if profile == "pilot":  # pilot chỉ có một PDF; giữ tên cũ cho hồ sơ đã render
        return f"page-{page:03}.png"
    return f"{hashlib.sha256(source.encode()).hexdigest()[:8]}-p{page:03}.png"


def _refresh_pending(records: list[dict], csv_path: Path) -> None:
    """Cập nhật `draft_sha256` cho dòng còn `pending` và thêm dòng cho câu nháp mới.

    Dòng đã có quyết định (approve/reject) không bị đụng tới, kể cả khi hash đã cũ: `promote`
    vẫn từ chối dòng đó cho tới khi người duyệt xem lại. Dùng khi bản nháp đổi trước khi duyệt
    (ví dụ đường dẫn nguồn đổi `docs/` → `data/` ngày 02/10/2026).
    """
    with csv_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != REVIEW_FIELDS:
            raise ValueError(f"{csv_path}: không phải reviews.csv hợp lệ (cột {reader.fieldnames})")
        rows = list(reader)
    by_id = {row["item_id"]: row for row in rows}
    for r in records:
        row = by_id.get(r["item"]["id"])
        if row is None:
            rows.append(
                {"item_id": r["item"]["id"], "draft_sha256": digest(r), "decision": "pending"}
            )
        elif row["decision"] == "pending":
            row["draft_sha256"] = digest(r)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _existing_reviews(csv_path: Path) -> dict[str, dict]:
    """Dòng đã có trong reviews.csv để form trong hồ sơ hiện lại; file hỏng thì bỏ qua."""
    with csv_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != REVIEW_FIELDS:
            return {}
        return {row["item_id"]: row for row in reader}


# Thư viện thuần (không đụng DOM) để test được bằng node.
REVIEW_LIB_JS = r"""
const FIELDS = __FIELDS__;
function pad(n) { return String(Math.abs(n)).padStart(2, "0"); }
function isoLocal(d) {
  const off = -d.getTimezoneOffset();
  return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate())
    + "T" + pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds())
    + (off >= 0 ? "+" : "-") + pad(Math.floor(Math.abs(off) / 60)) + ":" + pad(Math.abs(off) % 60);
}
function csvCell(value) {
  const text = value == null ? "" : String(value);
  return /[",\r\n]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text;
}
function toCsv(fields, rows) {
  const lines = [fields.join(",")].concat(rows.map(r => fields.map(f => csvCell(r[f])).join(",")));
  return lines.join("\r\n") + "\r\n";
}
""".replace("__FIELDS__", json.dumps(REVIEW_FIELDS))

# Gắn form vào trang: tick → điền người duyệt và giờ; lưu nháp trong trình duyệt; xuất CSV.
REVIEW_FORM_JS = """
(function () {
  const saved = JSON.parse(document.getElementById("review-rows").textContent);
  const revision = document.getElementById("review-rows").dataset.storageRevision;
  const key = "gold-review:" + location.pathname + (revision ? ":" + revision : "");
  let local = {};
  try { local = JSON.parse(localStorage.getItem(key) || "{}"); } catch (e) { local = {}; }
  const nameBox = document.getElementById("reviewer");
  try { nameBox.value = localStorage.getItem("gold-reviewer") || ""; } catch (e) {}
  nameBox.addEventListener("input", () => {
    try { localStorage.setItem("gold-reviewer", nameBox.value.trim()); } catch (e) {}
  });
  const forms = Array.from(document.querySelectorAll("fieldset.review"));
  const state = {};
  function persist() {
    try { localStorage.setItem(key, JSON.stringify(state)); } catch (e) {}
    const done = Object.values(state).filter(r => r.decision !== "pending").length;
    document.getElementById("progress").textContent =
      done + "/" + forms.length + " câu đã có quyết định";
  }
  function show(form, row) {
    form.querySelector(".ok").checked = row.decision === "approve";
    form.querySelector(".bad").checked = row.decision === "reject";
    form.querySelector(".notes").value = row.notes || "";
    form.querySelector(".when").textContent =
      row.decision === "pending" ? "" : (row.reviewer || "") + " · " + (row.verified_at || "");
    form.closest("article").dataset.decision = row.decision;
  }
  forms.forEach(form => {
    const id = form.dataset.item, hash = form.dataset.hash;
    const mine = local[id] && local[id].draft_sha256 === hash ? local[id] : null;
    // Quyết định gắn với nội dung cũ (hash khác) thì không tick sẵn: phải duyệt lại.
    const prior = saved[id] && saved[id].draft_sha256 === hash ? saved[id] : null;
    state[id] = Object.assign({item_id: id, draft_sha256: hash, decision: "pending",
      reviewer: "", verified_at: "", notes: ""}, prior || {}, mine || {});
    show(form, state[id]);
    function decide(decision) {
      const reviewer = nameBox.value.trim();
      if (decision !== "pending" && !reviewer) {
        alert("Nhập tên người duyệt ở đầu trang trước khi tick.");
        show(form, state[id]);
        return;
      }
      Object.assign(state[id], {draft_sha256: hash, decision: decision,
        reviewer: decision === "pending" ? "" : reviewer,
        verified_at: decision === "pending" ? "" : isoLocal(new Date())});
      show(form, state[id]);
      persist();
    }
    form.querySelector(".ok").addEventListener("change",
      e => decide(e.target.checked ? "approve" : "pending"));
    form.querySelector(".bad").addEventListener("change",
      e => decide(e.target.checked ? "reject" : "pending"));
    form.querySelector(".notes").addEventListener("input",
      e => { state[id].notes = e.target.value; persist(); });
  });
  persist();
  document.getElementById("export").addEventListener("click", () => {
    const rows = forms.map(f => state[f.dataset.item]);
    const blob = new Blob([toCsv(FIELDS, rows)], {type: "text/csv;charset=utf-8"});
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "reviews.csv";
    link.click();
    URL.revokeObjectURL(link.href);
  });
})();
"""


REVIEW_CSS = (
    "<style>body{max-width:1050px;margin:2em auto;font:17px/1.6 sans-serif}"
    "article{border-top:2px solid #999;padding:1em 0}pre{white-space:pre-wrap}"
    "blockquote{background:#f3f5f7;padding:1em}img{max-width:100%}"
    "#bar{position:sticky;top:0;background:#fff;border-bottom:1px solid #999;"
    "padding:.5em 0;display:flex;gap:1em;align-items:center;flex-wrap:wrap;z-index:1}"
    "fieldset.review{border:1px solid #bbb;border-radius:6px;margin:1em 0}"
    "fieldset.review label{margin-right:1.5em;font-weight:bold}"
    "fieldset.review textarea{width:100%;min-height:3em;margin-top:.5em}"
    ".when{color:#555;font-size:.9em}"
    "article[data-decision=approve] h2{color:#1a7f37}"
    "article[data-decision=reject] h2{color:#c62828}"
    "table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:.3em .6em}</style>"
)
REVIEW_BAR = (
    "<div id='bar'><label>Người duyệt: <input id='reviewer' "
    "placeholder='Họ tên'></label><span id='progress'></span>"
    "<button id='export' type='button'>Xuất reviews.csv</button></div>"
)


def review_form(item_id: str, item_hash: str) -> str:
    """Ô Đạt / Cần sửa + ghi chú của một mục, gắn với hash của bản nháp đang hiện."""
    return (
        f'<fieldset class="review" data-item="{html.escape(item_id)}" '
        f'data-hash="{item_hash}"><legend>Duyệt {html.escape(item_id)}</legend>'
        '<label><input type="checkbox" class="ok"> Đạt</label>'
        '<label><input type="checkbox" class="bad"> Cần sửa</label>'
        '<span class="when"></span>'
        '<textarea class="notes" placeholder="Ghi chú (bắt buộc khi Cần sửa)"></textarea>'
        "</fieldset>"
    )


def review_scripts(existing: dict[str, dict], *, storage_revision: str = "") -> list[str]:
    rows_json = json.dumps(existing, ensure_ascii=False).replace("</", "<\\/")
    return [
        (
            f'<script id="review-rows" type="application/json" '
            f'data-storage-revision="{html.escape(storage_revision, quote=True)}">'
            f"{rows_json}</script>"
        ),
        f'<script id="review-lib">{REVIEW_LIB_JS}</script>',
        f"<script>{REVIEW_FORM_JS}</script>",
    ]


def saved_review(row: dict, current_hash: str) -> str:
    """Hiện quyết định đã ghi vào CSV, độc lập với bản nháp của trình duyệt."""
    labels = {"approve": "Đạt", "reject": "Cần sửa", "pending": "Chưa duyệt"}
    decision = row.get("decision", "pending")
    if decision == "pending":
        return ""
    stale = row.get("draft_sha256") != current_hash
    label = "Nội dung đã thay đổi — cần duyệt lại" if stale else labels.get(decision, decision)
    return (
        "<blockquote class='saved-review'>"
        f"<b>Kết quả đã lưu: {html.escape(label)}</b>"
        f"<p>{html.escape(row.get('reviewer', ''))} · "
        f"{html.escape(row.get('verified_at', ''))}</p>"
        f"<p style='white-space:pre-wrap'>{html.escape(row.get('notes', ''))}</p></blockquote>"
    )


def review_overview(existing: dict[str, dict], item_ids: list[str]) -> str:
    """Tổng hợp hồ sơ đã lưu và đường dẫn nhanh đến các mục cần sửa."""
    rows = {key: existing.get(key, {}) for key in item_ids}
    counts = Counter(row.get("decision", "pending") for row in rows.values())
    rejected = [key for key, row in rows.items() if row.get("decision") == "reject"]
    links = " · ".join(
        f"<a href='#{html.escape(key, quote=True)}'>{html.escape(key)}</a>" for key in rejected
    )
    return (
        "<section id='review-summary'><h2>Kết quả đã lưu</h2>"
        f"<p><b>{counts['approve']} đạt · {counts['reject']} cần sửa · "
        f"{counts['pending']} chưa duyệt</b></p>"
        "<p>Tên người duyệt ghi ở từng mục. Hồ sơ chưa được promote thành gold chính thức; "
        "sửa các ô bên dưới rồi xuất CSV.</p>"
        + (f"<p><b>Mục cần sửa:</b> {links}</p>" if rejected else "")
        + "</section>"
    )


def review_packet(
    records: list[dict],
    output: Path,
    *,
    render: bool = False,
    refresh_pending: bool = False,
    profile: str = "pilot",
) -> None:
    output.mkdir(parents=True, exist_ok=True)
    csv_path = output / "reviews.csv"
    # Preserve manual work; detect stale item hashes during promotion instead.
    if not csv_path.exists():
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=REVIEW_FIELDS)
            writer.writeheader()
            for r in records:
                writer.writerow(
                    {"item_id": r["item"]["id"], "draft_sha256": digest(r), "decision": "pending"}
                )
    elif refresh_pending:
        _refresh_pending(records, csv_path)
    existing = _existing_reviews(csv_path)
    image_dir = output / "pages"
    if render:
        image_dir.mkdir(exist_ok=True)
        source_pages: dict[str, dict[int, set[str]]] = {}
        for r in records:
            for e in r["evidence"]:
                if "page" in e:
                    quotes = source_pages.setdefault(e["source"], {}).setdefault(e["page"], set())
                    values = [
                        v
                        for slot in r["item"]["expected_slots"]
                        for v in [slot["value"], *slot.get("value_synonyms", [])]
                    ]
                    quotes.add(focus_quote(e["quote"], values))
        zoom = 1.3 if profile == "pilot" else 2.0
        for source, pages in source_pages.items():
            with pymupdf.open(resolve_source(ROOT, source)) as doc:
                for p in sorted(pages):
                    page = doc[p - 1]
                    if profile == "v2":  # trích đoạn v2 ngắn: tô đúng dòng cần kiểm
                        for quote in sorted(pages[p]):
                            rects = highlight_rects(page, quote)
                            if rects:
                                page.add_highlight_annot(rects)
                    page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom)).save(
                        image_dir / _image_name(source, p, profile)
                    )
    parts = [
        "<!doctype html><html lang='vi'><meta charset='utf-8'>",
        f"<title>QNU {profile} — duyệt gold</title>",
        REVIEW_CSS,
        REVIEW_BAR,
        f"<h1>{len(records)} câu — hồ sơ duyệt {profile}</h1>",
        review_overview(existing, [r["item"]["id"] for r in records]) if profile == "v2" else "",
        (
            "<p>Đối chiếu câu hỏi, từng slot, năm, điều kiện, trang và mức rủi ro. "
            "Câu challenge chỉ đo thiếu nguồn chính thức trong corpus; không kết luận "
            "nội dung fanpage đúng/sai ngoài thực tế. Ghi approve, tên người duyệt và "
            "thời điểm ISO 8601 có múi giờ vào reviews.csv. Không duyệt nếu cần sửa.</p>"
            if profile == "pilot"
            else "<p>Đối chiếu câu hỏi, câu trả lời mẫu và từng số với trang gốc (dòng được tô "
            "vàng là trích đoạn). Ghi approve, tên người duyệt và thời điểm ISO 8601 có múi giờ "
            "vào reviews.csv. Câu cần sửa thì ghi reject kèm ghi chú.</p>"
        ),
    ]
    for r in records:
        item = r["item"]
        parts += [
            (
                f"<article id='{html.escape(item['id'])}'><h2>{item['id']} — "
                f"{html.escape(r['task_type'])}</h2><p>{html.escape(item['question'])}</p>"
            ),
            f"<p><b>Đáp án tham chiếu:</b> {html.escape(r['reference_answer'])}</p>",
            f"<p>{html.escape(r.get('abstention_rationale', ''))}</p>",
        ]
        if "review_note" in r:
            parts.append(f"<p><b>Cần xem:</b> {html.escape(r['review_note'])}</p>")
        rubric = item if "gold_evidence" not in r else {**item, "gold_evidence": r["gold_evidence"]}
        parts.append(
            "<details><summary>Slots và rubric</summary><pre>"
            + html.escape(json.dumps(rubric, ensure_ascii=False, indent=2))
            + "</pre></details>"
        )
        for e in r["evidence"]:
            if "page" in e:
                locator = f"trang PDF {e['page']}"
            elif "line" in e:
                locator = f"dòng {e['line']} (0-based, đọc như html_lines/docx_lines)"
            else:
                locator = f"đoạn DOCX {e['paragraph']} (0-based)"
            parts.append(
                f"<p>{html.escape(e['source'])} — {locator}</p>"
                f"<blockquote>{html.escape(e['quote'])}</blockquote>"
            )
            if "page" in e:
                image = _image_name(e["source"], e["page"], profile)
                parts.append(
                    f"<details><summary>Xem trang gốc {e['page']}</summary>"
                    f"<img loading='lazy' src='pages/{image}'></details>"
                )
        if profile == "v2":
            parts.append(saved_review(existing.get(item["id"], {}), digest(r)))
        parts.append(review_form(item["id"], digest(r)) + "</article>")
    parts += [
        *review_scripts(existing, storage_revision=digest(existing) if profile == "v2" else ""),
        "</html>",
    ]
    (output / "index.html").write_text("\n".join(parts), encoding="utf-8")


def promote(records: list[dict], reviews_path: Path, output: Path, profile: str = "pilot") -> None:
    errors = validate_drafts(records, profile=profile)
    if errors:
        raise ValueError("\n".join(errors))
    with reviews_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    reviews = {row["item_id"]: row for row in rows}
    if len(rows) != len(reviews) or set(reviews) != {r["item"]["id"] for r in records}:
        raise ValueError("Reviews must cover each draft exactly once")
    approved = []
    for record in records:
        row = reviews[record["item"]["id"]]
        if row["decision"] != "approve" or row["draft_sha256"] != digest(record):
            raise ValueError(f"{row['item_id']}: pending/rejected or stale review")
        reviewer = row["reviewer"].strip()
        if not reviewer or reviewer.casefold() in {"pending", "codex", "claude", "ai", "todo"}:
            raise ValueError(f"{row['item_id']}: human reviewer required")
        when = datetime.fromisoformat(row["verified_at"])
        if when.tzinfo is None or when > datetime.now(when.tzinfo):
            raise ValueError(f"{row['item_id']}: timestamp needs timezone and cannot be future")
        approved.append(
            {**record["item"], "reviewer": reviewer, "verified_at": row["verified_at"]}
            | ({"gold_evidence": record["gold_evidence"]} if profile == "v2" else {})
        )
    if output.exists() or output.with_suffix(".review.json").exists():
        raise ValueError("Gold already exists; use a new version/path to preserve frozen data")
    output.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in approved), encoding="utf-8"
    )
    manifest = {
        "status": "human_reviewed",
        "gold_sha256": sha256_file(output),
        "draft_sha256": digest(records),
        "reviews_sha256": sha256_file(reviews_path),
        "reviews_path": os.path.relpath(reviews_path.resolve(), ROOT),
        "source_hashes": {e["source"]: e["sha256"] for r in records for e in r["evidence"]},
        "n_items": len(approved),
        "review_method": "LLM draft; human source verification",
    }
    output.with_suffix(".review.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["check", "packet", "promote"])
    parser.add_argument("--profile", choices=PROFILES, default="pilot")
    parser.add_argument(
        "--draft", type=Path, help="mặc định: gold pilot, hoặc mọi benchmarks/v2/*.draft.jsonl"
    )
    parser.add_argument("--review-dir", type=Path, help="mặc định theo profile")
    parser.add_argument("--output", type=Path, help="mặc định theo profile")
    parser.add_argument("--render", action="store_true")
    parser.add_argument(
        "--refresh-pending",
        action="store_true",
        help="packet: cập nhật hash dòng pending trong reviews.csv (dòng đã duyệt giữ nguyên)",
    )
    args = parser.parse_args(argv)
    base, draft = (PILOT, DRAFT) if args.profile == "pilot" else (V2, V2_DRAFT)
    whole_v2 = args.profile == "v2" and args.draft is None  # mặc định v2: mọi file nháp
    args.draft = args.draft or draft
    args.review_dir = args.review_dir or base / "review"
    args.output = args.output or base / "gold.jsonl"
    try:
        records = read_v2_drafts() if whole_v2 else read_drafts(args.draft)
        errors = validate_drafts(records, profile=args.profile)
        if errors:
            raise ValueError("\n".join(errors))
        if args.action == "packet":
            review_packet(
                records,
                args.review_dir,
                render=args.render,
                refresh_pending=args.refresh_pending,
                profile=args.profile,
            )
        elif args.action == "promote":
            promote(records, args.review_dir / "reviews.csv", args.output, profile=args.profile)
        print(f"{len(records)} drafts: source checks passed; action={args.action}")
        return 0
    except (ValueError, OSError, KeyError) as exc:
        print(f"Gold blocked: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
