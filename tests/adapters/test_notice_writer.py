import httpx
import openai
import pytest

from qnuchat.adapters.generation.digest import request_digest
from qnuchat.adapters.generation.notice_writer import NOTICE_SYSTEM_PROMPT, VllmNoticeWriter
from qnuchat.core.errors import PipelineError
from tests.support.fakes import FakeChatApi

REQUEST = httpx.Request("POST", "http://localhost:8000/v1/chat/completions")


def writer(api, **kwargs):
    return VllmNoticeWriter(api, model="Qwen/Qwen3-4B-AWQ", seed=42, **kwargs)


def test_request_has_no_passages_and_the_fixed_limits():
    api = FakeChatApi(content="Tài liệu chưa có thông tin này.")
    out = writer(api, chat_template_kwargs={"enable_thinking": False}).write(
        "học bổng ngành Sư phạm Tiếng Anh"
    )
    sent = api.requests[0]
    assert sent["max_tokens"] == 128 and sent["temperature"] == 0 and sent["seed"] == 42
    assert sent["messages"][0] == {"role": "system", "content": NOTICE_SYSTEM_PROMPT}
    assert sent["messages"][1] == {"role": "user", "content": "học bổng ngành Sư phạm Tiếng Anh"}
    assert sent["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}
    assert "response_format" not in sent
    assert out.text == "Tài liệu chưa có thông tin này." and out.request == sent
    assert out.request_sha256 == request_digest(sent)
    assert (out.prompt_tokens, out.completion_tokens, out.finish_reason) == (1200, 80, "stop")


def test_without_chat_template_kwargs_no_extra_body_is_sent():
    api = FakeChatApi(content="Chưa có thông tin.")
    writer(api).write("q")
    assert "extra_body" not in api.requests[0]


def test_prompt_forbids_admission_facts():
    assert "Không nêu bất kỳ con số" in NOTICE_SYSTEM_PROMPT
    assert "Phòng Tuyển sinh" in NOTICE_SYSTEM_PROMPT


def test_text_is_stripped():
    assert writer(FakeChatApi(content="  Chưa có thông tin.\n")).write("q").text == (
        "Chưa có thông tin."
    )


@pytest.mark.parametrize(
    "api, cause",
    [
        (FakeChatApi(content="   "), "invalid_response"),
        (FakeChatApi(content=None), "invalid_response"),
        (FakeChatApi(content="Chưa", finish="length"), "truncated"),
        (FakeChatApi(content="Chưa", finish=None), "abnormal_finish"),
        (FakeChatApi(error=openai.APITimeoutError(request=REQUEST)), "timeout"),
        (FakeChatApi(error=openai.APIConnectionError(request=REQUEST)), "connection"),
        (
            FakeChatApi(
                error=openai.InternalServerError(
                    "boom", response=httpx.Response(500, request=REQUEST), body=None
                )
            ),
            "http_error",
        ),
    ],
)
def test_failures_are_execution_errors_at_generation(api, cause):
    with pytest.raises(PipelineError) as info:
        writer(api).write("q")
    assert (info.value.stage, info.value.cause) == ("generation", cause)
    assert info.value.details["request"] == api.requests[0]  # FakeChatApi ghi request trước khi ném


def test_failure_keeps_the_raw_response():
    with pytest.raises(PipelineError) as info:
        writer(FakeChatApi(content="Chưa", finish="length")).write("q")
    assert info.value.details["raw_response"] == "Chưa"
