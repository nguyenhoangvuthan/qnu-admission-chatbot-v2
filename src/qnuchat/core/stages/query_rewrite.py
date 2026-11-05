"""Hiểu câu hỏi nối tiếp theo danh mục. Tắt ở mọi arm không đo viết lại câu."""

from typing import Any

from qnuchat.core.catalog import Catalog
from qnuchat.core.rewrite import CatalogMatcher, rewrite
from qnuchat.core.stages.base import RunState


class QueryRewriteStage:
    name = "query_rewrite"
    note = "chat một lượt: history không dùng để viết lại câu hỏi"

    def __init__(self, enabled: bool = False, catalog: Catalog | None = None):
        if enabled and catalog is None:
            raise ValueError("query_rewrite bật thì phải có danh mục")
        self.enabled = enabled
        self._matcher = CatalogMatcher(catalog) if catalog is not None else None

    def run(self, state: RunState) -> dict[str, Any]:
        assert self._matcher is not None, "pipeline chỉ gọi stage đang bật"
        result = rewrite(state.query, self._matcher)
        if result.clarification is not None:
            state.clarification = result.clarification
        else:
            assert result.standalone is not None
            state.search_text = result.standalone
        return result.trace_data(self._matcher)
