"""Embedding BGE-M3 qua sentence-transformers."""

import sys

import numpy as np


class EmbedderDeviceError(RuntimeError):
    """Đòi GPU nhưng CUDA không dùng được — dừng ngay, không âm thầm chạy CPU."""


def resolve_device(requested: str | None = None) -> str:
    """Chốt thiết bị chạy embedding và FAIL NGAY nếu không có GPU.

    sentence-transformers tự dò thiết bị khi không được chỉ định, và khi torch
    không thấy CUDA (bản torch CPU-only, driver hỏng, chạy nhầm venv) nó lặng lẽ
    lùi về CPU. Kết quả số học vẫn y hệt nên không test nào đỏ, không log nào
    kêu — chỉ có một run BGE-m3 dài gấp hàng chục lần và một manifest không ghi
    lại việc đó.

    Muốn chạy CPU có chủ đích (máy dev không GPU) thì khai `device: "cpu"` trong
    config — im lặng thì mặc định là "cuda".
    """
    import torch

    device = requested or "cuda"
    if device.startswith("cuda") and not torch.cuda.is_available():
        raise EmbedderDeviceError(
            f"Cấu hình đòi embedding trên {device!r} nhưng torch.cuda.is_available() "
            f"là False (torch {torch.__version__}). Sửa môi trường CUDA, hoặc khai "
            'embedding.device: "cpu" trong config nếu CỐ Ý chạy trên CPU.'
        )
    return device


class BGEEmbedder:
    """Bọc sentence-transformers. Revision pin cứng để tái lập."""

    def __init__(
        self,
        model_name: str = "BAAI/bge-m3",
        revision: str | None = None,
        device: str | None = None,
    ):
        from sentence_transformers import SentenceTransformer

        self.device = resolve_device(device)
        self._model = SentenceTransformer(model_name, revision=revision, device=self.device)

    def encode(self, texts: list[str]) -> np.ndarray:
        return self._model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=len(texts) > 1 and sys.stderr.isatty(),  # corpus, không phải câu hỏi
            device=self.device,
        )

    def describe(self) -> dict:
        """Thông tin thiết bị để ghi vào manifest — bằng chứng run đã chạy trên GPU."""
        import torch

        return {
            "device": self.device,
            "torch_version": torch.__version__,
            "cuda_available": torch.cuda.is_available(),
            "cuda_device_name": (
                torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
            ),
        }
