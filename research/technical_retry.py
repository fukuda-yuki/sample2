"""Evidence-bound fresh-UUID eligibility, separate from same-Run message replay.

No quality fields or scorer outputs participate. Unknown causes require repair;
saved normally completed acquisitions require recovery, never model resampling.
"""
from pathlib import Path

from outer.harness import live_usage, util
from research import live_pilot, pair_execution

POLICY = 'sealed_infrastructure_failure_v1'
NETWORK_ERRORS = {'TimeoutError', 'ConnectionError', 'ConnectionResetError',
                  'ConnectionRefusedError', 'RemoteDisconnected', 'IncompleteRead',
                  'BrokenPipeError', 'gaierror'}


def inventory(batch):
    result = {}
    for root in Path(batch).glob('*/manifest.json'):
        for name in ('manifest.json', 'runtime.json', 'stop-request.json',
                     'evidence', 'usage/raw', '_controller/staged-input'):
            path = root.parent/name
            if path.is_file(): result[path.relative_to(batch).as_posix()] = util.sha256_file(path)
            elif path.is_dir():
                result.update({(path.relative_to(batch)/key).as_posix(): value
                               for key,value in util.tree_hashes(path).items()})
    for name in ('_control/pair-journal.jsonl', 'observer-terminal.json', 'phase.json', 'pipeline-attempt.json'):
        path = Path(batch)/name
        if path.is_file(): result[name] = util.sha256_file(path)
    return result


def classify(batch):
    try: return _classify(batch)
    except (OSError, ValueError, KeyError, TypeError): return None


def _classify(batch):
    """A narrow provider infrastructure allowlist; never infer from error prose."""
    batch = Path(batch)
    attempt = util.read_json(batch/'pipeline-attempt.json')
    phase = util.read_json(live_pilot.checked(attempt['phase']))
    cases = [c for a in phase['assignments'] for c in a['cases']]
    manifests = list(batch.glob('*/manifest.json'))
    if len(cases) != 1 or len(manifests) != 1: return None
    case = cases[0]; root = manifests[0].parent; manifest = util.read_json(manifests[0])
    if (root.name != case['run_id'] or any(manifest.get(k) != case[k] for k in ('run_id','run_instance_id'))
            or manifest.get('stop_confirmed') is not True
            or (manifest.get('network_cleanup') or {}).get('confirmed') is not True
            or manifest.get('end_reason') not in ('provider_failure','operator_stop','environment_failure','agent_error')):
        return None
    dispatch = pair_execution.state(batch/'_control/pair-journal.jsonl')['dispatch'].get(case['run_id'])
    if not dispatch or any(dispatch.get(k) != case[k] for k in ('run_id','run_instance_id')): return None
    allocation = root/'evidence/infrastructure-failure.json'
    if allocation.exists():
        evidence = util.read_json(allocation)
        if (evidence.get('kind')=='owned_worker_oom_v1' and evidence.get('oom_killed') is True
                and manifest['end_reason']=='agent_error'
                and all(evidence.get(k)==case[k] for k in ('run_id','run_instance_id'))):
            return dict(run_id=case['run_id'],run_instance_id=case['run_instance_id'],
                        causes=[dict(kind='owned_worker_oom',evidence=evidence)])
        if (evidence.get('kind') == 'owned_docker_allocation_failure_v1'
                and evidence.get('phase') == 'allocation'
                and all(evidence.get(k) == case[k] for k in ('run_id','run_instance_id'))
                and manifest['end_reason'] == 'environment_failure'
                and not (root/'usage/raw/started.jsonl').exists()):
            return dict(run_id=case['run_id'],run_instance_id=case['run_instance_id'],
                        causes=[dict(kind='docker_allocation',evidence=evidence)])
        return None
    if manifest['end_reason']=='agent_error':return None
    events, errors = live_usage.journal(root/'usage/raw/events.jsonl')
    starts, more = live_usage.journal(root/'usage/raw/started.jsonl')
    failures, malformed = live_usage.journal(root/'usage/raw/failure.jsonl')
    if errors or more or malformed or not failures: return None
    if any(f.get('request_id') is None for f in failures): return None
    start_ids = [s.get('request_id') for s in starts]
    if len(set(start_ids)) != len(start_ids) or len({e.get('request_id') for e in events}) != len(events): return None
    causes = []
    for event in events:
        if (event.get('run_id') != case['run_id'] or event.get('session_id') != case['run_instance_id']
                or event.get('request_id') not in start_ids): return None
        status = event.get('http_status'); policy = event.get('policy_error')
        # Missing model identity on an upstream error response is expected;
        # an actual wrong model or credential exposure is not a retry cause.
        if policy and not (policy == 'response_model_mismatch' and not event.get('response_model_id')): return None
        if status == 429 or type(status) is int and 500 <= status <= 599:
            causes.append(dict(request_id=event['request_id'], kind='provider_http', http_status=status))
        elif (event.get('status') == 'transport_error' and event.get('error_type') in NETWORK_ERRORS
              and status in (None, 200)):
            causes.append(dict(request_id=event['request_id'], kind='provider_transport', error_type=event['error_type']))
        elif event.get('status') not in ('completed','cancelled'): return None
    if not causes: return None
    return dict(run_id=case['run_id'], run_instance_id=case['run_instance_id'], causes=causes)


def seal(batch, usage):
    evidence = classify(batch)
    if evidence is None: return None
    path = Path(batch)/'technical-retry-evidence.json'
    util.write_new_json(path, dict(kind=POLICY, evidence=evidence, inventory=inventory(Path(batch)),
        usage=usage, same_run_resend=False, retry_requires_new_uuid=True))
    return live_pilot.reference(path)


def eligible(batch, saved):
    try:
        ref = saved.get('technical_retry_evidence')
        if not ref or live_pilot.checked(ref) != Path(batch)/'technical-retry-evidence.json': return False
        receipt = util.read_json(Path(batch)/'technical-retry-evidence.json')
        return (receipt['kind'] == POLICY and receipt['evidence'] == classify(batch)
            and receipt['inventory'] == inventory(Path(batch)) and receipt['usage'] == saved['usage']
            and receipt['same_run_resend'] is False and receipt['retry_requires_new_uuid'] is True)
    except (OSError, ValueError, KeyError, TypeError):
        return False
