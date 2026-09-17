"""Real OpenCode CLI against a local mock provider. No real model or key is used.

This host-side compatibility probe is not evidence of Docker isolation.
Every invocation retains its own native log, gateway originals and result.
"""
import json
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness import evaluate, gateway, profiles, runtime, util
from harness.security import child_environment


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--intervention', choices=['explore', 'preload', 'explained'])
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    root = repo / 'runs' / ('_agent-probe-' + uuid.uuid4().hex[:12])
    root.mkdir(parents=True)
    for name in ('workspace', 'home', 'config', 'data', 'cache', 'tmp'):
        (root / name).mkdir()
    model = 'deepseek-v4.1-flash'
    class Upstream(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            item = {'id': 'mock-' + uuid.uuid4().hex, 'object': 'chat.completion.chunk',
                    'model': model, 'created': 1,
                    'choices': [{'index': 0, 'delta': {'role':'assistant','content':'synthetic-probe-complete'},
                                 'finish_reason': None}]}
            self.wfile.write(('data: ' + json.dumps(item) + '\n\n').encode())
            item['choices'] = [{'index':0, 'delta':{}, 'finish_reason':'stop'}]
            item['usage'] = {'prompt_tokens':20, 'completion_tokens':5, 'total_tokens':25}
            self.wfile.write(('data: ' + json.dumps(item) + '\n\ndata: [DONE]\n\n').encode())
    upstream = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
    proxy = gateway.Gateway(('127.0.0.1', 0), root/'raw', root.name, model, 'nonsecret-test-fixture',
                            upstream_host='127.0.0.1', upstream_port=upstream.server_port, tls=False)
    for server in (upstream, proxy):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    config = runtime.opencode_config(profiles.resolve(repo, 'MS1-001', 'explore'))
    config['provider']['sample2']['options']['baseURL'] = f'http://127.0.0.1:{proxy.server_port}/v1'
    util.write_new_json(root/'opencode.json', config)
    prompt = root/'prompt.txt'
    context = None
    if args.intervention:
        condition = profiles.resolve(repo, 'MS1-001', args.intervention)
        source = runtime.source(repo, condition)
        text, context = profiles.prepare_prompt(condition, source)
        prompt.write_text(text, encoding='utf-8')
        util.write_new_json(root/'context.json', context)
    else:
        prompt.write_text('This is a non-model fixture. Reply synthetic-probe-complete.', encoding='utf-8')
    env = child_environment({
        'HOME':str(root/'home'), 'USERPROFILE':str(root/'home'),
        'APPDATA':str(root/'config'), 'LOCALAPPDATA':str(root/'data'),
        'XDG_CONFIG_HOME':str(root/'config'), 'XDG_DATA_HOME':str(root/'data'),
        'XDG_CACHE_HOME':str(root/'cache'), 'TEMP':str(root/'tmp'), 'TMP':str(root/'tmp'),
        'OPENCODE_CONFIG':str(root/'opencode.json'), 'OPENCODE_DISABLE_AUTOUPDATE':'true',
        'OPENCODE_DISABLE_MODELS_FETCH':'true', 'OPENCODE_DISABLE_DEFAULT_PLUGINS':'true'})
    invocation = [shutil.which('opencode'), 'run', 'Read the attached fixture.', '--pure',
                  '--format', 'json', '--model', 'sample2/'+model, '--title',root.name, '--file',str(prompt)]
    util.write_new_json(root/'plan.json', {'synthetic':True, 'model_called':False,
        'purpose':'host CLI compatibility only', 'command':invocation,
        'expected':{'exit_code':0,'at_least_one_gateway_call':True,'input_reached':True}})
    try:
        with (root/'agent.jsonl').open('xb') as log:
            process = subprocess.Popen(invocation, cwd=root/'workspace', env=env,
                                       stdout=log, stderr=subprocess.STDOUT, **evaluate._popen_kwargs())
            try:
                code = process.wait(timeout=90)
            except BaseException:
                evaluate.kill_process_tree(process)
                raise
    finally:
        proxy.shutdown(); proxy.server_close()
        upstream.shutdown(); upstream.server_close()
    events = util.read_lines(root/'raw/events.jsonl')
    from harness.live_usage import input_locations
    messages = util.read_json(root/'raw'/events[0]['request_file']).get('messages', []) if events else []
    locations = input_locations(messages, prompt.read_text(encoding='utf-8'))
    reached = bool(locations)
    result = {'synthetic':True, 'model_called':False, 'exit_code':code,
        'gateway_calls':len(events), 'input_reached':reached, 'directory':str(root),
        'intervention':args.intervention,
        'locations':locations,
        'blocks_reached': sum(bool(input_locations(messages, block['text'])) for block in context['blocks']) if context else None,
        'passed':code == 0 and bool(events) and reached and all(e['status']=='completed' for e in events)}
    util.write_new_json(root/'result.json', result)
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
