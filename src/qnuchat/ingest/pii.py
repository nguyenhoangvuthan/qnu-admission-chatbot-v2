"""Phát hiện danh sách người để bỏ hẳn khỏi kho (spec W3, §7.3).

Ba luật: tiêu đề (trước khi tải), tiêu đề cột của bảng (≥ 2 khái niệm về người, hoặc chỉ cột
họ tên nhưng ≥ 3 dòng dữ liệu có họ tên; tìm trong 10 dòng đầu vì file XLSX thường có vài dòng
tên trường/tên danh sách ở trên), và ≥ 5 dòng
liên tiếp có họ tên kèm ngày sinh hoặc mã số — xét cả dòng text lẫn dòng bảng (ô nối bằng
" | "). Không chặn theo chữ "danh sách" trong nội dung: "danh sách ngành" vẫn qua.
"""

import re
import unicodedata
from collections.abc import Sequence
from datetime import date

from qnuchat.ingest.extract import Extracted

MIN_PEOPLE_ROWS = 5
HEADER_SCAN_ROWS = 10
MIN_NAME_ONLY_ROWS = 3
_CONCEPTS: dict[str, tuple[str, ...]] = {
    "ho_ten": ("họ và tên", "họ tên"),
    "ngay_sinh": ("ngày sinh", "ngày tháng năm sinh"),
    "ma_sv": ("mssv", "mã sinh viên", "mã số sinh viên", "mã sv"),
    "sbd": ("số báo danh", "sbd"),
    "cccd": ("cccd", "cmnd", "căn cước"),
    "sdt": ("số điện thoại", "sđt"),
    "lop": ("lớp",),
}
_DOB = re.compile(r"(?<!\d)(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})(?!\d)")
_ID = re.compile(r"(?<!\d)(\d{8,12})(?!\d)")
_SPLIT = re.compile(r"[\s|,;]+")


def _norm(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).lower().split())


def title_skip(title: str, patterns: Sequence[str]) -> str | None:
    normalized = _norm(title)
    for pattern in patterns:
        if re.search(pattern, normalized, re.IGNORECASE):
            return f"title:{pattern}"
    return None


def header_concepts(row: Sequence[str]) -> set[str]:
    found: set[str] = set()
    for cell in row:
        value = _norm(str(cell))
        for concept, prefixes in _CONCEPTS.items():
            if any(value == p or value.startswith(p + " ") for p in prefixes):
                found.add(concept)
    return found


# Từ mở đầu tên tổ chức / ngành học: cụm tên bắt đầu bằng từ này (Khoa Công Nghệ Thông Tin,
# Ngành Kỹ Thuật…) không phải họ tên người nên không tính vào luật dòng.
_ORG_WORDS = frozenset(
    {"ngành", "khoa", "phòng", "trung", "viện", "trường", "công", "sư", "kỹ", "kinh", "quản"}
    | {"giáo", "ngôn", "toán", "vật", "hóa", "sinh", "lịch", "địa", "tâm", "luật"}
    | {"dược", "tổ", "ban", "hội"}
)
# "Đoàn", "Văn", "Y" là họ người Việt / Ê-đê nên chỉ miễn khi hai từ đầu của cụm tạo thành
# tên tổ chức hay ngành quen thuộc.
_ORG_PAIRS = frozenset({("văn", "học"), ("văn", "hóa"), ("y", "khoa"), ("y", "dược"), ("y", "học")})


# "Đoàn Thanh Hải" là người; chỉ "Đoàn Thanh niên" (từ thứ ba là "niên") mới là tổ chức.
_YOUTH_UNION = ("đoàn", "thanh", "niên")


def _name_token(token: str) -> bool:
    token = token.strip(".()\\")
    return token.isalpha() and (token.istitle() or (token.isupper() and len(token) > 1))


def _has_name(line: str) -> bool:
    # Mỗi ô (ngăn bởi "|") xét riêng: cụm tổ chức ở ô này không che họ tên ở ô khác.
    return any(_cell_has_name(cell) for cell in line.split("|"))


def _cell_has_name(cell: str) -> bool:
    run = 0
    org = False
    first = ""
    tokens = _SPLIT.split(cell)
    for index, token in enumerate(tokens):
        if _name_token(token):
            word = token.strip(".()\\").casefold()
            if run == 0:
                first = word
                org = word in _ORG_WORDS
            elif run == 1 and (first, word) in _ORG_PAIRS:
                org = True
            elif run == 1 and (first, word) == _YOUTH_UNION[:2]:
                third = tokens[index + 1] if index + 1 < len(tokens) else ""
                org = third.strip(".()\\").casefold() == _YOUTH_UNION[2]
            run += 1
            if run >= 2 and not org:
                return True
        else:
            run = 0
    return False


def _is_personal_digits(digits: str) -> bool:
    # CCCD: đúng 12 số, bắt đầu bằng 0. Mã sinh viên / số báo danh: 8–10 số, không bắt đầu
    # bằng 0 và không tận cùng "000" (số tiền học phí). Số điện thoại (bắt đầu 0, 10–11 số)
    # và các dãy số khác không tính.
    if len(digits) == 12 and digits.startswith("0"):
        return True
    return 8 <= len(digits) <= 10 and not digits.startswith("0") and not digits.endswith("000")


def _has_personal_number(line: str, today: date) -> bool:
    for match in _DOB.finditer(line):
        day, month, year = (int(g) for g in match.groups())
        if 1 <= day <= 31 and 1 <= month <= 12 and 1940 <= year <= today.year - 14:
            return True
    return any(_is_personal_digits(m.group(1)) for m in _ID.finditer(line))


def _people_rows(lines: Sequence[str], today: date) -> bool:
    run = 0
    for line in lines:
        line = unicodedata.normalize("NFC", line)
        if _has_name(line) and _has_personal_number(line, today):
            run += 1
            if run >= MIN_PEOPLE_ROWS:
                return True
        else:
            run = 0
    return False


def _name_column_rows(table: Sequence[Sequence[str]], start: int, column: int) -> int:
    """Số dòng dữ liệu sau dòng tiêu đề `start` mà ô ở cột `column` có dạng họ tên."""
    return sum(
        1
        for row in table[start + 1 :]
        if column < len(row) and _cell_has_name(unicodedata.normalize("NFC", str(row[column])))
    )


def _name_only_header(table: Sequence[Sequence[str]]) -> bool:
    """Tiêu đề chỉ có cột họ tên (vd "STT | Họ và tên | Điểm") mà ≥ 3 dòng dữ liệu có họ tên."""
    for start, row in enumerate(table[:HEADER_SCAN_ROWS]):
        for column, cell in enumerate(row):
            if header_concepts([cell]) == {"ho_ten"} and (
                _name_column_rows(table, start, column) >= MIN_NAME_ONLY_ROWS
            ):
                return True
    return False


def detect(extracted: Extracted, *, today: date) -> str | None:
    for table in extracted.tables:
        for row in table[:HEADER_SCAN_ROWS]:
            concepts = header_concepts(row)
            if len(concepts) >= 2:
                return "header:" + "+".join(sorted(concepts))
    if any(_name_only_header(table) for table in extracted.tables):
        return "header:ho_ten"
    if _people_rows(extracted.text.splitlines(), today):
        return "rows"
    for table in extracted.tables:
        if _people_rows([" | ".join(str(c) for c in row) for row in table], today):
            return "rows"
    return None
