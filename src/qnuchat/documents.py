"""Kiểu tài liệu dùng chung giữa ingest và core. Module này không import phần nào của qnuchat."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Page:
    page: int
    text: str


@dataclass(frozen=True)
class Passage:
    """Một đoạn tài liệu đã chia. `chunk_id` duy nhất trong toàn kho, kể cả khi nhiều nguồn."""

    chunk_id: str
    source_id: str
    page: int
    text: str
    source_year: int | None = None
