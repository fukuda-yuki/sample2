"""Fixed-upstream gateway. Credential enters on stdin, never argv/env/files.

Runs in a separate container. Only this process has both upstream access and
the credential. Request bodies and redacted response streams are researcher-only.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import threading
import uuid


def now():
    return datetime.now(timezone.utc).isoformat()


def usage_from_native(native):
    if not isinstance(native, dict):
        return None
    details = native.get('prompt_tokens_details') or {}
    out_details = native.get('completion_tokens_details') or {}
    return {'input_tokens': native.get('prompt_tokens'),
            'output_tokens': native.get('completion_tokens'),
            'total_tokens': native.get('total_tokens'),
            'cache_read_tokens': details.get('cached_tokens', native.get('prompt_cache_hit_tokens')),
            'cache_write_tokens': details.get('cache_write_tokens'),
            'reasoning_tokens': out_details.get('reasoning_tokens')}


class SecretFilter:
    """Hold enough bytes to redact a credential split across transport chunks."""
    def __init__(self, secret):
        self.secret, self.pending, self.detected = secret.encode(), b'', False

    def feed(self, chunk, final=False):
        self.pending += chunk
        if self.secret in self.pending:
            self.detected = True
            self.pending = self.pending.replace(self.secret, b'[REDACTED]')
        size = len(self.pending) if final else max(0, len(self.pending) - len(self.secret) + 1)
        result, self.pending = self.pending[:size], self.pending[size:]
        return result


class Gateway(ThreadingHTTPServer):
    daemon_threads = False

    def __init__(self, address, root, run_id, model, secret, *, upstream_host='opencode.ai',
                 upstream_port=443, tls=True, session_id=None):
        super().__init__(address, Handler)
        self.root, self.run_id, self.model, self.secret = Path(root), run_id, model, secret
        self.session_id = session_id or run_id
        self.upstream_host, self.upstream_port, self.tls = upstream_host, upstream_port, tls
        self.lock = threading.Lock()
        self.failed = threading.Event()
        self.root.mkdir(parents=True, exist_ok=True)

    def record(self, file, obj):
        with self.lock:
            with (self.root / file).open('a', encoding='utf-8', newline='\n') as f:
                f.write(json.dumps(obj, ensure_ascii=False) + '\n')
                f.flush()
                os.fsync(f.fileno())


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"ready":true}')
        else:
            self.send_error(403, 'Endpoint denied')

    def do_POST(self):
        g = self.server
        if self.path not in ('/v1/chat/completions', '/chat/completions') or g.failed.is_set():
            self.send_error(403, 'Endpoint denied or Run stopped')
            return
        try:
            self.connection.settimeout(30)
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 64 * 1024 * 1024:
                raise ValueError()
            raw = self.rfile.read(size)
            body = json.loads(raw)
            if g.secret.encode() in raw or body.get('model') != g.model or not body.get('stream'):
                raise ValueError()
            if (not isinstance(body.get('messages'), list) or body.get('store')
                    or not isinstance(body.get('stream_options', {}), dict)):
                raise ValueError()
            # include_usage changes telemetry only; capture the exact transmitted body.
            body.setdefault('stream_options', {})['include_usage'] = True
            raw = json.dumps(body, ensure_ascii=False, separators=(',', ':')).encode()
        except (ValueError, TypeError, OSError, AttributeError):
            g.failed.set()
            g.record('control.jsonl', {'run_id': g.run_id, 'at': now(), 'reason': 'request_rejected'})
            g.record('failure.jsonl', {'run_id': g.run_id, 'at': now(), 'status': 'request_rejected'})
            self.send_error(403, 'Request policy denied')
            return
        rid = uuid.uuid4().hex
        event = {'run_id': g.run_id, 'session_id': g.session_id, 'event_id': rid, 'request_id': rid,
                 'mode': 'request', 'includes_children': False, 'model_id': g.model,
                 'provider': 'opencode-go', 'started_at': now(), 'usage': None,
                 'status': 'started', 'request_file': rid + '.request.json',
                 'response_file': rid + '.response.sse',
                 'request_sha256': hashlib.sha256(raw).hexdigest()}
        with (g.root / event['request_file']).open('xb') as original:
            original.write(raw)
            original.flush()
            os.fsync(original.fileno())
        g.record('started.jsonl', event)
        filt = SecretFilter(g.secret)
        response_bytes = bytearray()
        connection = None
        sent_headers = False
        original = (g.root / event['response_file']).open('xb')
        try:
            cls = http.client.HTTPSConnection if g.tls else http.client.HTTPConnection
            connection = cls(g.upstream_host, g.upstream_port, timeout=120)
            connection.request('POST', '/zen/go/v1/chat/completions', raw, {
                'Authorization': 'Bearer ' + g.secret, 'Content-Type': 'application/json',
                'Accept': 'text/event-stream', 'User-Agent': 'sample2-verification-machine/1',
                'x-opencode-session': g.session_id})
            response = connection.getresponse()
            event['http_status'] = response.status
            if response.status != 200:
                g.failed.set()
            self.send_response(response.status)
            self.send_header('Content-Type', response.getheader('Content-Type', 'text/event-stream'))
            self.send_header('Connection', 'close')
            self.end_headers()
            sent_headers = True
            connected = True
            while True:
                chunk = response.read1(16384)
                safe = filt.feed(chunk, final=not chunk)
                response_bytes.extend(safe)
                original.write(safe)
                original.flush()
                os.fsync(original.fileno())
                if len(response_bytes) > 64 * 1024 * 1024:
                    raise ValueError('response_limit')
                if connected:
                    try:
                        self.wfile.write(safe)
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionError, OSError):
                        connected = False
                        event['client_disconnected'] = True
                if not chunk:
                    break
            done = False
            for line in bytes(response_bytes).splitlines():
                if not line.startswith(b'data:'):
                    continue
                payload = line[5:].strip()
                if payload == b'[DONE]':
                    done = True
                    continue
                item = json.loads(payload)
                if item.get('model'):
                    event['response_model_id'] = item['model']
                if item.get('id'):
                    event['provider_response_id'] = item['id']
                if item.get('usage') is not None:
                    event['native_usage'] = item['usage']
                    event['usage'] = usage_from_native(item['usage'])
            event['stream_done'] = done
            event['status'] = 'completed' if response.status == 200 and done else 'provider_error'
            if event.get('response_model_id') != g.model:
                event['policy_error'] = 'response_model_mismatch'
                g.failed.set()
        except Exception as exc:
            # Never log exception messages: upstream errors can include credentials.
            event['status'] = 'transport_error'
            event['error_type'] = type(exc).__name__
            g.failed.set()
            if not sent_headers:
                self.send_error(502, 'Upstream transport failed')
        finally:
            if connection:
                connection.close()
            tail = filt.feed(b'', final=True)
            response_bytes.extend(tail)
            original.write(tail)
            original.flush()
            os.fsync(original.fileno())
            original.close()
            if filt.detected:
                event['policy_error'] = 'credential_echo_redacted'
                g.failed.set()
            event['response_sha256'] = hashlib.sha256(response_bytes).hexdigest()
            event['ended_at'] = now()
            if event['status'] != 'completed':
                g.failed.set()
            g.record('events.jsonl', event)
            if g.failed.is_set():
                g.record('failure.jsonl', {'run_id': g.run_id, 'request_id': rid,
                                          'status': event['status'], 'at': now()})


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--run-id', required=True)
    p.add_argument('--model', required=True)
    p.add_argument('--session-id')
    p.add_argument('--directory', default='/records')
    args = p.parse_args()
    import sys
    secret = sys.stdin.readline().strip()
    if not secret:
        raise SystemExit('Gateway credential is missing')
    server = Gateway(('0.0.0.0', 8080), args.directory, args.run_id, args.model, secret,
                     session_id=args.session_id)
    server.serve_forever()


if __name__ == '__main__':
    main()
