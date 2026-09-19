"""Portable completion gate for corrected analysis, preserving acquisition truth."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from outer.harness import preserve
from research.correction_inventory import write_new
from research.validate import digest, read, safe_path, issue_code


def audit(root, inventory_path, independent_path, originals_path, acquisition_code):
    root = Path(root).resolve()
    inventory, independent, originals = read(inventory_path), read(independent_path), read(originals_path)
    issues, archives, all_runs, all_calls, all_actions = [], [], [], [], []
    def check(ok, text):
        if not ok: issues.append(text)
    check(independent.get('pass'), 'independent_audit_failed')
    check(independent['inventory_sha256'] == digest(inventory_path), 'inventory_changed_since_independent_audit')
    check(inventory['all_originals_receipt_sha256'] == digest(originals_path), 'originals_receipt_changed')
    check(Counter(r['cohort'] for r in inventory['runs']) == {'pilot':6,'primary18':18,'supplement':1}, 'expected_cohorts')
    def fingerprint(value):
        return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode('utf-8')).hexdigest()
    initial = read(root/'runs/exploration-20260919-ms1/frozen-plan.json')
    resumed = read(root/'runs/exploration-20260919-ms1/resume-v1/resumed-plan.json')
    pilot = read(root/'runs/acceptance-64ad09cd85ca/acceptance-plan.json')
    frozen_checks=0
    for plan, code in [(initial,Path(acquisition_code).parent/'initial-research-source'),
                       (resumed,root/'runs/exploration-20260919-ms1/resume-v1/frozen-research-source')]:
        for name, sha in plan['research_code_hashes'].items():
            p = safe_path(code,name)
            check(p.is_file() and digest(p)==sha,'frozen_research_mismatch:'+str(p))
            frozen_checks+=1
        check(digest(root/'docs/ms1-exploration-20260919-protocol.md')==plan['protocol_sha256'],'frozen_protocol_mismatch')
    amendment=resumed['resume_amendment']
    check(digest(root/amendment['amendment_doc'])==amendment['amendment_doc_sha256'],'retry_amendment_mismatch')
    for result in independent['results']:
        source = safe_path(root, result['analysis'])
        check(digest(source) == result['analysis_sha256'], 'analysis_changed:' + result['group'])
        data = read(source)
        all_runs += data['runs']; all_calls += data['calls']; all_actions += data['actions']
    check(Counter(r['run_instance_id'] for r in all_runs) == Counter(r['run_instance_id'] for r in inventory['runs']), 'completion_run_inventory')
    by_instance = {r['run_instance_id']:r for r in inventory['runs']}
    for r in all_runs:
        allowed = set(by_instance[r['run_instance_id']].get('allowed_audit_issues', []))
        check(all(issue_code(i) in allowed for i in r['audit_issues']), 'unexpected_audit_issue:' + r['run_instance_id'])
    for key, items in [('run_instance_id',all_runs),('request_id',all_calls),('tool_call_id',all_actions)]:
        values = [i.get(key) for i in items]
        check(None not in values and len(values) == len(set(values)), 'global_duplicate_or_missing:' + key)
    sessions = set()
    for r in all_runs:
        current = {a['native_session_id'] for a in all_actions if a['run_instance_id'] == r['run_instance_id']}
        check(len(current) == int(r['calls'] > 0), 'native_session_count:' + r['run_instance_id'])
        check(not (current & sessions), 'reused_native_session')
        sessions.update(current)
    for name, sha in originals.items():
        p = safe_path(root, name)
        check(p.is_file() and digest(p) == sha, 'original_changed:' + name)
    for entry in inventory['runs']:
        run_root = safe_path(root, entry['root'])
        condition = read(run_root/'condition.json')
        expected = (pilot if entry['cohort']=='pilot' else initial)['condition_fingerprints']
        for key in ('task','runtime'):
            check(fingerprint(read(run_root/'profiles'/(key+'.json')))==expected[key],'frozen_profile:'+entry['run_instance_id']+':'+key)
        intervention=read(run_root/'profiles/intervention.json')
        check(fingerprint(intervention)==expected['interventions'][condition['condition_id']], 'frozen_intervention:'+entry['run_instance_id'])
        check(fingerprint(condition['runtime_lock'])==expected['runtime_lock'],'frozen_runtime_lock:'+entry['run_instance_id'])
        for name, sha in condition['runtime_lock']['controller_files'].items():
            p = Path(acquisition_code)/'outer/harness'/name
            check(p.is_file() and digest(p) == sha, 'acquisition_controller_mismatch:' + name)
        try:
            package = preserve.verify(safe_path(root, entry['archive']), entry['package']['package_id'], entry['package']['sha256'])
            archives.append({'run_instance_id':entry['run_instance_id'], 'package':entry['package'], 'files':len(package['files']), 'verified':True})
        except Exception as exc:
            issues.append('archive:' + entry['run_instance_id'] + ':' + str(exc))
    return {'pass':not issues, 'issues':issues, 'independent_audit_sha256':digest(independent_path),
        'inventory_sha256':digest(inventory_path), 'original_files_rechecked':len(originals),
        'calls':len(all_calls), 'actions':len(all_actions), 'attempts':len(all_runs), 'native_sessions':len(sessions),
        'frozen_research_files_checked':frozen_checks,
        'archives':archives, 'human_review':'not_run', 'confirmation_experiment':'not_run',
        'scope':'original completeness, immutable acquisition provenance and corrected analytical integrity'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=Path.cwd())
    p.add_argument('--inventory',type=Path,required=True)
    p.add_argument('--independent-audit',type=Path,required=True)
    p.add_argument('--original-hashes',type=Path,required=True)
    p.add_argument('--acquisition-code',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    result=audit(a.root,a.inventory,a.independent_audit,a.original_hashes,a.acquisition_code)
    write_new(a.out,result)
    print(json.dumps({k:v for k,v in result.items() if k!='archives'}))
    return int(not result['pass'])


if __name__=='__main__':
    raise SystemExit(main())
