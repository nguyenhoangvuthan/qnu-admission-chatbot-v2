#!/usr/bin/env bash
# OCR file chờ trong data/web/quarantine/ bằng cấu hình cur_rotgate. Cần GPU, không lùi về CPU.
#
#   ./scripts/chay-ocr.sh setup     lần đầu: cài environments/ocr, tải trọng số (khoảng 10 GB)
#   ./scripts/chay-ocr.sh check     chỉ kiểm điều kiện, chưa OCR
#   ./scripts/chay-ocr.sh verify    OCR lại trang chuẩn, phải giống data/ocr-data từng dòng
#   ./scripts/chay-ocr.sh           OCR trong terminal này, có thanh tiến độ
#   ./scripts/chay-ocr.sh start     OCR nền (systemd), đóng terminal vẫn chạy
#   ./scripts/chay-ocr.sh log       xem lần chạy nền; Ctrl-C chỉ thôi xem, không dừng OCR
#   ./scripts/chay-ocr.sh stop      dừng lần chạy nền, chạy lại thì làm tiếp
#   ./scripts/chay-ocr.sh status    tiến độ
#   ./scripts/chay-ocr.sh review    file nào giữ, file nào là danh sách người; chưa đổi kho
#   ./scripts/chay-ocr.sh apply     áp kết quả vào kho; XOÁ file danh sách người, xem review trước
#   ./scripts/chay-ocr.sh remove <sha256>...   xoá hẳn file, lần quét sau không tải lại
#
# Thứ tự: setup, verify, chạy, review, apply. `run` từ chối khi worker hoặc environments/ocr đã đổi
# mà chưa verify lại. Tắt vLLM trước: laptop 6 GB, mỗi lúc một việc dùng GPU.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

UNIT=qnu-ocr
ENV_PYTHON=environments/ocr/.venv/bin/python
VIETOCR_DIR="$HOME/.cache/qnu-ocr/vietocr"
VIETOCR_URL=https://vocr.vn/data/vietocr
RUN=(uv run --frozen python -m apps.cli.ocr)

say() { printf '==> %s\n' "$*"; }
die() { printf 'LỖI: %s\n' "$*" >&2; exit 1; }
background_running() { systemctl --user is-active --quiet "$UNIT"; }

fetch_vietocr() {
  mkdir -p "$VIETOCR_DIR"
  local pair
  for pair in vgg_transformer.pth:vgg_transformer.pth base.yml:config/base.yml \
              vgg_transformer.yml:config/vgg-transformer.yml; do
    [[ -f "$VIETOCR_DIR/${pair%%:*}" ]] || curl -fsSL -o "$VIETOCR_DIR/${pair%%:*}" "$VIETOCR_URL/${pair#*:}"
  done
}

# Dựng hai model một lần để paddlex tải về ~/.paddlex; `import paddle` phải đứng đầu.
fetch_paddle() {
  "$ENV_PYTHON" -W ignore -c '
import paddle
from paddleocr import DocImgOrientationClassification, TextDetection
TextDetection(model_name="PP-OCRv6_medium_det", device="cpu")
DocImgOrientationClassification(model_name="PP-LCNet_x1_0_doc_ori", device="cpu")
'
}

check_ready() {
  command -v uv >/dev/null || die "thiếu uv"
  command -v nvidia-smi >/dev/null || die "thiếu nvidia-smi: OCR chỉ chạy GPU"
  [[ -x "$ENV_PYTHON" ]] || die "chưa có environments/ocr; chạy ./scripts/chay-ocr.sh setup"
  [[ -f "$VIETOCR_DIR/vgg_transformer.pth" ]] || die "thiếu trọng số VietOCR; chạy ./scripts/chay-ocr.sh setup"
  "$ENV_PYTHON" -W ignore -c 'import paddle, torch
assert paddle.device.is_compiled_with_cuda() and torch.cuda.is_available()' 2>/dev/null \
    || die "environments/ocr không dùng được CUDA"
  local used
  used="$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | awk '{s+=$1} END {print s+0}')"
  (( used < 500 )) || die "GPU đang dùng ${used} MiB, cần dưới 500 MiB: tắt vLLM rồi chạy lại"
}

case "${1:-run}" in
  setup)
    uv sync --locked --project environments/ocr
    fetch_vietocr
    fetch_paddle
    say "Xong. Tiếp theo: ./scripts/chay-ocr.sh verify"
    ;;
  check)
    check_ready
    "${RUN[@]}" status
    say "Đủ điều kiện OCR"
    ;;
  verify)
    check_ready
    "${RUN[@]}" verify "${@:2}"
    ;;
  run)
    check_ready
    "${RUN[@]}" run "${@:2}"
    ;;
  start)
    check_ready
    # KillMode=mixed: `stop` chỉ gửi SIGTERM cho tiến trình chính, nó chờ worker làm xong ảnh dở.
    systemd-run --user --unit "$UNIT" --same-dir --collect --quiet --setenv=PATH="$PATH" \
      --property=KillMode=mixed --property=TimeoutStopSec=300 \
      "${RUN[@]}" run "${@:2}"
    say "Đang OCR nền. Xem: ./scripts/chay-ocr.sh log; dừng: ./scripts/chay-ocr.sh stop"
    ;;
  log)
    journalctl --user -u "$UNIT" -n 20 -f -o cat
    ;;
  stop)
    background_running || die "không có lần OCR nền nào đang chạy"
    systemctl --user stop "$UNIT"
    say "Đã dừng; chạy lại thì làm tiếp"
    ;;
  status)
    if background_running; then say "Đang OCR nền"; else say "Không có lần OCR nền"; fi
    "${RUN[@]}" status
    ;;
  review)
    "${RUN[@]}" review
    ;;
  apply)
    "${RUN[@]}" apply
    ;;
  remove)
    "${RUN[@]}" remove "${@:2}"
    ;;
  *)
    die "lệnh không có: '$1'; xem đầu file scripts/chay-ocr.sh"
    ;;
esac
