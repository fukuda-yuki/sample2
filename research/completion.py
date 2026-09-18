"""Read-only completion audit for the authorized R1 continuation."""
import json
from pathlib import Path
from collections import Counter

from outer.harness import machine, preserve, runtime
from research.analyze import read_json, sha, write_json
from research.ledger import build_ledger
from research.network_recovery import docker, inventory


def main():
    repo = Path(__file__).resolve().parents[1]
    base = repo/'artifacts/exploration/20260919'
    batch = repo/'runs/exploration-20260919-ms1'
    plan = read_json(repo/'research/protocols/ms1-001-exploration-20260919-resume-v1.json')
    analysis = read_json(base/'new-resumed-v1/analysis.json')
    original = read_json(base/'pilot-v1.0.1/analysis.json')
    result = read_json(batch/'resume-v1/result.json')
    problems = []
    def check(ok, message):
        if not ok: problems.append(message)
    check(result['complete'] and not result['unstarted_initial_slots'], 'continuation_incomplete')
    ledger = build_ledger(batch, plan)
    check(not ledger['schedule_issues'], 'schedule_issues')
    check(len(ledger['ledger']) == 19, 'unexpected_attempt_count')
    check(Counter(r['cohort'] for r in analysis['runs']) == {'primary18':18,'supplement':1}, 'cohort_counts')
    check(sha(batch/'frozen-plan.json') == '7e4df4a319557b161368fe4fb1d68f5456229d2e6f5619e5ce37bbb58e0d318a', 'original_plan_changed')
    check(sha(batch/'resume-v1/resumed-plan.json') == 'a258e0d81304f1665d83b809e928410f6e9d7189f57e687d04910fdeefb9b011', 'resumed_plan_changed')
    check(sha(repo/'research/protocols/ms1-001-exploration-20260919-resume-v1.json') == sha(batch/'resume-v1/resumed-plan.json'), 'amended_plan_copy_mismatch')
    check(sha(repo/'research/protocols/ms1-001-exploration-20260919.json') == sha(batch/'frozen-plan.json'), 'original_plan_copy_mismatch')
    amendment = plan['resume_amendment']
    check(sha(repo/amendment['amendment_doc']) == amendment['amendment_doc_sha256'], 'amendment_document_changed')
    check(sha(batch/'batch-result.json') == amendment['prior_result_sha256'], 'original_result_changed')
    prior = (batch/'resume-v1/prior-journal.jsonl').read_bytes()
    prefix_preserved = (batch/'batch-journal.jsonl').read_bytes().startswith(prior)
    check(prefix_preserved, 'prior_journal_changed')
    check(sha(batch/'resume-v1/prior-journal.jsonl') == amendment['prior_journal_sha256'], 'prior_journal_receipt_changed')
    parser_fix = read_json(base/'parser-fix-v1.0.2.json')
    for name, digest in plan['research_code_hashes'].items():
        check(sha(batch/'resume-v1/frozen-research-source'/name)==digest, 'frozen_research_copy_changed:'+name)
        expected_current = parser_fix['after_sha256'] if name==parser_fix['changed_file'] else digest
        check(sha(repo/name) == expected_current, 'unrecorded_research_code_change:'+name)
    prior_receipts = read_json(base/'new-v1.0.1/source-hashes.json')
    prior_files_checked = 0
    for rid, files in prior_receipts.items():
        for name, digest in files.items():
            path = batch/rid/name
            check(path.is_file() and sha(path)==digest, 'original_segment_changed:'+rid+'/'+name)
            prior_files_checked += 1
    check(runtime.controller_files(repo) == read_json(repo/'artifacts/runtime/MS1-001/lock.json')['controller_files'], 'controller_changed')
    all_runs = original['runs'] + analysis['runs']
    all_calls = original['calls'] + analysis['calls']
    all_actions = original['actions'] + analysis['actions']
    for key, values in [('run_instance_id',[r['run_instance_id'] for r in all_runs]),
                        ('request_id',[c['request_id'] for c in all_calls]),
                        ('tool_call_id',[a['tool_call_id'] for a in all_actions])]:
        check(len(values) == len(set(values)), 'global_duplicate_'+key)
    sessions = {}
    for r in all_runs:
        ss = {a['native_session_id'] for a in all_actions if a['run_instance_id']==r['run_instance_id']}
        check(len(ss) == int(r['calls'] > 0), 'native_session_count:'+r['cohort']+'/'+r['run_id'])
        if ss:
            session = next(iter(ss))
            check(session not in sessions, 'reused_native_session:'+session)
            sessions[session] = r['run_instance_id']
        check(r['initial_prompt_present_calls']==r['calls'], 'initial_prompt_not_retained:'+r['run_id'])
        check(r['all_initial_blocks_present_calls']==r['calls'], 'initial_blocks_not_retained:'+r['run_id'])
        if r['calls']:
            first = next(c for c in all_calls if c['run_instance_id']==r['run_instance_id'] and c['call_index']==1)
            request = read_json(Path(r['root'])/first['request_ref'])
            check(not any(m.get('role') in ('assistant','tool') for m in request['messages']), 'first_request_has_history:'+r['run_id'])
    networks = inventory()
    network_names = {n['Name'] for n in networks}
    archives = []
    for r in analysis['runs']:
        root = Path(r['root'])
        manifest = read_json(root/'manifest.json')
        machine.verify_conditions(root, plan['condition_fingerprints'], r['condition'])
        check(manifest.get('stop_confirmed'), 'stop_not_confirmed:'+r['run_id'])
        check(manifest.get('submission_fixed'), 'submission_not_fixed:'+r['run_id'])
        check(not manifest.get('synthetic'), 'synthetic_run:'+r['run_id'])
        reference = read_json(root/'archive-reference.json')
        preserve.verify(batch/'_archive', reference['package_id'], reference['sha256'])
        archives.append({'run_id':r['run_id'], 'package_id':reference['package_id'], 'verified':True})
        if manifest.get('model_called'):
            check(read_json(root/'evidence/isolation.json')['verified'], 'isolation_not_verified:'+r['run_id'])
            state = read_json(root/'runtime.json')
            check(state['network'] not in network_names, 'private_network_not_reclaimed:'+r['run_id'])
            for role in ('worker','gateway'):
                state_text = docker('inspect',state[role],'--format','{{json .State}}')
                container = json.loads(state_text)
                check(not any(container.get(k) for k in ('Running','Restarting','Paused')), 'container_active:'+state[role])
    receipt = {'pass':not problems, 'issues':problems, 'initial_slots':18, 'supplements':1,
        'model_runs':sum(read_json(Path(r['root'])/'manifest.json').get('model_called',False) for r in analysis['runs']),
        'total_analyzed_runs':len(all_runs), 'total_calls':len(all_calls), 'total_actions':len(all_actions),
        'unique_native_sessions':len(sessions), 'archive_verifications':archives,
        'docker_network_count_after':len(networks), 'original_journal_prefix_preserved':prefix_preserved,
        'original_segment_files_rechecked':prior_files_checked,
        'post_acquisition_parser_fix':parser_fix,
        'human_review':'not_run', 'confirmation_experiment':'not_run'}
    target = base/'completion-check-resumed-v1.json'
    if target.exists(): raise SystemExit('Refusing to overwrite completion audit')
    write_json(target, receipt)
    print(json.dumps({k:v for k,v in receipt.items() if k!='archive_verifications'}, ensure_ascii=True))
    return int(bool(problems))


if __name__ == '__main__':
    raise SystemExit(main())
