"""Manifest chỉ-thêm `data/web/manifest.jsonl` (spec §6.3). Mỗi dòng một tài nguyên ở một phiên bản;
không bao giờ sửa dòng cũ."""

import dataclasses
import json
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

TEXT_STATUSES = ("text", "needs_ocr", "ocr_done", "failed", "skipped_pii", "auth_required")
KINDS = ("page", "file", "image", "favicon")
_REMOVES = frozenset({"skipped_pii", "auth_required"})
# `failed` với lý do này rút tài liệu khỏi kho; lỗi vĩnh viễn khác giữ phiên bản dùng được trước đó.
# `out_of_range`: trước `min_year`; `out_of_scope`: nay nằm ngoài phạm vi cấu hình (spec §6.5);
# `off_topic`: bộ lọc chủ đề đã đo đạt gán `loai` (spec knowledge base §5.3);
# `people_photo`: ảnh chờ OCR mà model nhận là ảnh chụp người, không mang chữ thông tin.
_REMOVING_REASONS = frozenset(
    {"gone", "robots_disallowed", "out_of_range", "out_of_scope", "off_topic", "people_photo"}
)


@dataclass(frozen=True)
class ManifestEntry:
    url: str
    source_id: str
    page_url: str | None
    kind: str
    title: str | None
    published: str | None
    retrieved_at: str
    sha256: str | None
    mime: str | None
    bytes: int | None
    host: str
    tier: str
    text_status: str
    reason: str | None
    crawl_run: str
    config_hash: str
    sources_yaml_ref: str | None

    @property
    def usable(self) -> bool:
        return bool(self.sha256) and self.text_status not in (
            "failed",
            "skipped_pii",
            "auth_required",
        )


class Manifest:
    """`repair=True` cắt dòng ghi dở ở cuối file (tiến trình chết giữa lúc ghi) trước khi đọc.
    Chỉ tiến trình giữ `crawl.lock` (người ghi duy nhất) được mở với `repair=True`; người chỉ
    đọc (lệnh `status`…) mở với `repair=False`: dòng dở chỉ bị bỏ qua khi đọc, file giữ nguyên,
    vì dòng đó có thể đang được người ghi viết dở."""

    def __init__(self, path: Path, *, repair: bool = True):
        self._path = Path(path)
        self._repair = repair
        self._lock = threading.Lock()
        self._entries: list[ManifestEntry] = []
        self._latest: dict[str, ManifestEntry] = {}
        if self._path.exists():
            self._load()

    def _load(self) -> None:
        data = self._path.read_bytes()
        if data and not data.endswith(b"\n"):
            cut = data.rfind(b"\n") + 1
            if self._repair:
                logger.warning(
                    "manifest_truncated_line_dropped %s bytes=%d", self._path, len(data) - cut
                )
                with self._path.open("r+b") as fh:
                    fh.truncate(cut)
            data = data[:cut]
        # Chỉ tách theo b"\n": str.splitlines() còn tách cả U+2028, U+2029, U+0085 trong tiêu đề.
        for number, raw in enumerate(data.split(b"\n"), start=1):
            line = raw.decode("utf-8")
            if not line.strip():
                continue
            try:
                entry = ManifestEntry(**json.loads(line))
            except (json.JSONDecodeError, TypeError) as exc:
                raise ValueError(f"{self._path} dòng {number} hỏng: {exc}") from exc
            self._remember(entry)

    def _remember(self, entry: ManifestEntry) -> None:
        self._entries.append(entry)
        self._latest[entry.url] = entry

    def append(self, entry: ManifestEntry) -> None:
        if not self._repair:
            raise RuntimeError("Manifest mở chỉ đọc (repair=False): không ghi được")
        line = json.dumps(dataclasses.asdict(entry), ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            self._remember(entry)

    def entries(self) -> list[ManifestEntry]:
        return list(self._entries)

    def latest(self, url: str) -> ManifestEntry | None:
        return self._latest.get(url)

    def current(self) -> dict[str, ManifestEntry]:
        """Phiên bản hiện hành của từng URL. `skipped_pii`, `auth_required`, `failed`/`gone`
        và `failed`/`robots_disallowed` rút tài liệu khỏi kho; lỗi vĩnh viễn khác (too_large…)
        giữ phiên bản dùng được trước đó."""
        current: dict[str, ManifestEntry] = {}
        for entry in self._entries:
            if entry.usable:
                current[entry.url] = entry
            elif entry.text_status in _REMOVES or entry.reason in _REMOVING_REASONS:
                current.pop(entry.url, None)
        return current

    def favicon(self, host: str) -> ManifestEntry | None:
        found = None
        for entry in self._entries:
            if entry.kind == "favicon" and entry.host == host and entry.usable:
                found = entry
        return found


def load_sources_index(path: Path) -> dict[str, str]:
    """sha256 → đường dẫn trong data/sources.yaml: file quét trùng file bàn giao
    thì trỏ về sổ tay."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return {s["sha256"]: s["file"] for s in raw.get("sources", []) if s.get("sha256")}
