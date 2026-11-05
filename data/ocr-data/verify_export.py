"""Đối chiếu toàn bộ bản xuất với kết quả gốc, bao gồm nội dung và provenance."""

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

from export_results import digest, read, write_json


def main():
    dest = Path(__file__).resolve().parent
    summary = read(dest / 'audit/summary.json')
    source = Path(summary['source_directory'])
    with (dest / 'audit/file_inventory.csv').open(encoding='utf-8-sig', newline='') as stream:
        inventory = list(csv.DictReader(stream))
    actual_files = {p.relative_to(source).as_posix() for p in source.rglob('*') if p.is_file()}
    assert actual_files == {row['source_file'] for row in inventory}
    for row in inventory:
        path = source / row['source_file']
        assert digest(path) == row['sha256'], path
        assert path.stat().st_size == int(row['bytes']), path
    assert dict(Counter(row['status'] for row in inventory)) == summary['file_status_counts']

    with (dest / 'reference/ocr_candidates.jsonl').open(encoding='utf-8') as stream:
        candidates = [json.loads(line) for line in stream]
    assert len(candidates) == summary['complete_ocr_candidates']
    assert len({row['source_file'] for row in candidates}) == len(candidates)
    by_id = {row['record_id']: row for row in candidates}
    for row in candidates:
        raw = read(source / row['source_file'])
        assert row['result'] == raw
        assert row['benchmark_set'] != 'S2'
        assert 'error' not in raw
        assert raw.get('finish_reason') in (None, 'stop')
        assert row['text'].strip()
        assert row['text'] == '\n'.join(line['text'] for line in raw['lines'])
        assert row['text_sha256'] == hashlib.sha256(row['text'].encode()).hexdigest()
        assert row['line_count'] == len(raw['lines'])

    corpus = read(dest / 'corpus.json')
    assert len(corpus) == summary['selected_pages']
    assert len({row['page_key'] for row in corpus}) == len(corpus)
    preferred_keys = {row['page_key'] for row in candidates
                      if (row['stage'], row['engine']) in {('m8', 'cur_rotgate'), ('m1', 'paddle_vietocr')}}
    assert {row['page_key'] for row in corpus} == preferred_keys
    source_hashes = {}
    for row in corpus:
        assert row['result'] == by_id[row['record_id']]['result']
        assert row['source_locations']
        for path in row['source_locations']:
            if path not in source_hashes:
                source_hashes[path] = digest(Path(path))
            assert source_hashes[path] == row['source_document_sha256']
        if row['engine'] == 'paddle_vietocr':
            assert not any(other['engine'] == 'cur_rotgate' and other['page_key'] == row['page_key']
                           for other in candidates)
    assert sum(row['line_count'] for row in corpus) == summary['selected_lines']
    with (dest / 'corpus.csv').open(encoding='utf-8-sig', newline='') as stream:
        csv_rows = list(csv.DictReader(stream))
    assert len(csv_rows) == len(corpus)
    for original, converted in zip(corpus, csv_rows):
        assert converted['text'] == original['text']
        assert converted['page_key'] == original['page_key']

    documents = read(dest / 'documents.json')
    assert len(documents) == summary['documents']
    for document in documents:
        pages = sorted((row for row in corpus if row['source_document_sha256'] == document['source_document_sha256']),
                       key=lambda row: row['page'])
        assert document['exported_pages'] == [row['page'] for row in pages]
        expected = '\n\n'.join(f'--- Trang {row["page"]} ---\n{row["text"]}' for row in pages) + '\n'
        assert (dest / document['text_file']).read_text(encoding='utf-8') == expected

    d1 = read(source / 'data-inventory/d1/inventory.json')
    records = read(dest / 'tables/admission_records.json')
    assert len(records) == len(d1['records']) == summary['admission_records']
    for original, converted in zip(d1['records'], records):
        assert all(converted[key] == value for key, value in original.items())
        assert converted['source_document_sha256'] == d1['environment']['sources'][original['doc']]
        assert converted['method'] is None
    with (dest / 'tables/admission_records.csv').open(encoding='utf-8-sig', newline='') as stream:
        table_csv = list(csv.DictReader(stream))
    assert len(table_csv) == len(records)
    for original, converted in zip(records, table_csv):
        for key in d1['records'][0]:
            assert str(original[key]) == converted[key]
    review = read(dest / 'review/handbook_rows.json')
    assert review['rows'] == read(source / 'ocr/p0-01/rows.json')
    assert review['validation'] == read(source / 'ocr/p0-01/validation.json')
    result = dict(status='passed', verified_source_files=len(inventory), verified_candidates=len(candidates),
                  verified_selected_pages=len(corpus), verified_documents=len(documents),
                  verified_table_records=len(records), verified_review_rows=len(review['rows']),
                  checks=['source SHA-256 and inventory completeness', 'raw OCR and text preservation',
                          'no synthetic, empty, failed or truncated candidates', 'preferred page coverage and deduplication',
                          'original document SHA-256', 'CSV and TXT roundtrip', 'table fields and review validation'],
                  scope='Export integrity; not manual verification of OCR facts')
    write_json(dest / 'audit/verification.json', result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
