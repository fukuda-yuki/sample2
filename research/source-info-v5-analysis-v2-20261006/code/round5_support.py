"""Check pair matching, actual acquisition-regime support and rank before any adjustment."""
from fractions import Fraction
import argparse
from common import *

def rank(matrix):
    a=[[Fraction(x) for x in row] for row in matrix];i=0
    for j in range(len(a[0]) if a else 0):
        k=next((k for k in range(i,len(a)) if a[k][j]),None)
        if k is None:continue
        a[i],a[k]=a[k],a[i];v=a[i][j];a[i]=[x/v for x in a[i]]
        for k in range(len(a)):
            if k!=i and a[k][j]:
                v=a[k][j];a[k]=[x-v*y for x,y in zip(a[k],a[i])]
        i+=1
        if i==len(a):break
    return i

def compute(d):
    rows=d['runs'];ps=pairs(rows);pts={p['pair']:p for p in pair_tokens(rows)}
    keys=('acquisition_phase','run_concurrency_cap','start_date_utc','evaluator_sha256','acquisition_wave_pairs')
    matched={k:sum(str(g['explore'][k])==str(g['preload'][k]) for g in ps.values()) for k in keys}
    pp=[g['explore'] for g in ps.values()];tasks=d['plan']['task_ids'];phase=[]
    for ph in sorted({r['acquisition_phase'] for r in pp}):
        rr=[r for r in rows if r['acquisition_phase']==ph];pids=sorted({r['pair'] for r in rr});cc=[pts[i] for i in pids if pts[i]['complete']]
        bytask={t:{'assigned_pairs':sum(r['task']==t for r in rr)//2,'complete_pairs':sum(p['task']==t for p in cc),
                   'complete_total_diff':mean([p['diff']['total_tokens'] for p in cc if p['task']==t])} for t in tasks}
        same_target=all(bytask[t]['complete_pairs'] for t in tasks)
        phase.append({'phase':ph,'pair_ids':pids,'quality':quality(rr),'task_support':bytask,
           'caps':dict(sorted(Counter(str(r['run_concurrency_cap']) for r in rr).items())),
           'complete_token_pairs':len(cc),'equal4_complete_token_mean':sum(bytask[t]['complete_total_diff'] for t in tasks)/4 if same_target else None,
           'all_assigned_token_mean':None if len(cc)!=len(pids) else sum(bytask[t]['complete_total_diff'] for t in tasks)/4 if same_target else None})
    features=('task','acquisition_phase','run_concurrency_cap','start_date_utc','evaluator_sha256')
    cats={k:sorted({str(r[k]) for r in pp}) for k in features};cols=['intercept']+[(k,v) for k in features for v in cats[k][1:]]
    matrix=[[1]+[int(str(r[k])==v) for k,v in cols[1:]] for r in pp]
    designrank=rank(matrix)
    build=[]
    for b in sorted({r['evaluator_sha256'] for r in rows}):
        rr=[r for r in rows if r['evaluator_sha256']==b]
        build.append({'build_sha256':b,'runs':len(rr),'tasks':dict(sorted(Counter(r['task'] for r in rr).items())),
          'phases':dict(sorted(Counter(r['acquisition_phase'] for r in rr).items())), 'dates':dict(sorted(Counter(r['start_date_utc'] for r in rr).items()))})
    return {'question':'Could phase, time, concurrency or evaluator build explain the selected contrasts, and are separate adjusted effects identifiable?',
      'pair_matching_counts_of_100':matched,'actual_cap_run_counts':dict(sorted(Counter(str(r['run_concurrency_cap']) for r in rows).items())),
      'phase_support':phase,'evaluator_support':build,
      'additive_pair_difference_design':{'rows':100,'columns':[str(x) for x in cols],'column_count':len(cols),'exact_rational_rank':designrank,
        'rank_deficient':designrank<len(cols),'coefficients_estimated':False,
        'reason':'Structural task/family/build and phase/date support overlap is insufficient to identify all additive coefficients; rank is algebra, not a causal identification proof.'},
      'conclusions':['Phase/cap/day/build match within all100pairs. Additive common pair-level baseline does not itself create arm imbalance; cancellation does not establish invariant arm response, no interference or no selection.',
        'OldEducation build onlyD/earliestphase; no samephase old/new contrast. Fullbuild-vs-task/family moderation cannot be separated without unsupported extrapolation.',
        'Large phases contain all4variants but smaller phases do not. Phase-equal4 comparisons are conditionaldescriptive and null for missingtask support; they are not replacements for originalall100target.',
        'Observed cap2/4/8 and overlappingwave metadata differ from prespecifiedpair2-only regime. Historicalprospectiveamendments must be retained; findings apply to acquiredmixedregime, not proof of effect under stablecap2.',
        'No regression or invented adjusted causal effect is fit. A well-conditioned design under a declared model would still require measurement, selection and interference assumptions.']}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--data',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    execute('round5_support',__file__,a.data,a.out,compute)
