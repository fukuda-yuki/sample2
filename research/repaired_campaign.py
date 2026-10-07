"""Central bounded orchestration over unchanged repaired-main pair primitives.

The campaign fixes logical slots; child plans fix acquisition UUIDs. Reservations
are not transmissions. Faulted originals and initial-slot denominators survive
all administrative epochs and saved-artifact assessments.
"""
import argparse
import copy
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import threading
import time
import traceback
import uuid

from outer.harness import live_usage, run, util
from research import acquisition_readiness as readiness, live_pilot, pair_execution
from research.validation_scope import scoped_validation

KIND = 'repaired_parallel_logical100_campaign_v1'
BASE_SHA = '3e0c459138ff9bc1b9d3fd676347239ba343f65876cbeb44835097bedae1ccfe'
BOUNDS = dict(max_pair_attempts=300, max_run_attempts=600, active_pairs=2,
    active_runs=4, http_inflight_max=4, request_count=90000,
    observed_tokens=4500000000, accumulated_run_seconds=1080000,
    wall_seconds=1350000, wave_wall_seconds=7200, retry_backoff_seconds=[60,300,900,3600],
    disk_free_min_bytes=8*1024**3)
EXTRA_PINS = ('research/repaired_campaign.py', 'research/campaign_launcher.py',
              'research/campaign_reassessment.py','research/campaign_recovery.py')
# Historical campaigns admitted the next wave only after an actual public
# Release round trip. The owned policy (explicit user decision, 2026-10-07)
# admits it after owned acquisition, evaluation, local archive and verified
# resource release. Every other research rule is unchanged.
LEGACY_NEXT_WAVE = 'actual_publication_restore_cleanup_and_owned_closure'
OWNED_NEXT_WAVE = 'owned_acquisition_evaluation_archive_and_resource_release_closure'
OWNED_CLOSURE_KIND = 'owned_operational_closure_v1'
OWNED_PAIR_KIND = 'owned_pair_completion_receipt_v1'
PREDECESSOR_RECOVERY_KIND = 'successor_predecessor_wave_recovery_v1'
OBSERVER_READ_RETRIES = 5


def document(ref):
    return util.read_json(live_pilot.checked(ref))


def logical(pair):
    value = copy.deepcopy(pair)
    for case in value['cases']:
        for key in ('run_id','run_instance_id','attempt'):
            case.pop(key, None)
    return value


@scoped_validation
def validate(repo, path):
    repo, path = live_pilot.safe_path(repo), live_pilot.safe_path(path)
    p = util.read_json(path)
    if p.get('kind') != KIND or p.get('schema_version') != 1 or p.get('bounds') != BOUNDS:
        raise ValueError('Explicit finite campaign version required')
    if p.get('base_plan',{}).get('sha256') != BASE_SHA:
        raise ValueError('Wrong immutable design baseline')
    base = document(p['base_plan'])
    if p.get('slots') != [logical(x) for x in base['assignments']]:
        raise ValueError('All 100 logical slots/order/strata must be preserved')
    if p.get('settings') != base['settings'] or len(p['slots']) != 100:
        raise ValueError('Fixed Go settings and 100 slots required')
    if not re.fullmatch('[a-f0-9]{32}',p.get('campaign_id','')):
        raise ValueError('New campaign identity required')
    if not re.fullmatch('[a-f0-9]{40}',p.get('source_commit','')):
        raise ValueError('Committed controller required')
    live_pilot.verify_pins(repo,p['source_pins'])
    if not set(EXTRA_PINS) <= p['source_pins'].keys():
        raise ValueError('All campaign controllers must be pinned')
    root = live_pilot.safe_path(p['batch'])
    for old in [repo,*map(live_pilot.safe_path,p['protected_roots'])]:
        if live_pilot.within(root,old) or live_pilot.within(old,root):
            raise ValueError('Campaign overlaps protected source/data')
    if p.get('policy') not in (policy(), legacy_policy()):
        raise ValueError('Research acquisition policy changed')
    if p.get('storage_policy')!='new_campaign_ntfs_compression_originals_retained':
        raise ValueError('Explicit bounded new-root storage policy required')
    if p.get('predecessor'):
        if 'research/campaign_transition.py' not in p['source_pins']:
            raise ValueError('Successor transition controller must be pinned')
        from research import campaign_transition
        campaign_transition.validate_predecessor(repo,p)
    return p


def policy(next_wave=OWNED_NEXT_WAVE):
    return dict(initial_denominator=100, quality_failure_is_valid=True,
        low_quality_replacement=False, ambiguous_send='reconcile_never_blind_resend',
        technical_failure='saved_same_version_assessment_before_whole_pair_replacement',
        cross_attempt_arm_composition=False, all_attempts_and_usage_retained=True,
        next_wave_requires=next_wave,
        balance=False, paid_fallback=False, purchases=False)


def legacy_policy():
    """Exact historical policy; retained plans keep validating unchanged."""
    return policy(LEGACY_NEXT_WAVE)


def owned_policy(p):
    return p.get('policy') == policy()


@scoped_validation
def validate_readiness(repo,path):
    p=validate(repo,path)
    base=document(p['base_plan'])
    source=live_pilot.safe_path(p['readiness_source_repo'])
    if live_pilot.checked(base['launch_supervisor'])!=source/'research/live_pilot_launcher.py':
        raise ValueError('Accepted readiness checkout binding changed')
    from research import proof_session
    return proof_session.use('readiness',dict(repo=str(source),plan=base),
        lambda: readiness.readiness_for_main(source,base))


@scoped_validation
def create(repo, path, base_path, batch, authorization):
    repo, path, batch = map(live_pilot.safe_path,(repo,path,batch))
    base_ref = live_pilot.reference(base_path)
    if base_ref['sha256'] != BASE_SHA: raise ValueError('Wrong baseline')
    base = document(base_ref)
    from research import next_phase, repaired_runtime
    if next_phase.git(repo,'status','--porcelain'): raise ValueError('Clean committed checkout required')
    names = set(base['source_pins']) | set(EXTRA_PINS) | {'research/validation_scope.py','research/proof_session.py'}
    pins = {name:util.sha256_file(repo/name) for name in sorted(names)}
    commit = next_phase.git(repo,'rev-parse','HEAD')
    repaired_runtime._committed_files(repo,commit,pins)
    p = dict(schema_version=1,kind=KIND,campaign_id=uuid.uuid4().hex,
        source_commit=commit,source_pins=pins,base_plan=base_ref,batch=str(batch),
        settings=base['settings'],bounds=BOUNDS,slots=[logical(x) for x in base['assignments']],
        storage_policy='new_campaign_ntfs_compression_originals_retained',
        readiness_source_repo=str(Path(base['launch_supervisor']['path']).parent.parent),
        policy=policy(),protected_roots=list(dict.fromkeys(base['protected_roots']+
            [str(Path(base['batch'])),str(Path(base_path).parent.parent.parent)])),
        authorization_reference=authorization,created_at=run.now())
    util.write_new_json(path,p)
    validate(repo,path)
    batch.mkdir(exist_ok=False)
    # Compression applies only to this newly created campaign directory; NTFS
    # inheritance gives both arms the same storage policy and retains all bytes.
    if os.name!='nt':raise ValueError('This frozen campaign requires Windows NTFS storage')
    import subprocess
    from outer.harness.security import child_environment
    subprocess.run(['compact.exe','/C',str(batch)],env=child_environment(),
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True,timeout=30)
    if not (batch.stat().st_file_attributes & 0x800):raise ValueError('New campaign directory compression unconfirmed')
    util.write_new_json(batch/'allocation.json',dict(campaign=live_pilot.reference(path),
        slots=100,actual_model_dispatches=0))
    util.write_new_json(batch/'authorization.json',dict(authorized=True,approved_by='user',
        authorization_reference=authorization,plan_sha256=util.sha256_file(path),
        scope='new_100_evaluable_logical_pairs_parallel_and_technical_recovery',
        source='delegated user instruction; no per-pair reconfirmation'))
    return p


def ledger(p):
    inherited=[]
    if p.get('predecessor'):
        from research import campaign_transition
        inherited=campaign_transition.history_events(p)
    return inherited+pair_execution.events(Path(p['batch'])/'attempts.jsonl')


def stop_markers(p):
    root=Path(p['batch'])/'_control'
    return ([root/'dispatch-stop.json'] if (root/'dispatch-stop.json').exists() else [])+list((root/'stop-events').glob('*.json'))


def campaign_stop_pending(p):
    """Old STOPs survive; only verified immutable closure can acknowledge them."""
    paths=stop_markers(p)
    if not paths:return False
    root=Path(p['batch']); acknowledged={}
    for file in (root/'_control/clearances').glob('*.json'):
        clearance=util.read_json(file)
        closure=document(clearance['wave_closure'])
        if closure.get('closed') is not True or clearance.get('kind')!='campaign_stop_clearance_v1':
            raise ValueError('Invalid campaign STOP clearance')
        campaign_ref=util.read_json(root/'allocation.json')['campaign']
        if clearance.get('campaign')!=campaign_ref:raise ValueError('Foreign STOP clearance')
        wave_path=live_pilot.checked(closure['wave'])
        # Recheck the actual retained transport and ownership proof, never a success flag alone.
        live_pilot.checked(closure['recovery'])
        from research import campaign_recovery
        campaign_recovery.validate_closure(Path(clearance['source_repo']),campaign_ref['path'],
            wave_path,closure['recovery'])
        acknowledged.update(clearance['stops'])
    return any(acknowledged.get(str(path))!=util.sha256_file(path) for path in paths)


@scoped_validation
def epoch(repo,path):
    """Freeze fresh UUIDs; only later explicit wave reservation permits execution."""
    p=validate(repo,path); base=copy.deepcopy(document(p['base_plan']))
    root=Path(p['batch']); number=1+len(list((root/'epochs').glob('*/plan.json')))
    directory=root/'epochs'/f'{number:03d}'; directory.mkdir(parents=True,exist_ok=False)
    base.update(phase_id=uuid.uuid4().hex,source_commit=p['source_commit'],source_pins=p['source_pins'],
        batch=str(directory/'data'),cohort=f'repaired-parallel100-{p["campaign_id"][:12]}/epoch-{number:03d}')
    base['launch_supervisor']=live_pilot.reference(Path(repo)/'research/live_pilot_launcher.py')
    for rid,ref in base['runtime_locks'].items():
        base['runtime_locks'][rid]=live_pilot.reference(Path(repo)/'artifacts/runtime'/Path(ref['path']).parent.name/'lock.json')
    base['protected_roots']=p['protected_roots']
    used={c['run_instance_id'] for q in document(p['base_plan'])['assignments'] for c in q['cases']}
    used.update(readiness.protected_instance_ids())
    if p.get('predecessor'):
        from research import campaign_transition
        used.update(campaign_transition.reserved_instance_ids(p))
    for previous in (root/'epochs').glob('*/plan.json'):
        used.update(c['run_instance_id'] for q in util.read_json(previous)['assignments'] for c in q['cases'])
    for pair in base['assignments']:
        for case in pair['cases']:
            identity=uuid.uuid4().hex
            if identity in used:raise ValueError('Fresh epoch UUID collision; no acquisition started')
            used.add(identity);case['run_instance_id']=identity
    base['campaign_authority']=live_pilot.reference(path)
    base['reservation_only_until_wave_intent']=True
    target=directory/'plan.json'; util.write_new_json(target,base)
    readiness.verify_main_phase(target,repo)
    readiness.create(repo,target)
    pair_execution.append(root/'epochs.jsonl',dict(kind='epoch_reserved',number=number,
        epoch_plan=live_pilot.reference(target),campaign_sha256=util.sha256_file(path),
        reserved_run_uuids=200,model_dispatches=0))
    return live_pilot.reference(target)


@scoped_validation
def wave_spec(repo,path,wave_path):
    p=validate(repo,path); wpath=live_pilot.safe_path(wave_path); w=util.read_json(wpath)
    if (w.get('campaign')!=live_pilot.reference(path) or wpath.name!='spec.json'
            or wpath.parent.parent != Path(p['batch'])/'waves'):
        raise ValueError('Foreign wave specification')
    child=readiness.verify_main_phase(live_pilot.checked(w['epoch_plan']),repo)
    if child.get('campaign_authority')!=live_pilot.reference(path): raise ValueError('Foreign epoch')
    if child['source_commit']!=p['source_commit'] or child['source_pins']!=p['source_pins']:
        raise ValueError('Epoch controller differs from frozen campaign')
    if (len(w.get('pairs',[])) not in (1,2) or len(set(w['pairs']))!=len(w['pairs'])
            or any(type(n) is not int or not 1<=n<=100 for n in w['pairs'])):
        raise ValueError('At most two fixed logical pairs required')
    for n in w['pairs']:
        if logical(child['assignments'][n-1])!=p['slots'][n-1]: raise ValueError('Changed slot assignment')
    if w.get('assignments')!=[child['assignments'][n-1] for n in w['pairs']]:
        raise ValueError('Wave UUIDs differ from epoch plan')
    return w


@scoped_validation
def reserve_wave(repo,path,epoch_ref,pairs):
    p=validate(repo,path)
    with pair_execution.exclusive(Path(p['batch'])/'_allocation'):
        return _reserve_wave(repo,path,epoch_ref,pairs)


def _reserve_wave(repo,path,epoch_ref,pairs):
    p=validate(repo,path); root=Path(p['batch']); events=ledger(p)
    if campaign_stop_pending(p): raise ValueError('Campaign STOP requires explicit reconciliation')
    prior=[e for e in events if e['kind']=='pair_attempt_reserved']
    if len(prior)+len(pairs)>BOUNDS['max_pair_attempts']: raise ValueError('Finite attempt budget exhausted')
    initial_slots={e['slot'] for e in prior}
    pending_initial=[n for n in range(1,101) if n not in initial_slots]
    new_initial=[n for n in pairs if n not in initial_slots]
    if new_initial!=pending_initial[:len(new_initial)]:raise ValueError('Initial fixed slot/task order changed')
    # Completed wave publication/cleanup receipts, not model quality, admit the next wave.
    for spec_path in sorted((root/'waves').glob('*/spec.json')):
        receipt=spec_path.parent/'closure.json'
        if not receipt.exists(): raise ValueError('Previous wave closure pending')
        verify_closure(repo,path,spec_path,receipt)
    child=readiness.verify_main_phase(live_pilot.checked(epoch_ref),repo)
    for n in pairs:
        if any(e['slot']==n for e in events if e['kind']=='pair_accepted'): raise ValueError('Slot already accepted')
        if any(e['slot']==n for e in prior):
            decisions=[e for e in events if e['kind']=='pair_recovery_decision' and e['slot']==n]
            if not decisions or decisions[-1]['decision']['disposition']!='replacement_eligible':
                raise ValueError('Replacement needs separately verified technical-fault/reassessment decision')
            decision=decisions[-1]
            saved=document(decision['closure'])
            from research import campaign_recovery
            if saved.get('kind')==PREDECESSOR_RECOVERY_KIND:
                verified=_verify_predecessor_recovery(repo,path,p,saved,decision['closure'])
            elif _inherited_decision(p,decision):
                verified=_verify_inherited_recovery(repo,p,saved,decision['closure'])
            else:
                verified=campaign_recovery.validate_closure(repo,path,live_pilot.checked(saved['wave']),saved['recovery'])
            if verified['decisions'][str(n)]!=decision['decision']:
                raise ValueError('Recovery decision differs from immutable verified closure')
            if datetime.now(timezone.utc)<datetime.fromisoformat(decision['not_before']):
                raise ValueError('Technical retry backoff has not elapsed')
            if any(e['epoch_plan']==epoch_ref for e in prior if e['slot']==n):
                raise ValueError('Replacement requires a fresh epoch with two fresh Run UUIDs')
        directory=Path(child['batch'])/f'pair-{n}'
        if (directory/'pair-invocation.json').exists() or pair_execution.events(directory/'_control/pair-journal.jsonl'):
            raise ValueError('Ambiguous or previously attempted UUIDs cannot be resent')
    wave_id=uuid.uuid4().hex; directory=root/'waves'/wave_id; directory.mkdir(parents=True,exist_ok=False)
    spec=dict(campaign=live_pilot.reference(path),epoch_plan=epoch_ref,pairs=pairs,
        assignments=[child['assignments'][n-1] for n in pairs],wave_id=wave_id,reserved_at=run.now(),
        wall_seconds=BOUNDS['wave_wall_seconds'])
    target=directory/'spec.json';util.write_new_json(target,spec)
    wave_spec(repo,path,target)
    for n in pairs:
        pair_execution.append(root/'attempts.jsonl',dict(kind='pair_attempt_reserved',slot=n,
            pair_attempt=1+sum(e['slot']==n for e in prior),epoch_plan=epoch_ref,wave=live_pilot.reference(target),
            run_instances={c['condition']:c['run_instance_id'] for c in child['assignments'][n-1]['cases']}))
    return target


@scoped_validation
def validate_admission(repo,path,wave_path):
    p=validate(repo,path);w=wave_spec(repo,path,wave_path);ref=live_pilot.reference(wave_path)
    reservations=[e for e in ledger(p) if e['kind']=='pair_attempt_reserved']
    if len(reservations)>p['bounds']['max_pair_attempts']:raise ValueError('Campaign attempt ceiling')
    selected=[e for e in reservations if e['wave']==ref]
    if len(selected)!=len(w['pairs']) or {e['slot'] for e in selected}!=set(w['pairs']):
        raise ValueError('Exactly one durable reservation per selected logical pair required')
    for item in selected:
        pair=next(q for q in w['assignments'] if q['pair']==item['slot'])
        if (item['epoch_plan']!=w['epoch_plan'] or item['run_instances']!=
                {c['condition']:c['run_instance_id'] for c in pair['cases']}):
            raise ValueError('Durable attempt reservation/UUID mismatch')
    for other in (Path(p['batch'])/'waves').glob('*/spec.json'):
        if other!=Path(wave_path):verify_closure(repo,path,other,other.parent/'closure.json')
    return True


@scoped_validation
def reconcile_reservation(repo,path,wave_path):
    """Complete a torn local reservation only after proving no launch/dispatch."""
    p=validate(repo,path);w=wave_spec(repo,path,wave_path);ref=live_pilot.reference(wave_path)
    root=Path(p['batch']);directory=Path(wave_path).parent;child=document(w['epoch_plan'])
    with pair_execution.exclusive(root/'_allocation'):
        if any((directory/name).exists() for name in ('_launcher','execution-intent.json','result.json')):
            raise ValueError('Launch uncertainty requires reconciliation, not reservation replay')
        for n in w['pairs']:
            batch=Path(child['batch'])/f'pair-{n}'
            if ((batch/'pair-invocation.json').exists() or
                    pair_execution.events(batch/'_control/pair-journal.jsonl')):
                raise ValueError('Attempted UUIDs cannot be replayed')
        events=ledger(p);prior=[e for e in events if e['kind']=='pair_attempt_reserved']
        for n in w['pairs']:
            selected=[e for e in prior if e['wave']==ref and e['slot']==n]
            ids={x['condition']:x['run_instance_id'] for x in child['assignments'][n-1]['cases']}
            if selected:
                if len(selected)!=1 or selected[0]['run_instances']!=ids:raise ValueError('Torn reservation identity conflict')
                continue
            if len(prior)>=BOUNDS['max_pair_attempts']:raise ValueError('Finite attempt budget exhausted')
            entry=dict(kind='pair_attempt_reserved',slot=n,pair_attempt=1+sum(e['slot']==n for e in prior),
                epoch_plan=w['epoch_plan'],wave=ref,run_instances=ids)
            pair_execution.append(root/'attempts.jsonl',entry);prior.append(entry)
    return validate_admission(repo,path,wave_path)


def observed_usage(p, exclude=()):
    counts=dict(requests=0,observed_tokens=0,accumulated_run_seconds=0.0,
                dispatched_runs=0,usage_journal_errors=[],missing_duration_runs=[])
    seen=set()
    for item in ledger(p):
        if item['kind']!='pair_attempt_reserved': continue
        child=document(item['epoch_plan']); pair=child['assignments'][item['slot']-1]
        batch=Path(child['batch'])/f'pair-{item["slot"]}'
        for case in pair['cases']:
            ident=case['run_instance_id']
            if ident in seen: raise ValueError('Duplicated reserved UUID')
            seen.add(ident)
            if ident in exclude: continue
            r=batch/case['run_id']
            for name in ('started','events'):
                rows,errors=live_usage.journal(r/f'usage/raw/{name}.jsonl')
                counts['usage_journal_errors'] += [dict(run_instance_id=ident,journal=name,error=str(e)) for e in errors]
                if name=='started': counts['requests']+=len(rows)
                else:
                    for row in rows:
                        usage=row.get('usage',{})
                        for field in ('input_tokens','output_tokens'):
                            value=usage.get(field)
                            if type(value) is not int or value<0: raise ValueError('Unknown or invalid observed usage')
                            counts['observed_tokens']+=value
            manifest=util.read_json(r/'manifest.json') if (r/'manifest.json').exists() else {}
            journal=pair_execution.state(batch/'_control/pair-journal.jsonl')
            if case['run_id'] in journal['dispatch']:
                counts['dispatched_runs']+=1
                duration=manifest.get('duration_seconds')
                if type(duration) in (int,float) and duration>=0: counts['accumulated_run_seconds']+=duration
                else: counts['missing_duration_runs'].append(ident)
    return counts


def _observer_snapshot(monitor):
    """Bounded retry of a Windows sharing violation on the observer's atomic
    status replacement. Staleness, binding and health checks are unchanged; a
    persistent denial still raises and latches STOP."""
    for attempt in range(OBSERVER_READ_RETRIES):
        try:
            return monitor.snapshot()
        except PermissionError:
            if attempt==OBSERVER_READ_RETRIES-1: raise
            time.sleep(0.1*(attempt+1))


class CampaignWatch(live_pilot.PilotWatch):
    def __init__(self,child,digest,campaign,prior,origin,owner_pid,wave_dir):
        super().__init__(child,digest,wall_started_at=origin)
        self.campaign,self.prior=campaign,prior
        from research import proof_session
        reference=proof_session.current_reference()
        self.proof_client=proof_session.Client(reference) if reference else None
        self.owner_pid,self.wave_dir=owner_pid,Path(wave_dir)
        self.owner_handle=None
        if os.name=='nt':
            import ctypes
            kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            kernel.OpenProcess.restype=ctypes.c_void_p
            self.owner_handle=kernel.OpenProcess(0x100000,False,owner_pid)
            if not self.owner_handle: raise ValueError('Cannot bind supervisor process handle')
            self.kernel=kernel

    def register(self,batch,binding):
        with self.lock:
            if len(self.bindings)>=4: raise ValueError('Global active Run limit 4')
            super().register(batch,binding)

    def counters(self):
        result=super().counters()
        for key in ('requests','observed_tokens','accumulated_run_seconds'):
            result[key]+=self.prior[key]
        return result

    def _loop(self):
        while not self.done.wait(1):
            try: self.check()
            except Exception as exc:
                # Preserve the first local supervisory exception before its
                # durable stop makes secondary observer faults inevitable.
                # No model payloads or process environment are captured here.
                try:
                    target=self.wave_dir/'watcher-exception.json'
                    if not target.exists():
                        util.write_new_json(target,dict(at=run.now(),
                            where='CampaignWatch.check',exception_type=type(exc).__name__,
                            message=str(exc),traceback=traceback.format_exc(),
                            plan_sha256=self.campaign['_plan_sha256'],
                            wave_sha256=util.sha256_file(self.wave_dir/'spec.json')))
                except Exception:
                    pass  # Evidence-write failure must never suppress STOP.
                self.latch(type(exc).__name__);return

    def _check_locked(self):
        from research import proof_session
        with proof_session.bind(self.proof_client):
            return self._check_live_locked()

    def _check_live_locked(self):
        if self.fault is not None: raise RuntimeError('Campaign wave fault latched')
        if self.owner_handle:
            import ctypes
            if self.kernel.WaitForSingleObject(ctypes.c_void_p(self.owner_handle),0)!=258:
                raise RuntimeError('Campaign supervisor ownership lost')
        elif os.getppid()!=self.owner_pid: raise RuntimeError('Campaign supervisor ownership lost')
        if self.proof_client is not None: self.proof_client.check()
        if campaign_stop_pending(self.campaign): raise RuntimeError('Campaign STOP')
        if (self.base/'_control/dispatch-stop.json').exists(): raise RuntimeError('Epoch STOP')
        if self.source_repo is not None: live_pilot.verify_pins(self.source_repo,self.plan['source_pins'])
        if self.plan_reference is not None: live_pilot.checked(self.plan_reference)
        c=self.counters(); limits=self.campaign['bounds']
        for key,limit in [('requests','request_count'),('observed_tokens','observed_tokens'),
                          ('accumulated_run_seconds','accumulated_run_seconds'),('wall_seconds','wall_seconds')]:
            if c[key]>=limits[limit]: raise RuntimeError('Campaign observed ceiling '+key)
        if c['longest_active_run_seconds']>=self.plan['bounds']['run_seconds']: raise RuntimeError('Run wall ceiling')
        if c['disk_free_bytes']<limits['disk_free_min_bytes']: raise RuntimeError('Disk floor')
        if c['http_inflight']>limits['http_inflight_max']: raise RuntimeError('Global HTTP overlap ceiling')
        for monitor in list(self.monitors):
            sample=_observer_snapshot(monitor)
            if sample.get('host_healthy') is not True or sample.get('resource_healthy') is not True:
                raise RuntimeError('Independent observer unhealthy')
            for key,limit in self.plan['thresholds'].items():
                if key=='http_inflight_max': continue  # Local observer checks 2; campaign checks aggregate 4.
                value=sample.get(key)
                if type(value) not in (int,float) or (value<limit if key.endswith('_min_bytes') else value>limit):
                    raise RuntimeError('Operational threshold '+key)
        util.write_json_atomic(self.wave_dir/'worker-heartbeat.json',dict(at=run.now(),pid=os.getpid(),
            owner_pid=self.owner_pid,counters=c,active_runs=len(self.run_clocks)-len(self.run_durations)))
        return c

    def latch(self,reason):
        target=Path(self.campaign['batch'])/'_control/dispatch-stop.json'
        try:
            with self.lock:
                if not target.exists(): util.write_new_json(target,dict(reason=reason,at=run.now(),
                    wave=str(self.wave_dir),plan_sha256=self.campaign['_plan_sha256'],
                    wave_sha256=util.sha256_file(self.wave_dir/'spec.json')))
                event=target.parent/'stop-events'/(self.wave_dir.name+'.json')
                if not event.exists():util.write_new_json(event,dict(reason=reason,at=run.now(),
                    plan_sha256=self.campaign['_plan_sha256'],wave_sha256=util.sha256_file(self.wave_dir/'spec.json')))
        except Exception as exc:
            self.stop_marker_error=type(exc).__name__
        finally:
            # Disk failure cannot suppress the in-memory latch and owned stops.
            super().latch(reason)

    def finish(self):
        joined=super().finish()
        if self.owner_handle:
            import ctypes
            self.kernel.CloseHandle(ctypes.c_void_p(self.owner_handle));self.owner_handle=None
        return joined


@scoped_validation
def execute_wave(repo,path,wave_path,owner_pid):
    p=validate(repo,path)
    with pair_execution.exclusive(Path(p['batch'])/'_control'):
        validate_admission(repo,path,wave_path)
        return _execute_wave(repo,path,wave_path,owner_pid)


def _execute_wave(repo,path,wave_path,owner_pid):
    p=validate(repo,path);w=wave_spec(repo,path,wave_path); directory=Path(wave_path).parent
    child_path=live_pilot.checked(w['epoch_plan']);child=readiness.verify_main_phase(child_path,repo)
    auth=document(live_pilot.reference(Path(p['batch'])/'authorization.json'))
    if auth.get('authorized') is not True or auth.get('plan_sha256')!=util.sha256_file(path):
        raise ValueError('Exact user campaign authorization missing')
    from research import next_phase,catalog_environment,repaired_runtime
    if next_phase.git(repo,'rev-parse','HEAD')!=p['source_commit'] or next_phase.git(repo,'status','--porcelain'):
        raise ValueError('Clean pinned source required')
    repaired_runtime._committed_files(repo,p['source_commit'],p['source_pins'])
    validate_readiness(repo,path)
    catalog_environment.validate(document(child['browser_pin']),repo)
    selected={c['run_instance_id'] for pair in w['assignments'] for c in pair['cases']}
    prior=observed_usage(p,exclude=selected)
    if prior['usage_journal_errors'] or prior['missing_duration_runs']: raise ValueError('Prior usage needs reconciliation')
    origin=Path(p['batch'])/'execution-start.json'
    if not origin.exists():util.write_new_json(origin,dict(plan_sha256=util.sha256_file(path),started_at=run.now()))
    beginning=util.read_json(origin)
    if beginning['plan_sha256']!=util.sha256_file(path):raise ValueError('Campaign clock binding mismatch')
    util.write_new_json(directory/'execution-intent.json',dict(campaign=w['campaign'],wave=live_pilot.reference(wave_path),
        owner_pid=owner_pid,worker_pid=os.getpid(),started_at=run.now()))
    watch=CampaignWatch(child,w['epoch_plan']['sha256'],dict(p,_plan_sha256=util.sha256_file(path)),
        prior,beginning['started_at'],owner_pid,directory)
    results={};errors={}; joined=False
    postprocess_lock=threading.Lock()
    with pair_execution.exclusive(Path(child['batch'])/'_control'):
        try:
            watch.check();watch.start()
            with ThreadPoolExecutor(max_workers=2) as pool:
                jobs={pool.submit(live_pilot.execute_owned_pair_scope,repo,child_path,
                    Path(child['batch'])/f'pair-{n}'/'phase.json',budget_watch=watch,
                    postprocess_lock=postprocess_lock):n for n in w['pairs']}
                for future in as_completed(jobs):
                    n=jobs[future]
                    try:results[str(n)]=future.result()
                    except BaseException as exc:
                        errors[str(n)]=type(exc).__name__;watch.latch(type(exc).__name__)
        finally:
            joined=watch.finish()
            outcome=dict(plan_sha256=util.sha256_file(path),wave_sha256=util.sha256_file(wave_path),
                epoch_plan=w['epoch_plan'],pair_results=results,errors=errors,fault=watch.fault,
                watcher_shutdown_verified=joined,operational_complete=bool(joined and not errors and not watch.fault
                and len(results)==len(w['pairs']) and all(v.get('reason')=='pair_publication_restore_cleanup_required'
                    for v in results.values())),publication_gates_complete=False)
            util.write_new_json(directory/'result.json',outcome)
    return outcome


@scoped_validation
def verify_closure(repo,path,wave_path,closure_path):
    w=wave_spec(repo,path,wave_path);c=util.read_json(closure_path)
    if c.get('wave')!=live_pilot.reference(wave_path) or c.get('closed') is not True:
        raise ValueError('Wave closure missing/foreign')
    if 'recovery' in c:
        from research import campaign_recovery
        campaign_recovery.validate_closure(repo,path,wave_path,c['recovery'])
        return True
    if c.get('closure_kind')==OWNED_CLOSURE_KIND:
        if not owned_policy(validate(repo,path)):
            raise ValueError('Owned wave closure requires the owned closure campaign policy')
        _verify_owned_closure(repo,path,wave_path,w,c)
        return True
    from research import acquisition_sharing
    child=document(w['epoch_plan'])
    if set(c.get('gates',{}))!={str(n) for n in w['pairs']}:raise ValueError('Both wave gates required')
    for n in w['pairs']:
        batch=Path(child['batch'])/f'pair-{n}'
        current=pair_execution.state(batch/'_control/pair-journal.jsonl')
        gate=document(c['gates'][str(n)])
        acquisition_sharing.validate_gate(gate,current,n)
    return True


@scoped_validation
def close_wave(repo,path,wave_path):
    p=validate(repo,path)
    with pair_execution.exclusive(Path(p['batch'])/'_allocation'):
        return _close_wave(repo,path,wave_path)


def _close_wave(repo,path,wave_path):
    p=validate(repo,path);w=wave_spec(repo,path,wave_path);child=document(w['epoch_plan'])
    directory=Path(wave_path).parent
    launch=util.read_json(directory/'_launcher/result.json')
    if (launch.get('operational_complete') is not True or launch.get('plan')!=live_pilot.reference(path)
            or launch.get('wave')!=live_pilot.reference(wave_path) or launch.get('owned_closure_confirmed') is not True
            or launch.get('verification',{}).get('confirmed') is not True):
        raise ValueError('Launcher terminal proof pending')
    live_pilot.checked(launch['verification']['evidence'])
    target=directory/'closure.json'
    if target.exists():
        verify_closure(repo,path,wave_path,target)
        return _record_closed_wave(p,w,util.read_json(target))
    if owned_policy(p):
        return _close_wave_owned(repo,path,wave_path,p,w,child,directory,launch,target)
    from research import campaign_reassessment
    gates={}; observations={}
    for n in w['pairs']:
        batch=Path(child['batch'])/f'pair-{n}'
        current=pair_execution.state(batch/'_control/pair-journal.jsonl')
        if n not in current['gates']:raise ValueError('Actual publication gate pending')
        gates[str(n)]=live_pilot.reference(current['gates'][n]['receipt'])
        observations[str(n)]={case['condition']:campaign_reassessment.classify(repo=repo,
            source=batch/case['run_id'],main_plan_ref=w['epoch_plan']) for case in child['assignments'][n-1]['cases']}
    closure=dict(wave=live_pilot.reference(wave_path),closed=True,gates=gates,observations=observations,at=run.now())
    util.write_new_json(target,closure)
    verify_closure(repo,path,wave_path,target)
    return _record_closed_wave(p,w,closure)


def _launcher_proof(path,wave_path,directory):
    launch=util.read_json(directory/'_launcher/result.json')
    if (launch.get('kind')!='repaired_campaign_wave_launcher_v1_result'
            or launch.get('operational_complete') is not True or launch.get('plan')!=live_pilot.reference(path)
            or launch.get('wave')!=live_pilot.reference(wave_path) or launch.get('owned_closure_confirmed') is not True
            or launch.get('verification',{}).get('confirmed') is not True):
        raise ValueError('Owned closure requires exact launcher terminal proof')
    proof=document(launch['verification']['evidence'])
    if (proof.get('confirmed') is not True or proof.get('plan')!=live_pilot.reference(path)
            or proof.get('wave')!=live_pilot.reference(wave_path)):
        raise ValueError('Owned closure lacks bound independent verification')
    return launch


def _wave_outcome(path,wave_path,directory,w):
    outcome=util.read_json(directory/'result.json')
    if (outcome.get('plan_sha256')!=util.sha256_file(path) or outcome.get('wave_sha256')!=util.sha256_file(wave_path)
            or outcome.get('epoch_plan')!=w['epoch_plan'] or outcome.get('operational_complete') is not True
            or outcome.get('errors') or outcome.get('fault') is not None
            or outcome.get('watcher_shutdown_verified') is not True
            or set(outcome.get('pair_results',{}))!={str(n) for n in w['pairs']}
            or any(v.get('reason')!='pair_publication_restore_cleanup_required' for v in outcome['pair_results'].values())):
        raise ValueError('Owned closure requires operationally complete acquisition and evaluation')
    return outcome


def _owned_pair_facts(child,n):
    """Owned acquisition, evaluation, local archive and resource-release facts."""
    from outer.harness import preserve
    from research import saved_reassessment
    batch=Path(child['batch'])/f'pair-{n}'
    current=pair_execution.state(batch/'_control/pair-journal.jsonl')
    cases=child['assignments'][n-1]['cases']
    if set(current['dispatch'])!={c['run_id'] for c in cases} or set(current['results'])!={c['run_id'] for c in cases}:
        raise ValueError('Owned closure requires both dispatched arms with durable results')
    proof=util.read_json(batch/'owned-terminal-proof.json')
    observer=util.read_json(batch/'observer-terminal.json')
    if observer.get('observer_ack_verified') is not True or len(proof.get('runs',[]))!=2:
        raise ValueError('Owned pair terminal/observer proof incomplete')
    runs={}
    for case in cases:
        root=batch/case['run_id']
        manifest=util.read_json(root/'manifest.json')
        if manifest.get('run_instance_id')!=case['run_instance_id'] or manifest.get('stop_confirmed') is not True:
            raise ValueError('Owned closure requires confirmed stop of the exact Run')
        reference=util.read_json(root/'archive-reference.json')
        row=current['results'][case['run_id']]['row']
        if row.get('archive')!=reference:
            raise ValueError('Owned local archive reference differs from durable result')
        package=batch/'_archive/packages'/reference['package_id']
        if not package.is_dir():raise ValueError('Owned local archive package missing')
        cleanup=[]
        for resource_file in sorted(root.rglob('browser-resources.json')):
            if not saved_reassessment._saved_cleanup_bound(resource_file.parent,case['run_instance_id']):
                raise ValueError('Owned browser/scoring resource release unconfirmed')
            cleanup.append(live_pilot.reference(resource_file))
        runs[case['condition']]=dict(run_id=case['run_id'],run_instance_id=case['run_instance_id'],
            manifest=live_pilot.reference(root/'manifest.json'),archive_reference=reference,
            archive_package=str(package),browser_resources=cleanup)
    return dict(journal=live_pilot.reference(batch/'_control/pair-journal.jsonl'),
        owned_terminal_proof=live_pilot.reference(batch/'owned-terminal-proof.json'),
        observer_terminal=live_pilot.reference(batch/'observer-terminal.json'),runs=runs), current


def _verify_owned_closure(repo,path,wave_path,w,c):
    directory=Path(wave_path).parent;child=document(w['epoch_plan'])
    launch=_launcher_proof(path,wave_path,directory)
    _wave_outcome(path,wave_path,directory,w)
    if (c.get('publication_performed') is not False or c.get('launcher')!=live_pilot.reference(directory/'_launcher/result.json')
            or c.get('outcome')!=live_pilot.reference(directory/'result.json')
            or c.get('policy')!=OWNED_NEXT_WAVE or c.get('resource_release',{}).get('scoring_containers_absent') is not True
            or set(c.get('gates',{}))!={str(n) for n in w['pairs']}
            or set(c.get('observations',{}))!={str(n) for n in w['pairs']}):
        raise ValueError('Owned wave closure incomplete or foreign')
    for n in w['pairs']:
        receipt=document(c['gates'][str(n)])
        facts,_=_owned_pair_facts(child,n)
        if (receipt.get('kind')!=OWNED_PAIR_KIND or receipt.get('pair')!=n or receipt.get('wave')!=live_pilot.reference(wave_path)
                or receipt.get('epoch_plan')!=w['epoch_plan'] or receipt.get('campaign')!=live_pilot.reference(path)
                or receipt.get('publication_performed') is not False or receipt.get('facts')!=facts
                or receipt.get('launcher')!=c['launcher']):
            raise ValueError('Owned pair completion receipt invalid')
    return launch


def _close_wave_owned(repo,path,wave_path,p,w,child,directory,launch,target):
    """No external write: owned acquisition, evaluation, archive and release."""
    from outer.harness import preserve, runtime
    from research import campaign_reassessment
    import json as _json
    _launcher_proof(path,wave_path,directory); _wave_outcome(path,wave_path,directory,w)
    listing=[_json.loads(line) for line in runtime.docker('ps','-a','--no-trunc','--format','{{json .}}',
        timeout=30).stdout.splitlines() if line.strip()]
    if any(row.get('Names','').startswith('s2-score-') for row in listing):
        raise ValueError('Unreleased scoring resource prevents owned closure')
    gates={};observations={}
    for n in w['pairs']:
        facts,current=_owned_pair_facts(child,n)
        batch=Path(child['batch'])/f'pair-{n}'
        archives={}
        for condition,run_facts in facts['runs'].items():
            ref=run_facts['archive_reference']
            preserve.verify(batch/'_archive',ref['package_id'],ref['sha256'])
            archives[condition]=dict(ref,verified=True)
        receipt=directory/f'owned-pair-{n}-completion.json'
        value=dict(kind=OWNED_PAIR_KIND,pair=n,campaign=live_pilot.reference(path),wave=live_pilot.reference(wave_path),
            epoch_plan=w['epoch_plan'],launcher=live_pilot.reference(directory/'_launcher/result.json'),
            facts=facts,archive_verified=archives,publication_performed=False,at=run.now())
        if not receipt.exists():util.write_new_json(receipt,value)
        gates[str(n)]=live_pilot.reference(receipt)
        observations[str(n)]={case['condition']:campaign_reassessment.classify(repo=repo,
            source=batch/case['run_id'],main_plan_ref=w['epoch_plan']) for case in child['assignments'][n-1]['cases']}
    closure=dict(wave=live_pilot.reference(wave_path),closed=True,closure_kind=OWNED_CLOSURE_KIND,
        policy=OWNED_NEXT_WAVE,launcher=live_pilot.reference(directory/'_launcher/result.json'),
        outcome=live_pilot.reference(directory/'result.json'),gates=gates,observations=observations,
        resource_release=dict(scoring_containers_absent=True,launcher_owned_closure_confirmed=True,
            checked_at=run.now()),publication_performed=False,at=run.now())
    util.write_new_json(target,closure)
    verify_closure(repo,path,wave_path,target)
    return _record_closed_wave(p,w,closure)


def _record_closed_wave(p,w,closure):
    wave_ref=closure['wave'];existing=ledger(p)
    for n in w['pairs']:
        if any(e.get('wave')==wave_ref and e.get('slot')==n and e['kind'] in
            ('pair_accepted','pair_preserved_requires_assessment') for e in existing):continue
        observations=closure['observations'][str(n)]
        valid_classes={'already_evaluable','normal_product_failure_partial_observation'}
        if not all(o['classification'] in valid_classes for o in observations.values()):
            pair_execution.append(Path(p['batch'])/'attempts.jsonl',dict(kind='pair_preserved_requires_assessment',
                slot=n,wave=wave_ref,observations=observations))
            continue
        attempt=next(e['pair_attempt'] for e in existing if e['kind']=='pair_attempt_reserved'
            and e['wave']==wave_ref and e['slot']==n)
        pair_execution.append(Path(p['batch'])/'attempts.jsonl',dict(kind='pair_accepted',slot=n,
            pair_attempt=attempt,wave=wave_ref,epoch_plan=w['epoch_plan'],
            quality_complete=all(o['classification']=='already_evaluable' for o in observations.values()),
            observations=observations,adoption='same_attempt_both_arms_observed_including_quality_failures',
            gate=closure['gates'][str(n)]))
    return closure


@scoped_validation
def reconcile_recovery(repo,path,wave_path,recovery_closure_ref):
    """Adopt exact same-attempt observations, or authorize a fresh paired retry."""
    from research import campaign_recovery
    p=validate(repo,path);w=wave_spec(repo,path,wave_path);root=Path(p['batch'])
    value=campaign_recovery.validate_closure(repo,path,wave_path,recovery_closure_ref)
    directory=Path(wave_path).parent;wave_ref=live_pilot.reference(wave_path)
    wrapper=dict(wave=wave_ref,closed=True,recovery=recovery_closure_ref)
    target=directory/'closure.json'
    if target.exists():
        if util.read_json(target)!=wrapper:
            target=directory/'recovery-closure.json'
            if target.exists():
                if util.read_json(target)!=wrapper:raise ValueError('Existing recovery closure differs; preserve it')
            else:util.write_new_json(target,wrapper)
    else:util.write_new_json(target,wrapper)
    verify_closure(repo,path,wave_path,target)
    with pair_execution.exclusive(root/'_allocation'):
        existing=ledger(p)
        target_ref=live_pilot.reference(target)
        for n in w['pairs']:
            decision=value['decisions'][str(n)]
            prior=[e for e in existing if e['kind']=='pair_recovery_decision' and e.get('slot')==n and e.get('wave')==wave_ref]
            if not prior:
                pair_execution.append(root/'attempts.jsonl',dict(kind='pair_recovery_decision',slot=n,
                    wave=wave_ref,decision=decision,closure=target_ref,
                    not_before=value['retry_not_before']))
            elif target.name=='recovery-closure.json' and not any(e.get('closure')==target_ref for e in prior):
                # Append-only supersession by the single verified second recovery
                # of the same wave; the earlier decision and closure stay intact.
                first=prior[-1]
                if first.get('closure')!=live_pilot.reference(directory/'closure.json'):
                    raise ValueError('Superseded recovery decision is not the wave closure decision')
                pair_execution.append(root/'attempts.jsonl',dict(kind='pair_recovery_decision',slot=n,
                    wave=wave_ref,decision=decision,closure=target_ref,
                    not_before=value['retry_not_before'],
                    supersedes=dict(closure=first['closure'],disposition=first['decision']['disposition'])))
            if decision['disposition']=='accept_same_attempt' and not any(
                    e['kind']=='pair_accepted' and e.get('slot')==n for e in existing):
                attempt=next(e['pair_attempt'] for e in existing if e['kind']=='pair_attempt_reserved'
                    and e['slot']==n and e['wave']==wave_ref)
                pair_execution.append(root/'attempts.jsonl',dict(kind='pair_accepted',slot=n,pair_attempt=attempt,
                    wave=wave_ref,epoch_plan=w['epoch_plan'],observations=decision['observations'],
                    quality_complete=decision.get('quality_complete',False),
                    adoption='same_attempt_saved_assessments_or_valid_product_failure',closure=live_pilot.reference(target)))
        if any(d['disposition']=='held' for d in value['decisions'].values()):
            return dict(reconciled=True,clearance=False,reason='unresolved_technical_evidence',closure=live_pilot.reference(target))
        clearance=dict(kind='campaign_stop_clearance_v1',campaign=live_pilot.reference(path),
            source_repo=str(Path(repo).resolve()),wave_closure=live_pilot.reference(target),
            stops={str(file):util.sha256_file(file) for file in stop_markers(p)
                if util.read_json(file).get('plan_sha256')==util.sha256_file(path)
                and util.read_json(file).get('wave_sha256')==wave_ref['sha256']
                and util.read_json(file).get('reason') not in ('user_stop','operator_stop','explicit_stop')})
        out=root/'_control/clearances'/(directory.name+'.json')
        if out.exists():
            if util.read_json(out)!=clearance:raise ValueError('Immutable STOP clearance differs')
        else:util.write_new_json(out,clearance)
    return dict(reconciled=True,clearance=not campaign_stop_pending(p),closure=live_pilot.reference(target))


def _predecessor_context(repo,p):
    pred=p.get('predecessor')
    if not pred or not owned_policy(p):
        raise ValueError('Predecessor recovery requires an owned-policy successor')
    return live_pilot.safe_path(pred['source_repo']),live_pilot.checked(pred['plan']),pred


def _verify_predecessor_recovery(repo,path,p,saved,saved_ref):
    from research import campaign_recovery
    old_repo,old_path,pred=_predecessor_context(repo,p)
    location=live_pilot.checked(saved_ref)
    if (saved.get('campaign')!=live_pilot.reference(path) or saved.get('predecessor_plan')!=pred['plan']
            or saved.get('closed') is not True
            or location.parent!=Path(p['batch'])/'predecessor-recovery'):
        raise ValueError('Foreign predecessor recovery wrapper')
    from research import campaign_transition
    history,_=campaign_transition._history(pred['history'])
    if saved['wave'] not in [row['wave'] for row in history['waves']]:
        raise ValueError('Recovery wave is not retained predecessor history')
    return campaign_recovery.validate_closure(old_repo,old_path,live_pilot.checked(saved['wave']),saved['recovery'])


def _inherited_decision(p,decision):
    if not p.get('predecessor'):return False
    from research import campaign_transition
    return decision in campaign_transition.history_events(p)


def _inherited_owner(repo,p,wave_ref):
    """Retired campaign (plan, pinned checkout) whose retained history holds wave_ref.

    Walks the hash-checked predecessor bindings back from the direct predecessor,
    so a decision recorded several administrative successions earlier (with
    wave-less intermediate successors) is verified under its own campaign."""
    from research import campaign_transition
    seen=set()
    while True:
        old_repo,old_path,pred=_predecessor_context(repo,p)
        history,_=campaign_transition._history(pred['history'])
        if wave_ref in [row['wave'] for row in history['waves']]:
            return old_repo,old_path
        if pred['plan']['sha256'] in seen:
            raise ValueError('Foreign inherited recovery decision')
        seen.add(pred['plan']['sha256'])
        try:
            older=util.read_json(old_path)
        except (OSError,ValueError):
            raise ValueError('Foreign inherited recovery decision')
        if not isinstance(older,dict) or not older.get('predecessor'):
            raise ValueError('Foreign inherited recovery decision')
        repo,p=old_repo,older


def _verify_inherited_recovery(repo,p,saved,saved_ref):
    """A replacement decision that the direct predecessor itself recorded for
    one of its retained waves is verified under that predecessor's own campaign
    plan and pinned checkout, exactly as the predecessor verified it."""
    from research import campaign_recovery
    if not isinstance(saved,dict) or set(saved)!={'wave','closed','recovery'} or saved.get('closed') is not True:
        raise ValueError('Foreign inherited recovery decision')
    old_repo,old_path=_inherited_owner(repo,p,saved['wave'])
    location=live_pilot.checked(saved_ref);wave_path=live_pilot.checked(saved['wave'])
    if location.parent!=wave_path.parent or location.name not in ('closure.json','recovery-closure.json'):
        raise ValueError('Foreign inherited recovery decision')
    return campaign_recovery.validate_closure(old_repo,old_path,wave_path,saved['recovery'])


@scoped_validation
def reconcile_predecessor_recovery(repo,path,wave_path,destination):
    """Same-attempt saved-artifact recovery of a retired predecessor wave whose
    recorded decision remained held. No model call, no publication; predecessor
    bytes and ledgers are never changed. The successor ledger records the new
    decision (and any same-attempt adoption) bound to this immutable recovery."""
    from research import campaign_recovery, campaign_transition
    p=validate(repo,path);root=Path(p['batch'])
    old_repo,old_path,pred=_predecessor_context(repo,p)
    history,_=campaign_transition._history(pred['history'])
    wave_ref=live_pilot.reference(wave_path)
    if wave_ref not in [row['wave'] for row in history['waves']]:
        raise ValueError('Not a retained predecessor wave')
    w=util.read_json(live_pilot.checked(wave_ref))
    # Recovery evidence may need a short Windows path (saved evaluator trees are
    # deep); it must stay outside every source/evidence root. The binding
    # successor-owned wrapper is always retained inside the successor root.
    destination=live_pilot.safe_path(destination)
    for protected in [repo,old_repo,*map(live_pilot.safe_path,p['protected_roots'])]:
        protected=live_pilot.safe_path(protected)
        if destination==protected or destination.is_relative_to(protected) or protected.is_relative_to(destination):
            raise ValueError('Predecessor recovery destination overlaps protected source/evidence')
    with pair_execution.exclusive(root/'_allocation'):
        events=ledger(p)
        for n in w['pairs']:
            if any(e['kind']=='pair_accepted' and e['slot']==n for e in events):raise ValueError('Slot already accepted')
            reserved=[e for e in events if e['kind']=='pair_attempt_reserved' and e['slot']==n]
            decisions=[e for e in events if e['kind']=='pair_recovery_decision' and e['slot']==n]
            if not reserved or reserved[-1]['wave']!=wave_ref:
                raise ValueError('Only the latest attempt of a slot may be recovered')
            if not decisions or decisions[-1]['wave']!=wave_ref or decisions[-1]['decision']['disposition']!='held':
                raise ValueError('Only a held predecessor decision may be revisited')
        recovery=campaign_recovery.recover_wave(old_repo,old_path,wave_path,destination)
        closure=campaign_recovery.close_recovery(old_repo,old_path,wave_path,recovery,None,
            owned_authority=dict(repo=str(live_pilot.safe_path(repo)),plan=live_pilot.reference(path)))
        value=campaign_recovery.validate_closure(old_repo,old_path,wave_path,closure)
        wrapper=dict(kind=PREDECESSOR_RECOVERY_KIND,campaign=live_pilot.reference(path),
            predecessor_plan=pred['plan'],wave=wave_ref,closed=True,recovery=closure)
        target=root/'predecessor-recovery'/(Path(wave_path).parent.name+'-'+destination.name+'.json')
        target.parent.mkdir(exist_ok=True)
        if target.exists():
            if util.read_json(target)!=wrapper:raise ValueError('Retained successor recovery wrapper differs')
        else:util.write_new_json(target,wrapper)
        ref=live_pilot.reference(target)
        _verify_predecessor_recovery(repo,path,p,wrapper,ref)
        events=ledger(p)
        for n in w['pairs']:
            decision=value['decisions'][str(n)]
            if not any(e['kind']=='pair_recovery_decision' and e['slot']==n and e.get('closure')==ref for e in events):
                pair_execution.append(root/'attempts.jsonl',dict(kind='pair_recovery_decision',slot=n,
                    wave=wave_ref,decision=decision,closure=ref,not_before=value['retry_not_before'],
                    predecessor_recovery=True))
            if decision['disposition']=='accept_same_attempt' and not any(
                    e['kind']=='pair_accepted' and e.get('slot')==n for e in events):
                attempt=[e for e in events if e['kind']=='pair_attempt_reserved' and e['slot']==n][-1]['pair_attempt']
                pair_execution.append(root/'attempts.jsonl',dict(kind='pair_accepted',slot=n,pair_attempt=attempt,
                    wave=wave_ref,epoch_plan=w['epoch_plan'],observations=decision['observations'],
                    quality_complete=decision.get('quality_complete',False),
                    adoption='same_attempt_saved_assessments_or_valid_product_failure',closure=ref))
    return dict(reconciled=True,closure=ref,decisions={n:d['disposition'] for n,d in value['decisions'].items()},
        retry_not_before=value['retry_not_before'])


def _main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('check','epoch','reserve-wave','close-wave','_wave','status'))
    parser.add_argument('plan',type=Path);parser.add_argument('--repo',type=Path,required=True)
    parser.add_argument('--wave',type=Path);parser.add_argument('--epoch',type=Path)
    parser.add_argument('--pairs',type=int,nargs='+');parser.add_argument('--owner-pid',type=int)
    a=parser.parse_args()
    if a.action=='check':return {'valid':bool(validate(a.repo,a.plan))}
    if a.action=='epoch':return epoch(a.repo,a.plan)
    if a.action=='reserve-wave':return str(reserve_wave(a.repo,a.plan,live_pilot.reference(a.epoch),a.pairs))
    if a.action=='close-wave':return close_wave(a.repo,a.plan,a.wave)
    if a.action=='_wave':return execute_wave(a.repo,a.plan,a.wave,a.owner_pid)
    p=validate(a.repo,a.plan);events=ledger(p)
    return dict(initial_logical_denominator=100,accepted_pairs=len([e for e in events if e['kind']=='pair_accepted']),
        reserved_attempts=len([e for e in events if e['kind']=='pair_attempt_reserved']),usage=observed_usage(p))


def main():
    from research.proof_session import cli_session
    with cli_session():
        return _main()


if __name__=='__main__':
    import json
    print(json.dumps(main(),ensure_ascii=False))
