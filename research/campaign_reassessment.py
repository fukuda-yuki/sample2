"""Same-version, non-acquisition reassessment of a stopped repaired main Run.

The original Run and every byte of its evidence remain immutable.  A complete
copy retains acquisition identity; only the new scoring/browser observation has
a new assessment identity.  This module neither sends nor authorizes a resend.
The caller owns campaign concurrency and must serialize the browser environment.
"""
from contextlib import contextmanager
import copy
import json
import math
from pathlib import Path
import re
import shutil
import sqlite3
import uuid

from outer.harness import browser_review, evaluate, monitor, preserve, profiles, util
from research import acquisition_readiness, catalog_environment, live_pilot, pair_execution
from research import saved_reassessment as saved

KIND = 'campaign_same_version_reassessment_v1'
VERSIONS = {'MS1-CONT-A': '1.6.0', 'MS1-CONT-B': '1.6.0',
            'CU1-ENR-C': 'education-1.1.0', 'CU1-ENR-D': 'education-1.1.0'}


@contextmanager
def _existing_lock(path):
    """Observe ownership using an existing lock without changing source bytes."""
    import os
    # LockFile accepts a read handle; preserve compatibility with immutable
    # proof guards without requesting permission to change source bytes.
    with Path(path).open('rb') as stream:
        if not stream.read(1):
            raise ValueError('Uninitialized source ownership lock')
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _finite(value):
    return type(value) in (int, float) and 0 <= value <= 100 and math.isfinite(value)


def _controllers(repo):
    return {**saved.controller_inventory(repo), **{
        name: util.sha256_file(Path(repo)/name) for name in
        ('research/campaign_reassessment.py', 'research/acquisition_readiness.py',
         'research/live_pilot.py', 'research/pair_execution.py',
         'research/catalog_environment.py', 'research/repaired_runtime.py')}}


def _source_binding(repo, source, main_plan_ref, *, observe_resources):
    path = live_pilot.checked(main_plan_ref)
    plan = acquisition_readiness.verify_main_phase(path, repo)
    if 'campaign_authority' in plan:
        from research import repaired_campaign
        repaired_campaign.validate_readiness(repo, live_pilot.checked(plan['campaign_authority']))
    else:
        acquisition_readiness.readiness_for_main(repo, plan)
    matches = [(pair, case) for pair in plan['assignments'] for case in pair['cases']
               if source == Path(plan['batch'])/('pair-'+str(pair['pair']))/case['run_id']]
    if len(matches) != 1:
        raise ValueError('Source is not one fixed child main-plan Run')
    pair, case = matches[0]
    phase = source.parent/'phase.json'
    if util.read_json(phase) != live_pilot.observer_phase(plan, main_plan_ref, pair['pair']):
        raise ValueError('Child observer phase differs from fixed main plan')
    state = pair_execution.state(source.parent/'_control/pair-journal.jsonl')
    binding = state['dispatch'].get(case['run_id'])
    if (not binding or binding.get('plan_sha256') != main_plan_ref['sha256']
            or any(binding.get(k) != v for k, v in case.items())
            or case['run_id'] not in state['implementations']):
        raise ValueError('Transmission/implementation identity unresolved; hold, never resend')
    terminal = live_pilot.validate_owned_terminal(source, binding, observe_resources=observe_resources)
    if observe_resources:
        # The ordinary HTTP scorer predates browser resource intents: a crash
        # before its index write can leave no per-Run name receipt.  Hold any
        # unresolved scorer instead of guessing its owner or starting over it.
        scorers = saved.runtime.docker('ps', '-a', '--filter', 'name=^/s2-score-',
            '--format', '{{.Names}}', timeout=30)
        if scorers.stdout.strip():
            raise ValueError('Unresolved scorer ownership; reconcile existing scorer before reassessment')
    manifest = util.read_json(source/'manifest.json')
    condition = profiles.validate_run(source)
    snapshot = util.read_json(source/'snapshot.json')
    if (manifest.get('submission_fixed') is not True
            or snapshot.get('run_id') != binding['run_id']
            or snapshot.get('artifact_sha256') != util.artifact_hash(source/'frozen')
            or condition.get('task_id') != case['task']
            or condition['evaluation']['evaluation_version'] != VERSIONS.get(case['task'])):
        raise ValueError('Stopped same-version repaired artifact binding required')
    if condition['runtime_lock'] != util.read_json(live_pilot.checked(
            plan['runtime_locks'][condition['runtime']['id']])):
        raise ValueError('Source runtime lock differs from its fixed main plan')
    evaluate.validate_repaired_scoring_provenance(repo, source, condition,
        source/'evaluation-assets/evaluator'/condition['evaluation']['assembly'])
    for ownership in source.rglob('browser-resources.json'):
        if not saved._saved_cleanup_bound(ownership.parent, binding['run_instance_id']):
            raise ValueError('Source scoring/browser ownership remains unresolved')
        if observe_resources:
            state = util.read_json(ownership)
            for kind in {r['kind'] for r in state['resources']}:
                args = ('ps', '-a') if kind == 'container' else ('network', 'ls')
                listing = saved.runtime.docker(*args, '--no-trunc', '--format', '{{json .}}', timeout=30)
                present = [json.loads(line) for line in listing.stdout.splitlines() if line.strip()]
                key = 'Names' if kind == 'container' else 'Name'
                if any(item.get(key) == resource['name'] or resource.get('id') and item.get('ID') == resource['id']
                       for item in present for resource in state['resources'] if resource['kind'] == kind):
                    raise ValueError('Source scoring/browser resource still present')
    return plan, binding, terminal


def _observation(source, condition, instance):
    """A normal finite observed failure is data, regardless of quality/verdict."""
    record = evaluate.last_scoring(source)
    if record is None:
        return {'classification': 'technical_postprocessing_missing', 'recoverable': True}
    directory = live_pilot.safe_path(source/record.get('directory', 'evaluations'))
    if not directory.is_relative_to(source/'evaluations'):
        raise ValueError('Scoring path escaped source Run')
    if not (directory/'evaluation.json').is_file():
        return {'classification': 'technical_scoring_missing', 'recoverable': True,
                'scoring_state': record.get('scoring_state')}
    output = util.read_json(directory/'evaluation.json')
    if record.get('evaluation_sha256') != util.sha256_file(directory/'evaluation.json'):
        raise ValueError('Source scoring output differs from its immutable index')
    artifact = util.artifact_hash(source/'frozen')
    config = condition['evaluation']
    identity = (not evaluate.check_mismatches(output, condition, config['evaluation_version'],
        source/'frozen', artifact, source/'evaluation-assets/requirements.json', config['spec_sha256'])
        and output.get('reviewRunInstanceId') == instance
        and evaluate._reported_evaluator_sha256(directory) == config['evaluator_sha256'])
    complete = (identity and output.get('researchStatus') == 'complete'
        and output.get('evaluatorFaults') == [] and not (directory/'browser-fault.json').exists()
        and browser_review.coverage_complete(output)
        and browser_review.stored_coverage_complete(directory, instance, artifact, config['spec_sha256'])
        and _finite(output.get('quality')))
    prerequisite = any(output.get(k) == 'not_run_product_prerequisite'
                       for k in ('browserCartCoverage', 'browserReviewCoverage'))
    if prerequisite:
        return _prerequisite_observation(directory, source, condition, instance)
    return {'classification': 'already_evaluable' if complete else 'technical_observation_incomplete',
            'recoverable': not complete, 'scoring_state': record.get('scoring_state'),
            'evaluation': live_pilot.reference(directory/'evaluation.json'),
            'quality_observed_complete': complete,
            'quality': output.get('quality') if complete else None,
            'verdict': output.get('verdict')}


def _prerequisite_observation(directory, source, condition, instance):
    """Read-only bound product failure proof, shared by original and assessment."""
    output = util.read_json(directory/'evaluation.json')
    config, artifact = condition['evaluation'], util.artifact_hash(source/'frozen')
    spec = source/'evaluation-assets/requirements.json'
    receipt = util.read_json(directory/'browser-product-prerequisite.json')
    http = directory/'http-only'
    baseline = util.read_json(http/'evaluation.json')
    requirement, check = ('R-001', 'C-001') if config['evaluation_version'] == '1.6.0' else ('EDU-R-001', 'E-001')
    expected = dict(run_instance_id=instance, artifact_sha256=artifact,
        spec_sha256=config['spec_sha256'], evaluation_version=config['evaluation_version'],
        evaluator_sha256=config['evaluator_sha256'], status='not_run_product_prerequisite',
        published_application_established=False, model_called=False, browser_observed=False,
        requirement_id=requirement, build_check=check,
        baseline_evaluation_sha256=util.sha256_file(http/'evaluation.json'),
        baseline_results_sha256=util.sha256_file(http/'results.jsonl'))
    failed = [r for r in baseline.get('requirements', []) if r.get('id') == requirement]
    checks = [c for c in util.read_lines(http/'results.jsonl') if c.get('checkId') == check]
    coverage = 'browserCartCoverage' if config['evaluation_version'] == '1.6.0' else 'browserReviewCoverage'
    if (output.get(coverage) != 'not_run_product_prerequisite'
            or output.get('reviewRunInstanceId') != instance
            or output.get('evaluatorFaults') != [] or output.get('quality') is not None
            or output.get('researchStatus') != 'incomplete' or (directory/'browser-fault.json').exists()
            or any(receipt.get(k) != v for k, v in expected.items())
            or output.get('baselineEvaluationSha256') != expected['baseline_evaluation_sha256']
            or output.get('baselineResultsSha256') != expected['baseline_results_sha256']
            or len(failed) != 1 or failed[0].get('judgement') != 'fail'
            or len(checks) != 1 or checks[0].get('requirementId') != requirement or checks[0].get('judgement') != 'fail'
            or baseline.get('evaluatorFaults') != []
            or any(evaluate.check_mismatches(raw, condition, config['evaluation_version'], source/'frozen',
                artifact, spec, config['spec_sha256']) for raw in (output, baseline))
            or any(evaluate._reported_evaluator_sha256(d) != config['evaluator_sha256'] for d in (directory, http))):
        raise ValueError('Product prerequisite failure receipt is not bound')
    return {'classification': 'normal_product_failure_partial_observation', 'recoverable': False,
        'quality': None, 'verdict': output.get('verdict'), 'valid_product_failure': True,
        'quality_observed_complete': False,
        'evaluation': live_pilot.reference(directory/'evaluation.json'),
        'prerequisite_evidence': live_pilot.reference(directory/'browser-product-prerequisite.json'),
        'scope': 'Confirmed build failure; dependent browser checks unobserved; do not replace for quality'}


def classify(*, repo, source, main_plan_ref):
    """Read-only recovery evidence. A held result never authorizes replacement."""
    source, repo = map(live_pilot.safe_path, (source, repo))
    try:
        with _existing_lock(source.parent/'_control/dispatch.lock'):
            with _existing_lock(source/'controller.lock'):
                pass  # Windows byte locks must be released before byte inventory.
            _, binding, _ = _source_binding(repo, source, main_plan_ref, observe_resources=True)
            result = _observation(source, util.read_json(source/'condition.json'), binding['run_instance_id'])
    except Exception as exc:
        result = {'classification': 'held_unresolved_evidence', 'recoverable': False,
                  'error_type': type(exc).__name__, 'reason': str(exc)}
    return {**result, 'model_calls': 0, 'resend_authorized': False,
            'acquisition_count_increment': 0, 'main_plan': main_plan_ref}


def prepare(*, repo, source, destination, main_plan_ref):
    """Create a fresh complete copy only after plan/ownership/usage verification."""
    repo, source, destination = map(live_pilot.safe_path, (repo, source, destination))
    with _existing_lock(source.parent/'_control/dispatch.lock'):
        with _existing_lock(source/'controller.lock'):
            pass
        plan, binding, terminal = _source_binding(repo, source, main_plan_ref, observe_resources=True)
        for protected in (repo, Path(plan['batch']), *map(Path, plan['protected_roots'])):
            if destination == protected or destination.is_relative_to(protected) or protected.is_relative_to(destination):
                raise ValueError('Assessment destination overlaps protected/source roots')
        condition = util.read_json(source/'condition.json')
        diagnosis = _observation(source, condition, binding['run_instance_id'])
        if not diagnosis['recoverable']:
            raise ValueError('Normal product outcome is valid data; quality does not justify reassessment')
        before = saved.byte_inventory(source)
        identity = uuid.uuid4().hex
        if identity == binding['run_instance_id']:
            raise ValueError('Assessment ID must differ from acquisition ID')
        holder = destination/identity
        root = holder/'run'/binding['run_id']
        root.parent.mkdir(parents=True, exist_ok=False)
        shutil.copytree(source, root)
        if saved.byte_inventory(root) != before or saved.byte_inventory(source) != before:
            raise ValueError('Complete source copy changed; retained but unusable')
        # STOP, old scores and runtime control files remain in the complete copy.
        # They cannot control an independently owned new observation.
        stage = holder/'observation'
        stage.mkdir()
        shutil.copytree(root/'frozen', stage/'frozen')
        shutil.copytree(root/'evaluation-assets', stage/'evaluation-assets')
        util.write_new_json(stage/'execution-config.json', copy.deepcopy(condition))
        config = condition['evaluation']
        record = dict(schema_version=1, kind=KIND, assessment_id=identity,
            main_plan=main_plan_ref, source_path_private=str(source),
            derivative_path_private=str(root),
            source_run_id=binding['run_id'], source_run_instance_id=binding['run_instance_id'],
            source_terminal=terminal, source_byte_inventory=before,
            source_artifact_sha256=util.artifact_hash(source/'frozen'),
            source_condition_sha256=util.sha256_file(source/'condition.json'),
            source_spec_sha256=config['spec_sha256'], new_spec_sha256=config['spec_sha256'],
            source_evaluation_version=config['evaluation_version'], evaluation_version=config['evaluation_version'],
            evaluator_sha256=config['evaluator_sha256'],
            build_inventory=saved.byte_inventory(stage/'evaluation-assets/evaluator'),
            assessment_assets_inventory=saved.byte_inventory(stage/'evaluation-assets'),
            execution_config_sha256=util.sha256_file(stage/'execution-config.json'),
            controller_inventory=saved.controller_inventory(repo), adapter_controller_inventory=_controllers(repo),
            diagnosis=diagnosis, model_calls=0, acquisition_count_increment=0,
            usage_basis='unchanged original acquisition; never added to campaign usage twice')
        util.write_new_json(stage/'assessment.json', record)
        if saved.byte_inventory(source) != before:
            raise ValueError('Original changed while observation inputs were copied')
        return live_pilot.reference(stage/'assessment.json')


def _inputs(repo, assessment_ref, main_plan_ref, *, observe_resources=False):
    path = live_pilot.checked(assessment_ref)
    stage, a = path.parent, util.read_json(path)
    source = live_pilot.safe_path(a['source_path_private'])
    if (a.get('kind') != KIND or a.get('schema_version') != 1 or a.get('main_plan') != main_plan_ref
            or not re.fullmatch('[a-f0-9]{32}', a.get('assessment_id', ''))
            or stage.name != 'observation' or stage.parent.name != a['assessment_id'] or source == stage
            or source.is_relative_to(stage) or stage.is_relative_to(source)
            or a['assessment_id'] == a['source_run_instance_id']
            or a.get('model_calls') != 0 or a.get('acquisition_count_increment') != 0):
        raise ValueError('Same-version assessment identity/lineage mismatch')
    plan, binding, _ = _source_binding(repo, source, main_plan_ref, observe_resources=observe_resources)
    if (a['source_run_id'] != binding['run_id'] or a['source_run_instance_id'] != binding['run_instance_id']
            or saved.byte_inventory(source) != a['source_byte_inventory']
            or _controllers(repo) != a['adapter_controller_inventory']):
        raise ValueError('Original evidence or bound controllers changed')
    root = live_pilot.safe_path(a['derivative_path_private'])
    if root != stage.parent/'run'/a['source_run_id']:
        raise ValueError('Complete acquisition copy escaped assessment')
    condition = profiles.validate_run(root)
    config = condition['evaluation']
    if (condition != util.read_json(source/'condition.json') or condition != util.read_json(stage/'execution-config.json')
            or util.sha256_file(root/'condition.json') != a['source_condition_sha256']
            or util.sha256_file(stage/'execution-config.json') != a['execution_config_sha256']
            or config['evaluation_version'] != a['evaluation_version']
            or a['evaluation_version'] != a['source_evaluation_version']
            or a['evaluation_version'] != VERSIONS.get(condition['task_id'])
            or config['spec_sha256'] != a['new_spec_sha256'] or a['new_spec_sha256'] != a['source_spec_sha256']
            or config['evaluator_sha256'] != a['evaluator_sha256']
            or saved.byte_inventory(stage/'evaluation-assets') != a['assessment_assets_inventory']
            or saved.byte_inventory(stage/'evaluation-assets/evaluator') != a['build_inventory']
            or util.artifact_hash(stage/'frozen') != a['source_artifact_sha256']):
        raise ValueError('Copied same-version inputs changed')
    if saved.byte_inventory(root) != a['source_byte_inventory']:
        raise ValueError('Complete acquisition copy changed')
    monitor_root = stage.parent/'monitor'/a['source_run_id']
    if monitor_root.exists() and (util.sha256_file(monitor_root/'manifest.json') != a['source_byte_inventory']['manifest.json']
            or saved.byte_inventory(monitor_root/'usage') != saved.byte_inventory(source/'usage')):
        raise ValueError('Monitor source is not the unchanged acquisition')
    return a, stage, source, plan


def _validation(stage, a):
    """saved.revalidate adoption semantics, with the explicit SAME-version gate.

    saved.revalidate itself rejects equal source/target versions.  Do not alter
    that historical API or manufacture an unequal source version to invoke it.
    """
    condition = util.read_json(stage/'execution-config.json')
    original = util.read_json(stage/'result.json')
    result = dict(adopted=False, valid_product_failure=False, quality=None,
                  quality_observed_complete=False, validation_status='invalid_evidence', errors=[])
    def require(ok, name):
        if not ok:
            raise ValueError(name)
    try:
        require(original.get('assessment_id') == a['assessment_id']
            and original.get('cleanup_confirmed') is True and original.get('source_unchanged') is True
            and type(original.get('evaluator_exit_code')) is int and original['evaluator_exit_code'] in (0, 2)
            and original.get('timed_out') is False and original.get('errors') == []
            and original.get('operation_status') in ('evaluation_finished', 'evaluation_partial_or_fault'),
            'execution_confirmations')
        out, http = stage/'output', stage/'output/http-only'
        require(original.get('raw_result') == 'output/evaluation.json', 'output_path')
        output, baseline = util.read_json(out/'evaluation.json'), util.read_json(http/'evaluation.json')
        prerequisite = any(output.get(k) == 'not_run_product_prerequisite'
                           for k in ('browserCartCoverage', 'browserReviewCoverage'))
        spec = stage/'evaluation-assets/requirements.json'
        require(browser_review.http_phase_eligible(condition, http,
            exit_code=original['evaluator_exit_code'], timed_out=False, cleanup_confirmed=True,
            stopped=(stage/'STOP').exists(), frozen=stage/'frozen', artifact_hash=a['source_artifact_sha256'],
            spec=spec, spec_hash=a['new_spec_sha256'], evaluator_hash=a['evaluator_sha256']), 'http_eligibility')
        for directory, raw in ((out, output), (http, baseline)):
            require(not evaluate.check_mismatches(raw, condition, a['evaluation_version'], stage/'frozen',
                a['source_artifact_sha256'], spec, a['new_spec_sha256']), 'output_identity')
            require(evaluate._reported_evaluator_sha256(directory) == a['evaluator_sha256'], 'reported_dll')
            if directory == out and prerequisite:
                cleanup = saved.browser_cleanup.latest(out)
                intent = util.read_json(out/'browser-intent.json')
                require(cleanup.get('confirmed') is True and cleanup.get('status') == 'no_resources_created'
                    and not (out/'browser-resources.json').exists() and 'launch_command' not in intent
                    and all(intent.get(k) == v for k, v in dict(run_instance_id=a['assessment_id'],
                        artifact_sha256=a['source_artifact_sha256'], spec_sha256=a['new_spec_sha256'],
                        baseline_evaluation_sha256=util.sha256_file(http/'evaluation.json'),
                        baseline_results_sha256=util.sha256_file(http/'results.jsonl'),
                        coverage='not_run_product_prerequisite', model_called=False, actor='agent').items()),
                    'product_prerequisite_no_browser_resources')
            else:
                require(saved._saved_cleanup_bound(directory, a['assessment_id']), 'owned_cleanup_receipts')
        require(output.get('reviewRunInstanceId') == a['assessment_id'], 'assessment_identity')
        require(output.get('baselineEvaluationSha256') == util.sha256_file(http/'evaluation.json')
            and output.get('baselineResultsSha256') == util.sha256_file(http/'results.jsonl'), 'baseline_links')
        require(original.get('raw_verdict') == output.get('verdict')
            and original.get('evaluator_sha256_reported') == a['evaluator_sha256'], 'original_report_binding')
        faults = output.get('evaluatorFaults')
        require(isinstance(faults, list), 'observer_fault_inventory')
        fault = bool(faults) or (out/'browser-fault.json').is_file()
        result.update(observer_fault=fault, observer_faults=faults, raw_verdict=output.get('verdict'),
            output_sha256=util.sha256_file(out/'evaluation.json'),
            finite_failure=browser_review.stored_failure(out, a['assessment_id'], a['source_artifact_sha256'],
                a['new_spec_sha256'], util.sha256_file(out/'evaluation.json'), baseline_directory=http))
        if prerequisite:
            require(not fault and original['operation_status'] == 'evaluation_finished'
                    and original.get('browser_exit_code') == 0, 'product_prerequisite_execution')
            product = _prerequisite_observation(out, stage, condition, a['assessment_id'])
            result.update(product, validation_status='normal_product_failure_partial_observation')
            return result
        complete = (browser_review.coverage_complete(output)
            and browser_review.stored_coverage_complete(out, a['assessment_id'], a['source_artifact_sha256'],
                a['new_spec_sha256']) and output.get('researchStatus') == 'complete' and not fault
            and original['operation_status'] == 'evaluation_finished' and original.get('browser_exit_code') == 0)
        result['adopted'] = complete and _finite(output.get('quality'))
        result['quality_observed_complete'] = result['adopted']
        result['quality'] = output['quality'] if result['adopted'] else None
        result['validation_status'] = ('complete_observation' if result['adopted'] else
            'observer_fault' if fault else 'partial_observation')
    except (OSError, ValueError, KeyError, TypeError, OverflowError) as exc:
        result['errors'].append({'type': type(exc).__name__, 'check': str(exc)})
    return result


def _monitor_validation(stage):
    link = util.read_json(stage/'telemetry-link.json')
    events = util.read_lines(stage/'usage/events.jsonl')
    payload = monitor.payload(events, stage.name, util.read_json(stage/'manifest.json'))
    totals = monitor.usage_totals(events)
    if (link.get('verified') is not True or link.get('usage_complete') is not True
            or util.read_json(stage/'telemetry/gateway.otlp.json') != payload
            or util.sha256_file(stage/'telemetry/gateway.otlp.json') != link.get('raw_sha256')
            or link.get('request_count') != len(events) or link.get('usage_totals') != totals):
        raise ValueError('Monitor export/usage differs from original acquisition')
    db = sqlite3.connect((stage/'telemetry/monitor.db').as_uri()+'?mode=ro', uri=True)
    try:
        db.execute('PRAGMA query_only=ON')
        found = [ident for ident, value in db.execute('SELECT id,payload_json FROM raw_records ORDER BY id')
                 if json.loads(value) == payload]
    finally:
        db.close()
    rows = util.read_json(stage/'telemetry/normalized-readback.json')
    expected = dict(experiment_id=stage.name, turn_count=len(events),
                    **{key: value['observed'] for key, value in totals.items()})
    if (len(found) != 1 or found != link.get('raw_record_ids') or len(rows) != 1
            or any(rows[0].get(k) != v for k, v in expected.items())):
        raise ValueError('Monitor independent readback differs')
    return link


def execute(*, repo, assessment_ref, main_plan_ref, timeout=1800):
    """One finite scoring/browser/monitor/archive attempt. Never a model send."""
    if type(timeout) is not int or not 1 <= timeout <= 1800:
        raise ValueError('Finite scoring timeout of 1..1800 seconds required')
    repo = live_pilot.safe_path(repo)
    source = live_pilot.safe_path(util.read_json(live_pilot.checked(assessment_ref))['source_path_private'])
    with _existing_lock(source.parent/'_control/dispatch.lock'):
        with _existing_lock(source/'controller.lock'):
            pass
        a, stage, source, plan = _inputs(repo, assessment_ref, main_plan_ref, observe_resources=True)
        holder, root = stage.parent, Path(a['derivative_path_private'])
        monitor_root = holder/'monitor'/a['source_run_id']
        util.write_new_json(holder/'execution-intent.json', dict(assessment=assessment_ref, main_plan=main_plan_ref,
            model_calls=0, acquisition_count_increment=0, timeout_seconds=timeout))
        error = None
        validation, telemetry = None, None
        try:
            browser = util.read_json(live_pilot.checked(plan['browser_pin']))
            with catalog_environment.activated(browser, repo):
                saved.execute(stage, repo=repo, timeout=timeout)
            validation = _validation(stage, a)
            # The importer is append-only. Retain any original partial database
            # in the full Run copy and build this assessment's monitor afresh.
            monitor_root.mkdir(parents=True, exist_ok=False)
            shutil.copy2(root/'manifest.json', monitor_root/'manifest.json')
            shutil.copytree(root/'usage', monitor_root/'usage')
            monitor.link(repo, monitor_root)
            telemetry = _monitor_validation(monitor_root)
        except (Exception, KeyboardInterrupt) as exc:
            error = type(exc).__name__
        invariant_error = None
        try:
            _inputs(repo, assessment_ref, main_plan_ref)
        except Exception as exc:
            invariant_error = type(exc).__name__
        unchanged = saved.byte_inventory(source) == a['source_byte_inventory']
        # Pack even incomplete attempts. This local package includes the complete
        # derivative evidence; public redaction/publication is a separate caller.
        archive_ref, archive_error = None, None
        try:
            sources = {'run': root, 'observation': stage}
            if monitor_root.exists():
                sources['monitor'] = monitor_root
            archive_ref = preserve.pack(holder/'archive', 'assessment-'+a['assessment_id'], sources,
                metadata=dict(kind=KIND, assessment_id=a['assessment_id'], source_run_id=a['source_run_id'],
                    source_run_instance_id=a['source_run_instance_id'], model_calls=0, acquisition_count_increment=0))
            package = preserve.verify(holder/'archive', archive_ref['package_id'], archive_ref['sha256'])
            if {name: entry['sha256'] for name, entry in package['files'].items()} != _derived_inventory(stage, root):
                raise ValueError('Archived assessment differs from current evidence')
        except Exception as exc:
            archive_error = type(exc).__name__
        confirmed = (validation is not None and telemetry is not None and unchanged
                     and error is None and invariant_error is None and archive_error is None)
        adopted = bool(confirmed and validation['adopted'])
        valid_failure = bool(confirmed and validation['valid_product_failure'])
        result = dict(schema_version=1, kind=KIND, assessment=assessment_ref, main_plan=main_plan_ref,
            assessment_id=a['assessment_id'], source_run_id=a['source_run_id'],
            source_run_instance_id=a['source_run_instance_id'], source_unchanged=unchanged,
            model_calls=0, acquisition_count_increment=0, adopted=adopted,
            valid_product_failure=valid_failure, quality_observed_complete=adopted,
            classification=('already_evaluable' if adopted else 'normal_product_failure_partial_observation'
                            if valid_failure else 'technical_observation_incomplete'),
            prerequisite_evidence=validation['prerequisite_evidence'] if valid_failure else None,
            quality=validation['quality'] if adopted else None, validation=validation,
            monitor=telemetry, archive=archive_ref, error_type=error,
            invariant_error_type=invariant_error, archive_error_type=archive_error,
            derivative_after_inventory=_derived_inventory(stage, root), resend_authorized=False)
        util.write_new_json(holder/'result.json', result)
        return live_pilot.reference(holder/'result.json')


def revalidate(*, repo, result_ref, main_plan_ref):
    """Read-only campaign admission; archive, source and all derived bytes bound."""
    path = live_pilot.checked(result_ref)
    result = util.read_json(path)
    a, stage, _, _ = _inputs(live_pilot.safe_path(repo), result['assessment'], main_plan_ref)
    root = Path(a['derivative_path_private'])
    if (path != stage.parent/'result.json' or result.get('kind') != KIND
            or result.get('main_plan') != main_plan_ref
            or any(result.get(k) != a[k] for k in ('assessment_id', 'source_run_id', 'source_run_instance_id'))
            or result.get('model_calls') != 0 or result.get('acquisition_count_increment') != 0
            or result.get('resend_authorized') is not False
            or _derived_inventory(stage, root) != result.get('derivative_after_inventory')):
        raise ValueError('Assessment receipt/derivative changed')
    ref = result['archive']
    package = preserve.verify(stage.parent/'archive', ref['package_id'], ref['sha256'])
    if {n: v['sha256'] for n, v in package['files'].items()} != _derived_inventory(stage, root):
        raise ValueError('Assessment archive differs from derived bytes')
    if result.get('adopted') is True or result.get('valid_product_failure') is True:
        if (result.get('source_unchanged') is not True or result.get('error_type') is not None
                or result.get('invariant_error_type') is not None or result.get('archive_error_type') is not None
                or _validation(stage, a) != result['validation']
                or result.get('adopted') is not result['validation']['adopted']
                or result.get('valid_product_failure') is not result['validation']['valid_product_failure']
                or result.get('quality_observed_complete') is not result['adopted']
                or result.get('classification') != ('already_evaluable' if result['adopted']
                    else 'normal_product_failure_partial_observation')
                or result.get('prerequisite_evidence') != result['validation'].get('prerequisite_evidence')
                or _monitor_validation(stage.parent/'monitor'/a['source_run_id']) != result['monitor']
                or result.get('quality') != result['validation']['quality']):
            raise ValueError('Claimed adoption is not reproducible')
    return result


def _derived_inventory(stage, root):
    monitor_root = stage.parent/'monitor'/root.name
    return {**{'run/'+n: h for n, h in saved.byte_inventory(root).items()},
            **{'observation/'+n: h for n, h in saved.byte_inventory(stage).items()},
            **({'monitor/'+n: h for n, h in saved.byte_inventory(monitor_root).items()}
               if monitor_root.exists() else {})}
