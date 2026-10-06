"""Full-denominator descriptive checks, added after acquisition began.

These comparisons change the population or condition on post-assignment
outcomes. They are descriptive sensitivity checks, not new primary estimates.
No model, evaluator, acquisition or network calls.
"""
from collections import Counter, defaultdict
from pathlib import Path
import argparse
import hashlib
import json
import statistics as st
from offline_reanalysis import validate, compare_subset


def distribution(values):
    xs = sorted(x for x in values if isinstance(x, (int, float)) and not isinstance(x, bool))
    def q(p):
        if not xs: return None
        at = (len(xs)-1)*p; low = int(at); high = min(low+1,len(xs)-1)
        return xs[low]+(xs[high]-xs[low])*(at-low)
    return {'known':len(xs), 'missing':len(values)-len(xs), 'min':min(xs) if xs else None,
            'p10':q(.1), 'p25':q(.25), 'median':q(.5), 'p75':q(.75), 'p90':q(.9),
            'max':max(xs) if xs else None, 'mean':st.mean(xs) if xs else None}


def descriptive(rows):
    out = {}
    for arm in ('explore','preload'):
        items = [r for r in rows if r['arm']==arm]
        out[arm] = {'assigned':len(items),
            'duration_seconds':distribution([r.get('implementation_duration_seconds') for r in items]),
            'complete_whole_run_tokens':{k:distribution([r['usage'].get(k) for r in items])
                for k in ('input_tokens','output_tokens','total_tokens')},
            'observed_partial_usage':{k:distribution([r['usage']['observed_partial'].get(k) for r in items if not r['usage']['complete']])
                for k in ('input_tokens','output_tokens','total_tokens')},
            'request_count_not_independent_run_count':distribution([r['usage'].get('observed_request_count') for r in items]),
            'token_components_already_inside_input_or_output':{k:distribution([
                r['usage'].get('components_not_additional_to_input_output',{}).get(k) for r in items])
                for k in ('cache_read_tokens','cache_write_tokens','reasoning_tokens')},
            'raw_verdict':dict(Counter(str(r['raw_verdict']) for r in items)),
            'raw_adopted':dict(Counter(str(r.get('adopted')) for r in items))}
    return out


def analyze(dataset, audits):
    pairs = validate(dataset); rows=dataset['runs']
    if len(audits['runs'])!=200 or {r['run_id'] for r in audits['runs']}!={r['run_id'] for r in rows}:
        raise ValueError('The exact same full-cohort check audit is required')
    row_for = {r['run_id']:r for r in rows}
    for audit in audits['runs']:
        row=row_for[audit['run_id']]
        if (audit['run_instance_id']!=row['run_instance_id'] or audit['spec_sha256']!=row['spec_sha256']
            or type(audit['original_sequence']) is not int or audit['original_sequence']!=1
            or any(audit['derived'][k]!=row[k] for k in ('full_pass','critical_failure'))
            or audit['derived']['rule_version']!=row['quality_derivation_rule']):
            raise ValueError('Audit UUID/spec/seq1/derived endpoints do not match the dataset')
    arm_for={r['run_id']:r['arm'] for r in rows};task_for={r['run_id']:r['task'] for r in rows}
    checks=defaultdict(lambda: {'explore':Counter(), 'preload':Counter()})
    for audit in audits['runs']:
        for check in audit['checks']:
            key=(task_for[audit['run_id']],check['requirement_id'],check['check_id'],check['severity'])
            checks[key][arm_for[audit['run_id']]][(str(check['original_judgement']),check['derived_state'])]+=1
    check_table=[]
    for key,arms in sorted(checks.items()):
        check_table.append({'task':key[0],'requirement_id':key[1],'check_id':key[2],'severity':key[3],
            'arms':{a:{'assigned':sum(c.values()),'joint_raw_judgement_and_audited_state':[
                {'raw_judgement':j,'derived_state':s,'count':n} for (j,s),n in sorted(c.items())]}
                for a,c in arms.items()}})
    strata = {}
    for axis in ('source_family','task','scoring_state','research_status','execution_state','evaluator_sha256'):
        strata[axis]={str(v):descriptive([r for r in rows if r[axis]==v])
                     for v in sorted({r[axis] for r in rows},key=str)}
    order_groups={}
    for arm in ('explore','preload'):
        members=[r for pair in pairs.values() if next(x for x in pair if x['position']==1)['arm']==arm for r in pair]
        order_groups[arm+'_first']={'pairs':len(members)//2,'comparison':compare_subset(members),
                                  'distributions':descriptive(members)}
    # Every added selection rule is reported, including empty or inconclusive
    # subsets. Do not choose a successful-looking condition after inspecting it.
    selections={
        'both_implementations_completed':lambda es:all(r['execution_state']=='completed' for r in es),
        'both_original_scored':lambda es:all(r['scoring_state']=='scored' for r in es),
        'both_original_research_coverage_complete':lambda es:all(r['research_status']=='complete' for r in es),
        'both_usage_complete':lambda es:all(r['usage']['complete'] for r in es),
        'both_derived_full_pass':lambda es:all(r['full_pass']==1 for r in es),
        'any_execution_failure':lambda es:any(r['execution_state']!='completed' for r in es),
        'any_derived_quality_unknown':lambda es:any(r['full_pass'] is None for r in es)}
    selection_results={}
    for name,predicate in selections.items():
        subset=[r for pair in pairs.values() if predicate(pair) for r in pair]
        selection_results[name]={'pairs':len(subset)//2,'runs':len(subset),
            'comparison':compare_subset(subset),'distributions':descriptive(subset),
            'post_assignment_selection':True,'all_assigned_intervention_effect':False}
    return {'kind':'added_full200_descriptive_and_selection_sensitivities_v1',
        'all200_distribution':descriptive(rows),'strata':strata,'original_order_groups':order_groups,
        'all_frozen_check_outcomes':check_table,'all_added_selection_conditions':selection_results,
        'limitations':['Descriptive strata may pool unequal variant/family mixtures; consult counts and primary fixed weights.',
            'Selection conditions depend on post-assignment execution, coverage, usage or quality and do not establish efficiency or maintenance.',
            'Observed partial usage is neither a complete whole-Run total nor a verified lower bound.',
            'Cache input and reasoning output components must not be added a second time.',
            'Calls/requests are nested observations, not independent Runs; two families are fixed.',
            'No multiple-comparison significance selection or mechanism claim is performed.']}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--data',type=Path,required=True)
    p.add_argument('--audit',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    data=json.loads(a.data.read_bytes());audit=json.loads(a.audit.read_bytes())
    if data.get('kind')!='public_verified_all200_reanalysis_dataset_v1': raise ValueError('Final verified dataset required')
    if data['cohort_identity'].get('public_check_audit_sha256')!=hashlib.sha256(a.audit.read_bytes()).hexdigest():
        raise ValueError('Check audit SHA256 differs from the exact dataset binding')
    result=analyze(data,audit)
    result['input_sha256']=hashlib.sha256(a.data.read_bytes()).hexdigest()
    result['audit_sha256']=hashlib.sha256(a.audit.read_bytes()).hexdigest()
    result['source_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    with a.out.open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')
    print(json.dumps({'runs':200,'pairs':100,'output':str(a.out),'model_called':False,'evaluator_called':False}))


if __name__=='__main__':main()
