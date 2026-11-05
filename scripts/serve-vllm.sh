#!/usr/bin/env bash
# Bật vLLM phục vụ generator trên laptop RTX 4050 6 GB. Giữ terminal mở; Ctrl-C để tắt.
#
#   ./scripts/serve-vllm.sh
#   VLLM_PORT=8001 ./scripts/serve-vllm.sh
#
# Model và revision phải khớp configs/pipeline/b3-qwen3-4b-awq.yaml (có test kiểm).
# Môi trường nằm ở environments/vllm, lock riêng với app; lần đầu `uv sync` cài khoảng 9 GB.
set -euo pipefail
cd "$(dirname "$0")/.."

uv sync --locked --quiet --project environments/vllm

# Sampler FlashInfer JIT-compile kernel và cần nvcc; laptop không có CUDA toolkit.
export VLLM_USE_FLASHINFER_SAMPLER=0
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"

# Chỉ nghe loopback: server không đặt API key, nên máy khác trong mạng sẽ gọi thẳng được và chiếm
# GPU. enable_thinking=false đi kèm từng request, không đặt mặc định ở server.
#   --structured-outputs-config: không có thì model lặp khoảng trắng tới hết max_tokens.
#   --gpu-memory-utilization 0.93: thấp hơn thì KV cache không đủ cho 8.192 token.
exec environments/vllm/.venv/bin/vllm serve Qwen/Qwen3-4B-AWQ \
  --revision 74d4bd2bd4bff9cafc9345221320bffb08b406a3 \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.93 \
  --seed 42 \
  --structured-outputs-config '{"backend": "xgrammar", "disable_any_whitespace": true}' \
  --host 127.0.0.1 \
  --port "${VLLM_PORT:-8000}"
