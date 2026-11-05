"""Chuẩn hoá chữ tiếng Việt để khớp từ khoá (danh mục ngành, câu xã giao).

Đặt ở core vì stage `query_rewrite` cần nó và core không được import `apps`.
"""

import re
import unicodedata


def fold(text: str) -> str:
    """Chữ thường, bỏ dấu tiếng Việt (đ → d), bỏ dấu câu và emoji, gộp khoảng trắng."""
    lowered = text.lower().replace("đ", "d")
    stripped = "".join(
        c for c in unicodedata.normalize("NFD", lowered) if unicodedata.category(c) != "Mn"
    )
    return " ".join(re.sub(r"[^a-z0-9\s]", " ", stripped).split())
