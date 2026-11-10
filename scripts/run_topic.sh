#!/usr/bin/env bash
# Lọc chủ đề kho web bằng model, mỗi bước một lệnh (RUNBOOK mục 11.3).
#
#   scripts/run_topic.sh status              trạng thái kho, sổ quyết định, vLLM
#   scripts/run_topic.sh sample [SEED]       bốc mẫu và dựng form gán nhãn; không cần GPU
#   scripts/run_topic.sh check-sample        mẫu đang dùng còn khớp kho không
#   scripts/run_topic.sh topup [N]           bốc thêm N mục (mặc định 50) khi thiếu mục giu
#   scripts/run_topic.sh labels FILE.csv     áp thẳng nhãn của Kent, không cần model
#   scripts/run_topic.sh vllm                bật vLLM nền và chờ sẵn sàng
#   scripts/run_topic.sh try                 chạy thử 5 mục, in kết quả
#   scripts/run_topic.sh start | log | stop  lượt chính chạy nền; Ctrl-C ở log chỉ thôi xem
#   scripts/run_topic.sh score FILE.csv      đo bộ lọc trên nhãn của Kent
#   scripts/run_topic.sh pending             mục `prune` sẽ rút; chưa đổi gì
#   scripts/run_topic.sh prune               rút mục đó và XOÁ BLOB VĨNH VIỄN; hỏi xác nhận
#   scripts/run_topic.sh vllm-stop           tắt vLLM đã bật bằng lệnh vllm
#
# Chạy bằng bash nên gọi được từ fish.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

UNIT=qnu-topic
VLLM_UNIT=qnu-vllm-topic
VLLM_URL="${QNUCHAT_VLLM_BASE_URL:-http://127.0.0.1:8000/v1}"
export QNUCHAT_VLLM_BASE_URL="$VLLM_URL"
STORE=data/web
LEDGER="$STORE/topic.jsonl"
FILTER_DIR=artifacts/knowledge_base/topic-filter
POINTER="$FILTER_DIR/current-sample"  # `sample` ghi; score, topup, check-sample, labels đọc
GPU_IDLE_MIB=500
PY=(uv run --frozen python)
KB=("${PY[@]}" -m apps.cli.knowledge_base)

say() { printf '==> %s\n' "$*"; }
warn() { printf 'CẢNH BÁO: %s\n' "$*" >&2; }
die() { printf 'LỖI: %s\n' "$*" >&2; exit 1; }
running() { systemctl --user is-active --quiet "$1"; }
vllm_up() { curl -fsS --max-time 3 "$VLLM_URL/models" >/dev/null 2>&1; }
crawl_busy() { [[ -f "$STORE/crawl.lock" ]] && ! flock -n "$STORE/crawl.lock" true; }
need_quiet_store() {
  ! crawl_busy || die "kho $STORE đang được quét hoặc prune; chờ xong rồi chạy lại"
}
need_vllm() { vllm_up || die "vLLM chưa chạy ở $VLLM_URL; chạy: scripts/run_topic.sh vllm"; }

sample_dir() {
  [[ -f "$POINTER" ]] || die "chưa có mẫu; chạy: scripts/run_topic.sh sample"
  cat "$POINTER"
}

counts() {
  [[ -f "$LEDGER" ]] || { say "chưa có $LEDGER"; return 0; }
  "${PY[@]}" - "$LEDGER" <<'PY'
import sys
from collections import Counter
from qnuchat.ingest.topic_filter.ledger import TopicLedger
latest = {(d.url, d.sha256): d for d in TopicLedger(sys.argv[1]).entries()}
c = Counter((d.label or f"lỗi:{d.error_cause}", d.decided_by) for d in latest.values())
parts = ", ".join(f"{label} ({by}) {n}" for (label, by), n in sorted(c.items()))
print(f"{len(latest)} mục đã có quyết định: {parts}")
PY
}

store() {
  "${PY[@]}" - <<'PY'
from collections import Counter
from pathlib import Path
from qnuchat.ingest.config import load_crawl_config
from qnuchat.ingest.manifest import Manifest
from qnuchat.ingest.state import CheckState
from qnuchat.ingest.topic_filter.inputs import candidates, seed_urls
current = Manifest(Path("data/web/manifest.jsonl"), repair=False).current()
cfg, _ = load_crawl_config("configs/crawl/qnu.yaml")
state = CheckState(Path("data/web/last_checked.json"))
todo = candidates(current, seeds=seed_urls(cfg), state=state)
kinds = Counter(e.kind for e in todo)
print(f"kho: {len(current)} mục; cần lọc: {len(todo)} "
      f"(trang {kinds['page']}, file {kinds['file']}, ảnh {kinds['image']})")
PY
}

cmd_sample() {
  need_quiet_store
  local seed="${1:-$(date +%Y%m%d)}"
  "${KB[@]}" topic-sample --seed "$seed"
  mkdir -p "$FILTER_DIR"
  printf '%s\n' "$FILTER_DIR/sample-$seed" >"$POINTER"
  say "mở form: xdg-open $FILTER_DIR/sample-$seed/index.html"
}

cmd_check_sample() {
  crawl_busy && warn "kho đang được quét hoặc prune, kết quả kiểm còn có thể đổi"
  local dir
  dir="$(sample_dir)"  # gán riêng: lỗi trong $(...) ở vị trí tham số không dừng được set -e
  "${PY[@]}" - "$dir" <<'PY'
import sys
from pathlib import Path
from qnuchat.ingest.manifest import Manifest
from qnuchat.ingest.topic_filter.sample import read_rounds
current = Manifest(Path("data/web/manifest.jsonl"), repair=False).current()
rows = read_rounds(Path(sys.argv[1]))
gone = [r for r in rows if r["url"] not in current]
changed = [r for r in rows if r["url"] in current and current[r["url"]].sha256 != r["sha256"]]
print(f"mẫu {sys.argv[1]}: {len(rows)} mục; không còn trong kho {len(gone)}; nội dung đổi {len(changed)}")
for row in (gone + changed)[:10]:
    print(f"  {row['item_id']} {row['url'][:100]}")
if gone or changed:
    print("Mẫu không còn khớp kho: bốc mẫu mới bằng seed khác, chỉ khi chưa chạy start.")
    sys.exit(1)
print("mẫu khớp kho")
PY
}

cmd_topup() {
  need_quiet_store
  local dir seed
  dir="$(sample_dir)"
  seed="${dir##*sample-}"
  "${KB[@]}" topic-sample --seed "$seed" --top-up "${1:-50}"
  say "mở lại form (có cả vòng cũ): xdg-open $dir/index.html"
}

cmd_vllm() {
  if vllm_up; then
    say "vLLM đã chạy ở $VLLM_URL; dùng luôn"
    return
  fi
  local used
  used="$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | awk '{s+=$1} END {print s+0}')"
  (( used < GPU_IDLE_MIB )) || die "GPU đang dùng ${used} MiB; tắt việc dùng GPU khác (OCR, embedding) rồi chạy lại"
  say "bật vLLM nền (unit $VLLM_UNIT); nạp model mất 1–3 phút"
  systemd-run --user --unit "$VLLM_UNIT" --same-dir --collect --quiet \
    --setenv=PATH="$PATH" scripts/serve-vllm.sh
  local i
  for i in $(seq 1 120); do
    if vllm_up; then
      say "vLLM sẵn sàng ở $VLLM_URL"
      return
    fi
    running "$VLLM_UNIT" || die "vLLM dừng khi đang nạp; xem: journalctl --user -u $VLLM_UNIT -n 50"
    sleep 3
  done
  die "chờ 6 phút vLLM chưa sẵn sàng; xem: journalctl --user -u $VLLM_UNIT -f"
}

cmd_try() {
  need_quiet_store
  need_vllm
  local before=0
  [[ -f "$LEDGER" ]] && before="$(wc -l <"$LEDGER")"
  "${KB[@]}" classify --limit 5
  say "các dòng vừa ghi vào $LEDGER:"
  tail -n +"$((before + 1))" "$LEDGER" | python3 -c '
import json, sys
rows = [json.loads(line) for line in sys.stdin if line.strip()]
for r in rows:
    label = r["label"] or "LỖI " + str(r["error_cause"])
    print("  " + label.ljust(20) + " " + r["url"][:90])
if rows and all(r["label"] is None for r in rows):
    print("TẤT CẢ đều lỗi: dừng, đừng chạy start; xem log vLLM.")
'
}

follow_log() {
  say "Ctrl-C chỉ thôi xem, lượt chính vẫn chạy nền; dừng: scripts/run_topic.sh stop"
  exec journalctl --user -u "$UNIT" -f -n 30 -o cat
}

cmd_start() {
  if running "$UNIT"; then
    say "lượt chính đang chạy, không bật lần hai"
    follow_log
  fi
  need_quiet_store
  need_vllm
  say "chạy nền: classify (chạy lại thì làm tiếp từ chỗ dừng)"
  systemd-run --user --unit "$UNIT" --same-dir --collect --quiet \
    --setenv=PATH="$PATH" --setenv=QNUCHAT_VLLM_BASE_URL="$VLLM_URL" \
    "${KB[@]}" classify
  follow_log
}

cmd_status() {
  if running "$UNIT"; then say "lượt chính: đang chạy"; else say "lượt chính: không chạy"; fi
  if vllm_up; then say "vLLM: sẵn sàng ở $VLLM_URL"; else say "vLLM: không chạy"; fi
  crawl_busy && warn "kho đang được quét hoặc prune"
  if [[ -f "$POINTER" ]]; then say "mẫu đang dùng: $(cat "$POINTER")"; else say "chưa có mẫu"; fi
  store
  counts
}

need_csv() {
  [[ -n "${1:-}" ]] || die "cần đường dẫn labels.csv, ví dụ ~/Downloads/labels.csv"
  [[ -f "$1" ]] || die "không thấy file $1"
}

with_labels() {
  need_csv "$2"
  local dir
  dir="$(sample_dir)"
  "${KB[@]}" "$1" --sample "$dir" --labels "$2"
}

cmd_prune() {
  running "$UNIT" && die "lượt chính đang chạy; chờ xong hoặc stop rồi mới prune"
  need_quiet_store
  "${KB[@]}" topic-pending
  warn "prune rút các mục trên và XOÁ BLOB VĨNH VIỄN (chỉ lấy lại bằng quét lại web)."
  warn "Nó cũng áp mốc năm và phạm vi như mọi lần prune."
  printf 'Gõ "prune" để tiếp tục: '
  local answer
  read -r answer
  [[ "$answer" == "prune" ]] || die "đã huỷ"
  "${PY[@]}" -m apps.cli.crawl prune
  counts
}

case "${1:-}" in
  status) cmd_status ;;
  sample) cmd_sample "${2:-}" ;;
  check-sample) cmd_check_sample ;;
  topup) cmd_topup "${2:-50}" ;;
  labels) with_labels topic-labels "${2:-}" ;;
  vllm) cmd_vllm ;;
  vllm-stop) systemctl --user stop "$VLLM_UNIT" && say "đã tắt vLLM" ;;
  try) cmd_try ;;
  start) cmd_start ;;
  log) follow_log ;;
  stop) systemctl --user stop "$UNIT" && say "đã dừng; chạy lại bằng: scripts/run_topic.sh start" ;;
  score) with_labels topic-score "${2:-}" ;;
  pending) "${KB[@]}" topic-pending ;;
  prune) cmd_prune ;;
  -h | --help | help | "") sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//' ;;
  *) die "lệnh lạ '$1'; xem: scripts/run_topic.sh help" ;;
esac
