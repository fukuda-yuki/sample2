"""Independent two-Run Education technical trial; historical attempts stay sealed.

Only its launcher intent starts its new 5400-second inclusive window. The
5160-second observed cutoff reserves 240 seconds for owned cleanup. Import,
create and validation never dispatch a model. No retry, replacement or main
start is provided. Numerical product failures remain valid observations.
"""
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re

from outer.harness import run, util
from research import live_pilot, pair_execution, readiness_recovery

KIND = 'education_go_readiness_trial_v1'
OBSERVER_KIND = 'education_go_readiness_trial_observer_v1'
WHOLE_SECONDS = 5400
CLEANUP_SECONDS = 240
BOUNDS = {**live_pilot.BOUNDS, 'max_pairs':1, 'max_runs':2,
          'accumulated_run_seconds':3600, 'request_count':460,
          'observed_tokens':18053732, 'wall_seconds':5160}
EXTRA_PINS = ('research/education_readiness_trial.py',
              'research/readiness_recovery.py', 'research/saved_postprocessing_recovery.py')
CONSUMED = dict(request_count=140, observed_tokens=11946268)


def document(ref):
    return util.read_json(live_pilot.checked(ref))


def launch_origin(plan, ref):
    intent=util.read_json(live_pilot.safe_path(Path(plan['batch'])/'_launcher/intent.json'))
    start=datetime.fromisoformat(intent['started_at'])
    if (intent.get('plan')!=ref or intent.get('phase_id')!=plan['phase_id']
            or start.tzinfo is None or start>datetime.now(timezone.utc)
            or intent.get('whole_deadline_utc')!=(start+timedelta(seconds=WHOLE_SECONDS)).isoformat()
            or intent.get('wall_threshold_seconds')!=BOUNDS['wall_seconds']
            or type(intent.get('wall_threshold_seconds')) is not int
            or intent.get('cleanup_reserve_seconds')!=CLEANUP_SECONDS
            or type(intent.get('cleanup_reserve_seconds')) is not int):
        raise ValueError('Bound fresh trial launcher origin and inclusive deadline required')
    return intent['started_at']


def remaining_wall(plan,ref):
    start=datetime.fromisoformat(launch_origin(plan,ref))
    remaining=BOUNDS['wall_seconds']-(datetime.now(timezone.utc)-start).total_seconds()
    if remaining<=0: raise TimeoutError('Independent trial observed wall exhausted')
    return remaining


def validate_cases(plan,old):
    assignments=plan.get('assignments')
    if (not isinstance(assignments,list) or len(assignments)!=1
            or type(assignments[0].get('pair')) is not int or assignments[0]['pair']!=1
            or len(assignments[0].get('cases',[]))!=2):
        raise ValueError('Exactly one independent Education pair required')
    protected={c['run_instance_id'] for p in old['assignments'] for c in p['cases']}
    from research.acquisition_readiness import protected_instance_ids
    protected|=protected_instance_ids()
    ids=set(); lineage=[]
    for slot,(case,source,arm) in enumerate(zip(assignments[0]['cases'],old['assignments'][1]['cases'],('explore','preload')),1):
        expected=dict(pair=1,slot=slot,task='CU1-ENR-C',condition=arm,attempt=7001,
                      run_id=run.run_id_for('CU1-ENR-C',arm,7001))
        rid=case.get('run_instance_id','')
        if ({k:v for k,v in case.items() if k!='run_instance_id'}!=expected
                or any(type(case.get(k)) is not int for k in ('pair','slot','attempt'))
                or not re.fullmatch('[a-f0-9]{32}',rid) or rid in protected|ids
                or rid==plan['phase_id']):
            raise ValueError('Fresh exact Education trial case/UUID required')
        ids.add(rid); lineage.append(dict(run_instance_id=rid,source_case=source))
        child=live_pilot.safe_path(Path(plan['batch'])/'pair-1')
        live_pilot.safe_path(run.run_dir_for(child,case['run_id']))
    if plan.get('case_lineage')!=lineage: raise ValueError('Exact sealed source-case lineage required')
    return ids


def sealed_sources(plan):
    old=document(plan['original_plan'])
    # This context is only a read-only historical proof check. It is never a
    # dispatched plan, watcher scope or restarted old recovery intent.
    context={**plan,'assignments':[old['assignments'][1]]}
    old,closure,natives=readiness_recovery.sealed_original(context)
    readiness_recovery.validate_prior_recoveries(context)
    close=document(plan['prepared_no_send_closeout']); prior=document(close['prior_plan'])
    root=live_pilot.safe_path(prior['batch'])
    cases=old['assignments'][1]['cases']
    if (close.get('kind')!='finite_pilot_no_send_reserve_stop_closeout_v1'
            or type(close.get('schema_version')) is not int or close['schema_version']!=1
            or close.get('original_plan')!=plan['original_plan']
            or close.get('original_seal')!=plan['original_closeout']
            or prior.get('kind')!=readiness_recovery.KIND or prior.get('original_plan')!=plan['original_plan']
            or prior.get('assignments')!=[old['assignments'][1]]
            or prior.get('carried')!=context['carried']
            or prior.get('original_wall_start_utc')!=closure['original_wall_start_utc']
            or prior.get('phase_id')==plan['phase_id'] or prior.get('cohort')==plan.get('cohort')
            or close.get('original_wall_start_utc')!=closure['original_wall_start_utc']
            or close.get('consumed')!=dict(request_count=140,observed_tokens=11946268,run_seconds=2102.502)
            or close.get('original_unchanged') is not True or close.get('failure_preserved') is not True
            or close.get('previous_zero_send_attempt_unchanged') is not True
            or close.get('ready') is not False or close.get('new100_dispatched') is not False
            or close.get('model_replay_authorized') is not False
            or type(close.get('logical_new_sent_runs')) is not int or close['logical_new_sent_runs']!=0
            or close.get('observer_ack_confirmed') is not True
            or type(close.get('observer_exit_code')) is not int or close['observer_exit_code']!=0
            or close.get('scoped_process_matches')!=[] or close.get('no_owned_runtime_resources') is not True
            or live_pilot.safe_path(close['failed_batch'])!=root
            or not any(live_pilot.safe_path(p)==root for p in plan['protected_roots'])
            or close.get('prepared_case_count')!=2 or type(close.get('prepared_case_count')) is not int):
        raise ValueError('Prepared prior Education attempt is not independently sealed zero-send')
    if util.tree_hashes(root)!=document(close['inventory']): raise ValueError('Prepared prior bytes changed')
    expected=[dict(run_id=c['run_id'],run_instance_id=c['run_instance_id'],profiles_prepared=True,
        model_dispatched=False,runtime_allocated=False,http_requests=0,sdk_telemetry_present=False,
        stopped_not_claimed=True) for c in cases]
    if close.get('prepared_unexecuted_cases')!=expected: raise ValueError('Exact two prepared unsent cases required')
    if pair_execution.state(root/'pair-2/_control/pair-journal.jsonl')['dispatch']:
        raise ValueError('Previous Education dispatched')
    for field,relative in (('result','result.json'),('launcher_result','_launcher/result.json'),
                           ('observer_terminal','pair-2/observer-terminal.json')):
        if live_pilot.checked(close[field])!=root/relative: raise ValueError('Foreign prior terminal')
    result=document(close['result']); launched=document(close['launcher_result']); terminal=document(close['observer_terminal'])
    registration=util.read_json(root/'_launcher/registration.json'); child=launched.get('child',{})
    if (result.get('new_model_runs')!=0 or type(result.get('new_model_runs')) is not int
            or result.get('recovery_operational_complete') is not False
            or result.get('watcher_shutdown_verified') is not True
            or launched.get('operational_complete') is not False or launched.get('plan')!=close['prior_plan']
            or registration.get('plan')!=close['prior_plan']
            or type(registration.get('child_pid')) is not int or registration['child_pid']<=0
            or type(launched.get('child_pid')) is not int or launched['child_pid']!=registration['child_pid']
            or type(child.get('pid')) is not int or child['pid']!=registration['child_pid']
            or any(type(child.get(k)) is not int or child[k]!=1 for k in ('initial_exit_code','exit_code'))
            or any(child.get(k) is not False for k in ('unknown','terminated','killed'))
            or terminal.get('observer_ack_verified') is not True or terminal.get('observer_exit_code')!=0
            or type(terminal.get('observer_exit_code')) is not int):
        raise ValueError('Prior failure or observer closure lost')
    directory=live_pilot.safe_path(terminal['directory']);phase_ref=live_pilot.reference(root/'pair-2/phase.json')
    if (terminal.get('plan')!=close['prior_plan'] or terminal.get('phase')!=phase_ref
            or directory.parent!=live_pilot.safe_path(root/'_observers') or directory.name!=terminal.get('session')
            or type(terminal.get('observer_pid')) is not int or terminal['observer_pid']<=0
            or type(terminal.get('generation')) is not int or terminal['generation']<=0):
        raise ValueError('Prepared prior observer identity differs')
    pins=terminal.get('evidence_files',{})
    if not {'config.json','shutdown.json','shutdown-ack.json','status.json','startup-ready.json'}<=pins.keys():
        raise ValueError('Prepared prior observer source evidence missing')
    for name,sha in pins.items():
        if (Path(name).is_absolute() or '..' in Path(name).parts or ':' in name or '\\' in name
                or util.sha256_file(live_pilot.safe_path(directory/name))!=sha):
            raise ValueError('Prepared prior observer evidence changed')
    config=util.read_json(directory/'config.json');request=util.read_json(directory/'shutdown.json');ack=util.read_json(directory/'shutdown-ack.json')
    expected=dict(session=terminal['session'],generation=terminal['generation'],phase_sha256=phase_ref['sha256'])
    if (config.get('session')!=terminal['session'] or config.get('phase')!=phase_ref
            or live_pilot.safe_path(config['directory'])!=directory or request.get('dispatched')!=[]
            or any(v.get(k)!=x for v in (request,ack) for k,x in expected.items())
            or ack.get('owned_resources_resolved') is not True or ack.get('monitor_stop_confirmed') is not True):
        raise ValueError('Prepared prior observer actual shutdown ACK differs')
    observations=close.get('resource_observations',[])
    wanted={(kind,c['run_instance_id']) for kind in ('containers','networks') for c in cases}
    if (len(observations)!=4 or {(r.get('kind'),r.get('run_instance_id')) for r in observations}!=wanted
            or any(r.get('matches')!=[] for r in observations)):
        raise ValueError('Prepared prior resource absence scope differs')
    pre=document(plan['zero_send_precheck'])
    if (pre.get('kind')!='education_independent_trial_zero_send_precheck_v1'
            or pre.get('source_plan')!=close['prior_plan'] or pre.get('source_closeout')!=plan['prepared_no_send_closeout']
            or pre.get('source_tree_unchanged') is not True or pre.get('scoped_process_matches')!=[]
            or pre.get('new_model_runs')!=0 or type(pre.get('new_model_runs')) is not int
            or pre.get('original_clock_unchanged') is not True or pre.get('old_intents_replay_authorized') is not False
            or pre.get('new100_dispatched') is not False or pre.get('baseline_consumed')!=CONSUMED
            or pre.get('remaining_caps')!=dict(request_count=BOUNDS['request_count'],observed_tokens=BOUNDS['observed_tokens'])
            or len(pre.get('cases',[]))!=2):
        raise ValueError('Native no-SDK/HTTP/resource precheck required')
    hashes={};inputs={}
    for item,case in zip(pre['cases'],cases):
        prepared=root/'pair-2'/case['run_id']
        if (item.get('source_case')!=case or live_pilot.safe_path(item['prepared_root'])!=prepared
                or any(item.get(k) is not False for k in ('sdk_sent','http_sent','runtime_allocated'))
                or item.get('containers')!=[] or item.get('networks')!=[]
                or live_pilot.checked(item['manifest'])!=prepared/'manifest.json'
                or live_pilot.checked(item['condition'])!=prepared/'condition.json'):
            raise ValueError('Native prepared source-case join differs')
        manifest=document(item['manifest']); condition=document(item['condition'])
        live_pilot.profiles.validate_run(prepared)
        if (manifest.get('run_instance_id')!=case['run_instance_id']
                or manifest.get('condition_sha256')!=item['condition']['sha256']
                or condition.get('task_id')!=case['task'] or condition.get('condition_id')!=case['condition']):
            raise ValueError('Prepared original identity/input join differs')
        if util.sha256_file(prepared/'inputs/prompt.txt')!=manifest['prompt_sha256']:
            raise ValueError('Original prepared prompt bytes differ')
        for name in ('runtime.json','evidence/agent.jsonl','usage/raw/started.jsonl','sdk-telemetry.json'):
            if (prepared/name).exists(): raise ValueError('Prepared case has runtime/SDK/HTTP evidence')
        hashes[case['condition']]=manifest['prompt_sha256']
        inputs[case['condition']]=manifest['input_files']
    if plan.get('expected_input_sha256_by_arm')!=hashes: raise ValueError('Frozen original Education input hashes required')
    if plan.get('expected_input_files_by_arm')!=inputs:raise ValueError('Frozen complete original Education input inventories required')
    return old,natives


def validate_plan(plan,repo):
    if (plan.get('kind')!=KIND or type(plan.get('schema_version')) is not int or plan['schema_version']!=1
            or plan.get('independent_technical_trial') is not True or plan.get('old_pilot_adoption') is not False
            or plan.get('sent_run_replay_authorized') is not False
            or plan.get('bounds')!=BOUNDS or any(type(plan['bounds'][k]) is not int for k in BOUNDS)
            or type(plan.get('whole_seconds')) is not int or plan['whole_seconds']!=WHOLE_SECONDS
            or type(plan.get('cleanup_reserve_seconds')) is not int or plan['cleanup_reserve_seconds']!=CLEANUP_SECONDS
            or not set(EXTRA_PINS)<=plan.get('source_pins',{}).keys()):
        raise ValueError('Explicit fixed independent two-Run trial required')
    old=document(plan['original_plan'])
    # Common source/namespace/model/path guards validate the original fixed
    # assignments read-only; the actual trial cases and smaller bounds follow.
    live_pilot.validate_plan({**plan,'kind':live_pilot.KIND,'bounds':live_pilot.BOUNDS,
                             'assignments':old['assignments']},repo)
    validate_cases(plan,old)
    if (plan['phase_id']==old['phase_id'] or plan['cohort']==old['cohort']
            or plan['settings']!=old['settings'] or plan['task_revision']!=old['task_revision']
            or plan['runtime_by_task']!=old['runtime_by_task']
            or not any(live_pilot.safe_path(p)==live_pilot.safe_path(old['batch']) for p in plan['protected_roots'])
            or any(plan['source_pins'].get(n)!=old['source_pins'].get(n)
                   for n in live_pilot.PIN_FILES if n.endswith('.json'))):
        raise ValueError('Unamended source semantics and fresh protected owner required')
    sealed_sources(plan)
    from research.saved_postprocessing_recovery import validate_saved_music_postprocessing
    rows=validate_saved_music_postprocessing(repo,plan['saved_music_postprocessing'],plan['original_plan'])
    if (len(rows)!=2 or {r['source_run_instance_id'] for r in rows}!={c['run_instance_id'] for c in old['assignments'][0]['cases']}
            or len({r['assessment_id'] for r in rows})!=2
            or any(r.get('model_dispatch_count')!=0 or type(r.get('model_dispatch_count')) is not int
                   or r.get('acquisition_count_increment')!=0 or type(r.get('acquisition_count_increment')) is not int
                   or r.get('original_pilot_adoption') is not False for r in rows)):
        raise ValueError('Current separately saved Music technical proof required')
    if live_pilot.checked(plan['launch_supervisor'])!=live_pilot.safe_path(repo)/'research/live_pilot_launcher.py':
        raise ValueError('Reviewed trial external launcher required')
    return plan


def validate_input(plan,binding,manifest):
    arm=binding['condition']
    if (binding['input_sha256']!=plan['expected_input_sha256_by_arm'][arm]
            or manifest['input_files']!=plan['expected_input_files_by_arm'][arm]):
        raise ValueError('Trial full inputs differ from sealed original Education case')


class TrialWatch(live_pilot.PilotWatch):
    """Only new trial resources and counters are enrolled, never sealed roots."""
    def __init__(self,plan,digest,*,wall_started_at):
        super().__init__(plan,digest,wall_started_at=wall_started_at)


def create(repo,plan_path):
    path=live_pilot.safe_path(plan_path); plan=validate_plan(util.read_json(path),repo)
    ref=live_pilot.reference(path); base=live_pilot.safe_path(plan['batch'])
    base.mkdir(parents=False,exist_ok=False)
    util.write_new_json(base/'allocation.json',dict(kind=KIND,plan=ref,phase_id=plan['phase_id']))
    child=base/'pair-1';child.mkdir()
    util.write_new_json(child/'phase.json',live_pilot.observer_phase(plan,ref,1))
    return dict(allocated=True,plan=ref,model_dispatched=False,old_pilot_adoption=False)


def execute(repo,plan_path,approval_path):
    from research import next_phase,catalog_environment
    path=live_pilot.safe_path(plan_path);plan=validate_plan(util.read_json(path),repo)
    ref=live_pilot.reference(path);approval_ref=live_pilot.reference(approval_path);approval=document(approval_ref)
    remaining_wall(plan,ref)
    if (approval.get('scope')!='education_two_run_technical_trial' or approval.get('plan_sha256')!=ref['sha256']
            or approval.get('authorized') is not True or approval.get('approved_by')!='user'
            or not approval.get('authorization_reference')):
        raise ValueError('Exact independent Education two-Run authorization required')
    if next_phase.git(repo,'rev-parse','HEAD')!=plan['source_commit'] or next_phase.git(repo,'status','--porcelain'):
        raise ValueError('Clean exact committed trial source required')
    catalog_environment.validate(document(plan['browser_pin']),repo)
    base=live_pilot.safe_path(plan['batch'])
    if util.read_json(base/'allocation.json')!=dict(kind=KIND,plan=ref,phase_id=plan['phase_id']):
        raise ValueError('Foreign trial allocation')
    with pair_execution.exclusive(base/'_control'):
        util.write_new_json(base/'execution-intent.json',dict(plan_sha256=ref['sha256'],approval=approval_ref,
            phase_id=plan['phase_id'],started_at=run.now(),launcher_started_at=launch_origin(plan,ref)))
        watch=TrialWatch(plan,ref['sha256'],wall_started_at=launch_origin(plan,ref))
        watch.native_sessions=sealed_sources(plan)[1];watch.start();results=[];unchanged=False
        try:
            watch.check();results.append(live_pilot.execute_owned_pair_scope(repo,path,base/'pair-1/phase.json',budget_watch=watch))
            if results[0].get('reason')!='pair_publication_restore_cleanup_required':watch.latch('trial_pair_incomplete')
            watch.check();sealed_sources(plan);unchanged=True
        except BaseException as exc:
            watch.latch(type(exc).__name__);raise
        finally:
            joined=watch.finish()
            if not joined and watch.fault is None:watch.fault={'reason':'watcher_shutdown_unconfirmed'}
            try:sealed_sources(plan);unchanged=True
            except BaseException:unchanged=False;watch.fault=watch.fault or {'reason':'sealed_history_changed'}
            util.write_new_json(base/'result.json',dict(kind=KIND,plan_sha256=ref['sha256'],pair_results=results,
                fault=watch.fault,watcher_shutdown_verified=joined,finished_at=run.now(),old_pilot_adoption=False,
                original_unchanged=unchanged,publication_gates_complete=False,automatic_main_start=False,
                new_model_runs=len(pair_execution.state(base/'pair-1/_control/pair-journal.jsonl')['dispatch']),
                trial_operational_complete=len(results)==1 and watch.fault is None and joined and unchanged))
    return util.read_json(base/'result.json')


def validate_elapsed(start,finish):
    start,finish=datetime.fromisoformat(start),datetime.fromisoformat(finish)
    if start.tzinfo is None or finish.tzinfo is None or not 0<=(finish-start).total_seconds()<=WHOLE_SECONDS:
        raise ValueError('Trial inclusive 5400-second deadline exceeded')
    return (finish-start).total_seconds()


def pipeline_evidence(repo,plan_ref,result_ref):
    from research import live_pilot_launcher
    plan=validate_plan(document(plan_ref),repo);result=document(result_ref)
    if (result_ref!=live_pilot.reference(Path(plan['batch'])/'result.json') or result.get('kind')!=KIND
            or result.get('plan_sha256')!=plan_ref['sha256'] or result.get('trial_operational_complete') is not True
            or result.get('fault') is not None or result.get('watcher_shutdown_verified') is not True
            or result.get('original_unchanged') is not True or result.get('old_pilot_adoption') is not False
            or result.get('automatic_main_start') is not False or type(result.get('new_model_runs')) is not int
            or result['new_model_runs']!=2):raise ValueError('Actual trial full pipeline incomplete')
    validate_elapsed(launch_origin(plan,plan_ref),result['finished_at'])
    live_pilot_launcher.verify_pair_terminal(repo,plan,plan_ref,1,result_ref)
    watch=TrialWatch(plan,plan_ref['sha256'],wall_started_at=launch_origin(plan,plan_ref))
    journal=pair_execution.state(Path(plan['batch'])/'pair-1/_control/pair-journal.jsonl')
    if len(journal['dispatch'])!=2:raise ValueError('Actual two fresh trial dispatches required')
    for binding in journal['dispatch'].values():
        root=Path(plan['batch'])/'pair-1'/binding['run_id'];seconds=util.read_json(root/'manifest.json').get('duration_seconds')
        if type(seconds) not in (int,float) or not 0<=seconds<BOUNDS['run_seconds']:
            raise ValueError('Trial per-Run duration ceiling exceeded')
        watch.restore_completed(Path(plan['batch'])/'pair-1',[binding])
    observed=watch.counters()
    # Frozen terminal proof is recomputable weeks later. Live disk/wall samples
    # remain observer evidence, and must not contaminate proof equality.
    consumed={key:observed[key] for key in ('requests','observed_tokens','accumulated_run_seconds')}
    if any(consumed[k]>=BOUNDS[b] for k,b in [('requests','request_count'),('observed_tokens','observed_tokens'),
                                           ('accumulated_run_seconds','accumulated_run_seconds')]):
        raise ValueError('Trial remaining finite ceilings exceeded')
    if watch.native_sessions & sealed_sources(plan)[1]:raise ValueError('Trial reused original Music native session')
    return dict(ready=True,plan=plan_ref,result=result_ref,new_model_runs=2,model_runs=2,
        technical_cases=4,saved_music_postprocessing=plan['saved_music_postprocessing'],original_plan=plan['original_plan'],
        old_pilot_adoption=False,independent_technical_trial=True,consumed=consumed,
        new_main_authorized=False,product_quality_guaranteed=False)


def ready(repo,plan_ref,result_ref):
    from research import live_pilot_launcher
    proof=pipeline_evidence(repo,plan_ref,result_ref)
    return {**proof,**live_pilot_launcher.validate_launcher_terminal(repo,document(plan_ref),plan_ref,proof,
        controller_module='research.education_readiness_trial')}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('create','execute','check'));parser.add_argument('plan',type=Path)
    parser.add_argument('--repo',type=Path,required=True);parser.add_argument('--approval',type=Path)
    args=parser.parse_args()
    if args.action=='create':return create(args.repo,args.plan)
    if args.action=='check':return ready(args.repo,live_pilot.reference(args.plan),live_pilot.reference(Path(util.read_json(args.plan)['batch'])/'result.json'))
    if args.approval is None:parser.error('--approval required for execute')
    return execute(args.repo,args.plan,args.approval)


if __name__=='__main__':main()
