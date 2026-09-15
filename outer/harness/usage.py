"""Normalize sanitized usage events, never whole agent transcripts.

Ported from sample1 scripts/normalize_usage.py (aa76384654bd64bf38cc5a9ada486fb8d3a559ca).
Function names, rejection rules and the meaning of usage_complete are unchanged.
Only the module name differs.
"""
import argparse
import json
from pathlib import Path

VERSION = '1'


def normalize(events, expected_sessions, inventory_complete=False):
    totals, last, seen, modes, missing = {}, {}, {}, {}, []
    calls = 0
    run_ids = {e['run_id'] for e in events}
    if len(run_ids) > 1:
        raise ValueError('Cannot combine runs')
    for e in events:
        session = e['session_id']
        key = (session, e['event_id'])
        if key in seen:
            if seen[key] != e:
                raise ValueError('Conflicting duplicate event')
            continue
        seen[key] = e
        if e.get('includes_children', False):
            raise ValueError('Parent-inclusive totals cannot be combined with per-session events')
        if session not in expected_sessions:
            raise ValueError('Unregistered session')
        mode = e['mode']
        if mode not in ('request', 'cumulative') or modes.setdefault(session, mode) != mode:
            raise ValueError('Use exactly one accounting mode per session')
        u = e.get('usage')
        if not u or u.get('input_tokens') is None or u.get('output_tokens') is None:
            missing.append({'session_id': session, 'event_id': e['event_id'], 'reason': 'usage_missing'})
            continue
        counts = (u['input_tokens'], u['output_tokens'])
        if any(type(n) is not int or n < 0 for n in counts):
            raise ValueError('Token counts must be nonnegative integers')
        if mode == 'request':
            request_key = ('request', e['request_id'])
            if request_key in seen:
                if seen[request_key] != counts:
                    raise ValueError('Conflicting request usage')
                continue
            seen[request_key] = counts
            delta = counts
            calls += 1
        else:
            previous = last.get(session, (0, 0))
            delta = tuple(n - p for n, p in zip(counts, previous))
            if min(delta) < 0:
                raise ValueError('Cumulative reset/out-of-order event requires a new session')
            last[session] = counts
        totals[session] = totals.get(session, 0) + sum(delta)
    for session in expected_sessions:
        if session not in totals:
            missing.append({'session_id': session, 'reason': 'session_unobserved'})
    if not inventory_complete:
        missing.append({'reason': 'call_and_session_inventory_unverified'})
    complete = not missing
    observed = sum(totals.values())
    return {'normalizer_version': VERSION, 'usage_complete': complete,
            'total_tokens': observed if complete else None, 'observed_tokens': observed,
            'observed_request_count': calls, 'sessions': totals, 'missing': missing,
            'cumulative_sessions': [s for s, m in modes.items() if m == 'cumulative']}


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('input', type=Path)
    p.add_argument('output', type=Path)
    a = p.parse_args()
    data = json.loads(a.input.read_text(encoding='utf-8'))
    result = normalize(data['events'], data['expected_sessions'], data.get('inventory_complete', False))
    a.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
