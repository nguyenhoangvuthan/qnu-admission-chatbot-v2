"""Kho web giả trên đĩa cho test knowledge base: manifest + blob thật trong tmp_path."""

import io
from pathlib import Path

from qnuchat.ingest.blobs import BlobStore
from qnuchat.ingest.manifest import Manifest, ManifestEntry
from qnuchat.ingest.urls import source_id_for

W = "https://www.qnu.edu.vn"
TS = "https://tuyensinh.qnu.edu.vn"


def html_page(title: str, main_text: str) -> bytes:
    return (
        f"<html><head><title>{title}</title></head><body><nav>Menu trang chủ</nav>"
        f"<main><h1>{title}</h1><p>{main_text}</p></main></body></html>"
    ).encode()


def docx_bytes(text: str) -> bytes:
    import docx

    document = docx.Document()
    document.add_paragraph(text)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def png_bytes(width: int = 40, height: int = 30) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (200, 30, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


class WebStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.manifest = Manifest(self.root / "manifest.jsonl")
        self.blobs = BlobStore(self.root)

    def put(
        self,
        url: str,
        *,
        kind: str = "page",
        data: bytes | None = None,
        title: str | None = None,
        page_url: str | None = None,
        tier: str = "B",
        text_status: str | None = None,
        mime: str | None = None,
        quarantine: bool = False,
    ) -> str:
        data = data if data is not None else html_page(title or url, f"Nội dung {url}")
        sha = self.blobs.put(data, tier=tier, quarantine=quarantine)
        status = text_status or ("text" if kind == "page" else "needs_ocr")
        self.manifest.append(
            ManifestEntry(
                url=url,
                source_id=source_id_for(url),
                page_url=page_url,
                kind=kind,
                title=title,
                published=None,
                retrieved_at="2026-10-13T08:00:00+07:00",
                sha256=sha,
                mime=mime or ("text/html" if kind == "page" else "application/octet-stream"),
                bytes=len(data),
                host=url.split("/")[2],
                tier=tier,
                text_status=status,
                reason=None,
                crawl_run="test",
                config_hash="c" * 64,
                sources_yaml_ref=None,
            )
        )
        return sha

    def current(self) -> dict[str, ManifestEntry]:
        return self.manifest.current()
