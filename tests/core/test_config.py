import re
import shutil
from pathlib import Path

import pytest

from qnuchat.core.config import ConfigError, load_pipeline_config

ROOT = Path(__file__).resolve().parents[2]
SHIPPED = ROOT / "configs/pipeline/b3-qwen3-4b-awq.yaml"
# Đổi cấu hình là đổi hash; hash lệch thì phải cố ý cập nhật ở đây.
B3_HASH = "733cb13ae9a3cbcab486c40d0d27f2018a035469a2d784a8084cce7a54c86912"
CHAT = ROOT / "configs/pipeline/b3-chat.yaml"
REAL_CATALOG = ROOT / "configs/catalog/qnu-2025.yaml"

BASE = """
retrieval: {mode: hybrid, top_k: 5, rrf_k: 60}
corpus:
  max_chunk_chars: 1500
  sources:
    - {source_id: nguon-x, path: docs/x.pdf, excluded_pages: [1, 2], source_year: 2025}
embedding: {model: BAAI/bge-m3, revision: 5617a9f61b028005a4858fdac845db406aefb181}
generator:
  model: Qwen/Qwen3-4B-AWQ
  revision: 74d4bd2bd4bff9cafc9345221320bffb08b406a3
  quantization: awq
  max_tokens: 1024
  temperature: 0
  seed: 42
  chat_template_kwargs: {enable_thinking: false}
history: {max_turns: 6}
stages: {query_rewrite: {enabled: false}}
"""


def write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_shipped_config_loads_with_the_b3_values():
    loaded = load_pipeline_config(SHIPPED)
    cfg = loaded.config
    assert loaded.name == "b3-qwen3-4b-awq"
    assert len(loaded.sha256) == 64
    assert (cfg.retrieval.top_k, cfg.retrieval.rrf_k) == (5, 60)
    assert cfg.corpus.sources[0].excluded_pages == [1, 2, 3, 107, 108]
    assert cfg.corpus.sources[0].source_id == "cam-nang-2025"
    assert cfg.generator.model == "Qwen/Qwen3-4B-AWQ"
    assert cfg.generator.chat_template_kwargs == {"enable_thinking": False}
    assert cfg.history.max_turns == 6
    assert cfg.stages.query_rewrite.enabled is False


def test_unknown_key_is_an_error(tmp_path):
    path = write(tmp_path, "c.yaml", BASE + "unexpected: 1\n")
    with pytest.raises(ConfigError, match="unexpected"):
        load_pipeline_config(path)


def test_extends_merges_mappings_and_replaces_lists(tmp_path):
    write(tmp_path, "base.yaml", BASE)
    child = write(
        tmp_path,
        "child.yaml",
        "extends: base.yaml\ncorpus: {sources: [{source_id: khac, path: y.pdf}]}\n",
    )
    loaded = load_pipeline_config(child)
    assert [s.source_id for s in loaded.config.corpus.sources] == ["khac"]
    assert loaded.config.corpus.max_chunk_chars == 1500
    assert loaded.name == "child"


def test_extends_override_with_a_wrong_path_is_an_error(tmp_path):
    write(tmp_path, "base.yaml", BASE)
    child = write(tmp_path, "child.yaml", "extends: base.yaml\nretreival: {top_k: 3}\n")
    with pytest.raises(ConfigError, match="retreival"):
        load_pipeline_config(child)


def test_extends_allows_only_one_level(tmp_path):
    write(tmp_path, "root.yaml", BASE)
    write(tmp_path, "mid.yaml", "extends: root.yaml\n")
    child = write(tmp_path, "child.yaml", "extends: mid.yaml\n")
    with pytest.raises(ConfigError, match="một tầng"):
        load_pipeline_config(child)


def test_hash_is_the_same_for_extends_and_the_flattened_file(tmp_path):
    write(tmp_path, "base.yaml", BASE)
    child = write(tmp_path, "child.yaml", "extends: base.yaml\nretrieval: {top_k: 3}\n")
    flat = write(tmp_path, "flat.yaml", BASE.replace("top_k: 5", "top_k: 3"))
    assert load_pipeline_config(child).sha256 == load_pipeline_config(flat).sha256


def test_hash_changes_when_chat_template_kwargs_change(tmp_path):
    a = write(tmp_path, "a.yaml", BASE)
    b = write(tmp_path, "b.yaml", BASE.replace("enable_thinking: false", "enable_thinking: true"))
    assert load_pipeline_config(a).sha256 != load_pipeline_config(b).sha256


def test_hash_ignores_the_file_name_and_yaml_formatting(tmp_path):
    a = write(tmp_path, "a.yaml", BASE)
    b = write(tmp_path, "b.yaml", "\n\n".join(BASE.strip().splitlines()))
    assert load_pipeline_config(a).sha256 == load_pipeline_config(b).sha256


def test_shipped_config_hash_is_pinned():
    loaded = load_pipeline_config(SHIPPED)
    assert loaded.sha256 == B3_HASH
    assert loaded.catalog is None


def test_enabling_query_rewrite_requires_a_catalog(tmp_path):
    path = write(tmp_path, "c.yaml", BASE.replace("enabled: false", "enabled: true"))
    with pytest.raises(ConfigError, match="catalog"):
        load_pipeline_config(path)


def with_catalog(tmp_path, catalog_text=None, enabled="true"):
    shutil.copy(REAL_CATALOG, tmp_path / "cat.yaml")
    if catalog_text is not None:
        (tmp_path / "cat.yaml").write_text(catalog_text, encoding="utf-8")
    stages = f"stages: {{query_rewrite: {{enabled: {enabled}, catalog: cat.yaml}}}}\n"
    return write(
        tmp_path,
        "c.yaml",
        BASE.replace("stages: {query_rewrite: {enabled: false}}\n", stages),
    )


def test_catalog_path_is_relative_to_the_config_file_and_is_loaded(tmp_path):
    loaded = load_pipeline_config(with_catalog(tmp_path))
    assert loaded.catalog is not None and loaded.catalog.years == [2025]


def test_hash_changes_when_catalog_content_changes(tmp_path):
    first = load_pipeline_config(with_catalog(tmp_path)).sha256
    catalog_text = REAL_CATALOG.read_text(encoding="utf-8")
    edited = catalog_text.replace("aliases: [KTPM,", "aliases: [SE, KTPM,")
    second = load_pipeline_config(with_catalog(tmp_path, edited)).sha256
    assert first != second


def test_hash_ignores_catalog_comments(tmp_path):
    first = load_pipeline_config(with_catalog(tmp_path)).sha256
    commented = "# thêm chú thích\n" + REAL_CATALOG.read_text(encoding="utf-8")
    assert load_pipeline_config(with_catalog(tmp_path, commented)).sha256 == first


@pytest.mark.parametrize("catalog_text", ["majors: [\n", "version: 1\n"])
def test_broken_or_missing_catalog_is_a_config_error_naming_the_file(tmp_path, catalog_text):
    with pytest.raises(ConfigError, match="cat.yaml"):
        load_pipeline_config(with_catalog(tmp_path, catalog_text))


def test_missing_catalog_file_is_a_config_error(tmp_path):
    path = write(
        tmp_path,
        "c.yaml",
        BASE.replace(
            "stages: {query_rewrite: {enabled: false}}\n",
            "stages: {query_rewrite: {enabled: true, catalog: khong-co.yaml}}\n",
        ),
    )
    with pytest.raises(ConfigError, match="khong-co.yaml"):
        load_pipeline_config(path)


def test_shipped_chat_config_is_b3_plus_query_rewrite():
    chat, b3 = load_pipeline_config(CHAT), load_pipeline_config(SHIPPED)
    assert chat.name == "b3-chat"
    assert chat.config.stages.query_rewrite.enabled is True
    assert chat.catalog is not None
    # Web app nới max_tokens: câu "ngành X là ngành gì" cần ~1100 token, 1024 bị cắt. Giải mã
    # tham lam nên ngân sách lớn hơn chỉ đổi đúng những câu B3 sẽ cắt; mọi thứ khác giữ nguyên.
    assert chat.config.generator.max_tokens == 2048 > b3.config.generator.max_tokens
    rest = {"stages": True, "generator": {"max_tokens"}, "generation": {"empty_answer_notice"}}
    assert chat.config.model_dump(exclude=rest) == b3.config.model_dump(exclude=rest)
    assert chat.sha256 != b3.sha256
    assert chat.config.generation.empty_answer_notice is True


def test_revision_must_be_a_full_commit_hash(tmp_path):
    revision = "74d4bd2bd4bff9cafc9345221320bffb08b406a3"
    path = write(tmp_path, "c.yaml", BASE.replace(revision, "main"))
    with pytest.raises(ConfigError, match="revision"):
        load_pipeline_config(path)


def test_temperature_must_be_zero(tmp_path):
    path = write(tmp_path, "c.yaml", BASE.replace("temperature: 0", "temperature: 0.7"))
    with pytest.raises(ConfigError, match="temperature"):
        load_pipeline_config(path)


def test_top_k_must_be_positive(tmp_path):
    path = write(tmp_path, "c.yaml", BASE.replace("top_k: 5", "top_k: 0"))
    with pytest.raises(ConfigError, match="top_k"):
        load_pipeline_config(path)


def write_config(tmp_path, text: str):
    path = tmp_path / "cfg.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_source_id_is_a_slug_and_enters_the_hash(tmp_path):
    plain = load_pipeline_config(write_config(tmp_path, BASE)).sha256
    other = load_pipeline_config(write_config(tmp_path, BASE.replace("nguon-x", "nguon-y")))
    assert other.sha256 != plain
    with pytest.raises(ConfigError):
        load_pipeline_config(write_config(tmp_path, BASE.replace("nguon-x", "Nguon X")))


def test_corpus_needs_at_least_one_source(tmp_path):
    text = "corpus: {max_chunk_chars: 1500, sources: []}\n"
    path = write_config(tmp_path, re.sub(r"corpus:\n(  .*\n)+", text, BASE))
    with pytest.raises(ConfigError, match="sources"):
        load_pipeline_config(path)


def test_source_ids_must_be_unique(tmp_path):
    line = "    - {source_id: nguon-x, path: docs/y.pdf}\n"
    text = BASE.replace("embedding:", line + "embedding:", 1)
    with pytest.raises(ConfigError, match="trùng"):
        load_pipeline_config(write_config(tmp_path, text))


def test_unknown_key_under_generation_is_rejected(tmp_path):
    with pytest.raises(ConfigError):
        load_pipeline_config(write_config(tmp_path, BASE + "generation: {inline: true}\n"))


def test_empty_answer_notice_on_changes_the_hash(tmp_path):
    plain = load_pipeline_config(write_config(tmp_path, BASE)).sha256
    text = BASE + "generation: {empty_answer_notice: true}\n"
    on = load_pipeline_config(write_config(tmp_path, text))
    assert on.config.generation.empty_answer_notice is True
    assert on.sha256 != plain
