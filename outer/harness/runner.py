"""Scripted runners that never call a model.

`dummy` writes a scripted workspace and scripted usage events so the outer
harness can be exercised without a model. It runs as a separate process so the
harness has a real exit code and a real process exit to confirm.

This module is not a model client. There is no model-calling path in `outer/`.
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

from . import util

RUNNERS = ('dummy', 'manual')

# Scenarios the dummy runner can produce. Every one is a non-model situation the
# harness must record without turning it into a score.
DUMMY_SCENARIOS = (
    'ok',
    'crlf',
    'crash',
    'empty',
    'no-usage',
    'partial-usage',
    'conflict-usage',
    'cumulative-usage',
    'no-provenance',
    'no-usage-id',
)

SESSION_MAIN = 'session-main'
SESSION_SUB = 'session-subagent'


def _event(run_id, session, event_id, request_id, input_tokens, output_tokens, mode='request'):
    return {'run_id': run_id, 'session_id': session, 'event_id': event_id,
            'request_id': request_id, 'mode': mode,
            'usage': {'input_tokens': input_tokens, 'output_tokens': output_tokens},
            'includes_children': False}


def _complete_events(run_id):
    return [
        _event(run_id, SESSION_MAIN, 'e1', 'r1', 1200, 300),
        _event(run_id, SESSION_MAIN, 'e2', 'r2', 3400, 800),
        _event(run_id, SESSION_MAIN, 'e3', 'r3', 500, 120),
        _event(run_id, SESSION_SUB, 'e1', 'r4', 900, 200),
    ]


def _write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def _write_events(usage_dir, events):
    path = Path(usage_dir) / 'events.jsonl'
    path.parent.mkdir(parents=True, exist_ok=True)
    text = ''.join(json.dumps(e, ensure_ascii=False) + '\n' for e in events)
    path.write_text(text, encoding='utf-8')


def _provenance(run_id, sessions, inventory_complete=True, basis=None):
    return {
        'schema_version': 1,
        'run_id': run_id,
        'source': 'scripted by outer/harness/runner.py (dummy runner); no model was called',
        'raw_files': ['raw/usage-dump.json'],
        'expected_sessions': list(sessions),
        'inventory_complete': inventory_complete,
        'inventory_complete_basis': basis,
        'observable': ['per-request input_tokens and output_tokens for the scripted sessions'],
        'not_observable': ['model prompts', 'tool results', 'conversation history',
                           'compaction', 'whether a comparison intervention reached the input'],
    }


def _to_crlf_with_bom(workspace):
    """Rewrite text files so collection has something to normalize."""
    changed = []
    for path in sorted(Path(workspace).rglob('*')):
        if not path.is_file() or path.suffix.lower() not in ('.cs', '.cshtml', '.json'):
            continue
        data = path.read_bytes()
        if data.startswith(b'\xef\xbb\xbf'):
            data = data[3:]
        data = data.replace(b'\r\n', b'\n').replace(b'\r', b'\n').replace(b'\n', b'\r\n')
        path.write_bytes(b'\xef\xbb\xbf' + data)
        changed.append(str(path.relative_to(workspace)).replace('\\', '/'))
    return changed


def _ignored_directories(directory, names):
    """Skip the directories that collection and hashing drop anyway.

    The seed is a fixture on disk; a leftover `bin/` or `obj/` in it must not
    leak into the recorded workspace.
    """
    return [name for name in names
            if name.lower() in util.EXCLUDED_DIRECTORIES]


def run_dummy(run_id, workspace, usage_dir, scenario, seed=None, timeout_note=None):
    workspace, usage_dir = Path(workspace), Path(usage_dir)
    if scenario not in DUMMY_SCENARIOS:
        raise ValueError('Unknown scenario: ' + scenario)
    workspace.mkdir(parents=True, exist_ok=True)
    if scenario != 'empty':
        if seed is None:
            raise ValueError('Scenario ' + scenario + ' requires --seed')
        seed = Path(seed)
        if not seed.is_dir():
            raise FileNotFoundError(seed)
        for entry in sorted(seed.iterdir()):
            target = workspace / entry.name
            if entry.is_dir():
                shutil.copytree(entry, target, ignore=_ignored_directories)
            else:
                shutil.copy2(entry, target)

    if scenario == 'empty':
        return 0

    if scenario == 'crlf':
        _to_crlf_with_bom(workspace)

    if scenario == 'no-usage':
        _write_json(usage_dir / 'raw' / 'usage-dump.json',
                    {'run_id': run_id, 'events': [], 'note': 'scripted empty usage'})
        _write_json(usage_dir / 'provenance.json',
                    _provenance(run_id, [SESSION_MAIN, SESSION_SUB], True,
                                'scripted: the dummy runner emitted no events at all'))
        _write_events(usage_dir, [])
        return 0

    if scenario == 'partial-usage':
        events = [e for e in _complete_events(run_id) if e['session_id'] == SESSION_MAIN]
        _write_json(usage_dir / 'raw' / 'usage-dump.json', {'run_id': run_id, 'events': events})
        _write_json(usage_dir / 'provenance.json',
                    _provenance(run_id, [SESSION_MAIN, SESSION_SUB], True,
                                'scripted: the second session was expected but not emitted'))
        _write_events(usage_dir, events)
        return 0

    if scenario == 'conflict-usage':
        events = _complete_events(run_id)
        conflict = dict(events[0])
        conflict['usage'] = {'input_tokens': 9999, 'output_tokens': 1}
        events.append(conflict)
        _write_json(usage_dir / 'raw' / 'usage-dump.json', {'run_id': run_id, 'events': events})
        _write_json(usage_dir / 'provenance.json',
                    _provenance(run_id, [SESSION_MAIN, SESSION_SUB], True,
                                'scripted: a duplicate event_id carries different usage'))
        _write_events(usage_dir, events)
        return 0

    if scenario == 'cumulative-usage':
        events = [
            _event(run_id, SESSION_MAIN, 'e1', 'c1', 1200, 300, mode='cumulative'),
            _event(run_id, SESSION_MAIN, 'e2', 'c2', 4600, 1100, mode='cumulative'),
            _event(run_id, SESSION_MAIN, 'e3', 'c3', 5100, 1220, mode='cumulative'),
            _event(run_id, SESSION_SUB, 'e1', 'r4', 900, 200),
        ]
        _write_json(usage_dir / 'raw' / 'usage-dump.json', {'run_id': run_id, 'events': events})
        _write_json(usage_dir / 'provenance.json',
                    _provenance(run_id, [SESSION_MAIN, SESSION_SUB], True,
                                'scripted: one session reports cumulative totals, the other per request'))
        _write_events(usage_dir, events)
        return 0

    if scenario == 'no-provenance':
        _write_json(usage_dir / 'raw' / 'usage-dump.json',
                    {'run_id': run_id, 'events': _complete_events(run_id)})
        _write_events(usage_dir, _complete_events(run_id))
        return 0

    if scenario == 'no-usage-id':
        events = _complete_events(run_id)
        events[1] = dict(events[1])
        events[1]['usage'] = {'input_tokens': None, 'output_tokens': None}
        _write_json(usage_dir / 'raw' / 'usage-dump.json', {'run_id': run_id, 'events': events})
        _write_json(usage_dir / 'provenance.json',
                    _provenance(run_id, [SESSION_MAIN, SESSION_SUB], False,
                                'scripted: the runner could not read usage for one request'))
        _write_events(usage_dir, events)
        return 0

    events = _complete_events(run_id)
    _write_json(usage_dir / 'raw' / 'usage-dump.json', {'run_id': run_id, 'events': events})
    _write_json(usage_dir / 'provenance.json',
                _provenance(run_id, [SESSION_MAIN, SESSION_SUB], True,
                            'scripted: the dummy runner emitted every event it produced'))
    _write_events(usage_dir, events)
    if scenario == 'crash':
        sys.stderr.write('dummy runner: scripted failure\n')
        return 3
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description='Scripted runner. Does not call a model.')
    parser.add_argument('--scenario', required=True, choices=DUMMY_SCENARIOS)
    parser.add_argument('--workspace', required=True, type=Path)
    parser.add_argument('--usage', required=True, type=Path)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--seed', type=Path)
    args = parser.parse_args(argv)
    return run_dummy(args.run_id, args.workspace, args.usage, args.scenario, args.seed)


if __name__ == '__main__':
    sys.exit(main())
