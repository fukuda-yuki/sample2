"""Gateway-derived OTLP through the existing monitor importer, with raw readback."""
from contextlib import closing
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from . import runtime, util


def attributes(values):
    return [{'key': k, 'value': {'intValue': str(v)} if type(v) is int else {'stringValue': v}}
            for k, v in values.items() if v is not None]


def payload(events, run_id, manifest=None):
    manifest = manifest or {}
    trace = hashlib.sha256(('sample2:' + run_id).encode()).hexdigest()[:32]
    spans = []
    for e in events:
        usage = e.get('usage') or {}
        start = int(datetime.fromisoformat(e['started_at']).timestamp() * 1e9)
        end = int(datetime.fromisoformat(e.get('ended_at', e['started_at'])).timestamp() * 1e9)
        spans.append({'traceId': trace, 'spanId': hashlib.sha256(e['request_id'].encode()).hexdigest()[:16],
            'name': 'chat ' + e['model_id'], 'kind': 3, 'startTimeUnixNano': str(start),
            'endTimeUnixNano': str(end), 'attributes': attributes({
                'gen_ai.operation.name': 'chat', 'gen_ai.request.model': e['model_id'],
                'gen_ai.conversation.id': e.get('session_id', run_id), 'sample2.request.id': e['request_id'],
                'gen_ai.usage.input_tokens': usage.get('input_tokens'),
                'gen_ai.usage.output_tokens': usage.get('output_tokens'),
                'sample2.cache_read_tokens': usage.get('cache_read_tokens'),
                'sample2.cache_write_tokens': usage.get('cache_write_tokens'),
                'sample2.reasoning_tokens': usage.get('reasoning_tokens')}),
            'status': {'code': 1 if e.get('status') == 'completed' else 2}})
    return {'resourceSpans': [{'resource': {'attributes': attributes({
        'service.name': 'sample2-gateway', 'client.kind': 'sample2-gateway', 'run.id': run_id,
        'sample2.run_instance_id': manifest.get('run_instance_id'),
        'experiment.id': run_id, 'task.id': manifest.get('task_id'),
        'task.run_index': manifest.get('attempt'), 'experiment.condition': manifest.get('intervention_id'),
        'sample2.provenance': 'gateway-derived; not native OpenCode telemetry'})},
        'scopeSpans': [{'scope': {'name': 'sample2.gateway', 'version': '1'}, 'spans': spans}]}]}


def link(repo, root):
    root = Path(root).resolve()
    events = util.read_lines(root / 'usage/events.jsonl')
    manifest = util.read_json(root / 'manifest.json') if (root / 'manifest.json').exists() else {}
    data = payload(events, root.name, manifest)
    directory = root / 'telemetry'
    directory.mkdir(exist_ok=True)
    raw = directory / 'gateway.otlp.json'
    if raw.exists():
        if util.read_json(raw) != data:
            raise ValueError('Telemetry original changed; use a new export directory')
    else:
        util.write_new_json(raw, data)
    monitor_root = Path(os.environ.get('SAMPLE2_MONITOR_ROOT',
        str(Path.home() / 'Documents/Codex/copilot-agent-observability')))
    project = monitor_root / 'src/CopilotAgentObservability.ConfigCli/CopilotAgentObservability.ConfigCli.csproj'
    if not project.exists():
        raise RuntimeError('Set SAMPLE2_MONITOR_ROOT to the existing local-agent-monitor checkout')
    database = directory / 'monitor.db'
    invocation = ['dotnet', 'run', '--project', str(project), '-c', 'Release', '--',
                  'ingest-raw', str(raw), '--db', str(database)]
    # The monitor importer is append-only, not idempotent. Never import twice.
    if not database.exists():
        result = runtime.command(invocation, timeout=300)
        (directory / 'importer.log').write_text(result.stdout + result.stderr, encoding='utf-8')
    found = []
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('PRAGMA query_only=ON')
        for ident, value in db.execute('SELECT id,payload_json FROM raw_records ORDER BY id'):
            parsed = json.loads(value)
            if parsed == data:
                found.append(ident)
    normalized = directory / 'normalized-readback.json'
    normalization = runtime.command(['dotnet', 'run', '--project', str(project), '-c', 'Release', '--',
                                      'normalize-raw', str(database), '--json', str(normalized)], timeout=300)
    (directory / 'normalizer.log').write_text(normalization.stdout + normalization.stderr, encoding='utf-8')
    rows = util.read_json(normalized)
    expected = {'experiment_id': root.name, 'turn_count': len(events)}
    for key in ('input_tokens', 'output_tokens'):
        values = [(e.get('usage') or {}).get(key) for e in events]
        expected[key] = sum(values) if values and all(type(v) is int and v >= 0 for v in values) else None
    readback = rows[0] if len(rows) == 1 else {}
    comparison = {k: {'expected': v, 'observed': readback.get(k), 'matched': readback.get(k) == v}
                  for k, v in expected.items()}
    receipt = {'verified': len(found) == 1 and all(v['matched'] for v in comparison.values()),
               'readback': comparison, 'raw_record_ids': found, 'request_count': len(events),
               'source': 'gateway-derived OTLP, not native agent telemetry',
               'raw_sha256': util.sha256_file(raw), 'database': 'telemetry/monitor.db',
               'monitor_commit': runtime.command(['git', '-C', str(monitor_root), 'rev-parse', 'HEAD']).stdout.strip(),
               'command': invocation}
    util.write_json_atomic(root / 'telemetry-link.json', receipt)
    if not receipt['verified']:
        raise RuntimeError('Monitor readback did not match the original')
    return receipt
