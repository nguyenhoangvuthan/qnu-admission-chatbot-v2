"""Nạp cấu hình pipeline: `extends` một tầng, khoá lạ là lỗi, hash theo nội dung đã hợp lệ.

Chỉ chứa thứ có thể đổi câu trả lời. Thứ đổi theo máy (URL vLLM, thiết bị embedding…) không vào
hash.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from qnuchat.core.catalog import Catalog, CatalogError, load_catalog

_COMMIT_HASH = r"^[0-9a-fA-F]{40}$"


class ConfigError(ValueError):
    """Cấu hình sai: khoá lạ, sai kiểu, vi phạm ràng buộc liên thành phần."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RetrievalConfig(_Strict):
    mode: Literal["hybrid"]
    top_k: int = Field(gt=0)
    rrf_k: int = Field(gt=0)


class SourceConfig(_Strict):
    source_id: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    path: str
    excluded_pages: list[int] = Field(default_factory=list)
    source_year: int | None = None


class CorpusConfig(_Strict):
    sources: list[SourceConfig] = Field(min_length=1)
    max_chunk_chars: int = Field(gt=0)

    @model_validator(mode="after")
    def _unique_source_ids(self) -> "CorpusConfig":
        ids = [s.source_id for s in self.sources]
        if dup := sorted({i for i in ids if ids.count(i) > 1}):
            raise ValueError(f"source_id trùng: {dup}")
        return self


class EmbeddingConfig(_Strict):
    model: str
    revision: str = Field(pattern=_COMMIT_HASH)


class GeneratorConfig(_Strict):
    model: str
    revision: str = Field(pattern=_COMMIT_HASH)
    quantization: str
    max_tokens: int = Field(gt=0)
    temperature: float = 0.0
    seed: int
    chat_template_kwargs: dict[str, Any] | None = None

    @field_validator("temperature")
    @classmethod
    def _greedy_only(cls, value: float) -> float:
        if value != 0:
            raise ValueError("temperature phải bằng 0 (generator tất định như pilot)")
        return value


class HistoryConfig(_Strict):
    max_turns: int = Field(ge=0)


class QueryRewriteConfig(_Strict):
    enabled: bool = False
    # Đường dẫn danh mục, tương đối với thư mục của file cấu hình được nạp.
    catalog: str | None = None

    @model_validator(mode="after")
    def _catalog_when_enabled(self) -> "QueryRewriteConfig":
        if self.enabled and self.catalog is None:
            raise ValueError("stages.query_rewrite.enabled=true cần stages.query_rewrite.catalog")
        return self


class StagesConfig(_Strict):
    query_rewrite: QueryRewriteConfig = Field(default_factory=QueryRewriteConfig)


class GenerationConfig(_Strict):
    # Câu trả lời rỗng mà không từ chối → gọi model lần hai viết câu báo chưa có thông tin, lượt
    # ghi từ chối EMPTY_ANSWER. Chỉ cấu hình chat bật.
    empty_answer_notice: bool = False


class PipelineConfig(_Strict):
    retrieval: RetrievalConfig
    corpus: CorpusConfig
    embedding: EmbeddingConfig
    generator: GeneratorConfig
    history: HistoryConfig
    stages: StagesConfig = Field(default_factory=StagesConfig)
    generation: GenerationConfig = Field(default_factory=GenerationConfig)


@dataclass(frozen=True)
class LoadedConfig:
    config: PipelineConfig
    name: str  # tên file không đuôi
    sha256: str  # hash của cấu hình ĐÃ hợp nhất và hợp lệ
    catalog: Catalog | None = None  # danh mục đã nạp; None khi cấu hình không khai


def _read(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: gốc của file phải là một mapping")
    return data


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Mapping gộp theo khoá; mọi thứ khác (list, số, chuỗi) được thay toàn bộ."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_pipeline_config(path: str | Path) -> LoadedConfig:
    path = Path(path)
    raw = _read(path)
    parent = raw.pop("extends", None)
    if parent is not None:
        base = _read(path.parent / parent)
        if "extends" in base:
            raise ConfigError(f"{path}: extends chỉ được một tầng ({parent} cũng có extends)")
        raw = _merge(base, raw)
    try:
        config = PipelineConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    payload = config.model_dump(mode="json")
    catalog: Catalog | None = None
    if config.stages.query_rewrite.catalog is not None:
        catalog_path = path.parent / config.stages.query_rewrite.catalog
        try:
            catalog, catalog_sha = load_catalog(catalog_path)
        except CatalogError as exc:
            raise ConfigError(f"{path}: {exc}") from exc
        # Nội dung danh mục đổi câu trả lời nên vào hash; trace/replay biết bản nào đã dùng.
        payload["catalog_sha256"] = catalog_sha
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return LoadedConfig(config=config, name=path.stem, sha256=digest, catalog=catalog)
