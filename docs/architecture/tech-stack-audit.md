# Tech stack audit — 05/11/2026

**Bản audit này viết trước khi v2 có `pyproject.toml` và `uv.lock`; lockfile v2 lấy từ repo nguồn
nên giữ nguyên các phiên bản bên dưới. Phần lớn stack được kiểm đang ở bản rất mới.** Cần ưu tiên khả năng tái lập và
tương thích; không nâng mọi thư viện lên `latest` trong cùng bước chuyển code.

## 1. Ba lớp bằng chứng

- **V2:** có `pyproject.toml`, `uv.lock`, lõi `src/qnuchat`; chưa có web app và frontend.
  Các version trong RUNBOOK là thông tin kế thừa.
- **Máy:** Python hệ thống 3.14.9, Node 26.13.0, pnpm 12.16.1, uv 0.13.7, Docker 29.9.2.
  Python trong app của repo cũ là **3.12.16**, khác Python hệ thống.
- **Repo nguồn:** đọc `pyproject.toml`, `uv.lock`, `web-ui/package.json`; kiểm installed
  FastAPI/Pydantic/Torch/Transformers/Sentence Transformers/OpenAI SDK trong môi trường app,
  cùng bộ vLLM/Torch/Transformers trong `.venv-vllm`. Không đọc secret.

Phiên bản registry lấy trực tiếp ngày kiểm; bằng chứng máy đọc được ở
[registry-versions-2026-11-05.json](registry-versions-2026-11-05.json).
Khoá dependency là version thật; `>=2.9` trong manifest không có nghĩa đang cài Pydantic 2.9.

## 2. Kết quả đối chiếu

| Thành phần | Repo nguồn / máy | Upstream quan sát được | Đề xuất |
|---|---|---|---|
| Python app | 3.12.16; manifest `>=3.12,<3.13` | [Python 3.15.2](https://www.python.org/downloads/) | Giữ 3.12.16 khi chuyển; nâng interpreter là bước riêng |
| uv | 0.13.7 | [PyPI 0.13.7](https://pypi.org/project/uv/) | Dùng uv cho app, eval, vLLM và OCR |
| Node | 26.13.0 | [26.13.0 LTS](https://github.com/nodejs/node/releases/tag/v26.13.0) | Giữ dòng 26 LTS |
| pnpm | 12.16.1, packageManager pin | [GitHub 12.18.0](https://github.com/pnpm/pnpm/releases/tag/v12.18.0); npm `latest` trả 12.16.1 | Chưa mới nhất theo GitHub; nâng riêng sau kiểm lock/build |
| React / React DOM | lock 19.3.1 | [npm 19.3.1](https://registry.npmjs.org/react/latest) | Khớp |
| TypeScript | lock 7.0.2 | [npm 7.0.2](https://registry.npmjs.org/typescript/latest) | Khớp; giữ khi chuyển UI |
| Vite | lock 8.3.5; manifest `^8.3.5` | [npm 8.3.6](https://registry.npmjs.org/vite/latest) | Có patch mới; range cho phép nhưng lock chưa nâng |
| FastAPI / Uvicorn | lock 0.162.0 / 0.54.0 | [0.162.0](https://pypi.org/project/fastapi/) / [0.54.0](https://pypi.org/project/uvicorn/) | Khớp |
| Pydantic | lock + installed 2.14.2 | [2.14.3](https://pypi.org/project/pydantic/) | Có patch mới; nâng riêng, kiểm schema/API |
| Pydantic Settings | lock 2.16.2 | [2.16.2](https://pypi.org/project/pydantic-settings/) | Khớp |
| SQLAlchemy / Alembic | lock 2.1.8 / 1.20.1 | [2.1.8](https://pypi.org/project/sqlalchemy/) / [1.20.1](https://pypi.org/project/alembic/) | Khớp |
| Psycopg / pgvector Python | lock 3.3.8 / 0.5.1 | [3.3.8](https://pypi.org/project/psycopg/) / [0.5.1](https://pypi.org/project/pgvector/) | Khớp; Python client khác DB extension |
| PostgreSQL | RUNBOOK ghi major 18 | [stable 18.6; 19 RC1](https://www.postgresql.org/docs/release/) | Pin patch + image digest khi tạo infra; chưa xác nhận server đang chạy |
| pgvector extension | RUNBOOK 0.8.7 | [0.8.7](https://github.com/pgvector/pgvector) | Khớp tài liệu; chưa truy vấn extension trong DB |
| vLLM | installed 0.33.0 trong venv riêng | [0.33.0](https://pypi.org/project/vllm/) | Khớp; giữ môi trường riêng |
| Torch / Transformers app | lock + installed 2.15.0 / 5.22.1 | [2.15.0](https://pypi.org/project/torch/) / [5.22.1](https://pypi.org/project/transformers/) | Khớp; không áp các version này vào vLLM |
| Torch / Transformers vLLM | installed 2.14.0+cu132 / 5.20.2 | vLLM pin `torch==2.14.0`, `transformers>=5.16.1,<5.21.0` | Đúng ràng buộc; version thấp hơn là có chủ đích |
| Sentence Transformers | lock + installed 6.2.0 | [6.2.0](https://pypi.org/project/sentence-transformers/) | Giữ; kiểm embedding regression khi nâng |
| NumPy / PyMuPDF | lock 2.5.4 / 2.1 | [2.5.4](https://pypi.org/project/numpy/) / [2.1](https://pypi.org/project/PyMuPDF/) | Khớp |
| Ruff / pytest | lock 0.17.3 / 9.2.0 | [0.17.3](https://pypi.org/project/ruff/) / [9.2.0](https://pypi.org/project/pytest/) | Khớp |

Phạm vi bảng là thành phần chính; chưa phải audit mọi dependency bắc cầu hay mọi npm package.
Trang docs React chỉ ghi minor 19.3, homepage Vite ghi 8.3.4 trong khi registry trả patch mới hơn.
pnpm có lệch giữa dist-tag và release GitHub; báo cáo giữ cả hai nguồn, không suy `latest` luôn
là số phiên bản phát hành lớn nhất.

## 3. uv là lựa chọn quản lý môi trường

uv là công cụ resolve/install/run; PyPI là registry; vLLM là thư viện inference. Chúng bổ sung nhau.
[uv lock/sync](https://docs.astral.sh/uv/concepts/projects/sync/) mô tả `--locked`, `--no-sync`
và nâng một package; lệnh audit test dùng `uv run --no-sync` để không tự cập nhật môi trường cũ.

Thiết kế:

- App: `pyproject.toml` + `uv.lock`, pin Python; group dev/eval và extras web/db/ingest theo nhu cầu.
- Inference: `environments/vllm/pyproject.toml` + `uv.lock` riêng, đã có. Không dùng chung lock với
  app. `torch` phải khai trực tiếp vì `tool.uv.sources` không áp dụng cho dependency bắc cầu; không
  khai thì lock trôi sang Torch PyPI và bộ CUDA khác.
- OCR: project môi trường riêng, chia thêm theo engine khi cần; không trộn Paddle/VietOCR/Torch
  bằng một lệnh upgrade toàn bộ.
- CI và dựng lại máy dùng `uv sync --locked`; nâng một package bằng
  `uv lock --upgrade-package <name>`, review lock diff rồi kiểm regression.

[vLLM](https://docs.vllm.ai/en/stable/getting_started/installation/gpu/) hỗ trợ Python 3.11–3.14
và khuyến nghị môi trường mới do phụ thuộc binary Torch/CUDA. Python 3.15 mới nhất **không** là
lựa chọn hợp lệ cho môi trường vLLM 0.33.0 hiện tại. Trong khi đó giữ app Python 3.12.16 giúp
so sánh migration ít thay đổi hơn; đây là lựa chọn triển khai, không tuyên bố 3.12 là mới nhất.

## 4. OCR và model cần kiểm riêng

Registry có PaddleOCR 3.7.0, PaddleX 3.7.2, VietOCR 0.3.13. Chưa kiểm môi trường OCR cũ nên
không kết luận các engine đã cập nhật. PyPI `paddlepaddle-gpu` trả 2.6.2; không dùng con số này
đại diện bản CUDA phù hợp từ index riêng của Paddle. Phải kiểm hướng dẫn cài và wheel của
engine đã chọn trước khi tạo lock OCR. Đây là mục còn cần compatibility probe.

Qwen3-4B-AWQ và BGE-M3 đang pin revision theo thiết kế nghiên cứu. Model không tuân theo
quy tắc version thư viện; báo cáo không khẳng định đây là model mới nhất hoặc tốt nhất.
Nếu đổi model, cần arm/probe riêng đo VRAM 6 GB, latency và chất lượng tiếng Việt, giữ kết quả
baseline có cùng revision. Không đổi model trong lần chuyển folder.

## 5. Thứ tự thực hiện đề xuất

1. Chuyển phần code cần dùng và khai báo packaging uv dựa trên lock nguồn đã kiểm.
2. Tách môi trường app/vLLM/OCR; ghi rõ version đang cài, version khóa và nguồn wheel.
3. Chạy test tương đương; chốt contract và data provenance.
4. Nâng Pydantic patch/pnpm/Vite nếu resolution thực tế cần; mỗi nhóm thay đổi có kiểm riêng.
5. Probe GPU, live chat, OCR và DB sau đó; không suy các bước này đã đạt từ unit test.

Lúc audit không cài, nâng hoặc đổi dependency của hai repo.
