"""One user-approved preservation gate; original evaluator failure stays intact.

No models, scoring, retries or generic HTTP-failure classification. The only
admitted exception is the exact saved original53 fault and its explicit authority.
"""
from pathlib import Path

from outer.harness import util
from research import next_phase

KIND = 'exact_pair53_preservation_with_retained_evaluator_fault_v1'
CONTRACT_KIND = 'exact_pair53_retained_evaluator_fault_preservation_contract_v1'
RUN = 'CU1-ENR-D-preload-5053'
INSTANCE = 'ad3b80243f6a5a2daf5dbeb5fdfc1499'
ARTIFACT = '0fd7087077096bb1d6289a61bc0ec41aebbb9f1661c3eafc7ac89e341bc7a153'
PHASE = 'ee5d677792c029d004e03f9d33c37624a834b80ee7b22d22c0193318c368d28d'
PAIR_INSTANCES = {RUN: INSTANCE, 'CU1-ENR-D-explore-5053': '2c68755aa72f55ae8368fb3a60e886c7'}
SOURCE_MODULES = ('research/preservation_gate.py','research/pair_execution.py','research/wave_dispatch.py',
    'research/wave_plan.py','research/wave_campaign.py','research/wave_sharing.py','research/next_phase_sharing.py')
EVIDENCE = ('phase', 'authority', 'source_review', 'nonmodel_acceptance', 'boundary', 'journal_snapshot',
            'stop', 'fence', 'manifest', 'snapshot', 'postprocess', 'evaluation', 'record',
            'browser_events', 'browser_collector', 'browser_server_log', 'browser_fault',
            'browser_cleanup', 'archive_package', 'pair52_preload_events', 'pair52_explore_events')


def checked(reference):
    if (not isinstance(reference, dict) or set(reference) != {'path', 'sha256'}
            or not isinstance(reference['path'], str) or not isinstance(reference['sha256'], str)
            or not Path(reference['path']).is_absolute() or not Path(reference['path']).is_file()
            or not next_phase.verify_reference(reference)):
        raise ValueError('Preservation contract evidence missing or changed')
    return Path(reference['path'])


def validate_contract(reference, *, current=None):
    contract = util.read_json(checked(reference))
    if (contract.get('kind') != CONTRACT_KIND or contract.get('pair') != 53
            or contract.get('run_id') != RUN or contract.get('run_instance_id') != INSTANCE
            or contract.get('artifact_sha256') != ARTIFACT or contract.get('phase_sha256') != PHASE
            or contract.get('run_instances') != PAIR_INSTANCES
            or contract.get('retained_scoring_state') != 'evaluator_fault'
            or contract.get('quality') is not None or contract.get('quality_acceptance') is not False
            or contract.get('browser_coverage_completed') is not False
            or contract.get('model_called') is not False or contract.get('evaluator_called') is not False
            or contract.get('originals_scores_and_missingness_preserved') is not True):
        raise ValueError('Only the exact retained original53 fault is authorized')
    refs = contract.get('evidence', {})
    if set(refs) != set(EVIDENCE): raise ValueError('Exact preservation evidence set required')
    paths = {key: checked(value) for key, value in refs.items()}
    if refs['phase']['sha256'] != PHASE: raise ValueError('Different original phase')
    phase = util.read_json(paths['phase'])
    root = Path(phase['batch']) / RUN
    expected = {'manifest': root/'manifest.json', 'snapshot': root/'snapshot.json',
                'postprocess': root/'postprocess-receipt.json',
                'stop': Path(phase['batch'])/'_control'/phase['phase_id']/'dispatch-stop.json'}
    for key, path in expected.items():
        if paths[key].resolve() != path.resolve(): raise ValueError('Different saved instance evidence path')
    evaluation_root = root/'evaluations/evaluator_fault-001-5b7ef884605245af932d3d63d3579abb'
    fault_paths = {'evaluation':'evaluation.json','record':'record.json',
        'browser_events':'browser-school/events.json','browser_collector':'browser-school/collector-receipt.json',
        'browser_server_log':'browser-server.log','browser_fault':'browser-fault.json','browser_cleanup':'browser-cleanup.json'}
    if any(paths[key].resolve() != (evaluation_root/name).resolve() for key,name in fault_paths.items()):
        raise ValueError('Only the original saved fault attempt is covered')
    manifest, saved = util.read_json(paths['manifest']), util.read_json(paths['postprocess'])
    row = saved['row']
    if (manifest.get('run_id') != RUN or manifest.get('run_instance_id') != INSTANCE
            or manifest.get('stop_confirmed') is not True or manifest.get('submission_fixed') is not True
            or manifest.get('end_reason') != 'operator_stop'
            or saved.get('run_id') != RUN or saved.get('run_instance_id') != INSTANCE
            or saved.get('pair') != 53 or saved.get('phase_sha256') != PHASE
            or row.get('run_instance_id') != INSTANCE or row.get('quality') is not None
            or row.get('scoring', {}).get('state') != 'evaluator_fault'
            or row.get('scoring', {}).get('browser_review_coverage') != 'evaluator_fault'
            or row.get('usage', {}).get('usage_complete') is not True
            or row.get('browser_cleanup', {}).get('confirmed') is not True
            or row.get('network_cleanup', {}).get('confirmed') is not True
            or row.get('artifact', {}).get('artifact_sha256') != ARTIFACT
            or util.artifact_hash(root/'frozen') != ARTIFACT):
        raise ValueError('Original stopped/fixed fault, usage or cleanup evidence changed')
    evaluation, record = util.read_json(paths['evaluation']), util.read_json(paths['record'])
    if (evaluation.get('artifactSha256') != ARTIFACT or evaluation.get('reviewRunInstanceId') != INSTANCE
            or evaluation.get('quality') is not None or evaluation.get('humanReview') != 'not_run'
            or evaluation.get('browserReviewCoverage') != 'evaluator_fault'
            or evaluation.get('evaluatorFaults') != ['School browser collection incomplete']
            or record.get('scoring_state') != 'evaluator_fault' or record.get('quality') is not None
            or record.get('evaluation_sha256') != refs['evaluation']['sha256']):
        raise ValueError('Original evaluator fault cannot be changed or accepted as scored')
    for key in ('evaluation','record','browser_events','browser_collector','browser_server_log',
                'browser_fault','browser_cleanup'):
        if not paths[key].resolve().is_relative_to((root/'evaluations').resolve()):
            raise ValueError('Fault evidence must belong to the original saved evaluation')
    if paths['record'].parent != paths['evaluation'].parent:
        raise ValueError('Mixed evaluation attempts')
    events = util.read_json(paths['browser_events'])
    collector, fault = util.read_json(paths['browser_collector']), util.read_json(paths['browser_fault'])
    if (not any(e.get('kind') == 'response' and type(e.get('status')) is int and e['status'] == 500
                and e.get('url', '').endswith('/Student/Create') for e in events)
            or "The view 'Create' was not found" not in paths['browser_server_log'].read_text(encoding='utf-8')
            or collector.get('runInstanceId') != INSTANCE or collector.get('artifactSha256') != ARTIFACT
            or not collector.get('faults') or fault != {'type':'RuntimeError',
                'message':'School browser collection incomplete','scoring_state':'evaluator_fault'}
            or util.read_json(paths['browser_cleanup']).get('confirmed') is not True):
        raise ValueError('Exact saved product500/collector interruption/cleanup proof required')
    authority = util.read_json(paths['authority'])
    scope = authority.get('scope', {})
    if (authority.get('kind') != 'actual_user_exact_pair53_preservation_gate_adoption_authority'
            or authority.get('authorized') is not True or authority.get('approved_by') != 'user'
            or authority.get('actual_transcript_evidence_received') is not True
            or authority.get('user_reply_verbatim') != 'いいよ。承認します。'
            or scope.get('preservation_pair') != 53 or scope.get('fault_run_instance_id') != INSTANCE
            or scope.get('remaining_original_UUID_count') != 94
            or scope.get('originals_scores_and_missingness_preserved') is not True
            or scope.get('no_resend') is not True or scope.get('no_refill') is not True
            or scope.get('maximum_runs') != 4
            or scope.get('exception_automatically_extends_to_other_samples') is not False):
        raise ValueError('Explicit exact53 user adoption authority required')
    review, acceptance = util.read_json(paths['source_review']), util.read_json(paths['nonmodel_acceptance'])
    pins = contract.get('source_pins', {})
    source_root = Path(__file__).resolve().parents[1]
    if (review.get('status') != 'passed' or review.get('reviewed_commit') != contract.get('source_commit')
            or review.get('reviewed_source_sha256') != pins
            or acceptance.get('passed') is not True or acceptance.get('model_called') is not False
            or acceptance.get('evaluator_called') is not False
            or acceptance.get('source_commit') != contract.get('source_commit')
            or acceptance.get('source_pins') != pins
            or not set(SOURCE_MODULES) <= set(pins)):
        raise ValueError('Accepted prospective recovery source and nonmodel checks required')
    for name, digest in pins.items():
        path = (source_root/name).resolve()
        if not path.is_relative_to(source_root) or util.sha256_file(path) != digest:
            raise ValueError('Executing preservation source differs from independently accepted bytes')
    boundary = util.read_json(paths['boundary'])
    counts = boundary.get('counts', {})
    if (counts.get('gated_pairs') != 52 or counts.get('actually_sent_stopped_fixed_postprocessed_archived') != 106
            or counts.get('undispatched') != 94 or counts.get('pending_pair_gates') != [53]
            or boundary.get('stop_reference') != refs['stop']):
        raise ValueError('Exact52-gate/106-original/94-unsent stopped boundary required')
    journal = Path(phase['batch'])/'_control'/phase['phase_id']/'wave-journal.jsonl'
    prefix = paths['journal_snapshot'].read_bytes()
    if (refs['journal_snapshot']['sha256'] != boundary['closed_current_journal_reference']['sha256']
            or Path(boundary['closed_current_journal_reference']['path']).resolve() != journal.resolve()
            or not prefix or not prefix.endswith(b'\n') or not journal.read_bytes().startswith(prefix)):
        raise ValueError('Original pre-recovery journal prefix changed')
    fence = util.read_json(paths['fence'])['receipt']
    owned = {RUN:INSTANCE,'CU1-ENR-D-explore-5053':PAIR_INSTANCES['CU1-ENR-D-explore-5053'],
        'MS1-CONT-A-preload-5052':'92f2227e9c7c50cba1403bdc9cccbe72',
        'MS1-CONT-A-explore-5052':'395cad3db4235fb09f41d6dd9ca3bd47'}
    if (fence.get('http_fence_confirmed') is not True
            or len(fence.get('worker_stops', [])) != 4
            or {r.get('run_id'):r.get('run_instance_id') for r in fence['worker_stops']} != owned
            or any(r.get('stop_confirmed') is not True for r in fence['worker_stops'])
            or len(fence.get('gateway_receipts', [])) != 4
            or {r.get('run_id'):r.get('run_instance_id') for r in fence['gateway_receipts']} != owned
            or any(r.get('confirmed') is not True for r in fence['gateway_receipts'])):
        raise ValueError('Original distributed stop proof required')
    package = row.get('archive', {})
    expected_package = Path(phase['batch'])/'_archive/packages'/package.get('package_id','')/'package.json'
    if paths['archive_package'].resolve() != expected_package.resolve() or refs['archive_package']['sha256'] != package.get('sha256'):
        raise ValueError('Original archived package manifest changed')
    # These two separate saved streams remain incomplete; no usage fabrication.
    for key,rid,instance,count,request,status in (
            ('pair52_preload_events','MS1-CONT-A-preload-5052','92f2227e9c7c50cba1403bdc9cccbe72',11,
             '1a0a8777d93c4146a05a2c0ae400763e','provider_error'),
            ('pair52_explore_events','MS1-CONT-A-explore-5052','395cad3db4235fb09f41d6dd9ca3bd47',23,
             'afc14f3becc745f1bbc8272d9b552275','cancelled')):
        expected = Path(phase['batch'])/rid/'usage/raw/events.jsonl'
        if paths[key].resolve() != expected.resolve():
            raise ValueError('Missing usage evidence must be from its own original52 instance')
        events52 = util.read_lines(paths[key])
        if (len(events52) != count or any(e.get('run_id') != rid or e.get('session_id') != instance for e in events52)
                or not any(e.get('request_id') == request and e.get('status') == status
                    and e.get('usage_complete') is False and e.get('stream_done') is False for e in events52)):
            raise ValueError('Original52 missing usage must remain recorded separately')
    if current is not None:
        binding = current['dispatch'].get(RUN, {})
        selected = {b['run_id']:b['run_instance_id'] for b in current['dispatch'].values() if b['pair'] == 53}
        if (binding.get('phase_sha256') != PHASE or selected != PAIR_INSTANCES
                or current['results'].get(RUN, {}).get('row') != row):
            raise ValueError('Gate must preserve the exact authoritative original result row')
    return contract


def gate_fields(reference):
    contract = validate_contract(reference)
    return {'gate_kind':KIND,'preservation_contract':reference,'quality_acceptance':False,
            'retained_scoring_state':'evaluator_fault','recovery_source_commit':contract['source_commit']}


def public_disclosure(reference):
    contract = validate_contract(reference)
    return {'kind':KIND,'pair':53,'contract_sha256':reference['sha256'],
            'recovery_source_commit':contract['source_commit'],'retained_scoring_state':'evaluator_fault',
            'quality':None,'quality_acceptance':False,'browser_coverage_completed':False,
            'meaning':'Original evaluation failed and browser quality evidence is incomplete. This gate verifies preservation/publication only; it does not accept quality or replace the original result.'}


def validate_gate(value, current, number):
    from research import pair_execution
    if (number != 53 or value.get('gate_kind') != KIND or value.get('phase_sha256') != PHASE
            or value.get('run_instances') != PAIR_INSTANCES or value.get('quality_acceptance') is not False
            or value.get('retained_scoring_state') != 'evaluator_fault'):
        raise ValueError('Unsupported retained-fault preservation gate')
    reference = value.get('preservation_contract', {})
    contract = validate_contract(reference,current=current)
    if (value.get('recovery_source_commit') != contract['source_commit']
            or value.get('evidence_files', {}).get(reference['path']) != reference['sha256']):
        raise ValueError('Private gate must bind actual recovery contract and source')
    selected = [b for b in current['dispatch'].values() if b['pair'] == 53]
    if any(b['run_id'] != RUN and pair_execution._postprocess_fault(current['results'][b['run_id']]['row'])
           for b in selected):
        raise ValueError('Exception cannot extend to another original result')
    pair_execution._validate_gate_common(value,current,number)
