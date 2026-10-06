"""Run a repaired evaluator on a saved artifact in an independent assessment.

This is not acquisition: it never calls a provider and never writes a Run index.
Only the explicit new specification is accepted; old contracts are not relabeled.
The existing no-network evaluator container and isolated browser path are reused.
"""
import argparse
import json
import re
from pathlib import Path
import shutil
import uuid

from outer.harness import browser_cleanup, browser_review, evaluate, profiles, runtime, util
from outer.harness.security import child_environment


def byte_inventory(root):
    """Include bin/obj, DB sidecars and previous output, not just artifact hash."""
    root = Path(root).resolve()
    result = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink() or path.is_junction():
            raise ValueError('Saved evidence must not contain links')
        if path.is_file():
            result[path.relative_to(root).as_posix()] = util.sha256_file(path)
    return result


def _inside(path, root):
    return path == root or path.is_relative_to(root)


def requirement_inventory(spec):
    """Descriptions may be clarified; identity, severity and checks may not drift."""
    return [(r['id'], r.get('severity'), r.get('weight'), [c['id'] for c in r['checks']])
            for r in spec['requirements']]


def controller_inventory(repo):
    repo = Path(repo).resolve()
    paths = list((repo/'outer/harness').glob('*.py')) + list((repo/'inner/browser').glob('*.cjs'))
    paths += [repo/'research/saved_reassessment.py', repo/'research/repair_spec.py']
    if not paths or any(not p.is_file() for p in paths):
        raise ValueError('Assessment requires its actual controller source tree')
    return {p.relative_to(repo).as_posix(): util.sha256_file(p) for p in sorted(paths)}


def prepare(*, source, destination, evaluator_bundle, assembly, spec,
            evaluation_version, repair_contract):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    bundle, spec = Path(evaluator_bundle).resolve(), Path(spec).resolve()
    if _inside(destination, source) or _inside(source, destination):
        raise ValueError('Assessment and original Run must have separate roots')
    if Path(assembly).name != assembly or not assembly.endswith('.dll'):
        raise ValueError('Expected one evaluator DLL filename')
    manifest = util.read_json(source/'manifest.json')
    condition = util.read_json(source/'condition.json')
    if condition.get('schema_version') != 2:
        raise ValueError('Only frozen isolated schema-2 Runs are supported')
    profiles.validate_run(source)
    snapshot = util.read_json(source/'snapshot.json')
    original_spec = util.read_json(source/'evaluation-assets/requirements.json')
    new_spec = util.read_json(spec)
    if manifest.get('stop_confirmed') is not True or manifest.get('submission_fixed') is not True:
        raise ValueError('Source acquisition must be stopped and fixed')
    if not re.fullmatch(r'[0-9a-f]{32}', manifest.get('run_instance_id', '')) or not repair_contract:
        raise ValueError('Source UUID and explicit repair contract are required')
    if (evaluation_version == condition['evaluation']['evaluation_version']
            or new_spec.get('specVersion') != evaluation_version):
        raise ValueError('An explicit new matching evaluation/spec version is required')
    if (new_spec.get('taskId') != original_spec.get('taskId')
            or requirement_inventory(new_spec) != requirement_inventory(original_spec)
            or new_spec.get('migrationContract') != original_spec.get('migrationContract')):
        raise ValueError('This repair adapter does not change requirement/check inventories')
    artifact = util.artifact_hash(source/'frozen')
    if manifest.get('condition_sha256') != util.sha256_file(source/'condition.json'):
        raise ValueError('Source manifest does not bind its actual condition')
    if snapshot.get('run_id') != manifest['run_id']:
        raise ValueError('Snapshot belongs to another source Run')
    if artifact != snapshot.get('artifact_sha256'):
        raise ValueError('Original frozen artifact does not match its snapshot')
    if util.sha256_file(source/'evaluation-assets/requirements.json') != condition['evaluation']['spec_sha256']:
        raise ValueError('Original specification does not match its condition')
    before = byte_inventory(source)
    build_inventory = byte_inventory(bundle)
    if assembly not in build_inventory:
        raise ValueError('Repaired evaluator bundle is missing its DLL')
    assessment_id = uuid.uuid4().hex
    stage = destination/assessment_id
    stage.mkdir(parents=True, exist_ok=False)
    # Source remains untouched. A fresh work DB is initialized from copied assets.
    shutil.copytree(source/'frozen', stage/'frozen')
    shutil.copytree(source/'evaluation-assets', stage/'evaluation-assets',
        ignore=lambda directory, names: ['evaluator']
        if Path(directory).resolve() == source/'evaluation-assets' else [])
    shutil.copytree(bundle, stage/'evaluation-assets/evaluator')
    shutil.copyfile(spec, stage/'evaluation-assets/requirements.json')
    copied_assets = byte_inventory(stage/'evaluation-assets')
    for name, digest in before.items():
        if name.startswith('evaluation-assets/'):
            relative = name[len('evaluation-assets/'):]
            if relative != 'requirements.json' and not relative.startswith('evaluator/'):
                if copied_assets.get(relative) != digest:
                    raise RuntimeError('Independent source asset copy mismatch')
    new_condition = json.loads(json.dumps(condition))
    new_condition['evaluation'].update(assembly=assembly, evaluation_version=evaluation_version,
        spec_sha256=util.sha256_file(spec), evaluator_sha256=build_inventory[assembly],
        evaluator_build={'kind': 'repaired_bundle', 'inventory': build_inventory,
            'build_receipt_sha256': build_inventory.get('build-receipt.json'),
            'source': 'assessment-bound repaired bundle; original build remains in source condition'})
    new_condition['runtime_lock'].update(evaluator_sha256=build_inventory[assembly],
        evaluator_build=new_condition['evaluation']['evaluator_build'],
        evaluator_files={name: {'sha256': sha, 'bytes': (bundle/name).stat().st_size}
                         for name, sha in build_inventory.items()})
    controllers = controller_inventory(Path(__file__).resolve().parents[1])
    new_condition['runtime_lock']['controller_files'] = controllers
    # This is assessment execution configuration, never a new acquisition condition.
    util.write_new_json(stage/'execution-config.json', new_condition)
    record = {'schema_version': 1, 'kind': 'saved_artifact_reassessment',
        'assessment_id': assessment_id, 'source_path_private': str(source),
        'source_run_id': manifest['run_id'], 'source_run_instance_id': manifest['run_instance_id'],
        'acquisition_count_increment': 0, 'source_artifact_sha256': artifact,
        'source_condition_sha256': util.sha256_file(source/'condition.json'),
        'source_spec_sha256': condition['evaluation']['spec_sha256'],
        'source_evaluation_version': condition['evaluation']['evaluation_version'],
        'evaluation_version': evaluation_version, 'repair_contract': repair_contract,
        'evaluator_sha256': build_inventory[assembly], 'build_inventory': build_inventory,
        'new_spec_sha256': util.sha256_file(spec), 'source_byte_inventory': before,
        'execution_config_sha256': util.sha256_file(stage/'execution-config.json'),
        'assessment_assets_inventory': byte_inventory(stage/'evaluation-assets'),
        'controller_inventory': controllers,
        'scope': 'fresh evaluation of saved artifact; not historical action reconstruction'}
    util.write_new_json(stage/'assessment.json', record)
    if byte_inventory(source) != before or util.artifact_hash(stage/'frozen') != artifact:
        raise RuntimeError('Source changed while assessment inputs were copied; do not execute')
    return stage


def execute(stage, *, repo, timeout=1800):
    stage, repo = Path(stage).resolve(), Path(repo).resolve()
    if not 1 <= timeout <= 1800:
        raise ValueError('Assessment timeout must be finite and at most 1800 seconds')
    assessment = util.read_json(stage/'assessment.json')
    source = Path(assessment['source_path_private']).resolve()
    if _inside(stage, source) or _inside(source, stage):
        raise ValueError('Assessment execution must remain outside the original Run')
    if controller_inventory(repo) != assessment['controller_inventory']:
        raise ValueError('Assessment controller differs from its prepared source bytes')
    if byte_inventory(source) != assessment['source_byte_inventory']:
        raise ValueError('Original changed since preparation')
    if (util.artifact_hash(stage/'frozen') != assessment['source_artifact_sha256']
            or util.sha256_file(stage/'evaluation-assets/requirements.json') != assessment['new_spec_sha256']
            or byte_inventory(stage/'evaluation-assets/evaluator') != assessment['build_inventory']
            or byte_inventory(stage/'evaluation-assets') != assessment['assessment_assets_inventory']
            or util.sha256_file(stage/'execution-config.json') != assessment['execution_config_sha256']):
        raise ValueError('Assessment input/build changed since preparation')
    output = stage/'output'
    output.mkdir(exist_ok=False)  # Partial/interrupted attempts cannot be overwritten.
    record = {'schema_version': 1, 'assessment_id': assessment['assessment_id'],
              'operation_status': 'not_completed', 'adopted': False, 'quality': None,
              'source_unchanged': None, 'cleanup_confirmed': False, 'errors': []}
    if (stage/'STOP').exists():
        record.update(operation_status='stopped_before_execution', source_unchanged=True)
        util.write_new_json(stage/'result.json', record)
        return record
    condition = util.read_json(stage/'execution-config.json')
    http = output/'http-only'; http.mkdir()
    work = stage/'work'; work.mkdir()
    name = None
    try:
        name, command = runtime.scoring_command(condition, stage/'frozen', http, work,
            stage/'evaluation-assets', assessment['evaluation_version'], 1)
        if command[:2] != ['docker', 'run'] or not re.fullmatch(r's2-score-[0-9a-f]{32}', name):
            name = None
            raise ValueError('Expected the isolated, independently owned evaluator command')
        owner = browser_cleanup.register(http, assessment['assessment_id'], 'container', name)
        command[2:2] = ['--label', 'sample2.browser-review='+owner,
                        '--label', 'sample2.assessment='+assessment['assessment_id']]
        with (output/'stdout.log').open('xb') as stdout, (output/'stderr.log').open('xb') as stderr:
            code, timed_out = evaluate.run_evaluator(command, repo, child_environment(), stdout, stderr, timeout)
        record.update(evaluator_exit_code=code, timed_out=timed_out)
        # Cleanup precedes further product execution, as in the existing score route.
        record['cleanup_confirmed'] = browser_cleanup.cleanup(http, locked=True)['confirmed']
        name = None if record['cleanup_confirmed'] else name
        if not record['cleanup_confirmed']:
            raise RuntimeError('Evaluator container cleanup unconfirmed')
        if (stage/'STOP').exists():
            record['operation_status'] = 'stopped_after_http'
            code = 2
        if code == 0 and not timed_out and (http/'evaluation.json').is_file():
            if browser_review.required(assessment['evaluation_version']):
                code = browser_review.complete_evaluation(repo, condition, stage/'frozen', http,
                    work/'publish', stage/'evaluation-assets', output, assessment['assessment_id'], 1)
                record['browser_exit_code'] = code
        if record['operation_status'] != 'stopped_after_http':
            record['operation_status'] = 'evaluation_finished' if code == 0 else 'evaluation_partial_or_fault'
    except (Exception, KeyboardInterrupt) as exc:
        record['errors'].append(type(exc).__name__ + ': ' + str(exc))
        record['operation_status'] = 'interrupted' if isinstance(exc, KeyboardInterrupt) else 'evaluation_fault'
    finally:
        if name:
            try:
                record['cleanup_confirmed'] = browser_cleanup.cleanup(http, locked=True)['confirmed']
            except Exception as exc:
                record['errors'].append('cleanup: ' + type(exc).__name__)
            if not record['cleanup_confirmed']:
                record['operation_status'] = 'cleanup_unconfirmed'
        try:
            record['source_unchanged'] = byte_inventory(source) == assessment['source_byte_inventory']
            for candidate in (output/'evaluation.json', http/'evaluation.json'):
                if candidate.is_file():
                    record['raw_result'] = candidate.relative_to(stage).as_posix()
                    result = util.read_json(candidate)
                    record['raw_verdict'] = result.get('verdict')
                    mismatches = evaluate.check_mismatches(result, condition, assessment['evaluation_version'],
                        stage/'frozen', assessment['source_artifact_sha256'],
                        stage/'evaluation-assets/requirements.json', assessment['new_spec_sha256'])
                    record['mismatches'] = mismatches
                    reported_build = evaluate._reported_evaluator_sha256(candidate.parent)
                    record['evaluator_sha256_reported'] = reported_build
                    if reported_build != assessment['evaluator_sha256']:
                        mismatches.append({'check': 'actual_evaluator_build',
                            'expected': assessment['evaluator_sha256'], 'actual': reported_build})
                    cleanup_receipt = browser_cleanup.latest(output)
                    full_browser = (browser_review.coverage_complete(result)
                        and result.get('reviewRunInstanceId') == assessment['assessment_id']
                        and browser_review.stored_coverage_complete(output, assessment['assessment_id'],
                            assessment['source_artifact_sha256'], assessment['new_spec_sha256'])
                        and cleanup_receipt.get('confirmed') is True
                        and cleanup_receipt.get('run_instance_id') == assessment['assessment_id'])
                    record['full_bound_browser_observation'] = full_browser
                    record['adopted'] = (not mismatches and record['source_unchanged']
                        and record['cleanup_confirmed'] and record['operation_status'] == 'evaluation_finished'
                        and candidate == output/'evaluation.json' and result.get('researchStatus') == 'complete'
                        and full_browser and result.get('quality') is not None)
                    record['quality'] = result.get('quality') if record['adopted'] else None
                    break
        except Exception as exc:
            record.update(operation_status='postprocessing_fault', adopted=False, quality=None)
            record['errors'].append('postprocessing: ' + type(exc).__name__)
        if record['source_unchanged'] is False:
            record.update(operation_status='source_invariance_failed', adopted=False, quality=None)
        elif record['source_unchanged'] is None:
            record.update(operation_status='source_invariance_unverified', adopted=False, quality=None)
        util.write_new_json(stage/'result.json', record)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    prep = sub.add_parser('prepare')
    for name in ('source', 'destination', 'evaluator-bundle', 'assembly', 'spec', 'evaluation-version', 'repair-contract'):
        prep.add_argument('--'+name, required=True)
    run = sub.add_parser('execute'); run.add_argument('stage'); run.add_argument('--repo', required=True)
    run.add_argument('--timeout', type=int, default=1800)
    args = vars(parser.parse_args()); action = args.pop('action')
    if action == 'prepare': print(prepare(**args))
    else: print(json.dumps(execute(**args), ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
