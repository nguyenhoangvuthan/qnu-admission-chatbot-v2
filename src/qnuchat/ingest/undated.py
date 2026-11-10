"""Trang chưa suy được năm từ ngày đăng, URL hay tiêu đề: xét bằng chữ trong trang.

RUNBOOK 4.2.

Danh sách gồm cả trang được `prune` miễn (hạt giống, tầng A, hub): mục 4.3 chọn trang cho
snapshot đề án từ đây, kể cả các trang ngành của tuyensinh.
"""

import csv
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
