# Tra cứu CodeGraph và Graphify

CodeGraph đã khởi tạo tại root v2. Graphify tạo graph cho code, YAML cấu hình và tài liệu phát triển.
File `.graphifyignore` loại secret, PDF/DOCX/XLSX, ảnh, dataset JSON/CSV và HTML sinh ra.
Đây là graph kiến trúc; kho dữ liệu tuyển sinh vẫn cần pipeline RAG riêng.

## Tìm source và ảnh hưởng thay đổi

Chạy từ root v2:

```bash
codegraph status
codegraph explore 'HybridRetriever rrf_fuse'
codegraph explore 'QnuChatPipeline assemble_pipeline'
codegraph sync
```

MCP `codegraph_explore` dùng `projectPath` tuyệt đối của repo cần xem. Với repo nguồn,
truyền `/home/kent/KentProject/qnu-admission-chatbot`; không nhầm với v2.

## Tìm quan hệ giữa tài liệu và code

```bash
graphify query 'pipeline retrieval passage' --budget 2000
graphify explain 'rrf_fuse'
graphify export html
```

Mở `graphify-out/graph.html`; dữ liệu là `graph.json`, báo cáo là `GRAPH_REPORT.md`.
Query dùng tên symbol/từ có trong label vì CLI không tự hiểu đồng nghĩa hay dịch tiếng Việt.
`EXTRACTED` là quan hệ đọc trực tiếp; `INFERRED` là suy luận có confidence.
Quan hệ từ RUNBOOK mô tả hệ thống cũ/đích, không chứng minh module đó có trong v2.

Sau sửa code: `codegraph sync` và `graphify update .` cập nhật phần AST; đọc output để biết
phần tài liệu nào chưa được semantic extraction. Sau đổi tài liệu, yêu cầu skill Graphify
`--update` để xử lý phần semantic bằng agent, hoặc dùng backend đã cấu hình.
Không cần thêm API key để dùng skill với agent hiện tại.

`.codegraph/` và `graphify-out/` được ignore trong Git vì là output local. Commit `.graphifyignore`
và tài liệu hướng dẫn để người khác dựng lại phạm vi giống nhau. Không cài hook tự động trong lần này.
