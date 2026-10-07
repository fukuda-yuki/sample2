"""C: one owned wave of the v6 successor (2 pairs / 4 runs). No publication.

reserve_wave -> campaign_launcher launch -> owned close_wave (or, on STOP/fault or
invalid observations, sanctioned same-attempt recover_wave + owned close_recovery +
reconcile_recovery) -> resource-release check -> W/campaign-status.json.
Usage: owned_wave.py LABEL PAIR [PAIR]
"""
from pathlib import Path
import os, sys, json, datetime, traceback, subprocess, time
R = Path(r'C:\Users\mwam0\Documents\Codex\2026-10-06\task')
W = Path(r'C:\Users\mwam0\Documents\Codex\2026-10-07\task')
# Campaign summary (plan + pinned checkout); env S2_SUMMARY selects the successor (default v6, historical).
summary_path = W/os.environ.get('S2_SUMMARY', 'succession-v6.json')
_S = json.loads(summary_path.read_text(encoding='utf-8'))
repo = Path(_S.get('repo', str(R/'pm26-code-v5')))
sys.path.insert(0, str(repo)); sys.path.insert(0, str(Path(__file__).resolve().parent)); os.chdir(repo)
from research import repaired_campaign as campaign, campaign_recovery, campaign_launcher, live_pilot
from outer.harness import util, runtime
import proofsvc

refresh_only = sys.argv[1] == '--status'
label = 'status' if refresh_only else sys.argv[1]
resume_wave = Path(sys.argv[3]) if not refresh_only and sys.argv[2] == '--resume' else None
pairs = [] if refresh_only or resume_wave else [int(x) for x in sys.argv[2:]]
assert refresh_only or (label.startswith('wave') and (resume_wave or 1 <= len(pairs) <= 2))
S = util.read_json(summary_path)
P = Path(S['plan']['path']); PLAN_SHA = S['plan']['sha256']
log = W/f'{label}-events.jsonl'; launch_log = W/f'{label}-launch.log'
RECOVERY_ROOT = Path(r'C:\s2r')

def event(kind, **kw):
    row = dict(at=datetime.datetime.now(datetime.timezone.utc).isoformat(), kind=kind, **kw)
    with log.open('a', encoding='utf-8') as f: f.write(json.dumps(row, default=str)+'\n')
    print(json.dumps(row, default=str), flush=True)

def git(*args):
    return subprocess.check_output(['git', *args], cwd=repo, text=True).strip()

def docker_owned():
    rows = [json.loads(l) for l in runtime.docker('ps', '-a', '--no-trunc', '--format', '{{json .}}', timeout=30).stdout.splitlines() if l.strip()]
    nets = [json.loads(l) for l in runtime.docker('network', 'ls', '--no-trunc', '--format', '{{json .}}', timeout=30).stdout.splitlines() if l.strip()]
    return dict(containers=sorted(r['Names'] for r in rows if r.get('Names', '').startswith(('s2-score-', 's2-browser-'))),
                running_s2=sorted(r['Names'] for r in rows if r.get('Names', '').startswith('s2-') and r.get('State') == 'running'),
                networks=sorted(n['Name'] for n in nets if n.get('Name', '').startswith('s2-browser-')))

def observers_exited(epoch):
    pending = []
    for startup in (Path(epoch['batch'])/'_observers').glob('*/startup-ready.json'):
        pid = util.read_json(startup).get('observer_pid')
        if not campaign_launcher.observer_exited(pid, timeout=0): pending.append(pid)
    return pending

def recover(wave, reason):
    dest = RECOVERY_ROOT/(label[4:]+'r'+str(len(list(RECOVERY_ROOT.glob(label[4:]+'r*')))))
    event('recovery_started', reason=reason, destination=str(dest))
    t = time.monotonic()
    rec = campaign_recovery.recover_wave(repo, P, wave, dest)
    closure = campaign_recovery.close_recovery(repo, P, wave, rec, None,
        owned_authority=dict(repo=str(repo), plan=live_pilot.reference(P)))
    out = campaign.reconcile_recovery(repo, P, wave, closure)
    value = util.read_json(live_pilot.checked(closure))
    event('recovery_reconciled', result=out, decisions={n: d['disposition'] for n, d in value['decisions'].items()},
          retry_not_before=value['retry_not_before'], seconds=round(time.monotonic()-t, 1))
    return out

def status(p, extra):
    events = campaign.ledger(p)
    accepted = sorted(e['slot'] for e in events if e['kind'] == 'pair_accepted')
    reserved = [e for e in events if e['kind'] == 'pair_attempt_reserved']
    latest = {}
    for e in events:
        if e['kind'] == 'pair_recovery_decision': latest[e['slot']] = e['decision']['disposition']
    pending = sorted(n for n, d in latest.items() if n not in accepted)
    usage = campaign.observed_usage(p)
    value = dict(kind='campaign_status', at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        plan=live_pilot.reference(P), source_commit=p['source_commit'], policy=p['policy']['next_wave_requires'],
        initial_logical_denominator=100, accepted_count=len(accepted), accepted_slots=accepted,
        reserved_pair_attempts=len(reserved), unresolved_slots={str(n): latest[n] for n in pending},
        next_initial_slot=next((n for n in range(1, 101) if n not in {e['slot'] for e in reserved}), None),
        usage=usage,
        bounds=dict(request_count=p['bounds']['request_count'], observed_tokens=p['bounds']['observed_tokens'],
                    accumulated_run_seconds=p['bounds']['accumulated_run_seconds'], max_pair_attempts=p['bounds']['max_pair_attempts']),
        settings=p['settings'], last_wave=extra)
    tmp = W/'campaign-status.json.tmp'; tmp.write_text(json.dumps(value, indent=1), encoding='utf-8')
    for attempt in range(20):
        try:
            os.replace(tmp, W/'campaign-status.json'); break
        except PermissionError:
            if attempt == 19: raise
            time.sleep(0.1)
    return value

added = proofsvc.safe_dirs()
result = dict(label=label, pairs=pairs)
try:
    assert util.sha256_file(P) == PLAN_SHA
    p0 = util.read_json(P)
    assert git('rev-parse', 'HEAD') == p0['source_commit'] and git('status', '--porcelain') == ''
    assert p0['settings'] == dict(p0['settings'], model_id='deepseek-v4.1-flash', provider='opencode-go', use_balance=False, paid_fallback=False)
    assert p0['bounds']['active_pairs'] == 2 and p0['bounds']['active_runs'] == 4
    if refresh_only:
        with proofsvc.session(repo, event):
            st = status(campaign.validate(repo, P), dict(action='ledger_refresh'))
            event('status', accepted=st['accepted_count'], unresolved=st['unresolved_slots'], usage=st['usage'])
    else:
        assert os.environ.get('OPENCODE_GO_API_KEY'), 'provider key missing'
        event('owner_started', pid=os.getpid(), pairs=pairs, resume=str(resume_wave) if resume_wave else None)
        pre = docker_owned()
        event('preflight_resources', **pre)
        assert not pre['containers'] and not pre['networks'] and not pre['running_s2'], 'owned resources not released'
        if resume_wave:
            wave = resume_wave
            w = util.read_json(wave); ep = w['epoch_plan']; pairs = w['pairs']
            result.update(pairs=pairs, wave=str(wave), resuming_saved_wave=True)
            launch = util.read_json(wave.parent/'_launcher/result.json')
        else:
            assert not launch_log.exists(), 'label already used'
            # A repeated logical slot gets fresh UUIDs, without a new campaign/code revision.
            with proofsvc.session(repo, event):
                p = campaign.validate(repo, P)
                epochs = sorted((Path(p['batch'])/'epochs').glob('*/plan.json'))
                ep = live_pilot.reference(epochs[-1])
                if any(e['kind']=='pair_attempt_reserved' and e['slot'] in pairs and e['epoch_plan']==ep for e in campaign.ledger(p)):
                    ep = campaign.epoch(repo, P)
                    event('retry_epoch_created', epoch=ep)
            with proofsvc.session(repo, event) as (ref, client):
                wave = campaign.reserve_wave(repo, P, ep, pairs)
                event('wave_reserved', wave=str(wave), epoch=ep)
                with launch_log.open('x', encoding='utf-8') as out:
                    proc = subprocess.run([sys.executable, '-B', '-X', 'utf8', '-m', 'research.campaign_launcher', 'launch', str(P),
                        '--repo', str(repo), '--wave', str(wave), '--proof-session', str(ref)], cwd=repo, stdout=out, stderr=subprocess.STDOUT)
                launch = util.read_json(Path(wave).parent/'_launcher/result.json')
                event('launch_returned', exit_code=proc.returncode, operational_complete=launch.get('operational_complete'),
                    owned_closure_confirmed=launch.get('owned_closure_confirmed'), reason=launch.get('reason'))
                result.update(wave=str(wave), launch_exit=proc.returncode, operational_complete=launch.get('operational_complete'))
        with proofsvc.session(repo, event):
            existing = Path(wave).parent/'closure.json'
            saved = util.read_json(existing) if existing.exists() else {}
            if saved.get('recovery'):
                result['recovery'] = campaign.reconcile_recovery(repo, P, wave, saved['recovery'])
            elif launch.get('operational_complete') is True:
                closure = campaign.close_wave(repo, P, wave)
                event('owned_wave_closed', observations={n:{c:o['classification'] for c,o in arms.items()} for n,arms in closure['observations'].items()})
            elif launch.get('owned_closure_confirmed') is True:
                result['recovery'] = recover(wave, 'launcher did not complete acquisition')
            else:
                raise RuntimeError('Owned processes must be reconciled before further acquisition')
        with proofsvc.session(repo, event):
            p = campaign.validate(repo, P); wref = live_pilot.reference(wave)
            accepted = {e['slot'] for e in campaign.ledger(p) if e['kind']=='pair_accepted'}
            preserved = [e['slot'] for e in campaign.ledger(p) if e['kind']=='pair_preserved_requires_assessment' and e.get('wave')==wref and e['slot'] not in accepted]
            if preserved: result['recovery'] = recover(wave, 'saved results require technical recovery: '+str(preserved))
        with proofsvc.session(repo, event):
            post = docker_owned(); pending_obs = observers_exited(util.read_json(live_pilot.checked(ep)))
            event('resource_release_check', **post, observers_pending=pending_obs)
            result['resource_release'] = dict(**post, observers_pending=pending_obs,
                released=not post['containers'] and not post['networks'] and not post['running_s2'] and not pending_obs)
            if not result['resource_release']['released']: raise RuntimeError('Owned resources not released')
            st = status(campaign.validate(repo, P), result)
            event('status', accepted=st['accepted_count'], unresolved=st['unresolved_slots'], usage=st['usage'], next_initial=st['next_initial_slot'])
except Exception as exc:
    event('owner_error', error=type(exc).__name__+': '+str(exc)); traceback.print_exc(); raise
finally:
    proofsvc.unsafe_dirs(added)
    event('owner_finished')
