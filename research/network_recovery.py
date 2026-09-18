"""Reclaim only preserved, stopped Run networks; never prune Docker globally."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import uuid

from outer.harness import preserve
from outer.harness.security import child_environment
from research.acquire import append
from research.analyze import read_json, sha

POOL_ERROR = 'all predefined address pools have been fully subnetted'


def docker(*args):
    result = subprocess.run(['docker', *args], capture_output=True, text=True,
                            timeout=60, env=child_environment())
    if result.returncode:
        raise RuntimeError('Docker operation failed: ' + ' '.join(args[:2]) + ': ' + result.stderr.strip())
    return result.stdout.strip()


def inventory():
    ids = docker('network', 'ls', '-q').splitlines()
    return json.loads(docker('network', 'inspect', *ids)) if ids else []


def validate_target(state, manifest, network, containers):
    """Reject active/foreign objects even when their names resemble a Run."""
    rid = manifest['run_id']
    if state.get('run_id') != rid or not state.get('stop_confirmed') or not manifest.get('stop_confirmed'):
        raise RuntimeError('Run identity or stop confirmation missing')
    name = state['network']
    if not re.fullmatch(r's2-net-[0-9a-f]{16}', name):
        raise RuntimeError('Unexpected private network name')
    if network is None:
        return
    if network['Name'] != name or (network.get('Labels') or {}).get('sample2.run') != rid:
        raise RuntimeError('Network ownership mismatch')
    if not network.get('Internal') or network.get('Driver') != 'bridge' or network.get('Containers'):
        raise RuntimeError('Network is not an unused internal bridge')
    expected = {state['worker'], state['gateway']}
    for item in containers:
        attached = name in item.get('networks', {})
        owned_name = item['name'] in expected
        if attached and not owned_name:
            raise RuntimeError('Foreign container refers to network')
        if owned_name:
            if (item.get('labels') or {}).get('sample2.run') != rid:
                raise RuntimeError('Container ownership mismatch')
            if item['state'].get('Running') or item['state'].get('Restarting') or item['state'].get('Paused'):
                raise RuntimeError('Container still active')


def container_inventory():
    # Deliberately omit environment variables, arguments and mounts.
    ids = docker('ps', '-aq').splitlines()
    result = []
    for cid in ids:
        raw = docker('inspect', cid, '--format',
                     '{"id":{{json .Id}},"name":{{json .Name}},"state":{{json .State}},'
                     '"labels":{{json .Config.Labels}},"networks":{{json .NetworkSettings.Networks}}}')
        item = json.loads(raw)
        item['name'] = item['name'].lstrip('/')
        result.append(item)
    return result


def reclaim(root, archive, log):
    root = Path(root)
    manifest = read_json(root/'manifest.json')
    state = read_json(root/'runtime.json')
    reference = read_json(root/'archive-reference.json')
    preserve.verify(archive, reference['package_id'], reference['sha256'])
    networks = inventory()
    network = next((n for n in networks if n['Name'] == state['network']), None)
    containers = container_inventory()
    validate_target(state, manifest, network, containers)
    evidence = {'run_id':manifest['run_id'], 'run_instance_id':manifest['run_instance_id'],
                'runtime_sha256':sha(root/'runtime.json'), 'archive':reference,
                'network':network, 'containers':[c for c in containers if c['name'] in (state['worker'],state['gateway'])],
                'network_count_before':len(networks)}
    append(log, {'kind':'network_reclaim_intent', **evidence})
    if network:
        # Use the exact immutable ID from the verified snapshot. Docker itself
        # rejects removal if an endpoint becomes active in the intervening time.
        docker('network', 'rm', network['Id'])
    after = inventory()
    if any(n['Name'] == state['network'] for n in after):
        raise RuntimeError('Network removal not confirmed')
    receipt = {'kind':'network_reclaimed', 'run_id':manifest['run_id'],
               'run_instance_id':manifest['run_instance_id'], 'network':state['network'],
               'removed':network is not None, 'network_count_after':len(after),
               'containers_retained':True, 'archive_verified':True}
    append(log, receipt)
    return receipt


def probe(log):
    name = 's2-recovery-probe-' + uuid.uuid4().hex[:16]
    append(log, {'kind':'network_probe_intent', 'name':name})
    nid = docker('network', 'create', '--internal', '--label', 'sample2.recovery=ms1-20260919', name)
    try:
        item = json.loads(docker('network', 'inspect', nid))[0]
        if not item['Internal'] or item.get('Containers'):
            raise RuntimeError('Unexpected probe network state')
    finally:
        docker('network', 'rm', nid)
    if any(n['Id'] == nid for n in inventory()):
        raise RuntimeError('Probe cleanup not confirmed')
    receipt = {'kind':'network_probe_pass', 'network':item, 'removed':True, 'model_called':False}
    append(log, receipt)
    return receipt


def pool_failure(root):
    root = Path(root)
    manifest = read_json(root/'manifest.json')
    error = root/'evidence/runtime-error.json'
    starts = root/'usage/raw/started.jsonl'
    return (manifest.get('end_reason') == 'environment_failure'
            and manifest.get('model_called') is False and manifest.get('stop_confirmed') is True
            and error.exists() and POOL_ERROR in read_json(error).get('message','')
            and (not starts.exists() or not starts.read_text(encoding='utf-8-sig').strip()))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--batch', type=Path, required=True)
    p.add_argument('--run-id', action='append', required=True)
    p.add_argument('--log', type=Path, required=True)
    a = p.parse_args()
    a.log.parent.mkdir(parents=True, exist_ok=True)
    for rid in a.run_id:
        if not re.fullmatch(r'MS1-001-(explore|preload|explained)-\d{3}', rid):
            raise SystemExit('Unexpected Run identifier')
        print(reclaim(a.batch/rid, a.batch/'_archive', a.log))
    probe(a.log)
    print('Internal network allocation and removal succeeded; no model called.')


if __name__ == '__main__':
    main()
