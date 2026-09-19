"""Explicitly amended continuation, retaining the halted segment and all attempts."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from research.acquire import append, execute_case, now
from research.analyze import journal, read_json, sha, write_json
from research.ledger import validate_schedule
from research.network_recovery import pool_failure, probe, reclaim


def events(batch):
    rows, errors = journal(batch/'batch-journal.jsonl')
    if errors:
        raise RuntimeError('Journal cannot be parsed: ' + str(errors))
    return [e for _,e in rows]


def is_eligible(result, recovered):
    return result['disposition']=='technical' or result['case']['run_id'] in recovered


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan', type=Path, required=True)
    a = p.parse_args()
    repo = Path(__file__).resolve().parents[1]
    plan = read_json(a.plan)
    amendment = plan['resume_amendment']
    batch = repo/plan['runs_dir']
    original = read_json(batch/'frozen-plan.json')
    for key in ('slots','maximum_supplements','condition_fingerprints','images','evaluator_sha256','randomization_seed'):
        if plan[key] != original[key]:
            raise RuntimeError('Original experimental plan changed: '+key)
    if sha(batch/'frozen-plan.json') != amendment['original_plan_sha256']:
        raise RuntimeError('Original plan bytes changed')
    if sha(batch/'batch-journal.jsonl') != amendment['prior_journal_sha256']:
        raise RuntimeError('Journal differs from approved continuation boundary')
    if sha(batch/'batch-result.json') != amendment['prior_result_sha256']:
        raise RuntimeError('Prior closed result changed')
    prior = events(batch)
    issues = validate_schedule(prior, original)
    if issues:
        raise RuntimeError('Prior schedule issues: '+str(issues))
    results = [e for e in prior if e['kind']=='result']
    dispatched = [e['case']['run_id'] for e in prior if e['kind']=='dispatch']
    if len(results)!=len(dispatched) or dispatched!=amendment['prior_dispatches']:
        raise RuntimeError('Uncertain or changed prior dispatch boundary')
    segment = batch/amendment['segment']
    segment.mkdir(exist_ok=False)
    (segment/'prior-journal.jsonl').write_bytes((batch/'batch-journal.jsonl').read_bytes())
    (segment/'prior-result.json').write_bytes((batch/'batch-result.json').read_bytes())
    (segment/'resumed-plan.json').write_bytes(a.plan.read_bytes())
    log = segment/'network-recovery.jsonl'
    append(batch/'batch-journal.jsonl', {'kind':'resume_begin','segment':amendment['segment'],
        'plan_path':str(a.plan.resolve()),'plan_sha256':sha(a.plan),
        'prior_journal_sha256':amendment['prior_journal_sha256'],
        'authorization':amendment['authorization'],
        'research_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()})
    recovered = set()
    stopped = None
    try:
        probe(log)
        for rid in amendment['initial_pool_failures']:
            if not pool_failure(batch/rid):
                raise RuntimeError('Recovery exception does not match pre-model Docker pool failure')
            recovered.add(rid)
            append(batch/'batch-journal.jsonl', {'kind':'infrastructure_recovered','run_id':rid,
                'reason':'premodel_docker_address_pool','plan_sha256':sha(a.plan),'recovery_log':str(log.resolve())})

        def run(case):
            result = execute_case(repo,batch,batch/'_archive',plan,case)
            results.append(result)
            # Recovery is outside the measured interval and after preservation.
            if pool_failure(batch/case['run_id']):
                # No replay of the failed identity: any permitted supplement is
                # scheduled only after all initial slots and remains separate.
                for previous in results:
                    reclaim(batch/previous['case']['run_id'],batch/'_archive',log)
                probe(log)
                recovered.add(case['run_id'])
                append(batch/'batch-journal.jsonl', {'kind':'infrastructure_recovered','run_id':case['run_id'],
                    'reason':'premodel_docker_address_pool','plan_sha256':sha(a.plan),'recovery_log':str(log.resolve())})
            else:
                reclaim(batch/case['run_id'],batch/'_archive',log)
            return result

        for case in plan['slots'][len(dispatched):]:
            result = run(case)
            if result['disposition'] in ('halt','review') and case['run_id'] not in recovered:
                stopped = {'case':case,'reason':result['reason'],'disposition':result['disposition']}
                break
        if stopped is None:
            eligible = [r for r in results if r['case']['cohort']=='primary18' and is_eligible(r,recovered)]
            for item in eligible[:plan['maximum_supplements']]:
                original_case = item['case']
                case = {**original_case,'attempt':original_case['attempt']+6,
                    'run_id':'MS1-001-'+original_case['condition']+'-'+str(original_case['attempt']+6).zfill(3),
                    'replacement_for':original_case['run_id'],'cohort':'supplement',
                    'original_block':original_case['block'],'block':None}
                result = run(case)
                if result['disposition'] in ('halt','review') and case['run_id'] not in recovered:
                    stopped = {'case':case,'reason':result['reason'],'disposition':result['disposition']}
                    break
    except Exception as exc:
        stopped = {'reason':str(exc),'type':type(exc).__name__,'disposition':'halt'}
        append(batch/'batch-journal.jsonl', {'kind':'resume_driver_error',**stopped})
    current = events(batch)
    dispatched = [e['case']['run_id'] for e in current if e['kind']=='dispatch']
    issues = validate_schedule(current, plan)
    if issues:
        stopped = {'reason':'schedule_validation_failed','issues':issues,'disposition':'halt'}
    result = {'complete':stopped is None,'stopped':stopped,'results':results,'dispatched':dispatched,
        'unstarted_initial_slots':[s for s in plan['slots'] if s['run_id'] not in dispatched],
        'recovered_infrastructure_attempts':sorted(recovered),'ended_at':now(),'schedule_issues':issues}
    write_json(segment/'result.json',result)
    append(batch/'batch-journal.jsonl', {'kind':'resume_end','segment':amendment['segment'],
        'complete':result['complete'],'stopped':stopped,'dispatched_count':len(dispatched)})
    print(json.dumps({'complete':result['complete'],'dispatched':len(dispatched),'stopped':stopped}),flush=True)
    return 0 if stopped is None else 2


if __name__=='__main__':
    sys.exit(main())
