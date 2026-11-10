"""Suy năm của trang/tài liệu web để giữ kho từ `min_year` trở đi (quyết định 13/10/2026,
spec nguồn web và trích dẫn §6.5).

Thứ tự tin cậy: ngày đăng của chính nó → ngày đăng của trang chứa nó (ảnh, file) → năm trong
tên URL hoặc tiêu đề của chính nó → của trang chứa nó. Không suy được thì trả None: mục đó được
giữ (trang giới thiệu, ngành đào tạo… thường không có ngày).
"""

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Literal
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


# --------------------------------------------- trang không có ngày đăng: đọc chữ (RUNBOOK 4.2)
#
# Chỉ tin năm đi kèm cụm chỉ thời điểm hiện hành. Năm đứng một mình trong chữ trang thường là nhiễu:
# menu lọt vào nội dung ("KIỂM ĐỊNH CTĐT NGÀNH LUẬT 2025"), chân trang, ngày của template, câu kể
# lịch sử ("Đến tháng 10 năm 2019").

_RANGE = r"(20\d\d)(?:\s*[-–]\s*(20\d\d))?"
_KHOA = r"kh(?:óa|oá)"
# "Từ năm học X", "áp dụng từ…", "có hiệu lực từ…": hiện hành TỪ năm đó trở đi.
_SINCE = re.compile(rf"\btừ\s+(?:năm học|năm|{_KHOA})\s*{_RANGE}", re.IGNORECASE)
# Hiện hành TẠI năm đó.
_POINT = (
    re.compile(rf"năm học\s*{_RANGE}", re.IGNORECASE),
    re.compile(r"năm tuyển sinh\s*(20\d\d)", re.IGNORECASE),
    re.compile(rf"áp dụng (?:cho|đối với)[^.\n]{{0,20}}?{_KHOA}\s*(20\d\d)", re.IGNORECASE),
    re.compile(
        r"(?:tuyển sinh|xét tuyển|trúng tuyển|điểm chuẩn|chỉ tiêu|học phí|đại học|THPT)"
        r"[^.\n\d]{0,40}?năm\s*(20\d\d)",
        re.IGNORECASE,
    ),
)
# Năm của văn bản được dẫn ("Quy chế … ban hành năm 2021") không phải năm hiện hành của trang.
_CITED = re.compile(
    r"ban hành|quyết định|thông tư|nghị định|công văn|căn cứ|số\s*\d", re.IGNORECASE
)
_CITE_WINDOW = 30


@dataclass(frozen=True)
class BodyDating:
    """`keep`: hiện hành từ `floor` trở đi, `year` là năm hiện hành. `remove`: chỉ hiện hành trước
    `floor`. `review`: không có dấu hiệu, hoặc chỉ biết "từ năm X" với X trước mốc (có thể vẫn hiệu
    lực): Kent duyệt, không tự giữ hay tự xoá. `evidence` là các cụm đã dùng để quyết."""

    decision: Literal["keep", "remove", "review"]
    year: int | None
    evidence: str


def _signal_year(match: re.Match, text: str, today: date) -> int | None:
    start = match.start(1)
    if _CITED.search(text[max(0, start - _CITE_WINDOW) : start]):
        return None
    years = [int(g) for g in match.groups() if g]
    year = max(years)
    return year if _plausible(year, today) else None


def date_from_body(text: str, *, floor: int, today: date) -> BodyDating:
    text = unicodedata.normalize("NFC", text or "")
    since: list[int] = []
    point: list[int] = []
    evidence: list[str] = []
    taken: list[tuple[int, int]] = []
    for pattern, bucket in [(_SINCE, since), *((p, point) for p in _POINT)]:
        for match in pattern.finditer(text):
            if any(match.start() < end and start < match.end() for start, end in taken):
                continue  # "năm học X" nằm trong "từ năm học X": đã tính là "từ"
            year = _signal_year(match, text, today)
            if year is None:
                continue
            taken.append(match.span())
            bucket.append(year)
            snippet = " ".join(match.group(0).split())
            if snippet not in evidence:
                evidence.append(snippet)
    found = " | ".join(evidence[:5])
    current = [y for y in since + point if y >= floor]
    if current:
        return BodyDating("keep", max(current), found)
    if point and not since:
        return BodyDating("remove", max(point), found)
    return BodyDating("review", None, found)
