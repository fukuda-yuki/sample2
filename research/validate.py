"""Original-first independent audit; extraction/normalization code is not imported.

Expected Runs come from an archived-plan-backed inventory, never the analysis.
--root relocates the corpus without editing any saved originals.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

VERSION = '2.0.1'
TOKEN_KEYS = ('input_tokens', 'output_tokens', 'cache_read_tokens', 'cache_write_tokens', 'reasoning_tokens')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def digest(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def safe_path(root, name):
    path = (Path(root) / name).resolve()
    if not path.is_relative_to(Path(root).resolve()):
        raise ValueError('Path outside corpus: ' + name)
    return path


def journal(path, errors, label):
    if not path.is_file():
        errors.append('missing:' + label)
        return []
    rows = []
    for n, raw in enumerate(path.read_bytes().splitlines(), 1):
        if not raw.strip(): continue
        try:
            item = json.loads(raw)
            if not isinstance(item, dict): raise ValueError()
            rows.append(item)
        except (ValueError, UnicodeError): errors.append('invalid_json:' + label + ':' + str(n))
    return rows


def raw_usage(path):
    usage, errors, done, models = None, [], False, set()
    if not path.is_file(): return {}, ['missing_response'], False, []
    for number, raw_line in enumerate(path.read_bytes().splitlines(), 1):
        try:
            line = raw_line.decode('utf-8-sig')
        except UnicodeError:
            errors.append('invalid_sse_encoding:' + str(number))
            continue
        if not line.startswith('data:'): continue
        raw = line[5:].strip()
        if raw == '[DONE]':
            done = True
            continue
        try:
            item = json.loads(raw)
            if not isinstance(item, dict): raise ValueError()
            if item.get('model'): models.add(item['model'])
            if item.get('usage') is not None:
                if not isinstance(item['usage'], dict): raise ValueError()
                usage = item['usage']
        except (ValueError, TypeError): errors.append('invalid_sse:' + str(number))
    if usage is None: return {}, errors + ['unreported_usage'], done, sorted(models)
    details, output = usage.get('prompt_tokens_details') or {}, usage.get('completion_tokens_details') or {}
    if not isinstance(details, dict) or not isinstance(output, dict):
        return {}, errors + ['invalid_usage_details'], done, sorted(models)
    values = {'input_tokens': usage.get('prompt_tokens'), 'output_tokens': usage.get('completion_tokens'),
        'cache_read_tokens': details.get('cached_tokens', usage.get('prompt_cache_hit_tokens')),
        'cache_write_tokens': details.get('cache_write_tokens'), 'reasoning_tokens': output.get('reasoning_tokens')}
    for key, value in values.items():
        if value is not None and (type(value) is not int or value < 0):
            errors.append('invalid_token:' + key); values[key] = None
    if values['input_tokens'] is None or values['output_tokens'] is None: errors.append('unreported_usage')
    return values, errors, done, sorted(models)


def observed(values):
    known = [v for v in values if type(v) is int]
    return sum(known) if known else None


def issue_code(issue):
    if issue.startswith('missing:'):
        text = issue[8:].replace('\\', '/')
        for prefix in ('usage/', 'evidence/'):
            at = text.rfind('/' + prefix)
            if at >= 0: return 'missing:' + text[at + 1:]
    return issue


def validate(source, inventory, root, group):
    source, root = Path(source), Path(root)
    inventory = read(inventory) if not isinstance(inventory, dict) else inventory
    data = read(source)
    failures, rows, request_ids, file_count = [], [], [], 0
    def check(ok, issue):
        if not ok: failures.append(issue)
    for name, expected in inventory.get('anchors', {}).items():
        p = safe_path(root, name)
        check(p.is_file() and digest(p) == expected, 'anchor_changed:' + name)
    info = inventory['groups'][group]
    receipt_path = safe_path(root, info['source_hashes'])
    check(digest(receipt_path) == info['source_hashes_sha256'], 'source_receipts_changed')
    receipts = read(receipt_path)
    expected_runs = [r for r in inventory['runs'] if r['group'] == group]
    expected_ids = [r['run_instance_id'] for r in expected_runs]
    check(bool(expected_ids) and len(expected_ids) == len(set(expected_ids)), 'invalid_expected_runs')
    check(Counter(r.get('run_instance_id') for r in data['runs']) == Counter(expected_ids), 'analysis_run_inventory')
    check(set(receipts) == {r['run_id'] for r in expected_runs}, 'receipt_run_inventory')
    check(all(c.get('run_instance_id') in expected_ids for c in data['calls']), 'foreign_analysis_call')
    for expected in expected_runs:
        run_id, instance = expected['run_id'], expected['run_instance_id']
        run_root, errors = safe_path(root, expected['root']), []
        def require(ok, issue):
            if not ok: errors.append(issue)
        manifest, condition = read(run_root/'manifest.json'), read(run_root/'condition.json')
        require(manifest.get('run_id') == run_id and manifest.get('run_instance_id') == instance, 'manifest_identity')
        require(digest(run_root/'manifest.json') == expected['manifest_sha256'], 'manifest_hash')
        starts = journal(run_root/'usage/raw/started.jsonl', errors, 'usage/raw/started.jsonl')
        ends = journal(run_root/'usage/raw/events.jsonl', errors, 'usage/raw/events.jsonl')
        events = journal(run_root/'usage/events.jsonl', errors, 'usage/events.jsonl')
        normalized = read(run_root/'usage/normalized.json')
        mapped = []
        for label, records in [('started', starts), ('terminal', ends), ('normalized', events)]:
            ids = [e.get('request_id') for e in records]
            require(all(isinstance(x, str) and x for x in ids) and len(ids) == len(set(ids)), 'duplicate_or_missing_id:' + label)
            require(all(e.get('run_id') == run_id and e.get('session_id') == instance for e in records), 'identity:' + label)
            mapped.append({e['request_id']: e for e in records if isinstance(e.get('request_id'), str)})
        beginnings, terminals, norm_by_id = mapped
        ids = set(beginnings) | set(terminals)
        require(set(beginnings) == set(terminals) == set(norm_by_id), 'original_call_inventory')
        calls = [c for c in data['calls'] if c.get('run_instance_id') == instance]
        require(Counter(c.get('request_id') for c in calls) == Counter(ids), 'analysis_call_inventory')
        by_id = {c.get('request_id'): c for c in calls}
        require(all(c.get('run_id') == run_id and c.get('cohort') == expected['cohort'] for c in calls), 'analysis_call_identity')
        values, referenced = [], set()
        for rid in sorted(ids):
            request_ids.append(rid)
            begin, end = beginnings.get(rid, {}), terminals.get(rid, {})
            event = begin or end
            require(all(begin.get(k) == end.get(k) for k in ('run_id', 'session_id', 'request_id', 'event_id', 'model_id', 'request_file', 'response_file', 'request_sha256')), 'event_identity_changed:' + rid)
            require(event.get('model_id') == condition['runtime']['model_id'], 'requested_model:' + rid)
            names = [event.get('request_file', ''), event.get('response_file', '')]
            if any(not n or Path(n).name != n or '\\' in n or ':' in n for n in names):
                errors.append('unsafe_original_path:' + rid); continue
            referenced.update(names)
            request_path, response_path = [run_root/'usage/raw'/n for n in names]
            require(request_path.is_file() and digest(request_path) == event.get('request_sha256'), 'request_hash:' + rid)
            require(response_path.is_file() and digest(response_path) == end.get('response_sha256'), 'response_hash:' + rid)
            tokens, packet_errors, done, models = raw_usage(response_path)
            errors.extend(rid + '/' + error for error in packet_errors)
            require(end.get('status') == 'completed' and not end.get('policy_error') and done, 'incomplete_response:' + rid)
            require(not models or models == [condition['runtime']['model_id']], 'response_model:' + rid)
            for label, target in [('terminal', end.get('usage') or {}), ('normalized', (norm_by_id.get(rid) or {}).get('usage') or {}), ('analysis', by_id.get(rid, {}))]:
                require(all(tokens.get(k) == target.get(k) for k in TOKEN_KEYS), label + '_usage:' + rid)
            if rid in by_id:
                require(by_id[rid].get('response_ref') == 'usage/raw/' + names[1] and by_id[rid].get('request_ref') == 'usage/raw/' + names[0], 'analysis_original_ref:' + rid)
            values.append(tokens)
        actual_files = {p.name for p in (run_root/'usage/raw').glob('*') if p.name.endswith(('.request.json', '.response.sse'))}
        require(actual_files == referenced, 'orphan_or_missing_original')
        require(normalized.get('observed_request_count') == len(ids), 'normalized_call_count')
        totals = {k: observed(v.get(k) for v in values) for k in TOKEN_KEYS}
        observed_total = totals['input_tokens'] + totals['output_tokens'] if totals['input_tokens'] is not None and totals['output_tokens'] is not None else None
        for key in TOKEN_KEYS:
            if normalized.get('usage_complete'): require(normalized.get(key) == totals[key], 'normalized_sum:' + key)
        require(normalized.get('observed_tokens') == observed_total, 'normalized_observed_total')
        allowed = set(expected.get('allowed_audit_issues', []))
        if allowed:
            require(manifest.get('model_called') is False and manifest.get('end_reason') == 'environment_failure' and not ids, 'invalid_premodel_exception')
            require('all predefined address pools have been fully subnetted' in read(run_root/'evidence/runtime-error.json').get('message', ''), 'premodel_exception_reason')
        candidates = [r for r in data['runs'] if r.get('run_instance_id') == instance]
        if candidates:
            r = candidates[0]
            require(r.get('run_id') == run_id and r.get('cohort') == expected['cohort'], 'analysis_run_identity')
            require(r.get('calls') == len(ids), 'analysis_call_count')
            require(r.get('observed_input_tokens') == totals['input_tokens'] and r.get('observed_output_tokens') == totals['output_tokens'], 'analysis_observed_totals')
            errors.extend('analysis_audit:' + issue_code(i) for i in r.get('audit_issues', []) if issue_code(i) not in allowed)
            expected_complete = bool(ids) and not errors and bool(normalized.get('usage_complete'))
            require(bool(r.get('usage_complete')) == expected_complete, 'analysis_usage_complete')
            if r.get('usage_complete'):
                require(r.get('total_tokens') == observed_total and all(r.get(k) == totals[k] for k in TOKEN_KEYS), 'analysis_complete_totals')
            else:
                require(r.get('total_tokens') is None and r.get('input_tokens') is None and r.get('output_tokens') is None, 'missing_total_not_null')
        for name, expected_hash in receipts.get(run_id, {}).items():
            path = safe_path(run_root, name)
            require(path.is_file() and digest(path) == expected_hash, 'changed:' + name)
            file_count += 1
        unexcepted = [e for e in errors if e not in allowed]
        failures.extend(group + '/' + run_id + '/' + e for e in unexcepted)
        complete = bool(ids) and not unexcepted and bool(normalized.get('usage_complete'))
        rows.append({'group': group, 'cohort': expected['cohort'], 'run_id': run_id, 'run_instance_id': instance,
            'started': len(starts), 'terminal': len(ends), 'normalized': len(events), 'analysis_calls': len(calls),
            'observed_input_tokens': totals['input_tokens'], 'observed_output_tokens': totals['output_tokens'],
            'observed_total_tokens': observed_total, 'usage_complete': complete,
            'total_tokens': observed_total if complete else None,
            'expected_exceptions': sorted(set(errors) & allowed), 'issues': unexcepted})
    check(len(request_ids) == len(set(request_ids)), 'duplicate_request_across_runs')
    return {'auditor_version': VERSION, 'analysis': str(source), 'analysis_sha256': digest(source), 'group': group,
        'files_checked': file_count, 'runs': rows, 'request_ids': request_ids, 'failures': failures, 'pass': not failures}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--analysis', type=Path, action='append', required=True)
    p.add_argument('--group', action='append', required=True)
    p.add_argument('--inventory', type=Path, required=True)
    p.add_argument('--root', type=Path, default=Path.cwd())
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    if len(args.analysis) != len(args.group): p.error('One --group per --analysis is required')
    results = [validate(s, args.inventory, args.root, g) for s, g in zip(args.analysis, args.group)]
    ids = [i for r in results for i in r['request_ids']]
    result = {'auditor_version': VERSION, 'inventory_sha256': digest(args.inventory), 'results': results,
        'pass': all(r['pass'] for r in results) and len(ids) == len(set(ids)),
        'files_checked': sum(r['files_checked'] for r in results), 'calls_checked': len(ids),
        'global_request_ids_unique': len(ids) == len(set(ids))}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2); f.write('\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'results'}))
    return 0 if result['pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
