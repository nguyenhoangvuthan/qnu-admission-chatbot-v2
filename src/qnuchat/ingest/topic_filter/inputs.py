"""Chọn mục của kho web cần lọc chủ đề và dựng đầu vào (spec knowledge base §5.2, §5.3).

Đầu vào là metadata cộng 1.500 ký tự đầu của chữ trích. Spec lọc trước, OCR sau; kho v2 đã OCR
trước nên file và ảnh có chữ OCR dùng luôn chữ đó, như đầu vào lần 2 của §5.2.
"""

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

from qnuchat.ingest.blobs import BlobStore
from qnuchat.ingest.config import CrawlConfig
from qnuchat.ingest.extract import ExtractError, extract, extract_html, sniff
from qnuchat.ingest.html_page import parse_page
from qnuchat.ingest.manifest import ManifestEntry
from qnuchat.ingest.state import CheckState
from qnuchat.ingest.urls import canonicalize

_KIND_ORDER = {"page": 0, "file": 1, "image": 2}


class BlobMissing(Exception):
    """Blob của mục không còn trên đĩa (đã xoá, chưa `restore`): không dựng được đầu vào."""


@dataclass(frozen=True)
class TopicInput:
    url: str
    sha256: str
    kind: str
    host: str
    title: str | None
    file_name: str | None
    page_url: str | None
    page_title: str | None
    link_text: str | None
    text: str | None


def seed_urls(cfg: CrawlConfig) -> set[str]:
    canonical = (canonicalize(u, aliases=cfg.host_aliases) for u in cfg.seeds)
    return {u for u in canonical if u}


def exempt(entry: ManifestEntry, *, seeds: set[str], state: CheckState) -> bool:
    """Tầng A, hạt giống, trang hub và favicon không qua bộ lọc, luôn giữ (§5.3 bước 1)."""
    return (
        entry.kind == "favicon"
        or entry.tier == "A"
        or entry.url in seeds
        or state.is_hub(entry.url)
    )


def candidates(
    current: dict[str, ManifestEntry], *, seeds: set[str], state: CheckState
) -> list[ManifestEntry]:
    """Trang trước (để ảnh biết trang chứa đã bị loại chưa), rồi file, rồi ảnh; theo URL."""
    chosen: Iterable[ManifestEntry] = (
        e for e in current.values() if not exempt(e, seeds=seeds, state=state)
    )
    return sorted(chosen, key=lambda e: (_KIND_ORDER.get(e.kind, 3), e.url))


def _file_name(url: str) -> str | None:
    name = PurePosixPath(urlsplit(url).path).name
    return unquote(name) or None


def _ocr_text(documents: Path | None, sha256: str) -> str | None:
    path = documents / f"{sha256}.json" if documents else None
    if path is None or not path.exists():
        return None
    pages = json.loads(path.read_text(encoding="utf-8"))["pages"]
    return "\n\n".join(p["text"] for p in pages if p["text"]) or None


def build_input(
    entry: ManifestEntry,
    *,
    current: dict[str, ManifestEntry],
    blobs: BlobStore,
    max_chars: int,
    ocr_documents: Path | None = None,
) -> TopicInput:
    path = blobs.path(entry.sha256) if entry.sha256 else None
    if path is None:
        raise BlobMissing(entry.url)
    if entry.kind == "page":
        page = parse_page(path.read_bytes(), entry.url)
        return TopicInput(
            url=entry.url,
            sha256=entry.sha256,
            kind=entry.kind,
            host=entry.host,
            title=entry.title,
            file_name=None,
            page_url=None,
            page_title=None,
            link_text=None,
            text=extract_html(page.main_html).text[:max_chars],
        )
    text = _ocr_text(ocr_documents, entry.sha256)
    if text:
        text = text[:max_chars]
    elif entry.kind == "file" and entry.text_status == "text":
        data = path.read_bytes()
        try:
            text = extract(sniff(data), data).text[:max_chars] or None
        except ExtractError:
            text = None  # file không đọc được thì lọc theo metadata như file chưa có chữ
    parent = current.get(entry.page_url) if entry.page_url else None
    return TopicInput(
        url=entry.url,
        sha256=entry.sha256,
        kind=entry.kind,
        host=entry.host,
        title=None,
        file_name=_file_name(entry.url),
        page_url=entry.page_url,
        page_title=parent.title if parent else None,
        # Với file/ảnh, manifest ghi chữ của đường link vào `title` (crawler §6.2).
        link_text=entry.title,
        text=text,
    )
