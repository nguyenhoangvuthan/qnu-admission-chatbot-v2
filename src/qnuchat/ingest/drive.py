"""Tải file Google Drive công khai theo id (spec §4.1; thử 12/10/2026 với TB100: đúng file,
khớp SHA-256).
Thư mục Drive không liệt kê được khi không đăng nhập nên không có hàm cho thư mục."""

import re
from urllib.parse import urlsplit

from qnuchat.ingest.fetch import Fetcher, FetchError, Response

UC_URL = "https://drive.google.com/uc?export=download&id={id}"
CONFIRM_URL = "https://drive.usercontent.google.com/download?id={id}&export=download&confirm=t"
# Chỉ link tới accounts.google.com ở chân trang (trang cảnh báo virus) thì không phải đăng nhập.
_SIGN_IN_FORM = re.compile(
    rb"<form\b[^>]*\baction\s*=\s*[\"']?[^\"'>\s]*(?:ServiceLogin|signin)", re.IGNORECASE
)
_SIGN_IN_TITLE = re.compile(
    rb"<title[^>]*>[^<]*(?:Sign in|\xc4\x90\xc4\x83ng nh\xe1\xba\xadp)", re.IGNORECASE
)


def _is_html(response: Response) -> bool:
    return response.content_type.startswith("text/html")


def _needs_sign_in(response: Response) -> bool:
    head = response.content[:20000]
    return (
        urlsplit(response.final_url).hostname == "accounts.google.com"
        or bool(_SIGN_IN_FORM.search(head))
        or bool(_SIGN_IN_TITLE.search(head))
    )


def fetch_file(fetcher: Fetcher, file_id: str) -> Response:
    response = fetcher.get(UC_URL.format(id=file_id))
    if not _is_html(response):
        return response
    if _needs_sign_in(response):
        raise FetchError(response.url, "web_auth_required", response.status, detail="drive_sign_in")
    # File lớn: Drive trả trang cảnh báo quét virus thay cho file; URL confirm bỏ qua trang đó.
    response = fetcher.get(CONFIRM_URL.format(id=file_id))
    if _is_html(response):
        if _needs_sign_in(response):
            raise FetchError(
                response.url, "web_auth_required", response.status, detail="drive_sign_in"
            )
        raise FetchError(response.url, "web_http_4xx", response.status, detail="drive_not_a_file")
    return response
