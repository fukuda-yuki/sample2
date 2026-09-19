"""Exercise the production Docker controller with a container-local mock provider.

No Windows credential is read. The only replacements are credential bootstrap,
gateway upstream and, for stop tests, the worker workload. Every attempt and
injected condition is retained separately from real-model acceptance.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness import live_usage, profiles, run, runtime, util
from harness.security import child_environment

REPO = Path(__file__).resolve().parents[2]
CANARY = 'synthetic-container-credential-canary'
CASES = ('normal', 'timeout', 'operator_stop', 'controller_crash',
         'http_error', 'missing_usage', 'wrong_model', 'cut_stream',
         'slow_stream', 'active_request_stop', 'partial_start', 'cleanup_retry', 'cli_run', 'normal_repeat')

GATEWAY_FIXTURE = r'''
import json, sys, threading, uuid, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
sys.path.insert(0, '/app')
from gateway import Gateway
mode, run_id, session_id = sys.argv[1:]
model = 'deepseek-v4.1-flash'
class Upstream(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def do_POST(self):
        self.rfile.read(int(self.headers['Content-Length']))
        self.send_response(503 if mode == 'http_error' else 200)
        self.send_header('Content-Type', 'text/event-stream')
        self.end_headers()
        if mode in ('slow_stream', 'active_request_stop'):
            # Heartbeats without model output reproduce a queued provider request.
            try:
                for _ in range(130 if mode == 'slow_stream' else 360):
                    self.wfile.write(b': synthetic provider heartbeat\n\n'); self.wfile.flush()
                    time.sleep(1)
            except OSError: return
        item = {'id':'fixture-'+uuid.uuid4().hex, 'object':'chat.completion.chunk',
                'created':1, 'model':'wrong-model' if mode == 'wrong_model' else model,
                'choices':[{'index':0, 'delta':{'role':'assistant','content':'synthetic fixture complete'},
                            'finish_reason':None}]}
        self.wfile.write(('data: '+json.dumps(item)+'\n\n').encode())
        item['choices'] = [{'index':0, 'delta':{}, 'finish_reason':'stop'}]
        if mode != 'missing_usage':
            item['usage'] = {'prompt_tokens':20, 'completion_tokens':5, 'total_tokens':25}
        self.wfile.write(('data: '+json.dumps(item)+'\n\n').encode())
        if mode != 'cut_stream': self.wfile.write(b'data: [DONE]\n\n')
upstream = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
upstream.daemon_threads = True
threading.Thread(target=upstream.serve_forever, daemon=True).start()
server = Gateway(('0.0.0.0',8080), '/records', run_id, model, sys.stdin.readline().strip(),
                 upstream_host='127.0.0.1', upstream_port=upstream.server_port, tls=False, session_id=session_id)
server.serve_with_signals()
'''

WORKER_FIXTURE = r'''
import os, subprocess, sys, time, urllib.request
from pathlib import Path
if len(sys.argv) == 1:
    assert not any(k in os.environ for k in ['OPENCODE_GO_API_KEY','UNRELATED_SECRET'])
    subprocess.Popen([sys.executable, __file__, 'grandchild'], start_new_session=True)
    Path('/workspace/ready').write_text(str(os.getpid()))
    while True: time.sleep(1)
else:
    while True:
        urllib.request.urlopen('http://gateway:8080/health', timeout=3).read()
        with Path('/workspace/grandchild-heartbeat').open('a') as f:
            f.write(str(time.time())+'\n'); f.flush(); os.fsync(f.fileno())
        time.sleep(.2)
'''

CLI_WORKER_FIXTURE = r'''
import json, shutil, uuid, urllib.request
from pathlib import Path
shutil.copytree('/fixtures/reference', '/workspace', dirs_exist_ok=True)
body = {'model':'deepseek-v4.1-flash','stream':True,'messages':[{'role':'user','content':Path('/input/prompt.txt').read_text()}]}
request = urllib.request.Request('http://gateway:8080/v1/chat/completions', data=json.dumps(body).encode(), headers={'Content-Type':'application/json'})
urllib.request.urlopen(request, timeout=30).read()
print(json.dumps({'type':'step_finish','sessionID':'synthetic-'+uuid.uuid4().hex,'part':{'reason':'stop'}}), flush=True)
'''


def controller(root, case):
    """Child controller, terminated deliberately by the crash-recovery case."""
    root = Path(root)
    original_docker = runtime.docker
    condition_resolver = profiles.resolve
    def resolve(*args, **kwargs):
        condition = condition_resolver(*args, **kwargs)
        seconds = 15 if case == 'timeout' else 240 if case == 'slow_stream' else 120
        condition['budget']['value'] = seconds
        condition['runtime']['timeout_seconds'] = seconds
        return condition
    def docker(*args, **kwargs):
        args = list(args)
        if case == 'cleanup_retry' and args[:2] == ['network','rm']:
            raise RuntimeError('Synthetic network removal failure; stop CLI must retry')
        if args[0] == 'create' and '--name' in args:
            name = args[args.index('--name') + 1]
            lock = util.read_json(REPO/'artifacts/runtime/MS1-001/lock.json')
            if name.startswith('s2-gateway-'):
                if case == 'partial_start':
                    raise RuntimeError('Synthetic failure after network creation')
                at = args.index(lock['images']['gateway'])
                session_id = args[args.index('--session-id')+1]
                args = args[:at] + ['--entrypoint','python3', *runtime.mount(root/'fixtures','/fixtures',True),
                    lock['images']['gateway'], '/fixtures/gateway.py', case, 'MS1-001-explore-001', session_id]
            elif name.startswith('s2-worker-') and case in ('timeout','operator_stop','controller_crash','cli_run'):
                at = args.index(lock['images']['worker'])
                args = args[:at] + [*runtime.mount(root/'fixtures','/fixtures',True),
                    lock['images']['worker'],'python3','/fixtures/cli-worker.py' if case == 'cli_run' else '/fixtures/worker.py']
        return original_docker(*args, **kwargs)
    with patch.object(profiles, 'resolve', resolve), patch.object(runtime, 'docker', docker), \
         patch.object(runtime, '_gateway_credential', return_value=CANARY), \
         patch.dict(os.environ, {'OPENCODE_GO_API_KEY':CANARY, 'UNRELATED_SECRET':CANARY}):
        if case == 'cli_run':
            from harness import cli
            original_start = runtime.start
            def diagnostic_start(*args, **kwargs):
                value = original_start(*args, **kwargs)
                value.update(synthetic=True, model_called=False, diagnostic_injection={'case':case,'provider':'container-local mock'})
                run.save_manifest(root, value['run_id'], value)
                return value
            with patch.object(runtime, 'start', diagnostic_start):
                code = cli.main(['--repo',str(REPO),'--runs-dir',str(root),'run','--task','MS1-001','--intervention','explore'])
            util.write_new_json(root/'cli-result.json', {'exit_code':code, 'ordinary_command':'run'})
            if code: raise RuntimeError('Ordinary run CLI failed')
            return
        manifest = profiles.create(REPO, root, 'MS1-001', 'explore', 1)
        rid = manifest['run_id']
        runtime.start(REPO, root, rid)
        manifest = run.load_manifest(root, rid)
        manifest.update(synthetic=True, model_called=False,
                        diagnostic_injection={'case':case, 'provider':'container-local mock'})
        run.save_manifest(root, rid, manifest)


def wait_for(path, process, seconds=75):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if path.exists(): return
        if process.poll() is not None: raise RuntimeError('Controller ended before '+path.name)
        time.sleep(.3)
    raise TimeoutError('Fixture did not reach '+path.name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--child', type=Path)
    parser.add_argument('--case', choices=CASES)
    args = parser.parse_args()
    if args.child:
        controller(args.child, args.case)
        return 0
    batch = REPO/'runs'/('_container-probe-'+uuid.uuid4().hex[:12])
    batch.mkdir(parents=True)
    networks_before = set(runtime.docker('network','ls','--no-trunc','-q').stdout.split())
    util.write_new_json(batch/'plan.json', {'synthetic':True, 'model_called':False,
        'cases':list(CASES), 'controller_files':runtime.controller_files(REPO),
        'expected':{'normal':'completed, complete usage and input',
            'timeout':'timeout with stopped grandchildren',
            'operator_stop':'operator_stop with stopped grandchildren',
            'controller_crash':'recovered operator_stop with stopped grandchildren',
            'http_error':'provider_failure, incomplete measurement',
            'missing_usage':'completed but incomplete measurement',
            'wrong_model':'provider_failure, incomplete measurement',
            'cut_stream':'provider_failure, incomplete measurement',
            'slow_stream':'completed after 130 seconds of heartbeats, complete usage',
            'active_request_stop':'operator_stop, terminal cancelled journal and incomplete usage'}})
    results = []
    for case in CASES:
        root = batch/case
        fixtures = root/'fixtures'
        fixtures.mkdir(parents=True)
        (fixtures/'gateway.py').write_text(GATEWAY_FIXTURE, encoding='utf-8')
        (fixtures/'worker.py').write_text(WORKER_FIXTURE, encoding='utf-8')
        (fixtures/'cli-worker.py').write_text(CLI_WORKER_FIXTURE, encoding='utf-8')
        if case == 'cli_run': util.collect(REPO/'inner/fixtures/reference', fixtures/'reference')
        rid = 'MS1-001-explore-001'
        run_root = root/rid
        with (root/'controller.log').open('xb') as log:
            process = subprocess.Popen([sys.executable, __file__, '--child',str(root),'--case',case],
                cwd=REPO, env=child_environment(), stdout=log, stderr=subprocess.STDOUT)
            try:
                if case in ('operator_stop','controller_crash'):
                    wait_for(run_root/'workspace/grandchild-heartbeat', process)
                    if case == 'controller_crash':
                        process.kill(); process.wait(timeout=10)
                    stopped = subprocess.run([sys.executable,'-m','outer.harness.cli','--runs-dir',str(root),
                        'stop','--run',rid], cwd=REPO, env=child_environment(), capture_output=True, timeout=65)
                    (root/'stop-cli.stdout').write_bytes(stopped.stdout)
                    (root/'stop-cli.stderr').write_bytes(stopped.stderr)
                    if stopped.returncode: raise RuntimeError('Stop CLI failed')
                if case == 'active_request_stop':
                    wait_for(run_root/'usage/raw/started.jsonl', process)
                    stopped = subprocess.run([sys.executable,'-m','outer.harness.cli','--runs-dir',str(root),
                        'stop','--run',rid], cwd=REPO, env=child_environment(), capture_output=True, timeout=65)
                    (root/'stop-cli.stdout').write_bytes(stopped.stdout)
                    (root/'stop-cli.stderr').write_bytes(stopped.stderr)
                    if stopped.returncode: raise RuntimeError('Stop CLI failed')
                code = process.wait(timeout=280 if case == 'slow_stream' else 160)
                if code and case != 'controller_crash': raise RuntimeError('Controller failed')
            finally:
                if process.poll() is None:
                    process.kill(); process.wait(timeout=10)
                if (run_root/'runtime.json').exists(): runtime.stop_owned(run_root)
        manifest = run.load_manifest(root, rid)
        first_cleanup = manifest.get('network_cleanup')
        if case == 'cleanup_retry':
            if first_cleanup is None or first_cleanup['confirmed']: raise RuntimeError('Removal failure injection was not observed')
            prior_interval = {k:manifest[k] for k in ('ended_at','duration_seconds','end_reason')}
            repaired = runtime.request_stop(run_root)
            manifest = run.load_manifest(root, rid)
            if not repaired['network_cleanup']['confirmed'] or any(manifest[k] != v for k,v in prior_interval.items()):
                raise RuntimeError('Cleanup retry changed the measured interval or did not recover')
        manifest.update(synthetic=True, model_called=False)
        run.save_manifest(root, rid, manifest)
        live_usage.collect(run_root)
        usage = run.read_usage(run_root)
        state = util.read_json(run_root/'runtime.json')
        stopped = runtime.stop_owned(run_root)
        heartbeat = run_root/'workspace/grandchild-heartbeat'
        before = heartbeat.read_bytes() if heartbeat.exists() else None
        time.sleep(.8)
        children_stopped = before == (heartbeat.read_bytes() if heartbeat.exists() else None)
        credentials_absent = True
        for role in ('worker','gateway'):
            item = runtime.inspect_container(state[role])
            if item and CANARY in json.dumps(item): credentials_absent = False
        records_safe = all(CANARY.encode() not in p.read_bytes() for p in (run_root/'usage').rglob('*') if p.is_file())
        expected = ('environment_failure' if case == 'partial_start' else 'timeout' if case == 'timeout' else 'operator_stop' if case in ('operator_stop','controller_crash','active_request_stop')
                    else 'provider_failure' if case in ('http_error','wrong_model','cut_stream') else 'completed')
        passed = (manifest['end_reason'] == expected and stopped and children_stopped
                  and credentials_absent and records_safe)
        if case in ('normal','normal_repeat','slow_stream','cleanup_retry','cli_run'): passed = passed and usage['usage_complete'] and usage['input_reached']
        else: passed = passed and not usage['usage_complete']
        cancelled_recorded = None
        if case == 'active_request_stop':
            starts = util.read_lines(run_root/'usage/raw/started.jsonl')
            ends = util.read_lines(run_root/'usage/raw/events.jsonl')
            cancelled_recorded = (len(starts) == len(ends) == 1 and ends[0]['status'] == 'cancelled'
                and util.sha256_file(run_root/'usage/raw'/ends[0]['response_file']) == ends[0]['response_sha256'])
            passed = passed and cancelled_recorded
        result = {'case':case,'passed':bool(passed),'end_reason':manifest['end_reason'],
            'stop_confirmed':stopped,'children_stopped':children_stopped,
            'credentials_absent_from_container_metadata':credentials_absent,
            'records_redacted':records_safe,'usage_complete':usage['usage_complete'],
            'input_reached':usage.get('input_reached'),'cancelled_terminal_recorded':cancelled_recorded}
        after = set(runtime.docker('network','ls','--no-trunc','-q').stdout.split())
        result.update(network_cleanup=manifest.get('network_cleanup'), network_inventory_unchanged=after == networks_before,
                      first_cleanup=first_cleanup if case == 'cleanup_retry' else None)
        result['passed'] = bool(passed and manifest.get('network_cleanup',{}).get('confirmed') and after == networks_before)
        util.write_new_json(root/'result.json', result)
        results.append(result)
        util.write_json_atomic(batch/'progress.json', {'results':results,'complete':False})
        print(json.dumps(result), flush=True)
        if not result['passed']: raise RuntimeError('Container probe failed; retained '+str(root))
    util.write_new_json(batch/'result.json', {'passed':all(r['passed'] for r in results),
        'synthetic':True,'model_called':False,'results':results,'directory':str(batch)})
    print(str(batch), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
