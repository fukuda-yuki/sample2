"""Link saved stop roles to outcomes without turning targets into triggers/product faults."""
import argparse
from common import *

OWNED={'other_owned_runtime_stop_target','saved_guard_failure_bearing_owned_target','owned_recovery_controller_target_origin_unresolved'}
def compute(d,stop_path):
    s=read(stop_path);sr={r['run_id']:r for r in s['runs']}
    if len(s['runs'])!=200 or set(sr)!={r['run_id'] for r in d['runs']} or s['dataset_ref']['sha256']!=DATA_SHA:raise ValueError('Stop evidence cohort mismatch')
    for r in d['runs']:
        a=sr[r['run_id']]
        if any(a[k]!=r[k] for k in ('run_instance_id','pair','task','arm','execution_state','full_pass','scoring_state')) or any(a['usage'][k]!=r['usage'][k] for k in ('complete',)+METRICS):raise ValueError('Stop/outcome identity conflict')
    rows=d['runs'];groups={}
    for cat in sorted({a['stop_evidence_category'] for a in sr.values()}):
        rr=[r for r in rows if sr[r['run_id']]['stop_evidence_category']==cat]
        groups[cat]={'runs':len(rr),'execution':dict(sorted(Counter(r['execution_state'] for r in rr).items())),
          'quality':quality(rr),'usage_complete':sum(r['usage']['complete'] for r in rr),'all_assigned_token_contrast':None}
    pts=pair_tokens(rows);selections={}
    selectors={'all_complete_pairs':lambda p:True,'both_completed':lambda p:p['both_completed'],
      'neither_explicit_owned_stop_target':lambda p:all(sr[r['run_id']]['stop_evidence_category'] not in OWNED for r in pairs(rows)[p['pair']].values()),
      'both_not_bound_to_audited_stop_or_latch':lambda p:all(sr[r['run_id']]['stop_evidence_category']=='not_bound_to_audited_stop_or_latch' for r in pairs(rows)[p['pair']].values())}
    for name,predicate in selectors.items():
        assigned=[p for p in pts if predicate(p)];known=[p for p in assigned if p['complete']]
        per={t:{'assigned_pairs':sum(p['task']==t for p in assigned),'complete_pairs':sum(p['task']==t for p in known),
          'complete_total_mean_difference':mean([p['diff']['total_tokens'] for p in known if p['task']==t])} for t in d['plan']['task_ids']}
        selections[name]={'pairs_selected':len(assigned),'complete_pairs':len(known),'pair_ids':[p['pair'] for p in assigned],
          'pool_complete_total_mean_difference':mean([p['diff']['total_tokens'] for p in known]),
          'equal4_complete_total_mean_difference':mean([v['complete_total_mean_difference'] for v in per.values()]) if all(v['complete_pairs'] for v in per.values()) else None,
          'per_variant':per,'interpretation':'Postassignment descriptive restriction. Not a no-fault/no-interference cohort or counterfactual completion estimate.'}
    return {'question':'Do saved stop origins justify treating stopped runs as product failures or prove all observed token saving is early interruption?',
      'stop_input_sha256':sha(stop_path),'origin_summary':s['summary'],'category_outcomes':groups,'conditional_token_restrictions':selections,
      'operational_origin_evidence':'8 runtime alarms:5resource observer-probe failures and3run-bound guard failure records;4additional v7 recovery/controller targets remain origin unresolved;4later observer scope entries were registered-only before dispatch.',
      'conclusions':['All33 operator_stop runs bind explicit owned target evidence. Three guard-failure-bearing records bind particularRun evidence, not provider-internal rootcause or productfailure.',
        'One runtime stop target ultimatelycompleted; four registered-only future-scope runs subsequentlycompleted. Target registration or stop-request presence alone does not establish active interruption.',
        'Negative complete-token descriptive contrasts persist under completed/no-owned-target restrictions if shown, so observed negative difference cannot be dismissed solely as stopped-run token accumulation. Selection, unknownquality, mixedregime, and provider interference still prevent an efficiency/causal claim.',
        'Stop-origin whitelist cannot identify healthy peers by exclusion. Not-bound means not-bound-to-this-audit, not nofault. Private original prefix inventories/raw evidence are required to independently redo origin extraction; public numerical derivation alone is reproducible.']}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--data',required=True);p.add_argument('--stop',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    execute('round6_stops',__file__,a.data,a.out,lambda d:compute(d,a.stop))
