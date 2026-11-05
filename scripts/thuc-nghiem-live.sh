#!/usr/bin/env bash
# Thực nghiệm live trên laptop RTX 4050 6 GB: chạy pipeline v2 với vLLM thật và so ID dài với ID
# ngắn trên cùng câu hỏi. Script tự bật vLLM và tự tắt khi xong; server đã chạy sẵn thì dùng lại.
#
#   ./scripts/thuc-nghiem-live.sh            # 20 câu
#   ./scripts/thuc-nghiem-live.sh 40         # số câu tuỳ chọn
#
# Biến môi trường:
#   VLLM_PORT         mặc định 8000
#   PIPELINE_CONFIG   mặc định configs/pipeline/b3-qwen3-4b-awq.yaml
#   EMBEDDING_DEVICE  mặc định cpu: BGE-M3 fp32 không nằm chung được với vLLM trên 6 GB
#   STARTUP_TIMEOUT_S mặc định 900; vLLM thường cần 1–2 phút, máy bận có thể tới 8 phút
#
# Kết quả ở artifacts/runs/live-<thời gian>/: report.md, rows.jsonl, run.log, vllm.log.
set -euo pipefail
cd "$(dirname "$0")/.."

LIMIT="${1:-20}"
VLLM_PORT="${VLLM_PORT:-8000}"
PIPELINE_CONFIG="${PIPELINE_CONFIG:-configs/pipeline/b3-qwen3-4b-awq.yaml}"
EMBEDDING_DEVICE="${EMBEDDING_DEVICE:-cpu}"
MODEL="Qwen/Qwen3-4B-AWQ"
MIN_FREE_MIB=5200
STARTUP_TIMEOUT_S="${STARTUP_TIMEOUT_S:-900}"
BASE_URL="http://127.0.0.1:${VLLM_PORT}/v1"
OUT="artifacts/runs/live-$(date +%Y%m%d-%H%M%S)"
VLLM_PID=""

say() { printf '==> %s\n' "$*"; }
die() { printf 'LỖI: %s\n' "$*" >&2; exit 1; }

[[ "$LIMIT" =~ ^[1-9][0-9]*$ ]] || die "số câu phải là số nguyên dương, nhận '$LIMIT'"
command -v uv >/dev/null || die "thiếu uv"
command -v curl >/dev/null || die "thiếu curl"
[[ -f "data/tuyen-sinh-dai-hoc-chinh-quy/Cẩm Nang Tuyển Sinh Đại Học Năm 2025.pdf" ]] \
  || die "thiếu PDF Cẩm nang 2025 trong data/"

stop_vllm() {
  [[ -n "$VLLM_PID" ]] || return 0
  say "Tắt vLLM (pid $VLLM_PID)"
  kill "$VLLM_PID" 2>/dev/null || true
  wait "$VLLM_PID" 2>/dev/null || true
  VLLM_PID=""
}
trap stop_vllm EXIT
trap 'exit 130' INT TERM

# Không dùng `curl | grep -q`: grep thoát sớm làm curl nhận SIGPIPE, pipefail báo lỗi giả.
serving() {
  local models
  models="$(curl -fsS -m 3 "$BASE_URL/models" 2>/dev/null)" || return 1
  [[ "$models" == *"$MODEL"* ]]
}

mkdir -p "$OUT"
exec > >(tee -a "$OUT/run.log") 2>&1
if serving; then
  say "Dùng lại vLLM đang chạy ở cổng $VLLM_PORT"
else
  if curl -s -m 3 -o /dev/null "http://127.0.0.1:${VLLM_PORT}/"; then
    die "cổng $VLLM_PORT đang có dịch vụ khác; đặt VLLM_PORT khác"
  fi
  if command -v nvidia-smi >/dev/null; then
    free_mib="$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | head -n 1)"
    (( free_mib >= MIN_FREE_MIB )) \
      || die "GPU chỉ còn ${free_mib} MiB, cần ${MIN_FREE_MIB}; tắt app đang dùng GPU rồi chạy lại"
  fi

  say "Bật vLLM, log ở $OUT/vllm.log"
  VLLM_PORT="$VLLM_PORT" ./scripts/serve-vllm.sh >"$OUT/vllm.log" 2>&1 &
  VLLM_PID=$!

  started=$SECONDS
  next_report=30
  until serving; do
    elapsed=$((SECONDS - started))
    if ! kill -0 "$VLLM_PID" 2>/dev/null; then
      VLLM_PID=""
      tail -n 20 "$OUT/vllm.log" >&2
      die "vLLM dừng khi đang khởi động; xem $OUT/vllm.log"
    fi
    (( elapsed < STARTUP_TIMEOUT_S )) || die "vLLM chưa sẵn sàng sau ${elapsed}s; xem $OUT/vllm.log"
    if (( elapsed >= next_report )); then
      say "Vẫn đang khởi động (${elapsed}s): $(grep -aE 'INFO|WARNING' "$OUT/vllm.log" | tail -n 1 | cut -c1-90)"
      next_report=$((next_report + 30))
    fi
    sleep 3
  done
  say "vLLM sẵn sàng sau $((SECONDS - started))s"
fi

say "Chạy $LIMIT câu, mỗi câu hai arm"
HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}" uv run python -m experiments.live_check \
  --base-url "$BASE_URL" \
  --config "$PIPELINE_CONFIG" \
  --limit "$LIMIT" \
  --embedding-device "$EMBEDDING_DEVICE" \
  --out "$OUT"

say "Xong. Báo cáo: $OUT/report.md"
