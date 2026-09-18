"""Reproduce call/action/context tables from saved gateway and OpenCode originals.

No model calls, evaluation, or writes to source Run directories. Counts come from
provider SSE, not OpenCode's differently defined token fields. Classification is
an inspectable heuristic, never a claim about model understanding or waste.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import difflib
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import statistics

VERSION = '1.0.1'
TOKEN_KEYS = ('input_tokens', 'output_tokens', 'cache_read_tokens',
              'cache_write_tokens', 'reasoning_tokens')


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def journal(path):
    result, errors = [], []
    if not Path(path).exists():
        return result, ['missing:' + str(path)]
    for number, line in enumerate(Path(path).read_bytes().splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError('not an object')
            result.append((number, value))
        except (ValueError, UnicodeError):
            errors.append('invalid_line:' + str(number))
    return result, errors


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def text_hash(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def observed_total(values):
    """No reported values is missing, not a measured zero (post-freeze fix)."""
    known = [value for value in values if isinstance(value, int)]
    return sum(known) if known else None


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from strings(child)


def provider_response(path):
    usage, model_ids, calls, errors, done = None, set(), {}, [], False
    for number, line in enumerate(Path(path).read_text(encoding='utf-8-sig').splitlines(), 1):
        if not line.startswith('data:'):
            continue
        raw = line[5:].strip()
        if raw == '[DONE]':
            done = True
            continue
        try:
            value = json.loads(raw)
        except ValueError:
            errors.append('invalid_sse:' + str(number))
            continue
        if value.get('model'):
            model_ids.add(value['model'])
        if value.get('usage') is not None:
            n = value['usage']
            usage = {'input_tokens': n.get('prompt_tokens'),
                     'output_tokens': n.get('completion_tokens'),
                     'cache_read_tokens': (n.get('prompt_tokens_details') or {}).get(
                         'cached_tokens', n.get('prompt_cache_hit_tokens')),
                     'cache_write_tokens': (n.get('prompt_tokens_details') or {}).get('cache_write_tokens'),
                     'reasoning_tokens': (n.get('completion_tokens_details') or {}).get('reasoning_tokens')}
        for choice in value.get('choices', []):
            for item in choice.get('delta', {}).get('tool_calls', []):
                key = (choice.get('index', 0), item.get('index', 0))
                current = calls.setdefault(key, {'id': '', 'name': '', 'arguments': ''})
                if item.get('id'):
                    current['id'] += item['id']
                function = item.get('function') or {}
                current['name'] += function.get('name') or ''
                current['arguments'] += function.get('arguments') or ''
    return usage, list(calls.values()), sorted(model_ids), errors, done


def classify(tool, inputs, output, written):
    """Multi-label observable action codes. Tests/log content are not quality scores."""
    labels, basis = set(), []
    path = inputs.get('filePath', '')
    command = inputs.get('command', '')
    low = command.lower()
    test_path = bool(re.search(r'(^|/)(test|check|contract|edge)[^/]*\.(py|sh|cs)$', path, re.I))
    if tool == 'read':
        labels.add('source_read' if path.startswith('/input/legacy-source/') else 'inspection')
        basis.append('explicit read tool')
    elif tool in ('write', 'edit', 'apply_patch'):
        labels.add('validation_setup' if test_path else 'implementation')
        if tool in ('edit', 'apply_patch') or path in written:
            labels.add('revision')
        basis.append('explicit file mutation')
    elif tool == 'bash':
        patterns = {
            'environment': r'dotnet\s+--|dotnet\s+nuget|nuget|/usr/share/dotnet|which\s|python3?\s+--version|\buname\b',
            'discovery': r'(^|[;&|\n ])(?:ls|find|rg|grep|wc)\s',
            'source_read': r'(?:\bcat\s|\bsed\s|\bhead\s|\btail\s|\bgrep\s|\.read\(|read_text\(|\bopen\().*(?:legacy-source|\.cs|\.cshtml)',
            'implementation': r'dotnet\s+(?:new|sln|add)|\bmkdir\b|\bcp\s|\bmv\s|\bcat\s*>|write_text\(|write_bytes\(|open\([^\n]*[\x22\x27][wa][\x22\x27]',
            'build': r'dotnet\s+(?:build|publish|restore)\b',
            'validation': r'\bcurl\b|localhost|127\.0\.0\.1|\bassert\b|sqlite3|(?:python3?|bash)\s+\S*(?:test|contract|edge|check)\S*|dotnet\s+test\b|\bpkill\b|\bkill\b|/proc/',
            'revision': r'\bsed\s+-i\b|\.replace\(|\bpatch\b',
            'cleanup': r'\brm\s|\brmdir\s',
        }
        for label, pattern in patterns.items():
            if re.search(pattern, low, re.S):
                labels.add(label)
        # Shell loops name files before `cat "$f"`; do not require the path to
        # follow the read command. A heredoc writer alone is not a source read.
        if ('legacy-source' in low and re.search(r'\bcat\s+(?!>)|\bsed\s+(?!-i)|\bgrep\s|\.read\(|read_text\(', low)):
            labels.add('source_read')
        if labels:
            basis.append('command syntax/paths; labels may overlap')
    elif tool in ('glob', 'grep', 'list'):
        labels.add('discovery')
    elif tool == 'todowrite':
        labels.add('planning')
    if not labels:
        labels.add('other_unknown')
    return sorted(labels), '; '.join(basis) or 'no supported rule'


def numbered_lines(output):
    # Restrict to Read's content wrapper, not line-looking diagnostics elsewhere.
    match = re.search(r'<content>\r?\n(.*?)</content>', output, re.S)
    if not match:
        return {}
    return {int(n): line.rstrip('\r') for n, line in
            re.findall(r'(?m)^(\d+): (.*)$', match[1])}


def reread_kind(lines, previous, revision, earlier_revision):
    if not lines:
        return 'indeterminate'
    overlap = set(lines) & set(previous)
    if not overlap:
        return 'first_observed_range'
    if revision > earlier_revision:
        return 'after_observed_edit'
    if any(lines[n] != previous[n] for n in overlap):
        return 'content_changed_edit_unobserved'
    if len(overlap) == len(lines):
        return 'unchanged_range_reacquisition'
    return 'partial_overlap'


def shell_source_ranges(command, output, source_root, source_cache):
    """Recover only source lines actually visible in the output, never execute shell.

    File names are candidates. A matching contiguous block of >= 3 original lines
    establishes exposure. Count-only reads/processes do not count as text delivery.
    Unresolvable variable/wildcard paths remain explicitly unclassified.
    """
    tokens = re.findall(r'(?:/input/legacy-source/)?[A-Za-z0-9_.@/-]+\.(?:cshtml|cs|config|json|txt)\b', command)
    paths = set()
    for token in tokens:
        if token.startswith('/input/legacy-source/'):
            candidate = source_root / token[len('/input/legacy-source/'):]
            if candidate.is_file():
                paths.add(candidate)
        elif not token.startswith('/'):
            matches = list(source_root.rglob(PurePosixPath(token).name))
            matches = [p for p in matches if p.as_posix().endswith('/' + token)]
            cd = re.search(r'\bcd\s+[\x22\x27]?(/input/legacy-source/[^;&\n\x22\x27 ]+)', command)
            if cd:
                prefix = cd.group(1)[len('/input/legacy-source/'):]
                local = source_root / prefix / token
                if local.is_file():
                    matches = [local]
            if len(matches) == 1:
                paths.add(matches[0])
    shown = output.splitlines()
    result = []
    for path in sorted(paths):
        if path not in source_cache:
            source_cache[path] = path.read_text(encoding='utf-8-sig', errors='replace').splitlines()
        original = source_cache[path]
        lines = {}
        for block in difflib.SequenceMatcher(None, original, shown, autojunk=False).get_matching_blocks():
            if block.size >= 3 and sum(len(s.strip()) for s in original[block.a:block.a + block.size]) >= 30:
                lines.update({i + 1: original[i] for i in range(block.a, block.a + block.size)})
        if lines:
            result.append(('/input/legacy-source/' + path.relative_to(source_root).as_posix(), lines))
    return result


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def write_csv(path, rows):
    if not rows:
        Path(path).write_text('', encoding='utf-8-sig')
        return
    keys = list(dict.fromkeys(k for row in rows for k in row))
    with Path(path).open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: canonical(v) if isinstance(v, (list, dict)) else v for k, v in row.items()})


def analyze_run(root, cohort, slot=None):
    from outer.harness import aggregate
    from outer.harness.live_usage import input_locations
    root = Path(root)
    manifest = read_json(root / 'manifest.json')
    condition = read_json(root / 'condition.json')
    context = read_json(root / 'context.json')
    normalized = read_json(root / 'usage/normalized.json') if (root / 'usage/normalized.json').exists() else {}
    issues, receipts = [], {}
    def receipt(path):
        if path.is_file():
            receipts[path.relative_to(root).as_posix()] = sha(path)
    for path in [root/'manifest.json', root/'condition.json', root/'context.json',
                 root/'snapshot.json', root/'inputs-manifest.json', root/'archive-reference.json',
                 root/'usage/normalized.json', root/'usage/provenance.json', root/'usage/events.jsonl',
                 root/'evidence/agent.jsonl', root/'telemetry-link.json']:
        receipt(path)
    events, event_errors = journal(root/'usage/events.jsonl')
    issues += event_errors
    native, native_errors = journal(root/'evidence/agent.jsonl')
    issues += native_errors
    begins, begin_errors = journal(root/'usage/raw/started.jsonl')
    ends, end_errors = journal(root/'usage/raw/events.jsonl')
    issues += begin_errors + end_errors
    for path in (root/'usage/raw').glob('*'):
        receipt(path)
    for directory in ('inputs', 'profiles', 'frozen', 'workspace', 'evaluation-assets', 'evaluations'):
        for path in (root/directory).rglob('*'):
            if path.is_file():
                receipt(path)
    for name, rows in [('starts', begins), ('terminals', ends), ('events', events)]:
        ids = [e.get('request_id') for _, e in rows]
        if len(ids) != len(set(ids)) or None in ids:
            issues.append('duplicate_or_absent_request_id:' + name)
        if any(e.get('run_id') != manifest['run_id'] or e.get('session_id') != manifest['run_instance_id'] for _, e in rows):
            issues.append('run_identity_mismatch:' + name)
    if {e.get('request_id') for _, e in begins} != {e.get('request_id') for _, e in ends}:
        issues.append('incomplete_start_terminal_inventory')
    native_tools = {}
    for line, entry in native:
        if entry.get('type') == 'tool_use':
            part = entry['part']
            if part['callID'] in native_tools:
                issues.append('duplicate_native_tool_id:' + part['callID'])
            native_tools[part['callID']] = (line, entry)
    native_sessions = sorted({e.get('sessionID') for _, e in native if e.get('sessionID')})
    if len(native_sessions) != 1:
        issues.append('native_session_count:' + str(len(native_sessions)))
    events.sort(key=lambda pair: (pair[1].get('started_at', ''), pair[0]))
    calls, response_tool_calls, exposures = [], {}, defaultdict(list)
    seen_message_hashes, previous_message_hashes = set(), set()
    previous_input = None
    prompt = (root/'inputs/prompt.txt').read_text(encoding='utf-8-sig')
    cumulative_in, cumulative_out = 0, 0
    for seq, (event_line, event) in enumerate(events, 1):
        identity = {'cohort': cohort, 'run_id': root.name, 'run_instance_id': manifest['run_instance_id'],
                    'condition': manifest['intervention_id'], 'block': (slot or {}).get('block'),
                    'slot': (slot or {}).get('slot'), 'call_index': seq, 'request_id': event.get('request_id')}
        request_path = root/'usage/raw'/event.get('request_file', 'absent')
        response_path = root/'usage/raw'/event.get('response_file', 'absent')
        if not request_path.is_file():
            issues.append('missing_request:' + str(seq))
            calls.append({**identity, **{k: None for k in TOKEN_KEYS}, 'status': event.get('status')})
            continue
        for path, key in [(request_path, 'request_sha256'), (response_path, 'response_sha256')]:
            if not path.is_file() or sha(path) != event.get(key):
                issues.append('original_hash_mismatch:' + path.name)
        request = read_json(request_path)
        if response_path.is_file():
            usage, response_calls, models, errors, done = provider_response(response_path)
        else:
            usage, response_calls, models, errors, done = None, [], [], ['response_missing'], False
        issues += [str(seq) + ':' + s for s in errors]
        if usage is not None:
            if any(usage[k] != (event.get('usage') or {}).get(k) for k in TOKEN_KEYS):
                issues.append('raw_usage_mismatch:' + str(seq))
        if models and models != [condition['runtime']['model_id']]:
            issues.append('response_model_mismatch:' + str(seq))
        usage = usage or {k: None for k in TOKEN_KEYS}
        for tc in response_calls:
            if tc['id'] in response_tool_calls:
                issues.append('duplicate_response_tool_id:' + tc['id'])
            response_tool_calls[tc['id']] = {**tc, **identity}
        messages = request.get('messages', [])
        mh = [text_hash(canonical(m)) for m in messages]
        current_hashes = set(mh)
        new_chars = sum(len(canonical(m)) for m, h in zip(messages, mh) if h not in seen_message_hashes)
        retained_chars = sum(len(canonical(m)) for m, h in zip(messages, mh) if h in seen_message_hashes)
        vanished = len(previous_message_hashes - current_hashes)
        role_chars = {role + '_chars': sum(len(canonical(m)) for m in messages if m.get('role') == role)
                      for role in ('system', 'user', 'assistant', 'tool')}
        for mi, message in enumerate(messages):
            if message.get('role') == 'tool':
                tid = message.get('tool_call_id')
                exposures[tid].append({'call_index': seq, 'message_index': mi,
                                       'chars': sum(len(s) for s in strings(message.get('content'))),
                                       'message_hash': mh[mi]})
        ip, op = usage['input_tokens'], usage['output_tokens']
        if isinstance(ip, int):
            cumulative_in += ip
        if isinstance(op, int):
            cumulative_out += op
        blocks_present = sum(bool(input_locations(messages, b['text'])) for b in context['blocks'])
        calls.append({**identity, **usage, **role_chars,
                      'status': event.get('status'), 'started_at': event.get('started_at'),
                      'ended_at': event.get('ended_at'), 'stream_done': done,
                      'input_delta': ip-previous_input if ip is not None and previous_input is not None else None,
                      'observed_cumulative_input': cumulative_in, 'observed_cumulative_output': cumulative_out,
                      'message_count': len(messages), 'new_message_chars': new_chars,
                      'retained_message_chars': retained_chars, 'disappeared_message_count': vanished,
                      'tool_schema_chars': len(canonical(request.get('tools', []))),
                      'initial_prompt_present': bool(input_locations(messages, prompt)),
                      'initial_blocks_present': blocks_present,
                      'response_tool_ids': [tc['id'] for tc in response_calls],
                      'event_ref': 'usage/events.jsonl:' + str(event_line),
                      'request_ref': 'usage/raw/' + request_path.name,
                      'response_ref': 'usage/raw/' + response_path.name})
        previous_input = ip
        previous_message_hashes = current_hashes
        seen_message_hashes |= current_hashes
    unknown_native = set(native_tools) - set(response_tool_calls)
    absent_native = set(response_tool_calls) - set(native_tools)
    issues += ['native_tool_without_response:' + x for x in sorted(unknown_native)]
    issues += ['response_tool_without_native:' + x for x in sorted(absent_native)]
    actions, reads, written, source_cache = [], [], set(), {}
    history, revision, last_read_revision = defaultdict(dict), defaultdict(int), defaultdict(int)
    for block in context['blocks']:
        if block['source'] != 'public-explanation':
            history['/input/legacy-source/' + block['source']] = dict(enumerate(block['text'].splitlines(), 1))
    first_build = None
    for tid, (line, entry) in sorted(native_tools.items(), key=lambda kv: kv[1][0]):
        part, mapped = entry['part'], response_tool_calls.get(tid, {})
        state = part.get('state') or {}
        inputs, output = state.get('input') or {}, state.get('output') or ''
        tool = part['tool']
        labels, basis = classify(tool, inputs, output, written)
        if 'build' in labels and first_build is None:
            first_build = mapped.get('call_index')
        action = {'cohort': cohort, 'run_id': root.name, 'run_instance_id': manifest['run_instance_id'],
                  'condition': manifest['intervention_id'], 'tool_call_id': tid,
                  'call_index': mapped.get('call_index'), 'request_id': mapped.get('request_id'),
                  'native_message_id': part.get('messageID'), 'native_session_id': part.get('sessionID'),
                  'tool': tool, 'labels': labels, 'classification_basis': basis,
                  'status': state.get('status'), 'inputs': inputs,
                  'output_chars': len(output), 'output_sha256': text_hash(output),
                  'subsequent_input_count': len(exposures[tid]),
                  'subsequent_input_char_exposure': sum(x['chars'] for x in exposures[tid]),
                  'exposures': exposures[tid],
                  'native_ref': 'evidence/agent.jsonl:' + str(line),
                  'build_error_observed': bool('build' in labels and re.search(r'\berror\s+(?:CS|NU|MSB)\d+|Build FAILED', output)),
                  'test_failure_text': bool('validation' in labels and re.search(r'AssertionError|Traceback \(most recent|\bFAIL(?:ED)?\b', output))}
        observed_ranges = []
        if tool == 'read':
            observed_ranges = [(inputs.get('filePath', ''), numbered_lines(output))]
        elif tool == 'bash' and 'source_read' in labels:
            observed_ranges = shell_source_ranges(inputs.get('command', ''), output,
                                                   root/'inputs/legacy-source', source_cache)
            if not observed_ranges:
                observed_ranges = [('', {})]
        for path, lines in observed_ranges:
            prior = history[path]
            kind = reread_kind(lines, prior, revision[path], last_read_revision[path])
            overlap = set(lines) & set(prior)
            row = {'cohort': cohort, 'run_id': root.name, 'condition': manifest['intervention_id'],
                   'call_index': mapped.get('call_index'), 'tool_call_id': tid, 'path': path,
                   'first_line': min(lines) if lines else None, 'last_line': max(lines) if lines else None,
                   'visible_line_count': len(lines), 'overlap_line_count': len(overlap),
                   'same_content_overlap_lines': sum(lines[n] == prior[n] for n in overlap),
                   'kind': kind, 'visible_chars': sum(len(v) for v in lines.values()),
                   'native_ref': action['native_ref']}
            reads.append(row)
            history[path].update(lines)
            last_read_revision[path] = revision[path]
        path = inputs.get('filePath')
        if tool in ('write', 'edit') and path:
            written.add(path)
            revision[path] += 1
        elif tool in ('bash', 'apply_patch') and ('revision' in labels or 'implementation' in labels):
            # Shell paths/side effects cannot always be reconstructed: mark editable
            # reads conservatively instead of incorrectly asserting unchangedness.
            for path in history:
                if path.startswith('/workspace/'):
                    revision[path] += 1
        action['source_read_kinds'] = [r['kind'] for r in reads if r['tool_call_id'] == tid]
        actions.append(action)
    bycall = defaultdict(list)
    for a in actions:
        bycall[a['call_index']].append(a)
    for c in calls:
        c['action_labels'] = sorted({label for a in bycall[c['call_index']] for label in a['labels']}) or ['text_or_auxiliary']
    row = aggregate.row_for(root.parent, root.name)
    complete = bool(normalized.get('usage_complete'))
    for key in TOKEN_KEYS:
        vals = [c.get(key) for c in calls]
        known = [v for v in vals if isinstance(v, int)]
        if complete and known and len(known) == len(vals) and sum(known) != normalized.get(key):
            issues.append('normalized_sum_mismatch:' + key)
    top = sorted(actions, key=lambda a: a['subsequent_input_char_exposure'], reverse=True)[:5]
    totals = {key: sum(c[key] for c in calls) if complete and calls and all(c.get(key) is not None for c in calls) else None
              for key in TOKEN_KEYS}
    total = (totals['input_tokens'] + totals['output_tokens']
             if totals['input_tokens'] is not None and totals['output_tokens'] is not None else None)
    result = {'cohort': cohort, 'run_id': root.name, 'run_instance_id': manifest['run_instance_id'],
              'condition': manifest['intervention_id'], 'root': str(root.resolve()),
              'block': (slot or {}).get('block'), 'slot': (slot or {}).get('slot'),
              'replacement_for': (slot or {}).get('replacement_for'),
              'started_at': manifest.get('started_at'), 'execution': row['execution'],
              'quality': row['quality'], 'verdict': row['verdict'], 'scoring': row['scoring'],
              'usage_complete': complete, **totals, 'total_tokens': total,
              'observed_input_tokens': observed_total(c.get('input_tokens') for c in calls),
              'observed_output_tokens': observed_total(c.get('output_tokens') for c in calls),
              'calls': len(calls), 'actions': len(actions),
              'mean_input': totals['input_tokens']/len(calls) if totals['input_tokens'] is not None and calls else None,
              'first_input': calls[0].get('input_tokens') if calls else None,
              'last_input': calls[-1].get('input_tokens') if calls else None,
              'initial_prompt_present_calls': sum(c.get('initial_prompt_present', False) for c in calls),
              'initial_blocks': len(context['blocks']),
              'all_initial_blocks_present_calls': sum(c.get('initial_blocks_present') == len(context['blocks']) for c in calls),
              'disappeared_message_count': sum(c.get('disappeared_message_count', 0) for c in calls),
              'tool_schema_chars': calls[0].get('tool_schema_chars') if calls else None,
              'action_label_counts': dict(Counter(label for a in actions for label in a['labels'])),
              'read_kind_counts': dict(Counter(r['kind'] for r in reads)),
              'first_build_call': first_build,
              'build_error_actions': sum(a['build_error_observed'] for a in actions),
              'test_failure_actions': sum(a['test_failure_text'] for a in actions),
              'top_retained_outputs': [{k:a[k] for k in ('call_index', 'tool_call_id', 'tool', 'labels', 'output_chars', 'subsequent_input_count', 'subsequent_input_char_exposure', 'native_ref')} for a in top],
              'largest_input_increases': [{'call_index':c['call_index'], 'delta':c['input_delta'], 'request_id':c['request_id']}
                                        for c in sorted([c for c in calls if c.get('input_delta') is not None], key=lambda c:c['input_delta'], reverse=True)[:5]],
              'audit_issues': sorted(set(issues))}
    # Hash again after extraction so input changes during the analysis are detected.
    changed = [name for name, digest in receipts.items() if sha(root/name) != digest]
    result['audit_issues'] += ['source_changed_during_analysis:' + n for n in changed]
    return result, calls, actions, reads, receipts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs-dir', type=Path, required=True)
    parser.add_argument('--cohort', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--plan', type=Path)
    args = parser.parse_args()
    if args.out.exists():
        raise SystemExit('Refusing to overwrite analysis output: ' + str(args.out))
    roots = sorted(args.runs_dir.glob('MS1-001-*/manifest.json'))
    if not roots:
        raise SystemExit('No Runs found')
    if args.out.resolve().is_relative_to(args.runs_dir.resolve()):
        raise SystemExit('Analysis output must be outside source Runs')
    slots = {}
    if args.plan:
        plan = read_json(args.plan)
        slots = {s['run_id']:s for s in plan['slots']}
        journal_path = args.runs_dir/'batch-journal.jsonl'
        if journal_path.exists():
            for _, event in journal(journal_path)[0]:
                if event.get('kind') == 'dispatch':
                    slots[event['case']['run_id']] = event['case']
    runs, calls, actions, reads, hashes = [], [], [], [], {}
    for manifest in roots:
        slot = slots.get(manifest.parent.name)
        cohort = 'supplement' if slot and slot.get('replacement_for') else args.cohort
        row, c, a, rr, h = analyze_run(manifest.parent, cohort, slot)
        runs.append(row); calls.extend(c); actions.extend(a); reads.extend(rr)
        hashes[row['run_id']] = h
    args.out.mkdir(parents=True)
    write_json(args.out/'analysis.json', {'analysis_version': VERSION, 'runs': runs, 'calls': calls, 'actions': actions, 'reads': reads})
    write_json(args.out/'source-hashes.json', hashes)
    write_json(args.out/'audit.json', {'analysis_version':VERSION, 'run_count':len(runs),
        'call_count':len(calls), 'action_count':len(actions), 'issues':{r['run_id']:r['audit_issues'] for r in runs if r['audit_issues']},
        'source_files_hashed':sum(len(h) for h in hashes.values()), 'source_hashes_sha256':sha(args.out/'source-hashes.json')})
    for name, rows in [('runs',runs), ('calls',calls), ('actions',actions), ('reads',reads)]:
        write_csv(args.out/(name+'.csv'), rows)
    print(json.dumps({'out':str(args.out), 'runs':len(runs), 'calls':len(calls), 'actions':len(actions),
                      'audit_issues':sum(len(r['audit_issues']) for r in runs)}, ensure_ascii=True))


if __name__ == '__main__':
    main()
