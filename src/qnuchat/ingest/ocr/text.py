"""Dòng OCR → chữ của trang: gom theo hàng nhìn thấy và sửa mã tổ hợp môn."""

import re

_COMBO_RE = re.compile(r"\b([A-DHKMNRSTVXa-dhkmnrstvx])([0-9Oo]{2})\b")


def fix_combo_codes(text: str) -> str:
    """Hậu xử lý theo nghiệp vụ: mã tổ hợp là một chữ cái + hai chữ số, nên chữ O trong phần số là
    số 0 đọc nhầm (VietOCR: "DO1", "BOO", "coo" — đo 02/10/2026)."""
    return _COMBO_RE.sub(
        lambda m: m.group(1).upper() + m.group(2).replace("O", "0").replace("o", "0"), text
    )


def group_rows(lines: list[dict]) -> list[list[str]]:
    """Hàng nhìn thấy: khung có tâm dọc nằm trong chiều cao khung đầu hàng là cùng hàng, các ô xếp
    trái sang phải. Lớp lọc danh sách người cần họ tên và ngày sinh chung một hàng; output OCR thì
    mỗi ô là một dòng riêng."""
    rows: list[list[dict]] = []
    for line in sorted(lines, key=lambda ln: (ln["box"][1] + ln["box"][3]) / 2):
        _, y0, _, y1 = line["box"]
        centre = (y0 + y1) / 2
        if rows and rows[-1][0]["box"][1] <= centre <= rows[-1][0]["box"][3]:
            rows[-1].append(line)
        else:
            rows.append([line])
    return [
        [fix_combo_codes(ln["text"]) for ln in sorted(row, key=lambda ln: ln["box"][0])]
        for row in rows
    ]


def page_text(rows: list[list[str]]) -> str:
    return "\n".join(" | ".join(cells) for cells in rows)
