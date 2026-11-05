"""Đọc một trang HTML của site trường: tiêu đề, khung nội dung, link (kèm ngày ở
thẻ bài), nút trang sau (postback ASP.NET), dấu hiệu trang đăng nhập, favicon (spec §6.2).

Heuristic chung, không bám một template: các site khoa/phòng dùng khung khác nhau.
Khung nội dung ưu tiên `.chitietbaiviet`, `#print-chitiet`, `<main>`, rồi tới `<body>` đã bỏ
script/style/nav/header/footer.
"""

import copy
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

import lxml.etree
import lxml.html

from qnuchat.ingest.urls import canonicalize

LOGIN_MAX_MAIN_CHARS = 500
_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_POSTBACK = re.compile(r"__doPostBack\('([^']+)'")
_NEXT_TEXTS = frozenset({"»", "›", ">", "sau", "tiếp", "next", "trang sau"})
_MAIN_XPATHS = (
    "//*[contains(concat(' ', normalize-space(@class), ' '), ' chitietbaiviet ')]",
    "//*[@id='print-chitiet']",
    "//main",
)
# `input` gồm `__VIEWSTATE`: đổi mỗi lần tải, nếu để lại thì blob trang hub đổi hằng ngày.
_STRIP = ("script", "style", "noscript", "nav", "header", "footer", "input", "button", "select")
_CHARSET = re.compile(rb"""charset=["']?([A-Za-z0-9_-]+)""")
_CONTAINERS = ("article", "li", "tr")
_NO_BODY = lxml.html.Element("div")  # khung rỗng dùng chung cho trang không có <body>; không sửa


@dataclass(frozen=True)
class Link:
    url: str
    text: str
    date: date | None
    in_main: bool


@dataclass(frozen=True)
class Pager:
    target: str
    fields: dict[str, str]
    action: str


@dataclass(frozen=True)
class ParsedPage:
    title: str
    main_html: str
    main_text_len: int
    links: list[Link]
    images: list[str]
    pager_next: Pager | None
    login_form: bool
    icon_href: str | None
    published: date | None


def parse_page(content: bytes, url: str, *, aliases: Mapping[str, str] | None = None) -> ParsedPage:
    try:
        doc = lxml.html.document_fromstring(_decode(content))
    except lxml.etree.ParserError:  # thân rỗng hoặc chỉ có comment
        return ParsedPage("", "", 0, [], [], None, False, None, None)
    main = _main_element(doc)
    main_members = set(main.iter())
    clean = copy.deepcopy(main)
    for element in list(clean.iter(*_STRIP)):
        element.drop_tree()
    main_text = " ".join(clean.text_content().split())

    links: list[Link] = []
    for anchor in doc.xpath("//a[@href]"):
        target = canonicalize(anchor.get("href"), base=url, aliases=aliases)
        if target is None:
            continue
        links.append(
            Link(
                url=target,
                text=" ".join(anchor.text_content().split()),
                date=_context_date(anchor),
                in_main=anchor in main_members and not _is_stripped(anchor, main),
            )
        )
    images = []
    for src in clean.xpath(".//img/@src"):
        target = canonicalize(src, base=url, aliases=aliases)
        if target is not None and target not in images:
            images.append(target)

    has_password = any(
        not _is_hidden(field)
        for field in doc.xpath("//input[translate(@type, 'PASWORD', 'pasword')='password']")
    )
    return ParsedPage(
        title=_title(doc),
        main_html="" if main is _NO_BODY else lxml.html.tostring(clean, encoding="unicode"),
        main_text_len=len(main_text),
        links=links,
        images=images,
        pager_next=_pager(doc, url, aliases),
        login_form=has_password and len(main_text) < LOGIN_MAX_MAIN_CHARS,
        icon_href=_icon(doc, url, aliases),
        published=_published(doc, main),
    )


def _is_stripped(anchor, main) -> bool:
    """Link nằm trong phần tử bị `_STRIP` (nav/header/footer…) của khung nội dung thì không
    phải link của bài; xét trên cây gốc vì `clean` là bản sao nên không chứa anchor gốc."""
    for ancestor in anchor.iterancestors():
        if ancestor is main:
            return False
        if ancestor.tag in _STRIP:
            return True
    return False


def _is_hidden(element) -> bool:
    """Ô nằm trong khối ẩn (modal đăng nhập RadWindow có ở mọi trang của site) thì không tính."""
    for node in (element, *element.iterancestors()):
        style = re.sub(r"\s+", "", node.get("style") or "").lower()
        if (
            "display:none" in style
            or "visibility:hidden" in style
            or node.get("hidden") is not None
        ):
            return True
        ident = f"{node.get('id') or ''} {node.get('class') or ''}"
        if "rwUserLogin" in ident or "rwWindow" in ident:
            return True
    return False


def _decode(content: bytes) -> str:
    """Tự giải mã: lxml đoán sai (latin-1) với trang UTF-8 không khai charset. Mặc định UTF-8."""
    content = content.removeprefix(b"\xef\xbb\xbf")
    match = _CHARSET.search(content[:4096])
    encoding = match.group(1).decode("ascii") if match else "utf-8"
    try:
        text = content.decode(encoding, errors="replace")
    except LookupError:
        text = content.decode("utf-8", errors="replace")
    # lxml từ chối chuỗi unicode có khai báo <?xml … encoding=…?>
    return re.sub(r"^\s*<\?xml[^>]*\?>", "", text)


def _main_element(doc):
    """Khung nội dung; không bao giờ là gốc tài liệu (có `<head>`). Trang không có `<body>`
    (trang lỗi mềm của site: chỉ có `<head><title>Untitled Page`) cho khung rỗng."""
    for xpath in _MAIN_XPATHS:
        found = doc.xpath(xpath)
        if found:
            return found[0]
    bodies = doc.xpath("//body")
    return bodies[0] if bodies else _NO_BODY


def _title(doc) -> str:
    for xpath in (
        "//meta[@property='og:title']/@content",
        "//h1",
        "//*[@id='print-chitiet']//h2",
        "//h2",
        "//title",
    ):
        found = doc.xpath(xpath)
        if found:
            value = found[0] if isinstance(found[0], str) else found[0].text_content()
            value = " ".join(value.split())
            if value:
                return value
    return ""


def _parse_vn_date(text: str) -> date | None:
    for match in _DATE.finditer(text):
        day, month, year = (int(g) for g in match.groups())
        try:
            return date(year, month, day)
        except ValueError:
            continue
    return None


def _context_date(anchor) -> date | None:
    """Ngày trong thẻ bài chứa link (article/li/tr hoặc class `card`), tối đa 5 tầng lên."""
    for ancestor in list(anchor.iterancestors())[:5]:
        classes = ancestor.get("class") or ""
        if ancestor.tag in _CONTAINERS or "card" in classes.split():
            return _parse_vn_date(" ".join(ancestor.itertext()))
    return None


def _pager(doc, url: str, aliases) -> Pager | None:
    for anchor in doc.xpath("//a[@href]"):
        match = _POSTBACK.search(anchor.get("href") or "")
        if not match:
            continue
        target = match.group(1)
        text = " ".join(anchor.text_content().split()).lower()
        if not (target.endswith("lbtNext") or text in _NEXT_TEXTS):
            continue
        forms = anchor.xpath("ancestor::form[1]")
        scope = forms[0] if forms else doc
        fields = {
            field.get("name"): field.get("value") or ""
            for field in scope.xpath(".//input[@type='hidden'][@name]")
        }
        action = url
        if forms and forms[0].get("action"):
            action = canonicalize(forms[0].get("action"), base=url, aliases=aliases) or url
        return Pager(target=target, fields=fields, action=action)
    return None


def _icon(doc, url: str, aliases) -> str | None:
    for href in doc.xpath(
        "//link[contains(concat(' ', normalize-space(@rel), ' '), ' icon ')]/@href"
    ):
        target = canonicalize(href, base=url, aliases=aliases)
        if target:
            return target
    return None


def _published(doc, main) -> date | None:
    """Chỉ tin metadata máy đọc được và ô ngày đăng có cấu trúc của CMS; KHÔNG lấy ngày đầu
    tiên trong thân bài (thường là ngày của văn bản được dẫn, ví dụ "Quy chế ... ngày
    15/02/2026"). Ngày đăng thường lấy từ thẻ bài ở trang danh sách."""
    for value in doc.xpath("//meta[@property='article:published_time']/@content"):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            continue
    for value in main.xpath(".//time/@datetime"):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            continue
    # CMS site các khoa: ô `<div class="date fa fa-clock-o">dd/mm/yyyy</div>` đầu bài, ngoài vùng
    # nội dung chính (cột bên dùng `<p class="date">`, không phải div này). Site www chỉ ghi
    # "30 Th03", không có năm: không dùng được.
    for cell in doc.xpath(
        "//div[contains(concat(' ', normalize-space(@class), ' '), ' date ')]"
        "[contains(concat(' ', normalize-space(@class), ' '), ' fa-clock-o ')]"
    ):
        found = _parse_vn_date(cell.text_content())
        if found is not None:
            return found
    return None
