#!/usr/bin/env bash
# Thực hiện plan công cụ chấm phần A (docs/superpowers/plans/2026-11-11-eval-phan-a.md), mỗi task một phiên Claude Code
# không tương tác. Sau mỗi task, script tự kiểm lại rồi commit; không push.
#
#   scripts/thuc-hien-plan-cham-a.sh              chạy Task 1 tới 7, rồi review toàn bộ
#   scripts/thuc-hien-plan-cham-a.sh 4            chạy tiếp từ Task 4 (sau khi một task dừng giữa chừng)
#   scripts/thuc-hien-plan-cham-a.sh 4 4          chỉ chạy Task 4
#   scripts/thuc-hien-plan-cham-a.sh review       chỉ chạy bước review
#
# Biến môi trường:
#   NO_COMMIT=1        không commit sau mỗi task (task sau vẫn chạy trên thay đổi chưa commit)
#   CLAUDE_MODEL=...   model cho phiên làm task, mặc định để claude tự chọn
#
# Task 8 cần vLLM và người đọc tay nên không chạy ở đây; script in lệnh ở cuối.
# Log từng task: artifacts/logs/plan-cham-a/. Chạy bằng bash nên gọi được từ fish.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

PLAN=docs/superpowers/plans/2026-11-11-eval-phan-a.md
SPEC=docs/superpowers/specs/2026-11-10-eval-phan-a-design.md
LOG_DIR=artifacts/logs/plan-cham-a
BASE_FILE="$LOG_DIR/base-commit"
LAST_TASK=7

# Commit của từng task, lấy từ bước Commit trong plan.
declare -A MESSAGE=(
  [1]="Thêm khoảng Wilson 95% cho tỷ lệ (chấm phần A)"
  [2]="Metric truy hồi so theo cặp nguồn và trang"
  [3]="Đọc bộ câu hỏi nháp và chọn câu theo nguồn trong kho"
  [4]="Xếp mỗi câu vào một nhóm kết quả (spec §4.1)"
  [5]="Runner chạy từng câu, ghi kết quả thô và chạy tiếp được"
  [6]="Chấm lượt chạy thành report.json và report.md có Wilson 95%"
  [7]="Thêm lệnh evaluate run/score (RUNBOOK mục 7, phần A)"
)

say() { printf '\n==> %s\n' "$*"; }
die() { printf 'LỖI: %s\n' "$*" >&2; exit 1; }

CURRENT_TASK=
on_exit() {
  local code=$?
  if [[ $code -ne 0 && -n "$CURRENT_TASK" ]]; then
    printf '\nTask %s không đạt, chưa commit. Xem %s/task-%s.log, sửa rồi chạy: %s %s\n' \
      "$CURRENT_TASK" "$LOG_DIR" "$CURRENT_TASK" "$0" "$CURRENT_TASK" >&2
  fi
}
trap on_exit EXIT

# Thay đổi ngoài thư mục .playwright-mcp/ (Kent tải file duyệt vào đó, không bao giờ commit).
dirty() { git status --porcelain --untracked-files=all | grep -v ' \.playwright-mcp/' || true; }

check_all() {
  say "Kiểm: pytest, ruff, lint-imports"
  uv run --frozen pytest -q
  uv run --frozen ruff check src tests experiments apps
  uv run --frozen lint-imports
  # Spec §2: không đụng core.
  if [[ -n "$(git status --porcelain -- src/qnuchat/core)" ]]; then
    die "Task đã sửa src/qnuchat/core; plan cấm. Xem: git status src/qnuchat/core"
  fi
}

task_prompt() {
  cat <<EOF
Thực hiện đúng Task $1 trong $PLAN, không làm task khác. Đọc phần đầu plan (Global Constraints, Review Focus) và spec
$SPEC trước. Làm theo superpowers:test-driven-development: viết test hỏng, chạy thấy hỏng, viết code, chạy thấy xanh.
Các task trước đã xong trong working tree; dùng đúng tên và kiểu trong khối Interfaces của chúng.

Ràng buộc:
- Không sửa src/qnuchat/core/, không thêm dependency, không sửa uv.lock.
- Không commit, không push, không chạy lệnh git làm đổi trạng thái; script bên ngoài sẽ commit.
- Không đụng .playwright-mcp/, data/, benchmarks/.
- Không ai đọc phiên này trong lúc chạy: viết đủ code, không chừa TODO hay chỗ trống cho người dùng tự viết, không hỏi lại.
- Kết thúc khi uv run pytest -q, uv run ruff check src tests experiments apps, uv run lint-imports đều xanh.
- Nếu plan mâu thuẫn với code hiện có hoặc không làm được, dừng và ghi rõ lý do ở dòng cuối, bắt đầu bằng "DỪNG:".

Cuối cùng in tóm tắt: file đã tạo/sửa, số test mới, kết quả ba lệnh kiểm.
EOF
}

run_claude() {  # $1 = tên log, $2 = prompt, các tham số còn lại đưa thẳng cho claude
  local name=$1 prompt=$2; shift 2
  local log="$LOG_DIR/$name.log"
  local model=()
  [[ -n "${CLAUDE_MODEL:-}" ]] && model=(--model "$CLAUDE_MODEL")
  say "Claude: $name (log: $log)"
  claude -p "$prompt" "${model[@]}" --output-format text "$@" 2>&1 | tee "$log"
  if grep -q '^DỪNG:' "$log"; then
    die "Claude dừng ở $name: $(grep '^DỪNG:' "$log" | tail -1)"
  fi
}

run_task() {
  local n=$1
  run_claude "task-$n" "$(task_prompt "$n")" \
    --permission-mode acceptEdits \
    --allowedTools "Read" "Edit" "Write" "Glob" "Grep" "Skill" \
    "Bash(uv run:*)" "Bash(git status:*)" "Bash(git diff:*)" "Bash(git log:*)" "Bash(ls:*)" "Bash(wc:*)"
  check_all
  if [[ -n "${NO_COMMIT:-}" ]]; then
    say "Task $n xong, chưa commit (NO_COMMIT=1)"
    return
  fi
  git add -A -- src tests apps docs scripts RUNBOOK.md README.md
  if git diff --cached --quiet; then
    say "Task $n không có thay đổi để commit"
  else
    git commit -q -m "${MESSAGE[$n]}"
    say "Task $n đã commit: $(git log -1 --format='%h %s')"
  fi
}

run_review() {
  local base
  base=$(cat "$BASE_FILE" 2>/dev/null || true)
  [[ -n "$base" ]] || die "Không có $BASE_FILE; chạy từ Task 1 để script ghi commit gốc."
  run_claude review "$(cat <<EOF
Review toàn bộ thay đổi từ commit $base tới working tree hiện tại (git diff $base) so với plan $PLAN và spec $SPEC.
Không sửa file nào. Tìm: yêu cầu của spec chưa có code, chỗ lệch Interfaces giữa các task, năm mục Review Focus đã có
test chưa, lỗi chấm làm sai số đo (nhất là contradicts và classify), chỗ PipelineError bị tính là từ chối.
Xếp phát hiện từ nặng tới nhẹ, mỗi phát hiện ghi file:dòng, tình huống làm sai, cách sửa. Không có gì thì ghi rõ.
EOF
)" --permission-mode default \
    --allowedTools "Read" "Glob" "Grep" "Bash(git diff:*)" "Bash(git log:*)" "Bash(git show:*)" "Bash(uv run:*)"
}

usage() { sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; }

main() {
  command -v claude >/dev/null || die "không thấy lệnh claude"
  command -v uv >/dev/null || die "không thấy lệnh uv"
  [[ -f "$PLAN" ]] || die "không thấy $PLAN"
  mkdir -p "$LOG_DIR"

  case "${1:-}" in
    -h|--help) usage; exit 0 ;;
    review) run_review; exit 0 ;;
  esac

  local from=${1:-1} to=${2:-$LAST_TASK}
  [[ "$from" =~ ^[1-7]$ && "$to" =~ ^[1-7]$ && "$from" -le "$to" ]] || die "task phải trong 1..7, từ ≤ đến"

  if [[ "$from" == 1 ]]; then
    [[ -z "$(dirty)" ]] || die "working tree còn thay đổi chưa commit; commit hoặc stash trước:
$(dirty)"
    git rev-parse HEAD > "$BASE_FILE"
    say "Commit gốc: $(cat "$BASE_FILE")"
  fi

  # Không viết `run_task || die`: trong vế trái của `||`, bash bỏ qua `set -e` nên pytest đỏ vẫn đi tới commit.
  for ((n = from; n <= to; n++)); do
    say "Task $n/$LAST_TASK: ${MESSAGE[$n]}"
    CURRENT_TASK=$n
    run_task "$n"
  done
  CURRENT_TASK=

  [[ "$to" == "$LAST_TASK" ]] && run_review

  cat <<EOF

==> Xong Task $from–$to. Đọc review: $LOG_DIR/review.log
Task 8 (kiểm trên dữ liệu thật) chạy tay:
  uv run python -m apps.cli.evaluate run --mode retrieval --run-id dev-r3-retrieval
  uv run python -m apps.cli.evaluate score dev-r3-retrieval     # mong đợi 67 câu, excluded.jsonl 59 dòng
  ./scripts/serve-vllm.sh                                        # terminal khác
  uv run python -m apps.cli.evaluate run --mode full --run-id dev-b3-full
  uv run python -m apps.cli.evaluate score dev-b3-full
Push khi đã đọc review: git push origin main
EOF
}

main "$@"
