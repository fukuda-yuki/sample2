"""Reconcile gateway originals, input interventions and native execution evidence."""
import json
import re
from pathlib import Path

from . import util, run


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from strings(child)


def journal(path):
    """Keep valid lines from an interrupted spool; a damaged line invalidates coverage."""
    path = Path(path)
    records, errors = [], []
    if not path.exists():
        return records, errors
    for number, raw in enumerate(path.read_bytes().splitlines(), 1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError('Expected object')
            records.append(value)
        except (ValueError, UnicodeError):
            errors.append(path.name + ':invalid_line:' + str(number))
    return records, errors


def input_locations(messages, original):
    """Map an original to raw input or OpenCode's documented Read rendering.

    Only consecutive numbered lines are decoded. No whitespace, source text or
    missing lines are guessed. The final newline is not represented by Read.
    """
    found = []
    target = original.splitlines()
    for index, message in enumerate(messages):
        if not isinstance(message, dict) or message.get('role') != 'user':
            continue
        for content_index, value in enumerate(strings(message.get('content'))):
            if original in value:
                found.append({'message_index': index, 'string_index': content_index,
                              'rendering': 'verbatim'})
                continue
            match = re.search(r'<content>\r?\n(.*?)\r?\n\(End of file - total (\d+) lines\)\r?\n</content>',
                              value, re.DOTALL)
            if not match:
                continue
            numbered = re.findall(r'(?m)^(\d+): (.*)\r?$', match[1])
            numbers = [int(n) for n, _ in numbered]
            decoded = [line.rstrip('\r') for _, line in numbered]
            if (numbers != list(range(1, len(numbered) + 1))
                    or len(numbered) != int(match[2])):
                continue
            for offset in range(len(decoded) - len(target) + 1):
                if decoded[offset:offset + len(target)] == target:
                    found.append({'message_index': index, 'string_index': content_index,
                        'rendering': 'opencode-read-numbered-lines', 'first_line': offset + 1,
                        'last_line': offset + len(target), 'terminal_newline': 'not represented by Read'})
    return found


def reconcile(started, ended, run_id):
    issues, starts, ends = [], {}, {}
    for events, dest in ((started, starts), (ended, ends)):
        for e in events:
            if e.get('run_id') != run_id or e.get('session_id') != run_id:
                issues.append('identity_mismatch')
                continue
            rid = e.get('request_id')
            if not rid or rid in dest:
                issues.append('duplicate_or_missing_request_id')
            else:
                dest[rid] = e
    if set(ends) != set(starts):
        issues.append('incomplete_call_inventory')
    events = []
    for rid, begin in starts.items():
        end = ends.get(rid)
        if end and any(begin.get(k) != end.get(k) for k in
                       ('run_id', 'session_id', 'event_id', 'model_id', 'request_sha256')):
            issues.append('event_identity_changed')
            end = None
        e = end or begin
        if e.get('status') != 'completed' or e.get('policy_error'):
            issues.append('request_not_completed')
        events.append(e)
    if not starts:
        issues.append('no_calls_observed')
    return events, sorted(set(issues))


def collect(root):
    root = Path(root)
    manifest = util.read_json(root / 'manifest.json')
    raw = root / 'usage/raw'
    starts, start_errors = journal(raw / 'started.jsonl')
    ends, end_errors = journal(raw / 'events.jsonl')
    events, issues = reconcile(starts, ends, manifest['run_id'])
    issues += start_errors + end_errors
    if (raw / 'failure.jsonl').exists():
        issues.append('gateway_failed')
    if not manifest['stop_confirmed']:
        issues.append('stop_unconfirmed')
    isolation = root / 'evidence/isolation.json'
    if not isolation.exists() or not util.read_json(isolation).get('verified'):
        issues.append('isolation_unverified')
    context = util.read_json(root / 'context.json')
    if util.sha256_file(root / 'context.json') != manifest.get('context_sha256'):
        issues.append('context_original_mismatch')
    matches = []
    source_reads = []
    prompt_reached = False
    for event in events:
        names = (event.get('request_file', ''), event.get('response_file', ''))
        if any(not name or Path(name).name != name or '\\' in name or ':' in name for name in names):
            issues.append('invalid_original_path')
            continue
        request_path, response_path = (raw / name for name in names)
        if not request_path.is_file() or util.sha256_file(request_path) != event['request_sha256']:
            issues.append('request_original_mismatch')
            continue
        if not response_path.is_file() or util.sha256_file(response_path) != event.get('response_sha256'):
            issues.append('response_original_mismatch')
        try:
            body = util.read_json(request_path)
        except (ValueError, UnicodeError):
            issues.append('invalid_request_original')
            continue
        messages = body.get('messages', [])
        transmitted = list(strings(messages))
        if event == events[0]:
            prompt_reached = bool(input_locations(messages, (root / 'inputs/prompt.txt').read_text(encoding='utf-8')))
        for block in context['blocks']:
            # Injection must be in the first request, not a later model/tool echo.
            locations = input_locations(messages, block['text']) if event == events[0] else []
            if locations:
                matches.append({'source': block['source'], 'block_sha256': block['sha256'],
                                'request_id': event['request_id'], 'request_file': event['request_file'],
                                'input_locations': locations})
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            if msg.get('role') == 'tool' and any('/input/legacy-source/' in s for s in strings(msg)):
                source_reads.append(event['request_id'])
    reached = (True if context['method'] == 'explore' else
               {x['source'] for x in matches} == {x['source'] for x in context['blocks']})
    reached = reached and prompt_reached
    # Agent-native identifiers are kept separate from the gateway's logical session ID.
    native, _ = journal(root / 'evidence/agent.jsonl')
    native_sessions = sorted({e['sessionID'] for e in native if isinstance(e.get('sessionID'), str)})
    native_steps = sum(e.get('type') == 'step_finish' for e in native)
    if len(native_sessions) != 1 or native_steps == 0:
        issues.append('native_agent_completion_unverified')
    if native_steps > len(ends):
        issues.append('native_steps_exceed_gateway_calls')
    util.write_json_atomic(root / 'usage/context-evidence.json', {
        'method': context['method'], 'input_reached': reached, 'blocks': matches,
        'first_request_prompt_reached': prompt_reached,
        'source_read_request_ids': sorted(set(source_reads)),
        'limitation': 'Shows transmitted input, not model understanding or causal effect.'})
    util.write_json_atomic(root / 'usage/provenance.json', {
        'schema_version': 2, 'run_id': manifest['run_id'], 'source': 'sample2-gateway',
        'native_agent_session_ids': native_sessions,
        'native_step_count': native_steps,
        'expected_sessions': [manifest['run_id']], 'inventory_complete': not issues,
        'inventory_complete_basis': {'issues': sorted(set(issues)), 'started_count': len(starts),
            'ended_count': len(ends),
            'transport': 'worker internal Docker network; sole outbound gateway',
            'stop_confirmed': manifest['stop_confirmed']},
        'raw_files': sorted(p.relative_to(root / 'usage').as_posix() for p in raw.glob('*') if p.is_file()),
        'observable': ['transmitted messages and tools', 'all gateway requests including auxiliary requests',
                       'provider token usage', 'context injection'],
        'not_observable': ['provider internals', 'unreported cache/reasoning breakdown', 'model understanding']})
    (root / 'usage/events.jsonl').write_text(''.join(json.dumps(e, ensure_ascii=False) + '\n' for e in events),
                                           encoding='utf-8', newline='\n')
    run._normalize_usage(root, manifest['run_id'])
    path = root / 'usage/normalized.json'
    normalized = util.read_json(path)
    for key in ('input_tokens', 'output_tokens', 'cache_read_tokens', 'cache_write_tokens', 'reasoning_tokens'):
        vals = [(e.get('usage') or {}).get(key) for e in events]
        known = [v for v in vals if type(v) is int and v >= 0]
        normalized['observed_' + key] = sum(known) if known else None
        normalized[key] = sum(known) if events and len(known) == len(vals) and not issues else None
    normalized['input_reached'] = reached
    normalized['inventory_issues'] = sorted(set(issues))
    components = [normalized['observed_input_tokens'], normalized['observed_output_tokens']]
    normalized['observed_tokens'] = sum(v for v in components if v is not None) if any(v is not None for v in components) else None
    normalized['observed_call_count'] = len(events)
    util.write_json_atomic(path, normalized)
    return normalized
