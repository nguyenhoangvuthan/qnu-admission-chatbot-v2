"""Suy năm của trang/tài liệu web để giữ kho từ `min_year` trở đi (quyết định 13/10/2026,
spec nguồn web và trích dẫn §6.5).

Thứ tự tin cậy: ngày đăng của chính nó → ngày đăng của trang chứa nó (ảnh, file) → năm trong
tên URL hoặc tiêu đề của chính nó → của trang chứa nó. Không suy được thì trả None: mục đó được
giữ (trang giới thiệu, ngành đào tạo… thường không có ngày).
"""

import re
from datetime import date
from urllib.parse import unquote, urlsplit

MIN_PLAUSIBLE_YEAR = 2000
_YEAR = re.compile(r"(?<!\d)(20\d\d)(?!\d)")
_EXTENSION = re.compile(r"\.[A-Za-z0-9]{1,5}$")
# Đuôi "-YYYY" của một tên URL chỉ là năm khi có ngữ cảnh: CMS của trường gắn ID số vào cuối
# tên (`co-cau-to-chuc-1117`, `…-dkxt-5907`), ID trong khoảng 2000–2029 trông như năm.
_YEAR_CONTEXT_BEFORE = re.compile(r"(?:nam|năm|20\d\d)[-_ ]$", re.IGNORECASE)


def _plausible(year: int, today: date) -> bool:
    return MIN_PLAUSIBLE_YEAR <= year <= today.year + 1


def year_from_text(text: str | None, *, today: date) -> int | None:
    """Năm lớn nhất trong một đoạn chữ (tiêu đề): "năm học 2019-2020" → 2020."""
    if not text:
        return None
    years = [int(y) for y in _YEAR.findall(text) if _plausible(int(y), today)]
    return max(years, default=None)


def year_from_url(url: str, *, title: str | None = None, today: date) -> int | None:
    """Năm trong đoạn cuối của đường dẫn. Đoạn cha (chuyên mục) không xét: số ở đó hay là ID."""
    segment = unquote(urlsplit(url).path).rstrip("/").rsplit("/", 1)[-1]
    stem = _EXTENSION.sub("", segment)
    title_years = set(_YEAR.findall(title or ""))
    found: list[int] = []
    for match in _YEAR.finditer(stem):
        year = int(match.group(1))
        if not _plausible(year, today):
            continue
        if match.end() == len(stem):
            before = stem[: match.start()]
            if not (_YEAR_CONTEXT_BEFORE.search(before) or match.group(1) in title_years):
                continue
        found.append(year)
    return max(found, default=None)


def _name_year(url: str | None, title: str | None, today: date) -> int | None:
    if url is None:
        return None
    years = [
        y
        for y in (year_from_url(url, title=title, today=today), year_from_text(title, today=today))
        if y
    ]
    return max(years, default=None)


def infer_year(
    *,
    url: str,
    title: str | None,
    published: date | None,
    today: date,
    parent_published: date | None = None,
    parent_url: str | None = None,
    parent_title: str | None = None,
) -> int | None:
    for day in (published, parent_published):
        if day is not None and _plausible(day.year, today):
            return day.year
    return _name_year(url, title, today) or _name_year(parent_url, parent_title, today)


def is_before(year: int | None, floor: int | None) -> bool:
    """Chỉ loại khi biết chắc năm và có đặt mốc."""
    return year is not None and floor is not None and year < floor
