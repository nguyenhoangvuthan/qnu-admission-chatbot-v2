"""Băm request gửi LLM: cùng thuật toán với experiments.prepare_gold.digest để hash khớp probe."""

import hashlib
import json
from typing import Any


def request_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
