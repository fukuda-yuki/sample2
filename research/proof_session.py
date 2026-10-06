"""Bounded, read-only proof sessions for sealed evidence.

This module never acquires a model, changes STOP, creates a campaign, or publishes.
Cached decisions live only in one owning process. Windows read handles deny writes
and deletion of every file actually read by a proof. Directory notifications make
additions/renames invalidate the session. External read probes
are replayed, never cached as liveness. A restart starts with no proof trust.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import argparse
import copy
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import queue
from concurrent.futures import Future
import subprocess
import sys
import threading
import time
import uuid

# `python -m` must use the same context variables as production imports.
if __name__ == '__main__':
    sys.modules['research.proof_session'] = sys.modules[__name__]

MAX_SECONDS = 8 * 3600
MAX_ENTRIES = 512
_CURRENT = ContextVar('closed_proof_session', default=None)
_CAPTURE = ContextVar('closed_proof_capture', default=None)
_BYPASS = ContextVar('closed_proof_audit_bypass', default=False)
_ORIGINAL_RUN = subprocess.run
_AUDIT_INSTALLED = False


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), default=str)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class ProofInvalid(RuntimeError):
    pass


class WindowsGuard:
    """Kernel enforced byte stability, with fail-closed namespace change detection."""
    def __init__(self):
        if os.name != 'nt':
            raise ProofInvalid('Shared evidence proofs require Windows guards')
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        k = self.kernel
        k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
            wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        k.CreateFileW.restype = wintypes.HANDLE
        k.FindFirstChangeNotificationW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL, wintypes.DWORD]
        k.FindFirstChangeNotificationW.restype = wintypes.HANDLE
        k.FindCloseChangeNotification.argtypes = [wintypes.HANDLE]
        k.FindCloseChangeNotification.restype = wintypes.BOOL
        k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        k.WaitForSingleObject.restype = wintypes.DWORD
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.CloseHandle.restype = wintypes.BOOL
        self.files, self.watches, self.parents = {}, {}, {}
        self.closed = False

    def _path(self, value):
        p = Path(os.path.abspath(os.fsdecode(value)))
        for ancestor in (p, *p.parents):
            if ancestor.is_symlink() or ancestor.is_junction():
                raise ProofInvalid('A proof dependency contains a link or junction')
        return p

    def _handle(self, path, access, share, flags):
        name = str(path)
        if not name.startswith('\\\\?\\'):
            name = '\\\\?\\' + name
        handle = self.kernel.CreateFileW(name, access, share, None, 3, flags, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ProofInvalid('Cannot protect proof dependency: ' + str(path))
        return handle

    def _ancestors(self, path):
        for parent in path.parents:
            key = str(parent).casefold()
            if key not in self.parents:
                # Directory identity cannot be renamed/deleted; children may grow.
                self.parents[key] = (parent, self._handle(parent, 0x80, 3, 0x02000000))

    def read(self, value):
        if isinstance(value, int):
            return
        p = self._path(value)
        if not p.exists():
            self.watch(p.parent)
            return
        if not p.is_file():
            raise ProofInvalid('Proof read is not a regular file')
        key = str(p).casefold()
        if key not in self.files:
            self._ancestors(p)
            self.watch(p.parent)
            self.files[key] = (p, self._handle(p, 0x80000000, 1, 0x08000000))

    def watch(self, value):
        p = self._path(value)
        while not p.exists():
            p = p.parent
        if not p.is_dir():
            p = p.parent
        key = str(p).casefold()
        if key in self.watches:
            return
        self._ancestors(p / '__proof_identity__')
        # Per-directory watches avoid invalidation by unrelated sibling trees.
        # File handles protect bytes; watching directory write timestamps would
        # also invalidate when an unrelated child's contents change (e.g. Git).
        handle = self.kernel.FindFirstChangeNotificationW(str(p), False, 0x1 | 0x2)
        if handle == ctypes.c_void_p(-1).value:
            raise ProofInvalid('Cannot watch proof namespace: ' + str(p))
        self.watches[key] = (p, handle)

    def check(self):
        if self.closed:
            raise ProofInvalid('Proof guard is closed')
        for p, handle in self.watches.values():
            state = self.kernel.WaitForSingleObject(handle, 0)
            if state != 258:
                raise ProofInvalid('Proof namespace changed: ' + str(p) + ' (wait=' + str(state) + ')')
        # The handles pin identities; reparse changes are also rejected explicitly.
        for p, _ in self.parents.values():
            if p.is_symlink() or p.is_junction():
                raise ProofInvalid('Proof ancestor became a reparse point')

    def close(self):
        if self.closed:
            return
        self.closed = True
        for _, handle in self.watches.values():
            self.kernel.FindCloseChangeNotification(handle)
        for _, handle in list(self.files.values()) + list(self.parents.values()):
            self.kernel.CloseHandle(handle)


class Entry:
    def __init__(self, guard):
        self.guard = guard
        self.dependencies = []
        self.probes = {}
        self.result = None

    def check(self, seen, probes):
        if id(self) in seen:
            return
        seen.add(id(self))
        self.guard.check()
        for dependency in self.dependencies:
            dependency.check(seen, probes)
        for key, (args, kwargs, expected) in self.probes.items():
            if key not in probes:
                token = _BYPASS.set(True)
                try:
                    actual = _ORIGINAL_RUN(*args, **kwargs)
                finally:
                    _BYPASS.reset(token)
                probes[key] = (actual.returncode, actual.stdout, actual.stderr)
            if probes[key] != expected:
                raise ProofInvalid('External read probe changed')
        self.guard.check()


def _readonly_command(args, kwargs):
    command = args[0] if args else kwargs.get('args')
    if not isinstance(command, (list, tuple)) or kwargs.get('shell'):
        raise ProofInvalid('Proof subprocess must be a structured read-only command')
    if any(kwargs.get(k) not in (None,subprocess.PIPE) for k in ('stdout','stderr')):
        raise ProofInvalid('Proof subprocess output must not target a file')
    strings = [str(x) for x in command]
    executable = Path(strings[0]).name.lower().removesuffix('.exe')
    if executable == 'docker':
        tail = strings[1:]
        allowed = (tail and tail[0] in ('ps', 'inspect')) or tail[:2] in (['network', 'ls'], ['image', 'inspect'])
    elif executable == 'git':
        tail = strings[1:]
        while tail and tail[0] in ('-c', '-C'):
            tail = tail[2:]
        allowed = bool(tail) and tail[0] in ('show', 'status', 'rev-parse', 'cat-file', 'ls-tree')
        if 'cat-file' in strings:
            allowed = allowed and not any(x in strings for x in ('--filters', '--textconv'))
    else:
        allowed = False
    if not allowed:
        raise ProofInvalid('Proof cannot run a mutating or unreviewed subprocess')


def _record_run(*args, **kwargs):
    entry = _CAPTURE.get()
    if entry is None or _BYPASS.get():
        return _ORIGINAL_RUN(*args, **kwargs)
    _readonly_command(args, kwargs)
    token = _BYPASS.set(True)
    try:
        result = _ORIGINAL_RUN(*args, **kwargs)
    finally:
        _BYPASS.reset(token)
    # A fresh environment is retained only in memory; never written or sent to clients.
    key = digest([args, {k:v for k,v in kwargs.items() if k != 'env'}])
    entry.probes[key] = (args, kwargs, (result.returncode, result.stdout, result.stderr))
    return result


def _audit(event, args):
    entry = _CAPTURE.get()
    if entry is None or _BYPASS.get():
        return
    token = _BYPASS.set(True)
    try:
        if event == 'open':
            path, mode, flags = args
            if (mode and any(c in mode for c in 'wax+')) or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                raise ProofInvalid('A closed proof attempted a write')
            entry.guard.read(path)
        elif event in ('os.scandir', 'os.listdir'):
            entry.guard.watch(args[0])
        elif event in ('os.remove', 'os.rename', 'os.mkdir', 'os.rmdir', 'os.chmod', 'os.link', 'os.symlink'):
            raise ProofInvalid('A closed proof attempted a filesystem mutation')
        elif event in ('socket.connect', 'socket.bind'):
            raise ProofInvalid('A closed proof attempted network access')
        elif event == 'subprocess.Popen':
            _readonly_command((args[1],), {})
    finally:
        _BYPASS.reset(token)


def _install():
    global _AUDIT_INSTALLED
    if not _AUDIT_INSTALLED:
        sys.addaudithook(_audit)
        subprocess.run = _record_run
        _AUDIT_INSTALLED = True


class Session:
    def __init__(self, seconds=3600, *, owner_alive=lambda: True, guard_factory=WindowsGuard):
        if type(seconds) not in (int, float) or not 0 < seconds <= MAX_SECONDS:
            raise ValueError('A finite proof session is required')
        self.deadline = time.monotonic() + seconds
        self.owner_alive = owner_alive
        self.guard_factory = guard_factory
        self.entries = {}
        self.closed = False
        self.lock = threading.RLock()
        self.stats = dict(full_validations=0, hits=0)
        _install()

    def check(self):
        if self.closed or time.monotonic() >= self.deadline or not self.owner_alive():
            self.close()
            raise ProofInvalid('Proof session expired or lost its owner')

    def use(self, name, arguments, validate):
        with self.lock:
            self.check()
            key = (name, digest(arguments))
            parent = _CAPTURE.get()
            if key in self.entries:
                entry = self.entries[key]
                try:
                    entry.check(set(), {})
                except BaseException:
                    self.close()
                    raise
                self.stats['hits'] += 1
            else:
                if len(self.entries) >= MAX_ENTRIES:
                    self.close()
                    raise ProofInvalid('Proof session entry limit reached')
                entry = Entry(self.guard_factory())
                token = _CAPTURE.set(entry)
                try:
                    entry.result = validate()
                    if entry.result is None or entry.result is False:
                        raise ProofInvalid('An unsuccessful proof cannot be shared')
                    entry.guard.check()
                    self.check()
                except BaseException:
                    entry.guard.close()
                    raise
                finally:
                    _CAPTURE.reset(token)
                self.entries[key] = entry
                self.stats['full_validations'] += 1
            if parent is not None and entry not in parent.dependencies:
                parent.dependencies.append(entry)
            return copy.deepcopy(entry.result)

    def close(self):
        if self.closed:
            return
        self.closed = True
        for entry in self.entries.values():
            entry.guard.close()
        self.entries.clear()


@contextmanager
def local_session(seconds=3600, **kwargs):
    session = Session(seconds, **kwargs)
    token = _CURRENT.set(session)
    try:
        yield session
    finally:
        _CURRENT.reset(token)
        session.close()


def use(name, arguments, validate):
    session = _CURRENT.get()
    if session is None:
        return validate()
    return session.use(name, arguments, validate)


def watch_absence(path):
    """Include an explicit negative-path predicate in a closed proof."""
    entry = _CAPTURE.get()
    if entry is not None:
        token = _BYPASS.set(True)
        try:
            entry.guard.watch(Path(path).parent)
        finally:
            _BYPASS.reset(token)


# Only these production, read-only proofs are callable across process boundaries.
def dispatch(name, arguments):
    if name == 'readiness':
        from research import acquisition_readiness
        return acquisition_readiness.readiness_for_main(Path(arguments['repo']), arguments['plan'])
    if name == 'main-phase-static':
        from research import acquisition_readiness
        return acquisition_readiness._verify_main_phase_static(Path(arguments['path']), Path(arguments['repo']))
    if name == 'normal-gate':
        from research import acquisition_sharing
        return acquisition_sharing._validate_gate_proof(arguments['value'], arguments['current'],
            arguments['number'], arguments['plan'])
    if name == 'recovery-evidence':
        from research import campaign_recovery
        ctx = arguments['context']
        for key in ('repo', 'wave_path'):
            ctx[key] = Path(ctx[key])
        return campaign_recovery._validate_recovery_evidence(ctx, Path(arguments['path']), arguments['value'])
    raise ProofInvalid('Unknown proof operation')


class Client:
    def __init__(self, reference):
        from multiprocessing.connection import Client as Connect
        self.connect = Connect
        self.path = Path(reference).resolve()
        self.bytes = self.path.read_bytes()
        self.record = json.loads(self.bytes)
        if (self.record.get('kind') != 'bounded_readonly_proof_session_v1'
                or not self.record['address'].startswith('\\\\.\\pipe\\sample2-proof-')
                or len(bytes.fromhex(self.record['authkey'])) != 32):
            raise ProofInvalid('Invalid proof session reference')
        if self.record.get('source_sha256') != hashlib.sha256(Path(__file__).read_bytes()).hexdigest():
            raise ProofInvalid('Proof service source differs from client')
        source_root = Path(__file__).resolve().parents[1]
        expected_names = {p.relative_to(source_root).as_posix() for directory in ('research','outer/harness')
            for p in (source_root/directory).glob('*.py')}
        inventory = self.record.get('source_inventory',{})
        if (self.record.get('source_root') != str(source_root) or set(inventory) != expected_names
                or any(hashlib.sha256((source_root/name).read_bytes()).hexdigest() != value for name,value in inventory.items())):
            raise ProofInvalid('Proof service controller inventory differs from client')
        self.session_id = self.record['session_id']
        self.check()

    def request(self, request):
        if self.path.read_bytes() != self.bytes:
            raise ProofInvalid('Proof session reference changed')
        try:
            connection = self.connect(self.record['address'], family='AF_PIPE',
                authkey=bytes.fromhex(self.record['authkey']))
            with connection:
                connection.send_bytes(canonical(dict(request, session_id=self.session_id)).encode())
                if not connection.poll(2 if request.get('action') == 'ping' else 600):
                    raise ProofInvalid('Proof service response timeout')
                response = json.loads(connection.recv_bytes(16 * 1024 * 1024))
        except (OSError, EOFError) as exc:
            raise ProofInvalid('Proof session is unavailable') from exc
        if response.get('session_id') != self.session_id or response.get('ok') is not True:
            raise ProofInvalid(response.get('error', 'Proof service rejected the request'))
        return response.get('result')

    def check(self):
        return self.request(dict(action='ping'))

    def use(self, name, arguments, validate):
        return self.request(dict(action='validate', name=name, arguments=arguments))


@contextmanager
def bind(session):
    token = _CURRENT.set(session)
    try:
        yield session
    finally:
        _CURRENT.reset(token)


@contextmanager
def connected_session(reference):
    client = Client(reference)
    token = _CURRENT.set(client)
    try:
        yield client
    finally:
        _CURRENT.reset(token)


def current_reference():
    session = _CURRENT.get()
    return str(session.path) if isinstance(session, Client) else None


def require_alive():
    session = _CURRENT.get()
    if session is not None:
        session.check()


def serve(reference, owner_pid, seconds):
    """One owner-bound process, no automatic campaign execution or disk proof cache."""
    from multiprocessing.connection import Listener
    from research.campaign_launcher import observer_exited
    # Load the finite read-only operation graph before capturing evidence reads.
    from research import acquisition_readiness, acquisition_sharing, campaign_recovery
    if os.name != 'nt' or type(owner_pid) is not int or owner_pid <= 0 or owner_pid == os.getpid():
        raise ProofInvalid('A distinct live Windows session owner is required')
    if observer_exited(owner_pid, timeout=0):
        raise ProofInvalid('Proof session owner has already exited')
    path = Path(reference).resolve()
    if path.exists():
        raise FileExistsError('Never replace a session reference')
    identity = uuid.uuid4().hex
    address = '\\\\.\\pipe\\sample2-proof-' + identity
    key = os.urandom(32)
    # Hold the process object, so PID reuse cannot revive a dead owner.
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE,wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    owner_handle = kernel.OpenProcess(0x100000, False, owner_pid)
    if not owner_handle:
        raise ProofInvalid('Cannot bind live proof owner')
    alive = lambda: kernel.WaitForSingleObject(owner_handle,0) == 258
    source_root = Path(__file__).resolve().parents[1]
    source_guard = WindowsGuard()
    source_inventory = {}
    for directory in ('research','outer/harness'):
        for file in sorted((source_root/directory).glob('*.py')):
            source_guard.read(file)
            source_inventory[file.relative_to(source_root).as_posix()] = hashlib.sha256(file.read_bytes()).hexdigest()
    with local_session(seconds, owner_alive=alive) as session:
        with Listener(address, family='AF_PIPE', authkey=key) as listener:
            record = dict(kind='bounded_readonly_proof_session_v1', session_id=identity,
                address=address, authkey=key.hex(), source_root=str(source_root), source_inventory=source_inventory, owner_pid=owner_pid, service_pid=os.getpid(),
                expires_unix=time.time() + seconds, source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('x', encoding='utf-8') as stream:
                json.dump(record, stream, indent=2)
            # Process exit closes all kernel guards even if a client is disconnected.
            def watchdog():
                while not session.closed:
                    if time.monotonic() >= session.deadline or not alive():
                        os._exit(2)
                    time.sleep(.25)
            threading.Thread(target=watchdog, daemon=True).start()
            requests = queue.Queue(maxsize=32)
            def proof_worker():
                # Windows directory notifications belong to their creating
                # thread. Keep that thread alive across client connections.
                _CURRENT.set(session)
                while not session.closed:
                    name, arguments, future = requests.get()
                    try:
                        source_guard.check()
                        result = session.use(name,arguments,lambda:dispatch(name,arguments))
                    except BaseException as exc:
                        future.set_exception(exc)
                    else:
                        future.set_result(result)
            threading.Thread(target=proof_worker,daemon=True).start()
            def handle(connection):
                token = _CURRENT.set(session)
                with connection:
                    try:
                        request = json.loads(connection.recv_bytes(16 * 1024 * 1024))
                        if request.get('session_id') != identity:
                            raise ProofInvalid('Foreign proof session')
                        session.check()
                        source_guard.check()
                        action = request.get('action')
                        if action == 'stop':
                            connection.send_bytes(canonical(dict(ok=True, session_id=identity, result='closed')).encode())
                            session.close()
                            os._exit(0)
                        if action == 'ping':
                            # No cached liveness: all guards remain live at every ping.
                            for entry in list(session.entries.values()):
                                entry.guard.check()
                            result = dict(stats=session.stats, entries=len(session.entries))
                        elif action == 'validate':
                            name, arguments = request['name'], request['arguments']
                            future = Future()
                            requests.put((name,arguments,future),timeout=2)
                            result = future.result(timeout=600)
                        else:
                            raise ProofInvalid('Unknown proof session action')
                        response = dict(ok=True, session_id=identity, result=result)
                    except BaseException as exc:
                        session.close()
                        response = dict(ok=False, session_id=identity, error=type(exc).__name__ + ': ' + str(exc))
                    try:
                        connection.send_bytes(canonical(response).encode())
                    finally:
                        if session.closed:
                            os._exit(2)

                _CURRENT.reset(token)
            while True:
                connection = listener.accept()
                threading.Thread(target=handle,args=(connection,),daemon=True).start()


@contextmanager
def cli_session():
    """Consume one explicit option before a production CLI parses its arguments."""
    if '--proof-session' not in sys.argv:
        yield None
        return
    index = sys.argv.index('--proof-session')
    if index + 1 >= len(sys.argv) or sys.argv.count('--proof-session') != 1:
        raise ProofInvalid('Exactly one proof session reference is required')
    reference = sys.argv[index + 1]
    del sys.argv[index:index + 2]
    with connected_session(reference) as client:
        yield client


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('serve', 'check', 'stop'))
    parser.add_argument('reference', type=Path)
    parser.add_argument('--owner-pid', type=int)
    parser.add_argument('--seconds', type=int, default=4*3600)
    args = parser.parse_args()
    if args.action == 'serve':
        return serve(args.reference, args.owner_pid, args.seconds)
    client = Client(args.reference)
    return client.request(dict(action='stop')) if args.action == 'stop' else client.check()


if __name__ == '__main__':
    print(canonical(main()))
