from datetime import date
from pathlib import Path

import pytest

from qnuchat.ingest.extract import extract_html
from qnuchat.ingest.html_page import ParsedPage, parse_page

FIXTURES = Path("tests/fixtures/qnu_web")
LISTING_URL = "https://www.qnu.edu.vn/vi/dai-hoc-chinh-quy-1764"

LISTING = """<!DOCTYPE html><html><head><title>Đại học chính quy</title>
<link rel="shortcut icon" type="image/png" href="/Resources/assets/index/imgs/favicon.ico" /></head>
<body><form method="post" action="./dai-hoc-chinh-quy-1764" id="form1">
<input type="hidden" name="__VIEWSTATE" value="VS1" />
<input type="hidden" name="__EVENTTARGET" value="" />
<nav><a href="/vi/gioi-thieu">Giới thiệu</a></nav>
<div class="row articles-top">
 <article class="card card-vertical"><div class="card-body">
  <h6 class="card-title">
  <a href="/vi/dai-hoc-chinh-quy-1764/tb141-diem-chuan">TB141 - Điểm chuẩn</a></h6>
  <ul class="list-inline text-muted"><li><span>09/08/2026</span></li></ul></div></article>
 <article class="card card-vertical"><div class="card-body">
  <h6 class="card-title"><a href="/vi/dai-hoc-chinh-quy-1764/tb121-nguong">TB121 - Ngưỡng</a></h6>
  <ul class="list-inline text-muted"><li><span>09/07/2026</span></li></ul></div></article>
</div>
<a id="ctl22_ctl02_lbt1" href="javascript:__doPostBack('ctl22$ctl02$lbt1','')">2</a>
<a id="ctl22_ctl02_lbtNext" href="javascript:__doPostBack('ctl22$ctl02$lbtNext','')">»</a>
</form></body></html>"""

ARTICLE = """<html><head>
<meta property="og:title" content="TB141 - Điểm chuẩn năm 2026" /></head><body>
<header><a href="/vi/trang-chu">Trang chủ</a></header>
<div id="print-chitiet"><h2 class="fs-3">TB141 - Điểm chuẩn năm 2026</h2>
<div class="chitietbaiviet"><p>Căn cứ Quy chế ... ngày 15/02/2026.</p>
<p><a href="/Resources/Docs/TB141.pdf">Tải văn bản</a></p>
<img src="/Resources/Images/bang%201.png" /><script>var x = 1;</script></div></div>
<div class="tin-khac"><a href="/vi/dai-hoc-chinh-quy-1764/tb121-nguong">TB121</a></div>
</body></html>"""


def test_listing_links_carry_the_card_date():
    page = parse_page(LISTING.encode(), LISTING_URL)
    dates = {link.url: link.date for link in page.links}
    assert dates["https://www.qnu.edu.vn/vi/dai-hoc-chinh-quy-1764/tb141-diem-chuan"] == date(
        2026, 8, 9
    )
    assert dates["https://www.qnu.edu.vn/vi/dai-hoc-chinh-quy-1764/tb121-nguong"] == date(
        2026, 7, 9
    )
    assert dates["https://www.qnu.edu.vn/vi/gioi-thieu"] is None


def test_next_page_is_the_postback_target_with_the_form_fields():
    pager = parse_page(LISTING.encode(), LISTING_URL).pager_next
    assert pager.target == "ctl22$ctl02$lbtNext"
    assert pager.fields == {"__VIEWSTATE": "VS1", "__EVENTTARGET": ""}
    assert pager.action == LISTING_URL


def test_icon_link_is_resolved():
    page = parse_page(LISTING.encode(), LISTING_URL)
    assert page.icon_href == "https://www.qnu.edu.vn/Resources/assets/index/imgs/favicon.ico"


def test_article_main_content_excludes_sidebar_header_and_scripts():
    page = parse_page(ARTICLE.encode(), LISTING_URL + "/tb141")
    assert page.title == "TB141 - Điểm chuẩn năm 2026"
    assert "Căn cứ Quy chế" in page.main_html
    assert "tin-khac" not in page.main_html and "Trang chủ" not in page.main_html
    assert "var x" not in page.main_html
    assert page.images == ["https://www.qnu.edu.vn/Resources/Images/bang%201.png"]
    in_main = {link.url: link.in_main for link in page.links}
    assert in_main["https://www.qnu.edu.vn/Resources/Docs/TB141.pdf"] is True
    assert in_main["https://www.qnu.edu.vn/vi/dai-hoc-chinh-quy-1764/tb121-nguong"] is False
    assert page.pager_next is None and page.login_form is False


def test_a_body_date_is_not_mistaken_for_the_publication_date():
    assert parse_page(ARTICLE.encode(), LISTING_URL + "/tb141").published is None


def test_published_meta_is_used_when_present():
    html = ARTICLE.replace(
        "<head>",
        '<head><meta property="article:published_time" content="2026-08-09T10:00:00+07:00" />',
    )
    assert parse_page(html.encode(), LISTING_URL + "/tb141").published == date(2026, 8, 9)


def test_short_page_with_password_field_is_a_login_page():
    html = (
        b"<html><body><form><input name=u /><input type='password' name=p /></form></body></html>"
    )
    assert parse_page(html, "https://pdt.qnu.edu.vn/login").login_form is True


def test_hidden_login_modal_on_a_long_page_is_not_a_login_page():
    body = "<p>" + "Thông tin tuyển sinh. " * 60 + "</p>"
    html = (
        f"<html><body><div class='chitietbaiviet'>{body}</div>"
        "<div id='rwUserLogin' style='display:none'><input type='password' /></div></body></html>"
    )
    assert parse_page(html.encode(), LISTING_URL + "/x").login_form is False


def test_utf8_bom_and_bytes_input_are_handled():
    page = parse_page("﻿".encode() + ARTICLE.encode(), LISTING_URL + "/tb141")
    assert page.title.startswith("TB141")


def test_real_qnu_listing_fixture():
    page = parse_page((FIXTURES / "qnu-listing.html").read_bytes(), LISTING_URL)
    children = [l for l in page.links if l.url.startswith(LISTING_URL + "/")]
    assert len(children) >= 5
    assert sum(1 for l in children if l.date is not None) >= 5
    assert page.pager_next is not None and page.pager_next.target.endswith("lbtNext")
    assert "__VIEWSTATE" in page.pager_next.fields
    assert page.icon_href.endswith("favicon.ico")


def test_real_qnu_article_fixture():
    url = LISTING_URL + "/tb141-diem-chuan-trung-tuyen-vao-dai-hoc-chinh-quy-nam-2026"
    page = parse_page((FIXTURES / "qnu-article.html").read_bytes(), url)
    assert page.title.startswith("TB141")
    assert "Các tin khác" not in page.main_html
    assert any(l.url.lower().endswith(".pdf") and l.in_main for l in page.links)
    assert page.login_form is False


def test_real_tuyensinh_listing_fixture():
    url = "https://tuyensinh.qnu.edu.vn/vi/tuyen-sinh-dai-hoc-chinh-quy-2027"
    page = parse_page((FIXTURES / "tuyensinh-listing.html").read_bytes(), url)
    assert len([l for l in page.links if l.url.startswith(url + "/")]) >= 3
    assert page.login_form is False


@pytest.mark.parametrize("content", [b"", b"   ", b"<!-- x -->"])
def test_empty_document_gives_empty_page(content):
    page = parse_page(content, LISTING_URL)
    assert page == ParsedPage(
        title="",
        main_html="",
        main_text_len=0,
        links=[],
        images=[],
        pager_next=None,
        login_form=False,
        icon_href=None,
        published=None,
    )


_SHORT_NOTICE = (
    "<html><body><div class='chitietbaiviet'><p>Thông báo ngắn.</p>"
    "<a href='/Resources/Docs/a.pdf'>Tải</a></div>{modal}</body></html>"
)


@pytest.mark.parametrize(
    "modal",
    [
        "<div id='rwUserLogin' style='display:none'><input type='password' /></div>",
        '<div style="DISPLAY: none"><input type="password" /></div>',
        "<div style='visibility : hidden'><form><input type='password' /></form></div>",
        "<div hidden><input type='password' /></div>",
        "<div class='RadWindow rwWindow'><input type='password' /></div>",
    ],
)
def test_password_inside_hidden_modal_is_not_a_login_page(modal):
    html = _SHORT_NOTICE.format(modal=modal)
    assert parse_page(html.encode(), LISTING_URL + "/x").login_form is False


SOFT_404 = "﻿<!DOCTYPE html><html><head><title>Untitled Page</title></head></html>".encode()


def test_bodyless_soft_404_has_no_main_content():
    page = parse_page(SOFT_404, LISTING_URL)
    assert page.main_html == "" and page.main_text_len == 0 and page.links == []
    assert extract_html(page.main_html).text == ""


def test_main_element_falls_back_to_body_never_the_whole_document():
    html = "<html><head><title>Trang</title></head><body><p>Thân trang.</p></body></html>".encode()
    page = parse_page(html, LISTING_URL)
    assert "<head" not in page.main_html and "Thân trang." in page.main_html


def test_links_in_stripped_nav_header_footer_are_not_in_main_on_body_fallback():
    html = (
        "<html><body><nav><a href='/vi/menu'>Menu</a></nav>"
        "<header><a href='/vi/dau'>Đầu</a></header>"
        "<div><a href='/vi/noi-dung'>Nội dung</a></div>"
        "<footer><a href='/vi/chan'>Chân</a></footer></body></html>"
    )
    page = parse_page(html.encode(), LISTING_URL)
    in_main = {link.url.rsplit("/", 1)[1]: link.in_main for link in page.links}
    assert in_main == {"menu": False, "dau": False, "noi-dung": True, "chan": False}


def test_compact_html_without_spaces_still_yields_the_card_date():
    html = (
        "<html><body><article><h6><a href='/vi/tb141'>TB141 - Điểm chuẩn</a></h6>"
        "<ul><li><span>Điểm chuẩn</span><span>09/08/2026</span></li></ul></article>"
        "</body></html>"
    )
    page = parse_page(html.encode(), LISTING_URL)
    assert page.links[0].date == date(2026, 8, 9)


def test_published_comes_from_the_faculty_cms_clock_date_not_the_sidebar():
    # Site các khoa: ngày đăng ở <div class="date fa fa-clock-o"> đầu bài, ngoài vùng nội dung
    # chính; cột bên có các <p class="date"> của bài khác.
    html = (
        "<html><body>"
        '<div class="date fa fa-clock-o" aria-hidden="true"> 22/07/2025 </div>'
        "<main><h1>TMA tuyển dụng</h1><p>Nội dung, trích quyết định ngày 15/02/2019.</p></main>"
        '<aside><p class="date">29/06/2026</p><p class="date">12/06/2026</p></aside>'
        "</body></html>"
    )
    assert parse_page(html.encode(), LISTING_URL + "/tma").published == date(2025, 7, 22)


def test_sidebar_dates_alone_are_not_a_publish_date():
    html = (
        "<html><body><main><h1>Bài</h1><p>Nội dung.</p></main>"
        '<aside><p class="date">29/06/2026</p></aside></body></html>'
    )
    assert parse_page(html.encode(), LISTING_URL + "/bai").published is None
