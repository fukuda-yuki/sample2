"""Separate postassignment selection and variant composition by exact descriptive identities."""
import argparse
from common import *

def compute(d):
    pts=pair_tokens(d['runs']); cc=[p for p in pts if p['complete']]; selected=[p for p in cc if p['both_pass']]
    tasks=d['plan']['task_ids'];stats={}
    for t in tasks:
        c=[p for p in cc if p['task']==t];s=[p for p in selected if p['task']==t];other=[p for p in c if not p['both_pass']]
        stats[t]={'complete_n':len(c),'both_pass_complete_n':len(s),'other_complete_n':len(other),'metrics':{}}
        for m in METRICS:
            cm=mean([p['diff'][m] for p in c]);sm=mean([p['diff'][m] for p in s]);om=mean([p['diff'][m] for p in other])
            ident=(len(s)*(sm or 0)+len(other)*(om or 0))/len(c)
            if abs(cm-ident)>1e-7:raise AssertionError('Selection mixture mismatch')
            stats[t]['metrics'][m]={'complete_mean':cm,'pass_selected_mean':sm,'other_mean':om,'mixture_identity_error':cm-ident,
                'pass_contribution_to_complete_mean':len(s)*(sm or 0)/len(c),'other_contribution_to_complete_mean':len(other)*(om or 0)/len(c)}
    common=[t for t in tasks if stats[t]['complete_n'] and stats[t]['both_pass_complete_n']]
    out={'question':'Can negative complete-pair tokens versus positive both-pass-selected tokens be explained only by variant weights?',
      'task_selection_mixtures':stats,'both_pass_complete_pair_ids':[p['pair'] for p in selected],'common_support_tasks':common,
      'undefined_original_equal4_success_target_tasks':[t for t in tasks if not stats[t]['both_pass_complete_n']], 'metrics':{}}
    for m in METRICS:
        complete_means=[stats[t]['metrics'][m]['complete_mean'] for t in tasks]
        # Convex reweighting of unchanged complete-case variant means cannot leave their hull.
        cc_common=[p for p in cc if p['task'] in common];s_common=[p for p in selected if p['task'] in common]
        within=composition=0;terms=[]
        for t in common:
            c=stats[t]['metrics'][m]['complete_mean'];s=stats[t]['metrics'][m]['pass_selected_mean']
            wc=stats[t]['complete_n']/len(cc_common);ws=stats[t]['both_pass_complete_n']/len(s_common)
            wterm=.5*(wc+ws)*(s-c);cterm=.5*(c+s)*(ws-wc)
            within+=wterm;composition+=cterm;terms.append({'task':t,'complete_weight':wc,'selected_weight':ws,'within_mean_component':wterm,'composition_component':cterm})
        cp=mean([p['diff'][m] for p in cc_common]);sp=mean([p['diff'][m] for p in s_common])
        if abs((sp-cp)-(within+composition))>1e-7:raise AssertionError('Kitagawa identity mismatch')
        out['metrics'][m]={'complete_equal4_mean':sum(complete_means)/4,'complete_pool_mean':mean([p['diff'][m] for p in cc]),
          'complete_variant_convex_weight_hull':[min(complete_means),max(complete_means)],
          'both_pass_selected_pool_mean':mean([p['diff'][m] for p in selected]),
          'both_pass_selected_equal4_mean':None,'both_pass_selected_equal_common_support_mean':mean([stats[t]['metrics'][m]['pass_selected_mean'] for t in common]),
          'common_support_complete_pool_mean':cp,'common_support_selected_pool_mean':sp,
          'symmetric_decomposition':{'observed_pool_mean_change':sp-cp,'within_variant_selection_component':within,'variant_composition_component':composition,'identity_error':sp-cp-within-composition,'terms':terms},
          'dropping_noncommon_support_complete_pairs_changes_pool_mean_by':cp-mean([p['diff'][m] for p in cc])}
    out['conclusion']='All four complete-case total-token variant means are negative, so reweighting those same means alone cannot produce positive total difference. Selected within-variant means change, and D has no both-pass complete pairs. This explains descriptive mixture changes, not causal selection bias magnitude or prompt efficiency.'
    return out

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--data',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    execute('round4_selection',__file__,a.data,a.out,compute)
