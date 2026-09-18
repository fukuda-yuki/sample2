"""Render every authorized slot and supplement from the immutable dispatch journal."""
import argparse
from pathlib import Path

from research.analyze import journal, read_json, write_csv, write_json


def validate_schedule(events,plan):
    problems=[]
    dispatches=[e for e in events if e['kind']=='dispatch']
    initial=[e['case'] for e in dispatches if e['case']['cohort']=='primary18']
    supplements=[e['case'] for e in dispatches if e['case']['cohort']=='supplement']
    if initial!=plan['slots'][:len(initial)]:
        problems.append('initial_order_or_identity_changed')
    if len(supplements)>plan['maximum_supplements']:
        problems.append('supplement_limit_exceeded')
    original_ids=[s.get('replacement_for') for s in supplements]
    if len(original_ids)!=len(set(original_ids)):
        problems.append('multiple_supplements_for_one_slot')
    active=None
    finished={}
    seen=set()
    for e in events:
        if e['kind']=='dispatch':
            s=e['case'];rid=s['run_id']
            if active is not None:problems.append('overlapping_dispatch:'+rid)
            if rid in seen:problems.append('replayed_dispatch:'+rid)
            seen.add(rid);active=rid
            if s['cohort']=='supplement':
                if len([x for x in finished.values() if x['case']['cohort']=='primary18'])!=18:
                    problems.append('supplement_before_all_initial_results')
                prior=finished.get(s.get('replacement_for'),{})
                if prior.get('disposition')!='technical':
                    problems.append('supplement_for_ineligible_run:'+rid)
                if prior.get('case',{}).get('condition')!=s['condition']:
                    problems.append('supplement_condition_changed:'+rid)
        elif e['kind']=='result':
            rid=e['case']['run_id']
            if active!=rid:problems.append('result_without_active_dispatch:'+rid)
            active=None;finished[rid]=e
    expected=[s['run_id'] for s in initial if finished.get(s['run_id'],{}).get('disposition')=='technical'][:plan['maximum_supplements']]
    if original_ids!=expected[:len(original_ids)]:
        problems.append('supplement_order_changed')
    return problems


def build_ledger(batch,plan):
    rows,errors=journal(batch/'batch-journal.jsonl')
    events=[e for _,e in rows]
    issues=errors+validate_schedule(events,plan)
    dispatches={e['case']['run_id']:e for e in events if e['kind']=='dispatch'}
    results={e['case']['run_id']:e for e in events if e['kind']=='result'}
    cases=plan['slots']+[e['case'] for e in events if e['kind']=='dispatch' and e['case']['cohort']=='supplement']
    ledger=[]
    for case in cases:
        rid=case['run_id'];root=batch/rid
        manifest=read_json(root/'manifest.json') if (root/'manifest.json').is_file() else {}
        result=results.get(rid,{})
        row=result.get('row',{})
        ev_id=row.get('scoring',{}).get('evaluation_id')
        ev_path=root/'evaluations'/ev_id/'evaluation.json' if ev_id else None
        ev=read_json(ev_path) if ev_path and ev_path.is_file() else {}
        usage=row.get('usage',{})
        ledger.append({**case,'run_instance_id':manifest.get('run_instance_id'),
            'state':row.get('execution',{}).get('state','dispatched_no_result' if rid in dispatches else 'not_started'),
            'dispatch_at':dispatches.get(rid,{}).get('at'),'started_at':manifest.get('started_at'),
            'ended_at':manifest.get('ended_at'),'result_at':result.get('at'),
            'duration_seconds':manifest.get('duration_seconds'),'end_reason':manifest.get('end_reason'),
            'disposition':result.get('disposition'),'disposition_reason':result.get('reason'),
            'quality':row.get('quality'),'verdict':row.get('verdict'),
            'requirements_passed':ev.get('passedCount'),'requirements_total':ev.get('requirementCount'),
            'failed_requirements':[r['id'] for r in ev.get('requirements',[]) if r['judgement']=='fail'] if ev else None,
            'blocked_requirements':[r['id'] for r in ev.get('requirements',[]) if r['judgement']=='blocked'] if ev else None,
            'error_requirements':[r['id'] for r in ev.get('requirements',[]) if r['judgement']=='error'] if ev else None,
            'usage_complete':usage.get('usage_complete'),'input_tokens':usage.get('input_tokens'),
            'output_tokens':usage.get('output_tokens'),'total_tokens':usage.get('total_tokens'),
            'observed_tokens':usage.get('observed_tokens'),'calls':usage.get('observed_request_count'),
            'evaluation_id':ev_id,'root':str(root.resolve()) if root.exists() else None,
            'archive_package':result.get('archive',{}).get('package_id'),
            'archive_sha256':result.get('archive',{}).get('sha256')})
    return {'ledger':ledger,'schedule_issues':issues,
        'batch_result':read_json(batch/'batch-result.json') if (batch/'batch-result.json').exists() else None}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--batch',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    if args.out.exists():raise SystemExit('Refusing to overwrite ledger output')
    result=build_ledger(args.batch,read_json(args.batch/'frozen-plan.json'))
    args.out.mkdir(parents=True)
    write_json(args.out/'execution-ledger.json',result)
    write_csv(args.out/'execution-ledger.csv',result['ledger'])
    print({'slots_and_supplements':len(result['ledger']),'schedule_issues':result['schedule_issues']})
    return int(bool(result['schedule_issues']))


if __name__=='__main__':
    raise SystemExit(main())
