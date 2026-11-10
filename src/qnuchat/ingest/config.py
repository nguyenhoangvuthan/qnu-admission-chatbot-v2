"""Cấu hình crawler: configs/crawl/qnu.yaml (spec nguồn web và trích dẫn §6.1)."""

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CONTACT_PLACEHOLDER = "{contact}"
_HOSTNAME = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)*$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Limits(_Strict):
    rps_per_host: float = Field(gt=0)
    hosts_parallel: int = Field(ge=1)
    max_file_mb: int = Field(gt=0)
    timeout_s: float = Field(gt=0)
    recheck_days: int = Field(default=30, ge=1)
    max_listing_pages: int = Field(default=200, ge=1)
    retries: int = Field(default=2, ge=0)


class TopicGate(_Strict):
    """Luật đi theo link và lưu trang: xem `qnuchat.ingest.topic`."""

    include: list[str] = Field(min_length=1)
    exclude: list[str] = Field(default_factory=list)
    trusted: list[str] = Field(default_factory=list)  # chuyên mục tuyển sinh: bài con luôn qua

    @field_validator("include", "exclude")
    @classmethod
    def _regexes_compile(cls, patterns: list[str]) -> list[str]:
        for pattern in patterns:
            try:
                re.compile(pattern)
            except re.error as err:
                raise ValueError(f"regex không hợp lệ {pattern!r}: {err}") from err
        return patterns


class CrawlConfig(_Strict):
    seeds: list[str] = Field(min_length=1)
    host_suffix: str = Field(pattern=r"^\.[a-z0-9-]+(\.[a-z0-9-]+)+$")
    host_aliases: dict[str, str] = Field(default_factory=dict)
    blocklist_hosts: list[str] = Field(default_factory=list)
    blocklist_url_patterns: list[str] = Field(default_factory=list)
    tier_a: list[str] = Field(min_length=1)
    pii_title_skip: list[str] = Field(default_factory=list)
    limits: Limits
    user_agent: str = Field(min_length=1)
    # Chỉ giữ trang/tài liệu từ năm này trở đi (spec §6.5); None = không lọc theo năm.
    min_year: int | None = Field(default=None, ge=2000)
    topic_gate: TopicGate | None = None  # None = đi theo mọi link trong phạm vi
    # File trong phần nội dung chính của trang con thuộc các URL này luôn tải, không xét `min_year`,
    # `blocklist_url_patterns` hay `topic_gate.exclude`; `prune` cũng không rút (PDF CTĐT trên trang
    # ngành, Kent 10/11/2026). Robots, host, tiêu đề và nội dung có thông tin người vẫn chặn.
    attachments_always_from: list[str] = Field(default_factory=list)

    @field_validator("blocklist_url_patterns", "pii_title_skip")
    @classmethod
    def _regexes_compile(cls, patterns: list[str]) -> list[str]:
        for pattern in patterns:
            try:
                re.compile(pattern)
            except re.error as err:  # pydantic chỉ đổi ValueError thành ValidationError
                raise ValueError(f"regex không hợp lệ {pattern!r}: {err}") from err
        return patterns

    @field_validator("blocklist_hosts")
    @classmethod
    def _hostnames(cls, hosts: list[str]) -> list[str]:
        for host in hosts:
            if not _HOSTNAME.fullmatch(host):
                raise ValueError(f"hostname không hợp lệ {host!r}")
        return hosts

    @field_validator("host_aliases")
    @classmethod
    def _alias_hostnames(cls, aliases: dict[str, str]) -> dict[str, str]:
        for key, value in aliases.items():
            for host in (key, value):
                if not _HOSTNAME.fullmatch(host):
                    raise ValueError(f"hostname không hợp lệ {host!r}")
        return aliases

    @model_validator(mode="after")
    def _urls_in_suffix(self) -> "CrawlConfig":
        bare = self.host_suffix.lstrip(".")
        for name in ("seeds", "tier_a"):
            for url in getattr(self, name):
                parts = urlsplit(url)
                host = (parts.hostname or "").lower()
                if parts.scheme not in ("http", "https") or not (
                    host == bare or host.endswith(self.host_suffix)
                ):
                    raise ValueError(
                        f"{name}: {url!r} phải là URL http(s) thuộc {self.host_suffix}"
                    )
        return self

    @field_validator("user_agent")
    @classmethod
    def _has_contact(cls, value: str) -> str:
        if CONTACT_PLACEHOLDER not in value:
            raise ValueError(
                f"user_agent phải chứa {CONTACT_PLACEHOLDER} (email liên hệ, lấy từ môi trường)"
            )
        return value

    def user_agent_for(self, contact: str) -> str:
        """User-Agent gửi đi: email liên hệ là thông tin cá nhân nên không nằm trong file commit."""
        if not contact.strip():
            raise ValueError("Đặt QNUCHAT_CRAWL_CONTACT_EMAIL: site trường cần biết ai đang quét")
        return self.user_agent.replace(CONTACT_PLACEHOLDER, contact.strip())


def load_crawl_config(path: str | Path) -> tuple[CrawlConfig, str]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    cfg = CrawlConfig.model_validate(raw)
    canonical = json.dumps(
        cfg.model_dump(mode="json"), sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return cfg, hashlib.sha256(canonical.encode("utf-8")).hexdigest()
