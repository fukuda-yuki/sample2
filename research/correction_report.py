"""Reproducible correction impact and provider-usage-format tables; no dispatch."""
import argparse
from collections import Counter, defaultdict
import copy
import csv
import hashlib
import json
from pathlib import Path

from research.correction_inventory import write_new
from research.summarize import distribution, summarize
from research.validate import read, safe_path

BASE = Path('artifacts/corrections/ms1-20260919-v1')


def shape(value):
    if isinstance(value, dict): return {k:shape(v) for k,v in sorted(value.items())}
    if isinstance(value, list): return [shape(v) for v in value]
    return type(value).__name__


def build(root, out):
    root, out = Path(root).resolve(), Path(out)
    if out.exists(): raise ValueError('Keep previous correction summaries; use a new directory')
    out.mkdir(parents=True)
    inventory = read(root/BASE/'baseline/inventory.json')
    entries = {r['run_instance_id']:r for r in inventory['runs']}
    old = {'runs':[], 'calls':[], 'actions':[]}
    for group in ('pilot','new'):
        source = read(root/BASE/('analysis-'+group)/'analysis.json')
        for key in old: old[key] += source[key]
    corrected = copy.deepcopy(old)
    rejudgement = read(root/BASE/'rejudgement-v1/summary.json')
    overlay = {c['run_instance_id']:c for c in rejudgement['corrections']}
    rows = []
    for r in corrected['runs']:
        original_quality, original_verdict = r['quality'], r['verdict']
        c = overlay.get(r['run_instance_id'])
        if c:
            if not c['pass']: raise ValueError('Invalid correction evaluation')
            if r['quality'] != c['original_quality'] or r['verdict'] != c['original_verdict']:
                raise ValueError('Correction bound to a different original result')
            r.update(quality=c['corrected_quality'],verdict=c['corrected_verdict'])
        rows.append({k:r[k] for k in ('cohort','condition','run_id','run_instance_id','calls','usage_complete','input_tokens','output_tokens','total_tokens')}
                    | {'original_quality':original_quality,'corrected_quality':r['quality'],
                       'original_verdict':original_verdict,'corrected_verdict':r['verdict'],
                       'quality_corrected':bool(c),'root':entries[r['run_instance_id']]['root']})
    groups=[]
    for cohort,condition in sorted({(r['cohort'],r['condition']) for r in rows}):
        rr=[r for r in rows if (r['cohort'],r['condition'])==(cohort,condition)]
        groups.append({'cohort':cohort,'condition':condition,'attempts':len(rr),
            'original_quality':distribution([r['original_quality'] for r in rr]),
            'corrected_quality':distribution([r['corrected_quality'] for r in rr]),
            'original_verdicts':dict(Counter(str(r['original_verdict']) for r in rr)),
            'corrected_verdicts':dict(Counter(str(r['corrected_verdict']) for r in rr)),
            'quality_missing':sum(r['corrected_quality'] is None for r in rr)})
    before, after = summarize(old), summarize(corrected)
    selection = after['human_review_selection']
    for r in selection:
        if r.get('run_instance_id'): r['root']=entries[r['run_instance_id']]['root']
    unchanged_selection = [r.get('run_instance_id') for r in before['human_review_selection']] == [r.get('run_instance_id') for r in selection]
    cohort_totals=[]
    for cohort in ('pilot','primary18','supplement'):
        rr=[r for r in rows if r['cohort']==cohort]
        cohort_totals.append({'cohort':cohort,'attempts':len(rr),'complete_runs':sum(r['usage_complete'] for r in rr),
            'calls':sum(r['calls'] for r in rr),
            'observed_input_tokens':sum(r['input_tokens'] for r in rr if r['input_tokens'] is not None),
            'observed_output_tokens':sum(r['output_tokens'] for r in rr if r['output_tokens'] is not None),
            'scope':'sum over completely measured Runs; absent Run usage remains null in individual rows'})
    write_new(out/'quality-impact.json',{'rows':rows,'groups':groups,'cohort_totals':cohort_totals,
        'human_review_selection':selection,'selection_unchanged':unchanged_selection,
        'human_review':'not_run','original_evaluations_replaced':False})
    with (out/'all-attempts.csv').open('x',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    write_new(out/'corrected-descriptive-summary.json',after)
    # Include all provider calls in the format audit. A numerical decrease alone
    # is not a schema change, and neither establishes a provider internal cause.
    schemas, calls, transitions, decreases = {}, [], [], []
    by_run=defaultdict(list)
    for call in old['calls']: by_run[call['run_instance_id']].append(call)
    for instance, records in by_run.items():
        previous=None
        for c in sorted(records,key=lambda x:x['call_index']):
            p=safe_path(root,entries[instance]['root'])/c['response_ref']
            packets=[]
            for line in p.read_text(encoding='utf-8').splitlines():
                if not line.startswith('data:') or line[5:].strip()=='[DONE]':continue
                packet=json.loads(line[5:])
                if packet.get('usage') is not None:packets.append(packet['usage'])
            formats=[]
            for packet in packets:
                structure=shape(packet)
                sid=hashlib.sha256(json.dumps(structure,sort_keys=True).encode()).hexdigest()
                schemas[sid]=structure;formats.append(sid)
            row={k:c[k] for k in ('cohort','condition','run_id','run_instance_id','call_index','request_id','input_tokens','output_tokens','input_delta','response_ref')}
            row.update(usage_packets=len(packets),schema_ids=sorted(set(formats)),final_schema_id=formats[-1] if formats else None,
                sent_message_chars=sum(c[k] for k in ('system_chars','user_chars','assistant_chars','tool_chars')),
                retained_message_chars=c['retained_message_chars'],disappeared_message_count=c['disappeared_message_count'])
            calls.append(row)
            if previous:
                pair={'before':previous,'after':row,'schema_changed':previous['final_schema_id']!=row['final_schema_id']}
                if pair['schema_changed']:transitions.append(pair)
                if row['input_delta'] is not None and row['input_delta'] < -3000:decreases.append(pair)
            previous=row
    write_new(out/'provider-usage-formats.json',{'calls_checked':len(calls),'schemas':schemas,
        'schema_call_counts':dict(Counter(c['final_schema_id'] for c in calls)),
        'schema_transitions':transitions,'large_input_decreases':decreases,'calls':calls,
        'decrease_selection':'post hoc delta input < -3000, descriptive only; no Run excluded',
        'primary_metric':'provider-reported input plus output, cache/reasoning not re-added',
        'limitation':'schema and characters are observable; provider internals and causal token attribution are not'})
    print(json.dumps({'attempts':len(rows),'corrected_artifacts':len(overlay),'selection_unchanged':unchanged_selection,
        'usage_calls':len(calls),'schemas':len(schemas),'schema_transitions':len(transitions),'large_decreases':len(decreases)}))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=Path.cwd());p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();build(a.root,a.out)


if __name__=='__main__':main()
