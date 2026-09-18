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
         'http_error', 'missing_usage', 'wrong_model', 'cut_stream')

GATEWAY_FIXTURE = r'''
import json, sys, threading, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
sys.path.insert(0, '/app')
from gateway import Gateway
mode, run_id = sys.argv[1:]
model = 'deepseek-v4.1-flash'
class Upstream(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def do_POST(self):
        self.rfile.read(int(self.headers['Content-Length']))
        self.send_response(503 if mode == 'http_error' else 200)
        self.send_header('Content-Type', 'text/event-stream')
        self.end_headers()
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
threading.Thread(target=upstream.serve_forever, daemon=True).start()
server = Gateway(('0.0.0.0',8080), '/records', run_id, model, sys.stdin.readline().strip(),
                 upstream_host='127.0.0.1', upstream_port=upstream.server_port, tls=False)
server.serve_forever()
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


def controller(root, case):
    """Child controller, terminated deliberately by the crash-recovery case."""
    root = Path(root)
    original_docker = runtime.docker
    condition_resolver = profiles.resolve
    def resolve(*args, **kwargs):
        condition = condition_resolver(*args, **kwargs)
        seconds = 15 if case == 'timeout' else 120
        condition['budget']['value'] = seconds
        condition['runtime']['timeout_seconds'] = seconds
        return condition
    def docker(*args, **kwargs):
        args = list(args)
        if args[0] == 'create' and '--name' in args:
            name = args[args.index('--name') + 1]
            lock = util.read_json(REPO/'artifacts/runtime/MS1-001/lock.json')
            if name.startswith('s2-gateway-'):
                at = args.index(lock['images']['gateway'])
                args = args[:at] + ['--entrypoint','python3', *runtime.mount(root/'fixtures','/fixtures',True),
                    lock['images']['gateway'], '/fixtures/gateway.py', case, 'MS1-001-explore-001']
            elif name.startswith('s2-worker-') and case in ('timeout','operator_stop','controller_crash'):
                at = args.index(lock['images']['worker'])
                args = args[:at] + [*runtime.mount(root/'fixtures','/fixtures',True),
                    lock['images']['worker'],'python3','/fixtures/worker.py']
        return original_docker(*args, **kwargs)
    with patch.object(profiles, 'resolve', resolve), patch.object(runtime, 'docker', docker), \
         patch.object(runtime, '_gateway_credential', return_value=CANARY), \
         patch.dict(os.environ, {'OPENCODE_GO_API_KEY':CANARY, 'UNRELATED_SECRET':CANARY}):
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
    util.write_new_json(batch/'plan.json', {'synthetic':True, 'model_called':False,
        'cases':list(CASES), 'controller_files':runtime.controller_files(REPO),
        'expected':{'normal':'completed, complete usage and input',
            'timeout':'timeout with stopped grandchildren',
            'operator_stop':'operator_stop with stopped grandchildren',
            'controller_crash':'recovered operator_stop with stopped grandchildren',
            'http_error':'provider_failure, incomplete measurement',
            'missing_usage':'completed but incomplete measurement',
            'wrong_model':'provider_failure, incomplete measurement',
            'cut_stream':'provider_failure, incomplete measurement'}})
    results = []
    for case in CASES:
        root = batch/case
        fixtures = root/'fixtures'
        fixtures.mkdir(parents=True)
        (fixtures/'gateway.py').write_text(GATEWAY_FIXTURE, encoding='utf-8')
        (fixtures/'worker.py').write_text(WORKER_FIXTURE, encoding='utf-8')
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
                code = process.wait(timeout=160)
                if code and case != 'controller_crash': raise RuntimeError('Controller failed')
            finally:
                if process.poll() is None:
                    process.kill(); process.wait(timeout=10)
                if (run_root/'runtime.json').exists(): runtime.stop_owned(run_root)
        manifest = run.load_manifest(root, rid)
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
        expected = ('timeout' if case == 'timeout' else 'operator_stop' if case in ('operator_stop','controller_crash')
                    else 'provider_failure' if case in ('http_error','wrong_model','cut_stream') else 'completed')
        passed = (manifest['end_reason'] == expected and stopped and children_stopped
                  and credentials_absent and records_safe)
        if case == 'normal': passed = passed and usage['usage_complete'] and usage['input_reached']
        else: passed = passed and not usage['usage_complete']
        result = {'case':case,'passed':bool(passed),'end_reason':manifest['end_reason'],
            'stop_confirmed':stopped,'children_stopped':children_stopped,
            'credentials_absent_from_container_metadata':credentials_absent,
            'records_redacted':records_safe,'usage_complete':usage['usage_complete'],
            'input_reached':usage.get('input_reached')}
        util.write_new_json(root/'result.json', result)
        results.append(result)
        util.write_json_atomic(batch/'progress.json', {'results':results,'complete':False})
        print(json.dumps(result), flush=True)
        if not passed: raise RuntimeError('Container probe failed; retained '+str(root))
    util.write_new_json(batch/'result.json', {'passed':all(r['passed'] for r in results),
        'synthetic':True,'model_called':False,'results':results,'directory':str(batch)})
    print(str(batch), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
