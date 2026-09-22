"""Read-only, all-slot observations for the catalog technical pilot.

Retains every request and tool action, not only successful products. Source
access candidates are reviewed against the recorded commands; heuristics are
descriptive labels, never quality judgments or grounds to exclude a Run.
"""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re

from outer.harness import aggregate, evaluate, profiles, util
from research.analyze import numbered_lines, provider_response, strings
from research.catalog_identity import compare_initial


def access_labels(tool, inputs):
    path = str(inputs.get('filePath', ''))
    command = str(inputs.get('command', ''))
    text = path if tool == 'read' else command
    labels = []
    if tool == 'read':
        if '/legacy-source/' in path:
            labels.append('legacy_file_return')
            if path.endswith('/SampleData.cs'):
                labels.append('catalog_source_return')
        if path.endswith('/catalog-derived/catalog.json'):
            labels.append('derived_catalog_return')
        if path.endswith('/catalog-derived/raw-first.txt'):
            labels.append('catalog_packet_return')
    elif tool == 'bash' and any(p in text for p in ('/inputs/', 'SampleData.cs', 'catalog.json', 'catalog-derived', 'read-source')):
        labels.append('file_access_candidate_review_command')
    return labels


def observe(root, plan):
    root = Path(root)
    manifest = util.read_json(root/'manifest.json')
    starts = util.read_lines(root/'usage/raw/started.jsonl')
    ends = {e['request_id']:e for e in util.read_lines(root/'usage/raw/events.jsonl')}
    native = util.read_lines(root/'evidence/agent.jsonl')
    prompt = (root/'inputs/prompt.txt').read_bytes().decode('utf-8')
    packet = (root/'inputs/catalog-derived/raw-first.txt').read_bytes().decode('utf-8')
    usage = util.read_json(root/'usage/normalized.json') if (root/'usage/normalized.json').exists() else {}
    calls, tool_origins, exposures, issues = [], {}, defaultdict(list), []
    if len(starts) != len(ends):
        issues.append('incomplete_request_inventory')
    for number, start in enumerate(starts, 1):
        end = ends.get(start['request_id'], {})
        request = root/'usage/raw'/start['request_file']
        response = root/'usage/raw'/start['response_file']
        if util.sha256_file(request) != start['request_sha256']:
            issues.append('request_hash_mismatch:'+request.name)
        values, tool_calls, models, errors, done = provider_response(response) if response.exists() else (None,[],[],['missing_response'],False)
        if response.exists() and util.sha256_file(response) != end.get('response_sha256'):
            issues.append('response_hash_mismatch:'+response.name)
        issues.extend(str(number)+':'+e for e in errors)
        if values is not None:
            for key in ('input_tokens','output_tokens'):
                if values.get(key) != (end.get('usage') or {}).get(key):
                    issues.append('usage_raw_mismatch:'+str(number)+':'+key)
        for call in tool_calls:
            tool_origins[call['id']] = {'call_index':number,'request_id':start['request_id'],'provider_call':call}
        body = util.read_json(request)
        initial_texts = [text for message in body.get('messages',[]) if message.get('role')=='user'
                         for text in strings(message.get('content',''))]
        for mi, message in enumerate(body.get('messages', [])):
            if message.get('role') == 'tool':
                content = ''.join(strings(message.get('content', '')))
                exposures[message.get('tool_call_id')].append({'call_index':number,'message_index':mi,
                    'bytes':len(content.encode()), 'sha256':util.sha256_bytes(content.encode()),
                    'request_file':request.relative_to(root).as_posix()})
        calls.append({'call_index':number,'request_id':start['request_id'], 'status':end.get('status'),
            'http_status':end.get('http_status'),'response_models':models,'stream_done':done,
            'request_file':request.relative_to(root).as_posix(),'request_sha256':util.sha256_file(request),
            'response_file':response.relative_to(root).as_posix(),'response_sha256':util.sha256_file(response) if response.exists() else None,
            'input_tokens':(values or {}).get('input_tokens'),'output_tokens':(values or {}).get('output_tokens'),
            'initial_prompt_retained':any(prompt in text for text in initial_texts),
            'initial_packet_retained':any(packet in text for text in initial_texts),
            'request_utf8_bytes':request.stat().st_size})
    token_audit_issues = list(issues)
    actions = []
    seen = set()
    for line, entry in enumerate(native,1):
        if entry.get('type') != 'tool_use': continue
        part = entry['part']
        tid = part['callID']
        if tid in seen: issues.append('duplicate_native_tool:'+tid)
        seen.add(tid)
        state = part.get('state', {})
        output = state.get('output', '')
        exposure = exposures.get(tid, [])
        first = exposure[0] if exposure else None
        origin = tool_origins.get(tid,{})
        lines = numbered_lines(output) if part['tool']=='read' else {}
        actions.append({'tool_call_id':tid, 'tool':part['tool'], 'status':state.get('status'),
            'inputs':state.get('input',{}), 'labels':access_labels(part['tool'],state.get('input',{})),
            'origin_call':origin.get('call_index'), 'native_ref':'evidence/agent.jsonl:'+str(line),
            'native_output_utf8_bytes':len(output.encode()), 'native_output_sha256':util.sha256_bytes(output.encode()),
            'visible_numbered_lines': {'first':min(lines),'last':max(lines),'count':len(lines)} if lines else None,
            'truncation_notice_observed':bool(re.search(r'Output (?:capped|truncated)|output has been truncated',output,re.I)),
            'exposures':exposure, 'first_returned_utf8_bytes':first['bytes'] if first else None,
            'request_exposures':len(exposure),
            'later_exact_retentions':sum(e['sha256']==first['sha256'] for e in exposure[1:]) if first else 0,
            'later_changed_retentions':sum(e['sha256']!=first['sha256'] for e in exposure[1:]) if first else 0,
            'returned_bytes_exposure_sum':sum(e['bytes'] for e in exposure)})
    if seen != set(tool_origins):
        issues.append('native_provider_tool_inventory_differs')
    row = aggregate.row_for(root.parent,root.name)
    scoring = evaluate.last_scoring(root)
    evaluation = util.read_json(root/scoring['directory']/'evaluation.json') if scoring else {}
    baseline = Path(plan['probe'])/('MS1-001-'+manifest['intervention_id']+'-001')
    receipt_path = root/'usage/raw/first-request-contract.json'
    access_path = root/'state/catalog-access.json'
    comparison = compare_initial(root, baseline, plan) if starts else None
    initial = {'gateway':util.read_json(receipt_path) if receipt_path.exists() else None,
        'semantic_match_to_mock':comparison['matches'] if comparison else False,
        'comparison': comparison,
        'same_files_permissions_ranges':util.read_json(access_path)==util.read_json(baseline/'state/catalog-access.json') if access_path.exists() else False}
    sums = {}
    for key in ('input_tokens','output_tokens'):
        known = [c[key] for c in calls if type(c[key]) is int]
        sums['known_'+key] = sum(known) if known else None
        sums[key] = sum(known) if known and len(known)==len(calls) and usage.get('usage_complete') and not token_audit_issues else None
    sums['known_total_tokens'] = sum(v for k,v in sums.items() if k.startswith('known_') and v is not None) if any(v is not None for v in sums.values()) else None
    sums['total_tokens'] = sums['input_tokens']+sums['output_tokens'] if all(sums[k] is not None for k in ('input_tokens','output_tokens')) else None
    if sums['total_tokens'] != usage.get('total_tokens'):
        issues.append('normalized_total_differs')
    return {'run_id':root.name,'row':row,'initial_input':initial,'tokens':sums,'calls':calls,'actions':actions,
        'requirements':evaluation.get('requirements',[]),
        'evaluation_scope':{k:evaluation.get(k) for k in ('browserCartCoverage','evaluatorFaults','executionStatus','verdict','quality')},
        'runtime_cleanup':manifest.get('network_cleanup'), 'browser_cleanup':row.get('browser_cleanup'),
        'native_sessions':sorted({e['sessionID'] for e in native if e.get('sessionID')}),
        'usage_complete':usage.get('usage_complete'), 'usage_issues':usage.get('inventory_issues'),
        'audit_issues':issues, 'token_audit_issues':token_audit_issues,
        'tools_without_native_completion':sorted(set(tool_origins)-seen),
        'large_output_definition':'at least 10000 UTF-8 bytes in the first actual tool message; descriptive only',
        'large_outputs':[a for a in actions if (a['first_returned_utf8_bytes'] or 0)>=10000],
        'input_references':{name:util.sha256_file(root/name) for name in ('condition.json','inputs-manifest.json','context.json','inputs/prompt.txt','manifest.json')},
        'human_review':'not_run'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    plan=util.read_json(args.plan)
    history = None
    if plan.get('date_revision'):
        from research.catalog_date_revision import validate_history
        history = validate_history(args.plan, Path(__file__).resolve().parents[1])
    result=[]
    for case in plan['slots']:
        root=Path(plan['runs_dir'])/case['run_id']
        if (root/'manifest.json').exists():
            result.append({'case':case,**observe(root,plan)})
        else:
            result.append({'case':case,'run_id':case['run_id'],'state':'not_started','tokens':None,'requirements':[]})
    util.write_new_json(args.out, {'schema_version':1,'plan_sha256':util.sha256_file(args.plan),
        'cohort':plan['cohort'],'read_only':True,'runs':result,
        **({'date_revision_history': history, 'launch_receipt': util.read_json(Path(plan['runs_dir'])/'_control/launch-receipt.json')} if history else {}),
        'interpretation':'Technical pilot only; no efficacy or noninferiority inference; harness preflight reads excluded from model actions'})
    print(json.dumps([{'run':r['run_id'],'calls':len(r.get('calls',[])),'tokens':r['tokens'],
        'issues':r.get('audit_issues'),'quality':r.get('row',{}).get('quality')} for r in result]))


if __name__=='__main__': main()
