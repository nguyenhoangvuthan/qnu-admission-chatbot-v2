"""URL: chuẩn hoá, phạm vi quét, link Google Drive, tầng, source_id (spec §5.2, §6)."""

import hashlib
import posixpath
import re
from collections.abc import Mapping, Sequence
from typing import Literal
from urllib.parse import parse_qsl, quote, unquote, urlencode, urljoin, urlsplit, urlunsplit

from qnuchat.ingest.config import CrawlConfig

LinkKind = Literal["page", "file", "image", "drive_file", "drive_folder"]

DOC_EXTS = frozenset({".pdf", ".doc", ".docx", ".xls", ".xlsx"})
IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg"})
SKIP_EXTS = frozenset(
    {
        ".zip",
        ".rar",
        ".7z",
        ".mp4",
        ".mp3",
        ".avi",
        ".mov",
        ".ppt",
        ".pptx",
        ".gif",
        ".svg",
        ".ico",
        ".css",
        ".js",
        ".exe",
        ".apk",
    }
)
_PATH_SAFE = "/:@!$&'()*+,;=-._~"
_DRIVE_FILE = (
    re.compile(r"^https://drive\.google\.com/file/d/([A-Za-z0-9_-]{10,})"),
    re.compile(r"^https://drive\.google\.com/(?:open|uc)\?(?:[^#]*&)?id=([A-Za-z0-9_-]{10,})"),
)
_DRIVE_FOLDER = re.compile(
    r"^https://drive\.google\.com/drive/(?:u/\d+/)?folders/([A-Za-z0-9_-]{10,})"
)


def canonicalize(
    href: str, base: str | None = None, aliases: Mapping[str, str] | None = None
) -> str | None:
    """URL tuyệt đối dạng chuẩn; None với link không điều hướng (#, javascript:, mailto:, tel:)."""
    href = (href or "").strip()
    if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
        return None
    url = urljoin(base, href) if base else href
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https"):
        return None
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        return None
    host = (aliases or {}).get(host, host)
    netloc = host if port in (None, 80, 443) else f"{host}:{port}"
    path = quote(unquote(parts.path or "/"), safe=_PATH_SAFE)
    query = urlencode(
        sorted(
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if not k.lower().startswith("utm_")
        )
    )
    return urlunsplit(("https", netloc, path, query, ""))


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def in_scope(url: str, cfg: CrawlConfig, *, url_patterns: bool = True) -> bool:
    """`url_patterns=False`: bỏ qua `blocklist_url_patterns`, vẫn xét host (file luôn tải)."""
    host = host_of(url)
    bare = cfg.host_suffix.lstrip(".")
    if not (host == bare or host.endswith(cfg.host_suffix)):
        return False
    if host in cfg.blocklist_hosts:
        return False
    if not url_patterns:
        return True
    return not any(re.search(pattern, url) for pattern in cfg.blocklist_url_patterns)


def attachments_always(page_url: str | None, cfg: CrawlConfig) -> bool:
    """Trang chứa là trang con của một URL trong `attachments_always_from`."""
    if not page_url:
        return False
    parents = (canonicalize(p, aliases=cfg.host_aliases) for p in cfg.attachments_always_from)
    return any(parent and is_child(page_url, parent) for parent in parents)


def drive_file_id(url: str) -> str | None:
    for pattern in _DRIVE_FILE:
        match = pattern.match(url)
        if match:
            return match.group(1)
    return None


def drive_canonical(url: str) -> str | None:
    """Một URL cho mỗi file Drive (`file/d/<id>/…`, `open?id=`, `uc?id=`, mọi `usp=`…):
    `https://drive.google.com/file/d/<id>/view`. None nếu không phải link file Drive."""
    file_id = drive_file_id(url)
    return f"https://drive.google.com/file/d/{file_id}/view" if file_id else None


def drive_folder_id(url: str) -> str | None:
    match = _DRIVE_FOLDER.match(url)
    return match.group(1) if match else None


def classify_link(url: str, cfg: CrawlConfig, *, url_patterns: bool = True) -> LinkKind | None:
    if drive_folder_id(url):
        return "drive_folder"
    if drive_file_id(url):
        return "drive_file"
    if not in_scope(url, cfg, url_patterns=url_patterns):
        return None
    ext = posixpath.splitext(unquote(urlsplit(url).path))[1].lower()
    if ext in DOC_EXTS:
        return "file"
    if ext in IMAGE_EXTS:
        return "image"
    if ext in SKIP_EXTS:
        return None
    return "page"


def source_id_for(url: str) -> str:
    return "w-" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def is_child(url: str, parent: str) -> bool:
    return url.startswith(parent.rstrip("/") + "/") and url.rstrip("/") != parent.rstrip("/")


def tier_for(url: str, tier_a: Sequence[str]) -> Literal["A", "B"]:
    url = urlunsplit(urlsplit(url)._replace(query="", fragment=""))
    for prefix in tier_a:
        if url.rstrip("/") == prefix.rstrip("/") or is_child(url, prefix):
            return "A"
    return "B"
