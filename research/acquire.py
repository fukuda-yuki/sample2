"""Bounded research batch driver around the unchanged ordinary harness CLI.

The frozen JSON plan is the only schedule. A dispatch is journaled before the
CLI starts. A second invocation refuses the same batch; no uncertain Run is
silently replayed. This script adds no agent or evaluator capability.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from outer.harness import aggregate, machine, preserve, profiles, runtime
from outer.harness.security import child_environment
from research.analyze import read_json, sha, write_json, journal


def now():
    return datetime.now(timezone.utc).isoformat()


def append(path, entry):
    with Path(path).open('a', encoding='utf-8', newline='\n') as f:
        f.write(json.dumps({'at':now(), **entry}, ensure_ascii=False) + '\n')
        f.flush()
        os.fsync(f.fileno())


def disposition(root, row, exit_code):
    manifest=read_json(root/'manifest.json')
    usage=read_json(root/'usage/normalized.json') if (root/'usage/normalized.json').exists() else {}
    events=[e for _,e in journal(root/'usage/raw/events.jsonl')[0]]
    statuses={e.get('http_status') for e in events}
    if statuses & {401,402,403,429}:
        return 'halt', 'authentication_or_quota_http'
    if any(e.get('policy_error') or (e.get('response_model_id') and e['response_model_id']!='deepseek-v4.1-flash') for e in events):
        return 'halt', 'model_or_policy_mismatch'
    if not manifest.get('stop_confirmed'):
        return 'halt', 'stop_unconfirmed'
    isolation=root/'evidence/isolation.json'
    if not isolation.exists() or not read_json(isolation).get('verified'):
        return 'halt', 'isolation_not_verified'
    issues=usage.get('inventory_issues',[])
    if any(any(word in s for word in ('identity','duplicate','original_mismatch','changed','model')) for s in issues):
        return 'halt', 'identity_or_integrity_failure'
    if row['scoring']['state'] in ('rejected_mismatch','evaluator_fault','not_attempted'):
        return 'review', 'offline_scoring_or_pipeline_recovery_required'
    telemetry=root/'telemetry-link.json'
    if not telemetry.exists() or not read_json(telemetry).get('verified'):
        return 'review', 'offline_monitor_recovery_required'
    reason=manifest.get('end_reason')
    if reason=='provider_failure':
        return 'technical', 'provider_or_transport_failure'
    if reason in ('operator_stop','environment_failure','stop_unconfirmed'):
        return 'halt', reason
    if reason=='timeout':
        return 'quality_attempt', 'ordinary_implementation_deadline_not_supplemented'
    if not usage.get('usage_complete'):
        return 'review', 'offline_usage_recovery_required'
    if exit_code and reason not in ('agent_error',):
        return 'review', 'unclassified_cli_error'
    return 'observed', 'retained_including_quality_failure'


def execute_case(repo, batch, archive, plan, case):
    expected=machine.expected_conditions(repo,'MS1-001','deepseek',('explore','preload','explained'))
    if expected!=plan['condition_fingerprints']:
        raise RuntimeError('Frozen conditions changed before dispatch')
    if runtime.controller_files(repo)!=read_json(repo/'artifacts/runtime/MS1-001/lock.json')['controller_files']:
        raise RuntimeError('Frozen controller bytes changed')
    for name,digest in plan['research_code_hashes'].items():
        if sha(repo/name)!=digest:
            raise RuntimeError('Frozen research code changed: '+name)
    root=batch/case['run_id']
    if root.exists():
        raise RuntimeError('Run already exists; uncertain dispatch must not be replayed')
    args=[sys.executable,'-m','outer.harness.cli','--runs-dir',str(batch),'run',
          '--task','MS1-001','--intervention',case['condition'],'--runtime','deepseek',
          '--attempt',str(case['attempt']),'--archive',str(archive)]
    append(batch/'batch-journal.jsonl', {'kind':'dispatch','case':case,'command':args})
    print('DISPATCH '+case['run_id']+' slot='+str(case['slot']),flush=True)
    with (batch/'cli-logs'/(case['run_id']+'.log')).open('xb') as output:
        process=subprocess.Popen(args,cwd=repo,env=child_environment(),stdout=output,stderr=subprocess.STDOUT)
        last_update=0
        while process.poll() is None:
            if time.monotonic()-last_update>=30:
                started=journal(root/'usage/raw/started.jsonl')[0]
                ended=journal(root/'usage/raw/events.jsonl')[0]
                write_json(batch/'active.json',{'case':case,'pid':process.pid,'checked_at':now(),
                    'started_calls':len(started),'terminal_calls':len(ended)})
                last_update=time.monotonic()
            time.sleep(2)
    row=aggregate.row_for(batch,case['run_id'])
    machine.verify_conditions(root,plan['condition_fingerprints'],case['condition'])
    if not (root/'archive-reference.json').exists():
        raise RuntimeError('Preservation receipt missing; stop before another Run')
    reference=read_json(root/'archive-reference.json')
    preserve.verify(archive, reference['package_id'], reference['sha256'])
    state,reason=disposition(root,row,process.returncode)
    record={'kind':'result','case':case,'cli_exit_code':process.returncode,'disposition':state,
            'reason':reason,'row':row,'archive':reference}
    append(batch/'batch-journal.jsonl',record)
    print('RESULT '+case['run_id']+' '+state+' quality='+str(row['quality'])+
          ' tokens='+str(row['usage']['total_tokens']),flush=True)
    return record


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan',type=Path,required=True)
    args=p.parse_args()
    repo=Path(__file__).resolve().parents[1]
    plan=read_json(args.plan)
    if len(plan['slots'])!=18 or plan['maximum_supplements']!=6:
        raise SystemExit('Unexpected authorized batch size')
    if any(sum(s['condition']==c for s in plan['slots'])!=6 for c in ('explore','preload','explained')):
        raise SystemExit('Unbalanced initial slots')
    batch=repo/plan['runs_dir']
    batch.mkdir(parents=True,exist_ok=False)
    (batch/'cli-logs').mkdir()
    archive=batch/'_archive'
    plan_copy=batch/'frozen-plan.json'
    plan_copy.write_bytes(args.plan.read_bytes())
    append(batch/'batch-journal.jsonl',{'kind':'begin','plan_sha256':sha(plan_copy),
        'research_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip(),
        'initial_slots':18,'maximum_supplements':6})
    results=[]
    stopped=None
    try:
        for case in plan['slots']:
            result=execute_case(repo,batch,archive,plan,case)
            results.append(result)
            if result['disposition'] in ('halt','review'):
                stopped={'case':case,'reason':result['reason'],'disposition':result['disposition']}
                break
        if stopped is None:
            eligible=[r for r in results if r['disposition']=='technical'][:plan['maximum_supplements']]
            for item in eligible:
                original=item['case']
                case={**original,'attempt':original['attempt']+6,
                      'run_id':'MS1-001-'+original['condition']+'-'+str(original['attempt']+6).zfill(3),
                      'replacement_for':original['run_id'],'cohort':'supplement','original_block':original['block'],'block':None}
                result=execute_case(repo,batch,archive,plan,case)
                results.append(result)
                if result['disposition'] in ('halt','review'):
                    stopped={'case':case,'reason':result['reason'],'disposition':result['disposition']}
                    break
    except Exception as exc:
        stopped={'reason':str(exc),'type':type(exc).__name__,'disposition':'halt'}
        append(batch/'batch-journal.jsonl',{'kind':'driver_error',**stopped})
    dispatched=[e['case']['run_id'] for _,e in journal(batch/'batch-journal.jsonl')[0] if e.get('kind')=='dispatch']
    result={'complete':stopped is None,'stopped':stopped,'results':results,
            'dispatched':dispatched,'unstarted_initial_slots':[s for s in plan['slots'] if s['run_id'] not in dispatched],
            'ended_at':now()}
    write_json(batch/'batch-result.json',result)
    append(batch/'batch-journal.jsonl',{'kind':'end','complete':stopped is None,'stopped':stopped,
                                       'dispatched_count':len(dispatched)})
    print(json.dumps({'complete':result['complete'],'dispatched':len(dispatched),'stopped':stopped},ensure_ascii=True),flush=True)
    return 0 if stopped is None else 2


if __name__=='__main__':
    sys.exit(main())
