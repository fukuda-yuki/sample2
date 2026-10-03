"""Fixed four-slot technical cohort. Never a research acquisition/resume CLI."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
import threading
import time

IMPORT_REPO=Path(sys.argv[sys.argv.index('--repo')+1]) if '--repo' in sys.argv else Path(__file__).resolve().parents[2]
sys.path.insert(0,str(IMPORT_REPO.resolve()))
from outer.harness import live_usage, machine, profiles, runtime, util
from research import pair_execution


def measurement(root,cases,elapsed):
    manifests=[]; calls=[]
    for case in cases:
        base=root/case['run_id']
        if not (base/'manifest.json').exists(): continue
        manifests.append(util.read_json(base/'manifest.json'))
        ends,_=live_usage.journal(base/'usage/raw/events.jsonl'); calls+=ends
    starts=[datetime.fromisoformat(m['started_at']) for m in manifests if m.get('started_at')]
    ends=[datetime.fromisoformat(m['ended_at']) for m in manifests if m.get('ended_at')]
    timed=[(datetime.fromisoformat(e['transmitted_at']),1) for e in calls if e.get('transmitted_at')]
    timed +=[(datetime.fromisoformat(e['ended_at']),-1) for e in calls if e.get('transmitted_at') and e.get('ended_at')]
    concurrent=peak=0
    for stamp,delta in sorted(timed): concurrent+=delta; peak=max(peak,concurrent)
    return {'local_pair_elapsed_seconds':elapsed,
        'pair_implementation_makespan_seconds':(max(ends)-min(starts)).total_seconds() if starts and ends else None,
        'start_difference_seconds':(max(starts)-min(starts)).total_seconds() if len(starts)==2 else None,
        'implementation_overlap_seconds':max(0,(min(ends)-max(starts)).total_seconds()) if len(starts)==len(ends)==2 else None,
        'observed_peak_local_http_concurrency':peak,'gateway_calls':len(calls),
        'http_latency_seconds':[(datetime.fromisoformat(e['ended_at'])-datetime.fromisoformat(e['transmitted_at'])).total_seconds()
                               for e in calls if e.get('transmitted_at') and e.get('ended_at')],
        'gateway_errors':[{'request_id':e['request_id'],'status':e['status']} for e in calls if e['status']!='completed'],
        'run_durations':{m['run_id']:m.get('duration_seconds') for m in manifests},
        'public_gate_elapsed_seconds':None,'public_gate_state':'not_run'}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--repo',type=Path,default=Path(__file__).resolve().parents[2])
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--mock-receipt',type=Path,required=True)
    p.add_argument('--mode',choices=('prepare','execute'),default='prepare')
    a=p.parse_args(); repo=a.repo.resolve(); batch=a.out.resolve()
    template=repo/'research/protocols/technical-pair-live-20261003.json'
    selected=util.read_json(template)
    mock=util.read_json(a.mock_receipt)
    if not mock.get('passed') or mock.get('real_model_calls')!=0:
        raise ValueError('Ordinary worker mock acceptance must pass before this finite live cohort')
    actual=[r for r in mock['results'] if r['case'] in ('actual-explore','actual-preload')]
    if len(actual)!=2 or not all(r.get('ordinary_opencode_worker') for r in actual):
        raise ValueError('Both actual-worker arm serialization receipts are required')
    task,runtime_id=selected['task'],selected['runtime']
    expected=machine.expected_conditions(repo,task,runtime_id,('explore','preload'))
    lock=util.read_json(profiles.runtime_root(repo,task,profiles.read(repo,'runtimes',runtime_id))/'lock.json')
    if runtime.controller_files(repo)!=lock['controller_files']:
        raise ValueError('Prepared controller differs from current code')
    if a.mode=='prepare':
        batch.mkdir(parents=True,exist_ok=False)
        plan={**selected,'prepared_lock_sha256':machine.fingerprint(lock),'conditions':expected,
            'template_sha256':util.sha256_file(template),'mock_receipt':str(a.mock_receipt.resolve()),
            'mock_receipt_sha256':util.sha256_file(a.mock_receipt),
            'source_commit':runtime.command(['git','rev-parse','HEAD'],cwd=repo).stdout.strip(),
            'controller_files':runtime.controller_files(repo),'created_at':live_usage.run.now()}
        util.write_new_json(batch/'plan.json',plan)
        print(json.dumps({'prepared':True,'plan':str(batch/'plan.json'),'plan_sha256':util.sha256_file(batch/'plan.json'),
                          'model_dispatched':False})); return 0
    plan=util.read_json(batch/'plan.json')
    if (plan['conditions']!=expected or plan['prepared_lock_sha256']!=machine.fingerprint(lock)
            or plan['controller_files']!=runtime.controller_files(repo)
            or plan['mock_receipt_sha256']!=util.sha256_file(a.mock_receipt)
            or plan['template_sha256']!=util.sha256_file(template)):
        raise ValueError('Frozen technical conditions/evidence changed')
    if (batch/'execution-intent.json').exists():
        raise ValueError('Technical cohort already dispatched or uncertain; no replay or passing retry')
    util.write_new_json(batch/'execution-intent.json',{'at':live_usage.run.now(),
        'plan_sha256':util.sha256_file(batch/'plan.json'),'authorization':plan['authorization']})
    done=threading.Event(); stop_reason=[]; owner={}; metrics=[]
    safety=plan['limits']
    def watch():
        next_stats=0
        while not done.wait(1):
            observed=count=0; accumulated=0; fault=None; active=[]
            for rid,instance in list(owner.items()):
                root=batch/rid
                starts,se=live_usage.journal(root/'usage/raw/started.jsonl')
                ends,ee=live_usage.journal(root/'usage/raw/events.jsonl')
                count+=len(starts)
                for e in ends:
                    usage=e.get('usage') or {}
                    vals=[usage.get(k) for k in ('input_tokens','output_tokens')]
                    observed+=sum(v for v in vals if type(v) is int and v>=0)
                    if any(v is None for v in vals) or e.get('status')!='completed': fault='provider_or_missing_usage'
                    if e.get('session_id')!=instance: fault='identity_fault'
                if se or ee: fault='damaged_journal'
                if (root/'usage/raw/failure.jsonl').exists(): fault='provider_fault'
                if (root/'manifest.json').exists():
                    m=util.read_json(root/'manifest.json')
                    if m.get('run_instance_id')!=instance: fault='identity_fault'
                    if m.get('started_at') and not m.get('stop_confirmed'): active.append(root)
                    if m.get('duration_seconds') is not None: accumulated+=m['duration_seconds']
                    elif m.get('started_at'):
                        from datetime import timezone
                        accumulated+=(datetime.now(timezone.utc)-datetime.fromisoformat(m['started_at'])).total_seconds()
            if count>=safety['gateway_started_calls_stop']: fault='call_safety_limit'
            if observed>=safety['reported_observed_tokens_stop']: fault='observed_token_safety_limit'
            if accumulated>=safety['maximum_accumulated_run_seconds']: fault='run_time_safety_limit'
            if fault and not stop_reason:
                stop_reason.append(fault)
                util.write_new_json(batch/'safety-stop.json',{'reason':fault,'calls':count,'accumulated_run_seconds':accumulated,
                    'observed_reported_tokens':observed,'at':live_usage.run.now(),'totals_may_be_incomplete':True})
                for root in active: runtime.request_stop(root)
            if time.monotonic()>=next_stats:
                next_stats=time.monotonic()+10
                names=[]
                for root in active:
                    if (root/'runtime.json').exists(): names.append(util.read_json(root/'runtime.json')['worker'])
                if names:
                    result=runtime.docker('stats','--no-stream','--format','{{json .}}',*names,check=False,timeout=20)
                    util.append_line(batch/'resource-samples.jsonl',{'at':live_usage.run.now(),
                        'names':names,'exit_code':result.returncode,'stdout':result.stdout,'stderr':result.stderr})
    def safe_watch():
        try: watch()
        except Exception as exc:
            stop_reason.append('safety_monitor_fault:'+type(exc).__name__)
            for rid in list(owner):
                root=batch/rid
                try: runtime.request_stop(root)
                except Exception: pass
    watcher=threading.Thread(target=safe_watch,daemon=True); watcher.start()
    results=[]
    try:
        for order in plan['order']:
            if stop_reason: break
            cases=[{'run_id':f"{task}-{arm}-{order['attempt']:03d}",'task':task,'condition':arm,
                'attempt':order['attempt'],'pair':order['pair'],'slot':2*(order['pair']-1)+i}
                for i,arm in enumerate(order['conditions'],1)]
            descriptor={'cohort':plan['cohort']+('-serial' if order['concurrency']==1 else '-paired'),
                        'plan_sha256':util.sha256_file(batch/'plan.json'),'runtime':runtime_id}
            # Separate managers/cohort paths for the two execution-regime blocks;
            # the public gate remains pending for each. No fake gate bypass.
            pair_batch=batch/('serial' if order['concurrency']==1 else 'paired')
            pair_batch.mkdir(exist_ok=False)
            def prepare_in_block(binding):
                manifest=profiles.create(repo,pair_batch,task,binding['condition'],binding['attempt'],runtime_id,
                    run_instance_id=binding['run_instance_id'],assignment=binding)
                machine.verify_conditions(pair_batch/manifest['run_id'],expected,binding['condition'])
                owner[str(Path(pair_batch.name)/manifest['run_id'])]=manifest['run_instance_id']; return manifest
            block_cases=[{**c,'pair':1,'slot':i} for i,c in enumerate(cases,1)]
            start=time.monotonic()
            result=pair_execution.execute_pair(descriptor,block_cases,pair_batch,repo=repo,
                concurrency=order['concurrency'],prepare=prepare_in_block)
            measured=measurement(pair_batch,block_cases,time.monotonic()-start)
            receipt={'regime':'serial' if order['concurrency']==1 else 'paired','result':result,'measurement':measured}
            util.write_new_json(batch/f"result-block-{order['pair']}.json",receipt); results.append(receipt)
            print(json.dumps(receipt),flush=True)
            if result['reason']!='pair_publication_restore_cleanup_required': break
    except Exception as exc:
        stop_reason.append('campaign_fault:'+type(exc).__name__)
        util.write_new_json(batch/'campaign-failure.json',{'type':type(exc).__name__,
            'results_completed':len(results),'replacement_authorized':False})
    finally:
        done.set(); watcher.join(timeout=60)
    complete=len(results)==2 and all(r['result']['reason']=='pair_publication_restore_cleanup_required' for r in results)
    improvement=(results[1]['measurement']['local_pair_elapsed_seconds']<results[0]['measurement']['local_pair_elapsed_seconds']) if complete else None
    receipt={'cohort':plan['cohort'],'results':results,'fixed_maximum_dispatches':4,
        'dispatches':sum(len(pair_execution.state(batch/n/'_control/pair-journal.jsonl')['dispatch'])
                         for n in ('serial','paired') if (batch/n/'_control/pair-journal.jsonl').exists()),
        'stop_reasons':stop_reason,'complete_technical_local_blocks':complete,
        'local_elapsed_improved':improvement,'public_gate_acceptance':'not_run',
        'paired_overall_acceptance':False,'distribution_equivalence_proven':False,'new_research_started':False}
    util.write_new_json(batch/'result.json',receipt); print(json.dumps(receipt)); return 0 if complete else 1


if __name__=='__main__': sys.exit(main())
