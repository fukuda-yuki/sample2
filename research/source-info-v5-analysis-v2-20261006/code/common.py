"""Offline, finite-cohort exploratory analysis; never calls models or evaluators."""
from pathlib import Path
from collections import defaultdict, Counter
from datetime import datetime, timezone
import hashlib, json, statistics, importlib.util

DATA_SHA = '8a74ffc4bf90b38297a7668eabe91befa572215c9facdf20c814e617efa125f3'
STOP_SHA = '9d7738e4cc54300667d90e59a51c364e6e580f4d25d3239cbfb551a9095df4df'
ARMS = ('explore', 'preload')
METRICS = ('input_tokens', 'output_tokens', 'total_tokens')

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def now(): return datetime.now(timezone.utc).isoformat()
def read(path): return json.loads(Path(path).read_text(encoding='utf-8'))
def save(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists(): raise FileExistsError(str(path))
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)+'\n', encoding='utf-8')

def load_dataset(data_dir):
    p=Path(data_dir)/'public-dataset.json'
    if sha(p)!=DATA_SHA: raise ValueError('Different original cohort dataset')
    d=read(p); rows=d['runs']; assignments={r['run_id']:r for r in d['original_assignments']}
    if len(rows)!=200 or len(assignments)!=200 or len({r['run_instance_id'] for r in rows})!=200: raise ValueError('Exact 200 identities required')
    for r in rows:
        if any(r[k]!=assignments[r['run_id']][k] for k in ('run_instance_id','pair','task','arm','slot','position')): raise ValueError('Assignment mismatch')
        if any(r[k] is not True for k in ('actual_send_observed','stop_confirmed','submission_fixed','pair_gate_verified')): raise ValueError('Unconfirmed acquisition')
        if r['full_pass'] is not None and (type(r['full_pass']) is not int or r['full_pass'] not in (0,1)): raise ValueError('Invalid quality')
        u=r['usage']
        if type(u['complete']) is not bool: raise ValueError('Invalid usage flag')
        if u['complete']:
            if any(type(u[k]) is not int or u[k]<0 for k in METRICS) or u['total_tokens']!=u['input_tokens']+u['output_tokens']: raise ValueError('Invalid totals')
        elif any(u[k] is not None for k in METRICS): raise ValueError('Incomplete totals must stay null')
    ps=pairs(rows)
    if len(ps)!=100 or sorted(ps)!=list(range(1,101)): raise ValueError('Exact 100 pairs required')
    if d['plan']['variant_weights']!=[.25]*4: raise ValueError('Fixed weights changed')
    if any(sum(r['task']==t and r['arm']==a for r in rows)!=25 for t in d['plan']['task_ids'] for a in ARMS): raise ValueError('Task/arm counts changed')
    return d

def pairs(rows):
    out=defaultdict(dict)
    for r in rows:
        if r['arm'] in out[r['pair']]: raise ValueError('Duplicate arm')
        out[r['pair']][r['arm']]=r
    if any(set(g)!=set(ARMS) or len({r['task'] for r in g.values()})!=1 for g in out.values()): raise ValueError('Pair mismatch')
    return dict(sorted(out.items()))

def mean(xs): return statistics.mean(xs) if xs else None
def quality(rows):
    out={}
    for a in ARMS:
        rr=[r for r in rows if r['arm']==a]; c=Counter(r['full_pass'] for r in rr); n=len(rr)
        out[a]={'assigned':n,'pass':c[1],'fail':c[0],'unknown':c[None], 'bounds':[c[1]/n,(c[1]+c[None])/n] if n else None}
    e,p=out['explore'],out['preload']
    out['difference_bounds']=[p['bounds'][0]-e['bounds'][1],p['bounds'][1]-e['bounds'][0]] if e['assigned'] and p['assigned'] else None
    return out

def pair_tokens(rows):
    ps=pairs(rows); out=[]
    for i,g in ps.items():
        e,p=g['explore'],g['preload']
        out.append({'pair':i,'task':e['task'],'family':e['source_family'],'complete':e['usage']['complete'] and p['usage']['complete'],
                    'both_pass':e['full_pass']==p['full_pass']==1,'both_completed':e['execution_state']==p['execution_state']=='completed',
                    'diff':{k:p['usage'][k]-e['usage'][k] if e['usage']['complete'] and p['usage']['complete'] else None for k in METRICS}})
    return out

def execute(round_id, code, data_dir, out_dir, fn):
    start=now(); d=load_dataset(data_dir); result=fn(d)
    out=Path(out_dir); result_path=out/'result.json'; save(result_path,result)
    sources={p.name:sha(p) for p in (Path(code),Path(__file__))}
    save(out/'execution-receipt.json',{'round':round_id,'started_at_utc':start,'completed_at_utc':now(),'input_dataset_sha256':DATA_SHA,
        'source_sha256':sources,'output_sha256':sha(result_path),'all_200_original_runs_used_as_base':True,'new_model_calls':0,'original_scores_changed':False})
    print(json.dumps({'round':round_id,'result_sha256':sha(result_path),'result':result},ensure_ascii=False))
