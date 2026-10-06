"""Declared added views; original all200 primary population is retained elsewhere.

Deletion, trimming, positive-ratio and complete-case views change the estimand.
Approximate cluster intervals assume independent clusters and cannot establish
that provider/date/wave dependence was removed. No model/evaluator/network.
"""
from collections import defaultdict
from pathlib import Path
import argparse,hashlib,json,math,statistics as st
from offline_reanalysis import ARMS,METRICS,avg,weighted,validate,ordered_pairs,compare_subset
from supplementary_reanalysis import distribution

def pair_values(rows,metric):
    out=[]
    for e,p in ordered_pairs(rows):
        if e['usage']['complete'] and p['usage']['complete']:
            ev,pv=e['usage'][metric],p['usage'][metric]
            if e['acquisition_phase']!=p['acquisition_phase'] or e['acquisition_wave_pairs']!=p['acquisition_wave_pairs']:
                raise ValueError('Paired acquisition-wave identity differs')
            out.append({'pair':e['pair'],'task':e['task'],'difference':pv-ev,
                'ratio':pv/ev if ev>0 else None,
                'log_ratio':math.log(pv/ev) if ev>0 and pv>0 else None,
                'session':e['analysis_session'],
                'wave':(e['acquisition_phase'],tuple(e['acquisition_wave_pairs']))})
    return out

def weighted_center(values,tasks):
    means=[avg([v['difference'] for v in values if v['task']==t]) for t in tasks]
    return weighted(means,[1/len(tasks)]*len(tasks))

def cluster_interval(values,tasks,axis):
    n={t:sum(v['task']==t for v in values) for t in tasks}
    center=weighted_center(values,tasks)
    clusters={v[axis] for v in values};g=len(clusters);total=len(values);k=len(tasks)
    clusters_by_variant={t:len({v[axis] for v in values if v['task']==t}) for t in tasks}
    base={'known_complete_pairs':total,'pair_counts_by_variant':n,'clusters':g,
        'equal_variant_complete_pair_center':center,'clusters_by_variant':clusters_by_variant,
        'assumption':'Independent clusters; arbitrary dependence within each chosen cluster; normal approximation and CR1 finite-sample adjustment. Not a guarantee and provider/date dependence between clusters may remain.',
        'scope':'Conditional on complete-pair token selection; changes the population.'}
    if center is None or min(n.values())<2 or g<2 or min(clusters_by_variant.values())<2 or total<=k:
        return base|{'interval95':None,'unavailable_reason':'Need every variant, two known pairs and two retained clusters per variant, two global clusters and N>K.'}
    means={t:avg([v['difference'] for v in values if v['task']==t]) for t in tasks}
    influence=defaultdict(float)
    for v in values:
        influence[v[axis]]+=(v['difference']-means[v['task']])/(len(tasks)*n[v['task']])
    correction=(g/(g-1))*((total-1)/(total-k))
    se=math.sqrt(correction*sum(z*z for z in influence.values()))
    return base|{'standard_error':se,'cr1_correction':correction,
        'interval95':[center-1.959963984540054*se,center+1.959963984540054*se]}

def token_views(rows,tasks,metric):
    vals=pair_values(rows,metric);center=weighted_center(vals,tasks)
    variants={}
    for task in tasks:
        vs=[v for v in vals if v['task']==task];logs=[v['log_ratio'] for v in vs if v['log_ratio'] is not None]
        variants[task]={'complete_pairs':len(vs),'paired_difference':distribution([v['difference'] for v in vs]),
            'ratio_selection_counts':{'complete_pairs':len(vs),
                'incomplete_usage_pairs':len(ordered_pairs([r for r in rows if r['task']==task]))-len(vs),
                'explore_zero_ratio_undefined':sum(v['ratio'] is None for v in vs),
                'positive_explore_preload_zero_ratio0_log_undefined':sum(v['ratio']==0 for v in vs),
                'both_positive_log_defined':len(logs)},
            'positive_explore_ratio':distribution([v['ratio'] for v in vs]),
            'both_positive_log_ratio':distribution([v['log_ratio'] for v in vs]),
            'geometric_ratio':math.exp(avg(logs)) if logs else None}
    logs=[variants[t]['both_positive_log_ratio']['mean'] for t in tasks]
    influence=[]
    for v in vals:
        without=weighted_center([x for x in vals if x['pair']!=v['pair']],tasks)
        influence.append({'pair':v['pair'],'task':v['task'],'difference':v['difference'],
            'hypothetical_leave_one_complete_pair_center':without,
            'center_change':without-center if without is not None and center is not None else None})
    trim=[]
    for proportion in (0,.05,.1):
        means=[];counts={};wins=[]
        for t in tasks:
            ds=sorted(v['difference'] for v in vals if v['task']==t);cut=math.floor(len(ds)*proportion)
            keep=ds[cut:len(ds)-cut] if ds else []
            means.append(avg(keep));counts[t]={'before':len(ds),'removed_per_tail':cut,'retained':len(keep)}
            wins.append(avg([min(max(v,keep[0]),keep[-1]) for v in ds]) if keep else None)
        trim.append({'fraction_per_tail':proportion,'equal_variant_trimmed_difference':weighted(means,[1/len(tasks)]*len(tasks)),
            'equal_variant_winsorized_difference':weighted(wins,[1/len(tasks)]*len(tasks)),
            'counts_by_variant':counts,'primary_rows_removed':False,
            'interpretation':'Hypothetical changed estimand among complete pairs; not the all-assigned effect or recovered missing tokens.'})
    return {'metric':metric,'equal_variant_complete_pair_difference':center,'variant_distributions':variants,
        'equal_variant_positive_log_ratio_geometric_ratio':math.exp(avg(logs)) if all(v is not None for v in logs) else None,
        'all_leave_one_complete_pair_influences':influence,'trim_and_winsorization_scenarios':trim,
        'planned_session_cluster_interval':cluster_interval(vals,tasks,'session'),
        'actual_acquisition_wave_cluster_interval':cluster_interval(vals,tasks,'wave'),
        'ratios_change_scale_and_positive_subset':True,'primary_all_assigned_point_estimate_claimed':False}

def changed_population(rows,tasks):
    summaries={t:compare_subset([r for r in rows if r['task']==t]) for t in tasks}
    weights=[1/len(tasks)]*len(tasks)
    out={'target_variants':tasks,'normalized_variant_weights':dict(zip(tasks,weights)),
        'assigned_runs':len(rows),'assigned_pairs':len(rows)//2,'changed_target_population':True}
    for key in ('full_pass','critical_failure'):
        ss=[summaries[t][key] for t in tasks]
        out[key]={'all_assigned_difference':weighted([v['all_assigned_difference'] for v in ss],weights),
            'identification_bounds':[weighted([v['identification_bounds'][j] for v in ss],weights) for j in (0,1)]}
    out['tokens']={m:{'all_assigned_difference':weighted([
        summaries[t]['arms']['preload']['tokens'][m]['all_assigned_mean']-
        summaries[t]['arms']['explore']['tokens'][m]['all_assigned_mean']
        if all(summaries[t]['arms'][a]['tokens'][m]['all_assigned_mean'] is not None for a in ARMS) else None
        for t in tasks],weights)} for m in METRICS}
    return out

def analyze(dataset):
    validate(dataset);rows=dataset['runs'];tasks=dataset['plan']['task_ids']
    by_pair=defaultdict(list)
    for r in rows:
        wave=r.get('acquisition_wave_pairs')
        if (not isinstance(wave,list) or not wave or any(type(x) is not int or x not in range(1,101) for x in wave)
            or len(wave)!=len(set(wave)) or wave!=sorted(wave) or r['pair'] not in wave):
            raise ValueError('Exact acquisition wave pair list required for added cluster view')
        by_pair[r['pair']].append(r)
    for r in rows:
        for pair in r['acquisition_wave_pairs']:
            if any(x['acquisition_phase']!=r['acquisition_phase'] or x['acquisition_wave_pairs']!=r['acquisition_wave_pairs'] for x in by_pair[pair]):
                raise ValueError('All assigned members of an acquisition wave must have the same phase and exact pair set, including missing-usage pairs')
    deletions={}
    for task in tasks:
        keep=[t for t in tasks if t!=task]
        deletions['omit_variant_'+task]=changed_population([r for r in rows if r['task'] in keep],keep)
    for f in sorted({r['source_family'] for r in rows}):
        keep=[t for t in tasks if dataset['plan']['task_hierarchy'][t]['family']!=f]
        deletions['omit_family_'+f]=changed_population([r for r in rows if r['task'] in keep],keep)
    return {'kind':'declared_added_exploratory_all200_views_v1','all200_input_retained':True,
        'tokens':{m:token_views(rows,tasks,m) for m in METRICS},'all_changed_population_omissions':deletions,
        'no_favorable_subset_selected_as_primary':True,'inference_limitations':[
        'Deletion and complete-case summaries change the target population; token missingness remains unidentified.',
        'Actual wave blocks differ from consecutive-four-pair planned sessions; neither proves independent clusters.',
        'Ratio/log/trim/winsorization scenarios change scale or estimand, do not fix early stopping or outcome-dependent selection.',
        'All prepared scenarios are reported, including empty/unavailable cells; no multiple-testing significance claim.']}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--data',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    raw=a.data.read_bytes();ds=json.loads(raw)
    if ds.get('kind')!='public_verified_all200_reanalysis_dataset_v1':raise ValueError('Verified full200 dataset required')
    value=analyze(ds);value['input_sha256']=hashlib.sha256(raw).hexdigest();value['source_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    a.out.mkdir(parents=True,exist_ok=False)
    with (a.out/'exploratory-results.json').open('x',encoding='utf8') as f:json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')
    print(json.dumps({'assigned_runs':200,'new_sampling':False,'model_called':False,'evaluator_called':False}))

if __name__=='__main__':main()
