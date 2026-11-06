"""Việc OCR của kho web: lập danh sách trang, gọi worker, kiểm tương đương, áp kết quả vào kho.

Worker chạy ở tiến trình riêng trong `environments/ocr`; module này chạy trong môi trường app.
`run` chỉ ghi checkpoint. Kho chỉ đổi ở `apply`, sau khi người vận hành xem `review`: file qua lọc
rời `quarantine/` vào kho, file bị lọc là danh sách người thì xoá cả bản gốc lẫn chữ đã OCR.
"""

import collections
import dataclasses
import fcntl
import hashlib
import json
import logging
import mimetypes
import shutil
import signal
import subprocess
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Literal

import pymupdf
import yaml

from qnuchat.ingest import pii
from qnuchat.ingest.blobs import BlobStore
from qnuchat.ingest.crawl_job import _crawl_lock
from qnuchat.ingest.extract import Extracted, extract_pdf
from qnuchat.ingest.manifest import Manifest, ManifestEntry
from qnuchat.ingest.ocr import worker
from qnuchat.ingest.ocr.text import group_rows, page_text

logger = logging.getLogger(__name__)

DPI = 300
GPU_BUSY_MIB = 500  # kwin_wayland luôn chiếm vài chục MiB nên không đòi GPU trống hẳn
PDF_MIME = "application/pdf"
# Ảnh trong sổ nhãn được OCR; `anh_nguoi` phải xoá, ảnh chưa có nhãn chưa được đưa vào kho.
OCR_LABELS = frozenset({"co_chu", "khong_nguoi"})
ENV_LOCK = Path("environments/ocr/uv.lock")
EXCLUDED_PAGES = Path("configs/ocr/excluded-pages.yaml")
WORKER_COMMAND = (
    "environments/ocr/.venv/bin/python",
    "-P",  # không đưa thư mục của worker.py vào sys.path: `text.py` ở đó không được che thư viện
    worker.__file__,
)

Outcome = Literal["text", "pii", "empty", "error", "missing"]


class OcrBusy(RuntimeError):
    """GPU đang bận, hoặc một lần chạy khác đang giữ khoá."""


@dataclass(frozen=True)
class Document:
    """Một file khác hash chờ OCR; `pages` là các trang cần OCR (ảnh chỉ có trang 1)."""

    sha256: str
    mime: str
    entries: tuple[ManifestEntry, ...]
    pages: tuple[int, ...]
    excluded: frozenset[int] = frozenset()  # không OCR, không vào kho, kể cả khi có lớp chữ

    @property
    def title(self) -> str:
        return self.entries[0].title or self.entries[0].url

    @property
    def is_pdf(self) -> bool:
        return self.mime == PDF_MIME


@dataclass(frozen=True)
class Plan:
    documents: tuple[Document, ...]
    waiting_label: tuple[ManifestEntry, ...]  # ảnh chưa được phép OCR, xem `OCR_LABELS`
    missing: tuple[str, ...] = ()  # sha256 còn trong manifest nhưng file đã mất khỏi quarantine/


@dataclass(frozen=True)
class Assembled:
    document: Document
    outcome: Outcome
    detail: str | None
    pages: tuple[dict, ...] = ()


def ocr_dir(data_dir: Path) -> Path:
    return data_dir / "ocr"


def pages_dir(data_dir: Path) -> Path:
    return ocr_dir(data_dir) / "pages"


def page_id(sha: str, page: int) -> str:
    return f"{sha}-p{page:04}"


def load_labels(path: Path) -> dict[str, str | None]:
    """Nhãn của từng ảnh; dòng sau đè dòng trước vì sửa nhãn là thêm dòng mới."""
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        rows = (json.loads(line) for line in fh if line.strip())
        return {row["sha256"]: row["label"] for row in rows}


def load_excluded(path: Path) -> dict[str, frozenset[int]]:
    """Trang loại khỏi kho theo sha256 của file: việc của từng nguồn, không nằm trong code."""
    if not path.exists():
        return {}
    rows = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {sha: frozenset(row["pages"]) for sha, row in rows.items()}


def build_plan(data_dir: Path, excluded_pages: Path = EXCLUDED_PAGES) -> Plan:
    manifest = Manifest(data_dir / "manifest.jsonl", repair=False)
    labels = load_labels(data_dir / "people.jsonl")
    excluded = load_excluded(excluded_pages)
    grouped: dict[str, list[ManifestEntry]] = collections.defaultdict(list)
    for entry in manifest.current().values():
        if entry.text_status == "needs_ocr" and entry.sha256:
            grouped[entry.sha256].append(entry)

    documents: list[Document] = []
    waiting: list[ManifestEntry] = []
    missing: list[str] = []
    for sha, entries in grouped.items():
        mime = entries[0].mime or ""
        source = data_dir / "quarantine" / sha
        if not source.exists():
            missing.append(sha)
            continue
        if mime == PDF_MIME:
            dropped = excluded.get(sha, frozenset())
            scanned = extract_pdf(source.read_bytes()).scanned_pages
            pages = tuple(page for page in scanned if page not in dropped)
        elif labels.get(sha) in OCR_LABELS:
            pages = (1,)
        else:
            waiting.extend(entries)
            continue
        documents.append(Document(sha, mime, tuple(entries), pages, excluded.get(sha, frozenset())))
    return Plan(tuple(documents), tuple(waiting), tuple(missing))


def render_page(pdf: Path, page: int) -> bytes:
    """Trang PDF → PNG. `get_pixmap` đã theo /Rotate nên ảnh ra theo hướng hiển thị."""
    with pymupdf.open(pdf) as doc:
        return doc[page - 1].get_pixmap(dpi=DPI).tobytes("png")


def _write_image(directory: Path, name: str, data: bytes) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(data)
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest()}


def prepare_items(documents: tuple[Document, ...], data_dir: Path, image_dir: Path) -> list[dict]:
    """Ảnh đầu vào của worker. File trong `quarantine/` không có đuôi mà paddlex cần đuôi để đọc,
    nên ảnh gốc được chép nguyên byte sang tên có đuôi."""
    items: list[dict] = []
    for doc in documents:
        source = data_dir / "quarantine" / doc.sha256
        for page in doc.pages:
            iid = page_id(doc.sha256, page)
            if doc.is_pdf:
                image = _write_image(image_dir, f"{iid}.png", render_page(source, page))
            else:
                suffix = mimetypes.guess_extension(doc.mime) or ""
                image = _write_image(image_dir, f"{iid}{suffix}", source.read_bytes())
            items.append({"id": iid, **image})
    return items


def gpu_used_mib() -> int:
    r = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return sum(int(row) for row in r.stdout.split())


@contextmanager
def ocr_lock(directory: Path) -> Iterator[None]:
    """Mỗi lúc một lần chạy dùng GPU; flock tự nhả khi tiến trình chết nên không kẹt."""
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "ocr.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise OcrBusy("đang có một lần OCR khác chạy") from exc
        yield


def run_worker(
    items: list[dict],
    out: Path,
    *,
    retry_errors: bool = False,
    command: tuple[str, ...] = WORKER_COMMAND,
    on_event: Callable[[dict], None] = lambda event: None,
) -> int:
    """Gọi worker, trả mã thoát. SIGTERM/SIGINT/SIGHUP được chuyển cho worker để nó làm xong ảnh
    đang dở rồi tự thoát; tiến trình này đứng chờ thay vì chết trước con."""
    out.mkdir(parents=True, exist_ok=True)
    job = out.parent / f"{out.name}.job.json"
    worker.atomic_write_json(job, items)
    argv = [*command, "--job", str(job), "--out", str(out)]
    if retry_errors:
        argv.append("--retry-errors")
    tail: collections.deque[str] = collections.deque(maxlen=20)
    proc = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    def forward(signum, frame) -> None:
        proc.send_signal(signal.SIGTERM)

    stops = (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)
    previous = {sig: signal.signal(sig, forward) for sig in stops}
    try:
        for line in proc.stdout:
            if line.startswith(worker.PREFIX):
                on_event(json.loads(line[len(worker.PREFIX) :]))
            else:
                tail.append(line.rstrip())
        code = proc.wait()
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    if code not in (worker.EXIT_OK, worker.EXIT_STOPPED):
        logger.error("ocr_worker_exit code=%s tail=%s", code, "\n".join(tail))
    return code


def run_ocr(
    data_dir: Path,
    *,
    retry_errors: bool = False,
    command: tuple[str, ...] = WORKER_COMMAND,
    on_event: Callable[[dict], None] = lambda event: None,
    on_plan: Callable[[Plan, int], None] = lambda plan, total: None,
) -> int:
    root = ocr_dir(data_dir)
    with ocr_lock(root):
        plan = build_plan(data_dir)
        images = root / "images"
        items = prepare_items(plan.documents, data_dir, images)
        on_plan(plan, len(items))
        code = run_worker(
            items,
            pages_dir(data_dir),
            retry_errors=retry_errors,
            command=command,
            on_event=on_event,
        )
        if code == worker.EXIT_OK:
            shutil.rmtree(images, ignore_errors=True)  # dựng lại được từ PDF, không cần giữ
        return code


def assemble(document: Document, data_dir: Path, *, today: date) -> Assembled:
    """Ghép chữ của cả file rồi lọc danh sách người. Trang có lớp chữ giữ lớp chữ; thiếu trang hay
    trang lỗi thì không kết luận gì về file, kể cả khi các trang còn lại trông sạch."""
    records: dict[int, dict] = {}
    for page in document.pages:
        rec = worker.read_output(pages_dir(data_dir) / f"{page_id(document.sha256, page)}.json")
        if rec is None:
            return Assembled(document, "missing", f"chưa OCR trang {page}")
        if "error" in rec:
            return Assembled(document, "error", f"trang {page}: {rec['error']['kind']}")
        records[page] = rec

    if document.is_pdf:
        layer = extract_pdf((data_dir / "quarantine" / document.sha256).read_bytes())
        layer_pages, tables = list(layer.pages or []), list(layer.tables)
    else:
        layer_pages, tables = [""], []

    pages: list[dict] = []
    for number, text in enumerate(layer_pages, start=1):
        if number in document.excluded:
            continue
        rec = records.get(number)
        if rec is None:
            pages.append({"page": number, "source": "text_layer", "text": text})
            continue
        rows = group_rows(rec["lines"])
        tables.append(rows)
        pages.append(
            {
                "page": number,
                "source": "ocr",
                "text": page_text(rows),
                "rotation": rec["rotation"],
                "image_sha256": rec["image_sha256"],
                "config": rec["config"],
                "env_sha256": rec["env_sha256"],
            }
        )

    texts = [p["text"] for p in pages]
    text = "\n\n".join(t for t in texts if t)
    reason = pii.detect(
        Extracted(text=text, pages=texts, tables=tables, scanned_pages=[]), today=today
    )
    if reason:
        return Assembled(document, "pii", reason)
    if not text.strip():
        return Assembled(document, "empty", "OCR không đọc được chữ")
    return Assembled(document, "text", None, tuple(pages))


def review(
    data_dir: Path, *, today: date, excluded_pages: Path = EXCLUDED_PAGES
) -> tuple[Plan, list[Assembled]]:
    plan = build_plan(data_dir, excluded_pages)
    return plan, [assemble(doc, data_dir, today=today) for doc in plan.documents]


def _keep(result: Assembled, data_dir: Path, manifest: Manifest, now: datetime) -> None:
    doc = result.document
    documents = ocr_dir(data_dir) / "documents"
    documents.mkdir(parents=True, exist_ok=True)
    worker.atomic_write_json(
        documents / f"{doc.sha256}.json",
        {
            "source_sha256": doc.sha256,
            "mime": doc.mime,
            "title": doc.title,
            "urls": [entry.url for entry in doc.entries],
            "pages": result.pages,
        },
    )
    source = data_dir / "quarantine" / doc.sha256
    tier = "A" if any(entry.tier == "A" for entry in doc.entries) else "B"
    BlobStore(data_dir).put(source.read_bytes(), tier=tier)
    for entry in doc.entries:
        manifest.append(
            dataclasses.replace(
                entry,
                text_status="text",
                reason="ocr",
                retrieved_at=now.isoformat(timespec="seconds"),
                crawl_run="ocr",
            )
        )
    source.unlink()
    for page in doc.excluded:  # chữ đã OCR trước khi trang bị loại
        (pages_dir(data_dir) / f"{page_id(doc.sha256, page)}.json").unlink(missing_ok=True)


def _withdraw(result: Assembled, data_dir: Path, manifest: Manifest, now: datetime) -> None:
    doc = result.document
    for entry in doc.entries:
        manifest.append(
            dataclasses.replace(
                entry,
                sha256=None,
                mime=None,
                bytes=None,
                text_status="skipped_pii",
                reason=f"ocr:{result.detail}",
                retrieved_at=now.isoformat(timespec="seconds"),
                crawl_run="ocr",
            )
        )
    BlobStore(data_dir).delete(doc.sha256)
    for path in pages_dir(data_dir).glob(f"{doc.sha256}-p*.json"):
        path.unlink()


def apply_results(
    data_dir: Path, *, today: date, now: datetime, excluded_pages: Path = EXCLUDED_PAGES
) -> collections.Counter:
    """Áp kết quả `review` vào kho. Giữ `crawl.lock` vì manifest chỉ có một người ghi; file lỗi,
    thiếu trang hay không có chữ ở lại `quarantine/`."""
    counts: collections.Counter = collections.Counter()
    with _crawl_lock(data_dir) as held:
        if not held:
            raise OcrBusy("kho đang được quét hoặc prune")
        _, results = review(data_dir, today=today, excluded_pages=excluded_pages)
        manifest = Manifest(data_dir / "manifest.jsonl")
        for result in results:
            counts[result.outcome] += 1
            if result.outcome == "text":
                _keep(result, data_dir, manifest, now)
            elif result.outcome == "pii":
                _withdraw(result, data_dir, manifest, now)
    return counts


def remove_files(data_dir: Path, shas: list[str], *, now: datetime) -> int:
    """Xoá hẳn file khỏi kho theo sha256: bản gốc, chữ OCR, và ghi `operator_removed` để lần quét
    sau không tải lại. Trả về số URL đã rút."""
    removed = 0
    with _crawl_lock(data_dir) as held:
        if not held:
            raise OcrBusy("kho đang được quét hoặc prune")
        manifest = Manifest(data_dir / "manifest.jsonl")
        wanted = set(shas)
        for entry in list(manifest.current().values()):
            if entry.sha256 not in wanted:
                continue
            manifest.append(
                dataclasses.replace(
                    entry,
                    sha256=None,
                    mime=None,
                    bytes=None,
                    text_status="failed",
                    reason="operator_removed",
                    retrieved_at=now.isoformat(timespec="seconds"),
                    crawl_run="ocr",
                )
            )
            removed += 1
        blobs = BlobStore(data_dir)
        for sha in wanted:
            blobs.delete(sha)
            for path in pages_dir(data_dir).glob(f"{sha}-p*.json"):
                path.unlink()
    return removed


def fingerprint(root: Path = Path(".")) -> dict[str, str]:
    """Thứ quyết định output: `verify` đạt chỉ có giá trị khi hai file này không đổi."""
    return {
        "worker_sha256": worker.sha256_file(Path(worker.__file__)),
        "env_lock_sha256": worker.sha256_file(root / ENV_LOCK),
    }


def is_verified(gate: Path, root: Path = Path(".")) -> bool:
    return worker.read_output(gate) == fingerprint(root)


@dataclass(frozen=True)
class Verification:
    compared: int
    identical: int
    differences: tuple[str, ...]
    render_mismatches: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return self.compared > 0 and self.compared == self.identical


def expected_pages(corpus: Path, limit: int | None = None) -> list[dict]:
    """Trang chuẩn trong `data/ocr-data/corpus.json`; bản ghi không thuộc `cur_rotgate` bị bỏ."""
    records = json.loads(corpus.read_text(encoding="utf-8"))
    chosen = [r for r in records if r["engine"] == worker.CONFIG]
    return chosen[:limit]


def _source_file(record: dict, data_root: Path) -> Path:
    for path in data_root.rglob(record["source_document"]):
        if worker.sha256_file(path) == record["source_document_sha256"]:
            return path
    raise FileNotFoundError(f"không tìm thấy {record['source_document']} trong {data_root}")


def verify_items(records: list[dict], data_root: Path, image_dir: Path) -> list[dict]:
    items: list[dict] = []
    for record in records:
        source = _source_file(record, data_root)
        iid = record["record_id"]
        if source.suffix.lower() == ".pdf":
            data = render_page(source, int(record["page"]))
            items.append({"id": iid, **_write_image(image_dir, f"{iid}.png", data)})
        else:
            image = _write_image(image_dir, f"{iid}{source.suffix}", source.read_bytes())
            items.append({"id": iid, **image})
    return items


def compare_outputs(records: list[dict], out: Path) -> Verification:
    identical = 0
    differences: list[str] = []
    render: list[str] = []
    for record in records:
        want = record["result"]
        name = f"{record['source_document']} trang {record['page']}"
        got = worker.read_output(out / f"{record['record_id']}.json")
        if got is None or "error" in got:
            differences.append(f"{name}: không có output")
        elif got["image_sha256"] != want["image_sha256"]:
            render.append(name)  # ảnh đầu vào đã khác thì so chữ không còn ý nghĩa
        elif got["rotation"] != want.get("rotation") or got["lines"] != want["lines"]:
            same = sum(a == b for a, b in zip(got["lines"], want["lines"], strict=False))
            differences.append(
                f"{name}: xoay {got['rotation']}/{want.get('rotation')}, "
                f"{same}/{len(want['lines'])} dòng giống, ra {len(got['lines'])} dòng"
            )
        else:
            identical += 1
    return Verification(len(records), identical, tuple(differences), tuple(render))


def run_verify(
    corpus: Path,
    data_root: Path,
    out_root: Path,
    *,
    limit: int | None = None,
    command: tuple[str, ...] = WORKER_COMMAND,
    on_event: Callable[[dict], None] = lambda event: None,
    on_plan: Callable[[int], None] = lambda total: None,
) -> tuple[int, Verification | None]:
    """Chạy lại các trang chuẩn. Chỉ lần kiểm đủ mọi trang mới được ghi `passed.json`."""
    with ocr_lock(out_root):
        records = expected_pages(corpus, limit)
        images = out_root / "images"
        items = verify_items(records, data_root, images)
        on_plan(len(items))
        out = out_root / "pages"
        shutil.rmtree(out, ignore_errors=True)  # kiểm phải OCR lại thật, không đọc checkpoint cũ
        code = run_worker(items, out, command=command, on_event=on_event)
        if code != worker.EXIT_OK:
            return code, None
        shutil.rmtree(images, ignore_errors=True)
        result = compare_outputs(records, out)
        if limit is None:
            gate = out_root / "passed.json"
            gate.unlink(missing_ok=True)
            if result.passed:
                worker.atomic_write_json(gate, fingerprint())
        return code, result
