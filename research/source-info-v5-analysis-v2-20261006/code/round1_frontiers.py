"""Exact quality and whole-Run-token sensitivity frontiers, not an imputation grid."""
import argparse
from common import *

def compute(d):
    rows=d['runs']; q=quality(rows); e,p=q['explore'],q['preload']; n=e['assigned']
    out={'question':'Can the full-assignment interpretation survive quality unknowns and token missingness beyond the previous finite multiplier grid?',
         'claim_type':'finite-cohort descriptive sensitivity, exploratory, not causal or noninferiority', 'quality':q,
         'quality_frontier':{'difference_formula':'(passP-passE + unknownP*qP - unknownE*qE)/100',
         'intercept':(p['pass']-e['pass'])/n,'qP_coefficient':p['unknown']/n,'qE_coefficient':-e['unknown']/n,
         'equality_qP_at_qE_0':(e['pass']-p['pass'])/p['unknown'],
         'equality_qP_at_qE_1':(e['pass']-p['pass']+e['unknown'])/p['unknown'],
         'equal_unknown_completion_rate_difference_at_q0':(p['pass']-e['pass'])/n,
         'equal_unknown_completion_rate_difference_at_q1':(p['pass']-e['pass']+p['unknown']-e['unknown'])/n,
         'equal_rate_break_even':(e['pass']-p['pass'])/(p['unknown']-e['unknown']),
         'parameters_are_assumptions_not_fitted_probabilities':True},'tokens':{},'unknown_quality_usage_joint':{}}
    for a in ARMS:
        rr=[r for r in rows if r['arm']==a]
        out['unknown_quality_usage_joint'][a]=dict(sorted(Counter(f"quality={r['full_pass']};usage_complete={r['usage']['complete']};execution={r['execution_state']}" for r in rr).items()))
    for k in METRICS:
        stats={}
        for a in ARMS:
            rr=[r for r in rows if r['arm']==a]; known=[r['usage'][k] for r in rr if r['usage']['complete']]
            stats[a]={'observed_complete_sum':sum(known),'complete_runs':len(known),'missing_runs':len(rr)-len(known),
                      'complete_mean':mean(known),'missing_run_ids':[r['run_id'] for r in rr if not r['usage']['complete']],
                      'verified_missing_lower_bounds':[r['usage'].get('verified_lower_bounds',{}).get(k) for r in rr if not r['usage']['complete']]}
        e,p=stats['explore'],stats['preload']; b=(p['observed_complete_sum']-e['observed_complete_sum'])/100
        # Unknown true means among the missing runs are arbitrary nonnegative values. Partial totals are NOT lower bounds.
        stats['frontier']={'known_sum_contrast_per_100':b,'formula':'delta=B + missingP*muP/100 - missingE*muE/100',
          'missing_P_mean_at_break_even_if_E_mean_0':-100*b/p['missing_runs'],
          'muP_frontier_intercept':-100*b/p['missing_runs'], 'muP_frontier_slope_on_muE':e['missing_runs']/p['missing_runs'],
          'muP_break_even_if_muE_equals_arm_complete_mean':(e['missing_runs']*e['complete_mean']-100*b)/p['missing_runs'],
          'break_even_P_mean_to_P_complete_mean_ratio_if_E_reference':(e['missing_runs']*e['complete_mean']-100*b)/(p['missing_runs']*p['complete_mean']),
          'finite_identification_bounds':None,'reason':'Missing totals in both arms and no justified finite upper bound; mean contrast unbounded both ways.'}
        # Cross-check previous task-specific multiplier assumptions algebraically; these are validation points, not iterations.
        stats['previous_grid_crosscheck']=[]
        for em,pm in ((.5,.5),(.5,2),(1,1),(2,2)):
            arm_sums={}; missing_means={}
            for a,mult in zip(ARMS,(em,pm)):
                added=0
                for t in d['plan']['task_ids']:
                    rr=[r for r in rows if r['arm']==a and r['task']==t]; known=[r['usage'][k] for r in rr if r['usage']['complete']]
                    added+=(25-len(known))*mean(known)*mult
                arm_sums[a]=stats[a]['observed_complete_sum']+added
                missing_means[a]=added/stats[a]['missing_runs']
            direct=(arm_sums['preload']-arm_sums['explore'])/100
            frontier=b+(p['missing_runs']*missing_means['preload']-e['missing_runs']*missing_means['explore'])/100
            if abs(direct-frontier)>1e-8: raise AssertionError('Frontier mismatch')
            stats['previous_grid_crosscheck'].append({'explore_multiplier':em,'preload_multiplier':pm,'delta':direct,'identity_error':direct-frontier})
        out['tokens'][k]=stats
    out['conclusion']='Neither quality-preserving token reduction nor the opposite is identified. Negative signs inside the old token grid do not constrain missing means outside it; the exact frontier quantifies the required reversal assumptions.'
    return out

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--data',required=True); p.add_argument('--out',required=True); a=p.parse_args()
    execute('round1_frontiers',__file__,a.data,a.out,compute)
