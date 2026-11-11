"""Giá trị slot có trong câu trả lời chữ: cơ sở của `correct` (spec §4.1, sửa lần ba 11/11/2026).

So theo dãy token, không theo chuỗi con: "4" không khớp "4,5", "138" không khớp "1380". Chấm trên
chữ không biết giá trị gắn với đối tượng nào; phần đó do `critical_error` trên claim lo.
"""

import re

from qnuchat.eval.metrics.numbers import normalise_number
from qnuchat.eval.schema import ExpectedSlot

# Số (giữ dấu chấm thập phân sau `normalise_number`) hoặc một từ; mọi ký tự khác là chỗ tách.
_TOKEN = re.compile(r"\d+(?:\.\d+)*|[^\W\d_]+")


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(normalise_number(text.lower()))


def _contains(haystack: list[str], needle: list[str]) -> bool:
    size = len(needle)
    starts = range(len(haystack) - size + 1)
    return size > 0 and any(haystack[i : i + size] == needle for i in starts)


def value_in_text(text: str, slot: ExpectedSlot) -> bool:
    """`value` của slot, hoặc một `value_synonyms`, nằm liền trong câu trả lời chữ."""
    tokens = _tokens(text)
    return any(_contains(tokens, _tokens(v)) for v in (slot.value, *slot.value_synonyms))
