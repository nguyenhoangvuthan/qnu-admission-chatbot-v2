"""Gọi Qwen3-4B qua vLLM để phân loại một mục của kho web (spec knowledge base §5.1).

Lỗi hạ tầng hoặc JSON không khớp schema được thử lại đúng một lần; vẫn lỗi thì là execution error
(`TopicExecutionError`) — không bao giờ thành `loai`, vì `loai` dẫn tới xoá.
"""

import json
from dataclasses import dataclass
from typing import Any

import openai

from qnuchat.ingest.topic_filter.inputs import TopicInput
from qnuchat.ingest.topic_filter.ledger import Label

LABELS = ("giu", "loai", "khong_chac")
GROUPS = ("tuyen_sinh", "hoc_phi_ktx_hoc_bong", "nganh_ctdt", None)
REASONS = ("sau_dai_hoc", "vlvh_tu_xa_lien_thong", "khoa_ngan_han", "khong_lien_quan", None)
TOPIC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "label": {"type": "string", "enum": list(LABELS)},
        "group": {"type": ["string", "null"], "enum": list(GROUPS)},
        "reason": {"type": ["string", "null"], "enum": list(REASONS)},
        "note": {"type": "string"},
    },
    "required": ["label", "group", "reason", "note"],
    "additionalProperties": False,
}
_NO_CONTENT = "Nội dung: (không có — file chưa có lớp chữ hoặc ảnh)"


class TopicExecutionError(Exception):
    def __init__(self, cause: str, message: str = ""):
        super().__init__(f"{cause}: {message}" if message else cause)
        self.cause = cause


@dataclass(frozen=True)
class TopicVerdict:
    label: Label
    group: str | None
    reason: str | None
    note: str


def render_input(inp: TopicInput) -> str:
    lines = [f"Loại mục: {inp.kind}", f"URL: {inp.url}", f"Host: {inp.host}"]
    if inp.title:
        lines.append(f"Tiêu đề: {inp.title}")
    if inp.file_name:
        lines.append(f"Tên file: {inp.file_name}")
    if inp.page_url:
        lines.append(f"Trang chứa: {inp.page_title or '(không rõ tiêu đề)'} — {inp.page_url}")
    if inp.link_text:
        lines.append(f"Chữ của đường link: {inp.link_text}")
    lines.append(f"Nội dung (1.500 ký tự đầu):\n{inp.text}" if inp.text else _NO_CONTENT)
    return "\n".join(lines)


def _verdict(raw: str | None) -> TopicVerdict:
    try:
        data = json.loads(raw or "")
    except json.JSONDecodeError as exc:
        raise TopicExecutionError("invalid_response", "JSON hỏng") from exc
    if (
        not isinstance(data, dict)
        or set(data) != {"label", "group", "reason", "note"}
        or data["label"] not in LABELS
        or data["group"] not in GROUPS
        or data["reason"] not in REASONS
        or not isinstance(data["note"], str)
    ):
        raise TopicExecutionError("invalid_response", f"không khớp schema: {raw!r}")
    return TopicVerdict(data["label"], data["group"], data["reason"], data["note"])


class VllmTopicClassifier:
    def __init__(
        self,
        api,
        *,
        model: str,
        seed: int,
        max_tokens: int,
        chat_template_kwargs: dict | None,
        prompt: str,
    ):
        self._api = api
        self._model = model
        self._seed = seed
        self._max_tokens = max_tokens
        self._chat_template_kwargs = chat_template_kwargs
        self._prompt = prompt

    def _request(self, inp: TopicInput) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": self._prompt},
                {"role": "user", "content": render_input(inp)},
            ],
            "temperature": 0,
            "seed": self._seed,
            "max_tokens": self._max_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "topic", "schema": TOPIC_SCHEMA},
            },
        }
        if self._chat_template_kwargs:
            request["extra_body"] = {"chat_template_kwargs": dict(self._chat_template_kwargs)}
        return request

    def _once(self, request: dict[str, Any]) -> TopicVerdict:
        try:
            response = self._api.chat.completions.create(**request)
        except openai.APITimeoutError as exc:  # phải đứng trước APIConnectionError (lớp cha)
            raise TopicExecutionError("timeout", str(exc)) from exc
        except openai.APIConnectionError as exc:
            raise TopicExecutionError("connection", str(exc)) from exc
        except openai.APIStatusError as exc:
            raise TopicExecutionError("http_error", str(exc.status_code)) from exc
        choice = response.choices[0]
        if choice.finish_reason == "length":
            raise TopicExecutionError("truncated")
        if choice.finish_reason != "stop":
            raise TopicExecutionError("abnormal_finish", repr(choice.finish_reason))
        return _verdict(choice.message.content)

    def classify(self, inp: TopicInput) -> TopicVerdict:
        request = self._request(inp)
        try:
            return self._once(request)
        except TopicExecutionError:
            return self._once(request)  # thử lại đúng một lần (§5.1)
