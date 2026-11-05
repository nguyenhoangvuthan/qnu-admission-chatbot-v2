# QNU Admission Chatbot v2

Chatbot tư vấn tuyển sinh Trường Đại học Quy Nhơn, dựng lại sạch từ repo cũ.
V2 chỉ chứa phần đã chọn; phần còn lại ở repo cũ, tag `v1-final`.

**Đã có:** lõi `src/qnuchat` (truy hồi BM25 + dense + RRF, pipeline, generator vLLM, ingest PDF,
metric đánh giá, quét web), công cụ gold trong `experiments/`, dữ liệu và benchmark.
**Chưa có:** web app, API, giao diện, database, router SQL, runner đánh giá.

```bash
uv sync
uv run pytest -q
uv run ruff check src tests experiments apps
uv run lint-imports
./scripts/quet-web.sh              # quét web trường vào data/web/; cần QNUCHAT_CRAWL_CONTACT_EMAIL
./scripts/serve-vllm.sh            # bật vLLM; lần đầu cài environments/vllm, khoảng 9 GB
./scripts/thuc-nghiem-live.sh 20   # thực nghiệm với vLLM thật, tự bật vLLM nếu chưa chạy
```

- [Nên chuyển code cũ hay viết lại?](docs/architecture/migration-assessment.md)
- [Cấu trúc thư mục](docs/architecture/folder-structure.md)
- [Kiểm tra tech stack ngày 05/11/2026](docs/architecture/tech-stack-audit.md)
- [Truy vấn CodeGraph và Graphify](docs/guides/code-navigation.md)

[RUNBOOK.md](RUNBOOK.md) là đường đi từ máy trống tới kết quả đề án. Mục ghi "Chưa có code" là lệnh dự kiến.
