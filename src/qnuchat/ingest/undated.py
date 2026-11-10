"""Trang chưa suy được năm từ ngày đăng, URL hay tiêu đề: xét bằng chữ trong trang.

RUNBOOK 4.2.

Danh sách gồm cả trang được `prune` miễn (hạt giống, tầng A, hub): mục 4.3 chọn trang cho
snapshot đề án từ đây, kể cả các trang ngành của tuyensinh.
"""

import csv
import html
import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from qnuchat.ingest.blobs import BlobStore
from qnuchat.ingest.dating import BodyDating, date_from_body, infer_year
from qnuchat.ingest.extract import extract_html
from qnuchat.ingest.html_page import parse_page
from qnuchat.ingest.manifest import ManifestEntry

COLUMNS = ("url", "title", "exempt", "decision", "year", "evidence")


@dataclass(frozen=True)
class UndatedPage:
    entry: ManifestEntry
    dating: BodyDating


def page_text(entry: ManifestEntry, blobs: BlobStore) -> str:
    """Chữ phần nội dung chính, bỏ menu và cột bên như bộ lọc chủ đề. Mất blob thì rỗng."""
    path = blobs.path(entry.sha256) if entry.sha256 else None
    if path is None:
        return ""
    return extract_html(parse_page(path.read_bytes(), entry.url).main_html).text


def _day(value: str | None) -> date | None:
    return date.fromisoformat(value[:10]) if value else None


def undated_pages(
    current: Mapping[str, ManifestEntry], blobs: BlobStore, *, floor: int, today: date
) -> list[UndatedPage]:
    rows = []
    for url, entry in sorted(current.items()):
        if entry.kind != "page":
            continue
        year = infer_year(url=url, title=entry.title, published=_day(entry.published), today=today)
        if year is None:
            dating = date_from_body(page_text(entry, blobs), floor=floor, today=today)
            rows.append(UndatedPage(entry, dating))
    return rows


def write_review(
    rows: list[UndatedPage], path: Path, *, exempt: Callable[[str], bool]
) -> Counter[str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    counts: Counter[str] = Counter()
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            counts[row.dating.decision] += 1
            writer.writerow(
                {
                    "url": row.entry.url,
                    "title": row.entry.title or "",
                    "exempt": "yes" if exempt(row.entry.url) else "no",
                    "decision": row.dating.decision,
                    "year": row.dating.year or "",
                    "evidence": row.dating.evidence,
                }
            )
    return counts


# ------------------------------------------------------------ trang duyệt (RUNBOOK 4.3)

REVIEW_COLUMNS = ("url", "sha256", "exempt", "auto_decision", "label", "note", "reviewer", "at")
MAX_TEXT_CHARS = 6000
# Chỉ để hiển thị, không đổi chữ dùng để xét năm: menu site khoa lọt vào phần nội dung chính.
_JUNK_LINE = re.compile(r"^(?:\{\d+\}|##LOC\[\w+\]##|Some text in the modal\.)$")
_SHORT_WORDS = 6  # dòng từ chừng này chữ trở xuống là dòng ngắn (mục menu, ô bảng)
_MENU_RUN = 8  # chừng này dòng ngắn liền nhau thì gập lại
_DECISION_VI = {"keep": "tự giữ", "remove": "chỉ hiện hành trước mốc", "review": "cần duyệt"}


def _highlight(text: str, evidence: str) -> str:
    """Escape chữ trang, tô các cụm `evidence` (đã gộp khoảng trắng khi ghi) bằng `<mark>`."""
    snippets = sorted({s for s in evidence.split(" | ") if s.strip()}, key=len, reverse=True)
    if not snippets:
        return html.escape(text)
    alternatives = "|".join(r"\s+".join(map(re.escape, s.split())) for s in snippets)
    pattern = re.compile(alternatives, re.IGNORECASE)
    parts, pos = [], 0
    for match in pattern.finditer(text):
        parts += [html.escape(text[pos : match.start()]), f"<mark>{html.escape(match[0])}</mark>"]
        pos = match.end()
    parts.append(html.escape(text[pos:]))
    return "".join(parts)


def display_text(text: str, evidence: str) -> str:
    """HTML của chữ trang để duyệt: bỏ dòng rác template, gập chuỗi dòng ngắn dài (thường là menu)
    vào `<details>`, tô dấu hiệu năm."""
    lines = [line for line in text.splitlines() if not _JUNK_LINE.match(line.strip())]
    blocks: list[tuple[bool, list[str]]] = []  # (là chuỗi dòng ngắn, các dòng)
    for line in lines:
        short = len(line.split()) <= _SHORT_WORDS
        if blocks and blocks[-1][0] == short:
            blocks[-1][1].append(line)
        else:
            blocks.append((short, [line]))
    parts = []
    for short, block in blocks:
        chunk = _highlight("\n".join(block), evidence)
        count = sum(1 for line in block if line.strip())
        if short and count >= _MENU_RUN:
            chunk = (
                f"<details><summary>{count} dòng ngắn (menu hoặc bảng), bấm để mở</summary>"
                f"{chunk}</details>"
            )
        parts.append(chunk)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(parts)).strip()


def _review_item(row: UndatedPage, blobs: BlobStore, *, exempt: bool) -> str:
    entry, dating = row.entry, row.dating
    url = html.escape(entry.url)
    text = unicodedata.normalize("NFC", page_text(entry, blobs))
    more = len(text) - MAX_TEXT_CHARS
    body = display_text(text[:MAX_TEXT_CHARS], dating.evidence) if text else "(trang không có chữ)"
    if more > 0:
        body += f"\n… còn {more} ký tự, mở trang gốc để xem."
    evidence = html.escape(dating.evidence) or "không thấy"
    tags = [_DECISION_VI[dating.decision]]
    if dating.year:
        tags.append(f"năm {dating.year}")
    if exempt:
        tags.append("được miễn prune")
    choices = "".join(
        f'<label><input type=radio name="{url}" value="{value}"> {label}</label>'
        for value, label in (("vao", "Đưa vào snapshot"), ("khong", "Không đưa vào"))
    )
    return (
        f'<section data-url="{url}" data-sha="{html.escape(entry.sha256 or "")}" '
        f'data-decision="{dating.decision}" data-exempt="{"yes" if exempt else "no"}">'
        f"<h2>{html.escape(entry.title or entry.url)}</h2>"
        f'<p><a href="{url}" target="_blank" rel="noopener">{url}</a></p>'
        f'<p class=tags>{" · ".join(tags)}</p><p class=ev>Dấu hiệu năm: {evidence}</p>'
        f"<div class=text>{body}</div>"
        f'<p class=choice>{choices}<input class=note placeholder="Ghi chú (không bắt buộc)"></p>'
        "</section>"
    )


_REVIEW_PAGE = """<!doctype html><html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Duyệt trang không có ngày đăng</title><style>
body{font:15px/1.5 system-ui,sans-serif;max-width:900px;margin:0 auto;padding:0 16px;
  background:#fff;color:#111}
header{position:sticky;top:0;background:#fff;padding:8px 0;border-bottom:1px solid #ccc;z-index:1}
section{border:1px solid #ccc;border-radius:6px;padding:12px;margin:12px 0}
section.done{border-color:#2a7;background:#f3fbf6} section.hidden{display:none}
h2{font-size:17px;margin:0 0 4px} a{word-break:break-all}
.text{white-space:pre-wrap;background:#f6f6f6;padding:8px;max-height:360px;overflow:auto}
summary{color:#666;cursor:pointer} .ev{margin:4px 0}
mark{background:#ffe066} .tags{color:#555;margin:4px 0}
.choice label{margin-right:16px;font-weight:600}
.note{width:100%;margin-top:8px;padding:4px}
</style></head><body><header><h1>Duyệt trang không có ngày đăng</h1>
<p>Mỗi trang chọn có <b>đưa vào snapshot đề án</b> hay không (RUNBOOK 4.3).
Cụm tô vàng là dấu hiệu năm code đã đọc. Trang "được miễn prune" vẫn ở lại kho dù chọn gì.
Lựa chọn lưu tạm trong trình duyệt; bấm Xuất để lấy file.</p>
<label>Người duyệt: <input id=reviewer></label>
<label><input type=checkbox id=only checked> Chỉ hiện trang cần duyệt</label>
<span id=count></span> <button id=export>Xuất undated-review.csv</button>
<label>Nhập file đã xuất: <input type=file id=import accept=".csv,text/csv"></label></header>
{items}
<script>
const HEADER = "{header}";
const KEY = "undated-review-" + location.pathname;
const sections = [...document.querySelectorAll("section")];
let saved = {};
try { saved = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) {}
const reviewer = document.getElementById("reviewer");
const only = document.getElementById("only");
reviewer.value = saved.__reviewer || "";
const item = (url) => (saved[url] = saved[url] || {});
function refresh() {
  let done = 0, shown = 0, todo = 0;
  for (const s of sections) {
    const v = saved[s.dataset.url] || {};
    const review = s.dataset.decision === "review";
    s.classList.toggle("done", !!v.label);
    s.classList.toggle("hidden", only.checked && !review);
    if (v.label) { done++; s.querySelector(`input[value="${v.label}"]`).checked = true; }
    s.querySelector(".note").value = v.note || "";
    if (review) { todo++; if (v.label) shown++; }
  }
  document.getElementById("count").textContent =
    `Cần duyệt: ${shown}/${todo} · đã chọn tất cả: ${done}/${sections.length}`;
}
function store() { try { localStorage.setItem(KEY, JSON.stringify(saved)); } catch (e) {} }
document.addEventListener("change", (e) => {
  if (e.target.type === "radio") { item(e.target.name).label = e.target.value; store(); refresh(); }
});
document.addEventListener("input", (e) => {
  if (e.target.classList.contains("note")) {
    item(e.target.closest("section").dataset.url).note = e.target.value; store();
  }
});
reviewer.addEventListener("input", () => { saved.__reviewer = reviewer.value; store(); });
only.addEventListener("change", refresh);
const q = (v) => '"' + String(v).replaceAll('"', '""') + '"';
document.getElementById("export").addEventListener("click", () => {
  const at = new Date().toISOString();
  const lines = [HEADER];
  for (const s of sections) {
    const v = saved[s.dataset.url];
    if (!v || !v.label) continue;
    const d = s.dataset;
    lines.push([d.url, d.sha, d.exempt, d.decision, v.label, v.note || "", reviewer.value, at]
      .map(q).join(","));
  }
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([lines.join("\\n") + "\\n"], {type: "text/csv"}));
  a.download = "undated-review.csv";
  a.click();
});
// Lựa chọn lưu theo từng trình duyệt: nhập lại file đã xuất để làm tiếp ở trình duyệt hay máy khác.
function parseCsv(text) {
  const rows = []; let row = [], field = "", quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') { field += '"'; i++; }
      else if (c === '"') quoted = false;
      else field += c;
    } else if (c === '"') quoted = true;
    else if (c === ",") { row.push(field); field = ""; }
    else if (c === "\\n" || c === "\\r") {
      if (c === "\\r" && text[i + 1] === "\\n") i++;
      row.push(field); rows.push(row); row = []; field = "";
    } else field += c;
  }
  if (field || row.length) { row.push(field); rows.push(row); }
  return rows.filter((r) => r.some((v) => v !== ""));
}
document.getElementById("import").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const [head, ...rows] = parseCsv(await file.text());
  const col = Object.fromEntries(head.map((name, i) => [name, i]));
  if (!("url" in col) || !("label" in col)) { alert("File không phải undated-review.csv"); return; }
  let n = 0;
  for (const r of rows) {
    if (!r[col.label]) continue;
    saved[r[col.url]] = { label: r[col.label], note: r[col.note] || "" };
    if (r[col.reviewer] && !reviewer.value) reviewer.value = saved.__reviewer = r[col.reviewer];
    n++;
  }
  store(); refresh();
  alert(`Đã nhập ${n} lựa chọn.`);
  e.target.value = "";
});
refresh();
</script></body></html>
"""


def render_review(
    rows: list[UndatedPage], blobs: BlobStore, *, exempt: Callable[[str], bool]
) -> str:
    """Trang HTML một file để Kent duyệt; xuất `undated-review.csv` theo `REVIEW_COLUMNS`."""
    items = "\n".join(_review_item(row, blobs, exempt=exempt(row.entry.url)) for row in rows)
    return _REVIEW_PAGE.replace("{header}", ",".join(REVIEW_COLUMNS)).replace("{items}", items)
