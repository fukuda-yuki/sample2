"""Owned browser-review cleanup only; reuses the Run lock and Docker wrapper."""
import json
from pathlib import Path
import re
import uuid
from contextlib import nullcontext

from . import ownership, runtime, util
from .run import now


def register(out, instance, kind, name, resource_id=None):
    path = Path(out)/'browser-resources.json'
    state = util.read_json(path) if path.exists() else {
        'owner': 's2-browser-' + uuid.uuid4().hex, 'run_instance_id': instance, 'resources': []}
    if state['run_instance_id'] != instance:
        raise ValueError('Browser resource owner mismatch')
    state['resources'].append({'kind': kind, 'name': name, 'id': resource_id})
    # Persist before creation: even a failed Docker invocation can leave a resource.
    util.write_json_atomic(path, state)
    return state['owner']


def latest(out):
    out = Path(out)
    attempts = util.read_lines(out/'browser-cleanup-attempts/index.jsonl')
    if attempts:
        return attempts[-1]
    legacy = out/'browser-cleanup.json'
    if legacy.is_file():
        value = util.read_json(legacy)
        return {**value, 'confirmed': value.get('confirmed',
                value.get('container_removed') is True and value.get('network_removed') is True)}
    return {'confirmed': False, 'status': 'not_attempted'}


def cleanup(out, *, locked=False):
    """Append a receipt; inspect identity, remove by ID, independently read absence.

    No model, evaluator, application launch, artifact write, or observation occurs.
    A failed resource does not suppress attempts to recover the other owned ones.
    """
    out = Path(out)
    with nullcontext() if locked else ownership.lease(out):
        state = util.read_json(out/'browser-resources.json')
        receipt = {'owner': state['owner'], 'run_instance_id': state['run_instance_id'],
                   'started_at': now(), 'confirmed': False, 'resources': [], 'model_called': False,
                   'browser_observed': False}
        if not re.fullmatch(r's2-browser-[0-9a-f]{32}', state['owner']):
            raise ValueError('Invalid browser owner')
        target = out/'browser-cleanup-attempts'
        target.mkdir(exist_ok=True)
        attempt = uuid.uuid4().hex
        resources = sorted(state['resources'], key=lambda r: r['kind'] == 'network')
        for resource in resources:
            item = {**resource, 'confirmed': False}
            receipt['resources'].append(item)
            try:
                kind, name = resource['kind'], resource['name']
                if kind not in ('container', 'network') or not re.fullmatch(
                        r's2-(browser|score)-[0-9a-f]{32}(-net)?', name):
                    raise ValueError('Invalid browser resource')

                def listed():
                    args = ('ps', '-a') if kind == 'container' else ('network', 'ls')
                    data = runtime.docker(*args, '--no-trunc', '--format', '{{json .}}', timeout=30)
                    return [json.loads(line) for line in data.stdout.splitlines() if line.strip()]

                name_key = 'Names' if kind == 'container' else 'Name'
                present = [r for r in listed() if r[name_key] == name or resource.get('id') == r['ID']]
                if present:
                    args = ('inspect', name) if kind == 'container' else ('network', 'inspect', name)
                    snapshot = json.loads(runtime.docker(*args, timeout=30).stdout)[0]
                    labels = snapshot['Config'].get('Labels') if kind == 'container' else snapshot.get('Labels')
                    if (snapshot['Name'].lstrip('/') != name or (labels or {}).get('sample2.browser-review') != state['owner']
                            or resource.get('id') and resource['id'] != snapshot['Id']):
                        raise RuntimeError('Browser resource ownership mismatch')
                    if kind == 'network' and (snapshot.get('Containers') or snapshot.get('Driver') != 'bridge'):
                        raise RuntimeError('Browser network still has endpoints or wrong driver')
                    item['id'] = snapshot['Id']
                    util.write_new_json(target/f'{attempt}-{len(receipt["resources"])}-intent.json',
                                        {**item, 'owner': state['owner'], 'snapshot': snapshot})
                    args = ('rm', '-f', snapshot['Id']) if kind == 'container' else ('network', 'rm', snapshot['Id'])
                    runtime.docker(*args, timeout=30)
                if any(r[name_key] == name or item.get('id') == r['ID'] for r in listed()):
                    raise RuntimeError('Browser resource removal not confirmed')
                item.update(confirmed=True, status='removed' if present else 'absent')
            except Exception as exc:
                item.update(status='failed', error={'type': type(exc).__name__, 'message': str(exc)})
        receipt.update(confirmed=all(r['confirmed'] for r in receipt['resources']), ended_at=now())
        receipt['status'] = 'complete' if receipt['confirmed'] else 'cleanup_failed'
        util.write_new_json(target/(attempt + '-result.json'), receipt)
        util.append_line(target/'index.jsonl', receipt)
        return receipt
