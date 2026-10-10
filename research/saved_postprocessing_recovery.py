"""Administrative same-version postprocessing of two stopped saved Music Runs.

Only a separate complete copy receives a current runtime-lock amendment. This
never dispatches a worker/model, changes the original pilot, or adopts its success.
"""
import copy
from contextlib import closing
import json
from pathlib import Path
import re
import sqlite3
import uuid

from outer.harness import aggregate, browser_cleanup, evaluate, machine, monitor, preserve, profiles, util
from research import catalog_environment, live_pilot, pair_execution, repaired_runtime
from research.saved_reassessment import byte_inventory

KIND = 'saved_music_postprocessing_recovery_v1'


def _source_binding(source, original_plan_ref):
    plan = util.read_json(live_pilot.checked(original_plan_ref))
    if plan.get('kind') != live_pilot.KIND or len(plan.get('assignments', [])) != 2:
        raise ValueError('Exact original four-Run pilot required')
    cases = plan['assignments'][0]['cases']
    if len(cases) != 2 or any(c.get('task') != 'MS1-CONT-A' or c.get('pair') != 1 for c in cases):
        raise ValueError('Only the original two Music assignments are recoverable')
    source = live_pilot.safe_path(source)
    batch = live_pilot.safe_path(plan['batch'])/'pair-1'
    matches = [c for c in cases if source == batch/c['run_id']]
    if len(matches) != 1:
        raise ValueError('Foreign original Run path')
    case = matches[0]
    binding = pair_execution.state(batch/'_control/pair-journal.jsonl')['dispatch'].get(case['run_id'])
    if not binding or any(binding.get(k) != v for k, v in case.items()):
        raise ValueError('Original dispatched assignment is not established')
    if binding.get('plan_sha256') != original_plan_ref['sha256']:
        raise ValueError('Original dispatch belongs to another plan')
    proof = live_pilot.validate_owned_terminal(source, binding, observe_resources=False)
    condition = util.read_json(source/'condition.json')
    old_lock = util.read_json(live_pilot.checked(plan['runtime_locks'][condition['runtime']['id']]))
    if condition['runtime_lock'] != old_lock:
        raise ValueError('Original condition differs from the pinned historical lock')
    if condition['evaluation']['evaluation_version'] != '1.6.0':
        raise ValueError('Same accepted Music 1.6 contract required')
    if evaluate.used_sequences(source) or evaluate.last_scoring(source) is not None:
        raise ValueError('Previously attempted scoring requires a different explicit reconciliation')
    return plan, binding, proof


def _controller(repo, lock):
    names = set(live_pilot.PIN_FILES) | {'research/saved_postprocessing_recovery.py'}
    names.update(p.relative_to(repo).as_posix() for p in (repo/'inner/browser').glob('*.cjs'))
    pins = {name: util.sha256_file(repo/name) for name in sorted(names)}
    repaired_runtime._committed_files(repo, lock['controller_source_commit'], pins)
    return pins


def _amendment(repo, original):
    current = profiles.read(repo, 'runtimes', original['runtime']['id'])
    if current != original['runtime']:
        raise ValueError('Recovery cannot change model/runtime settings')
    lock = util.read_json(profiles.runtime_root(repo, original['task_id'], current)/'lock.json')
    repaired_runtime.validate_repaired_runtime_binding(repo, lock)
    old = original['runtime_lock']
    for key in ('evaluator_sha256', 'evaluator_files', 'evaluator_build', 'evaluator_version', 'evaluator_project', 'images'):
        if lock.get(key) != old.get(key):
            raise ValueError('Recovery cannot change accepted evaluator/build/image: ' + key)
    result = copy.deepcopy(original)
    result['runtime_lock'] = lock
    return result


def prepare(*, repo, source, destination, original_plan_ref):
    """Read-only bindings first, then exclusively copy into a fresh UUID stage."""
    repo, source, destination = map(live_pilot.safe_path, (repo, source, destination))
    plan, binding, terminal = _source_binding(source, original_plan_ref)
    if (live_pilot.within(destination, plan['batch']) or live_pilot.within(plan['batch'], destination)
            or live_pilot.within(source, destination) or live_pilot.within(destination, source)):
        raise ValueError('Recovery must have a separate root')
    if any(live_pilot.within(destination, p) or live_pilot.within(p, destination)
           for p in plan.get('protected_roots', [])):
        raise ValueError('Recovery overlaps protected evidence')
    original = util.read_json(source/'condition.json')
    amended = _amendment(repo, original)
    pins = _controller(repo, amended['runtime_lock'])
    before = byte_inventory(source)
    assessment_id = uuid.uuid4().hex
    if assessment_id == binding['run_instance_id']:
        raise ValueError('Assessment identity must differ from acquisition identity')
    stage = destination/assessment_id
    stage.mkdir(parents=True, exist_ok=False)
    root = stage/'run'/binding['run_id']
    import shutil
    shutil.copytree(source, root)
    if byte_inventory(root) != before:
        raise ValueError('Complete derivative copy mismatch; retained as nonaccepted')
    shutil.copyfile(source/'condition.json', stage/'original-condition.json')
    util.write_json_atomic(root/'condition.json', amended)
    manifest = util.read_json(root/'manifest.json')
    manifest['condition_sha256'] = util.sha256_file(root/'condition.json')
    util.write_json_atomic(root/'manifest.json', manifest)
    profiles.validate_run(root)
    evaluate.validate_repaired_scoring_provenance(repo, root, amended,
        root/'evaluation-assets/evaluator'/amended['evaluation']['assembly'])
    record = dict(schema_version=1, kind=KIND, assessment_id=assessment_id,
        original_plan=original_plan_ref, source_path=str(source), run_path=str(root),
        source_run_id=binding['run_id'], source_run_instance_id=binding['run_instance_id'],
        source_terminal=terminal, source_byte_inventory=before,
        original_condition_sha256=util.sha256_file(stage/'original-condition.json'),
        amended_condition_sha256=util.sha256_file(root/'condition.json'),
        amended_manifest_sha256=util.sha256_file(root/'manifest.json'),
        allowed_condition_changes=['runtime_lock'], allowed_manifest_changes=['condition_sha256'],
        controller_source_commit=amended['runtime_lock']['controller_source_commit'], controller_files=pins,
        derivative_before_inventory=byte_inventory(root), evaluation_version='1.6.0',
        evaluator_sha256=amended['evaluation']['evaluator_sha256'],
        spec_sha256=amended['evaluation']['spec_sha256'],
        acquisition_count_increment=0, model_dispatch_count=0,
        original_pilot_adoption=False, purpose='technical postprocessing; not a new scientific acquisition')
    if byte_inventory(source) != before:
        raise ValueError('Original changed during copying; retained as nonaccepted')
    util.write_new_json(stage/'assessment.json', record)
    return live_pilot.reference(stage/'assessment.json')


def _inputs(repo, assessment_ref, original_plan_ref):
    repo = live_pilot.safe_path(repo)
    assessment_path = live_pilot.checked(assessment_ref)
    a = util.read_json(assessment_path)
    stage = assessment_path.parent
    if (a.get('kind') != KIND or a.get('schema_version') != 1 or a.get('original_plan') != original_plan_ref
            or not re.fullmatch('[a-f0-9]{32}', a.get('assessment_id', ''))
            or stage.name != a.get('assessment_id') or a.get('assessment_id') == a.get('source_run_instance_id')
            or a.get('acquisition_count_increment') != 0 or a.get('model_dispatch_count') != 0
            or a.get('original_pilot_adoption') is not False):
        raise ValueError('Technical assessment identity/amendment mismatch')
    source, root = map(live_pilot.safe_path, (a['source_path'], a['run_path']))
    if root != stage/'run'/a['source_run_id'] or live_pilot.within(root, source) or live_pilot.within(source, root):
        raise ValueError('Derivative escaped its assessment')
    plan, binding, terminal = _source_binding(source, original_plan_ref)
    if (a['source_terminal'] != terminal or a['source_run_instance_id'] != binding['run_instance_id']
            or byte_inventory(source) != a['source_byte_inventory']
            or util.sha256_file(stage/'original-condition.json') != a['original_condition_sha256']
            or util.sha256_file(source/'condition.json') != a['original_condition_sha256']):
        raise ValueError('Original acquisition lineage changed')
    original = util.read_json(stage/'original-condition.json')
    amended = _amendment(repo, original)
    if (util.read_json(root/'condition.json') != amended
            or util.sha256_file(root/'condition.json') != a['amended_condition_sha256']
            or a['allowed_condition_changes'] != ['runtime_lock']
            or a['allowed_manifest_changes'] != ['condition_sha256']):
        raise ValueError('Unauthorized derivative condition amendment')
    expected_manifest = util.read_json(source/'manifest.json')
    expected_manifest['condition_sha256'] = a['amended_condition_sha256']
    if (util.read_json(root/'manifest.json') != expected_manifest
            or util.sha256_file(root/'manifest.json') != a['amended_manifest_sha256']):
        raise ValueError('Unauthorized derivative manifest amendment')
    expected_before = dict(a['source_byte_inventory'], **{
        'condition.json': a['amended_condition_sha256'], 'manifest.json': a['amended_manifest_sha256']})
    if expected_before != a['derivative_before_inventory']:
        raise ValueError('Derivative baseline is not the full original plus declared amendments')
    profiles.validate_run(root)
    evaluate.validate_repaired_scoring_provenance(repo, root, amended,
        root/'evaluation-assets/evaluator'/amended['evaluation']['assembly'])
    if (_controller(repo, amended['runtime_lock']) != a['controller_files']
            or a['controller_source_commit'] != amended['runtime_lock']['controller_source_commit']
            or a['evaluator_sha256'] != amended['evaluation']['evaluator_sha256']
            or a['spec_sha256'] != amended['evaluation']['spec_sha256'] or a['evaluation_version'] != '1.6.0'):
        raise ValueError('Technical controller/evaluator/source contract changed')
    return a, root, source, plan


def _unchanged_copy(a, root):
    actual = byte_inventory(root)
    # These are exclusively technical pipeline outputs. No acquisition input,
    # native journal, raw usage, workspace, or frozen artifact may be changed.
    prefixes = ('evaluations/', 'evaluation-work/', 'telemetry/', 'evidence/scoring-')
    mutable = {'postprocess-timing.jsonl', 'telemetry-link.json', 'archive-reference.json'}
    baseline = a['derivative_before_inventory']
    for name, digest in baseline.items():
        if name not in mutable and not name.startswith(prefixes) and actual.get(name) != digest:
            raise ValueError('Copied acquisition evidence changed: ' + name)
    if any(name not in baseline and name not in mutable and not name.startswith(prefixes) for name in actual):
        raise ValueError('Unexpected derivative pipeline writer')
    return actual


def _pipeline(root, archive, a):
    record = evaluate.last_scoring(root)
    if (not record or record.get('scoring_state') not in ('scored', 'evaluation_incomplete')
            or record.get('evaluation_version') != '1.6.0' or record.get('evaluator_sha256') != a['evaluator_sha256']
            or record.get('mismatches') or not record.get('evaluation_id')):
        raise ValueError('Scoring fault/missing identity cannot be ready')
    directory = (root/record['directory']).resolve()
    if not directory.is_relative_to((root/'evaluations').resolve()):
        raise ValueError('Scoring directory escaped derivative')
    output = util.read_json(directory/'evaluation.json')
    artifact = util.artifact_hash(root/'frozen')
    condition = util.read_json(root/'condition.json')
    if (evaluate.check_mismatches(output, condition, '1.6.0', root/'frozen', artifact,
            root/'evaluation-assets/requirements.json', a['spec_sha256']) or output.get('evaluatorFaults')
            or util.sha256_file(directory/'evaluation.json') != record.get('evaluation_sha256')
            or evaluate._reported_evaluator_sha256(directory) != a['evaluator_sha256']
            or output.get('reviewRunInstanceId') != a['source_run_instance_id']):
        raise ValueError('Bound scoring output/fault mismatch')
    cleanup = browser_cleanup.latest(directory)
    if cleanup.get('confirmed') is not True or cleanup.get('run_instance_id') != a['source_run_instance_id']:
        raise ValueError('Browser cleanup not confirmed')
    intent = util.read_json(directory/'browser-intent.json')
    if (intent.get('run_instance_id') != a['source_run_instance_id'] or intent.get('model_called') is not False
            or intent.get('artifact_sha256') != artifact or intent.get('spec_sha256') != a['spec_sha256']
            or intent.get('evaluator_sha256') != a['evaluator_sha256']):
        raise ValueError('Browser execution intent not bound')
    if intent.get('coverage') != 'not_run_product_prerequisite':
        review = directory/'browser-cart'
        receipt = util.read_json(review/'receipt.json')
        request = util.read_json(review/'request.json')
        if (util.sha256_file(review/'receipt.json') != output.get('browserCartEvidenceSha256')
                or util.sha256_file(review/'request.json') != receipt.get('requestSha256')
                or intent.get('collector_sha256') != a['controller_files'].get('inner/browser/cart-review.cjs')
                or receipt.get('actor') != 'agent' or receipt.get('faults')
                or any(receipt.get(k) != v for k, v in dict(runInstanceId=a['source_run_instance_id'],
                    artifactSha256=artifact,specSha256=a['spec_sha256'],evaluationVersion='1.6.0').items())
                or any(request.get(k) != receipt.get(k) for k in
                    ('runInstanceId','artifactSha256','specSha256','evaluationVersion','baseUrl'))):
            raise ValueError('Actual browser receipt/request/collector mismatch')
        for removal in receipt.get('removals', []):
            for key in ('before','after','beforeScreenshot','afterScreenshot','setupBefore','setupScreenshot'):
                if key not in removal: continue
                ref = removal[key]; path = (review/ref['path']).resolve()
                if not path.is_relative_to(review.resolve()) or util.sha256_file(path) != ref['sha256']:
                    raise ValueError('Browser capture reference changed')
    row = aggregate.row_for(root.parent, root.name)
    if pair_execution._postprocess_fault(row):
        raise ValueError('Derived pipeline fault cannot be ready')
    if record['scoring_state'] == 'evaluation_incomplete' and (output.get('quality') is not None or row.get('quality') is not None):
        raise ValueError('Partial observation cannot acquire numeric quality')
    telemetry = util.read_json(root/'telemetry-link.json')
    if telemetry.get('verified') is not True or telemetry.get('usage_complete') is not True:
        raise ValueError('Actual monitor readback not verified')
    events = util.read_lines(root/'usage/events.jsonl')
    payload = monitor.payload(events, root.name, util.read_json(root/'manifest.json'))
    if (util.sha256_file(root/'telemetry/gateway.otlp.json') != telemetry.get('raw_sha256')
            or util.read_json(root/'telemetry/gateway.otlp.json') != payload):
        raise ValueError('Monitor import not bound to unchanged source events')
    with closing(sqlite3.connect((root/'telemetry/monitor.db').as_uri()+'?mode=ro', uri=True)) as database:
        database.execute('PRAGMA query_only=ON')
        found = [ident for ident, value in database.execute('SELECT id,payload_json FROM raw_records ORDER BY id')
                 if json.loads(value) == payload]
    normalized = util.read_json(root/'telemetry/normalized-readback.json')
    totals = monitor.usage_totals(events)
    expected = dict(experiment_id=root.name, turn_count=len(events),
                    **{key: value['observed'] for key, value in totals.items()})
    if (len(found) != 1 or found != telemetry.get('raw_record_ids')
            or len(normalized) != 1 or any(normalized[0].get(k) != v for k, v in expected.items())
            or telemetry.get('request_count') != len(events) or telemetry.get('usage_totals') != totals
            or any(not v.get('matched') for v in telemetry.get('readback', {}).values())
            or not telemetry.get('readback')):
        raise ValueError('Independent monitor database/normalization readback mismatch')
    reference = util.read_json(root/'archive-reference.json')
    package = preserve.verify(archive, reference['package_id'], reference['sha256'])
    metadata = package.get('metadata', {})
    if (metadata.get('missing') or metadata.get('kind') != 'run' or metadata.get('run_id') != root.name
            or metadata.get('stop_confirmed') is not True or metadata.get('submission_fixed') is not True):
        raise ValueError('Archive omitted required pipeline evidence')
    files = package['files']
    required = ['manifest.json','condition.json','snapshot.json','context.json',
        'evaluation-assets/requirements.json','evaluation-assets/evaluator/'+condition['evaluation']['assembly'],
        'telemetry-link.json',record['directory']+'/evaluation.json']
    if any(name not in files for name in required):
        raise ValueError('Archive omitted bound source/scoring files')
    for name, entry in files.items():
        path = (root/name).resolve()
        if not path.is_relative_to(root.resolve()) or util.sha256_file(path) != entry['sha256']:
            raise ValueError('Archive is not the actual derivative evidence')
    return dict(row=row, scoring=record, browser_cleanup=cleanup, browser_intent=intent,
        monitor=telemetry, archive=reference)


def execute(*, repo, assessment_ref, original_plan_ref):
    """Explicit one-shot technical continuation; never worker.start or resend."""
    a, root, source, plan = _inputs(repo, assessment_ref, original_plan_ref)
    stage = live_pilot.checked(assessment_ref).parent
    if byte_inventory(root) != a['derivative_before_inventory']:
        raise ValueError('Derivative has prior uncertain execution; no automatic repeat')
    util.write_new_json(stage/'execution-intent.json', dict(kind=KIND, assessment=assessment_ref,
        original_plan=original_plan_ref, model_dispatch_count=0))
    error = None
    pipeline = None
    try:
        browser = util.read_json(live_pilot.checked(plan['browser_pin']))
        with catalog_environment.activated(browser, repo):
            machine.postprocess(repo, root.parent, root.name, stage/'archive')
        pipeline = _pipeline(root, stage/'archive', a)
    except Exception as exc:
        error = type(exc).__name__
    try:
        after = _unchanged_copy(a, root)
    except Exception as exc:
        after = byte_inventory(root)
        invariant_error = type(exc).__name__
    else:
        invariant_error = None
    unchanged = byte_inventory(source) == a['source_byte_inventory']
    receipt = dict(schema_version=1, kind=KIND, assessment=assessment_ref, original_plan=original_plan_ref,
        assessment_id=a['assessment_id'], source_run_id=a['source_run_id'],
        source_run_instance_id=a['source_run_instance_id'], native_session_id=a['source_terminal']['native_session_id'],
        source_unchanged=unchanged,
        model_dispatch_count=0, acquisition_count_increment=0, original_pilot_adoption=False,
        derivative_after_inventory=after, pipeline=pipeline, error_type=error,
        invariant_error_type=invariant_error,
        operational_complete=unchanged and error is None and invariant_error is None and pipeline is not None)
    util.write_new_json(stage/'result.json', receipt)
    return live_pilot.reference(stage/'result.json')


def _validate_one(repo, ref, original_plan_ref):
    receipt = util.read_json(live_pilot.checked(ref))
    if (receipt.get('kind') != KIND or receipt.get('schema_version') != 1
            or receipt.get('original_plan') != original_plan_ref or receipt.get('operational_complete') is not True
            or receipt.get('error_type') is not None or receipt.get('invariant_error_type') is not None
            or receipt.get('source_unchanged') is not True
            or receipt.get('model_dispatch_count') != 0 or receipt.get('acquisition_count_increment') != 0
            or receipt.get('original_pilot_adoption') is not False):
        raise ValueError('Technical postprocessing not operationally complete')
    a, root, _, _ = _inputs(repo, receipt['assessment'], original_plan_ref)
    stage = live_pilot.checked(receipt['assessment']).parent
    if (live_pilot.checked(ref) != stage/'result.json'
            or any(receipt.get(k) != a[k] for k in ('assessment_id', 'source_run_id', 'source_run_instance_id'))
            or receipt.get('native_session_id') != a['source_terminal']['native_session_id']
            or _unchanged_copy(a, root) != receipt['derivative_after_inventory']
            or _pipeline(root, stage/'archive', a) != receipt['pipeline']):
        raise ValueError('Technical result/source/pipeline changed')
    return receipt


def collect(*, repo, receipt_refs, original_plan_ref, destination):
    """Freeze only two individually validated receipts, without executing them."""
    proof = dict(schema_version=1, kind=KIND, original_plan=original_plan_ref,
        receipts=receipt_refs, model_dispatch_count=0, acquisition_count_increment=0,
        original_pilot_adoption=False)
    rows = [_validate_one(repo, ref, original_plan_ref) for ref in receipt_refs]
    _exact_two(rows, original_plan_ref)
    destination = live_pilot.safe_path(destination)
    plan = util.read_json(live_pilot.checked(original_plan_ref))
    if any(live_pilot.within(destination, p) for p in [plan['batch'], *plan.get('protected_roots', [])]):
        raise ValueError('Technical proof cannot write protected originals')
    util.write_new_json(destination, proof)
    return live_pilot.reference(destination)


def _exact_two(rows, original_plan_ref):
    plan = util.read_json(live_pilot.checked(original_plan_ref))
    expected = {(c['run_id'], c['run_instance_id']) for c in plan['assignments'][0]['cases']}
    if len(rows) != 2 or {(r['source_run_id'], r['source_run_instance_id']) for r in rows} != expected:
        raise ValueError('Exactly the two original sent Music Runs required')
    if len({r['assessment_id'] for r in rows}) != 2:
        raise ValueError('Distinct technical assessment identities required')


def validate_saved_music_postprocessing(repo, ref, original_plan_ref):
    """Read-only final admission proof; returns verified technical receipt rows."""
    proof = util.read_json(live_pilot.checked(ref))
    if (proof.get('kind') != KIND or proof.get('schema_version') != 1
            or proof.get('original_plan') != original_plan_ref
            or proof.get('model_dispatch_count') != 0 or proof.get('acquisition_count_increment') != 0
            or proof.get('original_pilot_adoption') is not False):
        raise ValueError('Invalid saved Music technical proof')
    rows = [_validate_one(repo, r, original_plan_ref) for r in proof['receipts']]
    _exact_two(rows, original_plan_ref)
    return rows
