import httpx
import pytest

from qnuchat.adapters.generation.vllm_checks import (
    VllmMismatch,
    check_served_model,
    fetch_vllm_version,
)


def test_served_model_present_passes():
    check_served_model(["Qwen/Qwen3-4B-AWQ"], "Qwen/Qwen3-4B-AWQ")


def test_wrong_model_refuses_and_names_what_is_served():
    with pytest.raises(VllmMismatch, match="Qwen/Qwen3-8B-AWQ"):
        check_served_model(["Qwen/Qwen3-8B-AWQ"], "Qwen/Qwen3-4B-AWQ")


def test_no_models_served_refuses():
    with pytest.raises(VllmMismatch):
        check_served_model([], "Qwen/Qwen3-4B-AWQ")


def test_version_is_read_from_the_server_root_not_the_v1_prefix():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((str(request.url), request.headers["authorization"]))
        return httpx.Response(200, json={"version": "0.30.0"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert fetch_vllm_version("http://h:8000/v1", "KEY", client=client) == "0.30.0"
    assert seen == [("http://h:8000/version", "Bearer KEY")]
