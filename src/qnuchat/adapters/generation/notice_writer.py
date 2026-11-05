"""Viết câu báo chưa có thông tin khi model trả câu rỗng mà không từ chối (spec #17 §4).

Lần gọi thứ hai không kèm tài liệu: model chỉ thấy câu hỏi độc lập, nên không có gì để nêu số.
Mọi lỗi là execution error tại stage `generation`, không bao giờ thành abstention.
"""

import copy
from typing import Any

import openai

from qnuchat.adapters.generation.digest import request_digest
from qnuchat.core.errors import PipelineError
from qnuchat.core.ports import NoticeOutput

NOTICE_MAX_TOKENS = 128
NOTICE_SYSTEM_PROMPT = (
    "Bạn là trợ lý tuyển sinh của Trường Đại học Quy Nhơn. Tài liệu tuyển sinh hiện có không chứa "
    "thông tin để trả lời câu hỏi của người dùng. Viết 1–2 câu tiếng Việt, lịch sự: nói rằng tài "
    "liệu hiện có chưa có thông tin về điều người dùng hỏi, và mời người dùng liên hệ Phòng Tuyển "
    "sinh để được giải đáp. Không nêu bất kỳ con số, ngày tháng, điểm, học phí, chỉ tiêu, điều "
    "kiện hay thông tin tuyển sinh nào. Chỉ trả về câu đó, không thêm gì khác."
)


class VllmNoticeWriter:
    def __init__(self, api, *, model: str, seed: int, chat_template_kwargs: dict | None = None):
        self._api = api
        self._model = model
        self._seed = seed
        self._chat_template_kwargs = chat_template_kwargs

    def _request(self, question: str) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": NOTICE_SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ],
            "temperature": 0,
            "seed": self._seed,
            "max_tokens": NOTICE_MAX_TOKENS,
        }
        if self._chat_template_kwargs:
            request["extra_body"] = {"chat_template_kwargs": dict(self._chat_template_kwargs)}
        return request

    def write(self, question: str) -> NoticeOutput:
        request = self._request(question)
        details: dict[str, Any] = {"request": copy.deepcopy(request), "raw_response": None}
        try:
            response = self._api.chat.completions.create(**request)
        except openai.APITimeoutError as exc:  # phải đứng trước APIConnectionError (lớp cha)
            raise PipelineError("generation", "timeout", str(exc), details=details) from exc
        except openai.APIConnectionError as exc:
            raise PipelineError("generation", "connection", str(exc), details=details) from exc
        except openai.APIStatusError as exc:
            raise PipelineError(
                "generation", "http_error", f"{exc.status_code}: {exc}", details=details
            ) from exc
        choice = response.choices[0]
        raw = choice.message.content
        details["raw_response"] = raw
        if choice.finish_reason == "length":
            raise PipelineError("generation", "truncated", "câu báo bị cắt", details=details)
        if choice.finish_reason != "stop":
            raise PipelineError(
                "generation",
                "abnormal_finish",
                f"finish_reason={choice.finish_reason!r}",
                details=details,
            )
        text = (raw or "").strip()
        if not text:
            raise PipelineError("generation", "invalid_response", "câu báo rỗng", details=details)
        usage = getattr(response, "usage", None)
        return NoticeOutput(
            text=text,
            request=request,
            request_sha256=request_digest(request),
            raw_content=raw,
            prompt_tokens=getattr(usage, "prompt_tokens", None),
            completion_tokens=getattr(usage, "completion_tokens", None),
            finish_reason=choice.finish_reason,
        )
