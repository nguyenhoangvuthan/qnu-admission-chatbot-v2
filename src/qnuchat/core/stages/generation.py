"""Gọi generator và ghi lại request/usage. Trích dẫn ngoài top-k được ghi, không lặng lẽ bỏ."""

from typing import Any

from qnuchat.core.errors import PipelineError
from qnuchat.core.ports import Generator, NoticeWriter
from qnuchat.core.stages.base import RunState


class GenerationStage:
    name = "generation"
    enabled = True
    note = ""

    def __init__(
        self,
        generator: Generator,
        *,
        revision: str,
        runtime_info: dict[str, Any],
        notice_writer: NoticeWriter | None = None,
    ):
        self._generator = generator
        self._revision = revision
        self._runtime_info = dict(runtime_info)
        # None = cờ generation.empty_answer_notice tắt: câu rỗng giữ nguyên như arm thí nghiệm.
        self._notice_writer = notice_writer

    def run(self, state: RunState) -> dict[str, Any]:
        # search_text = query.text khi query_rewrite tắt (arm thí nghiệm không đổi); bật thì là câu
        # độc lập đã ghép ngành/năm — không đổi thì LLM chỉ thấy "Còn học phí?" (quyết định M9).
        output = self._generator.generate(state.search_text, state.passages)
        state.generated = output
        known = {p.chunk_id for p in state.passages}
        data: dict[str, Any] = {
            "model": output.model,
            "revision": self._revision,
            "request_sha256": output.request_sha256,
            "prompt_tokens": output.prompt_tokens,
            "completion_tokens": output.completion_tokens,
            "finish_reason": output.finish_reason,
            # Model trích id không có trong top-k = dấu hiệu bịa trích dẫn.
            "unknown_citations": [c for c in output.citation_ids if c not in known],
            "runtime": self._runtime_info,
            "request": output.request,
            "raw_response": output.raw_content,
        }
        if self._notice_writer is not None and not output.abstain and not output.answer.strip():
            try:
                notice = self._notice_writer.write(state.search_text)
            except PipelineError as exc:
                # Trace lỗi giữ cả request/phản hồi thô của lần sinh chính lẫn lần viết câu báo.
                exc.details = {**data, "empty_answer_notice": exc.details}
                raise
            state.notice = notice.text
            data["empty_answer_notice"] = {
                "request": notice.request,
                "raw_response": notice.raw_content,
                "request_sha256": notice.request_sha256,
                "prompt_tokens": notice.prompt_tokens,
                "completion_tokens": notice.completion_tokens,
                "finish_reason": notice.finish_reason,
            }
        return data
