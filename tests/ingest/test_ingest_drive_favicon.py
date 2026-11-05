import io

import httpx
import pytest
from PIL import Image

from qnuchat.ingest import drive, favicon
from qnuchat.ingest.fetch import Fetcher, FetchError

FILE_ID = "1OLBMmjBWFuk-xOrXSrUyTcveoritVYRW"


def fetcher_for(routes):
    def handler(request):
        status, ctype, body = routes.get(str(request.url), (404, "text/html", b"<html>404</html>"))
        return httpx.Response(status, headers={"content-type": ctype}, content=body)

    return Fetcher(
        user_agent="UA",
        rps_per_host=1000,
        timeout_s=5,
        max_bytes=10_000_000,
        retries=0,
        transport=httpx.MockTransport(handler),
    )


def ico_bytes() -> bytes:
    out = io.BytesIO()
    Image.new("RGBA", (16, 16), (200, 0, 0, 255)).save(out, format="ICO")
    return out.getvalue()


def test_drive_file_downloads_directly():
    routes = {drive.UC_URL.format(id=FILE_ID): (200, "application/pdf", b"%PDF-1.7 ...")}
    assert drive.fetch_file(fetcher_for(routes), FILE_ID).content.startswith(b"%PDF")


def test_drive_virus_scan_page_falls_back_to_the_confirm_url():
    routes = {
        drive.UC_URL.format(id=FILE_ID): (
            200,
            "text/html; charset=utf-8",
            b"<html>Virus scan warning</html>",
        ),
        drive.CONFIRM_URL.format(id=FILE_ID): (200, "application/pdf", b"%PDF-1.7 big"),
    }
    assert drive.fetch_file(fetcher_for(routes), FILE_ID).content == b"%PDF-1.7 big"


def test_drive_sign_in_page_is_auth_required():
    routes = {
        drive.UC_URL.format(id=FILE_ID): (
            200,
            "text/html",
            b"<html><form action='https://accounts.google.com/ServiceLogin'></form></html>",
        )
    }
    with pytest.raises(FetchError) as info:
        drive.fetch_file(fetcher_for(routes), FILE_ID)
    assert info.value.cause == "web_auth_required" and info.value.detail == "drive_sign_in"


VIRUS_PAGE = (
    b"<html><head><title>Google Drive - Virus scan warning</title></head><body>"
    b"<form action='https://drive.usercontent.google.com/download'></form>"
    b"<footer><a href='https://accounts.google.com/SignOutOptions'>Tai khoan</a></footer>"
    b"</body></html>"
)


def test_virus_warning_page_with_an_accounts_footer_link_is_not_a_sign_in():
    routes = {
        drive.UC_URL.format(id=FILE_ID): (200, "text/html", VIRUS_PAGE),
        drive.CONFIRM_URL.format(id=FILE_ID): (200, "application/pdf", b"%PDF-1.7 big"),
    }
    assert drive.fetch_file(fetcher_for(routes), FILE_ID).content == b"%PDF-1.7 big"


@pytest.mark.parametrize(
    "body",
    [
        b"<html><head><title>Sign in - Google Accounts</title></head></html>",
        b"<html><head><title>\xc4\x90\xc4\x83ng nh\xe1\xba\xadp</title></head></html>",
        b"<html><form action='/v3/signin/identifier'></form></html>",
    ],
)
def test_sign_in_page_is_recognised_by_title_or_form(body):
    routes = {drive.UC_URL.format(id=FILE_ID): (200, "text/html", body)}
    with pytest.raises(FetchError) as info:
        drive.fetch_file(fetcher_for(routes), FILE_ID)
    assert info.value.cause == "web_auth_required" and info.value.detail == "drive_sign_in"


def test_redirect_to_accounts_google_com_is_a_sign_in():
    def handler(request):
        if request.url.host == "drive.google.com":
            return httpx.Response(302, headers={"location": "https://accounts.google.com/x"})
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html/>")

    fetcher = Fetcher(
        user_agent="UA",
        rps_per_host=1000,
        timeout_s=5,
        max_bytes=10_000_000,
        retries=0,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(FetchError) as info:
        drive.fetch_file(fetcher, FILE_ID)
    assert info.value.detail == "drive_sign_in"


def test_favicon_candidates_prefer_the_declared_icon():
    page = "https://www.qnu.edu.vn/vi/dai-hoc-chinh-quy-1764"
    declared = "https://www.qnu.edu.vn/Resources/assets/index/imgs/favicon.ico"
    assert favicon.candidates(declared, page) == [declared, "https://www.qnu.edu.vn/favicon.ico"]
    assert favicon.candidates(None, page) == ["https://www.qnu.edu.vn/favicon.ico"]


def test_favicon_is_converted_to_a_32px_png():
    png = favicon.to_png(ico_bytes())
    with Image.open(io.BytesIO(png)) as img:
        assert img.format == "PNG" and img.size == (32, 32)


def test_html_error_page_served_as_favicon_is_refused():
    error_page = "﻿<!DOCTYPE html><html><head><title>Untitled Page</title></head></html>".encode()
    assert favicon.to_png(error_page) is None


def test_favicon_candidates_is_empty_for_a_page_url_without_host():
    assert favicon.candidates(None, "/vi/a") == []
    assert favicon.candidates(None, "") == []


def test_decompression_bomb_is_refused(monkeypatch):
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    out = io.BytesIO()
    Image.new("RGB", (64, 64)).save(out, format="PNG")
    assert favicon.to_png(out.getvalue()) is None
