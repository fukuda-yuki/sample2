"""One bounded, post-start r2 date-comparison amendment; no generic migration.

Proposal validation is read-only. Adoption requires a later explicit approval,
adds a receipt/journal event, and does not recover the pause or dispatch a Run.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from research.catalog_allocation_review import read, sha256, write_new
from research.catalog_identity import RULE, object_hash, compare_initial

OLD_SHA = '14622f31c510607c8999026fe2fa308630ce6bb528bcfeb6667b3d46c349ea9b'
OLD_PATH = 'research/protocols/ms1-catalog-comparison-v2-execution-20260922-r2.json'
NEW_PATH = 'research/protocols/ms1-catalog-comparison-v2-execution-20260923-r3.json'
RECORD_PATH = 'research/protocols/ms1-catalog-date-revision-20260923.json'
ID = 'MS1-CATALOG-DATE-REVISION-20260923'
STATUS = 'post_start_date_identity_revision_proposed_not_adopted'
ADOPTION = 'date-revision-adoption.json'
CHANGED_CODE = ('research/catalog_execution.py', 'research/catalog_pilot.py',
                'research/catalog_observations.py', 'research/catalog_confirmatory.py',
                'research/catalog_share.py')
ADDED_CODE = ('research/catalog_identity.py', 'research/catalog_date_revision.py')
SCOPE = 'Normalize only the validated automatic date in the leading OpenCode 1.17.11 system environment, on comparison copies; preserve generation and all scientific settings.'


def utc(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.utcoffset() != timezone.utc.utcoffset(result):
        raise ValueError('Revision timestamps must be actual UTC records')
    return result


def journal_events(path):
    raw = Path(path).read_bytes()
    if not raw.endswith(b'\n'):
        raise ValueError('Incomplete revision journal')
    return raw, [json.loads(line) for line in raw.decode('utf-8').splitlines()]


def checkpoint_projection(events, plan):
    """Portable event projection; its digest is NOT the original journal hash.

    The only projected value is the terminal seal's machine-local path. Public
    copies already redact that home prefix. The original prefix hash is still
    required locally, including before adoption; public readers verify this
    separately named projection and the approved raw-hash reference.
    """
    if len(events) != 5 or [e.get('kind') for e in events] != ['begin', 'admission', 'dispatch', 'result', 'pause']:
        raise ValueError('Revision is limited to the recorded first-slot pause')
    result = deepcopy(events)
    if (result[0].get('plan_sha256') != OLD_SHA or result[2].get('plan_sha256') != OLD_SHA or
            result[0].get('assigned') != 640 or
            any(result[i].get('case') != plan['slots'][0] for i in (1, 2, 3)) or
            result[4].get('reason') != 'run_fault' or
            result[4].get('stops') != ['initial_request_differs_from_probe'] or
            result[3].get('stops') != ['initial_request_differs_from_probe']):
        raise ValueError('Revision checkpoint differs from the date-only slot-1 stop')
    expected = plan['runs_dir'] + '/_control/' + plan['slots'][0]['run_id'] + '.seal.json'
    path = result[3]['seal_path'].replace('\\', '/')
    if path != expected and not path.endswith('/' + expected):
        raise ValueError('Unexpected checkpoint seal path')
    result[3]['seal_path'] = expected
    return result


def amendment_record(plan, new_sha, old):
    revision = plan['date_revision']
    return {'schema_version': 1, 'kind': 'post_start_date_identity_amendment_proposal',
            'id': ID, 'old_plan': {'path': OLD_PATH, 'sha256': OLD_SHA},
            'new_plan': {'path': NEW_PATH, 'sha256': new_sha},
            'old_code_hashes': old['execution']['code_hashes'],
            'new_code_hashes': plan['execution']['code_hashes'],
            'changed_code_files': list(CHANGED_CODE), 'added_code_files': list(ADDED_CODE),
            'revision': revision, 'after_first_result_seen': True,
            'counts_at_proposal': {'dispatched': 1, 'terminal': 1, 'undispatched': 639, 'uncertain': 0},
            'acquired_under_r2': [old['slots'][0]], 'resume_at': old['slots'][1],
            'uniform_application': 'The same revised comparison applies to the retained r2 Run and every later allocated Run.',
            'unchanged': ['N=320 pairs/640 slots', 'seed and complete allocation',
                          'model/agent/task and request generation', 'available files and retrieval',
                          'timeouts/concurrency', 'evaluation and missingness',
                          'estimands/interval methods and all other scientific settings'],
            'resumption_authorized': False,
            'authorization_boundary': 'Implementation/offline audit authorized; adoption and resumption require a later user approval bound to both new plan and amendment hashes.'}


def propose(repo):
    """Save a new proposal only; never adopt it, append to the journal or recover."""
    from research.catalog_share import inventory
    repo = Path(repo)
    old_path, target, record_path = repo / OLD_PATH, repo / NEW_PATH, repo / RECORD_PATH
    if target.exists() or record_path.exists():
        raise ValueError('Use the existing immutable proposal; never overwrite it')
    if sha256(old_path) != OLD_SHA:
        raise ValueError('Original r2 plan changed')
    old = read(old_path)
    control = repo / old['runs_dir'] / '_control'
    raw, events = journal_events(control / 'journal.jsonl')
    projection = checkpoint_projection(events, old)
    root = repo / old['runs_dir'] / old['slots'][0]['run_id']
    seal_path = control / (root.name + '.seal.json')
    if (sha256(seal_path) != events[3]['seal_sha256'] or
            inventory(root) != read(seal_path)['files']):
        raise ValueError('Original Run/seal changed before proposal')
    plan = deepcopy(old)
    plan['status'] = STATUS
    names = set(old['execution']['code_hashes']) | set(ADDED_CODE)
    plan['execution']['code_hashes'] = {n: sha256(repo / n) for n in sorted(names)}
    if {n for n, digest in old['execution']['code_hashes'].items()
            if plan['execution']['code_hashes'][n] != digest} != set(CHANGED_CODE):
        raise ValueError('Unexpected code changes; do not widen the proposal')
    for name in CHANGED_CODE:
        if name in plan['pinned_files']:
            plan['pinned_files'][name] = plan['execution']['code_hashes'][name]
    plan['date_revision'] = {'id': ID, 'rule': RULE, 'old_plan_path': OLD_PATH,
        'old_plan_sha256': OLD_SHA, 'record_path': RECORD_PATH,
        'proposed_at_utc': datetime.now(timezone.utc).isoformat(), 'scope': SCOPE,
        'checkpoint': {'journal_sha256': hashlib.sha256(raw).hexdigest(), 'journal_bytes': len(raw),
            'journal_projection_sha256': object_hash(projection),
            'launch_receipt_sha256': sha256(control / 'launch-receipt.json'),
            'old_approval_sha256': sha256(control / 'start-approval.json'),
            'run_seal_sha256': sha256(seal_path), 'result_at_utc': events[3]['at']}}
    validate_originals(plan, old, repo)
    baseline = repo / old['probe'] / 'MS1-001-catalog-expanded-001'
    comparison = compare_initial(root, baseline, plan)
    if comparison['raw_common_equal'] or not comparison['matches']:
        raise ValueError('Expected the saved date-only mismatch, not another revision')
    write_new(target, plan)
    write_new(record_path, amendment_record(plan, sha256(target), old))
    validate_proposal(target, repo)
    return {'status': 'proposal_only_not_adopted', 'plan': NEW_PATH, 'plan_sha256': sha256(target),
            'amendment': RECORD_PATH, 'amendment_sha256': sha256(record_path),
            'journal_unchanged': sha256(control / 'journal.jsonl') == hashlib.sha256(raw).hexdigest(),
            'dispatches': 0, 'recoveries': 0}


def validate_proposal(plan_path, repo):
    repo = Path(repo)
    plan_path = Path(plan_path)
    plan = read(plan_path)
    revision = plan.get('date_revision', {})
    expected_keys = {'id', 'rule', 'old_plan_path', 'old_plan_sha256', 'record_path',
                     'proposed_at_utc', 'scope', 'checkpoint'}
    if (set(revision) != expected_keys or revision.get('id') != ID or revision.get('rule') != RULE or
            revision.get('old_plan_path') != OLD_PATH or revision.get('old_plan_sha256') != OLD_SHA or
            revision.get('record_path') != RECORD_PATH or revision.get('scope') != SCOPE):
        raise ValueError('Unsupported date revision scope or history')
    old_path = repo / OLD_PATH
    if sha256(old_path) != OLD_SHA:
        raise ValueError('Original r2 plan changed')
    old = read(old_path)
    expected = deepcopy(old)
    expected['status'] = STATUS
    expected['date_revision'] = revision
    expected['execution']['code_hashes'] = plan['execution']['code_hashes']
    for name in CHANGED_CODE:
        if name in expected['pinned_files']:
            expected['pinned_files'][name] = plan['execution']['code_hashes'][name]
    if plan != expected:
        raise ValueError('Date revision changes unrelated plan/scientific settings')
    old_code, new_code = old['execution']['code_hashes'], plan['execution']['code_hashes']
    if (set(new_code) != set(old_code) | set(ADDED_CODE) or
            {n for n in old_code if new_code[n] != old_code[n]} != set(CHANGED_CODE)):
        raise ValueError('Date revision changes unapproved code-file scope')
    for name, digest in new_code.items():
        if sha256(repo / name) != digest:
            raise ValueError('Revised code hash mismatch: ' + name)
    checkpoint = revision['checkpoint']
    if set(checkpoint) != {'journal_sha256', 'journal_bytes', 'journal_projection_sha256',
                           'launch_receipt_sha256', 'old_approval_sha256', 'run_seal_sha256', 'result_at_utc'}:
        raise ValueError('Incomplete revision checkpoint')
    if utc(revision['proposed_at_utc']) <= utc(checkpoint['result_at_utc']):
        raise ValueError('Amendment must be recorded after the first result')
    record_path = repo / RECORD_PATH
    if read(record_path) != amendment_record(plan, sha256(plan_path), old):
        raise ValueError('Amendment record changed or does not bind the exact plans/code')
    return plan, old, record_path


def validate_approval(approval, plan_path, record_path, proposed_at):
    if (approval.get('authorized') is not True or approval.get('approved_by') != 'user' or
            approval.get('plan_sha256') != sha256(plan_path) or
            approval.get('amendment_sha256') != sha256(record_path) or
            not approval.get('authorization_reference') or
            utc(approval.get('approved_at_utc', '')) < utc(proposed_at)):
        raise ValueError('Separate user approval must bind this post-start plan and amendment')


def validate_originals(plan, old, repo, *, public=False):
    repo = Path(repo)
    control = repo / plan['runs_dir'] / '_control'
    checkpoint = plan['date_revision']['checkpoint']
    if (sha256(control / 'frozen-plan.json') != OLD_SHA or
            sha256(control / 'launch-receipt.json') != checkpoint['launch_receipt_sha256'] or
            sha256(control / 'start-approval.json') != checkpoint['old_approval_sha256']):
        raise ValueError('Original plan/launch receipt/approval changed or missing')
    original_approval = read(control / 'start-approval.json')
    receipt = read(control / 'launch-receipt.json')
    required = old['launch']['required_code_files']
    if (original_approval.get('authorized') is not True or original_approval.get('approved_by') != 'user' or
            original_approval.get('plan_sha256') != OLD_SHA or not original_approval.get('authorization_reference') or
            receipt.get('approval_sha256') != checkpoint['old_approval_sha256'] or
            receipt.get('analysis_plan_sha256') != OLD_SHA or receipt.get('pre_dispatch_verified') is not True or
            receipt.get('frozen_analysis_code_hashes') != {n: old['execution']['code_hashes'][n] for n in required} or
            receipt.get('dispatch_journal_path') != plan['runs_dir'] + '/_control/journal.jsonl'):
        raise ValueError('Original launch lineage is inconsistent')
    for key in ('resource_capacity_confirmation', 'identity_and_browser_pin_checks'):
        if receipt.get(key, {}).get('verified') is not True or not receipt[key].get('evidence_reference'):
            raise ValueError('Original launch checks are missing')
    path = repo / 'acquisition-journal.jsonl' if public else control / 'journal.jsonl'
    raw, events = journal_events(path)
    if (not public and hashlib.sha256(raw[:checkpoint['journal_bytes']]).hexdigest() != checkpoint['journal_sha256']):
        raise ValueError('Original journal byte prefix changed')
    projection = checkpoint_projection(events[:5], old)
    if (object_hash(projection) != checkpoint['journal_projection_sha256'] or
            projection[3]['seal_sha256'] != checkpoint['run_seal_sha256'] or
            projection[3]['at'] != checkpoint['result_at_utc'] or
            not utc(original_approval['approved_at_utc']) <= utc(receipt['checked_at_utc']) <= utc(events[2]['at'])):
        raise ValueError('Original checkpoint projection or chronology changed')
    if not public:
        seal_path = control / (old['slots'][0]['run_id'] + '.seal.json')
        if sha256(seal_path) != checkpoint['run_seal_sha256']:
            raise ValueError('Original Run seal changed')
    return control, raw, events, receipt


def validate_history(plan_path, repo, *, approval=None, public=False):
    plan, old, record_path = validate_proposal(plan_path, repo)
    control, raw, events, receipt = validate_originals(plan, old, repo, public=public)
    adoption_path = control / ADOPTION
    adoption = read(adoption_path)
    saved = adoption.get('approval', {})
    validate_approval(saved, plan_path, record_path, plan['date_revision']['proposed_at_utc'])
    if approval is not None and saved != approval:
        raise ValueError('Current approval differs from the adopted amendment')
    expected = {'kind': 'post_start_date_revision_adoption', 'id': ID,
                'old_plan_sha256': OLD_SHA, 'plan_sha256': sha256(plan_path),
                'amendment_sha256': sha256(record_path), 'approval': saved,
                'approval_object_sha256': object_hash(saved),
                'prior_journal_sha256': plan['date_revision']['checkpoint']['journal_sha256'],
                'adopted_at_utc': adoption.get('adopted_at_utc')}
    if adoption != expected or utc(adoption['adopted_at_utc']) < utc(saved['approved_at_utc']):
        raise ValueError('Changed or backdated amendment adoption')
    expected_event = {'kind': 'date_revision', 'id': ID, 'plan_sha256': sha256(plan_path),
                      'amendment_sha256': sha256(record_path), 'adoption_sha256': sha256(adoption_path)}
    amendments = [(i, e) for i, e in enumerate(events) if e['kind'] == 'date_revision']
    if (len(amendments) != 1 or amendments[0][0] != 5 or
            {k: v for k, v in amendments[0][1].items() if k != 'at'} != expected_event or
            utc(amendments[0][1]['at']) < utc(adoption['adopted_at_utc'])):
        raise ValueError('Missing, duplicate or altered amendment journal history')
    for e in events[6:]:
        if e['kind'] not in {'admission', 'dispatch', 'result', 'pause', 'recovery', 'pair_staged', 'pair_shared'}:
            raise ValueError('Unknown post-amendment journal history')
        if e['kind'] == 'dispatch' and e.get('plan_sha256') != sha256(plan_path):
            raise ValueError('Dispatch after amendment uses a different plan')
    return {'id': ID, 'rule': RULE, 'old_plan_sha256': OLD_SHA,
            'plan_sha256': sha256(plan_path), 'amendment_sha256': sha256(record_path),
            'adoption_sha256': sha256(adoption_path),
            'original_launch_receipt_sha256': plan['date_revision']['checkpoint']['launch_receipt_sha256'],
            'original_journal_sha256': plan['date_revision']['checkpoint']['journal_sha256'],
            'journal_projection_sha256': plan['date_revision']['checkpoint']['journal_projection_sha256'],
            'acquired_under_r2': [old['slots'][0]['run_id']]}


def adopt(plan_path, approval_path, repo, verify):
    # Imported lazily: neither proposal validation nor public readers import the
    # execution driver or any model/evaluator entry point.
    from research.catalog_execution import approval_for, exclusive, append, now
    from research.catalog_share import inventory
    plan, old, record_path = validate_proposal(plan_path, repo)
    approval = approval_for(approval_path, plan_path)
    validate_approval(approval, plan_path, record_path, plan['date_revision']['proposed_at_utc'])
    verify(plan, repo)
    control = Path(repo) / plan['runs_dir'] / '_control'
    with exclusive(control):
        control, raw, events, _ = validate_originals(plan, old, repo)
        if len(events) > 5:
            return validate_history(plan_path, repo, approval=approval)
        if sha256(control / 'journal.jsonl') != plan['date_revision']['checkpoint']['journal_sha256']:
            raise ValueError('Amendment requires the exact stopped checkpoint')
        root = Path(repo) / plan['runs_dir'] / old['slots'][0]['run_id']
        if inventory(root) != read(control / (root.name + '.seal.json'))['files']:
            raise ValueError('Original Run changed before amendment adoption')
        baseline = Path(repo) / plan['probe'] / 'MS1-001-catalog-expanded-001'
        if not compare_initial(root, baseline, plan)['matches']:
            raise ValueError('Date-only revision does not explain the saved mismatch')
        path = control / ADOPTION
        record = {'kind': 'post_start_date_revision_adoption', 'id': ID,
                  'old_plan_sha256': OLD_SHA, 'plan_sha256': sha256(plan_path),
                  'amendment_sha256': sha256(record_path), 'approval': approval,
                  'approval_object_sha256': object_hash(approval),
                  'prior_journal_sha256': sha256(control / 'journal.jsonl'), 'adopted_at_utc': now()}
        if path.exists():
            saved = read(path)
            if {k:v for k,v in saved.items() if k != 'adopted_at_utc'} != {k:v for k,v in record.items() if k != 'adopted_at_utc'}:
                raise ValueError('Interrupted amendment adoption differs')
        else:
            write_new(path, record)
        append(control / 'journal.jsonl', {'kind': 'date_revision', 'id': ID,
            'plan_sha256': sha256(plan_path), 'amendment_sha256': sha256(record_path), 'adoption_sha256': sha256(path)})
    history = validate_history(plan_path, repo, approval=approval)
    return {'status': 'amendment_adopted_pause_retained', 'history': history, 'dispatches': 0}
