"""Kiểm vLLM lúc khởi động: đúng model, ghi phiên bản (spec web app §5.2 bước 5)."""

from collections.abc import Sequence

import httpx


class VllmMismatch(RuntimeError):
    """Server không phục vụ model mà config yêu cầu: từ chối chạy với một model lạ."""


def check_served_model(served: Sequence[str], expected: str) -> None:
    if expected not in served:
        raise VllmMismatch(
            f"vLLM không phục vụ {expected!r}; đang phục vụ: {sorted(served) or 'không model nào'}"
        )


def fetch_vllm_version(
    base_url: str, api_key: str, timeout_s: float = 10.0, client: httpx.Client | None = None
) -> str:
    # /version nằm ngoài /v1; giữ nguyên tiền tố reverse-proxy nếu có (như /tokenize ở probe).
    server_url = base_url.rstrip("/").removesuffix("/v1")
    http = client or httpx.Client(timeout=timeout_s)
    response = http.get(server_url + "/version", headers={"Authorization": f"Bearer {api_key}"})
    response.raise_for_status()
    return str(response.json().get("version", "unknown"))
