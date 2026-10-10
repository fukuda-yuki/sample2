"""Read-only byte/provenance audit; never opens SQLite or invokes an evaluator.

The private receipt contains per-run identities, hashes and ledger IDs, not oracle
values or source/log text. A verified binding is not a validated quality verdict.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def load(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def inside(root: Path, relative: str) -> Path:
    # Portable names only: reject Windows drive/UNC paths on every platform.
    name = str(relative).replace('\\', '/')
    if name.startswith('/') or ':' in name or '..' in name.split('/'):
        raise ValueError('unsafe relative reference')
    path = root / name
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('reference escaped root')
    if any(p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction())
           for p in [path, *path.parents] if p.is_relative_to(root)):
        raise ValueError('linked reference')
    return path


def inventory(root: Path) -> dict:
    files = {}
    for path in root.rglob('*'):
        rel = path.relative_to(root)
        if any(p.lower() in {'bin', 'obj', '.git'} for p in rel.parts):
            continue
        inside(root, rel.as_posix())
        if path.is_file():
            files[rel.as_posix()] = {'sha256': digest(path), 'bytes': path.stat().st_size}
    return files


def tree_digest(files: dict) -> str:
    ordered = sorted(files, key=lambda name: name.replace('/', '\\').encode('utf-16-be'))
    data = ''.join(f"{name} {files[name]['sha256']}\n" for name in ordered)
    return hashlib.sha256(data.encode()).hexdigest()


def audit_run(root: Path) -> dict:
    root = root.resolve()
    issues, unknowns = [], []
    verified_files = {}

    def verify(relative, expected=None, size=None, label=None):
        label = label or relative
        try:
            p = inside(root, relative)
            actual = verified_files.get(relative)
            if actual is None:
                actual = {'sha256': digest(p), 'bytes': p.stat().st_size}
                verified_files[relative] = actual
            if expected is not None and actual['sha256'] != expected:
                issues.append({'kind': 'hash_mismatch', 'reference': label})
            if size is not None and actual['bytes'] != size:
                issues.append({'kind': 'size_mismatch', 'reference': label})
            return actual['sha256']
        except (OSError, ValueError) as ex:
            issues.append({'kind': 'missing_or_unsafe_file', 'reference': label,
                           'error_type': type(ex).__name__})
            return None

    def equality(actual, expected, label):
        if actual != expected:
            issues.append({'kind': 'binding_mismatch', 'reference': label})

    condition = load(root / 'condition.json')
    manifest = load(root / 'manifest.json')
    snapshot = load(root / 'snapshot.json')
    ev = condition['evaluation']
    verify('condition.json', manifest['condition_sha256'])
    verify('inputs-manifest.json', manifest.get('inputs_manifest_sha256'))
    for name, item in manifest.get('profile_files', {}).items():
        verify('profiles/' + name, item['sha256'], item.get('bytes'))
    verify('inputs/prompt.txt', manifest.get('prompt_sha256'))
    for name, item in manifest.get('assets_sha256', {}).items():
        verify('evaluation-assets/' + name, item['sha256'], item.get('bytes'))
    for name, item in condition.get('runtime_lock', {}).get('evaluator_files', {}).items():
        verify('evaluation-assets/evaluator/' + name, item['sha256'], item.get('bytes'),
               'runtime_lock/evaluator/' + name)
    spec_hash = verify(ev['spec_path'], ev['spec_sha256'])
    dll_hash = verify('evaluation-assets/evaluator/' + ev['assembly'], ev['evaluator_sha256'])
    equality(condition.get('runtime_lock', {}).get('evaluator_sha256'),
             ev['evaluator_sha256'], 'runtime_lock/evaluator_sha256')
    equality(condition['task_id'], manifest['task_id'], 'manifest/task_id')
    spec = load(inside(root, ev['spec_path']))
    equality(spec['taskId'], condition['task_id'], 'spec/taskId')
    equality(spec['specVersion'], ev['evaluation_version'], 'spec/specVersion')
    requirements = spec['requirements']
    req_ids = [req['id'] for req in requirements]
    mappings = [{'requirement_id': q['id'], 'check_ids': [x['id'] for x in q['checks']],
                 'category': q.get('category'), 'authority_declared': bool(q.get('authority') or q.get('basisDetail')),
                 'semantic_oracle_validation': 'not_proven_by_binding_audit'} for q in requirements]
    checks = [check for q in mappings for check in q['check_ids']]
    if len(req_ids) != len(set(req_ids)) or len(checks) != len(set(checks)) or any(not q['check_ids'] for q in mappings):
        issues.append({'kind': 'invalid_ledger_cardinality', 'reference': ev['spec_path']})
    request_hash = hashlib.sha256(condition.get('migration_request', '').encode()).hexdigest()
    for q in requirements:
        detail = q.get('basisDetail')
        if isinstance(detail, dict) and detail.get('publicRequestSha256'):
            equality(detail['publicRequestSha256'], request_hash, q['id'] + '/publicRequestSha256')

    inputs = load(root / 'inputs-manifest.json')
    for folder, item in inputs.get('inputs', {}).items():
        for name, file in item.get('files', {}).items():
            verify('inputs/' + folder + '/' + name, file['sha256'], file.get('bytes'))

    frozen_files = inventory(root / 'frozen')
    frozen_hash = tree_digest(frozen_files)
    equality(frozen_hash, snapshot.get('artifact_sha256'), 'snapshot/artifact_sha256')
    declared_frozen = {name.replace('\\', '/'): value for name, value in snapshot.get('frozen', {}).items()}
    equality(frozen_files, declared_frozen, 'snapshot/frozen_file_inventory')

    oracle_name = ev.get('migration_contract', {}).get('oracle', 'migration-oracle.json')
    oracle_path = 'evaluation-assets/' + oracle_name
    oracle_hash = verify(oracle_path)
    oracle = load(inside(root, oracle_path))
    equality(oracle.get('task_id'), condition['task_id'], 'oracle/task_id')
    equality(oracle.get('variant'), condition.get('semantic_variant'), 'oracle/variant')
    oracle_declared_hash = manifest.get('assets_sha256', {}).get(oracle_name, {}).get('sha256')
    if not oracle_declared_hash:
        issues.append({'kind': 'oracle_hash_unpinned', 'reference': oracle_path})
    initial_name = ev.get('migration_contract', {}).get('initial_database', 'initial-store.sqlite')
    initial_hash = verify('evaluation-assets/' + initial_name)
    import_name = ev.get('migration_contract', {}).get('import_input')
    if import_name:
        verify('evaluation-assets/' + import_name)

    build = ev.get('evaluator_build', {})
    if not all(build.get(x) for x in ['source_commit', 'source_path', 'command', 'sdk_version', 'sha256_origin']):
        issues.append({'kind': 'build_declaration_incomplete', 'reference': 'evaluation/evaluator_build'})
    unknowns.extend(['declared_source_commit_to_exact_compile_inputs_not_independently_rebuilt',
                     'finite_check_semantics_not_approved_by_hash_or_manifest_ID_match',
                     'SQLite_contents_and_WAL_consistency_not_opened_by_this_audit',
                     'human_review_not_performed_by_this_audit'])

    rows = []
    index_path = root / 'evaluations/index.jsonl'
    if index_path.exists():
        rows = [json.loads(x) for x in index_path.read_text(encoding='utf8').splitlines() if x.strip()]
    if len(rows) != 1:
        issues.append({'kind': 'evaluation_count_unexpected', 'reference': 'evaluations/index.jsonl', 'count': len(rows)})
    observed = []
    for row in rows:
        directory = inside(root, row['directory'])
        for key, expected in [('run_id', root.name), ('evaluation_version', ev['evaluation_version']),
                              ('spec_sha256', spec_hash), ('evaluator_sha256', dll_hash),
                              ('artifact_sha256_outer', frozen_hash)]:
            equality(row.get(key), expected, 'evaluation-index/' + key)
        verify(row['directory'] + '/evaluation.json', row.get('evaluation_sha256')) if row.get('evaluation_sha256') else None
        record = load(directory / 'record.json')
        for key in ['run_id', 'evaluation_version', 'spec_sha256', 'evaluator_sha256', 'artifact_sha256_outer']:
            equality(record.get(key), row.get(key), 'evaluation-record/' + key)
        outputs, implemented = [], []
        for stage in [directory, directory / 'http-only']:
            p = stage / 'evaluator-manifest.json'
            if not p.exists():
                continue
            j = load(p)
            for key, expected in [('evaluationVersion', ev['evaluation_version']), ('evaluatorSha256', dll_hash),
                                  ('specSha256', spec_hash), ('artifactSha256', frozen_hash)]:
                equality(j.get(key), expected, str(p.relative_to(root)) + '/' + key)
            ids = j.get('implementedCheckIds')
            if ids is not None:
                equality(sorted(ids), sorted(checks), str(p.relative_to(root)) + '/implementedCheckIds')
                implemented.append({'stage': str(stage.relative_to(directory)) or '.', 'ids': ids})
            outputs.append({'path': str(p.relative_to(root)), 'sha256': verify(str(p.relative_to(root)))})
        if not implemented:
            unknowns.append('actual_build_implemented_check_ID_manifest_missing')
        result_file = directory / 'results.jsonl'
        result_rows = [json.loads(x) for x in result_file.read_text(encoding='utf8').splitlines() if x.strip()] if result_file.exists() else []
        expected_pairs = {(q['requirement_id'], c) for q in mappings for c in q['check_ids']}
        actual_pairs = [(x.get('requirementId'), x.get('checkId')) for x in result_rows]
        if set(actual_pairs) != expected_pairs or len(actual_pairs) != len(expected_pairs):
            unknowns.append('saved_results_missing_or_duplicate_check_rows')
        statuses = Counter(x.get('judgement', 'missing') for x in result_rows)
        observed.append({'evaluation_id': row['evaluation_id'], 'scoring_state': row['scoring_state'],
                         'implementation_manifests': implemented, 'manifest_files': outputs,
                         'result_count': len(result_rows), 'judgements': dict(statuses)})
    eligible = bool(manifest.get('submission_fixed') and manifest.get('stop_confirmed')
                    and frozen_files and oracle_hash and initial_hash and spec_hash and not issues)
    return {'run_id': root.name, 'source_run_instance_id': manifest.get('run_instance_id'),
            'task_id': condition['task_id'], 'condition_id': condition.get('condition_id'),
            'evaluation_version': ev['evaluation_version'], 'evaluator_sha256': dll_hash,
            'build_source_commit_declared': build.get('source_commit'),
            'implementation_revision': build.get('implementation_revision'),
            'spec_sha256': spec_hash, 'oracle_sha256': oracle_hash, 'initial_database_sha256': initial_hash,
            'artifact_sha256_recomputed': frozen_hash, 'frozen_file_count': len(frozen_files),
            'verified_file_count': len(verified_files), 'requirement_count': len(req_ids), 'check_count': len(checks),
            'requirement_check_mappings': mappings, 'evaluations': observed,
            'asset_binding_eligible_for_separate_reassessment': eligible,
            'eligibility_limit': 'byte/input prerequisites only; build execution, schema/date/WAL semantics and saved observation completeness require separate acceptance',
            'issues': issues, 'unknowns': sorted(set(unknowns))}


def audit_cohort(root: Path, expected_runs: int = 200) -> dict:
    paths = sorted(p for p in root.iterdir() if p.is_dir() and (p / 'condition.json').is_file())
    if len(paths) != expected_runs:
        raise ValueError(f'Expected {expected_runs} run directories, found {len(paths)}')
    runs = [audit_run(p) for p in paths]
    uuids = [r['source_run_instance_id'] for r in runs]
    if None in uuids or len(set(uuids)) != len(uuids):
        raise ValueError('Missing or duplicate Run UUID')
    count = lambda key: dict(sorted(Counter(r[key] for r in runs).items()))
    return {'schema_version': 1, 'kind': 'saved_evaluation_binding_audit',
            'source_root': str(root.resolve()), 'run_count': len(runs),
            'method': 'read-only hashes and declared bindings; no SQLite connection, evaluator execution, model call or original write',
            'task_counts': count('task_id'), 'evaluation_version_counts': count('evaluation_version'),
            'evaluator_sha256_counts': count('evaluator_sha256'), 'oracle_sha256_counts': count('oracle_sha256'),
            'build_source_commit_declared_counts': count('build_source_commit_declared'),
            'scoring_states': dict(Counter(e['scoring_state'] for r in runs for e in r['evaluations'])),
            'binding_issue_run_count': sum(bool(r['issues']) for r in runs),
            'asset_binding_reassessment_candidate_count': sum(r['asset_binding_eligible_for_separate_reassessment'] for r in runs),
            'issue_counts': dict(Counter(i['kind'] for r in runs for i in r['issues'])),
            'unknown_counts': dict(Counter(i for r in runs for i in r['unknowns'])),
            'runs': runs}


def audit_saved_build(condition: dict, repository: Path) -> dict:
    """Check saved build products, retaining unknown compile-to-source provenance.

    Build origin is historical metadata, not an allowed write/execution target.
    This helper reads the pinned DLL and the optional declared second build only.
    """
    ev = condition['evaluation']
    build = ev['evaluator_build']
    origin = Path(build['sha256_origin'])
    if not origin.is_absolute():
        origin = repository / origin
    candidate = origin / ev['assembly']
    if not candidate.is_file():
        candidate = origin / 'evaluator' / ev['assembly']
    result = {'source_commit_declared': build['source_commit'], 'origin': str(origin),
              'evaluator_sha256_expected': ev['evaluator_sha256'],
              'saved_build_DLL_matches': candidate.is_file() and digest(candidate) == ev['evaluator_sha256'],
              'compile_source_to_binary': 'unknown_without_independent_rebuild',
              'second_build_files': {}}
    second = build.get('deterministic_second_build')
    if second:
        folder = Path(second['path'])
        for name, record in second['files'].items():
            p = inside(folder, name)
            result['second_build_files'][name] = p.is_file() and digest(p) == record['sha256'] and p.stat().st_size == record['bytes']
    if build.get('compile_project_sha256'):
        project = origin.parent.parent / 'source' / Path(build['source_path']).name
        result['compile_project_sha256_matches'] = project.is_file() and digest(project) == build['compile_project_sha256']
        result['saved_compile_source_files'] = {p.name: digest(p) for p in sorted(project.parent.glob('*.cs'))}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cohort', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--expected-runs', type=int, default=200)
    args = parser.parse_args()
    cohort, output = args.cohort.resolve(), args.output.resolve()
    if output.is_relative_to(cohort):
        raise ValueError('Audit output must be outside original cohort')
    if output.exists():
        raise FileExistsError('Audit receipt is append-only; choose a new output')
    receipt = audit_cohort(cohort, args.expected_runs)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(output), 'sha256': digest(output), **{k: v for k, v in receipt.items() if k not in {'runs', 'source_root'}}}, ensure_ascii=False))


if __name__ == '__main__':
    main()
