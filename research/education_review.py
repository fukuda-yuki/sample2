"""Bind Contoso human review to exact source/data/public/spec/code/evidence hashes."""
import argparse
from pathlib import Path

from . import education_tasks as education
from . import migration_tasks as common


def prepare(repo, requirements_root, workflow, published_root, destination):
    repo, requirements_root = Path(repo).resolve(), Path(requirements_root).resolve()
    workflow, published_root = Path(workflow).resolve(), Path(published_root).resolve()
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(destination)
    technical = common.read_json(workflow / 'summary.json')
    for relative, digest in technical['code_and_contract_files'].items():
        if common.sha256(repo / relative) != digest:
            raise ValueError('Executed code/contract changed: ' + relative)
    profiles, scopes = {}, {}
    for name in ('C', 'D'):
        profile_path = repo / 'outer/profiles/tasks' / ('CU1-ENR-' + name + '.json')
        profile = common.read_json(profile_path)
        profiles[name] = profile
        ledger = requirements_root / profile['evaluation']['spec_path']
        ledger_hash = common.sha256(ledger)
        if ledger_hash != profile['evaluation']['spec_sha256']:
            raise ValueError('Spec hash does not match profile')
        assets = education.prepare_assets(repo, name)
        scopes[name] = {'task_id': profile['task_id'], 'profile_sha256': common.sha256(profile_path),
            'public_request_sha256': common.sha256(repo / 'research/tasks/contoso-enrollment/public-request.txt'),
            'source_pin_sha256': common.sha256(repo / 'research/tasks/contoso-enrollment/source-pin.json'),
            'requirements_path': str(ledger), 'requirements_sha256': ledger_hash,
            'input_files': common.hashes(assets / 'inputs'), 'private_evaluation_files': common.hashes(assets / 'evaluation'),
            'preparation_sha256': common.sha256(assets / 'preparation.json'),
            'published_reference_files': common.hashes(published_root / ('published-' + name))}
    public = (repo / 'research/tasks/contoso-enrollment/public-request.txt').read_text(encoding='utf-8')
    if any(p['migration_request'] != public for p in profiles.values()):
        raise ValueError('Both variants must use the exact same public request')
    helpers = ['research/education_review.py', 'research/fetch_education_source.py', 'research/Start-EducationReview.ps1',
               'research/Stop-MigrationReview.ps1', 'outer/harness/migration_input.py',
               'research/tests/test_education_tasks.py']
    receipt = {'schema_version': 1, 'family_id': education.FAMILY, 'independent_family_count_this_unit': 1,
        'variants': ['C', 'D'], 'task_scopes': scopes,
        'code_and_contract_files': {**technical['code_and_contract_files'], **{p: common.sha256(repo / p) for p in helpers}},
        'candidate_register_sha256': common.sha256(repo / 'research/tasks/candidate-register.json'),
        'workflow_summary_sha256': common.sha256(workflow / 'summary.json'), 'workflow_evidence_files': common.hashes(workflow),
        'automated_reference_review': 'passed' if technical['accepted'] else 'failed',
        'normal_score_browser_calibration': 'coordinator_receipt_required', 'model_dispatches': 0, 'human_review': 'not_run',
        'membership': 'prospectively_reserved_family_for_research_model_outcomes_with_apparatus_exposure',
        'limitations': ['Old Framework app not_run; compatibility reference run.', 'Raw business installations are synthetic; source is public and known solutions exist.',
                       'C/D are nested variants of one independent education family.', 'Human basic oracle/workflow review remains not_run.']}
    destination.mkdir(parents=True)
    common.write_json(destination / 'technical-scope.json', receipt)
    checklist = [
        {'id': 'CU-H-001', 'status': 'not_run', 'operation': 'Read old Models/Enrollment.cs and raw Enrollment rows for C and D.',
         'expected': 'C enum A,B,C,D,F maps grades9001=0->A,9002=1->B,9010=3->D; D enum B,A,D,C,F maps those same ordinals to B,A,C. 9003=null is No grade.'},
        {'id': 'CU-H-002', 'status': 'not_run', 'operation': 'Open /Student/Details/101 and /Student/Details/202 in each reference; follow course links.',
         'expected': '101 Grace Hopper and 202 Alan Turing retain IDs and dates2010-09-01/2015-02-03; FullName is Hopper, Grace / Turing, Alan. Every enrollment points to its original course and shows CU-H-001 labels.'},
        {'id': 'CU-H-003', 'status': 'not_run', 'operation': 'Open /Course/Details/1045 and /Course/Details/2021, inspect raw Course/Department rows.',
         'expected': '1045 Algorithms belongs to Computing dept10, C credits4/D5; 2021 Calculus belongs to Mathematics dept20, C3/D1. Course4041 Logic credits2. Original department budgets/startdates and all identifiers retained.'},
        {'id': 'CU-H-004', 'status': 'not_run', 'operation': 'Search Hop on /Student; create Casey Researcher dated2026-01-02 with visible Create, then edit that new student to Morgan Review dated2026-02-03 with visible Save.',
         'expected': 'Search returns101 only. One new ID>202, edit keeps that ID; normal navigation displays Review, Morgan. Imported rows remain unchanged.'},
        {'id': 'CU-H-005', 'status': 'not_run', 'operation': 'Try missing name/date, whitespace name,51-character name and2026-02-30 in create and new-student edit. Inspect SQLite plus restart receipt.',
         'expected': 'Invalid submit status200 form/no mutation. target Students.FirstMidName maps raw Person.FirstName; old IDs101/202, courses1045/2021/4041,enrollments9001/9002/9003/9010 survive restart; no duplicate rows.'},
        {'id': 'CU-H-006', 'status': 'not_run', 'operation': 'Review the independent Python and ordinary score/browser calibration receipts and the fixed-C-on-D failure.',
         'expected': 'C/D reference52/52; fixedC decoder onD fails exactly grades9001/9002/9010. Ordinary scoring/browser receipts are separately required; automated results do not imply human approval.'},
        {'id': 'CU-H-007', 'status': 'not_run', 'operation': 'Judge credibility of the selected Student/Course/Enrollment subset and its reserved-family designation.',
         'expected': 'Record scope approval or concerns. A separate public education upstream/domain supplies a second family, while synthetic C/D variants and inspected apparatus limit generalization and benchmark secrecy.'}]
    common.write_json(destination / 'human-review-pending.json', {'schema_version': 1, 'status': 'not_run',
        'reviewed_by': None, 'reviewed_at': None, 'scope_receipt_sha256': common.sha256(destination / 'technical-scope.json'),
        'task_scopes': scopes, 'checklist': checklist,
        'instructions': 'A human must create a separate signed/hash-bound receipt. AI or automated execution cannot set human status=passed.'})
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--requirements-root', type=Path, required=True)
    parser.add_argument('--workflow', type=Path, required=True)
    parser.add_argument('--published-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    print(prepare(args.repo, args.requirements_root, args.workflow, args.published_root, args.out))


if __name__ == '__main__':
    main()
