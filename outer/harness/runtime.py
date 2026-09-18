"""Docker preparation and Run ownership. No host agent or host submission execution."""
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time
import uuid

from . import profiles, run, util, ownership
from .security import child_environment


def command(args, *, cwd=None, timeout=120, check=True):
    result = subprocess.run(args, cwd=cwd, env=child_environment(), capture_output=True,
                            text=True, encoding='utf-8', errors='replace', timeout=timeout)
    if check and result.returncode:
        raise RuntimeError('Command failed: ' + ' '.join(args[:3]) + '\n' + result.stderr[-3000:])
    return result


def docker(*args, **kwargs):
    return command(['docker', *map(str, args)], **kwargs)


def image_id(name):
    return docker('image', 'inspect', name, '--format', '{{.Id}}', timeout=30).stdout.strip()


def controller_files(repo):
    return {p.name:util.sha256_file(p) for p in sorted((Path(repo)/'outer/harness').glob('*.py'))}


def source(repo, task):
    start = task['start_state']
    revision = start['source_commit']
    root = Path(repo) / 'artifacts' / 'sources'
    dest = root / revision
    if dest.exists():
        saved = util.read_json(root / (revision + '.json'))
        if util.tree_hashes(dest) != saved['files']:
            raise ValueError('Prepared source changed')
        return dest
    cache = root / ('git-' + uuid.uuid4().hex)
    cache.mkdir(parents=True)
    command(['git', 'init', '-q', str(cache)])
    url = 'https://github.com/' + start['source_repository'] + '.git'
    command(['git', '-C', str(cache), 'fetch', '-q', '--depth=1', url, revision], timeout=300)
    actual = command(['git', '-C', str(cache), 'rev-parse', 'FETCH_HEAD']).stdout.strip()
    if actual != revision:
        raise ValueError('Source commit mismatch')
    data = subprocess.run(['git', '-C', str(cache), 'archive', '--format=tar', actual],
                          env=child_environment(), capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        if any(m.issym() or m.islnk() or m.isdev() for m in archive.getmembers()):
            raise ValueError('Source contains links or special files')
        dest.mkdir()
        archive.extractall(dest, filter='data')
    util.write_new_json(root / (revision + '.json'), {'source': url, 'commit': actual,
                                                    'files': util.tree_hashes(dest)})
    return dest


def prepare(repo, *, task_id='MS1-001', rebuild=False):
    repo = Path(repo).resolve()
    profiles.identifier(task_id)
    attempt = repo / 'artifacts/runtime' / task_id / 'preparation' / uuid.uuid4().hex
    attempt.mkdir(parents=True)
    util.write_new_json(attempt / 'request.json', {'task':task_id, 'rebuild':rebuild, 'started_at':run.now()})
    try:
        result = _prepare(repo, task_id=task_id, rebuild=rebuild)
        util.write_new_json(attempt / 'result.json', result)
        return result
    except Exception as exc:
        util.write_new_json(attempt / 'failure.json', {'ended_at':run.now(), 'type':type(exc).__name__,
                                                     'message':str(exc)})
        raise RuntimeError('Preparation failed; retained record: ' + str(attempt / 'failure.json')) from exc


def _prepare(repo, *, task_id='MS1-001', rebuild=False):
    repo = Path(repo).resolve()
    docker('info', '--format', '{{.OSType}}', timeout=30)
    task = profiles.read(repo, 'tasks', task_id)
    source(repo, task)
    root = repo / 'artifacts' / 'runtime' / task_id
    root.mkdir(parents=True, exist_ok=True)
    if (root / 'lock.json').exists() and not rebuild:
        lock = util.read_json(root / 'lock.json')
        for digest in lock['images'].values():
            image_id(digest)
        return lock
    profile = profiles.read(repo, 'runtimes', 'deepseek')
    build_id = uuid.uuid4().hex
    build_root = root / 'builds' / build_id
    build_root.mkdir(parents=True)
    images = {}
    for target in ('worker', 'evaluator', 'gateway'):
        tag = 'sample2-' + target + ':' + build_id
        args = ['docker', 'build', '--progress=plain', '-f', 'outer/runtime/Dockerfile',
                '--target', target, '--build-arg', 'OPENCODE_VERSION=' + profile['opencode_version'],
                '--build-arg', 'EVALUATOR_PROJECT=' + task['evaluation']['project'],
                '-t', tag, '.']
        print('Preparing ' + target, flush=True)
        with (build_root / (target + '.log')).open('xb') as log:
            result = subprocess.run(args, cwd=repo, env=child_environment(),
                                    stdout=log, stderr=subprocess.STDOUT, timeout=1800)
        if result.returncode:
            raise RuntimeError('Image build failed; inspect ' + str(build_root / (target + '.log')))
        images[target] = image_id(tag)
    container = 's2-extract-' + build_id
    docker('create', '--name', container, images['evaluator'])
    bundle = build_root / 'evaluator'
    try:
        docker('cp', container + ':/evaluator', str(bundle))
    finally:
        docker('rm', '-f', container, check=False)
    if (root / 'evaluator').exists():
        (root / 'evaluator').rename(root / ('evaluator-retained-' + uuid.uuid4().hex))
    shutil.copytree(bundle, root / 'evaluator')
    sdk = docker('run', '--rm', '--network', 'none', images['evaluator'], 'dotnet', '--version').stdout.strip()
    if sdk != task['environment']['sdk']:
        raise ValueError('Prepared .NET SDK version mismatch')
    opencode = docker('run', '--rm', '--network', 'none', images['worker'], 'opencode', '--version').stdout.strip()
    if opencode != profile['opencode_version']:
        raise ValueError('Prepared OpenCode version mismatch')
    lock = {'schema_version': 1, 'build_id': build_id, 'images': images,
            'controller_files': controller_files(repo),
            'opencode_version': opencode, 'versions': {'dotnet': sdk, 'opencode': opencode},
            'evaluator_files': util.tree_hashes(bundle),
            'evaluator_sha256': util.sha256_file(bundle / task['evaluation']['assembly']),
            'evaluator_build': {'source_path': 'inner/evaluator/' + task['evaluation']['project'],
                                'command': 'docker build --target evaluator', 'sdk_version': sdk,
                                'sha256_origin': 'artifacts/runtime/' + task_id + '/builds/' + build_id,
                                'clean_worktree': not bool(command(['git', 'status', '--porcelain'], cwd=repo).stdout),
                                'source_commit': command(['git', 'rev-parse', 'HEAD'], cwd=repo).stdout.strip()},
            'created_at': run.now()}
    util.write_new_json(build_root / 'lock.json', lock)
    util.write_json_atomic(root / 'lock.json', lock)
    return lock


def sandbox_args():
    return ['--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges',
            '--pids-limit=512', '--memory=6g', '--cpus=4', '--tmpfs', '/tmp:rw,exec,size=2g']


def mount(path, dest, readonly=False):
    return ['--mount', 'type=bind,source=' + str(Path(path).resolve()) + ',target=' + dest + (',readonly' if readonly else '')]


def opencode_config(condition):
    model = condition['runtime']['model_id']
    selected = 'sample2/' + model
    return {'$schema': 'https://opencode.ai/config.json', 'model': selected, 'small_model': selected,
            'enabled_providers': ['sample2'], 'autoupdate': False, 'share': 'disabled',
            'plugin': [], 'mcp': {}, 'lsp': False, 'compaction': condition['runtime']['compaction'],
            'permission': {'*': 'allow', 'task': 'deny', 'question': 'deny',
                           'webfetch': 'deny', 'websearch': 'deny'},
            'provider': {'sample2': {'npm': '@ai-sdk/openai-compatible', 'name': 'Sample2 gateway',
                'options': {'baseURL': 'http://gateway:8080/v1', 'apiKey': 'local-no-credential',
                            'timeout': 120000},
                'models': {model: {'name': 'DeepSeek V4.1 Flash',
                    'limit': {'context': condition['runtime']['model_context_tokens'],
                              'output': condition['runtime']['model_output_tokens']}}}}}}


def isolation_probe(root, state, condition):
    """Exercise the same network/mount/user boundaries before any model call."""
    code = """import json, os, socket, urllib.request
from pathlib import Path
def reachable(host, port):
    try:
        with socket.create_connection((host, port), timeout=2): return True
    except OSError: return False
result = {
 'gateway_reachable': urllib.request.urlopen('http://gateway:8080/health', timeout=5).status == 200,
 'internet_blocked': not reachable('1.1.1.1',443),
 'provider_blocked': not reachable('opencode.ai',443),
 'credential_absent': 'OPENCODE_GO_API_KEY' not in os.environ,
 'research_absent': not any(Path(p).exists() for p in ['/assets','/evaluator','/records','/var/run/docker.sock']),
 'source_present': Path('/input/legacy-source').is_dir(),
 'non_root': os.getuid() != 0}
try:
 Path('/input/probe-write').write_text('probe')
 result['input_readonly'] = False
except OSError: result['input_readonly'] = True
print(json.dumps(result))
"""
    output = docker('run', '--rm', '--network', state['network'], *sandbox_args(),
                    *mount(root / 'inputs', '/input', True),
                    condition['runtime_lock']['images']['worker'], 'python3', '-c', code, timeout=45)
    evidence = json.loads(output.stdout)
    evidence['verified'] = all(evidence.values())
    util.write_new_json(root / 'evidence/isolation.json', evidence)
    if not evidence['verified']:
        raise RuntimeError('Worker isolation probe failed')
    return evidence


def _gateway_credential():
    # This bootstrap never places the value in environment/arguments/files.
    if os.name != 'nt':
        raise RuntimeError('Live gateway bootstrap requires Windows user environment')
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as key:
        value, _ = winreg.QueryValueEx(key, 'OPENCODE_GO_API_KEY')
    if not value or '\n' in value or '\r' in value:
        raise RuntimeError('Gateway credential missing or invalid')
    return value


def inspect_container(name):
    result = docker('inspect', name, timeout=30, check=False)
    if result.returncode:
        return None
    return json.loads(result.stdout)[0]


def stop_owned(root):
    root = Path(root)
    state = util.read_json(root / 'runtime.json')
    confirmations = []
    for role in ('worker', 'gateway'):
        name = state[role]
        item = inspect_container(name)
        if item:
            if (item['Config'].get('Labels') or {}).get('sample2.run') != state['run_id']:
                raise RuntimeError('Container ownership mismatch')
            docker('stop', '--time', '10', name, timeout=40, check=False)
            item = inspect_container(name)
            confirmations.append(bool(item and not item['State']['Running']))
        else:
            # A failed inspect alone cannot distinguish a missing container from
            # an unavailable daemon. Verify absence through a successful listing.
            listed = docker('ps', '-a', '--format', '{{.Names}}', timeout=30, check=False)
            confirmations.append(listed.returncode == 0 and name not in listed.stdout.splitlines())
    return all(confirmations)


def start(repo, runs_dir, run_id):
    root = run.run_dir_for(runs_dir, run_id)
    with ownership.lease(root):
        return _start(repo, runs_dir, run_id)


def _start(repo, runs_dir, run_id):
    root = run.run_dir_for(runs_dir, run_id)
    condition = profiles.validate_run(root)
    if controller_files(repo) != condition['runtime_lock']['controller_files']:
        raise ValueError('Controller code changed since preparation; rebuild and create a new Run')
    manifest = run.load_manifest(runs_dir, run_id)
    if manifest['started_at']:
        raise ValueError('Run already started')
    lock = condition['runtime_lock']
    for digest in lock['images'].values():
        image_id(digest)
    unique = uuid.uuid4().hex[:16]
    private = 's2-net-' + unique
    state = {'run_id': run_id, 'worker': 's2-worker-' + unique,
             'gateway': 's2-gateway-' + unique, 'network': private, 'started_at': run.now()}
    util.write_new_json(root / 'runtime.json', state)
    for name in ('workspace', 'state', 'usage/raw', 'evidence'):
        (root / name).mkdir(parents=True, exist_ok=True)
    config = root / 'state' / 'opencode.json'
    util.write_new_json(config, opencode_config(condition))
    gateway_args = ['create', '-i', '--name', state['gateway'], '--label', 'sample2.run=' + run_id,
                    '--network', private, '--network-alias', 'gateway', *sandbox_args(),
                    *mount(root / 'usage/raw', '/records'), lock['images']['gateway'],
                    '--run-id', run_id, '--model', condition['runtime']['model_id'],
                    '--session-id', manifest.get('run_instance_id', run_id)]
    manifest.update(started_at=run.now(), runner={'id': 'opencode', 'version': lock['opencode_version']},
                    synthetic=False, model_called=False)
    run.save_manifest(runs_dir, run_id, manifest)
    started = time.monotonic()
    reason = 'environment_failure'
    exit_code = None
    gateway_process = None
    worker_process = None
    try:
        docker('network', 'create', '--internal', '--label', 'sample2.run=' + run_id, private)
        docker(*gateway_args)
        # Only gateway has an outbound network; it does not proxy arbitrary URLs.
        docker('network', 'connect', 'bridge', state['gateway'])
        with (root / 'evidence/gateway.log').open('xb') as gateway_log:
            gateway_process = subprocess.Popen(['docker', 'start', '-ai', state['gateway']],
                env=child_environment(), stdin=subprocess.PIPE, stdout=gateway_log, stderr=subprocess.STDOUT)
            gateway_process.stdin.write((_gateway_credential() + '\n').encode())
            gateway_process.stdin.flush()
            gateway_process.stdin.close()
            ready = False
            for _ in range(30):
                if time.monotonic() - started >= min(60, condition['budget']['value']):
                    break
                probe = docker('exec', state['gateway'], 'python3', '-c',
                    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health').read()", check=False, timeout=5)
                if probe.returncode == 0:
                    ready = True
                    break
                time.sleep(1)
            if not ready:
                raise RuntimeError('Gateway failed to start')
            isolation_probe(root, state, condition)
            if (root / 'stop-request.json').exists():
                reason = 'operator_stop'
                raise RuntimeError('Stopped before model dispatch')
            args = ['create', '--name', state['worker'], '--label', 'sample2.run=' + run_id,
                    '--network', private, *sandbox_args(), *mount(root / 'inputs', '/input', True),
                    *mount(root / 'workspace', '/workspace'), *mount(root / 'state', '/state'),
                    '-e', 'OPENCODE_CONFIG=/state/opencode.json', lock['images']['worker'],
                    'opencode', 'run', 'Carry out the attached modernization task.',
                    '--pure', '--format', 'json', '--title', run_id,
                    '--model', 'sample2/' + condition['runtime']['model_id'],
                    '--file', '/input/prompt.txt']
            docker(*args)
            with (root / 'evidence/agent.jsonl').open('xb') as log:
                worker_process = subprocess.Popen(['docker', 'start', '-a', state['worker']],
                    env=child_environment(), stdout=log, stderr=subprocess.STDOUT)
                while worker_process.poll() is None:
                    if (root / 'usage/raw/failure.jsonl').exists():
                        reason = 'provider_failure'
                        break
                    if (root / 'stop-request.json').exists():
                        reason = 'operator_stop'
                        break
                    if time.monotonic() - started >= condition['budget']['value']:
                        reason = 'timeout'
                        break
                    time.sleep(1)
                else:
                    exit_code = worker_process.returncode
                    reason = 'completed' if exit_code == 0 else 'agent_error'
            # Drain already dispatched auxiliary requests before stopping the gateway.
            drain_deadline = min(time.monotonic() + 120, started + condition['budget']['value'])
            from .live_usage import journal
            while reason == 'completed' and time.monotonic() < drain_deadline:
                beginnings, begin_errors = journal(root / 'usage/raw/started.jsonl')
                terminals, end_errors = journal(root / 'usage/raw/events.jsonl')
                if not (begin_errors or end_errors) and len(beginnings) == len(terminals):
                    break
                time.sleep(1)
            if (root / 'usage/raw/failure.jsonl').exists():
                reason = 'provider_failure'
    except Exception as exc:
        util.write_new_json(root / 'evidence/runtime-error.json', {'type': type(exc).__name__, 'message': str(exc)})
    finally:
        try:
            stopped = stop_owned(root)
        except Exception as exc:
            stopped = False
            util.write_new_json(root / 'evidence/stop-error.json', {'type': type(exc).__name__})
        for process in (worker_process, gateway_process):
            if process:
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
        state['stopped_at'] = run.now()
        state['stop_confirmed'] = stopped
        util.write_json_atomic(root / 'runtime.json', state)
        from .live_usage import journal
        endings, _ = journal(root / 'usage/raw/events.jsonl')
        observed_response = any(e.get('status') == 'completed' and not e.get('policy_error') for e in endings)
        manifest.update(ended_at=run.now(), duration_seconds=round(time.monotonic() - started, 3),
                        end_reason=reason if stopped else 'stop_unconfirmed', exit_code=exit_code,
                        stop_confirmed=stopped, stop_method='container_exit', stop_evidence=state,
                        model_called=(True if observed_response else
                                      None if (root / 'usage/raw/started.jsonl').exists() else False))
        run.save_manifest(runs_dir, run_id, manifest)
    from . import live_usage
    live_usage.collect(root)
    return manifest


def request_stop(root):
    root = Path(root)
    manifest = util.read_json(root / 'manifest.json')
    if manifest.get('ended_at') and manifest.get('stop_confirmed'):
        return {'run_id': root.name, 'stop_confirmed': True, 'already_stopped': True}
    if not (root / 'runtime.json').exists():
        raise ValueError('Run has no allocated runtime to stop')
    util.write_json_atomic(root / 'stop-request.json', {'requested_at': run.now()})
    try:
        with ownership.lease(root):
            # No controller is alive. Reclaim only containers bound to this Run.
            stopped = stop_owned(root)
            state = util.read_json(root / 'runtime.json')
            state.update(stopped_at=run.now(), stop_confirmed=stopped, recovered=True)
            util.write_json_atomic(root / 'runtime.json', state)
            manifest = util.read_json(root / 'manifest.json')
            manifest.update(ended_at=run.now(), stop_confirmed=stopped, stop_evidence=state,
                            stop_method='container_exit',
                            end_reason='operator_stop' if stopped else 'stop_unconfirmed')
            run.save_manifest(root.parent, root.name, manifest)
    except BlockingIOError:
        deadline = time.monotonic() + 55
        while time.monotonic() < deadline:
            manifest = util.read_json(root / 'manifest.json')
            if manifest.get('ended_at'):
                break
            time.sleep(1)
        stopped = manifest.get('stop_confirmed', False)
    result = {'run_id': root.name, 'stop_requested': True, 'stop_confirmed': stopped}
    util.write_json_atomic(root / 'stop-result.json', result)
    return result


def scoring_command(condition, frozen, out, work, assets, version, sequence):
    name = 's2-score-' + uuid.uuid4().hex
    cmd = ['docker', 'run', '--name', name, '--network', 'none', *sandbox_args(),
           *mount(frozen, '/artifact', True), *mount(assets, '/assets', True),
           *mount(out, '/result'), *mount(work, '/work'), condition['runtime_lock']['images']['evaluator'],
           'dotnet', '/assets/evaluator/' + condition['evaluation']['assembly'], '--artifact', '/artifact',
           '--out', '/result', '--work', '/work', '--spec', '/assets/requirements.json',
           '--catalog', '/assets/catalog.json', '--evaluation-version', version, '--sequence', str(sequence)]
    return name, cmd
