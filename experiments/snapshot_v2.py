"""Snapshot kho của gold v2 và các arm paper (chốt 14/10/2026): file trong `data/` có lớp chữ.

Chạy: `uv run python -m experiments.snapshot_v2` → `benchmarks/v2/snapshot.json`.

Loại: file đã bị thay (`superseded_by` trong sổ nguồn, và TB152 — xem `EXCLUDED`), bản scan và ảnh
chưa OCR (không trích được chữ), `QNU.CHATBOT.xlsx` (câu hỏi mẫu, không phải nguồn trả lời). Sau OCR
thì dựng snapshot mới với tên khác; không sửa đè snapshot đang dùng cho số đo.
"""

import json
from pathlib import Path

import yaml

from experiments.prepare_gold import _source_texts
from experiments.sources import REGISTRY

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "benchmarks/v2/snapshot.json"
EXCLUDED = {
    "TB152 - Điểm chuẩn trúng tuyển đại học chính quy năm 2025.pdf": (
        "TB153 ghi thay TB152 và sửa điểm CNTT, Trí tuệ nhân tạo (results/data-inventory/d2 §4.1)"
    ),
    "QNU.CHATBOT.xlsx": "câu hỏi mẫu (faq_seed), không phải nguồn trả lời",
}
TEXT_SUFFIXES = {".pdf", ".docx", ".html"}


def _has_text(path: Path) -> bool:
    texts = _source_texts(path, by_line=path.suffix != ".pdf")
    return any(t.strip() for t in texts.values())


def build_snapshot() -> dict:
    files, skipped = [], []
    for source in yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))["sources"]:
        path = REGISTRY.parent / source["file"]
        # Lý do ghi tay trong EXCLUDED thắng: TB152 có `superseded_by` từ 22/10/2026,
        # nhưng snapshot đã khoá giữ nguyên câu lý do cũ.
        reason = EXCLUDED.get(path.name)
        if reason is None and source.get("superseded_by"):
            reason = f"bị thay bởi {Path(source['superseded_by']).name}"
        elif reason is None and path.suffix not in TEXT_SUFFIXES:
            reason = "ảnh/bảng tính, chưa OCR"
        elif reason is None and not _has_text(path):
            reason = "bản scan, chưa OCR"
        entry = {"file": source["file"], "sha256": source["sha256"]}
        if reason:
            skipped.append({**entry, "reason": reason})
        else:
            files.append({**entry, "admission_year": source.get("admission_year")})
    return {"name": "v2-2026-10-14", "files": files, "excluded": skipped}


def main() -> None:
    SNAPSHOT.write_text(
        json.dumps(build_snapshot(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"-> {SNAPSHOT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
