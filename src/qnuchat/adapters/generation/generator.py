"""Gọi generator qua giao thức OpenAI-compatible, phân loại lỗi thành execution error.

Lỗi ở đây KHÔNG được biến thành abstention: abstention là một kết quả được chấm điểm, nên biến sự
cố hạ tầng thành abstention sẽ làm hỏng metric từ chối và risk-coverage curve.
"""

import copy
import json
from collections.abc import Sequence
from typing import Any

import openai
from pydantic import ValidationError

from qnuchat.adapters.generation.digest import request_digest
from qnuchat.adapters.generation.prompts import SYSTEM_PROMPT, build_user_prompt
from qnuchat.adapters.generation.schema import RESPONSE_FORMAT, ModelAnswer
from qnuchat.core.contracts import Claim
from qnuchat.core.errors import PipelineError
from qnuchat.core.ports import GeneratorOutput
from qnuchat.documents import Passage

_TRUNCATED = {"length", "content_filter"}


class VllmGenerator:
    def __init__(
        self,
        api,
        *,
        model: str,
        max_tokens: int,
        seed: int,
        chat_template_kwargs: dict | None = None,
    ):
        self._api = api
        self._model = model
        self._max_tokens = max_tokens
        self._seed = seed
        self._chat_template_kwargs = dict(chat_template_kwargs) if chat_template_kwargs else None

    def request_kwargs(self, question: str, passages: Sequence[Passage]) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(question, passages)},
            ],
            "temperature": 0,
            "seed": self._seed,
            "max_tokens": self._max_tokens,
            "response_format": RESPONSE_FORMAT,
        }
        if self._chat_template_kwargs:
            # vLLM đọc chat_template_kwargs ở cấp request (extra_body); tắt thinking của
            # Qwen3 ở đây thay vì dựa vào cờ --default-chat-template-kwargs của server.
            kwargs["extra_body"] = {"chat_template_kwargs": dict(self._chat_template_kwargs)}
        return kwargs

    def generate(self, question: str, passages: Sequence[Passage]) -> GeneratorOutput:
        # Bản sao sâu: request trong trace không dùng chung đối tượng với hằng module
        # (RESPONSE_FORMAT) nên không ai sửa nhầm hằng đó qua trace.
        request = copy.deepcopy(self.request_kwargs(question, passages))
        # Lỗi nào cũng mang request đã gửi (và phản hồi thô nếu có): trace dở dang vẫn tái hiện
        # được lượt gọi LLM.
        details: dict[str, Any] = {"request": request, "raw_response": None}

        def fail(cause: str, message: str, raw: str | None = None) -> PipelineError:
            details["raw_response"] = raw
            return PipelineError("generation", cause, message, details=details)

        try:
            response = self._api.chat.completions.create(**request)
        except openai.APITimeoutError as exc:  # phải đứng trước APIConnectionError (lớp cha)
            raise fail("timeout", str(exc)) from exc
        except openai.APIConnectionError as exc:
            raise fail("connection", str(exc)) from exc
        except openai.APIStatusError as exc:
            raise fail("http_error", f"{exc.status_code}: {exc}") from exc

        if not response.choices:
            raise fail("invalid_response", "Response has no choices.")
        choice = response.choices[0]
        content = choice.message.content
        finish_reason = getattr(choice, "finish_reason", None)
        if finish_reason in _TRUNCATED:
            raise fail("truncated", f"Response did not finish normally: {finish_reason}", content)
        if content is None:
            raise fail("invalid_response", "Response content is None.")
        try:
            answer = ModelAnswer.model_validate(json.loads(content))
        except json.JSONDecodeError as exc:
            raise fail("invalid_response", "Response content is not valid JSON.", content) from exc
        except ValidationError as exc:
            raise fail(
                "invalid_response", "Response JSON does not match Answer schema.", content
            ) from exc
        if finish_reason != "stop":
            # JSON hợp lệ nhưng kết thúc bất thường (None, "abort", …) vẫn là lỗi hạ tầng.
            raise fail("abnormal_finish", f"finish_reason={finish_reason!r}", content)

        usage = getattr(response, "usage", None)
        return GeneratorOutput(
            answer=answer.answer,
            abstain=answer.abstain,
            abstain_reason=answer.abstain_reason,
            claims=[Claim(**claim.model_dump()) for claim in answer.claims],
            citation_ids=list(answer.citation_ids),
            confidence=answer.confidence,
            request_sha256=request_digest(request),
            model=self._model,
            prompt_tokens=getattr(usage, "prompt_tokens", None),
            completion_tokens=getattr(usage, "completion_tokens", None),
            finish_reason=finish_reason,
            raw_content=content,
            request=request,
        )
