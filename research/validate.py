"""Independent read-only reconciliation of provider originals and analysis receipts.

Deliberately does not import the extraction/aggregation helpers. Findings are
recorded, including expected missing data, rather than repaired or zero-filled.
"""
import argparse
import hashlib
import json
from pathlib import Path


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f,'sha256').hexdigest()


def raw_usage(path):
    """Independently locate the last non-null provider usage packet."""
    packets=[]
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        if line.startswith('data:') and line[5:].strip()!='[DONE]':
            try:
                value=json.loads(line[5:])
            except ValueError:
                continue
            if isinstance(value.get('usage'),dict):
                packets.append(value['usage'])
    if not packets:
        return None,None
    return packets[-1].get('prompt_tokens'),packets[-1].get('completion_tokens')


def validate(source):
    data=read(source)
    receipts=read(source.parent/'source-hashes.json')
    failures=[]
    rows=[]
    files=0
    def check(ok,context):
        if not ok:
            failures.append(context)
    ids=[r['run_instance_id'] for r in data['runs']]
    check(len(ids)==len(set(ids)),'duplicate_run_instance')
    for r in data['runs']:
        root=Path(r['root'])
        prefix=r['cohort']+'/'+r['run_id']
        calls=[c for c in data['calls'] if c['run_instance_id']==r['run_instance_id']]
        observed_in=observed_out=unknown=0
        request_ids=[]
        for c in calls:
            request_ids.append(c['request_id'])
            path=root/c['response_ref'] if c.get('response_ref') else None
            ip,op=raw_usage(path) if path and path.is_file() else (None,None)
            check(ip==c['input_tokens'] and op==c['output_tokens'],prefix+'/call/'+str(c['call_index']))
            if ip is not None:observed_in+=ip
            if op is not None:observed_out+=op
            unknown+=int(ip is None or op is None)
        check(len(request_ids)==len(set(request_ids)),prefix+'/duplicate_request')
        expected_in=observed_in if any(c['input_tokens'] is not None for c in calls) else None
        expected_out=observed_out if any(c['output_tokens'] is not None for c in calls) else None
        check(expected_in==r['observed_input_tokens'],prefix+'/observed_input')
        check(expected_out==r['observed_output_tokens'],prefix+'/observed_output')
        if r['usage_complete']:
            check(unknown==0,prefix+'/false_complete')
            check(r['total_tokens']==observed_in+observed_out,prefix+'/complete_total')
            check(r['input_tokens']==observed_in and r['output_tokens']==observed_out,prefix+'/complete_parts')
        else:
            check(r['total_tokens'] is None,prefix+'/missing_total_not_null')
        for name,expected in receipts[r['run_id']].items():
            path=root/name
            check(path.is_file() and digest(path)==expected,prefix+'/changed/'+name)
            files+=1
        rows.append({'cohort':r['cohort'],'run_id':r['run_id'],'run_instance_id':r['run_instance_id'],
            'calls':len(calls),'unreported_call_usage':unknown,'observed_input_tokens':expected_in,
            'observed_output_tokens':expected_out,'authoritative_total':r['total_tokens'],
            'usage_complete':r['usage_complete']})
    return {'analysis':str(source),'analysis_sha256':digest(source),'files_checked':files,
            'runs':rows,'failures':failures,'pass':not failures}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--analysis',type=Path,action='append',required=True)
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    result=[validate(source) for source in args.analysis]
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with args.out.open('x',encoding='utf-8') as f:
        json.dump(result,f,ensure_ascii=False,indent=2)
        f.write('\n')
    print(json.dumps({'pass':all(x['pass'] for x in result),
          'files_checked':sum(x['files_checked'] for x in result),
          'failures':[e for x in result for e in x['failures']]}))
    return 0 if all(x['pass'] for x in result) else 1


if __name__=='__main__':
    raise SystemExit(main())
