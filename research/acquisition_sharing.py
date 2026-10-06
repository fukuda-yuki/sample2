"""Explicit repaired-main publication adapter; no acquisition or scoring.

Local staging is reversible. Share requires exact public-byte approval and the
existing real Release/anonymous restore/owned cleanup path. Injected transport
never creates a main journal gate. The legacy design is an administrative view,
not the execution authority for this new cohort.
"""
import argparse
import copy
from pathlib import Path
import re
import uuid

from outer.harness import profiles, util
from research import acquisition_readiness as readiness, live_pilot, next_phase
from research import catalog_share, catalog_delivery, pair_execution, next_phase_sharing as sharing

KIND = live_pilot.MAIN_KIND
GATE_KIND = 'repaired_main_pair_publication_gate_v1'


def pair_uuid(plan, number):
    """New publication pair identity, deterministically scoped to the owner UUID."""
    if type(number) is not int or not 1 <= number <= 100:
        raise ValueError('Exact main pair number required')
    return uuid.uuid5(uuid.UUID(plan['phase_id']), 'repaired-main-pair:' + str(number)).hex


def phase_view(plan, plan_path, number):
    child = Path(plan['batch']) / ('pair-' + str(number))
    return {'kind': KIND, 'phase_sha256': util.sha256_file(child / 'phase.json'),
        'main_plan_sha256': util.sha256_file(plan_path), 'source_commit': plan['source_commit'],
        'pair_uuid': pair_uuid(plan, number), 'task_revision': plan['task_revision'],
        'settings': copy.deepcopy(plan['settings']), 'bounds': copy.deepcopy(plan['bounds'])}


def _condition_binding(plan, batch, case, binding, phase):
    root = batch / case['run_id']; manifest = util.read_json(root/'manifest.json')
    condition_path = root/'condition.json'; condition = util.read_json(condition_path)
    assignment = manifest.get('assignment', {})
    digest = util.sha256_file(batch/'phase.json')
    if (manifest.get('run_id') != case['run_id'] or manifest.get('run_instance_id') != case['run_instance_id']
            or manifest.get('condition_sha256') != binding.get('condition_sha256')
            or util.sha256_file(condition_path) != binding.get('condition_sha256')
            or manifest.get('prompt_sha256') != binding.get('input_sha256')
            or any(assignment.get(k) != v for k,v in case.items())
            or any(assignment.get(k) != binding.get(k) for k in ('plan_sha256','cohort','runtime'))
            or assignment.get('phase_sha256') != digest
            or binding.get('phase_sha256', digest) != digest
            or condition.get('task_profile_revision') != plan['task_revision']
            or condition.get('runtime', {}).get('id') != phase['runtime']
            or condition['runtime'].get('model_id') != plan['settings']['model_id']):
        raise ValueError('Saved main manifest/condition/child-phase binding differs')


def pair_context(repo, plan_path, number):
    repo, plan_path = live_pilot.safe_path(repo), live_pilot.safe_path(plan_path)
    plan = readiness.verify_main_phase(plan_path, repo)
    pair_uuid(plan, number)
    reference = live_pilot.reference(plan_path)
    base = Path(plan['batch'])
    if util.read_json(base / 'allocation.json') != dict(kind=KIND, plan=reference, phase_id=plan['phase_id']):
        raise ValueError('Foreign main allocation')
    selected = next((a for a in plan['assignments'] if a['pair'] == number), None)
    if selected is None: raise ValueError('Unassigned main pair')
    child_phase = live_pilot.observer_phase(plan, reference, number)
    batch = live_pilot.safe_path(child_phase['batch'])
    phase_path = batch / 'phase.json'
    if util.read_json(phase_path) != child_phase: raise ValueError('Main child phase changed')
    current = pair_execution.state(batch / '_control/pair-journal.jsonl')
    names = {c['run_id'] for c in selected['cases']}
    if len(names) != 2 or set(current['dispatch']) != names or set(current['results']) != names:
        raise ValueError('Exactly two assigned terminal main results required')
    bindings = []
    for case in selected['cases']:
        rid = case['run_id']; binding = current['dispatch'][rid]
        if (any(binding.get(k) != v for k, v in case.items())
                or binding.get('plan_sha256') != reference['sha256']
                or binding.get('cohort') != child_phase['cohort']
                or binding.get('runtime') != child_phase['runtime']):
            raise ValueError('Foreign main dispatch/Run UUID/phase')
        if current['implementations'].get(rid, {}).get('receipt', {}).get('stop_confirmed') is not True:
            raise ValueError('Both actual implementation stops required')
        _condition_binding(plan,batch,case,binding,child_phase)
        # The production journal retains the dispatch assignment before prepare
        # adds the child SHA to manifest.assignment. Do not rewrite that journal.
        bindings.append({**binding,'phase_sha256':util.sha256_file(phase_path)})
    baseline = util.read_json(repo / readiness.BASE_PROTOCOL)
    bundle = {'kind': KIND, 'plan': baseline, 'cohort': child_phase['cohort'],
        'assignments': [selected], 'source_commit': plan['source_commit'],
        'task_revision': plan['task_revision'], 'settings': plan['settings'], 'bounds': plan['bounds']}
    return bundle, batch, current, selected, bindings


def release_prefix(plan_path, bundle, phase):
    digest = util.sha256_file(plan_path)
    if (bundle.get('kind') != KIND or not phase or phase.get('kind') != KIND
            or phase.get('main_plan_sha256') != digest or phase.get('source_commit') != bundle['source_commit']
            or phase.get('task_revision') != readiness.REVISION):
        raise ValueError('Exact repaired main phase required for publication')
    return 'source-info-repaired-v6-' + digest[:12] + '-pair-'


def public_readme(bundle, phase):
    if bundle.get('kind') != KIND or phase.get('kind') != KIND:
        raise ValueError('Explicit repaired-main disclosure required')
    return ('# Repaired evaluator cohort: one actual assigned pair\n\n'
        'Kind: source_info_repaired_v6_main. This is a fresh cohort with new Run UUIDs; '
        'it does not extend, replace or regenerate the original 100-pair dataset. '
        'STUDY.json retains the old seeded allocation design only as an administrative baseline; '
        'the separately frozen main plan SHA and child phase SHA identify current execution.\n\n'
        'Current model: ' + bundle['settings']['model_id'] + '; provider: ' + bundle['settings']['provider'] +
        '; balance OFF; paid fallback OFF. Task revision: ' + bundle['task_revision'] + '. '
        'The bundled public request and requirements use that revised profile. '
        'Both fixed Run UUIDs, arm order, failures, partial usage and unknown quality are preserved. '
        'Bounds and current settings are in STUDY.json. Only this pair is included; '
        'a future maximum of 100 pairs/200 Runs is not a completed acquisition claim.\n\n'
        'Private oracles, evaluator binaries, native state and static application databases remain local. '
        'The public slice supports saved-evidence extraction, not private-oracle rescoring. '
        'Request/response and usage bytes remain subject to the exact public review and manifest exclusions. '
        'Missing usage stays unknown; early stops are not token-efficiency improvements.\n\n'
        'Verify all pair.manifest.json hashes, restore into a new folder, then run '
        '`python -B -m research.catalog_share extract --root . --out ../extracted-requests.json` '
        'from that relocated folder. The delivery path compares offline extraction hashes with sockets denied '
        'and removes only owned public/transfer copies. Original Runs remain retained. '
        'Publication gates verify actual transport and preservation; they do not approve product quality '
        'or guarantee future acquisition. See THIRD-PARTY-NOTICES.md and LICENSES/.\n')


def _checked_reference(ref):
    path = live_pilot.safe_path(ref['path'])
    if not re.fullmatch('[a-f0-9]{64}', ref.get('sha256', '')) or util.sha256_file(path) != ref['sha256']:
        raise ValueError('Main gate reference changed')
    return path


def validate_gate(value, current, number):
    from research import proof_session
    path = _checked_reference(value['main_plan'])
    repo = live_pilot.safe_path(value['source_repo'])
    plan = readiness.verify_main_phase(path, repo, check_tree=False)
    # Current journal/UUID state is part of the key, never an admission bool.
    arguments = dict(value=value,current=current,number=number,plan=plan)
    return proof_session.use('normal-gate',arguments,
        lambda: _validate_gate_proof(value,current,number,plan))


def _validate_gate_proof(value, current, number, plan):
    """Saved actual transport validator; no network, extraction, repair or writes."""
    fields = {'pair','plan_sha256','cohort','run_instances','evidence_files','publication_receipt',
        'roundtrip_receipt','cleanup_receipt','phase_sha256','main_plan','child_phase','finalization',
        'public_review','gate_kind','quality_acceptance','source_repo','pair_uuid','task_revision',
        'source_commit','package_sha256','original_inventory'}
    if set(value) != fields: raise ValueError('Unreviewed repaired-main gate fields')
    if value.get('gate_kind') != GATE_KIND or value.get('quality_acceptance') is not False:
        raise ValueError('Explicit publication-only main gate required')
    path = _checked_reference(value['main_plan'])
    repo = live_pilot.safe_path(value['source_repo'])
    ref = live_pilot.reference(path)
    selected = next((a for a in plan['assignments'] if a['pair'] == number), None)
    if selected is None: raise ValueError('Unassigned main gate pair')
    child_phase = live_pilot.observer_phase(plan, ref, number); batch = Path(child_phase['batch'])
    phase_path = _checked_reference(value['child_phase'])
    if phase_path != (batch / 'phase.json').resolve() or util.read_json(phase_path) != child_phase:
        raise ValueError('Foreign gate child phase')
    expected = {'pair': number, 'plan_sha256': ref['sha256'], 'cohort': child_phase['cohort'],
        'phase_sha256': util.sha256_file(phase_path), 'pair_uuid': pair_uuid(plan, number),
        'task_revision': plan['task_revision'], 'source_commit': plan['source_commit'],
        'run_instances': {c['run_id']: c['run_instance_id'] for c in selected['cases']}}
    if any(value.get(k) != v for k, v in expected.items()): raise ValueError('Main gate identity/revision differs')
    if set(current['dispatch']) != set(expected['run_instances']) or set(current['results']) != set(expected['run_instances']):
        raise ValueError('Main gate needs exactly two assigned results')
    for case in selected['cases']:
        b = current['dispatch'][case['run_id']]
        if (any(b.get(k) != v for k, v in case.items()) or b.get('plan_sha256') != ref['sha256']
                or b.get('cohort') != child_phase['cohort']
                or b.get('runtime') != child_phase['runtime']
                or current['implementations'][case['run_id']]['receipt'].get('stop_confirmed') is not True
                or pair_execution._postprocess_fault(current['results'][case['run_id']]['row'])):
            raise ValueError('Unstopped, foreign or operationally faulted main result')
        _condition_binding(plan,batch,case,b,child_phase)
    refs = value['evidence_files']
    for reference in (value['main_plan'], value['child_phase'], value['finalization'], value['public_review']):
        _checked_reference(reference)
        if refs.get(reference['path']) != reference['sha256']: raise ValueError('Required main evidence not retained')
    final_path = _checked_reference(value['finalization']); final = util.read_json(final_path)
    workspace = final_path.parent.resolve(); allowed = (repo / 'artifacts/continuity-sharing-v1').resolve()
    if workspace == allowed or not workspace.is_relative_to(allowed): raise ValueError('Foreign sharing workspace')
    if any(final.get(k) != expected[k] for k in ('pair','plan_sha256','cohort','phase_sha256','run_instances')):
        raise ValueError('Retained finalization identity differs')
    if final.get('review_sha256') != value['public_review']['sha256']: raise ValueError('Public review changed')
    if final.get('roundtrip_receipt') != value['roundtrip_receipt'] or type(final.get('attempt')) is not int or final['attempt'] <= 0:
        raise ValueError('Retained finalization restore/attempt differs')
    for name,digest in final['evidence_files'].items():
        target = live_pilot.safe_path(name)
        if not target.is_relative_to(workspace) or util.sha256_file(target) != digest:
            raise ValueError('Finalization evidence escaped or changed')
    exact_refs = {**final['evidence_files'], value['cleanup_receipt']:util.sha256_file(value['cleanup_receipt']),
        **{r['path']:r['sha256'] for r in (value['main_plan'],value['child_phase'],value['finalization'],value['public_review'])}}
    if refs != exact_refs: raise ValueError('Main gate evidence inventory differs from finalization')
    original = final['original_inventory']
    if set(original) != set(expected['run_instances']): raise ValueError('Exact two original inventories required')
    for rid, inventory in original.items():
        if catalog_share.inventory(batch / rid) != inventory: raise ValueError('Immutable original main Run changed')
    if value.get('original_inventory') != original: raise ValueError('Gate original inventory differs')
    for receipt_name in ('publication_receipt','roundtrip_receipt','cleanup_receipt'):
        target = live_pilot.safe_path(value[receipt_name])
        if not target.is_relative_to(workspace) or str(target) not in refs:
            raise ValueError('Main publication evidence escaped workspace')
    publication = util.read_json(value['publication_receipt']); restored = util.read_json(value['roundtrip_receipt'])
    cleanup = util.read_json(value['cleanup_receipt'])
    if (publication.get('remote_assets_verified') is not True or restored.get('hashes_match') is not True
            or restored.get('extraction_sockets_blocked') is not True or cleanup.get('cleanup_completed') is not True
            or cleanup.get('original_runs_deleted') is not False):
        raise ValueError('Strict actual publication/restore/cleanup confirmations required')
    pair_execution._validate_gate_common(value, current, number)
    if publication.get('transport_mode') != 'github-release-anonymous-download-v1':
        raise ValueError('Injected transport cannot adopt a main publication gate')
    remote_ref = publication['actual_remote_readback']; remote_path = _checked_reference(remote_ref)
    if not remote_path.is_relative_to(workspace) or refs.get(remote_ref['path']) != remote_ref['sha256']:
        raise ValueError('Actual remote readback missing from gate')
    remote = util.read_json(remote_path); tag = 'source-info-repaired-v6-' + ref['sha256'][:12] + '-pair-' + f'{number:03d}'
    if (remote.get('tag_name') != tag or remote.get('target_commitish') != plan['source_commit']
            or remote.get('tag_commit') != plan['source_commit'] or type(remote.get('release_id')) is not int
            or remote['release_id'] <= 0 or remote.get('html_url') != 'https://github.com/' + catalog_delivery.REPOSITORY + '/releases/tag/' + tag):
        raise ValueError('Actual remote main tag/source identity differs')
    rows = remote['assets']
    if (len(rows) != len({r['name'] for r in rows}) or len(rows) != len({r['id'] for r in rows})
            or any(type(r['id']) is not int or r['id'] <= 0 or type(r['size']) is not int or r['size'] <= 0 for r in rows)):
        raise ValueError('Duplicate or invalid actual remote asset identity/size')
    for name,url in publication['urls'].items():
        if len(catalog_share.safe_member(name).parts) != 1 or url != ('https://github.com/' + catalog_delivery.REPOSITORY + '/releases/download/' + tag + '/' + name):
            raise ValueError('Noncanonical remote main download URL')
    asset = publication['asset_manifest']; package = value.get('package_sha256')
    if (not re.fullmatch('[a-f0-9]{64}', package or '') or package != final['package_sha256']
            or package != asset['sha256'] or publication.get('plan_sha256') != ref['sha256']
            or publication.get('pair') != number or publication.get('phase_sha256') != expected['phase_sha256']
            or asset.get('plan_sha256') != ref['sha256'] or asset.get('pair') != number
            or asset.get('selected_runs') != [c['run_id'] for c in selected['cases']]
            or asset.get('review_sha256') != value['public_review']['sha256']):
        raise ValueError('Reviewed package main binding differs')
    decision = util.read_json(_checked_reference(value['public_review']))
    if decision.get('publication_approved') is not True or decision.get('reviewed_inventory') != asset.get('file_inventory'):
        raise ValueError('Exact public-byte approval differs from package')
    from research import paired_acceptance
    paired_acceptance.actual_remote(value)
    if (restored.get('plan_sha256') != ref['sha256'] or restored.get('pair') != number
            or restored.get('selected_runs') != asset['selected_runs']
            or restored.get('part_hashes') != asset['parts']
            or set(restored.get('metadata_hashes',{})) != {'pair.manifest.json','public-review.json','scan.json'}
            or restored.get('model_called') is not False or restored.get('evaluator_called') is not False
            or restored.get('package_sha256') != package): raise ValueError('Saved restore main binding differs')
    if live_pilot.safe_path(restored['workspace']) != workspace / f"roundtrip-{final['attempt']:03d}":
        raise ValueError('Restore is not the exact owned attempt directory')
    before = workspace / 'before-upload-extraction.json'; after = Path(restored['workspace']) / 'extraction.json'
    for target in (before, after):
        target = live_pilot.safe_path(target)
        if not target.is_relative_to(workspace) or refs.get(str(target)) != util.sha256_file(target):
            raise ValueError('Offline extraction evidence escaped or changed')
    if util.sha256_file(before) != util.sha256_file(after) or restored['extraction_sha256'] != util.sha256_file(before):
        raise ValueError('Original and relocated extraction differ')
    targets = [workspace/'public', workspace/'package', Path(restored['workspace'])/'download', Path(restored['workspace'])/'restored']
    from research.proof_session import watch_absence
    for target in targets: watch_absence(target)
    if (cleanup.get('targets') != [str(t) for t in targets] or any(live_pilot.safe_path(t).exists() for t in targets)
            or cleanup.get('original_runs_deleted') is not False): raise ValueError('Owned cleanup scope/absence differs')
    return True


def _record(repo, plan_path, number, phase, review, batch, gate_path):
    bundle, expected_batch, current, pair, bindings = pair_context(repo, plan_path, number)
    if Path(batch).resolve() != expected_batch.resolve(): raise ValueError('Foreign gate batch')
    raw = util.read_json(gate_path); workspace = Path(gate_path).parent
    final = workspace/'finalization.json'; saved = util.read_json(final)
    reference = live_pilot.reference(plan_path)
    review = live_pilot.safe_path(review)
    if util.sha256_file(review) != saved['review_sha256']: raise ValueError('Exact retained public review missing')
    extra = {'main_plan':reference,'child_phase':live_pilot.reference(expected_batch/'phase.json'),
        'finalization':live_pilot.reference(final),'public_review':live_pilot.reference(review)}
    gate = {**raw, **extra, 'gate_kind':GATE_KIND,'quality_acceptance':False,'source_repo':str(Path(repo).resolve()),
        'pair_uuid':phase['pair_uuid'],'task_revision':phase['task_revision'],'source_commit':phase['source_commit'],
        'package_sha256':saved['package_sha256'],'original_inventory':saved['original_inventory'],
        'evidence_files':{**raw['evidence_files'],**{r['path']:r['sha256'] for r in extra.values()}}}
    validate_gate(gate,current,number)
    output = workspace/('repaired-main-'+Path(gate_path).name)
    if output.exists():
        if util.read_json(output)!=gate: raise ValueError('Retained main gate differs')
    else: util.write_new_json(output,gate)
    pair_execution.record_pair_gate(batch,number,output)
    return output


def stage(repo, plan_path, number, destination):
    plan = readiness.verify_main_phase(plan_path,repo); phase = phase_view(plan,plan_path,number)
    return sharing.stage(repo,plan_path,number,destination,context=pair_context,phase=phase)


def share(repo, plan_path, number, workspace, review, *, transfer=None, fetch=catalog_delivery.download):
    plan = readiness.verify_main_phase(plan_path,repo); phase = phase_view(plan,plan_path,number); recorded=[]
    def record(batch,n,path):recorded.append(_record(repo,plan_path,n,phase,review,batch,path))
    result=sharing.share(repo,plan_path,number,workspace,review,context=pair_context,phase=phase,
        record_gate=record,transfer=transfer,fetch=fetch)
    if recorded: result={**result,'gate':str(recorded[-1])}
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('stage','share')); parser.add_argument('--repo',required=True,type=Path)
    parser.add_argument('--plan',required=True,type=Path);parser.add_argument('--pair',required=True,type=int)
    parser.add_argument('--workspace',required=True,type=Path);parser.add_argument('--review',type=Path)
    args=parser.parse_args()
    if args.mode=='share' and args.review is None:parser.error('--review required for exact public-byte approval')
    return stage(args.repo,args.plan,args.pair,args.workspace) if args.mode=='stage' else share(args.repo,args.plan,args.pair,args.workspace,args.review)


if __name__=='__main__':print(main())
