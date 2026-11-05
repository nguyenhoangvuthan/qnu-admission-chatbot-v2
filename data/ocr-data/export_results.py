"""Xuất nội dung dùng được từ results, giữ nguồn và tách dữ liệu cần rà soát."""

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = list(dict.fromkeys(key for row in rows for key in row))
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
                             for k, v in row.items()})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path,
                        default=Path('/home/kent/KentProject/qnu-admission-chatbot/results'))
    parser.add_argument('--destination', type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    source, dest = args.source.resolve(), args.destination.resolve()
    if source == dest or source in dest.parents:
        raise ValueError('Thư mục xuất phải nằm ngoài results nguồn')
    repo = source.parent
    files = sorted(path for path in source.rglob('*') if path.is_file())
    parsed = {}
    audit = []
    for path in files:
        rel = path.relative_to(source).as_posix()
        item = dict(source_file=rel, bytes=path.stat().st_size, sha256=digest(path),
                    status='excluded', reason='report_log_metadata_or_evaluation')
        if path.suffix == '.json':
            try:
                parsed[rel] = read(path)
            except (ValueError, UnicodeError) as exc:
                item['reason'] = 'invalid_json: ' + str(exc)
        audit.append(item)
    audit_by_path = {row['source_file']: row for row in audit}
    m1_path = 'preprocess-bench/m1/manifest.json'
    m8_path = 'preprocess-bench/m8/manifest.json'
    manifests = {stage: {item['id']: item for item in parsed[path]['items']}
                 for stage, path in [('m1', m1_path), ('m8', m8_path)]}
    d1_path = 'data-inventory/d1/inventory.json'
    d1 = parsed[d1_path]
    p0_path = 'ocr/p0-01/raw.json'
    p0 = parsed[p0_path]
    name_hash = dict(d1['environment']['sources'])
    for item in manifests['m8'].values():
        name_hash[Path(item['source']).name] = item['source_sha256']
    name_hash[Path(p0['source']['pdf']).name] = p0['source']['pdf_sha256']

    # Chỉ dùng tên để tìm đường dẫn; bắt buộc đối chiếu hash trước khi gắn nguồn.
    source_paths = defaultdict(list)
    data_roots = [repo / 'data', dest.parent]
    for data_root in data_roots:
        for path in data_root.rglob('*'):
            if path.is_file() and path.name in name_hash and dest not in path.parents:
                source_paths[path.name].append(path)
    hash_cache = {}

    def locations(name, expected):
        matches = []
        for path in source_paths.get(Path(name).name, []):
            if path not in hash_cache:
                hash_cache[path] = digest(path)
            if hash_cache[path] == expected:
                matches.append(str(path))
        return sorted(set(matches))

    candidates = []
    for rel, raw in parsed.items():
        if not isinstance(raw, dict):
            continue
        is_bench = rel.startswith(('preprocess-bench/m1/raw/', 'preprocess-bench/m8/raw/')) and 'id' in raw
        if not is_bench and rel != p0_path:
            continue
        entry = audit_by_path[rel]
        reasons = []
        if raw.get('error'):
            reasons.append('execution_error')
        lines = raw.get('lines')
        valid_lines = isinstance(lines, list) and all(
            isinstance(line, dict) and isinstance(line.get('text'), str)
            and isinstance(line.get('box'), list) and len(line['box']) == 4
            and all(isinstance(n, (int, float)) and math.isfinite(n) for n in line['box'])
            for line in (lines if isinstance(lines, list) else []))
        if not valid_lines:
            reasons.append('invalid_lines_schema')
        elif not any(line['text'].strip() for line in lines):
            reasons.append('empty_text')
        if raw.get('finish_reason') not in (None, 'stop'):
            reasons.append('incomplete_generation:' + str(raw['finish_reason']))
        parts = Path(rel).parts
        if is_bench:
            stage, engine = parts[1], parts[3]
            run = parts[4] if stage == 'm8' else 'run1'
            item = manifests[stage].get(raw['id'])
            if item is None:
                reasons.append('missing_manifest_item')
                item = {}
            images = item.get('images', {})
            expected_hashes = [im['sha256'] for im in images.values()] if images else [item.get('image_sha256')]
            if raw.get('image_sha256') not in expected_hashes:
                reasons.append('image_hash_mismatch')
            if item.get('set') == 'S2' or 'degrade_seed' in item:
                reasons.append('synthetic_degraded_benchmark')
            source_name = item.get('source', '')
            source_hash = item.get('source_sha256') or name_hash.get(Path(source_name).name)
            page = item.get('page')
            if stage == 'm1' and raw['id'] == 'png2026':
                page = 1
            if stage == 'm1' and raw['id'] == 'camnang_table':
                page = p0['source']['page']
            manifest_file = m8_path if stage == 'm8' else m1_path
            coordinate_space = ('synthetic_line_order' if engine.startswith('vlm_') or engine == 'paddle_vl'
                                else 'rotated_image_pixels' if raw.get('rotation') else 'image_pixels')
        else:
            stage, engine, run = 'p0-01', 'paddle_crosscheck', 'run1'
            item = {}
            source_name, source_hash = p0['source']['pdf'], p0['source']['pdf_sha256']
            page, manifest_file, coordinate_space = p0['source']['page'], p0_path, 'embedded_image_pixels'
        if not source_hash or page is None:
            reasons.append('missing_source_identity')
        if reasons:
            entry['reason'] = ';'.join(reasons)
            continue
        text = '\n'.join(line['text'] for line in lines)
        key = f'{source_hash}:p{page}'
        candidates.append(dict(
            record_id=hashlib.sha256(rel.encode()).hexdigest()[:20], page_key=key,
            source_file=rel, source_result_sha256=entry['sha256'], manifest_file=manifest_file,
            source_document=Path(source_name).name, source_document_sha256=source_hash,
            source_locations=locations(source_name, source_hash), page=page,
            stage=stage, engine=engine, run=run, benchmark_set=item.get('set'),
            coordinate_space=coordinate_space, quality_status='ocr_unverified',
            line_count=len(lines), text=text, text_sha256=hashlib.sha256(text.encode()).hexdigest(),
            result=raw,
        ))
        entry.update(status='reference', reason='complete_ocr_candidate_not_fact_verified')

    # Cấu hình đã được dự án chọn; chỉ dùng M1 VietOCR cho trang chưa có M8.
    priorities = {('m8', 'cur_rotgate'): 0, ('m1', 'paddle_vietocr'): 1}
    grouped = defaultdict(list)
    for candidate in candidates:
        grouped[candidate['page_key']].append(candidate)
    selected = []
    for page_key, versions in sorted(grouped.items()):
        eligible = [row for row in versions if (row['stage'], row['engine']) in priorities]
        if not eligible:
            continue
        best = min(eligible, key=lambda r: (priorities[(r['stage'], r['engine'])], r['run'], r['source_file']))
        entry = dict(best)
        entry['alternative_count'] = len(versions) - 1
        entry['selection_reason'] = ('project_selected_cur_rotgate' if best['stage'] == 'm8'
                                     else 'm1_vietocr_page_not_covered_by_selected_m8')
        selected.append(entry)
        audit_by_path[best['source_file']].update(status='selected', reason=entry['selection_reason'])
    selected.sort(key=lambda row: (row['source_document'], row['page']))
    dest.mkdir(parents=True, exist_ok=True)
    write_json(dest / 'corpus.json', selected)
    write_csv(dest / 'corpus.csv', [{k: v for k, v in row.items() if k != 'result'} for row in selected])
    candidate_path = dest / 'reference' / 'ocr_candidates.jsonl'
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    with candidate_path.open('w', encoding='utf-8') as stream:
        for row in candidates:
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')

    documents = defaultdict(list)
    for row in selected:
        documents[row['source_document_sha256']].append(row)
    document_index = []
    for sha, pages in sorted(documents.items()):
        pages.sort(key=lambda row: row['page'])
        text_path = f'text/{sha[:16]}.txt'
        (dest / 'text').mkdir(exist_ok=True)
        text = '\n\n'.join(f'--- Trang {row["page"]} ---\n{row["text"]}' for row in pages)
        (dest / text_path).write_text(text + '\n', encoding='utf-8')
        document_index.append(dict(source_document=pages[0]['source_document'], source_document_sha256=sha,
                                   source_locations=pages[0]['source_locations'],
                                   exported_pages=[row['page'] for row in pages], text_file=text_path,
                                   quality_status='ocr_unverified', scope='only_pages_present_in_results'))
    write_json(dest / 'documents.json', document_index)

    # Giữ đợt/loại chỉ tiêu và văn bản riêng; không gộp các giá trị khác ngữ cảnh.
    records = []
    for number, row in enumerate(d1['records'], 1):
        sha = d1['environment']['sources'].get(row['doc'])
        check = d1['checks'].get(f'{row["table"]}|{row["year"]}|{row["round"]}')
        records.append(dict(row, record_number=number, source_file=d1_path,
                            source_document_sha256=sha, source_locations=locations(row['doc'], sha),
                            source_group_check=check, method=None,
                            quality_status='extracted_requires_context_review'))
    write_json(dest / 'tables' / 'admission_records.json', records)
    write_csv(dest / 'tables' / 'admission_records.csv', records)
    audit_by_path[d1_path].update(status='converted_table', reason='503_extracted_records_preserve_year_round_doc')
    write_json(dest / 'review' / 'handbook_rows.json', dict(
        source_file='ocr/p0-01/rows.json', source=p0['source'],
        quality_status='needs_review_known_errors', rows=parsed['ocr/p0-01/rows.json'],
        validation=parsed['ocr/p0-01/validation.json']))
    write_csv(dest / 'review' / 'handbook_rows.csv', [dict(row, quality_status='needs_review_known_errors')
                                                   for row in parsed['ocr/p0-01/rows.json']])
    audit_by_path['ocr/p0-01/rows.json'].update(status='review_only', reason='known_validation_errors_in_handbook_rows')

    metadata = {path: parsed[path] for path in parsed if path.endswith(('/environment.json', '/spec.json'))
                and path.startswith('preprocess-bench/')}
    # Chỉ giữ metadata nguồn; không đưa đáp án benchmark (gt_*) vào corpus.
    metadata.update({
        'preprocess-bench/m8/scores.json': parsed['preprocess-bench/m8/scores.json'],
        'ocr/p0-01/validation.json': parsed['ocr/p0-01/validation.json'],
        d1_path: {key: value for key, value in d1.items() if key != 'records'},
    })
    write_json(dest / 'audit' / 'source_metadata.json', metadata)
    write_csv(dest / 'audit' / 'file_inventory.csv', audit)
    summary = dict(
        source_directory=str(source), destination=str(dest), source_file_count=len(files),
        file_status_counts=dict(Counter(row['status'] for row in audit)),
        excluded_reason_counts=dict(Counter(row['reason'] for row in audit if row['status'] == 'excluded')),
        complete_ocr_candidates=len(candidates), selected_pages=len(selected),
        selected_lines=sum(row['line_count'] for row in selected), documents=len(documents),
        selected_engines=dict(Counter(row['engine'] for row in selected)),
        admission_records=len(records), handbook_rows_for_review=len(parsed['ocr/p0-01/rows.json']),
        selected_without_available_source=sum(not row['source_locations'] for row in selected),
        selection='cur_rotgate then M1 paddle_vietocr; first run; one result per source SHA-256/page',
        limitations=['OCR text is not manually fact-verified', 'Only pages present in results are exported',
                     'No benchmark labels, generated answers or synthetic degraded images enter the corpus',
                     'Admission method is unspecified in inventory records; method=null',
                     'Existing ocr_results.json is a separate earlier export, not merged into corpus'],
    )
    write_json(dest / 'audit' / 'summary.json', summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
