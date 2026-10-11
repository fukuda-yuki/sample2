"""Pinned CLI continuation against a loopback fixture, never a model/provider.

This checks serial --session resumption only. It does NOT establish safe
in-flight tool-boundary injection, Docker acceptance or acquisition authority.
All workspace, prompts and native state are synthetic and temporary.
"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from outer.harness import gateway, profiles, runtime, util


def probe(executable, *, observe_boundary=False):
    repo = Path(__file__).resolve().parents[2]
    executable = Path(executable).resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix='staged-cli-fixture-') as directory:
        root = Path(directory)
        workspace = root/'workspace'; workspace.mkdir()
        env = {'PATH': os.defpath, 'HOME': str(root/'home'),
               'XDG_CONFIG_HOME': str(root/'config'), 'XDG_DATA_HOME': str(root/'data'),
               'XDG_CACHE_HOME': str(root/'cache'), 'TMPDIR': str(root),
               'OPENCODE_CONFIG': str(root/'opencode.json'),
               'OPENCODE_DISABLE_AUTOUPDATE': 'true', 'OPENCODE_DISABLE_MODELS_FETCH': 'true',
               'OPENCODE_DISABLE_DEFAULT_PLUGINS': 'true'}
        version = subprocess.check_output([str(executable), '--version'], env=env,
                                          cwd=workspace, text=True, timeout=30).strip()
        if version != '1.17.11':
            raise ValueError('Only the frozen OpenCode 1.17.11 is supported by this probe')
        help_text = subprocess.check_output([str(executable), 'run', '--help'], env=env,
                                           cwd=workspace, text=True, stderr=subprocess.STDOUT, timeout=30)
        if '--session' not in help_text or '--pure' not in help_text:
            raise ValueError('Frozen CLI continuation flags missing')
        initial = 'Synthetic initial requirement. Create the fixture implementation.'
        followup = 'Synthetic additional requirement. Keep the same implementation.'
        requests = []
        tool_observed = threading.Event()
        boundary_observation = {}
        class Fixture(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                requests.append(body)
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.end_headers()
                first = len(requests) == 1
                delta = {'role': 'assistant', 'tool_calls': [{'index': 0,
                    'id': 'synthetic-write', 'type': 'function', 'function': {'name': 'write',
                    'arguments': json.dumps({'filePath': str(workspace/'Program.cs'),
                                            'content': '// synthetic implementation\n'})}}]} if first else {
                    'role': 'assistant', 'content': 'Synthetic fixture complete.'}
                item = {'id': 'synthetic-'+str(len(requests)), 'object': 'chat.completion.chunk',
                        'created': 1, 'model': body['model'],
                        'choices': [{'index': 0, 'delta': delta, 'finish_reason': None}]}
                self.wfile.write(('data: '+json.dumps(item)+'\n\n').encode())
                item['choices'] = [{'index': 0, 'delta': {},
                                    'finish_reason': 'tool_calls' if first else 'stop'}]
                item['usage'] = {'prompt_tokens': 10, 'completion_tokens': 2, 'total_tokens': 12}
                self.wfile.write(('data: '+json.dumps(item)+'\n\n').encode())
                self.wfile.flush()
                if first and observe_boundary:
                    # Observe the existing non-attach CLI only. Do not inject,
                    # cancel, modify native state or adopt a different boundary.
                    start = time.monotonic()
                    boundary_observation['tool_terminal_before_response_eof'] = tool_observed.wait(5)
                    if tool_observed.is_set(): time.sleep(.25)
                    boundary_observation['requests_before_first_response_eof'] = len(requests)
                    boundary_observation['held_response_seconds'] = time.monotonic()-start
                self.wfile.write(b'data: [DONE]\n\n'); self.wfile.flush()
        server = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        condition = profiles.resolve(repo, 'MS1-001', 'explore')
        config = runtime.opencode_config(condition)
        config['provider']['sample2']['options']['baseURL'] = f'http://127.0.0.1:{server.server_port}/v1'
        util.write_new_json(root/'opencode.json', config)
        command = [str(executable), 'run', '--pure', '--format', 'json', '--title',
                   'synthetic-staged-probe', '--model', 'sample2/'+condition['runtime']['model_id']]
        # One deadline from the first invocation; never reset for continuation.
        deadline = time.monotonic()+90
        def invoke(text, extra):
            with tempfile.TemporaryDirectory(dir=root) as capture_dir:
                output_path = Path(capture_dir)/'stdout.jsonl'
                error_path = Path(capture_dir)/'stderr.txt'
                stdout = output_path.open('wb'); stderr = error_path.open('wb')
                process = subprocess.Popen(command+extra, stdin=subprocess.PIPE, stdout=stdout,
                    stderr=stderr, cwd=workspace, env=env)
                process.stdin.write(text.encode()); process.stdin.close()
                try:
                    while process.poll() is None:
                        lines = output_path.read_text().splitlines()
                        for line in lines:
                            try: event = json.loads(line)
                            except ValueError: continue
                            if event.get('type') == 'tool_use' and event.get('part',{}).get('state',{}).get('status') in ('completed','error'):
                                tool_observed.set()
                        if time.monotonic() >= deadline: raise TimeoutError('Original probe budget exhausted')
                        time.sleep(.02)
                    output = output_path.read_text(); error = error_path.read_text()
                    if process.returncode: raise RuntimeError('Synthetic CLI failed: '+error[-2000:])
                    return [json.loads(line) for line in output.splitlines() if line.startswith('{')]
                finally:
                    if process.poll() is None: process.kill()
                    process.wait(timeout=5)
                    stdout.close(); stderr.close()
        try:
            first = invoke(initial, [])
            sessions = {e['sessionID'] for e in first if 'sessionID' in e}
            if len(sessions) != 1:
                raise ValueError('Initial native session not unique')
            session = next(iter(sessions))
            before = len(requests)
            changed = (workspace/'Program.cs').is_file()
            hidden = all(followup not in json.dumps(r) for r in requests)
            second = invoke(followup, ['--session', session])
            all_sessions = {e['sessionID'] for e in first+second if 'sessionID' in e}
            observed = [i for i, r in enumerate(requests) if gateway.check_initial_input(r, followup)['verified']]
            result = dict(synthetic=True, model_called=False, opencode_version=version,
                executable_sha256=util.sha256_file(executable),
                continuation_mode='serial_after_idle', native_session_count=len(all_sessions),
                same_native_session=all_sessions == {session}, workspace_change_observed=changed,
                completed_write_event=any(e.get('type') == 'tool_use' and
                    e.get('part', {}).get('tool') == 'write' and
                    e['part']['state']['status'] == 'completed' for e in first),
                followup_absent_before_dispatch=hidden, initial_request_count=before,
                first_followup_request_index=observed[0] if observed else None,
                initial_prompt_retained_on_continuation=bool(observed) and
                    gateway.check_initial_input(requests[observed[0]], initial)['verified'],
                request_count=len(requests), tool_boundary_injection_verified=False,
                live_acceptance=False)
            if observe_boundary: result['boundary_observation'] = boundary_observation
            result['passed'] = all(result[k] for k in ('same_native_session', 'workspace_change_observed',
                'completed_write_event', 'followup_absent_before_dispatch',
                'initial_prompt_retained_on_continuation')) and bool(observed) and observed[0] == before
            return result
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=5)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--opencode', required=True, help='Local frozen binary; this probe never installs it')
    parser.add_argument('--observe-boundary', action='store_true', help='Hold synthetic first response EOF to inspect current CLI ordering; never inject')
    args = parser.parse_args()
    result = probe(args.opencode, observe_boundary=args.observe_boundary)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['passed'] else 1)
