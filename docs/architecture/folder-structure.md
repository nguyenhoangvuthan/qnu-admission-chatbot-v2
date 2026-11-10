# Cấu trúc thư mục đề xuất cho v2

Chọn một package Python `qnuchat`, layout `src`, chia theo trách nhiệm. Giữ tên `core`,
`ingest`, `eval` quen thuộc của dự án cũ. `apps/` chỉ chứa điểm khởi động và giao diện.
Đây là **cây đích**. Đã có: `src/qnuchat` (lõi, quét web), `apps/cli`, `configs/pipeline`, `configs/catalog`, `configs/crawl`, `tests/`,
`pyproject.toml`, `uv.lock`, `environments/vllm`, `scripts/`. Các mục khác chỉ tạo khi có code thật.

```text
qnu-admission-chatbot-v2/
├── README.md                    # Điểm vào duy nhất
├── AGENTS.md                    # Cách tra cứu và ranh giới code
├── pyproject.toml               # Python app + nhóm dev/eval/ingest/web/db
├── uv.lock                      # Lock môi trường app; commit
├── .python-version              # Pin interpreter đã kiểm
├── .env.example                 # Tên biến + giá trị mẫu, không có secret
├── src/qnuchat/
│   ├── documents.py            # Page, Passage: kiểu chung của ingest và core
│   ├── core/
│   │   ├── contracts.py         # Query, Answer, Trace, Citation
│   │   ├── ports.py             # Giao diện retriever/generator/store
│   │   ├── errors.py
│   │   ├── pipeline.py
│   │   ├── stages/              # query_rewrite, retrieval, fusion, generation
│   │   ├── retrieval/           # BM25, dense, fusion, hybrid; file theo thuật toán
│   │   ├── routing/             # Chọn RAG/SQL; chỉ thêm khi triển khai
│   │   └── policies/            # Phạm vi ngành/năm, từ chối, evidence
│   ├── adapters/
│   │   ├── generation/         # Client vLLM, prompt/schema, stream
│   │   ├── embeddings/         # BGE + cache
│   │   ├── storage/            # SQL/pgvector repositories
│   │   └── runtime.py          # Nối nguồn, embedder, index, client theo cấu hình
│   ├── ingest/                 # Source registry, extract, OCR, chunk, snapshot
│   └── eval/                   # Gold schema, arms, runner, metrics, reports
├── apps/
│   ├── api/                    # FastAPI routes, wiring, settings, __main__
│   ├── cli/                    # Lệnh ingest/evaluate; gọi library
│   └── web/                    # React + TS + Vite, package.json, pnpm-lock.yaml
├── configs/
│   ├── pipeline/               # Cấu hình runtime
│   ├── catalog/                # Ngành/năm/bí danh
│   └── experiments/            # Ma trận arm và probe
├── environments/
│   ├── vllm/                   # pyproject.toml + uv.lock độc lập
│   └── ocr/                    # pyproject.toml + uv.lock độc lập; Paddle + VietOCR
├── migrations/                 # Một lịch sử Alembic cho DB ứng dụng
├── infra/                      # Compose, cấu hình service/container
├── scripts/                    # Setup, migrate, serve; không giữ nghiệp vụ
├── tests/
│   ├── core/
│   ├── adapters/
│   ├── ingest/
│   ├── eval/
│   ├── api/
│   ├── architecture/           # Kiểm chiều import
│   └── fixtures/               # Mẫu nhỏ, không tải model ở unit test
├── data/
│   ├── sources.yaml            # Registry nguồn hiện tại, giữ đường dẫn
│   ├── tuyen-sinh-dai-hoc-chinh-quy/
│   ├── hoc-phi/
│   ├── ky-tuc-xa/
│   ├── giao-duc-quoc-phong/
│   └── ocr-data/               # Dữ liệu OCR đã chuyển, có provenance
├── benchmarks/                 # Gold + review có version, không lẫn core
├── experiments/                # Script cũ/chưa ổn định; chuyển dần
├── artifacts/                  # Run/cache/log phát sinh, không commit mặc định
│   └── runs/<run_id>/          # manifest, raw, metrics, report
├── docs/
│   ├── README.md
│   ├── architecture/           # Quyết định + đánh giá; một nơi sở hữu
│   └── guides/                 # Hướng dẫn đã chạy kiểm chứng
├── .codegraph/                 # Index local
└── graphify-out/               # Graph JSON/HTML/report local
```

## Chiều phụ thuộc

`apps → adapters → core`; `apps → core`; `eval → core/ports` và adapter tại điểm lắp ghép
offline; `ingest` không import `eval`, `apps` hoặc pipeline chat. Core không import adapter,
FastAPI, SQLAlchemy, eval, benchmark hay experiments. Khi cần kiểu dữ liệu dùng chung, đặt
module model độc lập rõ tên; không kéo toàn bộ core vào ingest chỉ để lấy một dataclass.

Adapter nằm ở `qnuchat/adapters`, không còn trong `core`. `pyproject.toml` kiểm các chiều này bằng
import-linter.
Wiring thuộc app, hoặc factory được eval gọi rõ ràng; core nhận dependency qua ports.

`apps` chứa Python phải được khai báo rõ trong wheel build (kế thừa cách packaging nguồn),
loại `apps/web` frontend khỏi Python wheel. Kiểm wheel ngoài working directory là cổng hoàn tất.

## Quy tắc giúp tìm nhanh

- Tên file thể hiện tác vụ: `fusion.py`, `source_registry.py`, `run_manifest.py`;
  tránh gom logic vào `utils.py`, `common.py`, `manager.py`.
- Tìm theo luồng: API route → service/wiring → pipeline → port → adapter.
- Test song hành với module; fixture nhỏ chung, gold nghiên cứu ở `benchmarks/`.
- Source ID ổn định qua việc đổi folder; đường dẫn là thuộc tính trong registry.
  Không đổi layout dữ liệu theo sở thích trước khi sửa resolver và kiểm SHA-256.
- Giữ tên/thư mục raw data tiếng Việt hiện có. Mã nguồn mới dùng tên ASCII nhất quán.
- Chỉ mở thêm subpackage khi có code và trách nhiệm thật. Không tạo hàng loạt folder rỗng.
- `environments/vllm` và OCR là uv project độc lập, **không** nhập chung resolution workspace
  với app: các engine có thể đòi Torch/CUDA khác nhau.

## Mapping chuyển code

Bảng này chỉ cho biết đích của từng phần. Phần nào được vào v2 và lúc nào do
[danh sách §3.1](migration-assessment.md#31-danh-sách-lấy-viết-mới-hoãn-bỏ) quyết định.

| Nguồn cũ | Đích đề xuất | Điều kiện |
|---|---|---|
| `qnu_rag/index.py` | `core/retrieval/*` + `adapters/embeddings/*` | Giữ retrieval regression |
| `qnu_rag/generate.py` + legacy adapter | `adapters/generation/*` | Giữ request/error contract |
| `qnu_rag/schema.py` | `core/contracts.py` + `eval/schema.py` | Không lộ GoldItem vào core |
| `qnu_rag/corpus.py`, `chunking.py` | `ingest/*`; gold loader vào eval | Version hoá chunk/source ID |
| `qnu_rag/metrics`, `stats.py` | `eval/*` | Chỉ metric còn dùng; metric pilot ở lại repo cũ |
| `qnu_rag/arms.py`, `legacy_*` | Không chuyển | Arm mới theo YAML; adapter mới thay `legacy_*` |
| `src/qnuchat/core` | `src/qnuchat/core`, `adapters` | Viết gọn contract, bỏ stage của hướng đã bỏ |
| `src/qnuchat/ingest` | `src/qnuchat/ingest` | Đã chuyển 06/11/2026 |
| `apps/web` | `apps/api` | Cập nhật imports, OpenAPI export, migration path, static mount |
| `web-ui` | `apps/web` | Cập nhật đường dẫn generated API, build output và e2e |
| `apps/crawler` | `apps/cli/crawl.py` + `ingest/crawl_job.py`, `crawl_log.py` | Đã chuyển 06/11/2026 |
| `experiments/ocr_selection` (đường `cur_rotgate`) | `ingest/ocr/`, `apps/cli/ocr.py`, `environments/ocr` | Đã chuyển 06/11/2026; phần chọn cấu hình ở lại repo cũ |
| `apps/knowledge_base` (lọc chủ đề) | `ingest/topic_filter/`, `apps/cli/knowledge_base.py` | Đã chuyển 06/11/2026 |
| `apps/knowledge_base` (ảnh người, snapshot) | `apps/cli` + library ingest | Hoãn; không trộn CLI và nghiệp vụ |
| `data/ocr-data/*.py` | `scripts/data/*` hoặc library ingest | Sửa đường dẫn và kiểm export trước khi dời |

Đổi tên `apps/web`/`web-ui` là bước cuối riêng biệt khi chuyển ứng dụng, không bắt buộc để
hoàn tất chuyển lõi. Nếu chi phí đổi đường dẫn vượt lợi ích ngay lúc đó, giữ tên cũ tạm và ghi
mapping tại đây. Điều quan trọng là một nơi sở hữu mỗi chức năng và chiều import được kiểm.
