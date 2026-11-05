"""Favicon của từng host cho chip nguồn (spec N6, §6.2 bước 7). Chỉ nhận khi giải mã được thành ảnh:
`/favicon.ico` của site trường trả 200 kèm trang lỗi HTML (kiểm 12/10/2026)."""

import io
from urllib.parse import urlsplit

from PIL import Image, UnidentifiedImageError

SIZE = 32


def candidates(icon_href: str | None, page_url: str) -> list[str]:
    host = urlsplit(page_url).hostname
    if not host:
        return []
    fallback = f"https://{host}/favicon.ico"
    out = [icon_href] if icon_href else []
    if fallback not in out:
        out.append(fallback)
    return out


def to_png(data: bytes) -> bytes | None:
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            icon = img.convert("RGBA").resize((SIZE, SIZE), Image.Resampling.LANCZOS)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        return None
    out = io.BytesIO()
    icon.save(out, format="PNG")
    return out.getvalue()
