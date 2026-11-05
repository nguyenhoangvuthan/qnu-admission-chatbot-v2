# Rà toàn bộ gold đơn lượt: nguồn, ý định và khi nào hỏi lại

**Hoàn tất rà 126 câu; tìm và đọc thêm nguồn web QNU theo các nhóm rủi ro.** Kết quả có
**27 câu cần sửa đã ghi ở lần kiểm snapshot, cùng 11 câu cần xử lý thêm về nguồn/hành vi**.
Tổng danh sách theo dõi là **38 câu**, không có nghĩa 38 đáp án đều sai trên snapshot cũ.
Các câu còn lại vẫn có thể có khuyến nghị về phạm vi; không coi đây là 88 phiếu duyệt mới.

Người rà: **Codex**. Nguồn web đọc ngày 18/10; hoàn tất hồ sơ **19/10/2026** theo ngày của phiên.
Đây là rà soát của agent, không thay xác nhận của Nguyễn Hoàng Vũ Thân. Không sửa nháp,
snapshot, phiếu người duyệt hoặc promote gold. Không chạy mô hình để đo chất lượng trong lần này.

- [Bảng 126 câu: hành động, nguồn cần dùng, lý do và hướng sửa](source-intent-2026-10-19.csv).
- [Hồ sơ có hash từng câu, nguồn web và căn cứ code](source-intent-2026-10-19.json).
- [27 vấn đề câu hỏi/rubric trên snapshot](review-2026-10-18.md).
- [Trang duyệt lịch sử](index.html): vẫn hiển thị 108 đạt/18 cần sửa, chưa phản ánh audit này.

## 1. PIL-037 và PIL-070: đúng câu chữ chưa đủ để tư vấn

Nhận xét của chủ dự án chỉ ra đúng lỗ hổng của lần rà trước: mới kiểm đoạn trích khớp đáp án,
chưa kiểm nguồn có đủ để trả lời **điều kiện giảng dạy** hay không. Hai câu này lấy mục
**Cơ hội việc làm**, trang 66, rồi gán slot `điều kiện giảng dạy`. Đó chưa phải căn cứ đầy đủ
để kết luận sinh viên cụ thể đủ điều kiện đứng lớp.

Cũng cần phân biệt hai mục tiêu:

| Người dùng thực sự hỏi | Cách trả lời phù hợp |
|---|---|
| “Theo cẩm nang 2025, chương trình bổ sung được nêu là gì?” | Trả lời nội dung cẩm nang, nêu rõ giới hạn. Không cần hỏi lại bằng cấp của người hỏi. |
| “Em học Toán ứng dụng, muốn dạy Toán THCS/THPT thì phải làm gì?” | Tra nguồn về chương trình NVSP và điều kiện áp dụng. Nếu cần xét khả năng đăng ký của người này, hỏi đã tốt nghiệp hay đang học; kiểm cấp học, bằng/chuyên ngành và thời điểm áp dụng. |

Đã tìm được **TB2492 ngày 05/08/2025**, đọc trực quan trang 1–2 của PDF có dấu/chữ ký:
mục 2 dành cho người đã có bằng cử nhân chuyên ngành phù hợp muốn trở thành giáo viên THCS/THPT,
chương trình 34 tín chỉ. Thông báo này xác định đối tượng bồi dưỡng; không tự chứng minh một
người được tuyển dụng làm giáo viên. Nguồn: [TB2492](https://upload.qnu.edu.vn/Tempnam2025/eoffice/thang08/ngay06/58e0c108-3ec0-4627-b634-ee2b8cd4314e.pdf).

Đã đọc [CTĐT Toán ứng dụng 2025](https://math.qnu.edu.vn/Resources/Docs/SubDomain/math/Ch%C6%B0%C6%A1ng%20tr%C3%ACnh%20%C4%91%C3%A0o%20t%E1%BA%A1o%20To%C3%A1n%20%E1%BB%A9ng%20d%E1%BB%A5ng%202025.pdf):
mục vị trí việc làm, chuẩn đầu ra và điều kiện tốt nghiệp là các phần khác nhau. Chuẩn đầu ra
không tự thay điều kiện tuyển dụng. Bản công khai còn để trống số/ngày quyết định ở trang đầu,
nên chưa coi đó là quyết định áp dụng đã xác minh. Không chữa lỗi nguồn bằng cách lấy một đoạn
giới thiệu tương tự từ website rồi gọi là điều kiện chính thức.

**Hướng sửa cụ thể:** nếu giữ PIL-037/070 làm bài đọc hiểu, bỏ cách diễn giải slot như điều kiện
đủ để hành nghề và chấm việc giữ giới hạn nguồn. Để đo tư vấn như chủ dự án yêu cầu, dùng câu
đề xuất trong CSV, bổ sung nguồn về NVSP vào snapshot kế tiếp, chấm được bước hỏi tình trạng
tốt nghiệp khi thật sự cần. Câu trả lời không được suy “chỉ cần học NVSP tại QNU là chắc chắn
được dạy/được tuyển dụng”.

## 2. Những phát hiện khi mở rộng sang web

Các nguồn dưới đây là bằng chứng cho việc phải rà lại nguồn/hành vi. Chúng chưa được tự động
nạp vào corpus chính thức hoặc dùng để đổi nhãn trong snapshot `v2-2026-10-14`.

| Câu | Phát hiện và việc cần làm |
|---|---|
| PIL-037, PIL-070 | Tách đọc hiểu cẩm nang khỏi xét điều kiện giảng dạy; xem mục 1. |
| PIL-039 | Trang giới thiệu ngành cũng lặp mô tả cơ hội Master 1/Limoges, chưa phải quy chế cấp học bổng từng đợt. Không chấm việc “hoàn thành Master 1 → chắc chắn có học bổng” như kết luận tư vấn đã xác minh. |
| PIL-043, PIL-055 | Cần xét phiên bản thông báo và phân biệt ngày làm thủ tục/ngày thi; PIL-043 đã thuộc 27 câu cũ, PIL-055 là phát hiện bổ sung. |
| PIL-056, PIL-057 | Có hướng dẫn thi chính thức trên web. Từ chối vì snapshot thiếu nguồn không phải hành vi mặc định đúng cho hệ thống có web. |
| PIL-041, PIL-048 | Bảng ảnh TB2404 có học phí khóa 49. Cần đọc bảng, xác định khóa/chương trình; PIL-048 còn cần học kỳ. Không chia học phí toàn khóa thành các kỳ bằng nhau. |
| ABS-003 | Có thông báo mức thu KTX 2026–2027 và bảng chữ trên trang CTSV. Cần trả lời theo tòa/tầng/đối tượng, hoặc hỏi lựa chọn nếu muốn tính mức riêng. |
| PIL-050 | Có chính sách học bổng 2026 liệt kê Khoa học dữ liệu. Cần phân biệt loại học bổng và điều kiện xét, không suy mọi sinh viên trúng tuyển đều được hưởng. |
| PIL-051 | Có thể giải thích bảng đang có chỉ tiêu chung, chưa xác định được phần riêng cho học bạ. Cần chấm trả lời có giới hạn thay vì coi mọi câu trả lời là sai vì `must_abstain=true`. |

**Lịch thi có khác biệt thực sự về nguồn:** [TB2015](https://qnu.edu.vn/vi/tuyen-sinh-1763/tb2015-ve-viec-huong-dan-thuc-hien-quy-dinh-thi-nang-khieu-giao-duc-mam-non-tuyen-sinh-dai-hoc-chinh-quy-nam-2026)
ngày 17/06 nêu Mầm non làm thủ tục chiều 19/6, thi 20–22/6; gold dùng lịch 19–21/6 từ TB1906.
[TB2008](https://qnu.edu.vn/vi/tuyen-sinh-1763/tb2008-huong-dan-thuc-hien-quy-dinh-thi-nang-khieu-giao-duc-the-chat-tuyen-sinh-dai-hoc-chinh-quy-nam-2026)
có hướng dẫn riêng cho GDTC. Cả hai cũng cung cấp nội dung thi. Đây là lý do phải tìm đúng
thông báo tác nghiệp, không chỉ văn bản tuyển sinh tổng quát.

**Học phí có dữ liệu trong ảnh:** đã xem đủ bốn ảnh của
[TB2404](https://www.qnu.edu.vn/vi/hoc-phi-quy-dinh/tb2404-thong-bao-muc-hoc-phi-tam-tinh-toan-khoa-muc-hoc-phi-tin-chi-hoc-phi-hoc-ky-i-nam-hoc-2026-2027-cho-khoa-49-2026-2030-he-dai-hoc-chinh-quy).
Bảng phân biệt CNTT thường và chương trình tiếng Anh, ghi học phí/tín chỉ và học kỳ I cho khóa 49.
Snapshot HTML chưa có các ô này. Bảng có số tín chỉ khác cẩm nang; cần đối chiếu cách tính
GDTC/GDQP và khóa, chưa được kết luận đó là thay đổi CTĐT chỉ từ hai con số.

**KTX và học bổng:** [TB2417](https://qnu.edu.vn/vi/tuyen-sinh-1763/tb2417-thong-bao-ve-muc-thu-tien-o-ky-tuc-xa-nam-hoc-2026-2027)
xác nhận có công bố mức thu; [trang CTSV](https://hotrosinhvien.qnu.edu.vn/vi/thuc-tap-thuc-te-1147/thong-bao-ve-muc-thu-tien-o-ktx-nam-hoc-2026-2027)
có bảng rút gọn theo tòa/tầng. [Trang chính sách học bổng](https://hotrosinhvien.qnu.edu.vn/vi/tuyen-dung-viec-lam-sinh-vien/thong-tin-ve-chinh-sach-hoc-bong-theo-nghi-dinh-179-2026-nd-cp)
có Khoa học dữ liệu, nhưng cần kiểm đúng loại học bổng khi người dùng hỏi “đầu vào”.

**Chưa xác minh được:** quy định HSK cho đại học chính quy 2026 (kết quả tuyển thạc sĩ không
áp dụng), giờ làm thứ Bảy của phòng tuyển sinh, điều kiện cấp học bổng Limoges của đợt cụ thể.
Không tìm thấy qua các truy vấn đã dùng không chứng minh thông tin không tồn tại.

## 3. Rà đủ 126 câu: chọn hành động theo câu hỏi

Các nhóm là hành động tư vấn đề xuất, **không phải nhãn mới để chạy benchmark**:

| Hành động chính | Số câu | Cách áp dụng |
|---|---:|---|
| Trả lời theo tài liệu được chỉ rõ | 48 | Câu hỏi đọc hiểu “theo Cẩm nang 2025”; vẫn phải giữ giới hạn của nguồn. |
| Trả lời kèm phạm vi | 54 | Quy định/dữ kiện chung đã có căn cứ; nêu năm, khóa, phương thức, đối tượng khi liên quan. |
| Hỏi phạm vi hoặc trình bày các trường hợp | 13 | Thiếu đợt/phương thức hoặc khóa/học kỳ làm thay đổi câu trả lời. Có thể trình bày các nhánh nếu đủ nguồn. |
| Đối chiếu nguồn phù hợp trước khi kết luận | 6 | Lịch/nội dung thi, học bổng, KTX có nguồn web cần đưa vào quá trình đối chiếu. |
| Trả lời phần có căn cứ | 2 | ABS-002, PIL-051; không bịa phần thiếu và không từ chối bỏ hết phần trả lời được. |
| Nêu giới hạn, không đoán | 3 | ABS-001, ABS-004, PIL-047 trong phạm vi bằng chứng đã kiểm. |
| **Tổng** | **126** | CSV có từng mã, hash, lý do, nguồn và hành động. |

PIL-037/039/070 nằm trong nhóm đọc hiểu vì câu hiện tại **chỉ rõ cẩm nang**; chính sự đóng khung
này phải sửa nếu muốn kiểm khả năng tư vấn thực tế. Không ép model hỏi lại những gì câu hỏi đã nêu.
PIL-038/040 đã có lời giới hạn trong đáp án mẫu, nên không quy tất cả câu về nghề nghiệp thành sai;
cần thêm kiểm tra chống biến lời giới thiệu thành cam kết trong rubric.

CMP-001–008 và CMP-017 cần nêu cơ sở chương trình năm 2025 khi trả lời; khi hỏi cho khóa hiện tại
thì tra CTĐT của khóa đó. Các câu thiếu đợt đã liệt kê ở báo cáo 18/10 vẫn cần sửa. Không đổi
các câu hỏi điều kiện tuyển sinh chung thành phỏng vấn điểm/học lực của từng người nếu họ chưa
hỏi “em có đủ điều kiện không”.

Riêng **NEW-003**, giữ nguyên xác nhận của chủ dự án về sáu cặp mã/phương thức. Việc còn lại là
agent sửa rubric chấm cả mã lẫn tên và phạm vi ngành giáo viên; không yêu cầu người dùng duyệt lại
những cặp đã xác nhận.

## 4. Vì sao có cảm giác SLM chỉ bám tài liệu?

Có căn cứ trong cấu hình và code hiện tại, chưa cần quy nguyên nhân cho kích thước model:

1. **Đầu vào bị giới hạn.** Cấu hình web kế thừa
   [b3-qwen3-4b-awq.yaml](../../../configs/pipeline/b3-qwen3-4b-awq.yaml), vẫn nạp một PDF Cẩm nang
   2025. Có crawler trong dự án không có nghĩa kho web đã được nối vào đường trả lời này.
   [build_runtime](../../../src/qnuchat/core/adapters/legacy_runtime.py) đọc PDF và tạo index từ đó.
2. **Prompt yêu cầu chỉ dùng tài liệu được cấp.**
   [qnu_rag/generate.py](../../../qnu_rag/generate.py) quy định thiếu/không liên quan/mâu thuẫn thì
   abstain; schema generator không có hành động tìm nguồn hay hỏi làm rõ. Generator hiện không
   được cấp công cụ duyệt web. Mô hình không thể tự tìm một thông báo mà pipeline không đưa vào.
3. **Hỏi lại hiện hẹp.** [rewrite.py](../../../src/qnuchat/core/rewrite.py) chủ yếu kiểm ngành/năm;
   danh mục một năm có thể mặc định năm đó. Chưa có quyết định hỏi tình trạng tốt nghiệp, khóa,
   học kỳ hoặc đợt/phương thức dựa trên tác động tới câu trả lời.
4. **Chưa có bước đang hoạt động để chọn loại nguồn theo ý định.**
   [assemble_pipeline](../../../src/qnuchat/core/pipeline.py) để `query_understanding`, `routing`,
   `authority_policy`, `verification` ở `DisabledStage`. Truy hồi gần nghĩa có thể tìm đúng đoạn
   “giảng dạy” nhưng chưa bảo đảm đó là nguồn đủ thẩm quyền cho câu hỏi điều kiện.
5. **Gold và cách rà trước thiên về đọc hiểu.** Nhiều câu cài sẵn “theo cẩm nang”; single-turn có
   `must_abstain` nhưng chưa mô tả được hết hỏi lại/trả lời một phần/xác minh nguồn. Các phản ví dụ
   T1/T4 ở báo cáo 18/10 cho thấy đúng slot chưa đủ phát hiện sai quan hệ điều kiện. Bộ gold là
   công cụ đánh giá, không tự huấn luyện model; nó có thể thưởng/chọn hành vi không mong muốn khi
   dùng để tối ưu. Với agent soạn/duyệt gold, việc bỏ sót loại nguồn cũng là lỗi quy trình rà soát.

Qwen3-4B-AWQ, lượng tử hóa và cấu hình thinking có thể ảnh hưởng khả năng suy luận, nhưng chưa có
thử nghiệm đối chứng trong lần này để quy lỗi cho các yếu tố đó. Tăng kích thước model không tự
sửa việc thiếu nguồn, thiếu đường hỏi lại và rubric chấm chưa đúng mục tiêu.

## 5. Hướng xử lý sau audit

Giữ nguyên yêu cầu bám bằng chứng. Bổ sung quyết định **bằng chứng nào phù hợp với điều đang hỏi**:
tra CTĐT/chuẩn đầu ra cho tốt nghiệp; thông báo NVSP/điều kiện áp dụng cho bồi dưỡng; thông báo
tuyển dụng cho vị trí cụ thể; thông báo thi mới và đúng ngành cho lịch/nội dung thi.

Hỏi lại khi **thiếu dữ kiện của người dùng** có thể đổi đáp án. Tìm/đọc thêm nguồn khi **thiếu bằng
chứng của hệ thống**. Nếu chỉ biết một phần thì trả lời phần đó, nêu giới hạn. Không mặc định mọi
câu đều phải hỏi thêm, cũng không cho phép dùng kiến thức nhớ sẵn để bù quy định còn thiếu.

Các nguồn tìm được lần này phải đi qua ingest/OCR, provenance và snapshot mới trước khi dùng
trong thực nghiệm. Sau đó sửa câu hỏi, đáp án, nhãn hành động và rubric theo snapshot được chọn,
kiểm các cặp câu đọc hiểu/tư vấn cùng chủ đề, rồi duyệt phiên bản mới theo hash. Audit này hoàn tất
việc rà và đề xuất sửa; **chưa triển khai router, chưa thay prompt hay gold chính thức**.

## 6. Phạm vi và bằng chứng kiểm tra

Đã đọc câu hỏi/đáp án của cả 126 câu, kiểm rubric các nhóm rủi ro và kế thừa 27 nhận xét có bằng
chứng từ lần 18/10. Có 12 mục nguồn web được ghi rõ URL và giới hạn trong JSON; TB2404 có thêm
bốn URL ảnh bảng. Tìm web theo chủ đề NVSP/CTĐT, cơ hội/học bổng, năng khiếu, học phí, KTX, HSK
và giờ làm việc. Đây không phải crawl toàn bộ tên miền hoặc xác minh mới độc lập mọi số liệu của
126 câu. Các ô `web_check` phân biệt câu đã đối chiếu web với câu kế thừa kiểm snapshot.

Hash của hai file nháp, snapshot, hai phiếu người duyệt và trang duyệt lịch sử được ghi trong JSON.
Không dùng tên người duyệt để xác nhận kết luận của agent. STORM Brains4Ai có công cụ marketing/
sản phẩm và workflow không phù hợp kiểm nguồn tuyển sinh trong phiên; audit dùng công cụ web
và đọc repo trực tiếp, không ghi rằng STORM đã duyệt.

Kiểm tra cuối: `prepare_gold check --profile v2` đạt **126/126**; CSV đủ 126 mã duy nhất;
19 hash nguồn snapshot không đổi; hash nháp/phiếu người duyệt khớp; 9 liên kết nội bộ trong
báo cáo hợp lệ; `git diff --check` sạch. Chỉ kiểm dữ liệu/hồ sơ, không chạy lại test ứng dụng
vì lần này không sửa code ứng dụng.
