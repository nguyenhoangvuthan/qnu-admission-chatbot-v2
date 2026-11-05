"""Site giả cho test crawler: phục vụ GET/POST qua httpx.MockTransport, ghi lại mọi request."""

import io
from urllib.parse import parse_qsl

import httpx
import pymupdf
from PIL import Image

LISTING = "https://www.qnu.edu.vn/vi/dai-hoc-chinh-quy-1764"
NEXT = "ctl22$ctl02$lbtNext"


def png(width=300, height=300, color="white") -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), color).save(out, format="PNG")
    return out.getvalue()


def ico() -> bytes:
    out = io.BytesIO()
    Image.new("RGBA", (16, 16), (0, 80, 160, 255)).save(out, format="ICO")
    return out.getvalue()


def text_pdf(
    text="Thong bao diem chuan trung tuyen dai hoc chinh quy nam 2026, Truong Dai hoc Quy Nhon.",
):
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), text, fontsize=10)
    return doc.tobytes()


def scanned_pdf() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_image(page.rect, stream=png(400, 400, "gray"))
    return doc.tobytes()


def card(href: str, title: str, day: str) -> str:
    return (
        f'<article class="card card-vertical"><div class="card-body"><h6 class="card-title">'
        f'<a href="{href}">{title}</a></h6>\n'
        f'<ul class="list-inline"><li><span>{day}</span></li></ul>'
        f"</div></article>\n"
    )


def listing_html(
    cards: list[str],
    *,
    pager: bool = True,
    viewstate: str = "VS",
    nav: str = '<a href="/vi/quan-tri">Quản trị</a>',
) -> str:
    next_link = f"<a id=\"ctl22_ctl02_lbtNext\" href=\"javascript:__doPostBack('{NEXT}','')\">»</a>"
    return (
        "<!DOCTYPE html><html><head><title>Đại học chính quy</title>"
        '<link rel="shortcut icon" href="/Resources/assets/index/imgs/favicon.ico" /></head><body>'
        f'<form method="post" action="./dai-hoc-chinh-quy-1764">'
        f'<input type="hidden" name="__VIEWSTATE" value="{viewstate}" />'
        f'<nav>{nav}</nav><div class="row">{"".join(cards)}</div>'
        f"{next_link if pager else ''}</form></body></html>"
    )


def article_html(title: str, body: str, sidebar: str = "") -> str:
    return (
        f'<html><head><meta property="og:title" content="{title}" /></head><body>'
        f'<div id="print-chitiet"><h2 class="fs-3">{title}</h2>'
        f'<div class="chitietbaiviet">{body}</div></div>'
        f'<div class="tin-khac">{sidebar}</div>'
        '<input type="hidden" name="__VIEWSTATE" value="' + str(len(sidebar)) + '" /></body></html>'
    )


class FakeSite:
    def __init__(self):
        self.routes: dict[str, tuple[int, str, bytes]] = {}
        self.posts: dict[tuple[str, str], bytes] = {}
        self.requests: list[tuple[str, str]] = []

    def html(self, url: str, body: str, status: int = 200) -> None:
        self.routes[url] = (status, "text/html; charset=utf-8", body.encode("utf-8"))

    def file(self, url: str, data: bytes, ctype: str = "application/octet-stream") -> None:
        self.routes[url] = (200, ctype, data)

    def redirect(self, url: str, to: str) -> None:
        self.routes[url] = (302, to, b"")

    def remove(self, url: str) -> None:
        self.routes.pop(url, None)

    def post(self, url: str, target: str, body: str) -> None:
        self.posts[(url, target)] = body.encode("utf-8")

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append((request.method, url))
        if request.method == "POST":
            form = dict(parse_qsl(request.content.decode()))
            body = self.posts.get((url, form.get("__EVENTTARGET", "")))
            if body is None:
                return httpx.Response(404)
            return httpx.Response(200, headers={"content-type": "text/html"}, content=body)
        status, ctype, body = self.routes.get(url, (404, "text/html", b"<html>404</html>"))
        if status in (301, 302):
            return httpx.Response(status, headers={"location": ctype})
        return httpx.Response(status, headers={"content-type": ctype}, content=body)

    def count(self, method: str, url: str) -> int:
        return sum(1 for m, u in self.requests if m == method and u == url)


def build_site() -> FakeSite:
    """Chuyên mục tầng A hai trang; ba bài; bài A1 có PDF chữ, ảnh bảng, file Drive scan,
    thư mục Drive; bài A2 là danh sách người; một bài bị lọc theo tiêu đề; một link quản trị
    chuyển sang trang đăng nhập."""
    site = FakeSite()
    a1, a2, a3 = (
        f"{LISTING}/tb141-diem-chuan",
        f"{LISTING}/tb121-nguong",
        f"{LISTING}/tb112-chi-tieu",
    )
    skip = f"{LISTING}/danh-sach-thi-sinh-trung-tuyen"
    site.html(
        LISTING,
        listing_html(
            [
                card(
                    "/vi/dai-hoc-chinh-quy-1764/tb141-diem-chuan",
                    "TB141 - Điểm chuẩn",
                    "09/08/2026",
                ),
                card("/vi/dai-hoc-chinh-quy-1764/tb121-nguong", "TB121 - Ngưỡng", "09/07/2026"),
                card(
                    "/vi/dai-hoc-chinh-quy-1764/danh-sach-thi-sinh-trung-tuyen",
                    "Danh sách thí sinh trúng tuyển đợt 1",
                    "01/08/2026",
                ),
            ]
        ),
    )
    page2 = listing_html(
        [card("/vi/dai-hoc-chinh-quy-1764/tb112-chi-tieu", "TB112 - Chỉ tiêu", "01/03/2025")],
        viewstate="VS2",
    )
    site.post(LISTING, NEXT, page2)
    site.html(
        a1,
        article_html(
            "TB141 - Điểm chuẩn",
            (
                "<p>Điểm chuẩn trúng tuyển đại học chính quy năm 2026.</p>"
                '<p><a href="/Resources/Docs/TB141.pdf">Văn bản</a></p>'
                '<img src="/Resources/Images/bang1.png" /><img src="/Resources/Images/icon.png" />'
                '<p><a href="https://drive.google.com/file/d/1AbCdEfGhIjKlMnOp/view">'
                "Bản scan</a></p>"
                '<p><a href="https://drive.google.com/drive/folders/1FoLdErIdXyZ12345">'
                "Thư mục</a></p>"
            ),
            sidebar="<a href='/vi/dai-hoc-chinh-quy-1764/tb121-nguong'>TB121</a>",
        ),
    )
    site.html(
        a2,
        article_html(
            "TB121 - Ngưỡng",
            (
                "<table><tr><th>STT</th><th>Họ và tên</th><th>Ngày sinh</th></tr>"
                "<tr><td>1</td><td>Nguyễn Văn A</td><td>01/02/2008</td></tr></table>"
            ),
        ),
    )
    site.html(
        a3, article_html("TB112 - Chỉ tiêu", "<p>Chỉ tiêu tuyển sinh năm 2025 theo ngành.</p>")
    )
    site.html(skip, article_html("Danh sách", "<p>không được tải</p>"))
    site.file("https://www.qnu.edu.vn/Resources/Docs/TB141.pdf", text_pdf(), "application/pdf")
    site.file("https://www.qnu.edu.vn/Resources/Images/bang1.png", png(), "image/png")
    site.file("https://www.qnu.edu.vn/Resources/Images/icon.png", png(32, 32), "image/png")
    site.file(
        "https://drive.google.com/uc?export=download&id=1AbCdEfGhIjKlMnOp",
        scanned_pdf(),
        "application/pdf",
    )
    site.file(
        "https://www.qnu.edu.vn/Resources/assets/index/imgs/favicon.ico", ico(), "image/x-icon"
    )
    site.redirect("https://www.qnu.edu.vn/vi/quan-tri", "https://www.qnu.edu.vn/Login.aspx")
    site.html(
        "https://www.qnu.edu.vn/Login.aspx",
        "<html><body><form><input type='password' name='p' /></form></body></html>",
    )
    return site
