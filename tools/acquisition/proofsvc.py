"""Fresh cold proof service helper (no validator patching)."""
from contextlib import contextmanager
from pathlib import Path
import os, subprocess, sys, time

W = Path(r'C:\Users\mwam0\Documents\Codex\2026-10-07\task')
R = Path(r'C:\Users\mwam0\Documents\Codex\2026-10-06\task')

def next_index(start=16):
    i = start
    while (W/f'private-proof-reference-{i:02d}.json').exists() or (W/f'proof-service-{i:02d}.log').exists() \
            or list(W.glob(f'expired-*-private-proof-reference-{i:02d}.json')):
        i += 1
    return i

def safe_dirs():
    added = []
    for name in ['pm26-code', 'pm26-code-v2', 'pm26-code-v3', 'pm26-code-v4', 'pm26-code-v5']:
        path = (R/name).as_posix()
        old = subprocess.run(['git','config','--global','--get-all','safe.directory'],capture_output=True,text=True).stdout.splitlines()
        if path not in old:
            subprocess.run(['git','config','--global','--add','safe.directory',path],check=True); added.append(path)
    return added

def unsafe_dirs(added):
    for path in reversed(added):
        subprocess.run(['git','config','--global','--fixed-value','--unset-all','safe.directory',path],check=True)

@contextmanager
def session(repo, event=print, seconds=14400):
    from research import proof_session
    idx = next_index()
    ref = W/f'private-proof-reference-{idx:02d}.json'
    log = W/f'proof-service-{idx:02d}.log'
    svc = None
    try:
        with log.open('x', encoding='utf-8') as out:
            svc = subprocess.Popen([sys.executable,'-B','-X','utf8','-m','research.proof_session','serve',str(ref),
                '--owner-pid',str(os.getpid()),'--seconds',str(seconds)],cwd=repo,stdout=out,stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW)
            for _ in range(300):
                if ref.exists(): break
                if svc.poll() is not None: raise RuntimeError('Proof service exited before reference')
                time.sleep(0.1)
            event('proof_started', index=idx, ref=str(ref))
            with proof_session.connected_session(ref) as client:
                client.check()
                yield ref, client
    finally:
        if svc is not None:
            if svc.poll() is None and ref.exists():
                try: proof_session.Client(ref).request(dict(action='stop'))
                except Exception as exc: event('proof_stop_error', error=str(exc))
            try: svc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                svc.terminate(); svc.wait(timeout=15)
            event('proof_exited', index=idx, exit_code=svc.returncode)
