"""Explicit same-spec observation revision, separate from technical recovery.

The private revision pins one accepted build per family. The private selection
plan pins every old Run/evaluation, including old passes. No provider or old
index writer is reachable here; saved_reassessment owns execution/validation.
"""
import argparse
import json
from pathlib import Path
import re

from outer.harness import evaluate, preserve, profiles, util
from research import catalog_environment, live_pilot, repaired_runtime

REVISION = 'observation-20261011-v1'
KIND = 'same_spec_observation_revision_v1'
PLAN_KIND = 'selected_observation_reassessment_v1'


def family_for_task(task):
    return next(name for name, family in repaired_runtime.FAMILIES.items() if task in family['tasks'])


def family_binding(repo, reference, name):
    """Hash-bound acceptance receipt, current/committed sources and exact specs."""
    repo = Path(repo).resolve()
    revision = util.read_json(live_pilot.checked(reference))
    if (set(revision) != {'kind', 'revision_id', 'families'} or revision['kind'] != KIND
            or revision['revision_id'] != REVISION or set(revision['families']) != {'music', 'education'}):
        raise ValueError('Explicit supported observation revision and both family pins required')
    entry = revision['families'][name]
    if set(entry) != {'bundle', 'build_receipt', 'evaluator_sha256', 'images', 'spec_sha256_by_task'}:
        raise ValueError('Exact accepted observation build/runtime/spec pins required')
    original = repaired_runtime.FAMILIES[name]
    digest = entry['evaluator_sha256']
    if not re.fullmatch('[0-9a-f]{64}', digest) or digest == original['assembly_sha256']:
        raise ValueError('Historical DLL cannot be relabeled as the observation revision')
    family = dict(original, assembly_sha256=digest,
        runtime_id='deepseek-'+name+'-observation-v1', namespace=name+'-observation-runtime-20261011')
    bundle = live_pilot.safe_path(entry['bundle'])
    receipt_path = live_pilot.checked(entry['build_receipt'])
    receipt = util.read_json(receipt_path)
    if (receipt.get('observation_revision') != REVISION
            or receipt.get('source_worktree_clean_at_start') is not True
            or not re.fullmatch('[0-9a-f]{40}', receipt.get('source_commit', ''))):
        raise ValueError('Accepted revision requires its actual clean committed build receipt')
    files, sources = repaired_runtime._receipt_binding(repo, bundle, receipt, family)
    if (bundle/'build-receipt.json').is_file() and util.sha256_file(bundle/'build-receipt.json') != entry['build_receipt']['sha256']:
        raise ValueError('Embedded and accepted build receipts differ')
    if sources.get('global.json') != util.sha256_file(repo/'global.json'):
        raise ValueError('Observation build requires its fixed SDK source pin')
    repaired_runtime._committed_files(repo, receipt['source_commit'], sources)
    specs = {task: profiles.task_profile(repo, task, 'evaluators-20261006')['evaluation']['spec_sha256']
             for task in original['tasks']}
    if entry['spec_sha256_by_task'] != specs:
        raise ValueError('Observation revision cannot change the frozen task specs')
    for task, digest in specs.items():
        profile = profiles.task_profile(repo, task, 'evaluators-20261006')
        if util.sha256_file(repo/profile['evaluation']['spec_path']) != digest:
            raise ValueError('Frozen task spec bytes changed')
    images = entry['images']
    if (set(images) != {'worker', 'evaluator', 'gateway'}
            or any(not re.fullmatch('sha256:[0-9a-f]{64}', value) for value in images.values())):
        raise ValueError('Immutable observation runtime images required')
    return family, entry, files, sources


def selected_source(repo, plan_ref, source):
    """No verdict filter: validate membership, old bytes and optional restoration."""
    source = Path(source).resolve()
    plan = util.read_json(live_pilot.checked(plan_ref))
    if (set(plan) != {'kind', 'revision', 'browser_pin', 'selected_runs'}
            or plan['kind'] != PLAN_KIND or not isinstance(plan['selected_runs'], list) or not plan['selected_runs']):
        raise ValueError('Explicit finite selected observation plan required')
    rows = plan['selected_runs']
    required = {'source', 'run_id', 'run_instance_id', 'manifest_sha256', 'condition_sha256',
                'artifact_sha256', 'evaluation', 'evaluation_id'}
    if any(set(row) not in (required, required | {'restoration'}) for row in rows):
        raise ValueError('Exact selected original Run/evaluation bindings required')
    ids = [row['run_instance_id'] for row in rows]
    paths = [live_pilot.safe_path(row['source']) for row in rows]
    if (len(set(ids)) != len(ids) or len(set(paths)) != len(paths)
            or any(not re.fullmatch('[0-9a-f]{32}', value) for value in ids)):
        raise ValueError('Selected Run UUIDs and source paths must be unique')
    matches = [row for row, path in zip(rows, paths) if path == source]
    if len(matches) != 1:
        raise ValueError('Run is outside the selected observation plan')
    row = matches[0]
    # A restored source still passes the ordinary immutable schema-2 verifier.
    # The additional receipt proves saved-member -> restored bytes separately.
    if 'restoration' in row:
        verify_restoration(source, row)
    condition = profiles.validate_run(source)
    manifest = util.read_json(source/'manifest.json')
    snapshot = util.read_json(source/'snapshot.json')
    if (condition.get('schema_version') != 2 or manifest.get('stop_confirmed') is not True
            or manifest.get('submission_fixed') is not True
            or any(manifest.get(k) != row[k] for k in ('run_id', 'run_instance_id'))
            or util.sha256_file(source/'manifest.json') != row['manifest_sha256']
            or util.sha256_file(source/'condition.json') != row['condition_sha256']
            or snapshot.get('run_id') != row['run_id']
            or snapshot.get('artifact_sha256') != row['artifact_sha256']
            or util.artifact_hash(source/'frozen') != row['artifact_sha256']):
        raise ValueError('Selected original identity/artifact changed')
    evaluation = live_pilot.checked(row['evaluation'])
    if not evaluation.is_relative_to(source/'evaluations'):
        raise ValueError('Selected old evaluation must belong to its original Run')
    old = util.read_json(evaluation)
    if not isinstance(row['evaluation_id'], str) or not row['evaluation_id'] or old.get('evaluationId') != row['evaluation_id']:
        raise ValueError('Selected old evaluation ID changed')
    records = util.read_lines(source/'evaluations/index.jsonl')
    if not any(record.get('evaluation_sha256') == row['evaluation']['sha256']
               and (source/record.get('directory', '')/'evaluation.json').resolve() == evaluation
               for record in records):
        raise ValueError('Selected evaluation hash is not bound by the original index')
    family, entry, files, sources = family_binding(repo, plan['revision'], family_for_task(condition['task_id']))
    if (condition['evaluation']['evaluation_version'] != family['version']
            or condition['evaluation']['spec_sha256'] != entry['spec_sha256_by_task'][condition['task_id']]):
        raise ValueError('Selected Run does not use this exact frozen spec')
    if evaluate.check_mismatches(old, condition, family['version'], source/'frozen', row['artifact_sha256'],
                                 source/'evaluation-assets/requirements.json', condition['evaluation']['spec_sha256']):
        raise ValueError('Selected old evaluation identity differs from its Run')
    browser = util.read_json(live_pilot.checked(plan['browser_pin']))
    catalog_environment.validate(browser, repo)
    return plan, row, family, entry


def verify_restoration(source, selected):
    """One explicit receipt may map files from multiple preserved packages.

    Every restored byte is backed by a checked package member. The original
    manifest hash is selection-bound and is never rewritten to fit a copy.
    """
    receipt = util.read_json(live_pilot.checked(selected['restoration']))
    if (set(receipt) != {'restored_to', 'original_manifest_sha256', 'archive', 'files'}
            or live_pilot.safe_path(receipt['restored_to']) != source
            or receipt['original_manifest_sha256'] != selected['manifest_sha256']
            or util.sha256_file(source/'manifest.json') != selected['manifest_sha256']):
        raise ValueError('Restoration original-manifest binding changed')
    actual = preserve.tree(source)
    if set(actual) != set(receipt['files']):
        raise ValueError('Restored member inventory differs; hold')
    cache = {}
    for name, binding in receipt['files'].items():
        preserve.safe_name(name)
        if set(binding) != {'reference', 'member', 'original_sha256'}:
            raise ValueError('Explicit original hash and saved member required')
        package = preserve.verify(receipt['archive'], binding['reference']['package_id'],
                                  binding['reference']['sha256'], cache=cache)
        member = package['files'].get(preserve.safe_name(binding['member']))
        if (not member or member['sha256'] != binding['original_sha256']
                or actual[name]['sha256'] != member['sha256'] or actual[name]['bytes'] != member['bytes']):
            raise ValueError('Restoration byte mismatch; hold without manifest repair')


def validate_assessment(repo, stage, assessment):
    plan, row, family, entry = selected_source(repo, assessment['observation_plan'],
                                               Path(assessment['source_path_private']))
    config = util.read_json(Path(stage)/'execution-config.json')
    if (assessment.get('observation_revision') != REVISION
            or assessment.get('source_evaluation') != row['evaluation']
            or assessment.get('source_evaluation_id') != row['evaluation_id']
            or assessment['evaluation_version'] != family['version']
            or assessment['source_evaluation_version'] != family['version']
            or assessment['new_spec_sha256'] != assessment['source_spec_sha256']
            or assessment['new_spec_sha256'] != entry['spec_sha256_by_task'][config['task_id']]
            or assessment['evaluator_sha256'] != entry['evaluator_sha256']
            or config['runtime_lock']['images'] != entry['images']
            or config['evaluation']['evaluator_build'].get('observation_revision') != plan['revision']):
        raise ValueError('Prepared observation revision/build/selection differs')
    return plan


def validate_destination(repo, plan, destination):
    revision = util.read_json(live_pilot.checked(plan['revision']))
    protected = [Path(repo).resolve(), *[live_pilot.safe_path(row['source']) for row in plan['selected_runs']],
                 *[live_pilot.safe_path(entry['bundle']) for entry in revision['families'].values()]]
    if any(destination.is_relative_to(path) or path.is_relative_to(destination) for path in protected):
        raise ValueError('Observation output overlaps source, repository or accepted bundle')


def prepare_selected(repo, plan_ref, destination):
    """Prepare the entire fixed selection; never execute or choose by old score."""
    from research import saved_reassessment
    repo, destination = Path(repo).resolve(), Path(destination).resolve()
    plan = util.read_json(live_pilot.checked(plan_ref))
    if destination.exists():
        raise FileExistsError(destination)
    if not isinstance(plan.get('selected_runs'), list) or not plan['selected_runs']:
        raise ValueError('Explicit nonempty fixed selection required')
    bindings = [selected_source(repo, plan_ref, Path(row['source'])) for row in plan['selected_runs']]
    validate_destination(repo, plan, destination)
    destination.mkdir(parents=True, exist_ok=False)
    stages = []
    for _, row, family, entry in bindings:
        stage = saved_reassessment.prepare(source=row['source'], destination=destination,
            evaluator_bundle=entry['bundle'], assembly=family['assembly'],
            spec=Path(row['source'])/'evaluation-assets/requirements.json', evaluation_version=family['version'],
            repair_contract=REVISION, observation_plan=plan_ref)
        stages.append({'run_instance_id': row['run_instance_id'], 'assessment': live_pilot.reference(stage/'assessment.json')})
    result = {'plan': plan_ref, 'stages': stages, 'model_calls': 0, 'executed': False}
    util.write_new_json(destination/'selection.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan', type=Path)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--repo', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare_selected(args.repo, live_pilot.reference(args.plan), args.destination), indent=2))


if __name__ == '__main__':
    main()
