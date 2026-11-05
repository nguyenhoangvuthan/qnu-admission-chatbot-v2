"""Giao diện stage. Pipeline lo trạng thái và thời gian; stage chỉ trả `data`."""

from dataclasses import dataclass, field
from typing import Any, Protocol

from qnuchat.core.contracts import Clarification, Query
from qnuchat.core.ports import GeneratorOutput, RetrievalResult
from qnuchat.documents import Passage


@dataclass
class RunState:
    """Trạng thái một lần chạy, các stage đọc/ghi lần lượt."""

    query: Query
    search_text: str
    retrieval: RetrievalResult | None = None
    passages: list[Passage] = field(default_factory=list)
    generated: GeneratorOutput | None = None
    # query_rewrite đặt khi cần hỏi lại; các stage sau không chạy.
    clarification: Clarification | None = None
    # Câu báo chưa có thông tin khi model trả câu rỗng; có thì Answer là từ chối.
    notice: str | None = None


class Stage(Protocol):
    name: str
    enabled: bool
    note: str  # lý do ngắn, ghi vào trace khi stage tắt

    def run(self, state: RunState) -> dict[str, Any]: ...
