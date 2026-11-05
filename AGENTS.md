# Hướng dẫn làm việc với v2

Đọc `README.md` và `docs/README.md` để phân biệt hiện trạng với thiết kế đề xuất.
Repo cũ là `../qnu-admission-chatbot`, tag `v1-final`; v2 chỉ có phần đã chọn trong `src/qnuchat`.
Không suy một module đã tồn tại chỉ vì RUNBOOK có lệnh gọi nó.

## CodeGraph

Khi repo có `.codegraph/`, dùng `codegraph explore "<symbol hoặc câu hỏi>"` hoặc MCP
`codegraph_explore` với `projectPath` đúng repo trước khi tìm kiếm/đọc code.
Chạy `codegraph sync` sau thay đổi source. Không đưa secret hoặc index vào Git.

## Graphify

Khi có `graphify-out/graph.json`, dùng graph để tìm quan hệ code/tài liệu.
Phạm vi ở `.graphifyignore`; hướng dẫn tại `docs/guides/code-navigation.md`.
Kiểm source hiện tại trước khi sửa; graph có thể cũ sau một thay đổi chưa sync.

## Quy ước của v2

- Python dùng uv và lockfile; vLLM ở `environments/vllm`, bật bằng `scripts/serve-vllm.sh`; OCR có môi trường riêng.
- Một namespace runtime `qnuchat`; xem mapping ở `docs/architecture/folder-structure.md`.
- Core không import eval, apps, experiments hoặc gold/rubric.
- Lỗi timeout/JSON hỏng là execution error, không biến thành abstention.
- Chuyển code kèm test và provenance; không đổi thuật toán, model và dependency cùng lúc.
- Mặc định không mang code cũ sang; phần mới phải có trong danh sách §3.1 của bản đánh giá.
- Chỉ thêm stage, trường contract hoặc cờ khi có code dùng thật, không tạo chỗ trống trước.
- `tests/core/test_pilot_parity.py` giữ hành vi đã đo; đỏ thì phải cân nhắc chạy lại baseline.
- Không import chéo vào repo cũ hoặc chỉnh `sys.path` để che thiếu package.
- Kiểm tra: `uv run pytest -q`, `uv run ruff check src tests experiments apps`, `uv run lint-imports`.
- Không commit/push khi chưa được yêu cầu.
