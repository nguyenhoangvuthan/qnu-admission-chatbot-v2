# Tài liệu v2

| Tài liệu | Phạm vi | Trạng thái |
|---|---|---|
| [Đánh giá chuyển code](architecture/migration-assessment.md) | Bằng chứng từ repo cũ, danh sách lấy/viết mới/hoãn/bỏ | Đánh giá 05/11/2026; đã làm xong đợt lõi, xem §8 |
| [Folder structure](architecture/folder-structure.md) | Vị trí code, chiều dependency, thứ tự chuyển | Lõi đã theo cấu trúc này; `apps/cli` đã có; `apps/api`, `apps/web`, `migrations/`, `infra/`, `environments/ocr` còn là thiết kế |
| [Tech stack](architecture/tech-stack-audit.md) | Máy hiện tại, lockfile, bản phát hành upstream | Audit 05/11/2026; v2 đã có lockfile giữ nguyên phiên bản đã audit |
| [Manifest chuyển code](architecture/migration-manifest-v1-final.json) | Nguồn → đích, SHA-256 tại `v1-final` | Provenance của đợt lõi |
| [Manifest chuyển crawler](architecture/migration-manifest-crawler-2026-11-06.json) | Nguồn → đích, SHA-256 bản đã chép | Provenance của đợt quét web |
| [Manifest chuyển OCR](architecture/migration-manifest-ocr-2026-11-06.json) | Nguồn → đích, SHA-256 tại `v1-final` | Provenance của đợt OCR |
| [Manifest chuyển lọc chủ đề](architecture/migration-manifest-topic-2026-11-06.json) | Nguồn → đích, SHA-256 tại `v1-final` | Provenance của đợt lọc chủ đề |
| [Công cụ chấm, phần A](superpowers/specs/2026-11-10-eval-phan-a-design.md) | Runner, chấm, báo cáo Wilson cho một cấu hình (RUNBOOK mục 7) | Spec 10/11/2026, chờ Kent duyệt; chưa có code |
| [Tra cứu code](guides/code-navigation.md) | CodeGraph, Graphify, phạm vi chỉ mục | Hướng dẫn dùng công cụ đã khởi tạo |

Mỗi quyết định có một tài liệu sở hữu. `../RUNBOOK.md` chỉ mô tả v2: mục "Chạy được" có code trong
repo này, mục "Chưa có code" là lệnh dự kiến. Không sao chép toàn bộ lịch sử spec/plan.
