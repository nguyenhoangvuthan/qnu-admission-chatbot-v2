"""Chuẩn hoá số theo quy ước Việt Nam. Dùng cho metric T1 (slots).

Dấu chấm là phân cách hàng nghìn, dấu phẩy là phân cách thập phân:
    15.000.000 -> 15000000
    22,5       -> 22.5
    1.5        -> 1.5        (giữ nguyên: "5" không đủ ba chữ số)
"""

import re

_THOUSANDS_DOT = re.compile(r"(?<=\d)[.](?=\d{3}\b)")
_DECIMAL_COMMA = re.compile(r"(?<=\d),(?=\d)")


def normalise_number(text: str) -> str:
    return _DECIMAL_COMMA.sub(".", _THOUSANDS_DOT.sub("", text))
