"""Đọc lớp chữ của PDF. Trang cần loại là cấu hình của từng nguồn, không nằm trong code."""

from pathlib import Path

import pymupdf

from qnuchat.documents import Page


def load_pdf_pages(path: str | Path, exclude: frozenset[int] = frozenset()) -> list[Page]:
    with pymupdf.open(path) as doc:
        return [
            Page(page=index, text=page.get_text())
            for index, page in enumerate(doc, start=1)
            if index not in exclude
        ]
