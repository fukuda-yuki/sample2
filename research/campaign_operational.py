"""Finite providerless operational acceptance using existing production boundaries.

The explicit dummy backend never prompts a model. OpenCode sessions are real;
the artifact subprocess is synthetic and cannot measure research quality.
Historical v5 plan/pin checks and data are unchanged. No remote publication here.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

from outer.harness import ownership, run, runtime, util
from research import experiment_identity as identity, pair_execution as pairs
from research.resource_supervisor import ProcessMonitor, FIXTURE_KIND, safe_environment

PIN_FILES = ('research/campaign_operational.py', 'research/experiment_identity.py',
    'research/pair_execution.py', 'research/resource_supervisor.py', 'outer/harness/runtime.py',
    'outer/harness/gateway.py', 'outer/harness/ownership.py', 'outer/harness/util.py',
    'outer/harness/run.py', 'outer/harness/security.py')
KIND = 'providerless_operational_acceptance_v1'


def inventory(root):
    root = Path(root).resolve()
    util.reject_links(root)
    return {p.relative_to(root).as_posix(): util.sha256_file(p)
            for p in root.rglob('*') if p.is_file()}


def verify_unchanged(root, before):
    if inventory(root) != before: raise ValueError('Immutable bytes changed')


def verify_pins(repo, pins, *, required=PIN_FILES):
    repo = Path(repo).resolve()
    if not set(required) <= set(pins): raise ValueError('Missing executing-source pins')
    for name, digest in pins.items():
        relative = identity._relative(name)
        path = (repo / str(relative)).resolve()
        if not path.is_relative_to(repo) or util.sha256_file(path) != digest:
            raise ValueError('Executing-source pin mismatch: ' + name)


def verify_run(root, binding):
    root = Path(root)
    manifest = util.read_json(root / 'manifest.json')
    if any(manifest.get(k) != binding[k] for k in ('run_id', 'run_instance_id')):
        raise ValueError('Foreign or stale Run identity')
    marker = root / 'stop-request.json'
    if marker.exists() and any(util.read_json(marker).get(k) != binding[k]
                               for k in ('run_id', 'run_instance_id')):
        raise ValueError('Foreign or stale STOP identity')
    return manifest


def validate_session(value):
    session = value.get('created', {}).get('id')
    if (not isinstance(session, str) or not session.startswith('ses_')
            or value.get('read', {}).get('id') != session or value.get('abort') is not True
            or value.get('messages') != [] or value.get('status', {}).get(session, {}).get('type', 'idle') != 'idle'):
        raise ValueError('Real providerless session evidence not complete')
    return session


def gateway_count(records):
    records = Path(records)
    # A request creates an event or payload evidence, including a failed upstream.
    event = records / 'events.jsonl'
    count = sum(bool(line.strip()) for line in event.read_text(encoding='utf8').splitlines()) if event.exists() else 0
    unexpected = [p for p in records.iterdir() if p.name != 'control.jsonl' and
                  (p.name != 'events.jsonl' or p.stat().st_size)]
    if count or unexpected: raise ValueError('Unexpected gateway request or payload evidence')
    return 0


def validate_fence(receipt, binding):
    ack = receipt.get('acknowledgement', receipt)
    if (any(receipt.get(k) != binding[k] for k in ('run_id', 'run_instance_id'))
            or receipt.get('confirmed') is not True or receipt.get('method') != 'gateway_ack'
            or ack.get('admission_closed') is not True):
        raise ValueError('Independent gateway ACK not bound')
    if 'acknowledgement' in receipt and (ack.get('run_id') != binding['run_id']
            or ack.get('session_id') != binding['run_instance_id'] or not ack.get('closed_at')):
        raise ValueError('Foreign gateway acknowledgement')


def validate_artifact_shape(root, *, partial, child_exit):
    root = Path(root)
    expected = {'partial.json'} if partial else {'partial.json', 'artifact.json'}
    if child_exit is None or (not partial and child_exit != 0) or set(inventory(root)) != expected:
        raise ValueError('Actual stopped artifact shape disagrees with completion mode')
    if not partial and (root / 'artifact.json').read_bytes() != (root / 'partial.json').read_bytes():
        raise ValueError('Normal final artifact differs from observed partial bytes')


def validate_active_sample(snapshot, binding):
    if snapshot.get('resource_healthy') is not True: raise ValueError('Active resource health unavailable')
    for name, digest in snapshot['evidence_files'].items():
        if util.sha256_file(name) != digest: raise ValueError('Resource evidence bytes changed')
        record = util.read_json(name)
        if 'sample' not in record: continue
        sample = record['sample']
        rows = [row for row in sample.get('containers', [])
                if all(row.get(k) == binding[k] for k in ('run_id', 'run_instance_id'))]
        if (sample.get('ok') is True and {row.get('role') for row in rows} == {'worker', 'gateway'}
                and len(rows) == 2 and all(row.get('running') is True
                    and isinstance(row.get('memory_usage_bytes'), int)
                    and isinstance(row.get('container_id'), str) and len(row['container_id']) == 64 for row in rows)):
            return {'path': name, 'sha256': digest, 'sampled_at': snapshot['sampled_at'],
                    'run_id': binding['run_id'], 'run_instance_id': binding['run_instance_id']}
    raise ValueError('Actual active worker/gateway sample not bound to this Run')


def _http(container, port, method, path, body=None):
    script = """import http.client,json,sys
c=http.client.HTTPConnection('127.0.0.1',int(sys.argv[1]),timeout=5)
b=json.loads(sys.argv[4]); data=None if b is None else json.dumps(b).encode()
c.request(sys.argv[2],sys.argv[3],data,{'Content-Type':'application/json'})
r=c.getresponse(); raw=r.read()
try: body=json.loads(raw) if raw else None
except ValueError: body=None
print(json.dumps({'status':r.status,'body':body,'response_sha256':__import__('hashlib').sha256(raw).hexdigest()}))
"""
    result = runtime.docker('exec', container, 'python3', '-c', script,
        str(port), method, path, json.dumps(body), timeout=10)
    return json.loads(result.stdout)


def _ok(response, status=200):
    if response['status'] != status: raise ValueError('Unexpected local SDK/control HTTP status')
    return response['body']


def _lease_collision(control):
    script = """from pathlib import Path
import sys
from outer.harness import ownership
try:
 with ownership.lease(Path(sys.argv[1])): raise SystemExit(9)
except (BlockingIOError,OSError): raise SystemExit(0)
"""
    result = subprocess.run([sys.executable, '-B', '-X', 'utf8', '-c', script, str(control)],
        env=safe_environment(), capture_output=True, timeout=10,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode != 0: raise ValueError('OS lease collision was not rejected')
    return {'real_subprocess': True, 'foreign_lease_rejected': True, 'exit_code': result.returncode}


def prepare_plan(repo, destination, *, original, protected):
    """Exclusive allocation only; no containers/process/model before fixed plan."""
    repo, destination, original = map(lambda p: Path(p).resolve(), (repo, destination, original))
    if destination.exists(): raise FileExistsError(destination)
    if destination.is_relative_to(original) or original.is_relative_to(destination):
        raise ValueError('Original and acceptance roots must be separate')
    source = original / 'runs/source-info-v5-100p2/CU1-ENR-D-explore-5073'
    source_manifest = util.read_json(source / 'manifest.json')
    source_snapshot = util.read_json(source / 'snapshot.json')
    source_condition = util.read_json(source / 'condition.json')
    commit = subprocess.run(['git', '-c', 'safe.directory=' + str(repo), 'rev-parse', 'HEAD'],
        cwd=repo, env=safe_environment(), capture_output=True, text=True, timeout=15, check=True).stdout.strip()
    if len(commit) != 40 or any(c not in '0123456789abcdef' for c in commit):
        raise ValueError('Actual source commit required')
    if not source_manifest['stop_confirmed'] or not source_manifest['submission_fixed']:
        raise ValueError('Known saved source is not immutable')
    if util.artifact_hash(source / 'frozen') != source_snapshot['artifact_sha256']:
        raise ValueError('Known saved source artifact mismatch')
    monitor = original / 'artifacts/main-central-wave-v8-fixed-20261005/wave_resource_monitor.py'
    probe = monitor.with_name('wave_resource_probe.py')
    original_runs = original / 'runs/source-info-v5-100p2'
    protected = [original_runs, *[Path(p).resolve() for p in protected]]
    if any(destination.is_relative_to(p) or p.is_relative_to(destination) for p in protected):
        raise ValueError('Acceptance root overlaps protected data')
    destination.mkdir(parents=True, exist_ok=False)
    immutable = {str(p): inventory(p) for p in protected}
    util.write_new_json(destination / 'original-before.json', immutable)
    inputs = destination / 'saved-input'; inputs.mkdir()
    for name in ('snapshot.json', 'manifest.json', 'condition.json'):
        shutil.copyfile(source / name, inputs / name)
    # Saved byte inventory is input, not a private application/database export.
    prefix = source.name + '/'
    source_bytes = {name[len(prefix):]: digest for name, digest in immutable[str(original_runs)].items()
                    if name.startswith(prefix)}
    util.write_new_json(inputs / 'source-bytes.json', source_bytes)
    assignments = []
    for number in (1, 2):
        cases = [{'run_id': f'nonmodel-{number}-{slot}', 'run_instance_id': uuid.uuid4().hex,
            'task': 'saved-byte-observer', 'condition': 'providerless-dummy', 'attempt': slot,
            'pair': 1, 'slot': slot, 'mode': 'middle_stop' if (number, slot) == (2, 2) else 'normal'}
            for slot in (1, 2)]
        assignments.append({'campaign_id': f'operational-{number}', 'cases': cases})
    plan = {'schema_version': 1, 'kind': KIND, 'backend': 'providerless-opencode-session', 'source_commit': commit,
        'max_model_calls': 0, 'max_runs': 4, 'max_sessions': 4, 'pair_concurrency': 1,
        'require_fixed_instances': True, 'source_pins': {n: util.sha256_file(repo / n) for n in PIN_FILES},
        'source': {'run_id': source_manifest['run_id'], 'run_instance_id': source_manifest['run_instance_id'],
            'campaign_uuid': None, 'source_campaign_binding': 'caller_asserted_unverified',
            'artifact_sha256': source_snapshot['artifact_sha256'],
            'snapshot_sha256': util.sha256_file(source / 'snapshot.json')},
        'images': {k: source_condition['runtime_lock']['images'][k] for k in ('worker', 'gateway')},
        'opencode_version': source_condition['runtime_lock']['opencode_version'],
        'resource_monitor': {'path': str(monitor), 'sha256': util.sha256_file(monitor)},
        'resource_probe': {'path': str(probe), 'sha256': util.sha256_file(probe)},
        'assignments': assignments, 'protected_roots': list(immutable),
        'input_inventory': inventory(inputs), 'worker_seconds_estimate': 120,
        'operation_timeout_max_seconds': 120, 'root_supervision_deadline_seconds': 900,
        'limits': ['Nonmodel operational acceptance, not research acquisition or quality measurement.',
                   'Session HTTP lifecycle verified; prompt/SDK generation path untested.',
                   'Publication gate remains pending until separately verified real release.']}
    util.write_new_json(destination / 'plan.json', plan)
    return destination / 'plan.json'


class Backend:
    """Same dispatcher callback path; explicitly selected synthetic artifact backend."""
    def __init__(self, repo, base, plan, campaign, phase):
        self.repo, self.base, self.plan, self.campaign, self.phase = repo, base, plan, campaign, phase
        self.batch = campaign.root / 'runs'
        self.bindings, self.dispatched, self.ready = [], [], False
        self.monitor = ProcessMonitor(phase, campaign.root / '_control/observer', self.scope)

    def scope(self):
        return {'pairs': [1] if self.bindings else [], 'assignments': self.bindings, 'dispatched': self.dispatched}

    def prepare(self, binding):
        verify_pins(self.repo, self.plan['source_pins'])
        binding['phase_sha256'] = util.sha256_file(self.phase)
        root = self.batch / binding['run_id']; root.mkdir(exist_ok=False)
        for name in ('inputs', 'workspace', 'state', 'usage/raw', 'evidence', 'output'):
            (root / name).mkdir(parents=True)
        for name in self.plan['input_inventory']:
            shutil.copyfile(self.base / 'saved-input' / name, root / 'inputs' / name)
        util.write_new_json(root / 'inputs/prompt.txt', {'kind': 'nonmodel-no-prompt', 'model_calls': 0})
        manifest = {**binding, 'schema_version': 1, 'kind': 'nonmodel_operational_run',
            'assignment': dict(binding), 'prompt_sha256': util.sha256_file(root / 'inputs/prompt.txt'),
            'condition_sha256': util.sha256_file(root / 'inputs/condition.json'),
            'started_at': None, 'stop_confirmed': False, 'synthetic': True, 'model_called': False}
        util.write_new_json(root / 'manifest.json', manifest)
        util.write_new_json(root / 'run.json', {'schema_version': 1, 'kind': 'acquisition_run',
            'campaign_uuid': self.campaign.campaign_uuid, 'campaign_id': self.campaign.metadata['campaign_id'],
            'run_label': binding['run_id'], 'run_instance_id': str(uuid.UUID(binding['run_instance_id']))})
        self.bindings.append(binding)
        return manifest

    @contextmanager
    def admit(self, binding):
        verify_pins(self.repo, self.plan['source_pins'])
        if (self.campaign.root / '_control/operator-stop.json').exists():
            raise ValueError('Parent supervision stopped this campaign')
        verify_run(self.batch / binding['run_id'], binding)
        if not self.ready:
            self.monitor.enroll_ready(self.scope()); self.ready = True
        self.monitor.admit(binding)
        self.dispatched.append(binding['run_id'])
        yield

    def implement(self, repo, batch, run_id):
        root = Path(batch) / run_id
        b = next(x for x in self.bindings if x['run_id'] == run_id)
        with ownership.lease(root):
            manifest = verify_run(root, b)
            if (self.campaign.root / '_control/operator-stop.json').exists():
                raise ValueError('Parent supervision stopped before runtime creation')
            unique = uuid.uuid4().hex[:16]
            state = {'run_id': run_id, 'run_instance_id': b['run_instance_id'],
                'worker': 's2-worker-' + unique, 'gateway': 's2-gateway-' + unique,
                'network': 's2-net-' + unique, 'started_at': run.now()}
            util.write_new_json(root / 'runtime.json', state)
            manifest.update(started_at=run.now()); util.write_json_atomic(root / 'manifest.json', manifest)
            child = None; child_log = None
            session = {}; stopped = False; live_middle_stop = False
            try:
                for digest in self.plan['images'].values():
                    if runtime.image_id(digest) != digest: raise ValueError('Pinned image changed')
                state['network_id'] = runtime.docker('network', 'create', '--internal',
                    '--label', 'sample2.run=' + run_id, '--label', 'sample2.instance=' + b['run_instance_id'],
                    state['network']).stdout.strip()
                util.write_json_atomic(root / 'runtime.json', state)
                gateway = ("import sys;sys.path.insert(0,'/app');from gateway import Gateway;"
                    "Gateway(('0.0.0.0',8080),'/records',sys.argv[1],'nonmodel',"
                    "'nonmodel-inert-credential',session_id=sys.argv[2],upstream_host='127.0.0.1',"
                    "upstream_port=9,tls=False).serve_with_signals()")
                labels = ['--label', 'sample2.run=' + run_id, '--label', 'sample2.instance=' + b['run_instance_id']]
                runtime.docker('create', '--name', state['gateway'], *labels, '--network', state['network'],
                    '--network-alias', 'gateway', *runtime.sandbox_args(), *runtime.mount(root / 'usage/raw', '/records'),
                    '--entrypoint', 'python3', self.plan['images']['gateway'], '-c', gateway, run_id, b['run_instance_id'])
                runtime.docker('start', state['gateway'])
                if (self.campaign.root / '_control/operator-stop.json').exists():
                    raise ValueError('Parent supervision stopped before worker creation')
                config = {'enabled_providers': [], 'autoupdate': False, 'share': 'disabled',
                          'plugin': [], 'mcp': {}, 'lsp': False}
                util.write_new_json(root / 'state/opencode.json', config)
                runtime.docker('create', '--name', state['worker'], *labels, '--network', state['network'],
                    *runtime.sandbox_args(), *runtime.mount(root / 'inputs', '/input', True),
                    *runtime.mount(root / 'workspace', '/workspace'), *runtime.mount(root / 'state', '/state'),
                    '-e', 'OPENCODE_CONFIG=/state/opencode.json', self.plan['images']['worker'],
                    'opencode', 'serve', '--hostname', '127.0.0.1', '--port', '4096')
                runtime.docker('start', state['worker'])
                state['worker_started_at'] = run.now(); util.write_json_atomic(root / 'runtime.json', state)
                deadline = time.monotonic() + 40
                while True:
                    try:
                        _ok(_http(state['worker'], 4096, 'GET', '/session')); break
                    except (RuntimeError, ValueError):
                        if time.monotonic() >= deadline: raise
                        time.sleep(.5)
                version = runtime.docker('exec', state['worker'], 'opencode', '--version').stdout.strip()
                if version != self.plan['opencode_version']: raise ValueError('Actual OpenCode version mismatch')
                session['created'] = _ok(_http(state['worker'], 4096, 'POST', '/session', {'title': 'nonmodel acceptance'}))
                sid = session['created']['id']
                session['read'] = _ok(_http(state['worker'], 4096, 'GET', '/session/' + sid))
                if (self.campaign.root / '_control/operator-stop.json').exists():
                    raise ValueError('Parent supervision stopped before artifact subprocess')
                # Separate real process writes deterministic, saved-input-derived artifact.
                script = """import hashlib,json,pathlib,sys,time
p=pathlib.Path('/workspace'); src=pathlib.Path('/input/source-bytes.json').read_bytes()
value={'source_inventory_sha256':hashlib.sha256(src).hexdigest(),'source_file_count':len(json.loads(src)),
       'backend':'dummy-artifact','model_calls':0,'run_instance_id':sys.argv[1]}
(p/'partial.json').write_text(json.dumps(value,sort_keys=True))
deadline=time.monotonic()+45
while not (p/'release.flag').exists():
 if time.monotonic()>deadline: raise SystemExit(3)
 time.sleep(.05)
(p/'artifact.json').write_text(json.dumps(value,sort_keys=True))
"""
                child_log = (root / 'evidence/artifact-process.log').open('xb')
                child = subprocess.Popen(['docker', 'exec', state['worker'], 'python3', '-c', script,
                    b['run_instance_id']],
                    env=safe_environment(), stdin=subprocess.DEVNULL, stdout=child_log, stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                deadline = time.monotonic() + 10
                while not (root / 'workspace/partial.json').exists():
                    if child.poll() is not None or time.monotonic() > deadline: raise ValueError('Partial artifact not observed')
                    time.sleep(.05)
                # The child stays alive until an independent actual active sample.
                deadline = time.monotonic() + 30
                while True:
                    if child.poll() is not None: raise ValueError('Artifact subprocess exited before active sample')
                    try:
                        active = validate_active_sample(self.monitor.snapshot(), b); break
                    except (ValueError, RuntimeError, KeyError, OSError):
                        if time.monotonic() > deadline: raise
                        time.sleep(.1)
                util.write_new_json(root / 'evidence/active-resource-sample.json', active)
                if b['mode'] == 'middle_stop':
                    if child.poll() is not None or (root / 'workspace/artifact.json').exists():
                        raise ValueError('Middle stop was no longer unfinished')
                    util.write_new_json(root / 'stop-request.json', {**b, 'reason': 'finite acceptance middle stop'})
                else:
                    (root / 'workspace/release.flag').write_bytes(b'normal completion authorized')
                    if child.wait(timeout=15) != 0: raise ValueError('Artifact process failed')
                    (root / 'workspace/release.flag').unlink()
                verify_run(root, b)
                session['abort'] = _ok(_http(state['worker'], 4096, 'POST', '/session/' + sid + '/abort', {}))
                session['messages'] = _ok(_http(state['worker'], 4096, 'GET', '/session/' + sid + '/message'))
                session['status'] = _ok(_http(state['worker'], 4096, 'GET', '/session/status'))
                validate_session(session)
                util.write_new_json(root / 'evidence/sdk-session.json', session)
                foreign = _http(state['gateway'], 8080, 'POST', '/control/stop-admission',
                    {'run_id': run_id, 'session_id': uuid.uuid4().hex})
                if foreign['status'] != 403: raise ValueError('Foreign session control not rejected')
                fence = runtime.fence_owned(root); validate_fence(fence, b)
                rejected = _http(state['gateway'], 8080, 'POST', '/v1/chat/completions',
                    {'model': 'nonmodel', 'stream': True, 'messages': []})
                if rejected['status'] != 403: raise ValueError('Closed admission not rejected')
                util.write_new_json(root / 'evidence/boundaries.json', {'foreign_session_rejected': True,
                    'closed_admission_rejected': True, 'fence': fence, 'actual_opencode_version': version})
                if b['mode'] == 'middle_stop':
                    live_middle_stop = child.poll() is None and not (root / 'workspace/artifact.json').exists()
                    if not live_middle_stop: raise ValueError('Child no longer unfinished at actual stop boundary')
            finally:
                stopped = runtime.stop_owned(root)
                state['stop_confirmed'] = stopped; util.write_json_atomic(root / 'runtime.json', state)
                manifest.update(stop_confirmed=stopped, ended_at=run.now(),
                    end_reason='operator_stop' if b['mode'] == 'middle_stop' else 'completed')
                util.write_json_atomic(root / 'manifest.json', manifest)
                if child is not None:
                    child.wait(timeout=15)
                if child_log is not None: child_log.close()
            if not stopped: raise ValueError('Owned stop unconfirmed')
            if b['mode'] == 'middle_stop' and not live_middle_stop:
                raise ValueError('Actual middle stop did not observe a live unfinished child')
            validate_artifact_shape(root / 'workspace', partial=b['mode'] == 'middle_stop', child_exit=child.returncode)
            gateway_count(root / 'usage/raw')
            frozen = root / 'frozen'; shutil.copytree(root / 'workspace', frozen)
            before = inventory(root / 'workspace'); time.sleep(.2)
            verify_unchanged(root / 'workspace', before)
            cleanup = runtime.cleanup_network(root)
            if not cleanup['confirmed']: raise ValueError('Network cleanup unconfirmed')
            manifest['network_cleanup'] = cleanup; util.write_json_atomic(root / 'manifest.json', manifest)
            receipt = {**b, 'stop_confirmed': True, 'model_calls': 0,
                'backend': 'dummy-artifact-with-real-providerless-sdk-session',
                'artifact_process_pid': child.pid, 'artifact_process_exit_code': child.returncode,
                'session_id': validate_session(session),
                'artifact_sha256': util.sha256_file(frozen / 'partial.json'),
                'frozen_artifact_sha256': util.artifact_hash(frozen), 'gateway_request_count': 0,
                'local_negative_http_requests': 2, 'live_middle_stop': live_middle_stop,
                'session_evidence_sha256': util.sha256_file(root / 'evidence/sdk-session.json'),
                'boundary_evidence_sha256': util.sha256_file(root / 'evidence/boundaries.json'),
                'active_evidence_sha256': util.sha256_file(root / 'evidence/active-resource-sample.json'),
                'partial': b['mode'] == 'middle_stop', 'late_writer_absent': True,
                'collection_status': 'collected', 'submission_fixed': True}
            util.write_new_json(root / 'implementation-receipt.json', receipt)
            return receipt

    def postprocess(self, repo, batch, run_id, archive):
        root = Path(batch) / run_id
        receipt = util.read_json(root / 'implementation-receipt.json')
        if not receipt['stop_confirmed'] or gateway_count(root / 'usage/raw') != 0:
            raise ValueError('Nonmodel collection barrier failed')
        data = json.loads((root / 'frozen/partial.json').read_text(encoding='utf8'))
        row = {'run_id': run_id, 'run_instance_id': receipt['run_instance_id'],
            'operation_status': 'complete', 'scoring': {'state': 'nonmodel_not_quality_scored'},
            'quality': None, 'model_calls': 0, 'source_file_count': data['source_file_count'],
            'partial': receipt['partial']}
        util.write_new_json(root / 'output/result.json', row)
        return row


def _remove_owned(root):
    state = util.read_json(root / 'runtime.json')
    records = []
    for role in ('worker', 'gateway'):
        item = runtime._owned_container(state, role)
        if item is None:
            listed = runtime.docker('ps', '-a', '--filter', 'name=^/' + state[role] + '$', '--format', '{{.ID}}', timeout=20)
            if listed.stdout.strip(): raise ValueError('Container absence not confirmed')
            records.append({'role': role, 'absent': True, 'removed': False})
            continue
        if item['State']['Running']: raise ValueError('Owned container still running')
        runtime.docker('rm', item['Id'], timeout=20)
        if runtime.inspect_container(state[role]) is not None: raise ValueError('Removal unconfirmed')
        records.append({'role': role, 'id': item['Id'], 'removed': True})
    util.write_new_json(root / 'evidence/container-cleanup.json', {'run_instance_id': state['run_instance_id'],
        'resources': records, 'confirmed': True})


def _cleanup_backend(root, binding):
    """Bounded recovery only for this new adapter's exact owned runtime."""
    root = Path(root)
    manifest = verify_run(root, binding)
    state = util.read_json(root / 'runtime.json')
    if any(state.get(k) != binding[k] for k in ('run_id', 'run_instance_id')):
        raise ValueError('Cleanup runtime scope mismatch')
    if state.get('stop_confirmed') is not True or manifest.get('stop_confirmed') is not True:
        stopped = runtime.stop_owned(root)
        state['stop_confirmed'] = stopped; util.write_json_atomic(root / 'runtime.json', state)
        manifest.update(stop_confirmed=stopped, ended_at=run.now(), end_reason='operator_stop')
        util.write_json_atomic(root / 'manifest.json', manifest)
    if state.get('stop_confirmed') is not True or manifest.get('stop_confirmed') is not True:
        raise ValueError('Unknown stop cannot authorize cleanup')
    if not (manifest.get('network_cleanup') or {}).get('confirmed'):
        cleanup = runtime.cleanup_network(root)
        manifest['network_cleanup'] = cleanup; util.write_json_atomic(root / 'manifest.json', manifest)
        if cleanup.get('confirmed') is not True: raise ValueError('Owned network cleanup not confirmed')
    receipt = root / 'evidence/container-cleanup.json'
    if receipt.exists():
        value = util.read_json(receipt)
        if value.get('run_instance_id') != binding['run_instance_id'] or value.get('confirmed') is not True:
            raise ValueError('Existing cleanup evidence not bound')
        for role in ('worker', 'gateway'):
            if runtime._owned_container(state, role) is not None: raise ValueError('Late resource after cleanup')
    else:
        _remove_owned(root)


def emergency_stop(base, *, repo, expected_plan_sha256):
    """Parent's finite external-deadline recovery; no dispatcher/model/replay."""
    base, repo = Path(base).resolve(), Path(repo).resolve()
    if util.sha256_file(base / 'plan.json') != expected_plan_sha256:
        raise ValueError('Emergency stop plan changed')
    plan = util.read_json(base / 'plan.json'); verify_pins(repo, plan['source_pins'])
    results = []
    for assignment in plan['assignments']:
        campaign_root = base / 'campaigns' / assignment['campaign_id']
        if (campaign_root / 'campaign.json').exists():
            meta = util.read_json(campaign_root / 'campaign.json')
            if meta['plan_sha256'] != expected_plan_sha256: raise ValueError('Emergency campaign plan mismatch')
            marker = campaign_root / '_control/operator-stop.json'
            if not marker.exists(): util.write_new_json(marker, {'plan_sha256': expected_plan_sha256,
                'campaign_uuid': meta['campaign_uuid'], 'reason': 'parent finite deadline'})
            phase = util.read_json(campaign_root / 'phase.json')
            marker = campaign_root / 'runs/_control' / phase['phase_id'] / 'dispatch-stop.json'
            if not marker.exists(): util.write_new_json(marker, {'plan_sha256': expected_plan_sha256,
                'campaign_uuid': meta['campaign_uuid'], 'reason': 'parent finite deadline'})
        for binding in assignment['cases']:
            root = base / 'campaigns' / assignment['campaign_id'] / 'runs' / binding['run_id']
            if not (root / 'runtime.json').exists(): continue
            try:
                _cleanup_backend(root, binding)
                results.append({'run_id': binding['run_id'], 'run_instance_id': binding['run_instance_id'],
                                'stop_confirmed': True, 'cleanup_confirmed': True})
            except Exception as exc:
                results.append({'run_id': binding['run_id'], 'run_instance_id': binding['run_instance_id'],
                                'cleanup_confirmed': False, 'error_type': type(exc).__name__})
    path = base / ('emergency-stop-' + uuid.uuid4().hex + '.json')
    util.write_new_json(path, {'kind': 'owned_nonmodel_emergency_stop', 'results': results})
    return str(path)


def execute(plan_path, *, repo):
    plan_path, repo = Path(plan_path).resolve(), Path(repo).resolve()
    base, plan = plan_path.parent, util.read_json(plan_path)
    if plan.get('kind') != KIND or plan.get('max_runs') != 4 or plan.get('max_model_calls') != 0:
        raise ValueError('Explicit fixed nonmodel plan required')
    cases = [c for a in plan['assignments'] for c in a['cases']]
    if (len(plan['assignments']) != 2 or len(cases) != 4
            or len({a['campaign_id'] for a in plan['assignments']}) != 2
            or len({c['run_id'] for c in cases}) != 4 or len({c['run_instance_id'] for c in cases}) != 4
            or plan.get('max_sessions') != 4 or plan.get('pair_concurrency') != 1):
        raise ValueError('Fixed four distinct nonmodel Run/session identities required')
    verify_pins(repo, plan['source_pins'])
    if inventory(base / 'saved-input') != plan['input_inventory']: raise ValueError('Saved inputs changed')
    before = util.read_json(base / 'original-before.json')
    for root, hashes in before.items(): verify_unchanged(root, hashes)
    digest = util.sha256_file(plan_path)
    campaigns = []
    for assignment in plan['assignments']:
        campaign = identity.create_campaign(base, assignment['campaign_id'], plan_sha256=digest,
            evaluation_version='operational-dummy-1', evaluator_sha256=plan['source_pins']['research/campaign_operational.py'])
        phase = {'kind': FIXTURE_KIND, 'phase_id': 'providerless-acceptance',
            'cohort': campaign.campaign_uuid, 'runtime': 'providerless-opencode-session',
            'batch': str(campaign.root / 'runs'), 'assignments': [{'pair': 1, 'cases': assignment['cases']}],
            'two_pair_blocks': [[1]], 'original_bundle': {'path': str(plan_path), 'sha256': digest},
            'resource_monitor': plan['resource_monitor'], 'resource_probe': plan['resource_probe'],
            'source_pins': plan['source_pins']}
        phase_path = campaign.root / 'phase.json'; util.write_new_json(phase_path, phase)
        backend = Backend(repo, base, plan, campaign, phase_path)
        lease = campaign.acquire_lease()
        with ownership.lease(campaign.root / '_control'):
            collision = _lease_collision(campaign.root / '_control')
            util.write_new_json(campaign.root / '_control/lease-collision.json', collision)
            backend.monitor.start()
            try:
                result = pairs.execute_pair({'plan_sha256': digest, 'cohort': campaign.campaign_uuid,
                    'runtime': 'providerless-opencode-session', 'pair_concurrency': 1, 'require_fixed_instances': True},
                    assignment['cases'], campaign.root / 'runs', repo=repo, concurrency=1,
                    prepare=backend.prepare, implement=backend.implement, postprocess=backend.postprocess,
                    admit=backend.admit)
                if result.get('reason') != 'pair_publication_restore_cleanup_required':
                    raise ValueError('Actual pair did not reach terminal publication barrier')
                # Same production dispatcher must refuse a second send.
                replay = pairs.execute_pair({'plan_sha256': digest, 'cohort': campaign.campaign_uuid,
                    'runtime': 'providerless-opencode-session', 'pair_concurrency': 1, 'require_fixed_instances': True},
                    assignment['cases'], campaign.root / 'runs', repo=repo, prepare=backend.prepare,
                    implement=backend.implement, postprocess=backend.postprocess, admit=backend.admit)
                if replay.get('reason') != 'dispatched_identity_never_replayed': raise ValueError('Replay not rejected')
                try:
                    backend.monitor.admit({**backend.bindings[0], 'run_instance_id': uuid.uuid4().hex})
                except ValueError: foreign_rejected = True
                else: raise ValueError('Foreign observer identity admitted')
                util.write_new_json(campaign.root / '_control/dispatch-result.json',
                    {'result': result, 'replay': replay, 'foreign_observer_rejected': foreign_rejected})
            finally:
                try: observer_stopped = backend.monitor.stop()
                except Exception: observer_stopped = False
                cleanup_errors = []
                for case in assignment['cases']:
                    root = campaign.root / 'runs' / case['run_id']
                    if not (root / 'runtime.json').exists(): continue
                    try: _cleanup_backend(root, case)
                    except Exception as exc:
                        cleanup_errors.append({'run_id': case['run_id'], 'error_type': type(exc).__name__})
                if not observer_stopped:
                    if backend.monitor.process and backend.monitor.process.poll() is None:
                        backend.monitor.process.terminate(); backend.monitor.process.wait(timeout=10)
                if cleanup_errors:
                    util.write_new_json(campaign.root / '_control/owned-cleanup-failure.json', {'errors': cleanup_errors})
                    raise ValueError('Owned cleanup incomplete; foreign/unknown resources preserved')
                if not observer_stopped:
                    raise ValueError('Independent observer shutdown ACK missing')
        campaign.release_lease(lease)
        campaigns.append(campaign)
    source_campaign = campaigns[0]
    source_root = source_campaign.root / 'runs' / plan['assignments'][0]['cases'][0]['run_id']
    original_campaign_before = inventory(source_campaign.root)
    source_run = util.read_json(source_root / 'run.json')
    assessment = identity.create_reassessment(base, 'operational-reassessment', source=source_campaign,
        source_run=source_run, artifact=source_root / 'frozen/partial.json',
        artifact_sha256=util.sha256_file(source_root / 'frozen/partial.json'),
        evaluation_version='operational-dummy-2', evaluator_sha256=plan['source_pins']['research/campaign_operational.py'])
    data = util.read_json(source_root / 'frozen/partial.json')
    util.write_new_json(base / 'assessments/operational-reassessment/result.json',
        {'assessment_id': assessment['assessment_id'], 'source_run_instance_id': assessment['source_run_instance_id'],
         'source_artifact_sha256': assessment['source_artifact_sha256'], 'evaluation_version': 'operational-dummy-2',
         'source_file_count': data['source_file_count'], 'quality': None, 'model_calls': 0,
         'acquisition_count_increment': 0, 'kind': 'nonmodel_saved_artifact_reassessment'})
    verify_unchanged(source_campaign.root, original_campaign_before)
    after = {str(p): inventory(p) for p in before}
    if after != before: raise ValueError('Original or saved assessments changed')
    util.write_new_json(base / 'original-after.json', after)
    return normalize(base)


def normalize(base, *, phase_a_proof=None, phase_a_package=None):
    base = Path(base).resolve(); plan = util.read_json(base / 'plan.json')
    final = phase_a_proof is not None
    campaigns = []
    for assignment in plan['assignments']:
        root = base / 'campaigns' / assignment['campaign_id']
        meta = util.read_json(root / 'campaign.json')
        journal = pairs.state(root / 'runs/_control/pair-journal.jsonl')
        gate = 1 in journal['gates']
        if final != gate: raise ValueError('Publication phase and actual journal gate differ')
        observer_ack = list((root / '_control/observer').glob('*/shutdown-ack.json'))
        if len(observer_ack) != 1: raise ValueError('Exact observer shutdown evidence required')
        ack = util.read_json(observer_ack[0])
        if ack.get('owned_resources_resolved') is not True or ack.get('monitor_stop_confirmed') is not True:
            raise ValueError('Observer not independently stopped')
        runs = []
        for case in assignment['cases']:
            r = root / 'runs' / case['run_id']
            receipt = util.read_json(r / 'implementation-receipt.json')
            if receipt != journal['implementations'][case['run_id']]['receipt']:
                raise ValueError('Saved implementation differs from immutable dispatcher receipt')
            for field, name in (('session_evidence_sha256', 'sdk-session.json'),
                                ('boundary_evidence_sha256', 'boundaries.json'),
                                ('active_evidence_sha256', 'active-resource-sample.json')):
                if util.sha256_file(r / 'evidence' / name) != receipt[field]:
                    raise ValueError('Implementation observation evidence changed')
            validate_artifact_shape(r / 'frozen', partial=receipt['partial'], child_exit=receipt['artifact_process_exit_code'])
            if (util.artifact_hash(r / 'frozen') != receipt['frozen_artifact_sha256']
                    or util.sha256_file(r / 'frozen/partial.json') != receipt['artifact_sha256']):
                raise ValueError('Frozen artifact changed since stop/collection')
            active = util.read_json(r / 'evidence/active-resource-sample.json')
            if (active.get('run_id') != case['run_id'] or active.get('run_instance_id') != case['run_instance_id']
                    or util.sha256_file(active['path']) != active['sha256']):
                raise ValueError('Actual active sample evidence changed')
            sid = validate_session(util.read_json(r / 'evidence/sdk-session.json'))
            boundary = util.read_json(r / 'evidence/boundaries.json'); validate_fence(boundary['fence'], case)
            cleanup = util.read_json(r / 'evidence/container-cleanup.json')
            if cleanup.get('confirmed') is not True or gateway_count(r / 'usage/raw') != 0:
                raise ValueError('Actual cleanup or zero request evidence missing')
            runs.append({'run_id': case['run_id'], 'run_instance_id': case['run_instance_id'], 'session_id': sid,
                'session_create_verified': True, 'session_read_verified': True, 'session_abort_verified': True,
                'admission_ack_verified': True, 'observer_ack_verified': True,
                'stop_confirmed': receipt['stop_confirmed'], 'cleanup_confirmed': True,
                'artifact_sha256': receipt['artifact_sha256'], 'source_snapshot_sha256': plan['source']['snapshot_sha256'],
                'state': 'partial' if receipt['partial'] else 'complete', 'publication_gate_complete': gate})
        campaigns.append({'campaign_id': meta['campaign_id'], 'campaign_uuid': meta['campaign_uuid'],
            'plan_sha256': meta['plan_sha256'], 'plan_commit_declared': plan['source_commit'],
            'backend': 'providerless-opencode-session',
            'model_calls': 0, 'pairs': 1, 'runs': runs})
    a = util.read_json(base / 'assessments/operational-reassessment/assessment.json')
    value = {'schema_version': 1, 'kind': 'nonmodel_operational_acceptance', 'campaigns': campaigns,
        'reassessment': {'assessment_id': a['assessment_id'], 'source_run_instance_id': uuid.UUID(a['source_run_instance_id']).hex,
            'source_artifact_sha256': a['source_artifact_sha256'], 'evaluation_version': a['evaluation_version'],
            'acquisition_count_increment': 0, 'model_calls': 0},
        'provenance': {'plan.json': util.sha256_file(base / 'plan.json'),
            'original-before.json': util.sha256_file(base / 'original-before.json'),
            'original-after.json': util.sha256_file(base / 'original-after.json')},
        'limits': plan['limits'], 'publication_phase': 'final' if final else 'prepublication',
        'publication_gate_complete': final,
        'phase_a_verification_sha256': phase_a_proof, 'phase_a_package_sha256': phase_a_package}
    util.write_new_json(base / ('operational-final.json' if final else 'operational-prepublication.json'), value)
    return value


def finish_publication(base, receipt, *, expected_receipt_sha256, expected_package_sha256):
    """Consume real external proof, close existing gates, never dispatch/re-score."""
    base, receipt = Path(base).resolve(), Path(receipt).resolve()
    identity._sha(expected_package_sha256); identity._sha(expected_receipt_sha256)
    if util.sha256_file(receipt) != expected_receipt_sha256: raise ValueError('External publication proof changed')
    proof = util.read_json(receipt); plan = util.read_json(base / 'plan.json')
    if proof.get('package_sha256') != expected_package_sha256: raise ValueError('External package hash mismatch')
    expected = {c['run_id']: c['run_instance_id'] for a in plan['assignments'] for c in a['cases']}
    assessment = util.read_json(base / 'assessments/operational-reassessment/assessment.json')
    wanted_campaigns = [util.read_json(base / 'campaigns' / a['campaign_id'] / 'campaign.json')['campaign_uuid']
                        for a in plan['assignments']]
    if (proof.get('run_instances') != expected or proof.get('campaign_uuids') != wanted_campaigns
            or proof.get('assessment_id') != assessment['assessment_id']):
        raise ValueError('External proof campaign/Run/assessment mismatch')
    for a in plan['assignments']:
        root = base / 'campaigns' / a['campaign_id']; batch = root / 'runs'
        state = pairs.state(batch / '_control/pair-journal.jsonl')
        if state['gates']: raise ValueError('Publication already finished; never overwrite/repeat gate')
        refs = {str(receipt): expected_receipt_sha256}
        for name in ('publication_receipt', 'roundtrip_receipt', 'cleanup_receipt'):
            path = Path(proof[name]).resolve()
            if proof['evidence_files'].get(str(path)) != util.sha256_file(path):
                raise ValueError('External gate evidence changed')
            if util.read_json(path).get('package_sha256') != expected_package_sha256:
                raise ValueError('External gate receipt package mismatch')
            refs[str(path)] = util.sha256_file(path)
        gate = {'pair': 1, 'plan_sha256': util.sha256_file(base / 'plan.json'),
            'cohort': util.read_json(root / 'campaign.json')['campaign_uuid'],
            'run_instances': {c['run_id']: c['run_instance_id'] for c in a['cases']},
            'evidence_files': refs, **{name: str(Path(proof[name]).resolve())
                for name in ('publication_receipt', 'roundtrip_receipt', 'cleanup_receipt')}}
        # Validate all before adding any immutable receipt/journal entry.
        pairs._validate_gate(gate, state, 1)
    for a in plan['assignments']:
        root = base / 'campaigns' / a['campaign_id']; batch = root / 'runs'
        gate = {'pair': 1, 'plan_sha256': util.sha256_file(base / 'plan.json'),
            'cohort': util.read_json(root / 'campaign.json')['campaign_uuid'],
            'run_instances': {c['run_id']: c['run_instance_id'] for c in a['cases']},
            'evidence_files': refs, **{name: str(Path(proof[name]).resolve())
                for name in ('publication_receipt', 'roundtrip_receipt', 'cleanup_receipt')}}
        path = root / '_control/publication-gate.json'; util.write_new_json(path, gate)
        pairs.record_pair_gate(batch, 1, path)
    return normalize(base, phase_a_proof=expected_receipt_sha256, phase_a_package=expected_package_sha256)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare'); p.add_argument('destination', type=Path)
    p.add_argument('--repo', type=Path, required=True); p.add_argument('--original', type=Path, required=True)
    p.add_argument('--protect', type=Path, action='append', default=[])
    p = sub.add_parser('execute'); p.add_argument('plan', type=Path); p.add_argument('--repo', type=Path, required=True)
    p = sub.add_parser('finish-publication'); p.add_argument('base', type=Path); p.add_argument('receipt', type=Path)
    p.add_argument('--receipt-sha256', required=True); p.add_argument('--package-sha256', required=True)
    p = sub.add_parser('emergency-stop'); p.add_argument('base', type=Path)
    p.add_argument('--repo', type=Path, required=True); p.add_argument('--plan-sha256', required=True)
    args = parser.parse_args()
    if args.command == 'prepare':
        result = str(prepare_plan(args.repo, args.destination, original=args.original, protected=args.protect))
    elif args.command == 'execute': result = execute(args.plan, repo=args.repo)
    elif args.command == 'emergency-stop': result = emergency_stop(args.base, repo=args.repo, expected_plan_sha256=args.plan_sha256)
    else: result = finish_publication(args.base, args.receipt,
        expected_receipt_sha256=args.receipt_sha256, expected_package_sha256=args.package_sha256)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__': main()
