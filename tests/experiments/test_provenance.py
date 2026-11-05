import pathlib

import pytest

from experiments.provenance import (
    StaleRunError,
    run_identity,
    sha256_file,
    verify_corpus_unchanged,
)

CONFIG = {"run_id": "pilot-001", "seed": 42, "arms": ["B0", "B1"]}


def files(tmp_path: pathlib.Path, gold: str = "g", pdf: str = "p"):
    gold_path = tmp_path / "gold.jsonl"
    pdf_path = tmp_path / "corpus.pdf"
    gold_path.write_text(gold, encoding="utf-8")
    pdf_path.write_bytes(pdf.encode("utf-8"))
    return gold_path, pdf_path


def manifest_for(gold_path: pathlib.Path, pdf_path: pathlib.Path) -> dict:
    return {"gold_sha256": sha256_file(gold_path), "pdf_sha256": sha256_file(pdf_path)}


def test_identity_ignores_the_arms_list():
    """Chạy nốt một arm còn thiếu vào cùng run là hợp lệ."""
    subset = {**CONFIG, "arms": ["B0"]}
    assert run_identity(CONFIG, gold_sha256="a", pdf_sha256="b") == run_identity(
        subset, gold_sha256="a", pdf_sha256="b"
    )


def test_identity_changes_when_the_model_changes():
    other = {**CONFIG, "generator": {"model": "khác"}}
    assert run_identity(CONFIG, gold_sha256="a", pdf_sha256="b") != run_identity(
        other, gold_sha256="a", pdf_sha256="b"
    )


def test_identity_changes_when_gold_changes():
    assert run_identity(CONFIG, gold_sha256="a", pdf_sha256="b") != run_identity(
        CONFIG, gold_sha256="a2", pdf_sha256="b"
    )


def test_unchanged_corpus_passes(tmp_path: pathlib.Path):
    gold_path, pdf_path = files(tmp_path)
    verify_corpus_unchanged(
        manifest_for(gold_path, pdf_path), gold_path=gold_path, pdf_path=pdf_path
    )


def test_changed_gold_is_rejected(tmp_path: pathlib.Path):
    """Giữ nguyên cache, đổi gold — accuracy tụt từ 1.0 xuống 0.0 mà không báo gì."""
    gold_path, pdf_path = files(tmp_path)
    manifest = manifest_for(gold_path, pdf_path)
    gold_path.write_text("gold đã sửa", encoding="utf-8")
    with pytest.raises(StaleRunError) as excinfo:
        verify_corpus_unchanged(manifest, gold_path=gold_path, pdf_path=pdf_path)
    assert "gold_sha256" in str(excinfo.value)


def test_changed_pdf_is_rejected(tmp_path: pathlib.Path):
    """Giữ nguyên cache, đổi PDF — unsupported rate nhảy từ 0.0 lên 1.0."""
    gold_path, pdf_path = files(tmp_path)
    manifest = manifest_for(gold_path, pdf_path)
    pdf_path.write_bytes(b"PDF khac")
    with pytest.raises(StaleRunError) as excinfo:
        verify_corpus_unchanged(manifest, gold_path=gold_path, pdf_path=pdf_path)
    assert "pdf_sha256" in str(excinfo.value)


def test_manifest_without_hashes_is_rejected(tmp_path: pathlib.Path):
    gold_path, pdf_path = files(tmp_path)
    with pytest.raises(StaleRunError):
        verify_corpus_unchanged({}, gold_path=gold_path, pdf_path=pdf_path)
