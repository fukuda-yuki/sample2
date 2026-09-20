"""No-model connection evidence through the production controller and OpenCode serializer.

Only the gateway's upstream and credential bootstrap are replaced. The worker,
agent, prompt construction, tools, isolation and cleanup run normally.
"""
import argparse
import copy
import json
from pathlib import Path
from unittest.mock import patch

from outer.harness import profiles, run, runtime, util

ARMS = ('catalog-expanded', 'catalog-compact')
RUNTIME = 'deepseek-catalog-v1'
REPO = Path(__file__).resolve().parents[1]

MOCK = r'''
import argparse, json, sys, threading, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
sys.path.insert(0, '/app')
from gateway import Gateway
p=argparse.ArgumentParser()
p.add_argument('--run-id'); p.add_argument('--model'); p.add_argument('--session-id')
p.add_argument('--upstream-timeout',type=int); p.add_argument('--expected-prompt')
a=p.parse_args()
class Provider(BaseHTTPRequestHandler):
    def log_message(self,*_): pass
    def do_POST(self):
        raw=self.rfile.read(int(self.headers['Content-Length']))
        body=json.loads(raw)
        (Path('/records')/('mock-provider-'+uuid.uuid4().hex+'.json')).write_bytes(raw)
        self.send_response(200); self.send_header('Content-Type','text/event-stream'); self.end_headers()
        tool_seen=any(m.get('role')=='tool' for m in body['messages'])
        delta={'role':'assistant','content':'Connection probe complete.'}
        finish='stop'
        if not tool_seen:
            command='python3 /inputs/catalog-tools/catalog_return_contract.py read-source --source /inputs/legacy-source/MvcMusicStore-Completed/MvcMusicStore/Models/SampleData.cs --offset 361 --limit 71'
            delta={'role':'assistant','tool_calls':[{'index':0,'id':'probe-range', 'type':'function',
                'function':{'name':'bash','arguments':json.dumps({'command':command,'description':'Read the source range'})}}]}
            finish='tool_calls'
        item={'id':'mock-local','object':'chat.completion.chunk','created':1,'model':a.model,
              'choices':[{'index':0,'delta':delta,'finish_reason':None}]}
        self.wfile.write(('data: '+json.dumps(item)+'\n\n').encode())
        item['choices']=[{'index':0,'delta':{},'finish_reason':finish}]
        item['usage']={'prompt_tokens':20,'completion_tokens':5,'total_tokens':25}
        self.wfile.write(('data: '+json.dumps(item)+'\n\ndata: [DONE]\n\n').encode())
server=ThreadingHTTPServer(('127.0.0.1',0),Provider)
server.daemon_threads=True
threading.Thread(target=server.serve_forever,daemon=True).start()
gateway=Gateway(('0.0.0.0',8080),'/records',a.run_id,a.model,sys.stdin.readline().strip(),
    upstream_host='127.0.0.1',upstream_port=server.server_port,tls=False,
    session_id=a.session_id,expected_prompt=a.expected_prompt,upstream_timeout=a.upstream_timeout)
gateway.serve_with_signals()
'''


def first_body(root):
    event = util.read_lines(root / 'usage/raw/started.jsonl')[0]
    path = root / 'usage/raw' / event['request_file']
    assert util.sha256_file(path) == event['request_sha256']
    return util.read_json(path), path


def common_body(root):
    body, path = first_body(root)
    result = copy.deepcopy(body)
    condition = util.read_json(root / 'condition.json')
    if condition['intervention']['append_source_packet']:
        raw = (root / 'inputs/catalog-derived/raw-first.txt').read_bytes().decode('utf-8')
        for message in result['messages']:
            if isinstance(message.get('content'), str):
                message['content'] = message['content'].replace(raw, '')
            elif isinstance(message.get('content'), list):
                for part in message['content']:
                    if 'text' in part:
                        part['text'] = part['text'].replace(raw, '')
    return result


def check_pair(expanded, compact):
    roots = [Path(expanded), Path(compact)]
    receipts = [util.read_json(r / 'usage/raw/first-request-contract.json') for r in roots]
    access = [util.read_json(r / 'state/catalog-access.json') for r in roots]
    checks = {'first_requests_verified': all(r['verified'] for r in receipts),
        'semantic_difference_only_packet': common_body(roots[0]) == common_body(roots[1]),
        'same_files_permissions_and_ranges': access[0] == access[1],
        'actual_worker_access': all(a['verified'] for a in access),
        'cleanup_confirmed': all(util.read_json(r / 'manifest.json')['network_cleanup']['confirmed'] for r in roots)}
    for root in roots:
        prompt = (root / 'inputs/prompt.txt').read_bytes()
        receipt = util.read_json(root / 'usage/raw/first-request-contract.json')
        checks[root.name + '_prompt_hash'] = util.sha256_bytes(prompt) == receipt['prompt_sha256']
    return {'verified': all(checks.values()), 'checks': checks,
        'first_requests': [{'path': str(first_body(r)[1]), 'sha256': util.sha256_file(first_body(r)[1])} for r in roots]}


def probe(destination):
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    fixtures = destination / 'fixtures'
    fixtures.mkdir()
    (fixtures / 'gateway.py').write_text(MOCK, encoding='utf-8', newline='\n')
    original = runtime.docker
    lock = util.read_json(profiles.runtime_root(REPO, 'MS1-001', profiles.read(REPO, 'runtimes', RUNTIME)) / 'lock.json')
    def docker(*args, **kwargs):
        args = list(args)
        if args[:3] == ['network', 'connect', 'bridge']:
            # The mock has no external route and never uses a real credential.
            import subprocess
            return subprocess.CompletedProcess(args, 0, '', '')
        if args[0] == 'create' and lock['images']['gateway'] in args:
            at = args.index(lock['images']['gateway'])
            args = args[:at] + ['--entrypoint', 'python3', *runtime.mount(fixtures, '/fixtures', True),
                               lock['images']['gateway'], '/fixtures/gateway.py'] + args[at+1:]
        return original(*args, **kwargs)
    roots = []
    with patch.object(runtime, 'docker', docker), patch.object(runtime, '_gateway_credential', return_value='local-mock-only'):
        for arm in ARMS:
            manifest = profiles.create(REPO, destination, 'MS1-001', arm, 1, RUNTIME)
            root = destination / manifest['run_id']
            roots.append(root)
            print('PROBE ' + arm, flush=True)
            try:
                runtime.start(REPO, destination, root.name)
            finally:
                manifest = run.load_manifest(destination, root.name)
                manifest.update(synthetic=True, model_called=False, provider='container-local mock',
                    diagnostic_note='Synthetic usage values; excluded from the four live pilot slots')
                run.save_manifest(destination, root.name, manifest)
            if manifest['end_reason'] != 'completed' or not manifest['network_cleanup']['confirmed']:
                raise RuntimeError('Probe failed; retained evidence at ' + str(root))
    result = check_pair(*roots)
    for root in roots:
        starts = util.read_lines(root / 'usage/raw/started.jsonl')
        upstream = {util.sha256_file(p) for p in (root/'usage/raw').glob('mock-provider-*.json')}
        second = util.read_json(root/'usage/raw'/starts[1]['request_file']) if len(starts)>1 else {}
        output = (root/'state/catalog-range-361-71.txt').read_bytes().decode('utf-8')
        result['checks'][root.name+'_upstream_bytes'] = all(e['request_sha256'] in upstream for e in starts)
        result['checks'][root.name+'_retrieval_in_next_request'] = any(
            m.get('role')=='tool' and output in str(m.get('content','')) for m in second.get('messages',[]))
    result.update(verified=all(result['checks'].values()), model_called=False,
        runtime_lock_sha256=util.sha256_file(profiles.runtime_root(REPO,'MS1-001',profiles.read(REPO,'runtimes',RUNTIME))/'lock.json'),
        evidence=util.tree_hashes(destination), excluded_from_live_pilot=True)
    util.write_new_json(destination/'connection-result.json', result)
    print(json.dumps({'verified':result['verified'],'out':str(destination)}),flush=True)
    if not result['verified']:
        raise RuntimeError('Connection comparison failed; inspect saved checks')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    probe(parser.parse_args().out)
