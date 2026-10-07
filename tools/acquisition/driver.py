"""Detached continuous driver (user direction 2026-10-07 14:13 JST): runs owned waves back to back on the
current successor (S2_SUMMARY, default succession-v7.json) via the proven per-wave owner owned_wave.py
(reserve -> launch 4 runs / 2 pairs -> owned close or sanctioned recovery under the confirmed no-send
rule -> post-close check -> resource release check -> campaign-status.json; fresh proof session per phase).
Pairs: replacement_eligible slots first (new attempt IDs, after their backoff), then the next initial slots.
Stops only on a real blocker: held/unknown send status, budget bounds, unhandled owner exception after
reservation, or 100 accepted. Low quality is never a stop or discard reason. No publication.
Usage: driver_continuous.py [--selftest] [--adopt-chain PID]"""
from pathlib import Path
import os, sys, json, datetime, subprocess, time, re
W = Path(r'C:\Users\mwam0\Documents\Codex\2026-10-07\task'); PY = r'C:\Python314\python.exe'
sys.path.insert(0, str(Path(__file__).resolve().parent))
import procalive
LOG = W/'driver-continuous-events.jsonl'
SUMMARY = os.environ.get('S2_SUMMARY', 'succession-v10.json')
OWNER = Path(__file__).resolve().parent/'owner.py'
PRE_RESERVE_RETRIES = 3

def now(): return datetime.datetime.now(datetime.timezone.utc)
def event(kind, **kw):
    row = dict(at=now().isoformat(), kind=kind, **kw)
    with LOG.open('a', encoding='utf-8') as f: f.write(json.dumps(row, default=str)+'\n')
def rows(path):
    path = Path(path)
    if not path.exists(): return []
    out = []
    for line in path.read_text(encoding='utf-8').splitlines():
        if line.strip():
            try: out.append(json.loads(line))
            except ValueError: pass
    return out

def next_label(directory=W):
    used = {int(m.group(1)) for p in Path(directory).glob('wave*-launch.log') if (m := re.fullmatch(r'wave(\d+)-launch\.log', p.name))}
    used |= {int(m.group(1)) for p in Path(directory).glob('wave*-events.jsonl') if (m := re.fullmatch(r'wave(\d+)-events\.jsonl', p.name))}
    return 'wave%02d' % (max(used, default=0)+1)

def not_before_map(attempt_rows):
    out = {}
    for e in attempt_rows:
        if e.get('kind') == 'pair_recovery_decision' and e.get('not_before'):
            out[e['slot']] = e['not_before']
    return out

def choose(status, attempt_rows):
    """Return (pairs, wait_until_iso or None, blocker or None)."""
    if status['accepted_count'] >= 100: return [], None, 'complete_100_accepted'
    unresolved = {int(k): v for k, v in status.get('unresolved_slots', {}).items()}
    held = sorted(n for n, d in unresolved.items() if d != 'replacement_eligible')
    if held: return [], None, 'held_or_unknown_send_slots:'+','.join(map(str, held))
    eligible = sorted(n for n, d in unresolved.items() if d == 'replacement_eligible')
    pairs = eligible[:2]
    nxt = status.get('next_initial_slot')
    while len(pairs) < 2 and nxt is not None and nxt <= 100:
        pairs.append(nxt); nxt += 1
    if not pairs: return [], None, 'no_pending_slots'
    nb = not_before_map(attempt_rows)
    waits = [nb[n] for n in pairs if n in eligible and n in nb]
    return pairs, (max(waits) if waits else None), None

def budget_blocker(status, pairs):
    u, b = status['usage'], status['bounds']
    if u['requests'] >= b['request_count']: return 'request_budget_exhausted'
    if u['observed_tokens'] >= b['observed_tokens']: return 'token_budget_exhausted'
    if u['accumulated_run_seconds'] >= b['accumulated_run_seconds']: return 'run_seconds_budget_exhausted'
    if status['reserved_pair_attempts'] + len(pairs) > b['max_pair_attempts']: return 'pair_attempt_budget_exhausted'
    return None

def wave_outcome(events):
    kinds = [e['kind'] for e in events]
    err = [e for e in events if e['kind'] == 'owner_error']
    return dict(reserved='wave_reserved' in kinds, finished='owner_finished' in kinds, error=err[-1]['error'] if err else None,
                status=next((e for e in reversed(events) if e['kind'] == 'status'), None),
                release=next((e for e in reversed(events) if e['kind'] == 'resource_release_check'), None))

def merge_status(**kw):
    p = W/'campaign-status.json'
    s = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
    s.setdefault('driver', {}).update(kw); s['driver']['updated_at'] = now().isoformat()
    t = W/'campaign-status.json.driver.tmp'; t.write_bytes(json.dumps(s, indent=1).encode()); t.replace(p)
    return s

def selftest():
    import tempfile
    st = dict(accepted_count=7, unresolved_slots={'8': 'replacement_eligible'}, next_initial_slot=10,
              usage=dict(requests=10, observed_tokens=10, accumulated_run_seconds=10), reserved_pair_attempts=12,
              bounds=dict(request_count=100, observed_tokens=100, accumulated_run_seconds=100, max_pair_attempts=200))
    att = [dict(kind='pair_recovery_decision', slot=8, not_before='2026-01-01T00:00:00+00:00'),
           dict(kind='pair_recovery_decision', slot=8, not_before='2026-01-02T00:00:00+00:00')]
    assert choose(st, att) == ([8, 10], '2026-01-02T00:00:00+00:00', None), choose(st, att)
    assert choose(dict(st, unresolved_slots={}), [])[0:3] == ([10, 11], None, None)
    assert choose(dict(st, unresolved_slots={'8': 'held'}), [])[2].startswith('held_or_unknown')
    assert choose(dict(st, unresolved_slots={'8': 'replacement_eligible', '9': 'replacement_eligible', '3': 'replacement_eligible'}), [])[0] == [3, 8]
    assert choose(dict(st, unresolved_slots={}, next_initial_slot=100), [])[0] == [100]
    assert choose(dict(st, unresolved_slots={}, next_initial_slot=None), [])[2] == 'no_pending_slots'
    assert choose(dict(st, accepted_count=100), [])[2] == 'complete_100_accepted'
    assert budget_blocker(st, [1, 2]) is None
    assert budget_blocker(dict(st, usage=dict(requests=100, observed_tokens=1, accumulated_run_seconds=1)), [1]) == 'request_budget_exhausted'
    assert budget_blocker(dict(st, reserved_pair_attempts=199), [1, 2]) == 'pair_attempt_budget_exhausted'
    with tempfile.TemporaryDirectory() as d:
        assert next_label(d) == 'wave01'
        (Path(d)/'wave04-launch.log').write_text('x'); (Path(d)/'wave05-events.jsonl').write_text('')
        assert next_label(d) == 'wave06'
    ev = [dict(kind='owner_started'), dict(kind='wave_reserved'), dict(kind='status', accepted=7), dict(kind='owner_finished')]
    o = wave_outcome(ev); assert o['reserved'] and o['finished'] and o['error'] is None and o['status']['accepted'] == 7
    o = wave_outcome([dict(kind='owner_error', error='X'), dict(kind='owner_finished')]); assert not o['reserved'] and o['error'] == 'X'
    assert procalive.alive(os.getpid()) and not procalive.alive(4999999)
    print('driver selftest OK')

def current_status():
    return json.loads((W/'campaign-status.json').read_text(encoding='utf-8'))

def run_wave(label, pairs, resume=None):
    env = dict(os.environ, S2_SUMMARY=SUMMARY)
    s = json.loads((W/SUMMARY).read_text(encoding='utf-8'))
    with (W/(label+'-owner.out.log')).open('ab') as out:
        p = subprocess.Popen([PY, '-B', '-X', 'utf8', str(OWNER), label, *(['--resume', str(resume)] if resume else map(str, pairs))], stdout=out,
                             stderr=subprocess.STDOUT, cwd=s.get('repo'), env=env, creationflags=0x08000000)
    event('wave_started', label=label, pairs=pairs, pid=p.pid)
    merge_status(state='wave_running', label=label, pairs=pairs, owner_pid=p.pid, driver_pid=os.getpid())
    while p.poll() is None:
        heartbeat = dict(at=now().isoformat(), driver_pid=os.getpid(), owner_pid=p.pid, label=label, pairs=pairs, state='running')
        target = W/'acquisition-heartbeat.json'
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(heartbeat), encoding='utf-8'); temporary.replace(target)
        try: p.wait(timeout=20)
        except subprocess.TimeoutExpired: pass
    rc = p.returncode
    out = wave_outcome(rows(W/(label+'-events.jsonl')))
    event('wave_exited', label=label, rc=rc, **{k: v for k, v in out.items() if k != 'status'}, status=out['status'])
    return rc, out

def stop(reason, **kw):
    event('driver_stopped', reason=reason, **kw)
    merge_status(state='stopped', stop_reason=reason, owner_pid=None, **kw)
    sys.exit(0 if reason == 'complete_100_accepted' else 2)

def main():
    args = sys.argv[1:]
    if '--selftest' in args: selftest(); return
    event('driver_started', pid=os.getpid(), summary=SUMMARY)
    merge_status(state='starting', driver_pid=os.getpid(), log=str(LOG))
    if '--adopt-chain' in args:
        chain = int(args[args.index('--adopt-chain')+1])
        merge_status(state='adopting_chain', chain_pid=chain)
        while procalive.alive(chain): time.sleep(20)
        ch = rows(W/os.environ.get('S2_CHAIN_EVENTS', 'chain-v7d-events.jsonl'))
        if any(e['kind'] in ('blocker', 'error') for e in ch) or not any(e['kind'] == 'wave04_exited' for e in ch):
            stop('adopted_chain_did_not_finish_wave04', chain_tail=ch[-3:])
        out = wave_outcome(rows(W/'wave04-events.jsonl'))
        event('adopted_wave04', **{k: v for k, v in out.items() if k != 'status'}, status=out['status'])
        if out['error'] or not out['status']: stop('wave04_owner_error', error=out['error'])
    summary = json.loads((W/SUMMARY).read_text(encoding='utf-8'))
    recorded = rows(Path(summary['batch'])/'attempts.jsonl')
    for spec in sorted((Path(summary['batch'])/'waves').glob('*/spec.json')):
        matching = [e for e in recorded if e.get('wave', {}).get('path') == str(spec)]
        reserved = {e['slot'] for e in matching if e['kind']=='pair_attempt_reserved'}
        finished = {e['slot'] for e in matching if e['kind'] in ('pair_accepted', 'pair_recovery_decision')}
        if not (spec.parent/'closure.json').exists() or not reserved <= finished:
            rc, out = run_wave(next_label(), [], resume=spec)
            if rc or out['error']: stop('saved_wave_recovery_failed', wave=str(spec), error=out['error'])
    refresh = subprocess.run([PY, '-B', '-X', 'utf8', str(OWNER), '--status'], cwd=summary['repo'],
        env=dict(os.environ, S2_SUMMARY=SUMMARY), stdout=subprocess.DEVNULL)
    if refresh.returncode: stop('ledger_refresh_failed', rc=refresh.returncode)
    retries = 0
    while True:
        summary = json.loads((W/SUMMARY).read_text(encoding='utf-8'))
        st = current_status()
        if st.get('plan', {}).get('sha256') != summary['plan']['sha256']:
            stop('status_not_from_current_successor', status_plan=st.get('plan'))
        attempt_rows = rows(Path(summary['batch'])/'attempts.jsonl')
        pairs, wait_until, blocker = choose(st, attempt_rows)
        if blocker: stop(blocker, accepted=st['accepted_count'], usage=st['usage'])
        b = budget_blocker(st, pairs)
        if b: stop(b, accepted=st['accepted_count'], usage=st['usage'])
        if wait_until:
            t = datetime.datetime.fromisoformat(wait_until.replace('Z', '+00:00')) + datetime.timedelta(seconds=5)
            if now() < t:
                event('backoff_wait', until=t.isoformat(), pairs=pairs); merge_status(state='backoff_wait', until=t.isoformat(), pairs=pairs)
                while now() < t: time.sleep(10)
        label = next_label()
        rc, out = run_wave(label, pairs)
        if out['error'] or rc != 0 or not out['status']:
            if not out['reserved'] and retries < PRE_RESERVE_RETRIES:
                retries += 1; event('pre_reservation_retry', label=label, attempt=retries, error=out['error'])
                time.sleep(90); continue
            if out['reserved']:
                ev = rows(W/(label+'-events.jsonl'))
                wave = next(e['wave'] for e in reversed(ev) if e['kind']=='wave_reserved')
                event('resume_saved_wave', wave=wave, prior_error=out['error'])
                resume_rc, resumed = run_wave(next_label(), pairs, resume=wave)
                if resume_rc == 0 and resumed['status'] and not resumed['error']:
                    retries = 0; continue
            stop('owner_exception', label=label, error=out['error'], rc=rc, reserved=out['reserved'])
        retries = 0
        st = current_status()
        merge_status(state='wave_closed', last_label=label, last_pairs=pairs, accepted=st['accepted_count'],
                     usage=st['usage'], resource_release=(out['release'] or {}))

if __name__ == '__main__':
    try: main()
    except SystemExit: raise
    except Exception as exc:
        event('driver_error', error=type(exc).__name__+': '+str(exc)); merge_status(state='stopped', stop_reason='driver_exception: '+str(exc)); raise
