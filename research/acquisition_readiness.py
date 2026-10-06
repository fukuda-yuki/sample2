"""Prepare a fresh repaired-evaluator cohort; never start 100 pairs implicitly.

The old frozen protocols and acquisition identities remain unchanged. A future
explicitly authorized call admits one pair only, after the previous pair's real
publication/restore/cleanup gate. Technical readiness does not assert product
quality or authorize acquisition.
"""
import argparse
import copy
from pathlib import Path
import re
import sys
import uuid

from outer.harness import profiles, run, util
from research import live_pilot, pair_execution, next_phase

KIND = live_pilot.MAIN_KIND
REVISION = 'evaluators-20261006'
TASKS = ('MS1-CONT-A', 'MS1-CONT-B', 'CU1-ENR-C', 'CU1-ENR-D')
RUNTIMES = {t: ('deepseek-music-repaired-v1' if t.startswith('MS1-')
                 else 'deepseek-education-repaired-v1') for t in TASKS}
BOUNDS = {**live_pilot.BOUNDS, 'max_pairs':100, 'max_runs':200,
          'accumulated_run_seconds':360000, 'request_count':30000,
          'observed_tokens':1500000000, 'wall_seconds':450000}
BASE_PROTOCOL = 'research/protocols/source-information-two-families-20261003-v5-100p2.json'
BASE_PROTOCOL_SHA256 = 'd055265291721575a301fc7e44640ad2888730a0fb8427936bd239fc7ef12a25'
EXTRA_PINS = ('research/acquisition_readiness.py', 'research/repaired_runtime.py', BASE_PROTOCOL,
              'research/next_phase.py', 'research/next_phase_design.py',
              'research/acquisition_sharing.py','research/next_phase_sharing.py',
              'research/catalog_delivery.py','research/catalog_share.py',
              'research/catalog_allocation_review.py','research/paired_acceptance.py')


def reviewed_assignments():
    # Preserve the reviewed seeded randomization, arm ordering, nested task
    # membership and four-pair session grouping. Only acquisition identities
    # change. Neither the old protocol nor its frozen assignments are edited.
    baseline=Path(__file__).resolve().parents[1]/BASE_PROTOCOL
    if util.sha256_file(baseline)!=BASE_PROTOCOL_SHA256: raise ValueError('Reviewed design protocol changed')
    return next_phase.assignments(util.read_json(baseline))


def protected_instance_ids():
    return {case['run_instance_id'] for pair in reviewed_assignments() for case in pair['cases']}


def readiness_instance_ids(plan):
    """Hash-bound logical pilot identities, including unsent origin reservations."""
    trial_keys=('readiness_education_trial_plan','readiness_education_trial_result')
    if any(k in plan for k in trial_keys):
        from research import education_readiness_trial
        if (not all(k in plan for k in trial_keys)
                or any(k in plan for k in ('readiness_recovery_plan','readiness_recovery_result','readiness_pilot_plan','readiness_pilot_result'))):
            raise ValueError('Complete unmixed independent trial readiness references required')
        trial=util.read_json(live_pilot.checked(plan[trial_keys[0]]))
        live_pilot.checked(plan[trial_keys[1]])
        if trial.get('kind')!=education_readiness_trial.KIND:raise ValueError('Wrong typed trial owner')
        origin=util.read_json(live_pilot.checked(trial['original_plan']))
        ids=education_readiness_trial.validate_cases(trial,origin)
        original_ids={c['run_instance_id'] for p in origin['assignments'] for c in p['cases']}
        if origin.get('kind')!=live_pilot.KIND or len(original_ids)!=4:raise ValueError('Four original logical identities required')
        return ids|original_ids
    if 'readiness_recovery_plan' in plan or 'readiness_recovery_result' in plan:
        if not all(k in plan for k in ('readiness_recovery_plan','readiness_recovery_result')):
            raise ValueError('Both recovery references required')
        from research import readiness_recovery
        recovered=util.read_json(live_pilot.checked(plan['readiness_recovery_plan']))
        if recovered.get('kind')!=readiness_recovery.KIND: raise ValueError('Wrong recovery owner')
        reference=recovered['original_plan']
    elif 'readiness_pilot_plan' in plan:
        reference=plan['readiness_pilot_plan']
    else:
        return set()  # Offline draft cannot execute without readiness_for_main.
    origin=util.read_json(live_pilot.checked(reference))
    cases=[case for pair in origin.get('assignments',[]) for case in pair.get('cases',[])]
    identities={case.get('run_instance_id') for case in cases}
    if (origin.get('kind')!=live_pilot.KIND or len(cases)!=4 or len(identities)!=4
            or any(not isinstance(rid,str) or not re.fullmatch('[a-f0-9]{32}',rid) for rid in identities)):
        raise ValueError('Four distinct logical original pilot UUIDs required')
    return identities


def assignments():
    result=reviewed_assignments()
    for index,pair in enumerate(result):
        for case in pair['cases']:
            case['attempt']=6001+index
            case['run_id']=run.run_id_for(case['task'],case['condition'],case['attempt'])
            case['run_instance_id']=uuid.uuid4().hex
    return result


def verify_main_phase(path,repo, *, check_tree=True):
    # Current tree membership is fresh; closed-gate callers inspect their exact
    # original roots instead of walking every unrelated historical pair again.
    from research import proof_session
    path, repo = live_pilot.safe_path(path), live_pilot.safe_path(repo)
    value = util.read_json(path)
    base = live_pilot.safe_path(value['batch'])
    if check_tree and base.exists():
        for item in base.rglob('*'): live_pilot.safe_path(item)
    return proof_session.use('main-phase-static', dict(path=str(path),repo=str(repo)),
        lambda: _verify_main_phase_static(path,repo))


def _verify_main_phase_static(path,repo):
    """Strict read-only validation used by the independent live observer."""
    path=live_pilot.safe_path(path); repo=live_pilot.safe_path(repo)
    p=util.read_json(path)
    if (p.get('kind')!=KIND or type(p.get('schema_version')) is not int or p['schema_version']!=1
            or p.get('task_revision')!=REVISION or p.get('require_fixed_instances') is not True
            or type(p.get('pair_concurrency')) is not int or p['pair_concurrency']!=2
            or not re.fullmatch('[a-f0-9]{32}',p.get('phase_id',''))
            or not re.fullmatch('[a-f0-9]{40}',p.get('source_commit',''))):
        raise ValueError('Explicit fresh repaired main cohort required')
    if p.get('runtime_by_task')!=RUNTIMES or p.get('bounds')!=BOUNDS or any(
            type(p['bounds'][k]) is not int for k in BOUNDS):
        raise ValueError('Fixed repaired runtimes and finite main ceilings required')
    settings=p.get('settings',{})
    if (settings!=dict(model_id='deepseek-v4.1-flash',provider='opencode-go',use_balance=False,paid_fallback=False)
            or settings.get('use_balance') is not False or settings.get('paid_fallback') is not False):
        raise ValueError('Exact Go model and balance OFF required')
    cohort=p.get('cohort')
    if not isinstance(cohort,str) or not re.fullmatch(r'[a-zA-Z0-9_-]+(/[a-zA-Z0-9_-]+)*',cohort):
        raise ValueError('Safe fresh cohort required')
    base=live_pilot.safe_path(p['batch'])
    protected=p.get('protected_roots')
    if not isinstance(protected,list) or not protected: raise ValueError('Protected original roots required')
    for old in [repo,*map(live_pilot.safe_path,protected)]:
        if live_pilot.within(base,old) or live_pilot.within(old,base):
            raise ValueError('Fresh cohort overlaps protected/source tree')
    cases=p.get('assignments')
    expected=assignments()
    if not isinstance(cases,list) or len(cases)!=100: raise ValueError('Exactly 100 pairs required')
    instances=set(); old_instances=protected_instance_ids() | readiness_instance_ids(p)
    for pair,want in zip(cases,expected):
        if ({k:v for k,v in pair.items() if k!='cases'}!={k:v for k,v in want.items() if k!='cases'}
                or type(pair.get('pair')) is not int or len(pair.get('cases',[]))!=2):
            raise ValueError('Fixed complete main pair order required')
        for case,target in zip(pair['cases'],want['cases']):
            if {k:v for k,v in case.items() if k!='run_instance_id'}!={k:v for k,v in target.items() if k!='run_instance_id'}:
                raise ValueError('Task/arm/order/attempt/Run identity changed')
            if any(type(case[k]) is not int for k in ('pair','slot','attempt')):
                raise ValueError('Integer assignment indices required')
            identity=case.get('run_instance_id','')
            if not re.fullmatch('[a-f0-9]{32}',identity) or identity in instances or identity in old_instances:
                raise ValueError('Duplicate or foreign main Run UUID')
            instances.add(identity)
            live_pilot.safe_path(base/('pair-'+str(pair['pair']))/case['run_id'])
    live_pilot.verify_pins(repo,p['source_pins'])
    if not set(EXTRA_PINS)<=p['source_pins'].keys(): raise ValueError('Main/repaired binding source pins required')
    trial_keys=('readiness_education_trial_plan','readiness_education_trial_result')
    if any(key in p for key in trial_keys):
        from research import education_readiness_trial
        if not set(education_readiness_trial.EXTRA_PINS)<=p['source_pins'].keys():
            raise ValueError('Explicit trial readiness source pins required')
        readiness_instance_ids(p)
    recovery_keys=('readiness_recovery_plan','readiness_recovery_result')
    if any(key in p for key in recovery_keys):
        from research import readiness_recovery
        if (not all(key in p for key in recovery_keys)
                or not set(readiness_recovery.EXTRA_PINS)<=p['source_pins'].keys()):
            raise ValueError('Complete explicitly pinned recovery readiness references required')
        recovered=util.read_json(live_pilot.checked(p[recovery_keys[0]]))
        if recovered.get('kind')!=readiness_recovery.KIND:
            raise ValueError('Wrong typed recovery readiness owner')
        live_pilot.checked(p[recovery_keys[1]])
    if p['source_pins'][BASE_PROTOCOL]!=BASE_PROTOCOL_SHA256: raise ValueError('Reviewed protocol binding changed')
    monitor=live_pilot.checked(p['resource_monitor']); probe=live_pilot.checked(p['resource_probe'])
    if probe!=monitor.with_name('wave_resource_probe.py'): raise ValueError('Foreign resource probe')
    live_pilot.checked(p['browser_pin'])
    if live_pilot.checked(p['launch_supervisor'])!=repo/'research/live_pilot_launcher.py':
        raise ValueError('Fixed bounded launcher required')
    if p.get('thresholds')!=live_pilot.DEFAULT_THRESHOLDS: raise ValueError('Fixed resource thresholds required')
    refs=p.get('runtime_locks',{})
    if set(refs)!=set(RUNTIMES.values()): raise ValueError('Both repaired family locks required')
    for task in TASKS:
        profile=profiles.read(repo,'runtimes',RUNTIMES[task])
        lockpath=live_pilot.checked(refs[RUNTIMES[task]])
        if lockpath!=profiles.runtime_root(repo,task,profile)/'lock.json': raise ValueError('Foreign runtime namespace')
        lock=util.read_json(lockpath); ledger=profiles.task_profile(repo,task,REVISION)
        if (lock.get('task_profile_revision')!=REVISION or lock.get('runtime_profile_id')!=RUNTIMES[task]
                or lock.get('evaluator_version')!=ledger['evaluation']['evaluation_version']
                or lock.get('evaluator_project')!=ledger['evaluation']['project']):
            raise ValueError('Repaired runtime/ledger mismatch')
        from research.repaired_runtime import validate_repaired_runtime_binding
        validate_repaired_runtime_binding(repo,lock)
    return p


def create(repo,path):
    p=verify_main_phase(path,repo); base=Path(p['batch']); base.mkdir(parents=False,exist_ok=False)
    ref=live_pilot.reference(path)
    util.write_new_json(base/'allocation.json',dict(kind=KIND,plan=ref,phase_id=p['phase_id']))
    for pair in p['assignments']:
        phase=live_pilot.observer_phase(p,ref,pair['pair'])
        child=Path(phase['batch']); child.mkdir()
        util.write_new_json(child/'phase.json',phase)
    return dict(allocated=True,model_dispatched=False,automatic_main_start=False,plan=ref,batch=str(base))


def _pilot_pipeline_evidence(repo,plan_reference,result_reference):
    """Recheck actual saved dispatch/stop/usage/scoring and observer evidence."""
    path=live_pilot.checked(plan_reference); plan=live_pilot.validate_plan(util.read_json(path),repo)
    result=util.read_json(live_pilot.checked(result_reference))
    if (result.get('kind')!=live_pilot.KIND or result.get('plan_sha256')!=plan_reference['sha256']
            or result.get('pilot_operational_complete') is not True or result.get('fault') is not None
            or result.get('watcher_shutdown_verified') is not True):
        raise ValueError('Real repaired pipeline pilot is not operationally complete')
    native_sessions=set()
    for pair in plan['assignments']:
        child=Path(plan['batch'])/('pair-'+str(pair['pair']))
        journal=pair_execution.state(child/'_control/pair-journal.jsonl')
        if set(journal['dispatch'])!={c['run_id'] for c in pair['cases']} or len(journal['results'])!=2:
            raise ValueError('Pilot actual two-Run dispatch/result proof missing')
        terminal=util.read_json(child/'observer-terminal.json')
        validate_observer_terminal(plan,plan_reference,pair,child,terminal)
        owned=util.read_json(child/'owned-terminal-proof.json')
        phase_hash=util.sha256_file(child/'phase.json')
        if owned.get('plan_sha256')!=plan_reference['sha256'] or owned.get('phase_sha256')!=phase_hash:
            raise ValueError('Foreign owned terminal proof')
        newproofs=[]
        for case in pair['cases']:
            rid=case['run_id']; dispatch=journal['dispatch'][rid]
            if dispatch.get('run_instance_id')!=case['run_instance_id']: raise ValueError('Pilot UUID mismatch')
            receipt=journal['implementations'][rid]['receipt']
            row=journal['results'][rid]['row']
            root=child/rid; normalized=util.read_json(root/'usage/normalized.json')
            if (receipt.get('stop_confirmed') is not True or pair_execution._postprocess_fault(row)
                    or normalized.get('usage_complete') is not True or normalized.get('input_reached') is not True
                    or receipt.get('raw')!=util.tree_hashes(root/'usage/raw')
                    or not (root/'snapshot.json').is_file()
                    or receipt.get('snapshot_sha256')!=util.sha256_file(root/'snapshot.json')):
                raise ValueError('Pilot stop/usage/evaluator fault')
            starts,errors=live_pilot.live_usage.journal(root/'usage/raw/started.jsonl')
            events,more=live_pilot.live_usage.journal(root/'usage/raw/events.jsonl')
            if errors or more or not starts or not events: raise ValueError('Actual model request/response missing')
            from research.wave_campaign import journal_health
            health=journal_health(child,[dispatch],plan['settings']['model_id'])
            if not all(health[k] is True for k in ('journal_healthy','provider_healthy','http_healthy')):
                raise ValueError('Pilot model/HTTP identity evidence invalid')
            newproofs.append(live_pilot.validate_owned_terminal(root,dispatch))
        if owned.get('runs')!=newproofs or len({v['native_session_id'] for v in newproofs})!=2:
            raise ValueError('Owned terminal/provenance proof changed')
        for proof in newproofs:
            if proof['native_session_id'] in native_sessions: raise ValueError('Native session reused across pilot pairs')
            native_sessions.add(proof['native_session_id'])
    return dict(ready=True,pilot_plan=plan_reference,pilot_result=result_reference,model_runs=4,
                product_quality_guaranteed=False,new_main_authorized=False)


def pilot_ready(repo,plan_reference,result_reference):
    """Actual pipeline and its independent bounded launch have both closed."""
    pipeline=_pilot_pipeline_evidence(repo,plan_reference,result_reference)
    plan=util.read_json(live_pilot.checked(plan_reference))
    directory=live_pilot.safe_path(Path(plan['batch'])/'_launcher')
    intent=util.read_json(directory/'intent.json'); registration=util.read_json(directory/'registration.json')
    result=util.read_json(directory/'result.json')
    expected_source=util.sha256_file(Path(repo)/'research/live_pilot_launcher.py')
    if (intent.get('kind')!='live_pilot_launcher_v1' or intent.get('schema_version')!=1
            or intent.get('plan')!=plan_reference or intent.get('selected_pair') is not None
            or intent.get('phase_id')!=plan['phase_id'] or intent.get('source_sha256')!=expected_source
            or intent.get('controller_source_commit')!=plan['source_commit']
            or not re.fullmatch('[a-f0-9]{32}',intent.get('launch_id',''))
            or any(type(intent.get(k)) is not int or intent[k]<=0 for k in ('launcher_pid','parent_pid'))
            or {k:v for k,v in registration.items() if k!='child_pid'}!=intent
            or type(registration.get('child_pid')) is not int or registration['child_pid']<=0):
        raise ValueError('Independent launcher intent/child binding missing or foreign')
    command=intent.get('command',[])
    expected_tail=['-B','-X','utf8','-m','research.live_pilot','execute',plan_reference['path'],
                   '--repo',str(Path(repo).resolve()),'--approval',intent['approval']['path']]
    if (not isinstance(command,list) or len(command)!=len(expected_tail)+1
            or command[1:]!=expected_tail or live_pilot.safe_path(command[0])!=Path(sys.executable).resolve()):
        raise ValueError('Launcher actual child command differs')
    approval=util.read_json(live_pilot.checked(intent['approval']))
    if (approval.get('plan_sha256')!=plan_reference['sha256'] or approval.get('authorized') is not True
            or approval.get('approved_by')!='user' or not approval.get('authorization_reference')):
        raise ValueError('Launcher approval proof changed')
    if (result.get('kind')!='live_pilot_launcher_result_v1'
            or any(result.get(k)!=intent[k] for k in ('approval','controller_source_commit','launch_id','launcher_pid'))
            or result.get('child_pid')!=registration['child_pid']
            or type(result.get('verification_child_pid')) is not int or result['verification_child_pid']<=0
            or result.get('watcher_shutdown_verified') is not True
            or result.get('operational_complete') is not True or type(result.get('child_exit_code')) is not int
            or result['child_exit_code']!=0 or result.get('verification_child_exit_code')!=0
            or type(result.get('verification_child_exit_code')) is not int
            or result.get('plan')!=plan_reference or result.get('source_sha256')!=expected_source
            or result.get('stop_requested') is not False or result.get('selected_pair') is not None
            or type(result.get('model_runs')) is not int or result['model_runs']!=4
            or result.get('new_main_authorized') is not False):
        raise ValueError('Independent bounded launcher did not close successfully')
    proof=util.read_json(live_pilot.checked(result['terminal_proof']))
    if Path(result['terminal_proof']['path']).resolve()!=directory/'terminal-proof.json' or proof!=pipeline:
        raise ValueError('Launcher terminal verification proof differs')
    return {**pipeline,'launcher_result':live_pilot.reference(directory/'result.json'),
            'launcher_intent':live_pilot.reference(directory/'intent.json'),
            'launcher_registration':live_pilot.reference(directory/'registration.json')}


def readiness_for_main(repo,plan):
    """Explicit amended readiness never relabels the failed original pilot."""
    trial_keys=('readiness_education_trial_plan','readiness_education_trial_result')
    if any(k in plan for k in trial_keys):
        if (not all(k in plan for k in trial_keys)
                or any(k in plan for k in ('readiness_recovery_plan','readiness_recovery_result','readiness_pilot_plan','readiness_pilot_result'))):
            raise ValueError('Complete unmixed independent trial readiness references required')
        from research import education_readiness_trial
        return education_readiness_trial.ready(repo,plan[trial_keys[0]],plan[trial_keys[1]])
    keys=('readiness_recovery_plan','readiness_recovery_result')
    if any(key in plan for key in keys):
        if not all(key in plan for key in keys): raise ValueError('Both explicit recovery references required')
        from research import readiness_recovery
        return readiness_recovery.ready(repo,plan[keys[0]],plan[keys[1]])
    return pilot_ready(repo,plan['readiness_pilot_plan'],plan['readiness_pilot_result'])


def validate_observer_terminal(plan,plan_reference,pair,child,terminal):
    """Verify saved session generations, hashes, healthy samples and shutdown."""
    phase_path=live_pilot.safe_path(child/'phase.json'); phase_hash=util.sha256_file(phase_path)
    phase=util.read_json(phase_path)
    if phase!=live_pilot.observer_phase(plan,plan_reference,pair['pair']):
        raise ValueError('Pilot observer phase changed')
    raw=terminal.get('directory','')
    if raw.startswith('\\\\?\\'): raw=raw[4:]
    directory=live_pilot.safe_path(raw)
    session=terminal.get('session','')
    if (not re.fullmatch('[a-f0-9]{32}',session) or directory.name!=session
            or directory.parent!=live_pilot.safe_path(Path(plan['batch'])/'_observers')
            or terminal.get('plan')!=plan_reference
            or terminal.get('phase')!=dict(path=str(phase_path),sha256=phase_hash)
            or terminal.get('observer_ack_verified') is not True
            or type(terminal.get('observer_exit_code')) is not int or terminal['observer_exit_code']!=0):
        raise ValueError('Pilot observer terminal identity/exit mismatch')
    pins=terminal.get('evidence_files')
    required={'config.json','shutdown.json','shutdown-ack.json','status.json'}
    from research.resource_supervisor import STARTUP_KINDS,validate_startup_ready
    if phase.get('kind') in STARTUP_KINDS: required.add('startup-ready.json')
    if not isinstance(pins,dict) or not required<=pins.keys(): raise ValueError('Observer evidence hashes missing')
    for name,digest in pins.items():
        if (not isinstance(name,str) or Path(name).is_absolute() or '..' in Path(name).parts
                or '\\' in name or ':' in name or not re.fullmatch('[a-f0-9]{64}',digest)
                or util.sha256_file(live_pilot.safe_path(directory/name))!=digest):
            raise ValueError('Observer evidence pin changed')
    config=util.read_json(directory/'config.json')
    if phase.get('kind') in STARTUP_KINDS:
        validate_startup_ready(config,phase,terminal.get('observer_pid'),util.read_json(directory/'startup-ready.json'))
    if (config.get('session')!=session or config.get('phase')!=dict(path=str(phase_path),sha256=phase_hash)
            or str(config.get('directory','')).removeprefix('\\\\?\\')!=str(directory)):
        raise ValueError('Observer config binding changed')
    shutdown=util.read_json(directory/'shutdown.json'); ack=util.read_json(directory/'shutdown-ack.json')
    generation=shutdown.get('generation')
    if (type(generation) is not int or generation<1 or terminal.get('generation')!=generation
            or shutdown.get('dispatched')!=sorted(c['run_id'] for c in pair['cases'])
            or any(v.get('session')!=session or v.get('phase_sha256')!=phase_hash or v.get('generation')!=generation
                   for v in (shutdown,ack))
            or ack.get('owned_resources_resolved') is not True or ack.get('monitor_stop_confirmed') is not True
            or ack.get('fault_latched') is not False or (directory/'fault-latch.json').exists()):
        raise ValueError('Observer shutdown proof incomplete/foreign/faulted')
    request_name=f'scope-{generation:06d}.json'; ack_name=f'scope-ack-{generation:06d}.json'
    if not {request_name,ack_name}<=pins.keys(): raise ValueError('Final observer scope hashes missing')
    request=util.read_json(directory/request_name); enrolled=util.read_json(directory/ack_name)
    from research.resource_supervisor import validate_scope
    validate_scope({**phase,'_digest':phase_hash},request)
    if (request.get('session')!=session or request.get('generation')!=generation
            or request.get('pairs')!=[pair['pair']]
            or enrolled.get('accepted') is not True or enrolled.get('session')!=session
            or enrolled.get('generation')!=generation or enrolled.get('scope_sha256')!=pins[request_name]):
        raise ValueError('Observer enrollment proof changed')
    pointer=util.read_json(directory/'status.json'); status_path=live_pilot.checked(pointer)
    if not live_pilot.within(status_path,directory) or status_path.relative_to(directory).as_posix() not in pins:
        raise ValueError('Observer status pointer unbound')
    status=util.read_json(status_path); sample=status.get('snapshot',{})
    if (status.get('session')!=session or status.get('phase_sha256')!=phase_hash
            or status.get('generation')!=generation or status.get('sampled_scope_generation')!=generation
            or sample.get('host_healthy') is not True or sample.get('resource_healthy') is not True):
        raise ValueError('Observer final healthy generation missing')
    evidence=sample.get('evidence_files',{})
    if not evidence: raise ValueError('Original observer resource samples missing')
    for name,digest in evidence.items():
        rawname=name.removeprefix('\\\\?\\'); target=live_pilot.safe_path(rawname)
        if (not live_pilot.within(target,directory) or target.relative_to(directory).as_posix() not in pins
                or util.sha256_file(target)!=digest):
            raise ValueError('Observer resource sample hash changed')
    return True


def execute_pair(repo,path,number,approval_path):
    """Explicit future one-pair dispatch; this function never loops 100 pairs."""
    p=verify_main_phase(path,repo); digest=util.sha256_file(path)
    approval=util.read_json(live_pilot.checked(live_pilot.reference(approval_path)))
    if (approval.get('plan_sha256')!=digest or approval.get('authorized') is not True
            or approval.get('approved_by')!='user' or not approval.get('authorization_reference')
            or approval.get('scope')!='new_100_pairs_200_runs'):
        raise ValueError('Fresh main acquisition user authorization required')
    from research import next_phase,catalog_environment
    if next_phase.git(repo,'rev-parse','HEAD')!=p['source_commit'] or next_phase.git(repo,'status','--porcelain'):
        raise ValueError('Clean exact committed source required')
    readiness_for_main(repo,p)
    catalog_environment.validate(util.read_json(live_pilot.checked(p['browser_pin'])),repo)
    if type(number) is not int or not 1<=number<=100: raise ValueError('Fixed pair number required')
    base=Path(p['batch'])
    if util.read_json(base/'allocation.json')!=dict(kind=KIND,plan=live_pilot.reference(path),phase_id=p['phase_id']):
        raise ValueError('Foreign main allocation')
    with pair_execution.exclusive(base/'_control'):
        if (base/'_control/dispatch-stop.json').exists(): raise ValueError('Main STOP latched')
        # All predecessors must have a real verified remote gate. No synthesized
        # successful gate and no direct leap over an unsent or uncertain pair.
        history=[]
        for previous in range(1,number):
            state=pair_execution.state(base/('pair-'+str(previous))/'_control/pair-journal.jsonl')
            if previous not in state['gates']: raise ValueError('Previous actual publication gate pending')
            gate=util.read_json(state['gates'][previous]['receipt'])
            if gate.get('gate_kind')!='repaired_main_pair_publication_gate_v1':
                raise ValueError('Actual repaired main publication gate required')
            history.append((base/('pair-'+str(previous)),list(state['dispatch'].values())))
        for later in range(number+1,101):
            if pair_execution.events(base/('pair-'+str(later))/'_control/pair-journal.jsonl'):
                raise ValueError('Later pair already reserved or dispatched')
        child=base/('pair-'+str(number))
        if pair_execution.events(child/'_control/pair-journal.jsonl'): raise ValueError('No main pair resend/replacement')
        origin=base/'execution-start.json'
        if not origin.exists():
            if number!=1: raise ValueError('Durable main start timestamp missing')
            util.write_new_json(origin,dict(plan_sha256=digest,started_at=run.now()))
        beginning=util.read_json(origin)
        if beginning.get('plan_sha256')!=digest: raise ValueError('Foreign durable main start')
        util.write_new_json(child/'execution-intent.json',dict(plan_sha256=digest,approval=live_pilot.reference(approval_path)))
        watch=live_pilot.PilotWatch(p,digest,wall_started_at=beginning['started_at'])
        for previous,bindings in history: watch.restore_completed(previous,bindings)
        watch.check(); watch.start()
        scope_result=None
        try:
            scope_result=live_pilot.execute_owned_pair_scope(repo,path,child/'phase.json',budget_watch=watch)
        except BaseException as exc:
            watch.latch(type(exc).__name__)
            raise
        finally:
            joined=watch.finish()
            if not joined: watch.latch('watcher_shutdown_unconfirmed')
            util.write_new_json(child/'pair-result.json',dict(kind=KIND,plan_sha256=digest,pair=number,
                pair_result=scope_result,fault=watch.fault,watcher_shutdown_verified=joined,
                pair_operational_complete=bool(scope_result and
                    scope_result.get('reason')=='pair_publication_restore_cleanup_required'
                    and watch.fault is None and joined),automatic_next_pair_start=False))
        return scope_result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('check','create','execute-pair'))
    parser.add_argument('plan',type=Path); parser.add_argument('--repo',type=Path,required=True)
    parser.add_argument('--pair',type=int); parser.add_argument('--approval',type=Path)
    args=parser.parse_args()
    if args.action=='check':
        p=verify_main_phase(args.plan,args.repo)
        proof=readiness_for_main(args.repo,p)
        return dict(start_ready=True,main_plan=live_pilot.reference(args.plan),pilot=proof,new_main_authorized=False)
    if args.action=='create': return create(args.repo,args.plan)
    if args.pair is None or args.approval is None: parser.error('execute-pair requires --pair and --approval')
    return execute_pair(args.repo,args.plan,args.pair,args.approval)


if __name__=='__main__': main()
