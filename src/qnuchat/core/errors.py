"""Lỗi hạ tầng của pipeline. KHÔNG bao giờ được biến thành Answer hay abstention."""

from typing import Any

from qnuchat.core.contracts import Trace


class PipelineError(RuntimeError):
    """Execution error: timeout, mất kết nối, JSON hỏng, finish_reason bất thường, lỗi retrieval.

    `partial_trace` là trace của những gì đã chạy tới lúc lỗi; pipeline gắn vào trước khi ném.
    `details` là dữ liệu stage lỗi muốn giữ trong trace dở dang (vd. request đã gửi LLM).
    """

    def __init__(
        self,
        stage: str,
        cause: str,
        message: str,
        partial_trace: Trace | None = None,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(f"[{stage}/{cause}] {message}")
        self.stage = stage
        self.cause = cause
        self.message = message
        self.partial_trace = partial_trace
        self.details = dict(details or {})
