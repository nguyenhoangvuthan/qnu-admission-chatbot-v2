import json
from pathlib import Path

import httpx
import openai
import pytest

from qnuchat.ingest.topic_filter.classifier import (
    TOPIC_SCHEMA,
    TopicExecutionError,
    VllmTopicClassifier,
    render_input,
)
from qnuchat.ingest.topic_filter.inputs import TopicInput
from tests.support.fakes import FakeChatApi, SequenceApi

ROOT = Path(__file__).resolve().parents[2]
REQUEST = httpx.Request("POST", "http://localhost:8000/v1/chat/completions")
GIU = {"label": "giu", "group": "tuyen_sinh", "reason": None, "note": "Thông báo tuyển sinh."}
GIU_JSON = json.dumps(GIU, ensure_ascii=False)
INP = TopicInput(
    url="https://www.qnu.edu.vn/vi/tin/tuyen-sinh-2026",
    sha256="s" * 64,
    kind="page",
    host="www.qnu.edu.vn",
    title="Thông báo tuyển sinh 2026",
    file_name=None,
    page_url=None,
    page_title=None,
    link_text=None,
    text="Trường Đại học Quy Nhơn thông báo tuyển sinh đại học chính quy năm 2026.",
)
IMAGE = TopicInput(
    url="https://www.qnu.edu.vn/Temp/anh.jpg",
    sha256="i" * 64,
    kind="image",
    host="www.qnu.edu.vn",
    title=None,
    file_name="anh.jpg",
    page_url="https://www.qnu.edu.vn/vi/tin/hoi-thao",
    page_title="Hội thảo khoa học",
    link_text=None,
    text=None,
)


def classifier(api, **kwargs):
    return VllmTopicClassifier(
        api,
        model="Qwen/Qwen3-4B-AWQ",
        seed=42,
        max_tokens=256,
        chat_template_kwargs={"enable_thinking": False},
        prompt="PROMPT",
        **kwargs,
    )


def test_request_uses_schema_temperature_seed_and_thinking_off():
    api = FakeChatApi(content=GIU_JSON)
    classifier(api).classify(INP)
    sent = api.requests[0]
    assert (sent["model"], sent["temperature"], sent["seed"], sent["max_tokens"]) == (
        "Qwen/Qwen3-4B-AWQ",
        0,
        42,
        256,
    )
    assert sent["messages"][0] == {"role": "system", "content": "PROMPT"}
    assert sent["messages"][1] == {"role": "user", "content": render_input(INP)}
    assert sent["response_format"]["type"] == "json_schema"
    assert sent["response_format"]["json_schema"]["schema"] == TOPIC_SCHEMA
    assert sent["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}


def test_schema_enumerates_the_spec_values():
    props = TOPIC_SCHEMA["properties"]
    assert set(TOPIC_SCHEMA["required"]) == {"label", "group", "reason", "note"}
    assert TOPIC_SCHEMA["additionalProperties"] is False
    assert set(props["label"]["enum"]) == {"giu", "loai", "khong_chac"}
    assert set(props["group"]["enum"]) == {
        "tuyen_sinh",
        "hoc_phi_ktx_hoc_bong",
        "nganh_ctdt",
        None,
    }
    assert set(props["reason"]["enum"]) == {
        "sau_dai_hoc",
        "vlvh_tu_xa_lien_thong",
        "khoa_ngan_han",
        "khong_lien_quan",
        None,
    }


def test_valid_json_maps_to_verdict():
    verdict = classifier(FakeChatApi(content=GIU_JSON)).classify(INP)
    assert (verdict.label, verdict.group, verdict.reason, verdict.note) == (
        "giu",
        "tuyen_sinh",
        None,
        "Thông báo tuyển sinh.",
    )


def test_one_retry_then_success_returns_the_second_answer():
    api = SequenceApi([FakeChatApi(content="không phải json"), FakeChatApi(content=GIU_JSON)])
    assert classifier(api).classify(INP).label == "giu" and len(api.requests) == 2


@pytest.mark.parametrize(
    "bad, cause",
    [
        (FakeChatApi(content="{"), "invalid_response"),
        (
            FakeChatApi(content='{"label": "xoa", "group": null, "reason": null, "note": ""}'),
            "invalid_response",
        ),
        (FakeChatApi(content='{"label": "loai"}'), "invalid_response"),
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
        (FakeChatApi(content=GIU_JSON, finish="length"), "truncated"),
        (FakeChatApi(content=GIU_JSON, finish=None), "abnormal_finish"),
    ],
)
def test_two_failures_raise_execution_error_never_loai(bad, cause):
    api = SequenceApi([bad, bad])
    with pytest.raises(TopicExecutionError) as info:
        classifier(api).classify(INP)
    assert info.value.cause == cause and len(api.requests) == 2


def test_render_input_of_a_page_has_title_and_content():
    text = render_input(INP)
    assert "Loại mục: page" in text and "Tiêu đề: Thông báo tuyển sinh 2026" in text
    assert "Nội dung (1.500 ký tự đầu):\nTrường Đại học Quy Nhơn" in text
    assert "Tên file" not in text and "Trang chứa" not in text


def test_render_input_omits_missing_fields_and_marks_no_content():
    text = render_input(IMAGE)
    assert "Tên file: anh.jpg" in text
    assert "Trang chứa: Hội thảo khoa học — https://www.qnu.edu.vn/vi/tin/hoi-thao" in text
    assert "Nội dung: (không có — file chưa có lớp chữ hoặc ảnh)" in text
    assert "Tiêu đề:" not in text and "Chữ của đường link" not in text


def test_prompt_file_contains_k1_lists():
    text = (ROOT / "configs/knowledge_base/topic_prompt.md").read_text(encoding="utf-8").lower()
    for phrase in (
        "sau đại học",
        "vừa làm vừa học",
        "từ xa",
        "liên thông",
        "văn bằng 2",
        "học phí",
        "ký túc xá",
        "học bổng",
        "chương trình đào tạo",
        "khong_chac",
    ):
        assert phrase in text
