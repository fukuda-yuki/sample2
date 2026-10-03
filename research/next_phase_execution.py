"""Exact-bundle start gate and one-pair-at-a-time continuity acquisition."""
from pathlib import Path
import json

from outer.harness import util
from research import next_phase


def provider_metadata(root, expected_model):
    """Read saved response originals; alias metadata is not provider internals."""
    models = set()
    for path in (Path(root) / 'usage/raw').glob('*.response.sse'):
        for line in path.read_bytes().splitlines():
            if not line.startswith(b'data:'): continue
            payload = line[5:].strip()
            if payload == b'[DONE]': continue
            try: value = json.loads(payload)
            except (ValueError, UnicodeError): continue
            if isinstance(value, dict) and isinstance(value.get('model'), str):
                models.add(value['model'])
    return {'provider_reported_models': sorted(models), 'expected_request_model': expected_model,
        'reported_metadata_state': 'reported' if models else 'not_reported',
        'unexpected_reported_model': bool(models - {expected_model}),
        'limitation': 'Reported alias metadata does not prove an unchanged internal model or provider distribution.'}


def guarded_implementation(repo, batch, run_id):
    from outer.harness import machine
    root = Path(batch) / run_id
    receipt = machine.implement(repo, batch, run_id)
    condition = util.read_json(root / 'condition.json')
    metadata = provider_metadata(root, condition['runtime']['model_id'])
    util.write_new_json(root / 'provider-metadata-receipt.json', metadata)
    if metadata['unexpected_reported_model']:
        return {**receipt, 'error_type': 'unexpected_provider_reported_model'}
    return receipt


def execution_plan(bundle, bundle_path):
    return {'plan_sha256': util.sha256_file(bundle_path), 'cohort': bundle['cohort'],
        'runtime': bundle['runtime_id']}


def browser_postprocess(bundle):
    """The checked pin must reach the ordinary collector, not just preflight."""
    from outer.harness import machine
    from research import catalog_environment
    def postprocess(repo, batch, run_id, archive):
        if not bundle.get('browser'):
            raise ValueError('Pinned browser environment is required for scoring')
        with catalog_environment.activated(bundle['browser']['record'], repo):
            return machine.postprocess(repo, batch, run_id, archive)
    return postprocess


def execute(repo, bundle_path, approval_path):
    # No credential lookup, directory creation, or worker startup before all
    # acceptance, environment and exact scientific-start gates pass.
    checked = next_phase.check(repo, bundle_path)
    if not checked['scientific_and_technical_ready']:
        return checked
    if not approval_path:
        raise ValueError('Separate exact-bundle user research-start approval required')
    next_phase.approved(approval_path, bundle_path)
    bundle = util.read_json(bundle_path)
    batch = next_phase.inside(repo, bundle['cohort'], 'runs')
    from research import pair_execution
    current = pair_execution.state(batch / '_control/pair-journal.jsonl')
    plan = execution_plan(bundle, bundle_path)
    for binding in current['dispatch'].values():
        if binding['plan_sha256'] != plan['plan_sha256'] or binding['cohort'] != plan['cohort']:
            raise ValueError('Existing acquisition belongs to a different bundle')
    for pair in bundle['assignments']:
        number = pair['pair']
        if number in current['gates']:
            continue
        if any(c['run_id'] in current['dispatch'] for c in pair['cases']):
            return {'status': 'held', 'reason': 'explicit_recovery_or_publication_required',
                'pair': number, 'model_dispatched': False}
        # One invocation only starts one pair. No second pair can bypass review,
        # independent transfer/restore/extraction and owned-copy cleanup.
        batch.mkdir(parents=True, exist_ok=True)
        launch = batch / '_control/launch-receipt.json'
        record = {'bundle_sha256': plan['plan_sha256'], 'source_commit': bundle['source_commit'],
            'approval': next_phase.reference(approval_path), 'cohort': plan['cohort'],
            'started_at': next_phase.now(), 'pair_concurrency': 1}
        if launch.exists():
            saved = util.read_json(launch)
            if saved['bundle_sha256'] != record['bundle_sha256']:
                raise ValueError('Launch receipt differs from approved bundle')
        else:
            util.write_new_json(launch, record)
        return pair_execution.execute_pair(plan, pair['cases'], batch, repo=repo, concurrency=1,
            implement=guarded_implementation, postprocess=browser_postprocess(bundle))
    return {'status': 'complete', 'assigned_slots': bundle['plan']['allocation']['runs'],
        'model_dispatched': False, 'all_pair_gates_complete': True}


def recover(repo, bundle_path):
    bundle = util.read_json(bundle_path)
    next_phase.validate_plan(bundle['plan'])
    batch = next_phase.inside(repo, bundle['cohort'], 'runs')
    from research import pair_execution
    return pair_execution.recover_pair(execution_plan(bundle, bundle_path), batch, repo=repo,
        postprocess=browser_postprocess(bundle))


def resume(repo, bundle_path, approval_path):
    checked = next_phase.check(repo, bundle_path)
    if not checked['scientific_and_technical_ready']: return checked
    if not approval_path: raise ValueError('Exact-bundle user start approval required')
    approval = next_phase.approved(approval_path, bundle_path)
    bundle = util.read_json(bundle_path)
    batch = next_phase.inside(repo, bundle['cohort'], 'runs')
    from research import pair_execution
    from outer.harness import profiles
    journal = batch / '_control/pair-journal.jsonl'
    current = pair_execution.state(journal)
    unsent = {rid: binding['run_instance_id'] for rid, binding in current['reserved'].items() if rid not in current['dispatch']}
    if not unsent: return {'status': 'held', 'reason': 'no_reserved_unsent_slot', 'model_dispatched': False}
    authorization = {'authorized': True, 'approved_by': 'user',
        'authorization_reference': approval['authorization_reference'],
        'plan_sha256': util.sha256_file(bundle_path), 'journal_sha256': util.sha256_file(journal),
        'run_instances': unsent, 'explicit_operator_mode': 'resume_unsent_only'}
    def verify(plan, binding):
        receipt = next_phase.check(repo, bundle_path)
        if not receipt['scientific_and_technical_ready']: raise ValueError('Frozen preflight failed before resume')
        root = batch / binding['run_id']
        profiles.validate_run(root)
        manifest = util.read_json(root / 'manifest.json')
        if manifest['condition_sha256'] != binding['condition_sha256'] or manifest['prompt_sha256'] != binding['input_sha256']:
            raise ValueError('Reserved unsent input changed')
    return pair_execution.resume_pair(execution_plan(bundle, bundle_path), batch, authorization,
        repo=repo, verify=verify, implement=guarded_implementation,
        postprocess=browser_postprocess(bundle))
