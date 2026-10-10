"""Reconstruct successor-study comparability from already published prior tables."""
import argparse, csv
from common import *

def compute(d, prior_dir):
    root=Path(prior_dir)
    previous=read(root/'analysis--statistics--results.json')
    old=list(csv.DictReader((root/'analysis--statistics--pairs.csv').open(encoding='utf-8-sig',newline='')))
    if len(old)!=100 or sorted(int(x['block']) for x in old)!=list(range(1,101)): raise ValueError('Prior exact100 table required')
    if len({r[k] for r in old for k in ('compact_run_id','expanded_run_id')})!=200: raise ValueError('Prior200 identities required')
    old_quality={}
    for a in ('compact','expanded'):
        vals=[None if not x[a+'_all_requirements_pass'] else int(float(x[a+'_all_requirements_pass'])) for x in old]
        old_quality[a]={'pass':vals.count(1),'fail':vals.count(0),'unknown':vals.count(None)}
        if old_quality[a]['pass']!=previous['coverage'][a]['success']: raise ValueError('Prior report/table discrepancy')
    complete=[r for r in old if r['usage_pair_complete']=='True']
    old_delta=mean([float(r['compact_total_tokens'])-float(r['expanded_total_tokens']) for r in complete])
    saved=previous['resources']['tokens_complete_pairs']
    if len(complete)!=saved['n'] or abs(old_delta-saved['difference']['mean'])>1e-6: raise ValueError('Prior published statistical table disagreement')
    current=pair_tokens(d['runs']);cc=[p for p in current if p['complete']]
    means=[mean([p['diff']['total_tokens'] for p in cc if p['task']==t]) for t in d['plan']['task_ids']]
    return {'question':'Which prior limitation did this successor design address, and can old/new effects be compared?',
      'inputs_sha256':{f.name:sha(f) for f in root.iterdir() if f.is_file() and f.suffix in ('.csv','.json','.md')},
      'prior100':{'table_role':'public prior exploratory derived tables; original raw not replayed or rescored', 'pairs':len(old),'runs':200,
        'quality':old_quality,'complete_token_pairs':len(complete),'compact_minus_expanded_mean_complete_pairs':old_delta,
        'expanded_minus_compact_mean_complete_pairs':-old_delta,'reported_compact_saving_fraction':saved['saving_fraction'],
        'intervention':'expanded adds51393byte initialSampleData excerpt; both already have identical complete derivedcatalog and retrieval access',
        'quality_construct':'29requirements/30checks on one uniform-price catalog storefront; original adopting browser evidence', 'regime':'serial adjacent pairs; actualorder45/55, pauses and firstdate-policy revision retained'},
      'current100':{'pairs':100,'runs':200,'quality':quality(d['runs']),'complete_token_pairs':len(cc),
        'preload_minus_explore_equal_variant_complete_pair_mean':sum(means)/4,
        'intervention':'initial permittedsource presentation only; both have same source/data rights; source-defined semantically distinct variants',
        'quality_construct':'31Music requirements/33checks or12Education requirements/checks; source/data continuity, synthetic installation variants',
        'regime':'prespecified100/25each and sameaccount2Run candidate; actual waves/phase/cap departures require separate support audit'},
      'comparability':{'research_program_continuity':True,'same_model_agent_budget':True,'direct_effect_pooling_justified':False,
        'same_quality_measurement_scale':False,'same_intervention':False,'same_execution_regime':False,
        'high_information_orientation_only':'Prior expanded-minus-compact vs currentpreload-minus-explore have opposite complete-case descriptive signs. Changed target/selection/measurement/regime means this is not identified effect reversal or replication.'},
      'chronology':'Oct3 prioraudit andIssues21-24→source-dependenttask/evaluation/recordingrepair→v2twofamilies64serial→v4delegatedAIacceptance(nohuman)→user100/pairconcurrencyamendmentv5→actualacquisitionOct4-5. Prior final report publicationOct5 postdates design; cannot attribute Oct3 choice to its later recommendations.',
      'decision_gap':'Task information-dependence feasibility advanced; halfcurrentquality unknown and missingusage/regimevariation still block primary comparison. Next inspect measurement meaning/coverage before prioritizing more model acquisition.',
      'unknowns':['Original earlier assistantproposal-to-useragreement nativeconversation not independently retrieved; do not claim personal authorship.','Humanoracle/workflow and originalFrameworkexecution notrun.','Crosscohort apparent difference cannot isolate source necessity from changedtask/evaluator/regime.']}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--data',required=True);p.add_argument('--prior',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    execute('round2_continuity',__file__,a.data,a.out,lambda d:compute(d,a.prior))
