"""Bind finite technical and pending human review to exact migration asset bytes."""
import argparse
import hashlib
import json
from pathlib import Path

from . import migration_tasks as tasks


def prepare(repo, requirements_root, workflow, published_root, destination):
    repo = Path(repo).resolve()
    requirements_root = Path(requirements_root).resolve()
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(destination)
    code_paths = ['research/migration_tasks.py', 'research/verify_migration_tasks.py',
                  'research/migration_review.py', 'outer/harness/migration_input.py',
                  'research/tests/test_migration_tasks.py',
                  'research/Start-MigrationReview.ps1', 'research/Stop-MigrationReview.ps1']
    code_hashes = {path: tasks.sha256(repo / path) for path in code_paths}
    code_hashes.update({'inner/tasks/music-store-continuity/reference/' + k: v
            for k, v in tasks.hashes(repo / 'inner/tasks/music-store-continuity/reference').items()})
    scopes = {}
    for name in ('A', 'B'):
        profile_path = repo / 'outer/profiles/tasks' / ('MS1-CONT-' + name + '.json')
        profile = tasks.read_json(profile_path)
        prepared = repo / 'artifacts' / tasks.ASSET_NAMESPACE / profile['task_id']
        ledger = requirements_root / profile['evaluation']['spec_path']
        ledger_hash = tasks.sha256(ledger)
        if ledger_hash != profile['evaluation']['spec_sha256']:
            raise ValueError('Requirements hash disagrees with task profile')
        scopes[name] = {'task_id': profile['task_id'], 'profile_sha256': tasks.sha256(profile_path),
            'requirements_sha256': ledger_hash,
            'requirements_path': str(ledger), 'preparation_sha256': tasks.sha256(prepared / 'preparation.json'),
            'input_files': tasks.hashes(prepared / 'inputs'),
            'private_evaluation_files': tasks.hashes(prepared / 'evaluation'),
            'published_reference_files': tasks.hashes(Path(published_root) / ('published-' + name)),
            'source_authority': tasks.read_json(prepared / 'evaluation/migration-oracle.json')['authority']}
    technical = tasks.read_json(Path(workflow) / 'summary.json')
    for path, value in technical['executing_code_files'].items():
        if code_hashes.get(path) != value:
            raise ValueError('Executed workflow code differs from current review scope')
    if technical['reference_template_files'] != tasks.hashes(repo / 'inner/tasks/music-store-continuity/reference'):
        raise ValueError('Reference template changed after workflow execution')
    receipt = {'schema_version': 1, 'family_id': tasks.FAMILY, 'family_count': 1, 'semantic_variants': ['A', 'B'],
        'code_files': code_hashes,
        'public_request_sha256': tasks.sha256(tasks.asset_dir(repo) / 'public-request.txt'),
        'variants_definition_sha256': tasks.sha256(tasks.asset_dir(repo) / 'variants.json'),
        'candidate_register_sha256': tasks.sha256(repo / 'research/tasks/candidate-register.json'),
        'task_scopes': scopes,
        'workflow_summary_sha256': tasks.sha256(Path(workflow) / 'summary.json'),
        'workflow_evidence_files': tasks.hashes(workflow),
        'automated_review': {'status': 'passed' if technical['all_control_expectations_met'] else 'failed',
                             'case_count': technical['finite_case_count'], 'model_dispatches': 0},
        'human_review': 'not_run', 'independent_family_acceptance': 'not_met',
        'held_out_independent_membership': [],
        'limitations': ['This technical unit is a conditional one-family apparatus, not general migration quality.',
                       'Human expected-value/workflow confirmation remains mandatory and unperformed.',
                       'Old ASP.NET Framework/SQL Server app not run; executed compatibility reference substituted.']}
    destination.mkdir(parents=True)
    tasks.write_json(destination / 'technical-scope.json', receipt)
    checklist = [
        {'id': 'H-001', 'status': 'not_run', 'operation': 'Inspect original raw snapshots and source pricing rules for both variants.',
         'expected': 'A rate 1.00: 2*7.25+12.40=26.90. B rate 0.90: 9.95*.90=8.955->8.96 and 2.75*.90=2.475->2.48; 2*8.96+2.48=20.40. Round each unit before multiplying quantity.'},
        {'id': 'H-002', 'status': 'not_run', 'operation': 'In each browser click album 1 twice and album 2 once; open /ShoppingCart.',
         'expected': 'One album-1 line quantity 2, one album-2 line quantity 1; Cart (3). A total 26.90, B total 20.40.'},
        {'id': 'H-003', 'status': 'not_run', 'operation': 'Click the visible Remove from cart control twice for album 1; allow ordinary app behavior but do not force a refresh.',
         'expected': 'First quantity 1 and correct total/cart count, then no album-1 row. Browser automated review is separate from this human check.'},
        {'id': 'H-004', 'status': 'not_run', 'operation': 'Add the first album twice again. Submit valid address fields with wrong PromoCode and then missing Email; finally submit complete fields and fReE.',
         'expected': 'Invalid submits retain cart/history and show address form. Valid submit displays new OrderId >7001 and empties cart; SQLite quantities/unit prices/Total match the cart.'},
        {'id': 'H-005', 'status': 'not_run', 'operation': 'Inspect the saved SQLite and technical restart receipt.',
         'expected': 'Customer301, Order7001, Details9101/9102 and retained Cart5001 survive. A history total32.75 with units7.25/11.00; B history25.15 with units9.95/5.25. Historical units are not current-policy recalculations.'},
        {'id': 'H-006', 'status': 'not_run', 'operation': 'Judge whether this source/data preservation workflow is credible for the deliberately narrow exploratory question.',
         'expected': 'Record approval or concerns. It is one public tutorial family with synthetic operational assets, no independent held-out family and no proof that a model reads source.'}]
    human = {'schema_version': 1, 'status': 'not_run', 'reviewed_by': None, 'reviewed_at': None,
             'scope_receipt_sha256': tasks.sha256(destination / 'technical-scope.json'),
             'public_request_sha256': receipt['public_request_sha256'],
             'task_scopes': scopes, 'checklist': checklist,
             'instructions': 'A human must record each required judgment in a separate signed review receipt bound to this scope. AI/automated execution cannot set status=passed.'}
    tasks.write_json(destination / 'human-review-pending.json', human)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--requirements-root', type=Path)
    parser.add_argument('--workflow', type=Path, required=True)
    parser.add_argument('--published-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    print(prepare(args.repo, args.requirements_root or args.repo, args.workflow, args.published_root, args.out))


if __name__ == '__main__':
    main()
