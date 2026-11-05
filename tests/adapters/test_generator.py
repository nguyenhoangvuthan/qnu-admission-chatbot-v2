import json
from types import SimpleNamespace

import httpx
import openai
import pytest

from experiments.prepare_gold import digest
from qnuchat.adapters.generation.generator import VllmGenerator
from qnuchat.adapters.generation.prompts import SYSTEM_PROMPT, build_user_prompt
from qnuchat.adapters.generation.schema import ANSWER_JSON_SCHEMA, RESPONSE_FORMAT
from qnuchat.core.errors import PipelineError
from qnuchat.documents import Passage
from tests.support.fakes import FakeChatApi

PAYLOAD = {
    "abstain": False,
    "answer": "Học phí là 15 triệu.",
    "claims": [
        {
            "subject": "ngành CNTT",
            "predicate": "học phí",
            "value": "15",
            "unit": "triệu đồng",
            "admission_year": 2025,
        }
    ],
    "citation_ids": ["p004"],
    "confidence": 0.8,
    "abstain_reason": None,
}
REQUEST = httpx.Request("POST", "http://localhost:8000/v1/chat/completions")


def FakeApi(content=None, **kwargs):
    """FakeChatApi trả mặc định PAYLOAD hợp lệ."""
    return FakeChatApi(
        json.dumps(PAYLOAD, ensure_ascii=False) if content is None else content, **kwargs
    )


def generator(api, **kwargs):
    return VllmGenerator(api, model="Qwen/Qwen3-4B-AWQ", max_tokens=1024, seed=42, **kwargs)


PASSAGES = [Passage("p004", "cam-nang-2025", 4, "Học phí ngành CNTT là 15 triệu", 2025)]


def test_generator_maps_answer_usage_and_request_hash():
    api = FakeApi()
    out = generator(api).generate("Học phí?", PASSAGES)
    assert out.answer == "Học phí là 15 triệu." and out.abstain is False
    assert out.citation_ids == ["p004"] and out.confidence == pytest.approx(0.8)
    assert out.claims[0].value == "15"
    assert (out.prompt_tokens, out.completion_tokens, out.finish_reason) == (1200, 80, "stop")
    assert out.model == "Qwen/Qwen3-4B-AWQ" and out.raw_content == api.content
    assert out.request_sha256 == digest(api.requests[0])


def test_generator_sends_passages_in_the_prompt():
    api = FakeApi()
    generator(api).generate("Học phí?", PASSAGES)
    user = api.requests[0]["messages"][1]["content"]
    assert "[p004]" in user and "năm nguồn: 2025" in user
    assert "Học phí ngành CNTT là 15 triệu" in user


def test_generator_sends_chat_template_kwargs_in_the_request():
    api = FakeApi()
    generator(api, chat_template_kwargs={"enable_thinking": False}).generate("q", PASSAGES)
    assert api.requests[0]["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}


def test_generator_without_chat_template_kwargs_sends_no_extra_body():
    api = FakeApi()
    generator(api).generate("q", PASSAGES)
    assert "extra_body" not in api.requests[0]


@pytest.mark.parametrize(
    ("api", "cause"),
    [
        (FakeApi(content='{"abstain": tr', finish="length"), "truncated"),
        (FakeApi(content="{}", finish="content_filter"), "truncated"),
        (FakeApi(content="không phải json"), "invalid_response"),
        (FakeApi(content='{"abstain": true}'), "invalid_response"),
        (FakeApi(finish=None), "abnormal_finish"),
        (FakeApi(finish="abort"), "abnormal_finish"),
        (FakeApi(finish="tool_calls"), "abnormal_finish"),
        (FakeApi(error=openai.APITimeoutError(request=REQUEST)), "timeout"),
        (FakeApi(error=openai.APIConnectionError(request=REQUEST)), "connection"),
        (
            FakeApi(
                error=openai.InternalServerError(
                    "boom", response=httpx.Response(500, request=REQUEST), body=None
                )
            ),
            "http_error",
        ),
    ],
)
def test_generator_maps_infrastructure_failures_to_pipeline_error(api, cause):
    with pytest.raises(PipelineError) as info:
        generator(api).generate("q", PASSAGES)
    assert (info.value.stage, info.value.cause) == ("generation", cause)


def test_http_error_message_carries_the_status_code():
    api = FakeApi(
        error=openai.InternalServerError(
            "boom", response=httpx.Response(500, request=REQUEST), body=None
        )
    )
    with pytest.raises(PipelineError, match="500"):
        generator(api).generate("q", PASSAGES)


def test_output_request_is_exactly_the_kwargs_sent_to_the_api():
    api = FakeApi()
    out = generator(api).generate("Học phí ngành CNTT?", PASSAGES)
    assert out.request == api.requests[0]
    assert out.request["messages"][1]["content"].count("Học phí ngành CNTT?") == 1
    assert out.raw_content is not None


def test_output_request_does_not_alias_module_constants():
    out = generator(FakeApi()).generate("q", PASSAGES)
    out.request["response_format"]["json_schema"]["name"] = "đã bị sửa"
    again = generator(FakeApi()).generate("q", PASSAGES)
    assert again.request["response_format"]["json_schema"]["name"] != "đã bị sửa"


def test_request_and_raw_response_survive_an_invalid_response():
    api = FakeApi(content="{không phải json")
    with pytest.raises(PipelineError) as caught:
        generator(api).generate("q", PASSAGES)
    assert caught.value.cause == "invalid_response"
    assert caught.value.details["request"] == api.requests[0]
    assert caught.value.details["raw_response"] == "{không phải json"


def test_request_and_raw_response_survive_a_truncated_response():
    api = FakeApi(content='{"abstain": tr', finish="length")
    with pytest.raises(PipelineError) as caught:
        generator(api).generate("q", PASSAGES)
    assert caught.value.cause == "truncated"
    assert caught.value.details["request"] == api.requests[0]
    assert caught.value.details["raw_response"] == '{"abstain": tr'


def test_request_and_raw_response_survive_an_abnormal_finish():
    api = FakeApi(finish="abort")
    with pytest.raises(PipelineError) as caught:
        generator(api).generate("q", PASSAGES)
    assert caught.value.cause == "abnormal_finish"
    assert caught.value.details["request"] == api.requests[0]
    assert caught.value.details["raw_response"] == api.content


def test_request_survives_a_timeout():
    api = FakeApi(error=openai.APITimeoutError(request=REQUEST))
    with pytest.raises(PipelineError) as caught:
        generator(api).generate("q", PASSAGES)
    assert caught.value.cause == "timeout"
    assert caught.value.details["request"]["messages"][1]["role"] == "user"
    assert caught.value.details["request"] == api.requests[0]
    assert caught.value.details["raw_response"] is None


@pytest.mark.parametrize(
    ("error", "cause"),
    [
        (openai.APIConnectionError(request=REQUEST), "connection"),
        (
            openai.InternalServerError(
                "boom", response=httpx.Response(500, request=REQUEST), body=None
            ),
            "http_error",
        ),
    ],
)
def test_request_survives_connection_and_http_errors(error, cause):
    api = FakeApi(error=error)
    with pytest.raises(PipelineError) as caught:
        generator(api).generate("q", PASSAGES)
    assert caught.value.cause == cause
    assert caught.value.details == {"request": api.requests[0], "raw_response": None}


def test_schema_rejects_additional_properties():
    assert ANSWER_JSON_SCHEMA["additionalProperties"] is False
    assert ANSWER_JSON_SCHEMA["properties"]["claims"]["items"]["additionalProperties"] is False
    assert "confidence" in ANSWER_JSON_SCHEMA["required"]


def test_generator_pins_temperature_zero_seed_and_token_budget():
    api = FakeApi()
    generator(api).generate("q", [])
    sent = api.requests[0]
    assert (sent["temperature"], sent["seed"], sent["max_tokens"]) == (0, 42, 1024)


def test_generator_constrains_decoding_with_the_answer_schema():
    api = FakeApi()
    generator(api).generate("q", [])
    assert api.requests[0]["response_format"] == RESPONSE_FORMAT


def test_generator_sends_no_deprecated_guided_parameters():
    """vLLM đã bỏ họ `guided_*`; gửi chúng đi là mất ràng buộc schema trong im lặng.

    Client giả không thể phát hiện việc server bỏ qua một tham số lạ, nên test
    này chốt ở phía client: KHÔNG được có tham số nào thuộc họ đã bị loại bỏ.
    """
    api = FakeApi()
    generator(api).generate("q", [])
    sent = {**api.requests[0], **(api.requests[0].get("extra_body") or {})}
    assert not [key for key in sent if key.startswith("guided_")]


def test_empty_context_yields_prompt_without_evidence_block():
    assert "KHÔNG CÓ TÀI LIỆU" in build_user_prompt("Học phí?", [])


def test_prompt_labels_passages_by_chunk_id_and_exposes_source_year():
    prompt = build_user_prompt("q", PASSAGES)
    assert "[p004] (năm nguồn: 2025)" in prompt
    no_year = build_user_prompt("q", [Passage("p005", "s", 5, "nội dung")])
    assert "[p005]\nnội dung" in no_year


def test_passages_reach_the_outgoing_prompt():
    """Nếu context không vào messages thì mọi arm giống hệt nhau dưới góc nhìn của model."""
    api = FakeApi()
    generator(api).generate("Điểm chuẩn?", PASSAGES)
    messages = api.requests[0]["messages"]
    assert messages[0]["content"] == SYSTEM_PROMPT
    assert messages[1]["content"] == build_user_prompt("Điểm chuẩn?", PASSAGES)


def test_chat_template_kwargs_are_copied_not_shared():
    source = {"enable_thinking": False}
    instance = generator(FakeApi(), chat_template_kwargs=source)
    source["enable_thinking"] = True
    assert instance.request_kwargs("q", [])["extra_body"]["chat_template_kwargs"] == {
        "enable_thinking": False
    }


def test_valid_json_cut_off_by_the_token_limit_is_still_an_error():
    api = FakeApi(finish="length")
    with pytest.raises(PipelineError) as caught:
        generator(api).generate("q", [])
    assert caught.value.cause == "truncated"
    assert "length" in caught.value.message


def test_missing_required_field_is_an_invalid_response():
    incomplete = {k: v for k, v in PAYLOAD.items() if k != "confidence"}
    with pytest.raises(PipelineError) as caught:
        generator(FakeApi(json.dumps(incomplete))).generate("q", [])
    assert caught.value.cause == "invalid_response"


def test_response_without_choices_is_an_invalid_response():
    api = FakeApi()
    api.chat.completions.create = lambda **_: SimpleNamespace(choices=[], usage=None)
    with pytest.raises(PipelineError) as caught:
        generator(api).generate("q", [])
    assert caught.value.cause == "invalid_response"
    assert caught.value.details["raw_response"] is None


def test_null_content_is_an_invalid_response_not_an_abstention():
    api = FakeApi()
    message = SimpleNamespace(content=None)
    choice = SimpleNamespace(finish_reason="stop", message=message)
    api.chat.completions.create = lambda **_: SimpleNamespace(choices=[choice], usage=None)
    with pytest.raises(PipelineError) as caught:
        generator(api).generate("q", [])
    assert caught.value.cause == "invalid_response"


def test_prompt_defines_the_answer_field():
    """Prompt không nói `answer` là gì thì model để trống dù `claims` có đúng số liệu."""
    prompt = " ".join(SYSTEM_PROMPT.split())
    assert "answer là câu trả lời hoàn chỉnh" in prompt
    assert "không được để trống khi abstain=false" in prompt


def test_schema_asks_for_answer_before_the_optional_abstain_reason():
    """Model viết `"abstain_reason":""` rồi viết luôn `"answer":""`: 14/20 câu rỗng khi đo."""
    keys = list(ANSWER_JSON_SCHEMA["properties"])
    assert keys == ["abstain", "answer", "claims", "citation_ids", "confidence", "abstain_reason"]


def test_optional_abstain_reason_stays_out_of_required():
    assert "abstain_reason" not in ANSWER_JSON_SCHEMA["required"]
