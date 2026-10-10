"""Readable all-denominator tables from bound offline analysis outputs only."""
from pathlib import Path
import argparse,csv,hashlib,json
from offline_reanalysis import METRICS,validate,ordered_pairs

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path):return json.loads(path.read_bytes())
def cell(x):
    if x is None:return 'null'
    if isinstance(x,(dict,list)):return json.dumps(x,ensure_ascii=False,separators=(',',':'),allow_nan=False)
    if isinstance(x,bool):return str(x).lower()
    return x
def write(path,rows,fields):
    with path.open('x',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for row in rows:w.writerow({k:cell(row.get(k)) for k in fields})
def run_rows(ds):
    fields=['slot','pair','task','source_family','arm','position','run_id','run_instance_id',
        'acquisition_phase','acquisition_wave_pairs','run_concurrency_cap','phase_configured_maximum_run_slots',
        'analysis_session','started_at','ended_at','implementation_duration_seconds','execution_state',
        'scoring_state','research_status','raw_verdict','adopted','original_numeric_quality',
        'full_pass','critical_failure','spec_sha256','artifact_sha256','evaluator_sha256',
        'quality_derivation_rule','usage_complete','input_tokens','output_tokens','total_tokens',
        'observed_partial_input_tokens','observed_partial_output_tokens','observed_partial_total_tokens',
        'observed_request_count','cache_read_tokens_subset','cache_write_tokens_subset','reasoning_tokens_subset']
    rows=[]
    for r in sorted(ds['runs'],key=lambda r:r['slot']):
        u=r['usage'];out={k:r.get(k) for k in fields};out['usage_complete']=u['complete']
        for m in METRICS:out[m]=u.get(m);out['observed_partial_'+m]=u.get('observed_partial',{}).get(m) if not u['complete'] else None
        out['observed_request_count']=u.get('observed_request_count')
        for k in ('cache_read_tokens','cache_write_tokens','reasoning_tokens'):
            out[k+'_subset']=u.get('components_not_additional_to_input_output',{}).get(k)
        rows.append(out)
    return rows,fields
def pair_rows(ds):
    fields=['pair','task','source_family','first_assigned_arm','explore_run_id','preload_run_id',
        'explore_UUID','preload_UUID','explore_execution','preload_execution','explore_full_pass','preload_full_pass',
        'explore_critical_failure','preload_critical_failure','both_usage_complete']
    for m in METRICS:fields += ['explore_'+m,'preload_'+m,'preload_minus_explore_'+m]
    rows=[]
    for e,p in ordered_pairs(ds['runs']):
        good=e['usage']['complete'] and p['usage']['complete']
        out={'pair':e['pair'],'task':e['task'],'source_family':e['source_family'],
            'first_assigned_arm':e['arm'] if e['position']<p['position'] else p['arm'],
            'explore_run_id':e['run_id'],'preload_run_id':p['run_id'],'explore_UUID':e['run_instance_id'],
            'preload_UUID':p['run_instance_id'],'explore_execution':e['execution_state'],'preload_execution':p['execution_state'],
            'explore_full_pass':e['full_pass'],'preload_full_pass':p['full_pass'],
            'explore_critical_failure':e['critical_failure'],'preload_critical_failure':p['critical_failure'],
            'both_usage_complete':good}
        for m in METRICS:
            out['explore_'+m]=e['usage'].get(m);out['preload_'+m]=p['usage'].get(m)
            out['preload_minus_explore_'+m]=p['usage'][m]-e['usage'][m] if good else None
        rows.append(out)
    return rows,fields
def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('dataset','audit','analysis','supplementary','exploratory','out'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();ds=read(a.dataset);validate(ds);h=digest(a.dataset)
    if ds.get('kind')!='public_verified_all200_reanalysis_dataset_v1':raise ValueError('Exact verified full200 dataset required')
    if digest(a.audit)!=ds['cohort_identity']['public_check_audit_sha256']:raise ValueError('Public audit digest mismatch')
    audit=read(a.audit);outputs=[read(f) for f in (a.analysis,a.supplementary,a.exploratory)]
    if any(v.get('input_sha256')!=h for v in outputs):raise ValueError('Each analysis must bind the same actual dataset bytes')
    a.out.mkdir(parents=True,exist_ok=False)
    rr,rf=run_rows(ds);pr,pf=pair_rows(ds);assert len(rr)==200 and len(pr)==100
    write(a.out/'all-200-runs.csv',rr,rf);write(a.out/'all-100-pairs.csv',pr,pf)
    facts={r['run_id']:r for r in ds['runs']};checks=[]
    for r in audit['runs']:
        base={k:facts[r['run_id']][k] for k in ('run_id','run_instance_id','pair','task','arm')}
        for c in r['checks']:
            checks.append(base|{k:c.get(k) for k in ('requirement_id','check_id','severity','original_judgement',
                'derived_state','audit_disposition','check_specific_semantic_audit_performed','observation_complete',
                'product_violation_confirmed','public_evidence_complete')})
    fields=['run_id','run_instance_id','pair','task','arm','requirement_id','check_id','severity','original_judgement',
        'derived_state','audit_disposition','check_specific_semantic_audit_performed','observation_complete',
        'product_violation_confirmed','public_evidence_complete']
    write(a.out/'all-original-required-checks.csv',checks,fields)
    scenarios=outputs[0]['prespecified_missing_token_scenarios'];sf=['metric','missing_explore_multiplier',
        'missing_preload_multiplier','equal_variant_difference','identified_from_data','lower_bound_clamping_applied']
    write(a.out/'all-27-missing-token-scenarios.csv',scenarios,sf)
    receipt={'dataset_sha256':h,'source_sha256':digest(Path(__file__)),'run_rows':200,'pair_rows':100,
        'required_check_rows':len(checks),'missing_scenario_rows':len(scenarios),'null_serialization':'literal null, never zero',
        'source_outputs_sha256':{f.name:digest(f) for f in (a.audit,a.analysis,a.supplementary,a.exploratory)},
        'tables':{f.name:{'bytes':f.stat().st_size,'sha256':digest(f)} for f in sorted(a.out.glob('*.csv'))},
        'model_called':False,'evaluator_called':False}
    with (a.out/'table-validation.json').open('x',encoding='utf8') as f:json.dump(receipt,f,indent=2,allow_nan=False);f.write('\n')
    print(json.dumps({'runs':200,'pairs':100,'checks':len(checks),'scenarios':len(scenarios)}))
if __name__=='__main__':main()
