"""Mẫu đo bộ lọc chủ đề và form gán nhãn offline cho Kent (spec knowledge base §5.4).

Mẫu bốc trước khi xem nhãn model: `draw_sample` không nhận sổ quyết định. Phân bổ đều theo nhóm
host (Kent đồng ý 23/10/2026, plan V2) để mẫu có đủ mục `giu` cho cận trên Wilson; trong nhóm chia
theo tỉ lệ `kind`. Form không chứa nhãn hay tên bộ phân loại để người gán không bị dẫn dắt.
"""

import base64
import html
import io
import json
import random
from collections import defaultdict
from collections.abc import Callable, Hashable
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from qnuchat.ingest.blobs import BlobStore
from qnuchat.ingest.manifest import ManifestEntry
from qnuchat.ingest.topic_filter.classifier import render_input
from qnuchat.ingest.topic_filter.inputs import BlobMissing, build_input
from qnuchat.ingest.topic_filter.ledger import TopicConfig

HOST_SUFFIX = ".qnu.edu.vn"
TOP_UP_GROUPS = frozenset({"tuyensinh", "khoa"})
MIN_PER_KIND = 3
THUMB_PX = 600
CSV_HEADER = "item_id,url,sha256,label,reviewer,at"


def host_group(host: str, groups: dict[str, list[str]]) -> str:
    short = host.removesuffix(HOST_SUFFIX)
    for name, members in groups.items():
        if short in members:
            return name
    return "khac"


def _allocate(
    total: int, sizes: dict[Hashable, int], weights: dict[Hashable, float], minimum: int = 0
) -> dict[Hashable, int]:
    """Chia `total` theo `weights`, không vượt `sizes`, mỗi khoá ít nhất `minimum` (nếu đủ mục).
    Phần dư làm tròn theo phần lẻ lớn nhất; phần khoá nào không dùng hết chia lại cho khoá khác."""
    alloc = {k: min(minimum, sizes[k]) for k in sizes}
    remaining = min(total, sum(sizes.values())) - sum(alloc.values())
    while remaining > 0:
        open_keys = [k for k in sizes if alloc[k] < sizes[k]]
        weight = sum(weights[k] for k in open_keys)
        shares = {k: remaining * weights[k] / weight for k in open_keys}
        added = {k: min(int(shares[k]), sizes[k] - alloc[k]) for k in open_keys}
        if sum(added.values()) == 0:
            # Phần lẻ: lần lượt cho khoá có phần lẻ lớn nhất (thứ tự khoá tất định khi bằng nhau).
            order = sorted(open_keys, key=lambda k: (-(shares[k] - int(shares[k])), str(k)))
            added = {order[0]: 1}
        for k, v in added.items():
            alloc[k] += v
            remaining -= v
    return alloc


def draw_sample(
    candidates: list[ManifestEntry],
    *,
    groups: dict[str, list[str]],
    n: int,
    seed: int,
    exclude: set[str] | frozenset[str] = frozenset(),
    only_groups: set[str] | frozenset[str] | None = None,
) -> list[ManifestEntry]:
    strata: dict[str, dict[str, list[ManifestEntry]]] = defaultdict(lambda: defaultdict(list))
    for entry in sorted(candidates, key=lambda e: e.url):
        group = host_group(entry.host, groups)
        if entry.url in exclude or (only_groups is not None and group not in only_groups):
            continue
        strata[group][entry.kind].append(entry)
    group_sizes = {g: sum(len(v) for v in kinds.values()) for g, kinds in strata.items()}
    per_group = _allocate(n, group_sizes, {g: 1.0 for g in group_sizes})
    rng = random.Random(seed)
    chosen: list[ManifestEntry] = []
    for group in sorted(strata):
        kinds = strata[group]
        sizes = {k: len(v) for k, v in kinds.items()}
        per_kind = _allocate(
            per_group[group], sizes, {k: float(v) for k, v in sizes.items()}, MIN_PER_KIND
        )
        for kind in sorted(kinds):
            chosen += rng.sample(kinds[kind], per_kind[kind])
    rng.shuffle(chosen)
    return chosen


def read_rounds(out_dir: Path) -> list[dict]:
    rows: list[dict] = []
    for path in sorted(Path(out_dir).glob("round-*.jsonl"), key=lambda p: int(p.stem[6:])):
        rows += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return rows


def _thumbnail(path: Path) -> str | None:
    try:
        with Image.open(path) as image:
            image = image.convert("RGB")
            image.thumbnail((THUMB_PX, THUMB_PX))
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=80)
    except (UnidentifiedImageError, OSError):
        return None
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _item_html(
    row: dict, entry: ManifestEntry | None, *, current, blobs, max_chars, ocr_documents
) -> str:
    item_id = html.escape(row["item_id"])
    url = html.escape(row["url"])
    if entry is None:
        body = "<p class=warn>Mục không còn trong kho.</p>"
    else:
        try:
            text = render_input(
                build_input(
                    entry,
                    current=current,
                    blobs=blobs,
                    max_chars=max_chars,
                    ocr_documents=ocr_documents,
                )
            )
            body = f"<pre>{html.escape(text)}</pre>"
        except BlobMissing:
            body = "<p class=warn>Không đọc được nội dung: blob đã mất trên đĩa.</p>"
        if entry.kind == "image":
            path = blobs.path(entry.sha256) if entry.sha256 else None
            thumb = _thumbnail(path) if path else None
            body += (
                f'<img alt="" src="data:image/jpeg;base64,{thumb}">'
                if thumb
                else "<p class=warn>Không mở được ảnh.</p>"
            )
    choices = "".join(
        f'<label><input type=radio name="{item_id}" value="{v}"> {v}</label> '
        for v in ("giu", "loai")
    )
    return (
        f'<section data-id="{item_id}" data-url="{url}" data-sha="{html.escape(row["sha256"])}">'
        f"<h2>{item_id} · vòng {row['round']} · {html.escape(row['host_group'])} · "
        f"{html.escape(row['kind'])}</h2>"
        f'<p><a href="{url}" target="_blank" rel="noopener">{url}</a></p>'
        f"{body}<p class=choice>{choices}</p></section>"
    )


_PAGE = """<!doctype html><html lang="vi"><head><meta charset="utf-8">
<title>Gán nhãn mẫu kho web</title><style>
body{{font:15px/1.5 system-ui,sans-serif;max-width:900px;margin:0 auto;padding:16px}}
section{{border:1px solid #ccc;border-radius:6px;padding:12px;margin:12px 0}}
section.done{{border-color:#2a7}} pre{{white-space:pre-wrap;background:#f6f6f6;padding:8px}}
img{{max-width:100%}} .warn{{color:#a40}} .choice label{{margin-right:16px;font-weight:600}}
header{{position:sticky;top:0;background:#fff;padding:8px 0;border-bottom:1px solid #ccc}}
</style></head><body><header><h1>Gán nhãn mẫu kho web</h1>
<p>Mỗi mục chọn <b>giu</b> (cần cho tư vấn tuyển sinh đại học chính quy) hoặc <b>loai</b>.
Lựa chọn được lưu tạm trong trình duyệt.</p>
<label>Người duyệt: <input id=reviewer></label> <span id=count></span>
<button id=export>Xuất labels.csv</button></header>
{items}
<script>
const HEADER = "{header}";
const KEY = "topic-labels-" + location.pathname;
const sections = [...document.querySelectorAll("section")];
let saved = {{}};
try {{ saved = JSON.parse(localStorage.getItem(KEY) || "{{}}"); }} catch (e) {{}}
const reviewer = document.getElementById("reviewer");
reviewer.value = saved.__reviewer || "";
function refresh() {{
  let done = 0;
  for (const s of sections) {{
    const v = saved[s.dataset.id];
    s.classList.toggle("done", !!v);
    if (v) {{ done++; s.querySelector(`input[value="${{v}}"]`).checked = true; }}
  }}
  document.getElementById("count").textContent = `${{done}} / ${{sections.length}} mục`;
}}
function store() {{ try {{ localStorage.setItem(KEY, JSON.stringify(saved)); }} catch (e) {{}} }}
document.addEventListener("change", (e) => {{
  if (e.target.type === "radio") {{ saved[e.target.name] = e.target.value; store(); refresh(); }}
}});
reviewer.addEventListener("input", () => {{ saved.__reviewer = reviewer.value; store(); }});
const q = (v) => '"' + String(v).replaceAll('"', '""') + '"';
document.getElementById("export").addEventListener("click", () => {{
  const at = new Date().toISOString();
  const lines = [HEADER];
  for (const s of sections) {{
    const v = saved[s.dataset.id];
    if (!v) continue;
    const d = s.dataset;
    lines.push([d.id, d.url, d.sha, v, reviewer.value, at].map(q).join(","));
  }}
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([lines.join("\\n") + "\\n"], {{type: "text/csv"}}));
  a.download = "labels.csv";
  a.click();
}});
refresh();
</script></body></html>
"""


def render_form(
    rows: list[dict],
    *,
    current,
    blobs: BlobStore,
    max_chars: int,
    ocr_documents: Path | None = None,
) -> str:
    items = "\n".join(
        _item_html(
            r,
            current.get(r["url"]),
            current=current,
            blobs=blobs,
            max_chars=max_chars,
            ocr_documents=ocr_documents,
        )
        for r in rows
    )
    return _PAGE.format(items=items, header=CSV_HEADER)


def make_sample(
    out_dir: Path,
    candidates: list[ManifestEntry],
    *,
    current: dict[str, ManifestEntry],
    blobs: BlobStore,
    cfg: TopicConfig,
    seed: int,
    top_up: int | None = None,
    ocr_documents: Path | None = None,
    out: Callable[[str], None] = print,
) -> int:
    """Vòng 1 bốc `cfg.sample_size` mục; `top_up` thêm một vòng từ nhóm tuyensinh và khoa.
    Mã thoát 0 xong, 2 khi vòng 1 đã chốt (không top-up) hoặc top-up mà chưa có vòng 1."""
    out_dir = Path(out_dir)
    previous = read_rounds(out_dir)
    if top_up is None and previous:
        out(f"Mẫu {out_dir} đã chốt; thêm mục: --top-up; mẫu mới: --seed khác.")
        return 2
    if top_up is not None and not previous:
        out("Chưa có vòng 1: chạy topic-sample không kèm --top-up trước.")
        return 2
    round_no = max((r["round"] for r in previous), default=0) + 1
    entries = draw_sample(
        candidates,
        groups=cfg.host_groups,
        n=cfg.sample_size if top_up is None else top_up,
        seed=seed if round_no == 1 else seed + round_no,
        exclude={r["url"] for r in previous},
        only_groups=None if top_up is None else TOP_UP_GROUPS,
    )
    rows = [
        {
            "item_id": f"S{len(previous) + i:03d}",
            "url": e.url,
            "sha256": e.sha256,
            "kind": e.kind,
            "host_group": host_group(e.host, cfg.host_groups),
            "round": round_no,
            "page_url": e.page_url,
        }
        for i, e in enumerate(entries, start=1)
    ]
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"round-{round_no}.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )
    (out_dir / "index.html").write_text(
        render_form(
            previous + rows,
            current=current,
            blobs=blobs,
            max_chars=cfg.max_chars,
            ocr_documents=ocr_documents,
        ),
        encoding="utf-8",
    )
    out(f"Vòng {round_no}: {len(rows)} mục → {out_dir / 'index.html'}")
    return 0
