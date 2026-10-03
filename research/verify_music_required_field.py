"""Only the reviewed Music missing-Email defect and one same-branch regression.

Run against disposable owned preview copies. This does not execute the previous
full workflow, a model, restart/import checks, or any original Framework app.
"""
import argparse
import difflib
import json
from pathlib import Path

from . import migration_tasks as tasks
from .verify_migration_tasks import Session, fields


def verify(repo, preview, prior_verification, prior_program, destination):
    repo, preview = Path(repo).resolve(), Path(preview).resolve()
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(destination)
    prior = tasks.read_json(prior_verification)
    if prior['status'] != 'passed' or tasks.sha256(prior['owner_review_receipt_path']) != prior['owner_review_receipt_sha256']:
        raise ValueError('Owner review evidence verification is missing or changed')
    before = Path(prior_program)
    if tasks.sha256(before) != prior['code_before_sha256']:
        raise ValueError('Preserved before code does not match verified review')
    current = repo / 'inner/tasks/music-store-continuity/reference/MusicStore.Continuity/Program.cs'
    owners = tasks.read_json(preview / 'owners.json')
    if isinstance(owners, dict):
        owners = [owners]
    if set(owner['variant'] for owner in owners) != {'A', 'B'}:
        raise ValueError('Verify only the two owned Music previews')
    destination.mkdir(parents=True)
    cases = []
    for owner in owners:
        name = owner['variant']
        case = destination / name
        case.mkdir()
        assembly, database = Path(owner['assembly']), Path(owner['database'])
        if tasks.sha256(assembly) != owner['assembly_sha256']:
            raise ValueError('Owned preview binary changed')
        session = Session(owner['url'])
        added = session.request('/ShoppingCart/AddToCart/1')
        if added['status'] != 302:
            raise ValueError('Minimal cart setup failed')
        before_cart = session.request('/ShoppingCart')
        baseline = tasks.snapshot_tables(database)
        checks = {}
        observations = {}
        for missing in ('Email', 'FirstName'):
            submitted = fields(**{missing: ''})
            response = session.request('/Checkout/AddressAndPayment', submitted)
            expected = 'The ' + missing + ' field is required.'
            unexpected = 'The ' + ('FirstName' if missing == 'Email' else 'Email') + ' field is required.'
            cart = session.request('/ShoppingCart')
            observed = tasks.snapshot_tables(database)
            checks[missing + '_accurate_message'] = response['status'] == 200 and expected in response['body'] and unexpected not in response['body']
            checks[missing + '_submitted_values_retained'] = 'value="Ada"' in response['body'] if missing == 'Email' else 'ada@example.invalid' in response['body']
            checks[missing + '_cart_unchanged'] = cart['status'] == 200 and cart['body'] == before_cart['body']
            checks[missing + '_database_unchanged'] = observed == baseline
            (case / (missing + '-response.html')).write_text(response['body'], encoding='utf-8')
            observations[missing] = {'status': response['status'], 'expected_message': expected,
                'submitted_fields': submitted, 'observed_message_matches': checks[missing + '_accurate_message']}
        tasks.write_json(case / 'http.json', session.transcript)
        tasks.write_json(case / 'database-before.json', baseline)
        tasks.write_json(case / 'database-after.json', tasks.snapshot_tables(database))
        asset = repo / 'artifacts/migration-assets-v2' / ('MS1-CONT-' + name)
        cases.append({'variant': name, 'passed': all(checks.values()), 'checks': checks, 'observations': observations,
            'owner': owner, 'new_assembly_sha256': tasks.sha256(assembly),
            'reviewed_old_assembly_sha256': prior['bound_preview_assembly_checks'][name]['actual_sha256'],
            'unchanged_profile_sha256': tasks.sha256(repo / 'outer/profiles/tasks' / ('MS1-CONT-' + name + '.json')),
            'unchanged_assets': {p: tasks.sha256(asset / p) for p in ('preparation.json',
                'evaluation/initial-store.sqlite', 'evaluation/migration-oracle.json', 'evaluation/catalog.json')}})
    delta = ''.join(difflib.unified_diff(before.read_text(encoding='utf-8').splitlines(keepends=True),
        current.read_text(encoding='utf-8').splitlines(keepends=True), fromfile='Program.before.cs', tofile='Program.after.cs'))
    (destination / 'Program.delta.diff').write_text(delta, encoding='utf-8')
    receipt = {'schema_version': 1, 'status': 'passed' if all(c['passed'] for c in cases) else 'failed',
        'problem_id': 'REF-MUSIC-EMAIL-LABEL', 'owner_review_verification_sha256': tasks.sha256(prior_verification),
        'owner_review_receipt_sha256': prior['owner_review_receipt_sha256'],
        'program_before_sha256': tasks.sha256(before), 'program_after_sha256': tasks.sha256(current),
        'targeted_verifier_sha256': tasks.sha256(__file__), 'cases': cases, 'public_request_sha256': tasks.sha256(tasks.asset_dir(repo) / 'public-request.txt'),
        'full_prior_workflow_repeated': False, 'original_framework_run': False,
        'restart_import_verified_in_this_delta': False, 'full_integrated_score_verified_in_this_delta': False,
        'all_invalid_cases_verified_in_this_delta': False, 'research_model_dispatches': 0, 'human_review': 'not_run',
        'claim_limit': 'Current preview binaries were verified only for missing Email and missing FirstName messages/retained form values/cart/database. Prior broader receipts remain bound to their pre-fix code/binaries.',
        'evidence_files': tasks.hashes(destination)}
    tasks.write_json(destination / 'targeted-receipt.json', receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--preview-directory', type=Path, required=True)
    parser.add_argument('--prior-verification', type=Path, required=True)
    parser.add_argument('--prior-program', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.repo, args.preview_directory, args.prior_verification, args.prior_program, args.out)
    print(json.dumps({'status': result['status'], 'variants': [{'variant': c['variant'], 'passed': c['passed'], 'checks': c['checks']} for c in result['cases']]}))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
