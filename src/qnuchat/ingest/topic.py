"""Cổng chủ đề của crawler: chỉ đi theo và lưu mục về tuyển sinh, để không tải thừa.

Mẫu trong `topic_gate` so trên chuỗi đã bỏ dấu, nối bằng `-` (`topic_key`), nên một mẫu
`diem-chuan` khớp cả tiêu đề "Điểm chuẩn" lẫn đoạn URL. `exclude` xét cả đường dẫn và thắng mọi
luật khác; `include` chỉ xét đoạn cuối URL và tiêu đề, vì thư mục cha không nói lên chủ đề bài:
`/vi/tuyen-sinh-1763` của www là chuyên mục thông báo chung.
"""

import re
import unicodedata
from collections.abc import Mapping
from urllib.parse import unquote, urlsplit, urlunsplit

from qnuchat.ingest.config import TopicGate
from qnuchat.ingest.urls import canonicalize, is_child


def topic_key(*parts: str | None) -> str:
    text = " ".join(p for p in parts if p).replace("đ", "d").replace("Đ", "D")
    plain = "".join(c for c in unicodedata.normalize("NFD", text) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")


class TopicFilter:
    def __init__(self, gate: TopicGate | None, aliases: Mapping[str, str]):
        self.active = gate is not None
        self._include = [re.compile(p) for p in gate.include] if gate else []
        self._exclude = [re.compile(p) for p in gate.exclude] if gate else []
        trusted = gate.trusted if gate else []
        self._trusted = [u for u in (canonicalize(x, aliases=aliases) for x in trusted) if u]

    def excluded(self, url: str, *texts: str | None) -> bool:
        key = topic_key(unquote(urlsplit(url).path), *texts)
        return any(pattern.search(key) for pattern in self._exclude)

    def allows(self, url: str, *texts: str | None) -> bool:
        if not self.active:
            return True
        if self.excluded(url, *texts):
            return False
        bare = urlunsplit(urlsplit(url)._replace(query="", fragment=""))
        if any(bare.rstrip("/") == t.rstrip("/") or is_child(bare, t) for t in self._trusted):
            return True
        path = unquote(urlsplit(url).path).rstrip("/")
        if not path:  # trang chủ: tiêu đề là bài nổi bật, không phải chủ đề trang
            return False
        key = topic_key(path.rsplit("/", 1)[-1], *texts)
        return any(pattern.search(key) for pattern in self._include)
