#!/usr/bin/env bash
# Quét web trường vào data/web/. Không cần GPU, không cần database.
#
#   ./scripts/quet-web.sh           quét trong terminal này, có thanh tiến độ
#   ./scripts/quet-web.sh start     quét nền (systemd), đóng terminal vẫn chạy
#   ./scripts/quet-web.sh log       xem lần quét nền; Ctrl-C chỉ thôi xem, không dừng quét
#   ./scripts/quet-web.sh stop      dừng lần quét nền, chạy lại thì làm tiếp
#   ./scripts/quet-web.sh status    các lần quét gần nhất và dung lượng kho
#   ./scripts/quet-web.sh prune     áp lại min_year và danh sách chặn lên kho, xoá blob đã rút
#   ./scripts/quet-web.sh check     chỉ kiểm điều kiện, chưa quét
#
# Cần QNUCHAT_CRAWL_CONTACT_EMAIL trong .env: email này đi trong User-Agent để site trường biết ai
# đang quét. Dừng giữa chừng bằng Ctrl-C hay `stop` đều lưu hàng đợi, lần sau chạy tiếp.
# Mã thoát của lệnh quét: 0 xong, 1 lỗi, 2 thiếu biến môi trường, 3 đang có lần quét khác, 130 bị dừng.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

UNIT=qnu-crawl
STORE=data/web
MIN_FREE_GIB=5
PROBE_URL=https://tuyensinh.qnu.edu.vn/
RUN=(uv run --frozen python -m apps.cli.crawl)

say() { printf '==> %s\n' "$*"; }
die() { printf 'LỖI: %s\n' "$*" >&2; exit 1; }
background_running() { systemctl --user is-active --quiet "$UNIT"; }

check_contact() {
  [[ -n "${QNUCHAT_CRAWL_CONTACT_EMAIL:-}" ]] && return 0
  [[ -f .env ]] && grep -Eq '^QNUCHAT_CRAWL_CONTACT_EMAIL=.{3,}' .env && return 0
  die "thiếu QNUCHAT_CRAWL_CONTACT_EMAIL; thêm vào .env:
  printf \"QNUCHAT_CRAWL_CONTACT_EMAIL='<email liên hệ>'\\n\" >> .env"
}

# Hai crawler cùng lúc làm site trường nhận gấp đôi tải, kể cả khi chúng ghi vào hai kho khác nhau,
# nên ngoài crawl.lock còn phải dò tiến trình.
check_idle() {
  if [[ -f "$STORE/crawl.lock" ]] && ! flock -n "$STORE/crawl.lock" true; then
    die "kho $STORE đang được quét hoặc prune; chờ xong rồi chạy lại"
  fi
  local others
  # Neo vào đầu dòng lệnh: không thì khớp cả shell có chuỗi này trong tham số, báo nhầm.
  others="$(pgrep -af '^[^ ]*python[0-9.]* -m apps[.a-z_]*crawl[a-z]* run' || true)"
  [[ -z "$others" ]] || die "đang có crawler khác chạy trên máy này:
$others"
}

check_disk() {
  mkdir -p "$STORE"
  local free
  free="$(df --output=avail -BG "$STORE" | tail -n 1 | tr -dc '0-9')"
  (( free >= MIN_FREE_GIB )) || die "ổ đĩa chỉ còn ${free} GiB, cần ít nhất ${MIN_FREE_GIB} GiB"
}

check_network() {
  curl -sS -m 15 -o /dev/null --head "$PROBE_URL" || die "không kết nối được $PROBE_URL"
}

preflight() {
  command -v uv >/dev/null || die "thiếu uv"
  command -v curl >/dev/null || die "thiếu curl"
  check_contact
  check_idle
  check_disk
  check_network
}

case "${1:-run}" in
  run)
    preflight
    say "Quét vào $STORE; Ctrl-C để dừng, chạy lại thì làm tiếp"
    "${RUN[@]}" run --trigger cli
    ;;
  start)
    preflight
    systemd-run --user --unit "$UNIT" --same-dir --collect --quiet --setenv=PATH="$PATH" \
      "${RUN[@]}" run --trigger cli
    say "Đang quét nền. Xem: ./scripts/quet-web.sh log; dừng: ./scripts/quet-web.sh stop"
    ;;
  log)
    journalctl --user -u "$UNIT" -n 20 -f -o cat
    ;;
  stop)
    background_running || die "không có lần quét nền nào đang chạy"
    systemctl --user stop "$UNIT"
    say "Đã dừng; hàng đợi lưu ở $STORE/frontier.jsonl"
    ;;
  status)
    if background_running; then say "Đang quét nền"; else say "Không có lần quét nền"; fi
    "${RUN[@]}" status
    say "Dung lượng kho: $(du -sh "$STORE" 2>/dev/null | cut -f1)"
    ;;
  prune)
    check_idle
    "${RUN[@]}" prune
    ;;
  check)
    preflight
    say "Đủ điều kiện quét"
    ;;
  *)
    die "lệnh không có: '$1'; xem đầu file scripts/quet-web.sh"
    ;;
esac
