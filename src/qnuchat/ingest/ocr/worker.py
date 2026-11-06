"""Worker OCR `cur_rotgate`: nạp engine một lần, mỗi ảnh một checkpoint nguyên tử.

Chạy trong `environments/ocr`, không cài `qnuchat` ở đó nên gọi theo đường dẫn file:

    environments/ocr/.venv/bin/python -P src/qnuchat/ingest/ocr/worker.py --job job.json --out <dir>

Vì vậy cấp module chỉ import thư viện chuẩn; engine import muộn trong hàm nạp. Tách từ đường chạy
`cur_rotgate` của `experiments/ocr_selection/worker.py` (repo cũ, tag `v1-final`), giữ nguyên tham
số và thứ tự gọi để output giống lần chạy đã nghiệm thu; đổi file này phải chạy lại `verify`.

Sự kiện là một dòng stdout `OCREVENT {json}`: `loaded`, `image`, `fatal`. Mã thoát: 0 xong; 130 dừng
chủ động; 3 môi trường lệch; 4 không nạp được engine; 5 không có GPU.

Lỗi một ảnh là execution error: ghi `{"id", "image_sha256", "error"}` rồi làm ảnh sau, không biến
thành trang rỗng.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.metadata
import json
import os
import platform
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

PREFIX = "OCREVENT "
CONFIG = "cur_rotgate"

EXIT_OK = 0
EXIT_ENV_MISMATCH = 3
EXIT_LOAD_FAILED = 4
EXIT_GPU_UNAVAILABLE = 5
EXIT_STOPPED = 130

DET_MODEL = "PP-OCRv6_medium_det"
DOC_ORI_MODEL = "PP-LCNet_x1_0_doc_ori"
REC_MODEL = "vgg_transformer"
VIETOCR_DIR = Path.home() / ".cache" / "qnu-ocr" / "vietocr"
PACKAGES = ("paddleocr", "paddlex", "paddlepaddle-gpu", "vietocr", "torch")

# Hash lấy từ environment.json của lần chạy cur_rotgate đã nghiệm thu; lệch là model khác.
PADDLE_WEIGHTS = {
    DET_MODEL: "85218d2e3d98f5a21c58b4220627be923a97aee5db3cc71f39536ab31ac53960",
    DOC_ORI_MODEL: "e8d6e7c5d264507e40e58a655779059d616b20d7441ea22047d829eb3931989c",
}
VIETOCR_FILES = {
    "base.yml": "9c8283fadb950f06f5d3400475f80d5355700ff315c9c48b7875e6ea66647d1c",
    f"{REC_MODEL}.yml": "0df9feee197754c7381871e5dfd07c6f3e292a4853eece6f1af240923e57c907",
    f"{REC_MODEL}.pth": "380512193a8b6cbf6fad80deacdc9b6939d10d473d199892fc6408d13775ea59",
}

CROP_PAD = 3
# Cổng xoay trang: trang nằm ngang khi ≥ 80% khung chữ dài (cạnh dài ≥ 2 × cạnh ngắn) dựng đứng.
# Đo 21/10/2026 trên 122 ảnh: 24 trang ngang của Đề án 2024 đều 100%, mọi trang khác 0%.
SIDEWAYS_MIN_RATIO = 0.8
SIDEWAYS_MIN_LONG = 10
# Tham số phát hiện của pipeline OCR của paddlex; `TextDetection` đứng riêng có mặc định khác.
# `max_side_limit` không nhận ở hàm khởi tạo nên truyền lúc `predict`, như pipeline.
DET_PARAMS = {
    "limit_side_len": 64,
    "limit_type": "min",
    "thresh": 0.3,
    "box_thresh": 0.6,
    "unclip_ratio": 1.5,
    "max_side_limit": 4000,
}
_DET_PREDICT_ONLY = ("max_side_limit",)
_STOP_SIGNALS = (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)

# Engine trả `{"lines": [...], "rotation": góc}`.
OcrFn = Callable[[Path], dict]


class LoadFailed(Exception):
    """Không nạp được engine (thiếu model, thiếu trọng số)."""


class GpuUnavailable(Exception):
    """CUDA không dùng được; không lùi về CPU."""


class EnvMismatch(Exception):
    """Trọng số hoặc môi trường khác với bản đã nghiệm thu."""


_stop_requested = False


def emit(event: str, **fields) -> None:
    print(PREFIX + json.dumps({"event": event, **fields}, ensure_ascii=False), flush=True)


def _fatal(kind: str, message: str, code: int) -> int:
    emit("fatal", kind=kind, message=message)
    return code


def _stop_once(signum, frame) -> None:
    """Đặt cờ dừng; ảnh đang làm vẫn chạy xong và ghi checkpoint. Tín hiệu sau bị bỏ qua để không
    cắt ngang việc ghi."""
    global _stop_requested
    for sig in _STOP_SIGNALS:
        signal.signal(sig, signal.SIG_IGN)
    _stop_requested = True


def _install_signals() -> None:
    """Gắn (lại) bộ xử lý dừng. Paddle cài bộ xử lý SIGTERM của nó (in stack rồi chết, mã 143) lúc
    import/nạp model, nên gọi lại sau mỗi bước đó; đã nhận tín hiệu thì giữ bỏ qua."""
    handler = signal.SIG_IGN if _stop_requested else _stop_once
    for sig in _STOP_SIGNALS:
        signal.signal(sig, handler)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic_write_json(path: Path, obj) -> None:
    """Ghi JSON qua file tạm cùng thư mục, fsync rồi `os.replace`."""
    path = Path(path)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def clean_tmp(directory: Path) -> None:
    """Xoá file tạm `.*.tmp-*` bỏ lại sau khi bị ngắt."""
    for p in Path(directory).glob(".*.tmp-*"):
        if p.is_file():
            p.unlink()


def read_output(path: Path) -> dict | None:
    try:
        obj = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


def valid_output(path: Path, image_sha256: str, *, retry_errors: bool = False) -> bool:
    """File output hợp lệ: JSON đọc được, hash ảnh khớp, có `lines` hoặc `error`."""
    obj = read_output(path)
    if obj is None or obj.get("image_sha256") != image_sha256:
        return False
    if isinstance(obj.get("lines"), list):
        return True
    return isinstance(obj.get("error"), dict) and not retry_errors


def env_sha256(env: dict) -> str:
    raw = json.dumps(env, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def paddle_models_dir() -> Path:
    """Nơi paddlex lưu model chính thức (như `paddlex.utils.cache.CACHE_DIR`)."""
    home = os.environ.get("PADDLE_PDX_CACHE_HOME", str(Path.home() / ".paddlex"))
    return Path(home) / "official_models"


def check_weights(models_dir: Path | None = None, vietocr_dir: Path | None = None) -> None:
    """Trọng số phải đúng hash đã nghiệm thu; paddlex tải model lúc nạp nên gọi sau khi nạp."""
    models_dir = paddle_models_dir() if models_dir is None else models_dir
    vietocr_dir = VIETOCR_DIR if vietocr_dir is None else vietocr_dir
    expected = {models_dir / m / "inference.pdiparams": h for m, h in PADDLE_WEIGHTS.items()}
    expected |= {vietocr_dir / name: h for name, h in VIETOCR_FILES.items()}
    for path, sha in expected.items():
        actual = sha256_file(path) if path.is_file() else None
        if actual != sha:
            raise EnvMismatch(f"{path}: sha256 {actual} khác bản đã nghiệm thu {sha}")


def _package_versions() -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for name in PACKAGES:
        try:
            out[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            out[name] = None
    return out


def _gpu_info() -> str | None:
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip()


def build_env() -> dict:
    """Môi trường của lượt chạy; hash của nó quyết định có ghép tiếp checkpoint cũ được không."""
    return {
        "config": CONFIG,
        "python": platform.python_version(),
        "worker_sha256": sha256_file(Path(__file__)),
        "packages": _package_versions(),
        "paddle_weights": PADDLE_WEIGHTS,
        "vietocr_files": VIETOCR_FILES,
        "det_params": DET_PARAMS,
        "gpu": _gpu_info(),
    }


def check_cuda() -> None:
    """Kiểm CUDA của cả Paddle lẫn Torch; không có thì `GpuUnavailable`."""
    try:
        import paddle
        import torch
    except ImportError as e:
        raise LoadFailed(f"thiếu thư viện engine: {e}") from e
    if not (paddle.device.is_compiled_with_cuda() and paddle.device.cuda.device_count() > 0):
        raise GpuUnavailable("paddle không thấy GPU CUDA")
    if not torch.cuda.is_available():
        raise GpuUnavailable("torch.cuda.is_available() = False")


def _rect(poly) -> list[int]:
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return [int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))]


def det_init_kwargs() -> dict:
    return {k: v for k, v in DET_PARAMS.items() if k not in _DET_PREDICT_ONLY}


def det_predict_kwargs() -> dict:
    return {k: DET_PARAMS[k] for k in _DET_PREDICT_ONLY}


def load_vietocr_config(base: Path, named: Path) -> dict:
    """Ghép cấu hình như `Cfg.load_config_from_name` (base trước, cấu hình tên đè lên, đè nông)
    nhưng đọc file cục bộ. Tắt `cnn.pretrained`: trọng số ImageNet của VGG sẽ bị
    `load_state_dict` ghi đè, nên không cần tải ~550 MB từ download.pytorch.org."""
    import yaml

    cfg = yaml.safe_load(base.read_text(encoding="utf-8")) or {}
    cfg.update(yaml.safe_load(named.read_text(encoding="utf-8")) or {})
    cfg["cnn"] = {**(cfg.get("cnn") or {}), "pretrained": False}
    return cfg


def _det_boxes(det, sort, image) -> list[dict]:
    """Hộp chữ hình chữ nhật bao các đa giác `dt_polys`, theo thứ tự đọc như pipeline PaddleOCR."""
    polys = det.predict(image, **det_predict_kwargs())[0].json["res"]["dt_polys"]
    if len(polys) == 0:
        return []
    return [{"box": _rect(p)} for p in sort(polys)]


def is_sideways(boxes: list[dict]) -> bool:
    """Trang nằm ngang: đủ `SIDEWAYS_MIN_LONG` khung dài và phần lớn chúng cao hơn rộng.

    Bộ phân loại hướng trang đứng một mình đoán nhầm trang bảng đứng thẳng thành 90° (TB141), nên
    chỉ hỏi nó hướng nào sau khi hình học khung chữ đã cho thấy trang nằm ngang.
    """
    long = []
    for b in boxes:
        x0, y0, x1, y1 = b["box"]
        w, h = x1 - x0, y1 - y0
        if max(w, h) >= 2 * min(w, h):
            long.append(h > w)
    return len(long) >= SIDEWAYS_MIN_LONG and sum(long) >= SIDEWAYS_MIN_RATIO * len(long)


def sideways_angle(res: dict) -> int:
    """Góc 90 hoặc 270 có điểm cao hơn trong kết quả `topk=4` của bộ phân loại hướng trang."""
    scores = dict(zip(res["label_names"], res["scores"], strict=True))
    if "90" not in scores or "270" not in scores:
        raise ValueError(f"thiếu điểm góc 90/270: {res['label_names']}")
    return 90 if scores["90"] > scores["270"] else 270


def _crop(img, box: list[int]):
    """Nới `CROP_PAD` px, kẹp trong ảnh; `img` là mảng BGR của OpenCV."""
    x0, y0, x1, y1 = box
    h, w = img.shape[:2]
    return img[
        max(y0 - CROP_PAD, 0) : min(y1 + CROP_PAD, h), max(x0 - CROP_PAD, 0) : min(x1 + CROP_PAD, w)
    ]


def _read_upright(boxes: list[dict], image: Path, predictor) -> list[dict]:
    """Đường của trang đứng thẳng: cắt bằng Pillow từ file, như cấu hình `cur`."""
    from PIL import Image

    img = Image.open(image).convert("RGB")
    w, h = img.size
    crops = [
        img.crop(
            (
                max(b[0] - CROP_PAD, 0),
                max(b[1] - CROP_PAD, 0),
                min(b[2] + CROP_PAD, w),
                min(b[3] + CROP_PAD, h),
            )
        )
        for b in (ln["box"] for ln in boxes)
    ]
    texts = predictor.predict_batch(crops) if crops else []
    return [{"text": t, "box": ln["box"]} for t, ln in zip(texts, boxes, strict=True)]


def load_engine() -> OcrFn:
    """`cur` + cổng xoay: trang đứng thẳng đi đúng đường của `cur`; trang nằm ngang được xoay rồi
    phát hiện và đọc lại. Output ghi `rotation` (0, 90, 270); khung theo ảnh đã xoay."""
    check_cuda()
    configs = (VIETOCR_DIR / "base.yml", VIETOCR_DIR / f"{REC_MODEL}.yml")
    weights = VIETOCR_DIR / f"{REC_MODEL}.pth"
    for f in (*configs, weights):
        if not f.is_file():
            raise LoadFailed(f"thiếu file VietOCR {f}; chạy ./scripts/chay-ocr.sh setup")

    import cv2
    import numpy as np
    from paddleocr import DocImgOrientationClassification, TextDetection
    from paddlex.inference.pipelines.components import SortQuadBoxes, rotate_image
    from PIL import Image
    from vietocr.tool.config import Cfg
    from vietocr.tool.predictor import Predictor

    det = TextDetection(model_name=DET_MODEL, device="gpu", **det_init_kwargs())
    cfg = Cfg(load_vietocr_config(*configs))
    cfg["weights"] = str(weights)
    cfg["device"] = "cuda:0"
    predictor = Predictor(cfg)
    sort = SortQuadBoxes()
    doc_ori = DocImgOrientationClassification(model_name=DOC_ORI_MODEL, device="gpu")
    # Gọi thử lúc nạp: lần gọi đầu mới cấp workspace cuBLAS; để tới trang ngang đầu tiên thì VRAM đã
    # bị VietOCR giữ và cuBLAS báo CUBLAS_STATUS_ALLOC_FAILED (đo 21/10/2026).
    doc_ori.predict(np.full((224, 224, 3), 255, dtype=np.uint8), topk=4)

    def ocr(image: Path) -> dict:
        boxes = _det_boxes(det, sort, str(image))
        if not is_sideways(boxes):
            return {"lines": _read_upright(boxes, image, predictor), "rotation": 0}
        img = cv2.imread(str(image))  # BGR, như paddlex đọc từ đường dẫn
        if img is None:
            raise ValueError(f"cv2 không đọc được {image}")
        angle = sideways_angle(doc_ori.predict(img, topk=4)[0].json["res"])
        img = rotate_image(img, angle)
        boxes = _det_boxes(det, sort, img)
        crops = [_crop(img, b["box"]) for b in boxes]
        pil = [Image.fromarray(cv2.cvtColor(c, cv2.COLOR_BGR2RGB)) for c in crops]
        texts = predictor.predict_batch(pil) if pil else []
        lines = [{"text": t, "box": b["box"]} for t, b in zip(texts, boxes, strict=True)]
        return {"lines": lines, "rotation": angle}

    return ocr


def _is_oom(e: BaseException) -> bool:
    return "OutOfMemory" in type(e).__name__ or "out of memory" in str(e).lower()


def _free_gpu_cache() -> None:
    """Sau OOM: trả bộ nhớ đệm CUDA của thư viện đã nạp, để ảnh sau còn cơ hội chạy."""
    torch = sys.modules.get("torch")
    if torch is not None:
        with contextlib.suppress(Exception):  # dọn dẹp, không được che lỗi gốc
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
    paddle = sys.modules.get("paddle")
    if paddle is not None:
        with contextlib.suppress(Exception):
            paddle.device.cuda.empty_cache()


def ocr_one(ocr: OcrFn, item: dict, digest: str) -> dict:
    """OCR một ảnh → bản ghi output hoặc bản ghi lỗi; không ném exception của engine ra ngoài."""
    sha = item["sha256"]

    def error(kind: str, message: str) -> dict:
        return {"id": item["id"], "image_sha256": sha, "error": {"kind": kind, "message": message}}

    image = Path(item["path"])
    try:
        actual = sha256_file(image)
    except OSError as e:
        return error("image_missing", f"{image}: {e}")
    if actual != sha:
        return error("image_hash_mismatch", f"{image}: sha256 {actual} khác job {sha}")
    t0 = time.monotonic()
    try:
        res = ocr(image)
    except Exception as e:  # noqa: BLE001 — mọi lỗi engine là execution error của ảnh này
        oom = _is_oom(e)
        rec = error("cuda_oom" if oom else "exception", f"{type(e).__name__}: {e}")
    else:
        return {
            "id": item["id"],
            "image_sha256": sha,
            **res,
            "config": CONFIG,
            "env_sha256": digest,
            "seconds": round(time.monotonic() - t0, 3),
        }
    # Dọn bộ nhớ đệm sau khi đã có bản ghi lỗi và ra khỏi khối `except` (không giữ traceback).
    if oom:
        _free_gpu_cache()
    return rec


def run(
    items: list[dict],
    out: Path,
    *,
    retry_errors: bool = False,
    load: Callable[[], OcrFn] = load_engine,
    check: Callable[[], None] = check_weights,
    env: Callable[[], dict] = build_env,
) -> int:
    out.mkdir(parents=True, exist_ok=True)
    clean_tmp(out)
    t0 = time.monotonic()
    try:
        _install_signals()
        ocr = load()
        _install_signals()
        check()
    except GpuUnavailable as e:
        return _fatal("ocr_gpu_unavailable", str(e), EXIT_GPU_UNAVAILABLE)
    except EnvMismatch as e:
        return _fatal("env_mismatch", str(e), EXIT_ENV_MISMATCH)
    except Exception as e:  # noqa: BLE001 — nạp hỏng vì bất kỳ lý do gì đều là load_failed
        return _fatal("load_failed", f"{type(e).__name__}: {e}", EXIT_LOAD_FAILED)

    current = env()
    digest = env_sha256(current)
    env_path = out / "environment.json"
    old = read_output(env_path)
    if old is None:
        atomic_write_json(env_path, current)
    elif env_sha256(old) != digest:
        return _fatal(
            "env_mismatch",
            f"{env_path} khác môi trường hiện tại; xoá {out} để OCR lại từ đầu",
            EXIT_ENV_MISMATCH,
        )
    emit("loaded", load_s=round(time.monotonic() - t0, 3), env_sha256=digest)

    for item in items:
        if _stop_requested:
            return EXIT_STOPPED
        path = out / f"{item['id']}.json"
        if valid_output(path, item["sha256"], retry_errors=retry_errors):
            emit("image", id=item["id"], ok=True, skipped=True)
            continue
        rec = ocr_one(ocr, item, digest)
        atomic_write_json(path, rec)
        emit("image", id=item["id"], ok="lines" in rec, skipped=False)
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    _install_signals()
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--job", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--retry-errors", action="store_true")
    args = p.parse_args(argv)
    items = json.loads(args.job.read_text(encoding="utf-8"))
    return run(items, args.out, retry_errors=args.retry_errors)


if __name__ == "__main__":
    sys.exit(main())
