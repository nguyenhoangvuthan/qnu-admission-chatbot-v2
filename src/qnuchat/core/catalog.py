"""Danh mục ngành/năm/chủ đề do người duyệt (spec chat nhiều lượt §3).

Stage `query_rewrite` chỉ dựa vào file này để hiểu câu hỏi; bổ sung dữ liệu (mã ngành, học phí,
phương thức…) là sửa file này, không sửa code.
"""

import hashlib
import json
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from qnuchat.core.text import fold

MAX_SUGGESTED = 6


class CatalogError(ValueError):
    """Danh mục thiếu, hỏng hoặc mâu thuẫn: app từ chối khởi động như cấu hình sai."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Major(_Strict):
    id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    name: str = Field(min_length=1)  # tên chuẩn — phải xuất hiện trong corpus (test)
    aliases: list[str] = Field(default_factory=list)
    code: str | None = None  # mã ngành; None khi dữ liệu chưa có
    specializations: list[str] = Field(default_factory=list)
    programs: list[str] = Field(default_factory=list)  # chất lượng cao, …
    pages: list[int] = Field(min_length=1)  # trang nguồn trong corpus


class CatalogSlots(_Strict):
    """Loại thông tin khác ngành/năm. Danh sách rỗng = dữ liệu chưa có → không bao giờ hỏi."""

    admission_method: list[str] = Field(default_factory=list)
    training_mode: list[str] = Field(default_factory=list)
    round: list[str] = Field(default_factory=list)
    subject_group: list[str] = Field(default_factory=list)
    priority: list[str] = Field(default_factory=list)


class Catalog(_Strict):
    version: int = Field(ge=1)
    years: list[int] = Field(min_length=1)  # > 1 năm thì câu cần ngành mà thiếu năm phải hỏi
    majors: list[Major] = Field(min_length=1)
    suggested: list[str] = Field(default_factory=list, max_length=MAX_SUGGESTED)
    major_topics: list[str] = Field(default_factory=list)
    school_topics: list[str] = Field(default_factory=list)
    slots: CatalogSlots = Field(default_factory=CatalogSlots)

    @model_validator(mode="after")
    def _consistent(self) -> "Catalog":
        ids = [m.id for m in self.majors]
        if dup := sorted({i for i in ids if ids.count(i) > 1}):
            raise ValueError(f"id ngành trùng: {dup}")
        if len(set(self.years)) != len(self.years):
            raise ValueError(f"năm trùng trong years: {self.years}")
        owners: dict[str, str] = {}
        for major in self.majors:
            key = fold(major.name)
            if not key:
                raise ValueError(f"{major.id}: tên chuẩn rỗng sau chuẩn hoá: {major.name!r}")
            if key in owners:
                raise ValueError(f"tên chuẩn trùng (sau chuẩn hoá): {major.id} và {owners[key]}")
            owners[key] = major.id
        for major in self.majors:
            for term in (*major.aliases, *([major.code] if major.code else [])):
                key = fold(term)
                if not key:
                    raise ValueError(f"{major.id}: alias/mã rỗng sau chuẩn hoá: {term!r}")
                owner = owners.get(key)
                if owner is not None and owner != major.id:
                    raise ValueError(f"{major.id}: alias {term!r} trùng tên chuẩn của {owner}")
        if unknown := [s for s in self.suggested if s not in ids]:
            raise ValueError(f"suggested trỏ tới id không có: {unknown}")
        for topic in (*self.major_topics, *self.school_topics):
            if not fold(topic):
                raise ValueError(f"chủ đề rỗng sau chuẩn hoá: {topic!r}")
        return self


def load_catalog(path: Path) -> tuple[Catalog, str]:
    """Nạp + kiểm danh mục. Hash theo nội dung đã validate (comment/định dạng YAML không tính)."""
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise CatalogError(f"không đọc được danh mục {path}: {exc}") from exc
    try:
        catalog = Catalog.model_validate(raw)
    except ValidationError as exc:
        raise CatalogError(f"danh mục {path} sai: {exc}") from exc
    canonical = json.dumps(
        catalog.model_dump(mode="json"), sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return catalog, hashlib.sha256(canonical.encode("utf-8")).hexdigest()
