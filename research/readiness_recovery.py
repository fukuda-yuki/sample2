"""Separate one-shot recovery of two never-dispatched Education Runs.

Saved Music is postprocessed separately with new assessment IDs. Historical
STOP, failure, conditions and journals remain immutable. This controller has
no retry/replacement or automatic main acquisition route.
"""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import re

from outer.harness import run, util
from research import live_pilot, pair_execution

KIND = 'repaired_pilot_readiness_recovery_v1'
OBSERVER_KIND = 'repaired_pilot_readiness_recovery_observer_v1'
EXTRA_PINS = ('research/readiness_recovery.py', 'research/saved_postprocessing_recovery.py')


def remaining_wall(plan):
    start=datetime.fromisoformat(plan['original_wall_start_utc'])
    now=datetime.now(timezone.utc)
    if start.tzinfo is None or start>now: raise ValueError('Historical aware wall origin required')
    remaining=live_pilot.BOUNDS['wall_seconds']-(now-start).total_seconds()
    if remaining<=0: raise TimeoutError('Original finite pilot wall exhausted')
    return remaining


def _reference_json(ref):
    return util.read_json(live_pilot.checked(ref))


def validate_failed_launcher(launched,registration,plan_ref):
    """Failed launcher stores its owned-child disposition in nested child."""
    child=launched.get('child')
    if (launched.get('kind')!='live_pilot_launcher_result_v1'
            or launched.get('plan')!=plan_ref or launched.get('operational_complete') is not False
            or registration.get('plan')!=plan_ref
            or type(registration.get('child_pid')) is not int or registration['child_pid']<=0
            or type(launched.get('child_pid')) is not int
            or launched['child_pid']!=registration['child_pid'] or not isinstance(child,dict)
            or type(child.get('pid')) is not int or child['pid']!=registration['child_pid']
            or type(child.get('initial_exit_code')) is not int or child['initial_exit_code']!=0
            or type(child.get('exit_code')) is not int or child['exit_code']!=0
            or child.get('unknown') is not False or child.get('terminated') is not False
            or child.get('killed') is not False):
        raise ValueError('Original failed launcher owned child closure is missing or foreign')


def sealed_original(plan):
    """Full read-only origin check, including all retained original files."""
    closeout=_reference_json(plan['original_closeout'])
    old=_reference_json(plan['original_plan'])
    origin=live_pilot.safe_path(old['batch'])
    if (closeout.get('kind')!='failed_repaired_pilot_sealed_closeout_v1'
            or closeout.get('original_plan')!=plan['original_plan']
            or live_pilot.safe_path(closeout['original_batch'])!=origin
            or closeout.get('original_failed_status_preserved') is not True
            or closeout.get('sent_run_replay_authorized') is not False
            or closeout.get('ready') is not False or closeout.get('new_100_dispatched') is not False):
        raise ValueError('Sealed failed original identity required')
    # The immutable root map includes native/raw data, journal, conditions,
    # assets, logs and retained build products, rather than selected receipts.
    inventory=_reference_json(closeout['original_inventory'])
    if not inventory or util.tree_hashes(origin)!=inventory:
        raise ValueError('Sealed original bytes changed')
    result=_reference_json(closeout['original_result'])
    launched=_reference_json(closeout['original_launcher_result'])
    validate_failed_launcher(launched,util.read_json(origin/'_launcher/registration.json'),plan['original_plan'])
    if (live_pilot.checked(closeout['original_result'])!=origin/'result.json'
            or live_pilot.checked(closeout['original_launcher_result'])!=origin/'_launcher/result.json'):
        raise ValueError('Original terminal references must belong to sealed root')
    stop=util.read_json(origin/'_control/dispatch-stop.json')
    intent=util.read_json(origin/'_launcher/intent.json')
    execution=util.read_json(origin/'execution-intent.json')
    if (old.get('kind')!=live_pilot.KIND or old.get('schema_version')!=1
            or old.get('bounds')!=live_pilot.BOUNDS or old.get('require_fixed_instances') is not True
            or old.get('pair_concurrency')!=2 or len(old.get('assignments',[]))!=2
            or result.get('kind')!=live_pilot.KIND
            or result.get('plan_sha256')!=plan['original_plan']['sha256']
            or result.get('pilot_operational_complete') is not False or result.get('fault') is None
            or result.get('watcher_shutdown_verified') is not True
            or launched.get('plan')!=plan['original_plan'] or launched.get('operational_complete') is not False
            or stop.get('plan_sha256')!=plan['original_plan']['sha256']
            or intent.get('plan')!=plan['original_plan']
            or execution.get('plan_sha256')!=plan['original_plan']['sha256']):
        raise ValueError('Original STOP and failed terminal closure required')
    start=min(datetime.fromisoformat(intent['started_at']),datetime.fromisoformat(execution['started_at']))
    if (start.tzinfo is None or datetime.fromisoformat(closeout['original_wall_start_utc'])!=start
            or datetime.fromisoformat(plan['original_wall_start_utc'])!=start
            or closeout.get('original_wall_seconds')!=9000
            or closeout.get('observer_ack_confirmed') is not True
            or type(closeout.get('observer_exit_code')) is not int or closeout['observer_exit_code']!=0
            or closeout.get('scoped_process_matches')!=[]
            or closeout.get('never_started_pair2_observer_not_claimed_stopped') is not True):
        raise ValueError('Original independent observer/process closure and earliest wall required')
    observations=closeout.get('resource_observations',[])
    containers=[r for r in observations if 'name' in r]; networks=[r for r in observations if 'network' in r]
    if (len(containers)!=4 or len(networks)!=2
            or any(r.get('owned') is not True or r.get('running') is not False for r in containers)
            or any(r.get('present') is not False for r in networks)):
        raise ValueError('Original four stopped owned containers and two absent networks required')
    # Actual closure was observed and hash-bound by root. Re-adoption below
    # separately reobserves each saved Run's exact owned terminal resources.
    remaining=old['assignments'][1]
    expected_cases=remaining['cases']
    if (remaining.get('pair')!=2 or len(expected_cases)!=2
            or closeout.get('remaining_original_cases')!=expected_cases
            or plan.get('assignments')!=[remaining]):
        raise ValueError('Only exact originally unsent Education pair permitted')
    child=origin/'pair-2'
    for name in ('_control/pair-journal.jsonl','pair-invocation.json','observer-terminal.json','owned-terminal-proof.json'):
        if (child/name).exists(): raise ValueError('Original remaining pair was already attempted')
    for case in expected_cases:
        if (child/case['run_id']).exists(): raise ValueError('Original Education was allocated')
    sent=old['assignments'][0]
    journal=pair_execution.state(origin/'pair-1/_control/pair-journal.jsonl')
    if (sent.get('pair')!=1 or len(sent.get('cases',[]))!=2
            or set(journal['dispatch'])!={c['run_id'] for c in sent['cases']}):
        raise ValueError('Exactly two original Music dispatches required')
    requests=tokens=0; durations=0.0; natives=set()
    for case in sent['cases']:
        binding=journal['dispatch'][case['run_id']]
        if any(binding.get(k)!=v for k,v in case.items()): raise ValueError('Original Music UUID differs')
        root=origin/'pair-1'/case['run_id']
        proof=live_pilot.validate_owned_terminal(root,binding)
        native=proof['native_session_id']
        if native in natives: raise ValueError('Original native session collision')
        natives.add(native)
        manifest=util.read_json(root/'manifest.json')
        starts,errors=live_pilot.live_usage.journal(root/'usage/raw/started.jsonl')
        events,more=live_pilot.live_usage.journal(root/'usage/raw/events.jsonl')
        if (errors or more or not starts or len(starts)!=len(events)
                or manifest.get('end_reason')!='completed' or manifest.get('exit_code')!=0
                or type(manifest.get('duration_seconds')) not in (int,float)
                or manifest['duration_seconds']<0):
            raise ValueError('Original generated Music usage incomplete')
        requests+=len(starts)
        tokens+=sum(e['usage']['input_tokens']+e['usage']['output_tokens'] for e in events)
        durations+=manifest['duration_seconds']
    carried=dict(sent_runs=2,requests=requests,observed_tokens=tokens,accumulated_run_seconds=durations)
    if (plan.get('carried')!=carried or closeout.get('request_count_consumed')!=requests
            or closeout.get('observed_tokens_consumed')!=tokens
            or abs(closeout['run_seconds_consumed']-durations)>0.000001
            or any(type(closeout.get(k)) is not int or closeout[k]!=v for k,v in
                dict(logical_sent_runs=2,generation_complete_runs=2,stop_target_runs=2,
                     stop_confirmed_runs=2,scoring_reached_runs=0,unallocated_unsent_runs=2).items())):
        raise ValueError('Original consumed counters cannot be reset')
    return old,closeout,natives


def validate_plan(plan,repo):
    """All guards precede any mkdir, credential lookup or subprocess start."""
    if (plan.get('kind')!=KIND or type(plan.get('schema_version')) is not int or plan['schema_version']!=1
            or plan.get('original_pilot_adoption') is not False
            or plan.get('sent_run_replay_authorized') is not False):
        raise ValueError('Explicit separate technical recovery required')
    if not set(EXTRA_PINS)<=plan.get('source_pins',{}).keys():
        raise ValueError('Recovery and saved postprocessing source pins required')
    old,closure,_=sealed_original(plan)
    validate_prior_recoveries(plan)
    # Reuse the exact reviewed pilot semantic/source/runtime/path validator on
    # a virtual full assignment list. No Music directory is allocated by this
    # amendment; its real assignment list is only the original second pair.
    shadow=dict(plan,kind=live_pilot.KIND,assignments=old['assignments'])
    live_pilot.validate_plan(shadow,repo)
    semantic_files=[name for name in live_pilot.PIN_FILES if name.endswith('.json')]
    if any(plan['source_pins'].get(name)!=old.get('source_pins',{}).get(name) for name in semantic_files):
        raise ValueError('Recovery cannot amend task/runtime/evaluation/input semantic profiles')
    if (plan['phase_id']==old['phase_id'] or plan['cohort']==old['cohort']
            or plan['settings']!=old['settings'] or plan['task_revision']!=old['task_revision']
            or plan['runtime_by_task']!=old['runtime_by_task']
            or not any(live_pilot.safe_path(p)==live_pilot.safe_path(old['batch']) for p in plan['protected_roots'])):
        raise ValueError('Fresh recovery owner with original task/model/conditions and protection required')
    start=datetime.fromisoformat(plan['original_wall_start_utc'])
    if start.tzinfo is None or start>datetime.now(timezone.utc): raise ValueError('Historical wall origin required')
    from research.saved_postprocessing_recovery import validate_saved_music_postprocessing
    rows=validate_saved_music_postprocessing(repo,plan['saved_music_postprocessing'],plan['original_plan'])
    originals={c['run_instance_id'] for c in old['assignments'][0]['cases']}
    if (len(rows)!=2 or {r['source_run_instance_id'] for r in rows}!=originals
            or len({r['assessment_id'] for r in rows})!=2
            or any(not re.fullmatch('[a-f0-9]{32}',r.get('assessment_id',''))
                   or r['assessment_id'] in {c['run_instance_id'] for p in old['assignments'] for c in p['cases']} for r in rows)
            or any(type(r.get('model_dispatch_count')) is not int or r['model_dispatch_count']!=0
                   or type(r.get('acquisition_count_increment')) is not int or r['acquisition_count_increment']!=0
                   or r.get('original_pilot_adoption') is not False for r in rows)):
        raise ValueError('Two bound zero-acquisition saved Music assessments required')
    live_pilot.checked(plan['launch_supervisor'])
    if live_pilot.checked(plan['launch_supervisor'])!=live_pilot.safe_path(repo)/'research/live_pilot_launcher.py':
        raise ValueError('Reviewed external recovery launcher required')
    return plan


def validate_prior_recoveries(plan):
    """Only sealed, independently closed zero-send attempts permit a new root."""
    refs=plan.get('prior_recovery_closeouts')
    if not isinstance(refs,list) or not refs: raise ValueError('Explicit sealed prior recovery closeouts required')
    seen=set()
    for ref in refs:
        close=_reference_json(ref); prior_ref=close['prior_plan']; prior=_reference_json(prior_ref)
        root=live_pilot.safe_path(prior['batch'])
        if (close.get('kind')!='failed_recovery_observer_startup_closeout_v1'
                or type(close.get('schema_version')) is not int or close['schema_version']!=1
                or close.get('original_plan')!=plan['original_plan']
                or prior.get('kind')!=KIND or prior.get('original_plan')!=plan['original_plan']
                or prior.get('assignments')!=plan['assignments'] or prior.get('carried')!=plan['carried']
                or close.get('original_wall_start_utc')!=plan['original_wall_start_utc']
                or prior.get('original_wall_start_utc')!=plan['original_wall_start_utc']
                or close.get('original_seal')!=plan['original_closeout']
                or close.get('original_unchanged') is not True or close.get('failure_preserved') is not True
                or close.get('ready') is not False or close.get('new100_dispatched') is not False
                or type(close.get('logical_new_sent_runs')) is not int or close['logical_new_sent_runs']!=0
                or close.get('observer_ack_confirmed') is not True
                or type(close.get('observer_exit_code')) is not int or close['observer_exit_code']!=0
                or close.get('scoped_process_matches')!=[] or close.get('no_owned_runtime_resources') is not True
                or root in seen or live_pilot.safe_path(close['failed_batch'])!=root
                or prior['phase_id']==plan['phase_id']
                or not any(live_pilot.safe_path(p)==root for p in plan['protected_roots'])):
            raise ValueError('Prior recovery is unknown, active, sent, unprotected or foreign')
        seen.add(root)
        if util.tree_hashes(root)!=_reference_json(close['inventory']): raise ValueError('Prior failed recovery bytes changed')
        result=_reference_json(close['result']); launched=_reference_json(close['launcher_result'])
        terminal=_reference_json(close['observer_terminal'])
        for field,relative in [('result','result.json'),('launcher_result','_launcher/result.json'),
                               ('observer_terminal','pair-2/observer-terminal.json')]:
            if live_pilot.checked(close[field])!=root/relative: raise ValueError('Foreign prior terminal reference')
        child=launched.get('child',{}); registration=util.read_json(root/'_launcher/registration.json')
        if (result.get('kind')!=KIND or result.get('plan_sha256')!=prior_ref['sha256']
                or result.get('recovery_operational_complete') is not False or result.get('fault') is None
                or result.get('watcher_shutdown_verified') is not True or result.get('original_unchanged') is not True
                or type(result.get('new_model_runs')) is not int or result['new_model_runs']!=0
                or launched.get('kind')!='live_pilot_launcher_result_v1'
                or launched.get('plan')!=prior_ref or launched.get('operational_complete') is not False
                or registration.get('plan')!=prior_ref or type(registration.get('child_pid')) is not int
                or registration['child_pid']<=0 or type(child.get('pid')) is not int or child['pid']!=registration['child_pid']
                or type(launched.get('child_pid')) is not int or launched['child_pid']!=registration['child_pid']
                or type(child.get('initial_exit_code')) is not int or child['initial_exit_code']!=1
                or type(child.get('exit_code')) is not int or child['exit_code']!=1
                or child.get('unknown') is not False or child.get('terminated') is not False or child.get('killed') is not False
                or util.read_json(root/'_control/dispatch-stop.json').get('plan_sha256')!=prior_ref['sha256']
                or pair_execution.state(root/'pair-2/_control/pair-journal.jsonl')['dispatch']
                or any((root/'pair-2'/c['run_id']).exists() for c in plan['assignments'][0]['cases'])):
            raise ValueError('Prior attempt failed closure or zero-send proof invalid')
        directory=live_pilot.safe_path(terminal['directory']); phase_ref=live_pilot.reference(root/'pair-2/phase.json')
        if (terminal.get('plan')!=prior_ref or terminal.get('phase')!=phase_ref
                or directory.parent!=live_pilot.safe_path(root/'_observers') or directory.name!=terminal.get('session')
                or terminal.get('observer_ack_verified') is not True
                or type(terminal.get('observer_exit_code')) is not int or terminal['observer_exit_code']!=0
                or type(terminal.get('observer_pid')) is not int or terminal['observer_pid']<=0
                or type(terminal.get('generation')) is not int or terminal['generation']<=0):
            raise ValueError('Prior observer closed identity missing')
        pins=terminal.get('evidence_files',{}); required={'config.json','shutdown.json','shutdown-ack.json','status.json'}
        if not required<=pins.keys(): raise ValueError('Prior observer evidence missing')
        for name,sha in pins.items():
            if (Path(name).is_absolute() or '..' in Path(name).parts or ':' in name or '\\' in name
                    or util.sha256_file(live_pilot.safe_path(directory/name))!=sha):
                raise ValueError('Prior observer evidence changed')
        config=util.read_json(directory/'config.json'); request=util.read_json(directory/'shutdown.json')
        ack=util.read_json(directory/'shutdown-ack.json')
        expected=dict(session=terminal['session'],generation=terminal['generation'],phase_sha256=phase_ref['sha256'])
        if (config.get('session')!=terminal['session'] or config.get('phase')!=phase_ref
                or live_pilot.safe_path(config['directory'])!=directory or request.get('dispatched')!=[]
                or any(v.get(k)!=x for v in (request,ack) for k,x in expected.items())
                or ack.get('owned_resources_resolved') is not True or ack.get('monitor_stop_confirmed') is not True):
            raise ValueError('Prior independent shutdown ACK missing or foreign')
    return refs


class RecoveryWatch(live_pilot.PilotWatch):
    def __init__(self,plan,digest):
        super().__init__(plan,digest,wall_started_at=plan['original_wall_start_utc'])

    def register(self,batch,binding):
        if self.plan['carried']['sent_runs']+len(self.bindings)>=self.plan['bounds']['max_runs']:
            raise ValueError('Original plus recovery four-Run cap')
        super().register(batch,binding)

    def counters(self):
        counters=super().counters(); carried=self.plan['carried']
        for key in ('requests','observed_tokens','accumulated_run_seconds'):
            counters[key]+=carried[key]
        return counters


def create(repo,plan_path):
    path=live_pilot.safe_path(plan_path); plan=validate_plan(util.read_json(path),repo)
    remaining_wall(plan)
    base=live_pilot.safe_path(plan['batch']); ref=live_pilot.reference(path)
    base.mkdir(parents=False,exist_ok=False)
    util.write_new_json(base/'allocation.json',dict(kind=KIND,plan=ref,phase_id=plan['phase_id']))
    child=base/'pair-2'; child.mkdir()
    util.write_new_json(child/'phase.json',live_pilot.observer_phase(plan,ref,2))
    return dict(allocated=True,plan=ref,model_dispatched=False,original_pilot_adoption=False)


def execute(repo,plan_path,approval_path):
    from research import catalog_environment,next_phase
    path=live_pilot.safe_path(plan_path); plan=validate_plan(util.read_json(path),repo)
    ref=live_pilot.reference(path); approval_ref=live_pilot.reference(approval_path)
    remaining_wall(plan)
    approval=_reference_json(approval_ref)
    if (approval.get('plan_sha256')!=ref['sha256'] or approval.get('authorized') is not True
            or approval.get('approved_by')!='user' or not approval.get('authorization_reference')):
        raise ValueError('Exact recovery amendment authorization required')
    if next_phase.git(repo,'rev-parse','HEAD')!=plan['source_commit'] or next_phase.git(repo,'status','--porcelain'):
        raise ValueError('Clean exact committed recovery source required')
    catalog_environment.validate(_reference_json(plan['browser_pin']),repo)
    base=live_pilot.safe_path(plan['batch'])
    if util.read_json(base/'allocation.json')!=dict(kind=KIND,plan=ref,phase_id=plan['phase_id']):
        raise ValueError('Foreign recovery allocation')
    with pair_execution.exclusive(base/'_control'):
        util.write_new_json(base/'execution-intent.json',dict(plan_sha256=ref['sha256'],approval=approval_ref,
            phase_id=plan['phase_id'],started_at=run.now(),original_wall_start_utc=plan['original_wall_start_utc']))
        watch=RecoveryWatch(plan,ref['sha256']); watch.native_sessions=sealed_original(plan)[2]
        watch.start(); results=[]; joined=False; unchanged=False
        try:
            watch.check()
            results.append(live_pilot.execute_owned_pair_scope(repo,path,base/'pair-2/phase.json',budget_watch=watch))
            if results[0].get('reason')!='pair_publication_restore_cleanup_required':
                watch.latch('recovery_pair_not_operationally_complete')
            watch.check(); sealed_original(plan); unchanged=True
        except BaseException as exc:
            watch.latch(type(exc).__name__); raise
        finally:
            joined=watch.finish()
            if not joined and watch.fault is None: watch.fault={'reason':'watcher_shutdown_unconfirmed'}
            try: sealed_original(plan); unchanged=True
            except BaseException: unchanged=False; watch.fault=watch.fault or {'reason':'original_inventory_changed'}
            util.write_new_json(base/'result.json',dict(kind=KIND,plan_sha256=ref['sha256'],
                pair_results=results,fault=watch.fault,watcher_shutdown_verified=joined,
                finished_at=run.now(),
                original_unchanged=unchanged,original_pilot_adoption=False,publication_gates_complete=False,
                automatic_main_start=False,
                new_model_runs=len(pair_execution.state(base/'pair-2/_control/pair-journal.jsonl')['dispatch']),
                recovery_operational_complete=len(results)==1 and watch.fault is None and joined and unchanged))
    return util.read_json(base/'result.json')


def combined_consumed(plan):
    """Recompute ceilings from saved requests and durations; no stop writes."""
    child=Path(plan['batch'])/'pair-2'
    requests=plan['carried']['requests']; tokens=plan['carried']['observed_tokens']
    duration=plan['carried']['accumulated_run_seconds']
    for case in plan['assignments'][0]['cases']:
        root=child/case['run_id']; manifest=util.read_json(root/'manifest.json')
        starts,errors=live_pilot.live_usage.journal(root/'usage/raw/started.jsonl')
        events,more=live_pilot.live_usage.journal(root/'usage/raw/events.jsonl')
        seconds=manifest.get('duration_seconds')
        if (errors or more or type(seconds) not in (int,float) or not 0<=seconds<plan['bounds']['run_seconds']):
            raise ValueError('Recovery Run duration/request evidence invalid')
        requests+=len(starts); tokens+=sum(e['usage']['input_tokens']+e['usage']['output_tokens'] for e in events)
        duration+=seconds
    if (requests>=plan['bounds']['request_count'] or tokens>=plan['bounds']['observed_tokens']
            or duration>=plan['bounds']['accumulated_run_seconds']):
        raise ValueError('Combined original and recovery finite ceilings exceeded')
    return dict(requests=requests,observed_tokens=tokens,accumulated_run_seconds=duration)


def pipeline_evidence(repo,plan_ref,result_ref):
    from research import live_pilot_launcher
    plan=validate_plan(_reference_json(plan_ref),repo); result=_reference_json(result_ref)
    if (result_ref!=live_pilot.reference(Path(plan['batch'])/'result.json')
            or result.get('kind')!=KIND or result.get('plan_sha256')!=plan_ref['sha256']
            or result.get('recovery_operational_complete') is not True or result.get('fault') is not None
            or result.get('watcher_shutdown_verified') is not True or result.get('original_unchanged') is not True
            or result.get('original_pilot_adoption') is not False or result.get('automatic_main_start') is not False):
        raise ValueError('Recovery actual full pipeline is incomplete')
    finished=datetime.fromisoformat(result['finished_at']); start=datetime.fromisoformat(plan['original_wall_start_utc'])
    if finished.tzinfo is None or not 0<=(finished-start).total_seconds()<9000:
        raise ValueError('Recovery completion exceeded original durable deadline')
    # Same actual two-Run postprocessing/native/resource/observer proof as a main
    # child, but the top result is explicitly the separate recovery result.
    proof=live_pilot_launcher.verify_pair_terminal(repo,plan,plan_ref,2,result_ref)
    child=Path(plan['batch'])/'pair-2'; journal=pair_execution.state(child/'_control/pair-journal.jsonl')
    consumed=combined_consumed(plan)
    if result.get('new_model_runs')!=len(journal['dispatch']) or len(journal['dispatch'])!=2:
        raise ValueError('Actual recovery two-Run dispatch count differs')
    original_natives=sealed_original(plan)[2]
    saved=util.read_json(Path(plan['batch'])/'pair-2/owned-terminal-proof.json')
    if original_natives & {r['native_session_id'] for r in saved['runs']}:
        raise ValueError('Original and recovery native sessions collide')
    return dict(ready=True,plan=plan_ref,result=result_ref,model_runs=4,new_model_runs=2,
        saved_music_postprocessing=plan['saved_music_postprocessing'],original_plan=plan['original_plan'],
        original_closeout=plan['original_closeout'],original_pilot_adoption=False,
        consumed=consumed,
        new_main_authorized=False,product_quality_guaranteed=False)


def ready(repo,plan_ref,result_ref):
    from research import live_pilot_launcher
    proof=pipeline_evidence(repo,plan_ref,result_ref)
    plan=_reference_json(plan_ref)
    launcher=live_pilot_launcher.validate_launcher_terminal(repo,plan,plan_ref,proof,controller_module='research.readiness_recovery')
    return {**proof,**launcher}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('create','execute','check'))
    parser.add_argument('plan',type=Path); parser.add_argument('--repo',type=Path,required=True)
    parser.add_argument('--approval',type=Path)
    args=parser.parse_args()
    if args.action=='create': return create(args.repo,args.plan)
    if args.action=='check': return ready(args.repo,live_pilot.reference(args.plan),live_pilot.reference(Path(util.read_json(args.plan)['batch'])/'result.json'))
    if args.approval is None: parser.error('--approval is required for execute')
    return execute(args.repo,args.plan,args.approval)


if __name__=='__main__': main()
