"""Prepare public statistical rows from the verified final acquisition index.

No acquisition, evaluation, rescoring or network calls. Known failed endpoints
require separate evidence audit decisions, bound to the original seq1 bytes.
Absent decisions stay unknown; raw frozen judgements remain separate columns.
This script must only be run after actual all-200 controller/observer closure.
"""
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import argparse
import hashlib
import json
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from quality_derivation import derive
from offline_reanalysis import validate
from outer.harness import browser_review,browser_cart,education_browser,util
import offline_reanalysis


def read(p):
    return json.loads(p.read_text(encoding='utf-8'))


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def save(p, value):
    with p.open('x', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write('\n')


def original_ref(root, path, inventory):
    rel = path.relative_to(root).as_posix()
    digest = sha(path)
    if inventory.get(rel, {}).get('sha256') != digest:
        raise ValueError('Original file changed since the verified final index: '+rel)
    return {'path': rel, 'sha256': digest}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--facts', type=Path, required=True)
    p.add_argument('--completion', type=Path, required=True)
    p.add_argument('--bundle', type=Path, required=True)
    p.add_argument('--audit-decisions', type=Path)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--private-out', type=Path, required=True)
    a = p.parse_args()
    facts, complete, bundle = read(a.facts), read(a.completion), read(a.bundle)
    if (complete.get('kind') != 'actual_completed_original100_pairs_200_runs_all_gates_and_terminated_controller'
        or (complete.get('pairs'), complete.get('actual_sent_runs'), complete.get('completed_pair_gates')) != (100, 200, 100)
        or complete.get('actual_controller_exit_code') != 0
        or complete.get('scoped_controller_observer_and_watch_absent') is not True
        or complete.get('actual_200_archives_verified') is not True
        or complete.get('all100_real_publication_restore_extraction_cleanup_gates_verified') is not True
        or complete['data']['sha256'] != sha(a.facts)
        or complete['original_bundle']['sha256'] != sha(a.bundle)):
        raise ValueError('Actual final acquisition/shutdown receipt and evidence bindings are required')
    if (facts['assigned_pairs'], facts['assigned_slots'], facts['actual_gateway_sent_runs'],
        facts['completed_pair_gates'], facts['unknown_send_runs'], facts['incomplete_runs'],
        facts['undispatched_runs']) != (100, 200, 200, 100, 0, 0, 0):
        raise ValueError('Only the exact fully preserved original 100/200 cohort is allowed')
    if sha(a.bundle) != facts['bundle_reference']['sha256']:
        raise ValueError('Original bundle identity mismatch')
    decisions = read(a.audit_decisions) if a.audit_decisions else {'decisions': []}
    decision_map = {}
    for d in decisions['decisions']:
        key = (d['run_id'], d['requirement_id'], d['check_id'])
        if key in decision_map:
            raise ValueError('Duplicate audit decision')
        decision_map[key] = d
    if a.private_out.resolve() == a.out.resolve() or a.private_out.resolve().is_relative_to(a.out.resolve()):
        raise ValueError('Private review queue must be outside the public dataset tree')
    all_rows, audits, private_queue, originals = [], [], [], []
    used_decisions = set()
    expected = {c['run_id']: c for pair in bundle['assignments'] for c in pair['cases']}
    if set(expected) != {f['run_id'] for f in facts['rows']} or len(expected) != 200:
        raise ValueError('Final index and original registry differ')
    for fact in facts['rows']:
        rid = fact['run_id']; case = expected[rid]
        if any(fact[k] != case[k] for k in ('run_instance_id', 'pair', 'task', 'condition', 'slot', 'position')):
            raise ValueError('Original assignment mismatch')
        root = Path(fact['original_location']); inv = fact['original_sha256']
        mp = root/'manifest.json'; manifest = read(mp)
        refs = {'manifest': original_ref(root, mp, inv)}
        if not all(manifest[k] is True for k in ('stop_confirmed', 'submission_fixed')):
            raise ValueError('Stopped/fixed original is required')
        ep = [q for q in root.glob('evaluations/*/record.json') if read(q).get('sequence') == 1]
        if len(ep) != 1 or len(list(root.glob('evaluations/*/record.json'))) != 1:
            raise ValueError('Exactly one untouched original evaluation is required')
        rp = ep[0]; rec = read(rp); directory = rp.parent
        if root/rec['directory'] != directory or rec['run_id'] != rid:
            raise ValueError('Original evaluation directory identity mismatch')
        refs['original_record'] = original_ref(root, rp, inv)
        ip = root/'evaluations/index.jsonl'
        index = [json.loads(x) for x in ip.read_text(encoding='utf-8').splitlines() if x.strip()]
        if len(index) != 1 or type(index[0].get('sequence')) is not int or index[0]['sequence'] != 1:
            raise ValueError('Original first evaluation index must contain exactly seq1')
        if any(rec.get(k) != v for k, v in index[0].items()):
            raise ValueError('Saved first evaluation index and record differ')
        refs['original_index'] = original_ref(root, ip, inv)
        sp = root/'evaluation-assets/requirements.json'; spec = read(sp)
        refs['frozen_spec'] = original_ref(root, sp, inv)
        required = [{'requirement_id': r['id'], 'check_id': c['id'], 'severity': r['severity']}
                    for r in spec['requirements'] for c in r['checks']]
        snapshot = read(root/'snapshot.json'); condition = read(root/'condition.json')
        refs['snapshot'] = original_ref(root, root/'snapshot.json', inv)
        refs['condition'] = original_ref(root, root/'condition.json', inv)
        evaluation_path, results_path = directory/'evaluation.json', directory/'results.jsonl'
        ev = read(evaluation_path) if evaluation_path.exists() else {}
        results = [json.loads(x) for x in results_path.read_text(encoding='utf-8').splitlines() if x.strip()] if results_path.exists() else []
        if ev: refs['original_evaluation'] = original_ref(root, evaluation_path, inv)
        if results_path.exists(): refs['original_results'] = original_ref(root, results_path, inv)
        raw = {(c['requirementId'], c['checkId']): c for c in results}
        if len(raw) != len(results): raise ValueError('Duplicate original check')
        expected_checks = {(c['requirement_id'],c['check_id']) for c in required}
        if set(raw) - expected_checks:
            raise ValueError('Original results contain a check outside the frozen ledger')
        if rec.get('adopted') is True and set(raw) != expected_checks:
            raise ValueError('An adopted evaluation must contain every exact frozen check')
        if spec['taskId'] != case['task'] or rec['evaluation_version'] != condition['evaluation']['evaluation_version']:
            raise ValueError('Frozen task/evaluation version mismatch')
        if rec['evaluator_sha256'] != condition['evaluation']['evaluator_sha256']:
            raise ValueError('Original evaluation build differs from its frozen Run condition')
        if ev and (ev['evaluationId'] != rec['evaluation_id'] or ev['taskId'] != case['task']
                   or ev['evaluationVersion'] != rec['evaluation_version']):
            raise ValueError('Original evaluation ID/task/version mismatch')
        identity = (manifest['run_instance_id'] == case['run_instance_id']
                    and rec['artifact_sha256_outer'] == snapshot['artifact_sha256']
                    and rec['spec_sha256'] == sha(sp) == condition['evaluation']['spec_sha256']
                    and not rec.get('mismatches')
                    and (not ev or (ev['artifactSha256'] == snapshot['artifact_sha256']
                                    and ev['specSha256'] == sha(sp)
                                    and rec['evaluation_sha256'] == sha(evaluation_path))))
        if ev.get('reviewRunInstanceId'):
            identity = identity and ev['reviewRunInstanceId'] == case['run_instance_id']
        coverage = bool(identity and rec.get('adopted') is True and rec['scoring_state'] == 'scored'
                        and ev.get('researchStatus') == 'complete'
                        and browser_review.stored_coverage_complete(directory, case['run_instance_id'],
                              snapshot['artifact_sha256'], rec['spec_sha256']))
        coverage_module=education_browser if rec['evaluation_version']==education_browser.VERSION else browser_cart
        checks = []
        for req in required:
            key = (req['requirement_id'], req['check_id']); item = raw.get(key, {})
            judgement = item.get('judgement'); state = 'unobserved'
            reason = 'Original check is missing, blocked, or lacks complete verified observation.'
            if judgement == 'pass' and coverage:
                state, reason = 'pass', 'Original seq1 check passed under verified complete finite evaluator/browser coverage.'
            elif judgement == 'fail':
                state, reason = 'ambiguous', 'Original failed judgement retained; product violation needs a check-specific source/evidence audit.'
            if not identity: state, reason = 'identity_invalid', 'Original identity chain could not be verified.'
            decision = decision_map.get((rid, *key))
            evidence = [refs.get('original_results', refs['original_record']), refs['frozen_spec']]
            if decision:
                if (decision['original_results_sha256'] != refs.get('original_results', {}).get('sha256')
                    or decision['run_instance_id'] != case['run_instance_id']
                    or decision['spec_sha256'] != sha(sp)
                    or not decision.get('reason') or not decision.get('evidence_references')
                    or decision.get('check_specific_semantic_audit_performed') is not True):
                    raise ValueError('Audit decision is not bound to original check bytes')
                used_decisions.add((rid,*key))
                for er in decision['evidence_references']:
                    relative = Path(er['path'])
                    if relative.is_absolute() or '..' in relative.parts:
                        raise ValueError('Audit evidence must be relative original Run material')
                    actual = original_ref(root, root/relative, inv)
                    if actual['sha256'] != er['sha256']:
                        raise ValueError('Audit decision evidence hash mismatch')
                state, reason = decision['derived_state'], decision['reason']
                evidence += decision['evidence_references']
            checks.append({**req, 'original_judgement': judgement, 'derived_state': state,
                'check_specific_semantic_audit_performed': bool(decision),
                'audit_disposition': ('manually_audited_confirmed' if state in ('pass','product_failure') else 'manually_audited_unresolved') if decision
                    else 'automatic_saved_coverage_confirmed_no_independent_semantic_audit' if state=='pass'
                    else 'not_semantically_audited',
                'reason': reason, 'evidence_references': evidence, 'identity_verified': identity,
                'evidence_valid': coverage if state == 'pass' and not decision else bool(decision and decision.get('evidence_valid') is True),
                'observation_complete': coverage if state == 'pass' and not decision else bool(decision and decision.get('observation_complete') is True),
                'product_violation_confirmed': bool(decision and decision.get('product_violation_confirmed') is True),
                'public_evidence_complete': False})
            if judgement == 'fail' or state not in ('pass', 'product_failure'):
                private_queue.append({'run_id': rid, 'run_instance_id': case['run_instance_id'], **req,
                    'original_results_sha256': refs.get('original_results', {}).get('sha256'),
                    'spec_sha256': sha(sp), 'original_judgement': judgement, 'current_state': state,
                    'check_specific_semantic_audit_performed':bool(decision),
                    'original_observation': item.get('observation'), 'original_evidence': item.get('evidence')})
        audit = {'run_id': rid, 'run_instance_id':case['run_instance_id'],
            'spec_sha256':sha(sp), 'original_sequence': 1, 'original_identity_verified': identity,
            'original_evidence_references': list(refs.values()), 'checks': checks,
            'saved_coverage_reconstruction': {'evaluation_version':rec['evaluation_version'],
                'dispatcher_source_sha256':sha(Path(browser_review.__file__)),
                'selected_handler_module':coverage_module.__name__,
                'selected_handler_source_sha256':sha(Path(coverage_module.__file__)),
                'historical_postprocessor_source_equivalence_verified':False,
                'check_specific_independent_semantic_audit_is_not_implied':True},
            'original_identity_chain_public': False, 'frozen_ledger_public': True, 'derivation_rule_public': True}
        endpoint = derive(required, audit); audits.append({**audit, 'derived': endpoint})
        usage = fact['saved_terminal_row']['usage']; start = manifest['started_at']
        np = root/'usage/normalized.json'; normalized = read(np)
        refs['normalized_usage'] = original_ref(root, np, inv)
        if normalized['run_instance_id'] != case['run_instance_id'] or normalized['run_id'] != rid:
            raise ValueError('Normalized usage identity mismatch')
        registry = {k:case[k] for k in ('run_id','run_instance_id','pair','task','slot','position')}
        registry['arm'] = case['condition']; originals.append(registry)
        u = {'complete': usage['usage_complete'] is True,
             **{k:usage.get(k) if usage['usage_complete'] is True else None for k in ('input_tokens','output_tokens','total_tokens')},
             'observed_partial': {'input_tokens':normalized.get('observed_input_tokens'),
                'output_tokens':normalized.get('observed_output_tokens'), 'total_tokens':normalized.get('observed_tokens')},
             'observed_request_count': normalized.get('observed_request_count'),
             'observed_call_count': normalized.get('observed_call_count'),
             'components_not_additional_to_input_output': {k:normalized.get(k) for k in
                 ('cache_read_tokens','cache_write_tokens','reasoning_tokens')},
             'partial_observed_totals_are_formal_lower_bounds': False}
        all_rows.append({**registry, 'source_family': fact['source_family'], 'analysis_session': (case['pair']-1)//4+1,
            'acquisition_phase': fact['acquisition_phase'], 'run_concurrency_cap': fact['run_concurrency_cap'],
            'acquisition_wave_pairs': fact['wave_pairs'],
            'wave_assigned_run_slots': fact['wave_assigned_run_slots'],
            'phase_configured_maximum_run_slots': fact['phase_configured_maximum_run_slots'],
            'assigned_order_quartile': (case['pair']-1)//25+1, 'started_at': start, 'ended_at': manifest['ended_at'],
            'start_date_utc': datetime.fromisoformat(start).astimezone(timezone.utc).date().isoformat(),
            'actual_send_observed': fact['actual_gateway_send_observed'], 'stop_confirmed': manifest['stop_confirmed'],
            'submission_fixed': manifest['submission_fixed'], 'pair_gate_verified': True,
            'full_pass': endpoint['full_pass'], 'critical_failure': endpoint['critical_failure'],
            'quality_derivation_rule': endpoint['rule_version'], 'quality_evidence_references': list(refs.values()),
            'raw_verdict': rec.get('verdict'), 'adopted': rec.get('adopted'),
            'original_numeric_quality': rec.get('quality'), 'scoring_state': rec['scoring_state'],
            'research_status': fact['saved_terminal_row']['scoring']['research_status'],
            'execution_state': fact['saved_terminal_row']['execution']['state'],
            'implementation_duration_seconds': manifest.get('duration_seconds'),
            'evaluator_sha256': rec['evaluator_sha256'],
            'spec_sha256':sha(sp), 'artifact_sha256':snapshot['artifact_sha256'],
            'evaluator_build_source_commit': condition['evaluation'].get('evaluator_build',{}).get('source_commit'),
            'usage': u})
    if used_decisions != set(decision_map):
        raise ValueError('Unused or outside-cohort/check audit decisions are forbidden')
    dataset = {'kind': 'public_verified_all200_reanalysis_dataset_v1',
        'plan': {k:bundle['plan'][k] for k in ('task_ids','variant_weights','task_hierarchy')},
        'cohort_identity': {'bundle_sha256': sha(a.bundle), 'acquisition_facts_sha256': sha(a.facts),
            'actual_completion_sha256': sha(a.completion), 'different_from_existing_result_release': True,
            'exporter_source_sha256':sha(Path(__file__)),
            'derivation_source_sha256':sha(Path(__file__).with_name('quality_derivation.py')),
            'audit_decision_input_sha256':sha(a.audit_decisions) if a.audit_decisions else None,
            'analysis_dependency_source_sha256':{name:sha(Path(module.__file__)) for name,module in
                [('browser_review',browser_review),('browser_cart',browser_cart),('education_browser',education_browser),
                 ('util',util),('offline_reanalysis',offline_reanalysis)]},
            'manual_decision_semantic_validity_requires_separate_review':True,
            'requested_response_model_id':'deepseek-v4.1-flash'},
        'original_assignments': originals, 'runs': all_rows}
    validate(dataset)
    a.out.mkdir(exist_ok=False)
    a.private_out.mkdir(exist_ok=False)
    save(a.out/'public-check-audit.json', {'rule_version': audits[0]['derived']['rule_version'], 'runs': audits})
    dataset['cohort_identity']['public_check_audit_sha256'] = sha(a.out/'public-check-audit.json')
    save(a.out/'public-dataset.json', dataset)
    save(a.private_out/'private-check-review-queue.json', {'public': False, 'checks': private_queue})
    save(a.out/'export-validation.json', {'runs':len(all_rows), 'pairs':100,
        'full_pass':dict(Counter(str(r['full_pass']) for r in all_rows)),
        'critical_failure':dict(Counter(str(r['critical_failure']) for r in all_rows)),
        'check_audit_dispositions':dict(Counter(c['audit_disposition'] for audit in audits for c in audit['checks'])),
        'all_200_dataset_sha256':sha(a.out/'public-dataset.json'),
        'no_rescore_or_model_calls':True, 'private_queue_must_not_be_published':True,
        'public_chain_and_raw_evidence_independent_reaudit':False})


if __name__ == '__main__': main()
