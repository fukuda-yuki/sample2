"""Explicit public projection and offline recomputation of saved assessments.

Standard library only. No provider, evaluator, browser, Docker or Git invocation.
Private paths are inputs to projection only; they never enter the public data.
"""
import argparse
from collections import Counter
from decimal import Decimal, ROUND_HALF_EVEN
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import uuid
import zipfile

SCHEMA = 2
MAX_BYTES = 64 * 1024 * 1024
JUDGEMENTS = {'pass', 'fail', 'blocked', 'error', None}
ROW_KEYS = {'kind', 'assessment_id', 'validation_id', 'source_run_id', 'source_run_instance_id',
    'source_campaign_uuid', 'source_campaign_identity_status', 'source_artifact_sha256',
    'source_condition_sha256', 'source_spec_sha256', 'source_evaluation_version',
    'evaluation_version', 'evaluator_sha256', 'new_spec_sha256', 'plan_commit_declared',
    'plan_sha256', 'quality_method', 'requirements', 'checks', 'raw_verdict',
    'raw_research_status', 'reported_quality', 'validated_quality', 'adopted',
    'validation_status', 'operation_status', 'observer_fault', 'source_bytes_unchanged',
    'assessment_bytes_unchanged', 'cleanup_confirmed', 'finite_failure', 'cascade_warning',
    'model_calls', 'acquisition_count_increment', 'provenance'}
PROVENANCE_KEYS = {'assessment_metadata_sha256', 'initial_result_sha256', 'validation_receipt_sha256',
    'evaluation_json_sha256', 'results_jsonl_sha256', 'baseline_evaluation_sha256',
    'baseline_results_sha256', 'build_receipt_sha256', 'validation_implementation_sha256',
    'evaluation_controller_inventory', 'validation_controller_inventory'}


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def encode(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf8')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf8'))


def require(ok, message):
    if not ok: raise ValueError(message)


def hash_value(value):
    require(isinstance(value, str) and re.fullmatch(r'[a-f0-9]{64}', value), 'Expected SHA256')
    return value


def identity(value):
    require(isinstance(value, str), 'Expected UUID')
    parsed = uuid.UUID(value)
    require(value in (parsed.hex, str(parsed)), 'Noncanonical UUID')
    return value


def relative(name):
    require(isinstance(name, str) and not re.search(r'[\\:<>"|?*\x00-\x1f]', name), 'Nonportable path')
    p = PurePosixPath(name)
    require(name == p.as_posix() and not p.is_absolute() and p.parts
        and all(x not in ('.', '..') and not x.endswith(('.', ' ')) for x in p.parts), 'Unsafe path')
    reserved = {'CON', 'PRN', 'AUX', 'NUL', *[f'COM{i}' for i in range(1, 10)], *[f'LPT{i}' for i in range(1, 10)]}
    require(all(x.split('.')[0].upper() not in reserved for x in p.parts), 'Reserved path')
    return name


def public_text(value):
    """Deny host paths and credential-shaped text; not a complete secret review."""
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    require(not re.search(r'(?i)(?:(?<![a-z0-9])[a-z]:[\\/]|\\\\[^\\]|/home/|/Users/|Bearer\s+\S+)', text), 'Private host path or credential-shaped text')


def evidence_inventory_digest(root):
    """Match the pinned validator's digest of every saved assessment file."""
    root=Path(root).resolve();inventory={}
    for path in sorted(root.rglob('*')):
        require(not path.is_symlink() and not (hasattr(path,'is_junction') and path.is_junction()), 'Linked saved evidence')
        if path.is_file():inventory[path.relative_to(root).as_posix()]=sha(path)
    return hashlib.sha256(json.dumps(inventory,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def normalize_assessment(*, stage, validation, plan, expected_validation_sha256):
    """Allowlist IDs, hashes, labels and coarse confirmations; never export text evidence.

    The trusted validation digest is supplied by the operator's fixed aggregate.
    This projection does not replay private-oracle scoring or historical actions.
    """
    stage, validation, plan = Path(stage), Path(validation), Path(plan)
    require(sha(validation) == hash_value(expected_validation_sha256), 'Validation receipt digest mismatch')
    v=read(validation)
    require(evidence_inventory_digest(stage) == hash_value(v['assessment_inventory_sha256_after']), 'Assessment bytes changed since pinned validation')
    a, initial = read(stage/'assessment.json'), read(stage/'result.json')
    out, baseline = stage/'output', stage/'output/http-only'
    result, spec, plan_data = read(out/'evaluation.json'), read(stage/'evaluation-assets/requirements.json'), read(plan)
    require(v['assessment_id'] == a['assessment_id'] == initial['assessment_id'], 'Assessment mismatch')
    require(v['source_run_instance_id'] == a['source_run_instance_id'], 'Source Run mismatch')
    require(v['source_run_id'] == a['source_run_id'], 'Source label mismatch')
    require(v['output_sha256'] == sha(out/'evaluation.json'), 'Saved output changed since validation')
    require(v['original_result_sha256'] == sha(stage/'result.json'), 'Initial result changed since validation')
    require(result['evaluationVersion'] == a['evaluation_version'] == v['evaluation_version'], 'Version mismatch')
    require(result['artifactSha256'] == a['source_artifact_sha256'] and result['specSha256'] == a['new_spec_sha256'], 'Saved output binding mismatch')
    require(sha(stage/'evaluation-assets/requirements.json') == a['new_spec_sha256'], 'Spec bytes mismatch')
    require(result['baselineEvaluationSha256'] == sha(baseline/'evaluation.json')
        and result['baselineResultsSha256'] == sha(baseline/'results.jsonl'), 'Baseline evidence mismatch')
    commit = plan_data.get('source_commit')
    require(isinstance(commit, str) and re.fullmatch(r'[a-f0-9]{7,40}', commit), 'Plan commit declaration required')
    raw_req = {r['id']: r for r in result['requirements']}
    require(len(raw_req) == len(result['requirements']), 'Duplicate result requirement')
    observed_checks = [json.loads(line) for line in (out/'results.jsonl').read_text(encoding='utf8').splitlines() if line.strip()]
    pairs = [(c['requirementId'], c['checkId']) for c in observed_checks]
    require(len(pairs) == len(set(pairs)), 'Duplicate observed check')
    observed = {pair: c.get('judgement') for pair, c in zip(pairs, observed_checks)}
    reqs, checks = [], []
    for req in spec['requirements']:
        # Current pinned emitters use equal requirement weights, not severity weights.
        require(type(req.get('weight', 1)) is int and req.get('weight', 1) == 1, 'A new weight method requires explicit supported implementation')
        reqs.append({'id': req['id'], 'severity': req['severity'], 'weight': 1,
            'reported_judgement': raw_req.get(req['id'], {}).get('judgement')})
        for check in req['checks']:
            checks.append({'requirement_id': req['id'], 'check_id': check['id'],
                'reported_judgement': observed.get((req['id'], check['id']))})
    require(set(raw_req) <= {r['id'] for r in reqs}, 'Unexpected requirement result')
    require(set(observed) <= {(c['requirement_id'], c['check_id']) for c in checks}, 'Unexpected check result')
    build_receipt = stage/'evaluation-assets/evaluator/build-receipt.json'
    row = {'kind': 'saved_artifact_reassessment', 'assessment_id': a['assessment_id'], 'validation_id': v['validation_id'],
        'source_run_id': a['source_run_id'], 'source_run_instance_id': a['source_run_instance_id'],
        'source_campaign_uuid': None, 'source_campaign_identity_status': 'caller_asserted_unverified',
        'source_artifact_sha256': a['source_artifact_sha256'], 'source_condition_sha256': a['source_condition_sha256'],
        'source_spec_sha256': a['source_spec_sha256'], 'source_evaluation_version': a['source_evaluation_version'],
        'evaluation_version': a['evaluation_version'], 'evaluator_sha256': a['evaluator_sha256'],
        'new_spec_sha256': a['new_spec_sha256'], 'plan_commit_declared': commit, 'plan_sha256': sha(plan),
        'quality_method': 'equal_requirement_weight_v1', 'requirements': reqs, 'checks': checks,
        'raw_verdict': result['verdict'], 'raw_research_status': result['researchStatus'],
        'reported_quality': result.get('quality'), 'validated_quality': v.get('quality'), 'adopted': v['adopted'],
        'validation_status': v['validation_status'], 'operation_status': initial['operation_status'],
        'observer_fault': v['observer_fault'], 'source_bytes_unchanged': v['source_bytes_unchanged'],
        'assessment_bytes_unchanged': v['assessment_bytes_unchanged'], 'cleanup_confirmed': initial['cleanup_confirmed'],
        'finite_failure': v.get('finite_failure'), 'cascade_warning': v.get('dependent_check_cascade_warning', False),
        'model_calls': v['model_calls'], 'acquisition_count_increment': v['acquisition_count_increment'],
        'provenance': {'assessment_metadata_sha256': sha(stage/'assessment.json'), 'initial_result_sha256': sha(stage/'result.json'),
            'validation_receipt_sha256': sha(validation), 'evaluation_json_sha256': sha(out/'evaluation.json'),
            'results_jsonl_sha256': sha(out/'results.jsonl'), 'baseline_evaluation_sha256': sha(baseline/'evaluation.json'),
            'baseline_results_sha256': sha(baseline/'results.jsonl'),
            'build_receipt_sha256': sha(build_receipt) if build_receipt.is_file() else None,
            'validation_implementation_sha256': v['validation_implementation_sha256'],
            'evaluation_controller_inventory': v['evaluation_controller_inventory'],
            'validation_controller_inventory': v['validation_controller_inventory']}}
    validate_row(row)
    return row


def normalize_observation_scope(*, stage, validation, expected_validation_sha256, row):
    """Add coarse residual scope without modifying the saved public assessment row."""
    stage,validation=Path(stage),Path(validation);validate_row(row)
    require(sha(validation)==hash_value(expected_validation_sha256), 'Validation receipt digest mismatch')
    v=read(validation)
    require(evidence_inventory_digest(stage)==hash_value(v['assessment_inventory_sha256_after']), 'Assessment bytes changed since pinned validation')
    require(v['assessment_id']==row['assessment_id'], 'Scope assessment mismatch')
    output=stage/'output';result=read(output/'evaluation.json')
    require(sha(output/'evaluation.json')==row['provenance']['evaluation_json_sha256']
        and sha(output/'results.jsonl')==row['provenance']['results_jsonl_sha256'], 'Scope output binding mismatch')
    observed={}
    for line in (output/'results.jsonl').read_text(encoding='utf8').splitlines():
        if not line.strip():continue
        check=json.loads(line);pair=(check['requirementId'],check['checkId'])
        require(pair not in observed, 'Duplicate scope check')
        for name in ('unknownObservations','observationFaults'):
            require(isinstance(check.get(name,[]),list), 'Unknown scope metadata shape')
        observed[pair]=check
    checks=[]
    browser_unknown=set()
    if 'browserReviewCoverage' in result and result['browserReviewCoverage']!='agent_observed_StudentCreateEdit':browser_unknown.add('E-012')
    if 'browserCartCoverage' in result:
        cases=result.get('browserCartCases')
        if isinstance(cases,dict) and all(c in cases for c in ('C-015','C-016')):
            browser_unknown.update(c for c in ('C-015','C-016') if cases[c]!='observed')
        elif result['browserCartCoverage']!='agent_observed_C-015_C-016':browser_unknown.update(('C-015','C-016'))
    for c in row['checks']:
        pair=(c['requirement_id'],c['check_id']);raw=observed.get(pair)
        checks.append({'requirement_id':pair[0],'check_id':pair[1],
            'has_unknown_observation':raw is None or c['reported_judgement'] in (None,'blocked','error')
                or c['check_id'] in browser_unknown or bool(raw.get('unknownObservations',[])),
            'has_observer_fault':c['reported_judgement']=='error' or bool(raw and raw.get('observationFaults',[]))})
    require(set(observed)<={(c['requirement_id'],c['check_id']) for c in checks}, 'Unexpected scope check')
    for name in ('uncheckedScope','evaluatorFaults'):require(isinstance(result.get(name,[]),list), 'Unknown output scope metadata shape')
    scope={'method':'declared-output-and-check-flags-v1',
        'evaluation_json_sha256':row['provenance']['evaluation_json_sha256'],
        'results_jsonl_sha256':row['provenance']['results_jsonl_sha256'],
        'has_unchecked_scope':row['raw_research_status']!='complete' or row['validation_status']=='partial_observation'
            or bool(result.get('uncheckedScope',[])) or any(c['has_unknown_observation'] for c in checks),
        'has_observer_fault':bool(result.get('evaluatorFaults',[])) or any(c['has_observer_fault'] for c in checks),
        'checks':checks}
    validate_observation_scope(row,scope)
    return scope


def validate_observation_scope(row,scope):
    require(set(scope)=={'method','evaluation_json_sha256','results_jsonl_sha256','has_unchecked_scope','has_observer_fault','checks'}
        and scope['method']=='declared-output-and-check-flags-v1', 'Unreviewed observation scope')
    for name in ('evaluation_json_sha256','results_jsonl_sha256'):
        require(hash_value(scope[name])==row['provenance'][name], 'Scope provenance mismatch')
    for name in ('has_unchecked_scope','has_observer_fault'):require(type(scope[name]) is bool, 'Expected scope boolean')
    expected={(c['requirement_id'],c['check_id']) for c in row['checks']};pairs=[]
    for c in scope['checks']:
        require(set(c)=={'requirement_id','check_id','has_unknown_observation','has_observer_fault'}, 'Unreviewed check scope')
        for name in ('has_unknown_observation','has_observer_fault'):require(type(c[name]) is bool, 'Expected check scope boolean')
        pairs.append((c['requirement_id'],c['check_id']))
    require(len(pairs)==len(set(pairs)) and set(pairs)==expected, 'Check scope inventory mismatch')
    reported={(c['requirement_id'],c['check_id']):c['reported_judgement'] for c in row['checks']}
    for c in scope['checks']:
        judgement=reported[(c['requirement_id'],c['check_id'])]
        require(judgement not in (None,'blocked','error') or c['has_unknown_observation'], 'Hidden unobserved check')
        require(judgement!='error' or c['has_observer_fault'], 'Hidden error check')
    require(not any(c['has_unknown_observation'] for c in scope['checks']) or scope['has_unchecked_scope'], 'Hidden unknown scope')
    require(not any(c['has_observer_fault'] for c in scope['checks']) or scope['has_observer_fault'], 'Hidden observer fault')
    public_text(scope)


def validate_row(row):
    require(set(row) == ROW_KEYS, 'Unreviewed assessment fields')
    require(row['kind'] == 'saved_artifact_reassessment', 'Assessment is not acquisition')
    for name in ('assessment_id', 'validation_id', 'source_run_instance_id'): identity(row[name])
    require(re.fullmatch(r'[A-Za-z0-9_-]+', row['source_run_id']), 'Unsafe Run label')
    for name in ('source_artifact_sha256', 'source_condition_sha256', 'source_spec_sha256', 'evaluator_sha256', 'new_spec_sha256', 'plan_sha256'): hash_value(row[name])
    require(re.fullmatch(r'[a-f0-9]{7,40}', row['plan_commit_declared']), 'Invalid plan commit')
    for name in ('evaluation_version', 'source_evaluation_version'):
        require(re.fullmatch(r'[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*', row[name]), 'Invalid version')
    require(row['evaluation_version'] != row['source_evaluation_version'], 'Reassessment version must differ')
    require(row['source_campaign_uuid'] is None and row['source_campaign_identity_status'] == 'caller_asserted_unverified', 'Do not invent historical campaign identity')
    require(row['model_calls'] == 0 and type(row['model_calls']) is int
        and row['acquisition_count_increment'] == 0 and type(row['acquisition_count_increment']) is int, 'Reassessment cannot add model acquisition')
    for name in ('adopted','observer_fault','source_bytes_unchanged','assessment_bytes_unchanged','cleanup_confirmed','cascade_warning'):
        require(type(row[name]) is bool, 'Expected coarse boolean confirmation')
    require(row['quality_method'] == 'equal_requirement_weight_v1', 'Unknown quality method')
    reqs = row['requirements']; ids = [r['id'] for r in reqs]
    require(reqs and len(ids) == len(set(ids)), 'Invalid requirement inventory')
    for req in reqs:
        require(set(req) == {'id','severity','weight','reported_judgement'} and type(req['weight']) is int and req['weight'] == 1,
            'Unreviewed requirement fields or weights')
        require(re.fullmatch(r'(?:EDU-)?R-[0-9]{3}', req['id']) and req['reported_judgement'] in JUDGEMENTS, 'Invalid requirement label')
        require(req['severity'] in ('critical','major','minor','normal'), 'Invalid severity')
    pairs = []
    for c in row['checks']:
        require(set(c) == {'requirement_id','check_id','reported_judgement'} and c['requirement_id'] in ids
            and re.fullmatch(r'[CE]-[0-9]{3}', c['check_id']) and c['reported_judgement'] in JUDGEMENTS, 'Invalid check label')
        pairs.append((c['requirement_id'],c['check_id']))
    require(pairs and len(pairs) == len(set(pairs)), 'Duplicate check mapping')
    require({p[0] for p in pairs} == set(ids), 'Requirement without declared check scope')
    provenance = row['provenance']; require(set(provenance) == PROVENANCE_KEYS, 'Unreviewed provenance fields')
    for name,value in provenance.items():
        if name.endswith('_inventory'):
            require(isinstance(value,dict) and value, 'Missing controller inventory')
            for file,digest in value.items(): relative(file); hash_value(digest)
        elif value is not None: hash_value(value)
    failure = row['finite_failure']
    if failure is not None:
        require(set(failure) == {'verdict','requirements','source'} and failure['verdict'] in ('fail','fail_critical')
            and set(failure['requirements']) <= set(ids) and failure['source'] in ('composed','composed-product-http','http-only'), 'Invalid bound reported failure')
    public_text(row)


def derive_assessment(row,scope=None):
    validate_row(row)
    counts = Counter(r['reported_judgement'] or 'unknown' for r in row['requirements'])
    checks = Counter(c['reported_judgement'] or 'unknown' for c in row['checks'])
    if scope is not None:validate_observation_scope(row,scope)
    unknown_check_labels=[c['check_id'] for c in scope['checks'] if c['has_unknown_observation']] if scope else []
    faulted_check_labels=[c['check_id'] for c in scope['checks'] if c['has_observer_fault']] if scope else []
    has_unknown_scope=bool(any(counts[k] or checks[k] for k in ('blocked','error','unknown')) or scope and scope['has_unchecked_scope'])
    has_observer_fault=bool(row['observer_fault'] or scope and scope['has_observer_fault'])
    confirmations = all(row[k] for k in ('source_bytes_unchanged','assessment_bytes_unchanged','cleanup_confirmed'))
    complete = (row['adopted'] and row['validation_status'] == 'complete_observation'
        and row['raw_research_status'] == 'complete' and not has_observer_fault and not has_unknown_scope and confirmations
        and not any(counts[k] for k in ('blocked','error','unknown'))
        and not any(checks[k] for k in ('blocked','error','unknown')))
    quality = None
    if complete:
        quality = float((Decimal(counts['pass']) * 100 / Decimal(len(row['requirements']))).quantize(Decimal('.01'), rounding=ROUND_HALF_EVEN))
        require(quality == row['validated_quality'] == row['reported_quality'], 'Recomputed quality differs from preserved results')
    else:
        require(row['validated_quality'] is None and not row['adopted'], 'Partial/fault observation cannot adopt quality')
    critical = [r['id'] for r in row['requirements'] if r['severity']=='critical' and r['reported_judgement']=='fail']
    incomplete_scope={c['requirement_id'] for c in scope['checks'] if c['has_unknown_observation'] or c['has_observer_fault']} if scope else set()
    critical_unknown = [r['id'] for r in row['requirements'] if r['severity']=='critical'
        and (r['reported_judgement'] not in ('pass','fail') or r['id'] in incomplete_scope)]
    if complete:
        verdict = 'fail_critical' if critical else 'fail' if counts['fail'] else 'pass'
        require(row['raw_verdict'] in ({'pass','pass_auto'} if verdict=='pass' else {verdict}), 'Complete verdict disagrees with requirement labels')
    else:
        verdict = None  # Keep partial bound failures in a separate field.
    return {'assessment_id':row['assessment_id'], 'source_run_instance_id':row['source_run_instance_id'],
        'evaluation_version':row['evaluation_version'], 'complete_observation':complete, 'quality':quality,
        'complete_verdict':verdict, 'raw_verdict':row['raw_verdict'], 'bound_reported_failure':row['finite_failure'],
        'observer_fault':row['observer_fault'], 'cascade_warning':row['cascade_warning'],
        'requirement_counts':dict(sorted(counts.items())), 'check_counts':dict(sorted(checks.items())),
        'critical_reported_failed_labels':critical, 'critical_unknown_labels':critical_unknown,
        'scope_method':scope['method'] if scope else 'judgement-labels-only-unsealed',
        'has_unknown_scope':has_unknown_scope,'has_observer_fault':has_observer_fault,
        'unlocalized_unknown_scope':has_unknown_scope and not unknown_check_labels
            and not any(counts[k] for k in ('blocked','error','unknown')),
        'unknown_check_labels':unknown_check_labels,'faulted_check_labels':faulted_check_labels,
        'model_calls':0, 'new_acquisition_runs':0}


def _derive_assessments_only(data):
    required={'schema_version','kind','original_experiment','assessments','operational_acceptance'}
    require(required<=set(data)<=required|{'observation_scopes'}, 'Unreviewed dataset fields')
    require(data['schema_version']==SCHEMA and data['kind']=='evaluator_repair_public_projection', 'Unknown dataset schema')
    original=data['original_experiment']
    require(set(original)=={'experiment_id','assignment_pairs','assignment_runs','bundle_sha256','dataset_sha256','release_url'}, 'Unreviewed original reference')
    require(original['assignment_pairs']==100 and original['assignment_runs']==200, 'Original cohort denominator changed')
    hash_value(original['bundle_sha256']);hash_value(original['dataset_sha256'])
    require(original['release_url'].startswith('https://github.com/fukuda-yuki/sample2/releases/tag/'), 'Unexpected source Release')
    rows=data['assessments'];ids=[r['assessment_id'] for r in rows]
    require(rows and len(ids)==len(set(ids)), 'Duplicate assessment identity')
    validations=[r['validation_id'] for r in rows];require(len(validations)==len(set(validations)), 'Duplicate validation identity')
    source_artifacts={}
    for r in rows:
        old=source_artifacts.setdefault(r['source_run_instance_id'],r['source_artifact_sha256'])
        require(old==r['source_artifact_sha256'], 'Same source UUID with different artifacts')
    scopes=data.get('observation_scopes')
    if scopes is not None:require(isinstance(scopes,dict) and set(scopes)==set(ids), 'Exact assessment scope identities required')
    results=[derive_assessment(r,scopes[r['assessment_id']] if scopes is not None else None) for r in sorted(rows,key=lambda r:r['assessment_id'])]
    operational=data['operational_acceptance']
    if operational is not None: validate_operational(operational)
    public_text(data)
    return {'schema_version':SCHEMA,'kind':'evaluator_repair_recomputed_summary',
        'saved_assessment_count':len(rows),'unique_saved_source_runs':len(source_artifacts),
        'complete_observation_count':sum(r['complete_observation'] for r in results),
        'partial_or_fault_count':sum(not r['complete_observation'] for r in results),
        'complete_verdict_counts':dict(sorted(Counter(r['complete_verdict'] for r in results if r['complete_verdict']).items())),
        'observer_fault_count':sum(r['has_observer_fault'] for r in results),
        'validation_observer_fault_count':sum(r['observer_fault'] for r in results),
        'unknown_scope_count':sum(r['has_unknown_scope'] for r in results),
        'evaluation_version_counts':dict(sorted(Counter(r['evaluation_version'] for r in rows).items())),
        'operation_status_counts':dict(sorted(Counter(r['operation_status'] for r in rows).items())),
        'model_calls':0,'new_acquisition_runs':0,'original_assignment_runs':200,
        'nonmodel_operational_campaigns':len(operational['campaigns']) if operational else 0,
        'nonmodel_operational_runs':sum(len(c['runs']) for c in operational['campaigns']) if operational else 0,
        'operational_publication_phase':operational['publication_phase'] if operational else None,
        'operational_publication_gate_complete':operational['publication_gate_complete'] if operational else None,
        'assessments':results}


def validate_operational(value):
    # The operational producer owns its explicit reviewed projection; no raw log collection.
    require(isinstance(value,dict) and value.get('schema_version')==1
        and value.get('kind')=='nonmodel_operational_acceptance', 'Unexpected operational projection')
    require(set(value)<= {'schema_version','kind','campaigns','reassessment','provenance','limits','model_calls','new_acquisition_runs',
        'publication_phase','publication_gate_complete','phase_a_verification_sha256','phase_a_package_sha256'}, 'Unreviewed operational fields')
    phase=value['publication_phase'];require(phase in ('prepublication','final'), 'Explicit publication phase required')
    require(type(value['publication_gate_complete']) is bool and value['publication_gate_complete']==(phase=='final'), 'Publication gate/phase mismatch')
    if phase=='final':
        hash_value(value['phase_a_verification_sha256']);hash_value(value['phase_a_package_sha256'])
    else:
        require(value['phase_a_verification_sha256'] is None and value['phase_a_package_sha256'] is None, 'Prepublication cannot claim external proof')
    for name in ('model_calls','new_acquisition_runs'):
        if name in value: require(type(value[name]) is int and value[name]==0, 'Operational counts must be integer zero')
    allowed={'campaign_id','campaign_uuid','plan_sha256','backend','model_calls','pairs','runs','plan_commit_declared','source_snapshot_sha256'}
    run_allowed={'run_id','run_instance_id','session_id','session_create_verified','session_read_verified','session_abort_verified',
        'admission_ack_verified','observer_ack_verified','stop_confirmed','cleanup_confirmed','artifact_sha256',
        'source_snapshot_sha256','state','output_sha256','generation','observer_generation','model_calls','publication_gate_complete'}
    campaigns=value['campaigns'];require(len(campaigns)==2, 'Two operational campaigns required')
    require(len({c['campaign_uuid'] for c in campaigns})==2, 'Operational campaigns collide')
    run_ids=[]
    for c in campaigns:
        require(set(c)<=allowed and type(c['model_calls']) is int and c['model_calls']==0 and c['backend']=='providerless-opencode-session', 'Unreviewed or model operational campaign')
        identity(c['campaign_uuid']);hash_value(c['plan_sha256'])
        require(len(c['runs'])==2 and c['pairs']==1, 'Exactly one two-run dummy pair per campaign')
        for r in c['runs']:
            require(set(r)<=run_allowed, 'Unreviewed operational Run fields')
            identity(r['run_instance_id']);run_ids.append(r['run_instance_id']);hash_value(r['artifact_sha256']);hash_value(r['source_snapshot_sha256'])
            require(all(r.get(k) is True for k in ('session_create_verified','session_read_verified','session_abort_verified','admission_ack_verified','observer_ack_verified','stop_confirmed','cleanup_confirmed')), 'Operational acceptance confirmation missing')
            require(type(r.get('publication_gate_complete')) is bool and r['publication_gate_complete']==(phase=='final'), 'Production Run publication gate not observed')
            if 'model_calls' in r: require(type(r['model_calls']) is int and r['model_calls']==0, 'Operational Run cannot add model calls')
    require(len(run_ids)==len(set(run_ids)), 'Dummy Run identities collide')
    reassessment=value['reassessment']
    require(set(reassessment)<= {'assessment_id','source_run_instance_id','source_artifact_sha256','evaluation_version','acquisition_count_increment','source_unchanged','assessment_unchanged','state','model_calls'}, 'Unreviewed operational reassessment fields')
    identity(reassessment['assessment_id']);identity(reassessment['source_run_instance_id']);hash_value(reassessment['source_artifact_sha256'])
    require(reassessment['source_run_instance_id'] in run_ids and type(reassessment['acquisition_count_increment']) is int
        and reassessment['acquisition_count_increment']==0, 'Operational reassessment lineage mismatch')
    if 'model_calls' in reassessment: require(type(reassessment['model_calls']) is int and reassessment['model_calls']==0, 'Operational reassessment cannot add model calls')
    source_run=next(r for c in campaigns for r in c['runs'] if r['run_instance_id']==reassessment['source_run_instance_id'])
    require(reassessment['source_artifact_sha256']==source_run['artifact_sha256'], 'Operational reassessment artifact mismatch')
    if 'provenance' in value:
        require(isinstance(value['provenance'],dict), 'Expected receipt hash projection')
        for name,digest in value['provenance'].items(): relative(name);hash_value(digest)
    public_text(value)


README = '''# 評価器修正と保存生成物の別版再評価

INDEX.md → report/REPORT.md → data/assessments.json → code/evaluator_publication.py の順に読めます。
schema2は報告用assessment行と未検証HTTP-only試行を別type・別fileで保全します。未検証試行はquality null・validation ID nullのままです。
原100ペア・200 Runと今回の保存再評価は異なる単位です。モデル呼出し・新取得Run増分は0です。
異なる評価版のassessmentを元Run UUID・artifact SHAへ結合し、旧評価を置き換えません。
非モデルの2 campaign / 4 dummy Run / 1 reassessmentは研究サンプルへ加算しません。

専用Releaseの正確なZIPを新しいフォルダーへ展開し、Release本文のMANIFEST SHA256を控えます。
prepublication版Aは公開gate前の技術証跡です。最終版BはAの実匿名検証SHAと実journal gate完了を含む別packageです。
版Aを完了済み版Bへ書き換えず、公開後の同一package digestを自己証明に使いません。
Windows CPython 3.14.4、標準ライブラリのみ。展開先と異なるworking directoryからでも実行できます。

```powershell
python -B -X utf8 <展開先>/code/evaluator_publication.py reproduce --package <展開先> --expected-manifest-sha256 <Release本文のSHA256> --out <存在しない別フォルダー>
```

全ファイルのsize/SHA、manifestの完全inventory、IDの来歴、実保存評価の要求・check行を検査します。
completeだけ等重みの要求品質を再計算し、critical failureを別に判定します。
partial/faultのqualityはnullであり、報告された失敗ラベルと未観測scopeを保持します。
observation_scopesには公開行とは別に、各checkの未知観測・観測障害のcoarse booleanだけを保存します。
同じrequirementで報告failと残りの未知scopeが並存する場合も、両方を別配列で示します。
実rowから導いた結果がresults/summary.jsonとbyte一致し、終了0・新しいreceipt.jsonが揃えば完了です。
旧出力の上書き、未知method、改竄、path escape、重複IDは拒否します。

これは公開用最小投影から報告値を再計算する手順です。private oracle、DB、raw logs、画像、評価器binaryは含みません。
非公開素材を使ったfull scoring replay、過去の未観測操作の復元、全200の修正版再評価を意味しません。
coarse確認とhashは保存receiptの投影であり、第三者が原品質の意味を独立に再監査した証明ではありません。
source campaign UUIDのregistry検証は未成立のためnullを保持し、元Run UUIDを作り直しません。
将来の無故障や本格100再取得の開始可を保証しません。旧Releaseのbytesは維持します。
'''


def package_inventory(root):
    root=Path(root).resolve();result={}
    for p in root.rglob('*'):
        require(not p.is_symlink() and not (hasattr(p,'is_junction') and p.is_junction()), 'Linked package content')
        if p.is_file():
            name=relative(p.relative_to(root).as_posix())
            if name!='MANIFEST.json':result[name]={'sha256':sha(p),'bytes':p.stat().st_size}
    return dict(sorted(result.items()))




def _check_assessment_policy_only(data,policy):
    require(set(policy)=={'package_id','expected_assessment_ids','expected_assessment_versions','required_history_assessment_ids',
        'required_history_row_sha256','required_evaluation_versions','required_phase'}, 'Explicit exact seal policy required')
    ids={r['assessment_id'] for r in data['assessments']}
    require(ids==set(policy['expected_assessment_ids']) and len(ids)==len(policy['expected_assessment_ids']), 'Unfilled or unexpected assessment slot')
    history=policy['required_history_assessment_ids']
    require(len(history)==7 and len(set(history))==7 and set(history)<=ids, 'Preserve the original seven assessments')
    versions=policy['expected_assessment_versions']
    require(isinstance(versions,dict) and set(versions)==ids
        and all(versions[r['assessment_id']]==r['evaluation_version'] for r in data['assessments']), 'Assessment revision binding mismatch')
    history_hashes=policy['required_history_row_sha256']
    require(isinstance(history_hashes,dict) and set(history_hashes)==set(history), 'Pin all seven historical public rows')
    for row in data['assessments']:
        if row['assessment_id'] in history_hashes:
            require(hashlib.sha256(encode(row)).hexdigest()==hash_value(history_hashes[row['assessment_id']]), 'Historical public row changed')
    require(set(policy['required_evaluation_versions'])<={r['evaluation_version'] for r in data['assessments']}, 'Required revision not accepted yet')
    require(data['operational_acceptance'] is not None, 'Actual nonmodel operational acceptance is mandatory before seal')
    require(isinstance(data.get('observation_scopes'),dict), 'Coarse residual observation scope is mandatory before seal')
    validate_operational(data['operational_acceptance'])
    require(policy['required_phase']==data['operational_acceptance']['publication_phase'], 'Package phase differs from observed operational phase')




def reproduce(root, output, expected_manifest_sha256):
    root,output=Path(root).resolve(),Path(output).resolve()
    require(not output.is_relative_to(root) and not root.is_relative_to(output), 'Output must be outside package')
    require(not output.exists(), 'Reproduction output exists')
    manifest,summary=verify_package(root,expected_manifest_sha256)
    output.mkdir(parents=True,exist_ok=False);(output/'summary.json').write_bytes(encode(summary))
    receipt={'schema_version':SCHEMA,'kind':'actual_public_recomputation','package_id':manifest['package_id'],
        'manifest_sha256':expected_manifest_sha256,'summary_sha256':sha(output/'summary.json'),
        'verified_file_count':len(manifest['files']),'saved_assessment_count':summary['saved_assessment_count'],
        'reported_assessment_count':summary['reported_assessment_count'],
        'all_saved_reassessment_attempt_count':summary['all_saved_reassessment_attempt_count'],
        'unvalidated_http_only_attempt_count':summary['unvalidated_http_only_attempt_count'],
        'model_calls':0,'new_acquisition_runs':0,'all_derived_bytes_match':True}
    (output/'receipt.json').write_bytes(encode(receipt));return receipt


def zip_package(root,destination,expected_manifest_sha256):
    manifest,_=verify_package(root,expected_manifest_sha256)
    with Path(destination).open('xb') as stream,zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as z:
        for name in sorted([*manifest['files'],'MANIFEST.json']):z.write(Path(root)/name,name)
    return sha(destination)



# Schema2 adds immutable, unvalidated HTTP-only attempt records. The assessment
# row schema remains unchanged; quality is derived only from receipted rows.
ATTEMPT_KEYS = set(['acquisition_count_increment', 'assessment_id', 'browser_exit_code', 'browser_started', 'cleanup_confirmed', 'evaluation_version', 'evaluator_exit_code', 'evaluator_sha256', 'http_check_judgement_counts', 'http_has_observer_faults', 'http_has_unknown_observations', 'http_raw_research_status', 'http_raw_verdict', 'http_requirement_judgement_counts', 'kind', 'model_calls', 'new_spec_sha256', 'observed_stage', 'pipeline_complete', 'pipeline_gate_fault', 'plan_commit_declared', 'plan_sha256', 'provenance', 'quality', 'source_artifact_sha256', 'source_bytes_unchanged', 'source_campaign_identity_status', 'source_campaign_uuid', 'source_condition_sha256', 'source_evaluation_version', 'source_run_id', 'source_run_instance_id', 'source_spec_sha256', 'validated', 'validation_id'])
ATTEMPT_PROVENANCE_KEYS = set(['assessment_metadata_sha256', 'evaluator_manifest_sha256', 'fixed_aggregate_sha256', 'http_evaluation_json_sha256', 'http_results_jsonl_sha256', 'initial_result_sha256', 'observed_stage_inventory_sha256'])
ATTEMPTS_PATH = 'data/assessment-attempts.json'


def normalize_unvalidated_attempt(*, stage, plan, aggregate, expected_plan_sha256, expected_aggregate_sha256):
    """Preserve a pinned HTTP-only gate failure without asserting validation.

    Binding checks here make a public projection eligible. They do not execute
    the evaluator, create a validation receipt or adopt any numeric quality.
    Source/cleanup booleans are copied from the historical execution receipt.
    """
    stage,plan,aggregate=Path(stage),Path(plan),Path(aggregate)
    require(sha(plan)==hash_value(expected_plan_sha256) and sha(aggregate)==hash_value(expected_aggregate_sha256), 'Pinned attempt input changed')
    before=evidence_inventory_digest(stage)
    plan_data,group=read(plan),read(aggregate)
    require(group['plan_sha256']==expected_plan_sha256, 'Attempt plan/aggregate mismatch')
    for record in (plan_data,group):
        for name in ('model_calls','acquisition_count_increment'):
            require(type(record[name]) is int and record[name]==0, 'Attempt input cannot add model acquisition')
    a,r=read(stage/'assessment.json'),read(stage/'result.json')
    cases=[c for c in group['cases'] if c['assessment_id']==a['assessment_id']]
    require(len(cases)==1 and cases[0]['source_run_id']==a['source_run_id'], 'Attempt not in fixed aggregate')
    require(all(cases[0].get(k)==value for k,value in r.items()), 'Initial attempt result differs from fixed aggregate')
    output=stage/'output/http-only';result=read(output/'evaluation.json');manifest=read(output/'evaluator-manifest.json')
    require(isinstance(r.get('raw_result'),str), 'Attempt raw result reference missing')
    raw_path=Path(r['raw_result']);raw_path=raw_path if raw_path.is_absolute() else stage/raw_path
    require(raw_path.resolve()==(output/'evaluation.json').resolve(), 'Attempt raw result reference mismatch')
    require(a['assessment_id']==r['assessment_id'] and a['evaluation_version']==result['evaluationVersion']==manifest['evaluationVersion']=='1.6.0', 'Attempt identity/version mismatch')
    require(result['artifactSha256']==manifest['artifactSha256']==a['source_artifact_sha256'], 'Attempt artifact mismatch')
    require(result['specSha256']==manifest['specSha256']==a['new_spec_sha256']==sha(stage/'evaluation-assets/requirements.json'), 'Attempt spec mismatch')
    require(manifest['evaluatorSha256']==a['evaluator_sha256']==sha(stage/'evaluation-assets/evaluator/MusicStore.Evaluator.dll'), 'Attempt actual DLL mismatch')
    require(r['evaluator_exit_code']==2 and r.get('browser_exit_code') is None and r['adopted'] is False
        and r['quality'] is None and r['full_bound_browser_observation'] is False, 'Attempt cannot represent completed browser validation')
    require(not (stage/'output/evaluation.json').exists() and not (stage/'output/results.jsonl').exists(), 'Attempt has composed output; classification needs review')
    checks=[json.loads(line) for line in (output/'results.jsonl').read_text(encoding='utf8').splitlines() if line.strip()]
    require(len(checks)==len({(c['requirementId'],c['checkId']) for c in checks}), 'Duplicate HTTP attempt check')
    row={'kind':'unvalidated_saved_reassessment_attempt','assessment_id':a['assessment_id'],
        'validation_id':None,'validated':False,'quality':None,
        **{name:a[name] for name in ('source_run_id','source_run_instance_id','source_artifact_sha256','source_condition_sha256',
            'source_spec_sha256','source_evaluation_version','evaluation_version','evaluator_sha256','new_spec_sha256')},
        'source_campaign_uuid':None,'source_campaign_identity_status':'caller_asserted_unverified',
        'plan_commit_declared':plan_data['source_commit'],'plan_sha256':expected_plan_sha256,
        'observed_stage':'http_only','browser_started':False,'pipeline_complete':False,
        'pipeline_gate_fault':'http_exit2_rejected_before_browser','evaluator_exit_code':2,'browser_exit_code':None,
        'cleanup_confirmed':r['cleanup_confirmed'],'source_bytes_unchanged':r['source_unchanged'],
        'model_calls':0,'acquisition_count_increment':0,'http_raw_verdict':result['verdict'],'http_raw_research_status':result.get('researchStatus'),
        'http_requirement_judgement_counts':dict(sorted(Counter(x.get('judgement') or 'unknown' for x in result['requirements']).items())),
        'http_check_judgement_counts':dict(sorted(Counter(x.get('judgement') or 'unknown' for x in checks).items())),
        'http_has_unknown_observations':bool(result.get('uncheckedScope')) or any(x.get('unknownObservations') or x.get('judgement') in ('blocked',None) for x in checks),
        'http_has_observer_faults':bool(result.get('evaluatorFaults')) or any(x.get('observationFaults') or x.get('judgement')=='error' for x in checks),
        'provenance':{'assessment_metadata_sha256':sha(stage/'assessment.json'),'initial_result_sha256':sha(stage/'result.json'),
            'http_evaluation_json_sha256':sha(output/'evaluation.json'),'http_results_jsonl_sha256':sha(output/'results.jsonl'),
            'evaluator_manifest_sha256':sha(output/'evaluator-manifest.json'),'fixed_aggregate_sha256':expected_aggregate_sha256,
            'observed_stage_inventory_sha256':before}}
    validate_attempt(row)
    require(evidence_inventory_digest(stage)==before, 'Attempt projection changed stage bytes')
    return row


def validate_attempt(row):
    require(set(row)==ATTEMPT_KEYS and row['kind']=='unvalidated_saved_reassessment_attempt', 'Unreviewed attempt fields')
    identity(row['assessment_id']);identity(row['source_run_instance_id'])
    require(re.fullmatch(r'[A-Za-z0-9_-]+',row['source_run_id']), 'Unsafe source Run label')
    require(row['validation_id'] is None and row['validated'] is False and row['quality'] is None, 'Unvalidated attempt cannot adopt quality or a validation ID')
    require(row['source_campaign_uuid'] is None and row['source_campaign_identity_status']=='caller_asserted_unverified', 'Do not invent campaign identity')
    for name in ('source_artifact_sha256','source_condition_sha256','source_spec_sha256','new_spec_sha256','evaluator_sha256','plan_sha256'):hash_value(row[name])
    require(re.fullmatch(r'[a-f0-9]{7,40}',row['plan_commit_declared']), 'Invalid declared attempt commit')
    require(row['evaluation_version']=='1.6.0' and re.fullmatch(r'[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*',row['source_evaluation_version']), 'Unreviewed gate-fault version')
    require(row['observed_stage']=='http_only' and row['browser_started'] is False and row['pipeline_complete'] is False
        and row['pipeline_gate_fault']=='http_exit2_rejected_before_browser', 'Unreviewed or promoted pipeline attempt')
    require(type(row['evaluator_exit_code']) is int and row['evaluator_exit_code']==2 and row['browser_exit_code'] is None, 'Observed pipeline exit mismatch')
    require(row['cleanup_confirmed'] is True and row['source_bytes_unchanged'] is True, 'Attempt preservation/cleanup confirmation missing')
    for name in ('model_calls','acquisition_count_increment'):require(type(row[name]) is int and row[name]==0, 'Attempt cannot add model acquisition')
    require(row['http_raw_verdict'] in ('pass','pass_auto','fail','fail_critical','blocked','error')
        and row['http_raw_research_status'] in ('complete','incomplete'), 'Invalid HTTP diagnostic state')
    for name,total in (('http_requirement_judgement_counts',31),('http_check_judgement_counts',33)):
        counts=row[name];require(isinstance(counts,dict) and set(counts)<={'pass','fail','blocked','error','unknown'}
            and all(type(n) is int and n>=0 for n in counts.values()) and sum(counts.values())==total, 'HTTP diagnostic inventory mismatch')
    for name in ('http_has_unknown_observations','http_has_observer_faults'):require(type(row[name]) is bool, 'Expected coarse attempt boolean')
    require(set(row['provenance'])==ATTEMPT_PROVENANCE_KEYS, 'Unreviewed attempt provenance')
    for digest in row['provenance'].values():hash_value(digest)
    public_text(row)


def validate_attempt_sidecar(data,attempts):
    require(isinstance(attempts,dict) and set(attempts)=={'schema_version','kind','attempts','limits'}
        and attempts['schema_version']==SCHEMA and attempts['kind']=='unvalidated_saved_reassessment_attempts', 'Unknown attempt sidecar schema')
    require(isinstance(attempts['limits'],list) and all(isinstance(s,str) for s in attempts['limits']), 'Expected attempt limitations')
    reference=data['attempts_reference']
    require(set(reference)=={'path','sha256'} and relative(reference['path'])==ATTEMPTS_PATH
        and hash_value(reference['sha256'])==hashlib.sha256(encode(attempts)).hexdigest(), 'Attempt reference/path/digest mismatch')
    rows=attempts['attempts'];require(isinstance(rows,list) and len(rows)==4, 'Preserve exactly the four HTTP-only attempts')
    ids=[r['assessment_id'] for r in rows];require(len(ids)==len(set(ids)), 'Duplicate attempt UUID')
    followups=data['attempt_followups']
    require(isinstance(followups,dict) and set(followups)==set(ids) and len(set(followups.values()))==4,
        'Exact four distinct designated attempt followups required')
    for target in followups.values():identity(target)
    main=data['assessments'];main_ids={r['assessment_id'] for r in main}|{r['validation_id'] for r in main}
    require(not set(ids)&main_ids, 'Attempt and assessment/validation UUID collide')
    for row in rows:
        validate_attempt(row)
        matches=[r for r in main if r['assessment_id']==followups[row['assessment_id']]]
        require(len(matches)==1, 'Designated attempt followup is missing')
        match=matches[0]
        for name in ('source_run_id','source_run_instance_id','source_artifact_sha256','source_condition_sha256','source_spec_sha256','source_evaluation_version','evaluation_version','evaluator_sha256','new_spec_sha256'):
            require(match[name]==row[name], 'Attempt/followup lineage mismatch: '+name)
    public_text(attempts)


def derive(data,attempts=None):
    require({'attempts_reference','attempt_followups'}<=set(data), 'Explicit schema2 attempt reference and followups required')
    core={k:v for k,v in data.items() if k not in ('attempts_reference','attempt_followups')}
    summary=_derive_assessments_only(core)
    validate_attempt_sidecar(data,attempts)
    rows=attempts['attempts']
    summary.update(reported_assessment_count=len(data['assessments']),
        all_saved_reassessment_attempt_count=len(data['assessments'])+len(rows),
        unvalidated_http_only_attempt_count=len(rows),
        unvalidated_pipeline_gate_fault_count=len(rows),
        unvalidated_http_observer_fault_count=sum(r['http_has_observer_faults'] for r in rows),
        unvalidated_http_unknown_scope_count=sum(r['http_has_unknown_observations'] for r in rows),
        unvalidated_attempts=[{'assessment_id':r['assessment_id'],'source_run_instance_id':r['source_run_instance_id'],
            'followup_assessment_id':data['attempt_followups'][r['assessment_id']],
            'evaluation_version':r['evaluation_version'],'quality':None,'validated':False,'validation_id':None,
            'pipeline_gate_fault':r['pipeline_gate_fault'],'model_calls':0,'new_acquisition_runs':0} for r in sorted(rows,key=lambda r:r['assessment_id'])])
    return summary


def check_policy(data,policy,attempts=None):
    extra={'expected_unvalidated_attempt_ids','required_unvalidated_attempt_row_sha256','expected_attempt_followups'}
    require(extra<=set(policy), 'Exact immutable HTTP-only attempt policy required')
    core={k:v for k,v in policy.items() if k not in extra}
    _check_assessment_policy_only(data,core)
    validate_attempt_sidecar(data,attempts)
    require(policy['expected_attempt_followups']==data['attempt_followups'], 'Designated followup differs from exact policy')
    ids={r['assessment_id'] for r in attempts['attempts']};expected=policy['expected_unvalidated_attempt_ids']
    require(len(expected)==4 and len(set(expected))==4 and ids==set(expected), 'Unfilled or unexpected HTTP-only attempt slot')
    hashes=policy['required_unvalidated_attempt_row_sha256']
    require(isinstance(hashes,dict) and set(hashes)==ids, 'Pin all immutable HTTP-only attempts')
    for row in attempts['attempts']:
        require(hashlib.sha256(encode(row)).hexdigest()==hash_value(hashes[row['assessment_id']]), 'Preserved HTTP-only attempt changed')


def seal_package(destination, *, data, report, policy, attempts=None, operational_code=None):
    summary=derive(data,attempts);check_policy(data,policy,attempts)
    require(isinstance(report,bytes) and report and re.fullmatch(r'[A-Za-z0-9_-]+',policy['package_id']), 'Report and safe package ID required')
    public_text(report.decode('utf8'))
    destination=Path(destination).resolve();require(not destination.exists(), 'Package destination already exists')
    files={'INDEX.md':b'[Report](report/REPORT.md) | [Assessments](data/assessments.json) | [Unvalidated HTTP-only attempts](data/assessment-attempts.json) | [Offline reproduction](README-ja.md)\n',
        'README-ja.md':README.encode(), 'report/REPORT.md':report,'data/assessments.json':encode(data),
        ATTEMPTS_PATH:encode(attempts),'results/summary.json':encode(summary),'code/evaluator_publication.py':Path(__file__).read_bytes(),
        'NOTICE.txt':b'This package contains reviewed metadata projections and an authored standard-library derived-value reader. It excludes private oracles, evaluator binaries, databases, raw logs and third-party application source. This notice grants no blanket license for omitted materials.\n'}
    for name,content in (operational_code or {}).items():
        relative(name);require(name.startswith('code/') and name not in files and isinstance(content,bytes), 'Explicit extra code allowlist only')
        public_text(content.decode('utf8'));files[name]=content
    destination.mkdir(parents=True,exist_ok=False)
    for name,content in files.items():
        path=destination/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(content)
    manifest={'schema_version':SCHEMA,'kind':'sealed_evaluator_repair_public_package','package_id':policy['package_id'],
        'seal_policy':policy,'files':package_inventory(destination),'limits':'Derived-value recomputation; unvalidated attempts remain quality null; no private-oracle scoring replay'}
    (destination/'MANIFEST.json').write_bytes(encode(manifest));return manifest


def verify_package(root,expected_manifest_sha256):
    root=Path(root).resolve();require(sha(root/'MANIFEST.json')==hash_value(expected_manifest_sha256), 'Manifest external digest mismatch')
    manifest=read(root/'MANIFEST.json')
    require(manifest.get('schema_version')==SCHEMA and manifest.get('kind')=='sealed_evaluator_repair_public_package', 'Package not schema2 sealed')
    require(package_inventory(root)==manifest['files'], 'Package bytes or inventory mismatch')
    names=list(manifest['files']);require(len(names)==len({n.casefold() for n in names}), 'Nonportable case alias')
    require(all(n in manifest['files'] for n in ('INDEX.md','README-ja.md','data/assessments.json',ATTEMPTS_PATH,
        'results/summary.json','report/REPORT.md','code/evaluator_publication.py')), 'Reader/attempt route missing')
    data=read(root/'data/assessments.json');attempts=read(root/ATTEMPTS_PATH)
    require(sha(root/ATTEMPTS_PATH)==hash_value(data['attempts_reference']['sha256']), 'Attempt sidecar bytes changed')
    summary=derive(data,attempts);check_policy(data,manifest['seal_policy'],attempts)
    require(encode(summary)==(root/'results/summary.json').read_bytes(), 'Recomputation differs from published summary')
    return manifest,summary


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    rep=sub.add_parser('reproduce');rep.add_argument('--package',required=True,type=Path);rep.add_argument('--out',required=True,type=Path);rep.add_argument('--expected-manifest-sha256',required=True)
    args=parser.parse_args();print(json.dumps(reproduce(args.package,args.out,args.expected_manifest_sha256),ensure_ascii=False))


if __name__=='__main__':main()
