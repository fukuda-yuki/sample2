"""New-cohort public staging and identity-bound roundtrip gate; never models.

Staging is local. Publishing is a separate explicit command with exact-byte
review, using existing Release reconciliation, anonymous download, offline
extraction, and ownership-limited cleanup. Old catalog release tags are unused.
"""
import argparse
import json
from pathlib import Path
import shutil

from outer.harness import util
from research import catalog_delivery, catalog_share, next_phase, pair_execution


def pair_context(repo, bundle_path, number):
    bundle = util.read_json(bundle_path)
    next_phase.validate_plan(bundle['plan'])
    batch = next_phase.inside(repo, bundle['cohort'], 'runs')
    current = pair_execution.state(batch / '_control/pair-journal.jsonl')
    pair = next((p for p in bundle['assignments'] if p['pair'] == number), None)
    if not pair: raise ValueError('Unassigned pair')
    bindings = [current['dispatch'].get(c['run_id'], {}) for c in pair['cases']]
    digest = util.sha256_file(bundle_path)
    if any(b.get('plan_sha256') != digest or b.get('cohort') != bundle['cohort'] for b in bindings):
        raise ValueError('Pair dispatch belongs to another bundle/cohort')
    if any(c['run_id'] not in current['results'] for c in pair['cases']):
        raise ValueError('Two terminal postprocessing receipts are required')
    if any(current['implementations'][c['run_id']]['receipt'].get('stop_confirmed') is not True for c in pair['cases']):
        raise ValueError('Both implementation stops must be confirmed')
    return bundle, batch, current, pair, bindings


def stage(repo, bundle_path, number, destination):
    repo, destination = Path(repo).resolve(), Path(destination).resolve()
    bundle, batch, current, pair, bindings = pair_context(repo, bundle_path, number)
    if destination.exists() or not destination.is_relative_to(repo / 'artifacts'):
        raise ValueError('Use a new owned artifacts staging directory')
    public = destination / 'public'
    public.mkdir(parents=True)
    names = [c['run_id'] for c in pair['cases']]
    originals = {rid: catalog_share.inventory(batch / rid) for rid in names}
    manifest = {'schema_version': 1, 'kind': 'continuity_allocated_pair_public_copy',
        'cohort': bundle['cohort'], 'pair': number, 'plan_sha256': util.sha256_file(bundle_path),
        'selected_runs': names, 'assigned_slots': pair['cases'],
        'run_instances': {b['run_id']: b['run_instance_id'] for b in bindings},
        'original_inventory': originals, 'files': [], 'excluded': [], 'model_called': False,
        'evaluator_called': False, 'complete_research_corpus': False}
    def copy(source, name, original_hash=None):
        catalog_share.safe_member(name)
        output = catalog_share.native(public / name)
        output.parent.mkdir(parents=True, exist_ok=True)
        raw = source.read_bytes()
        value = catalog_share.public_bytes(source)
        output.write_bytes(value)
        manifest['files'].append({'path': name, 'source_sha256': original_hash or util.sha256_bytes(raw),
            'sha256': util.sha256_file(output), 'bytes': len(value),
            'transformation': 'local_home_path_only' if raw != value else 'byte_identical'})
    for rid in names:
        for relative, source in catalog_share.files(batch / rid):
            name = bundle['cohort'] + '/' + rid + '/' + relative
            reason = catalog_share.exclusion(relative)
            if reason:
                manifest['excluded'].append({'path': name, **originals[rid][relative], 'reason': reason})
            else:
                copy(source, name, originals[rid][relative]['sha256'])
    for name in ('research/__init__.py', 'research/catalog_allocation_review.py', 'research/catalog_share.py',
            'research/sql/catalog_otel_requests.sql', next_phase.PLAN,
            'research/tasks/candidate-register.json', 'research/tasks/music-store-continuity/public-request.txt',
            'inner/spec/requirements-cont-A-1.3.0.json', 'inner/spec/requirements-cont-B-1.3.0.json'):
        copy(repo / name, name)
    for name in ('README.md', 'THIRD-PARTY-NOTICES.md'):
        copy(repo / 'research/sharing' / name, name)
    portable = public / 'STUDY.json'
    util.write_new_json(portable, {'plan': bundle['plan'], 'assignments': bundle['assignments'],
        'source_commit': bundle['source_commit'], 'original_bundle_sha256': util.sha256_file(bundle_path),
        'public_subset_limitations': 'Private oracle, runtime, native state and evaluation databases remain local; this public slice supports saved evidence extraction, not a full evaluator replay.'})
    manifest['files'].append({'path': 'STUDY.json', 'sha256': util.sha256_file(portable),
        'source_sha256': None, 'bytes': portable.stat().st_size, 'transformation': 'explicit_portable_study_metadata'})
    if any(catalog_share.inventory(batch / rid) != originals[rid] for rid in names):
        raise ValueError('Originals changed during staging')
    manifest['originals_unchanged'] = True
    util.write_new_json(public / 'MANIFEST.json', manifest)
    util.write_new_json(destination / 'stage-receipt.json', {'originals_unchanged': True,
        'manifest_sha256': util.sha256_file(public / 'MANIFEST.json'), 'model_called': False})
    util.write_new_json(destination / 'review-template.json', {'publication_approved': False,
        'reviewed_inventory': catalog_share.inventory(public), 'reviewer': None,
        'checks': ['Secret/private-context scan', 'Images and task/source licenses',
            'Preserved failures, missing usage and unassessed states', 'Documented public exclusions']})
    return {'status': 'staged_pending_exact_public_review', 'workspace': str(destination),
        'model_called': False, 'next_pair_gate_complete': False}


def share(repo, bundle_path, number, workspace, review, *, transfer=None, fetch=catalog_delivery.download):
    repo, workspace = Path(repo).resolve(), Path(workspace).resolve()
    allowed = repo / 'artifacts/continuity-sharing-v1'
    if workspace == allowed or not workspace.is_relative_to(allowed):
        raise ValueError('Use the designated owned continuity sharing workspace')
    bundle, batch, current, pair, bindings = pair_context(repo, bundle_path, number)
    if number in current['gates']: return {'status': 'gate_already_complete', 'model_called': False}
    finalization = workspace / 'finalization.json'
    if finalization.exists():
        return finish(repo, bundle_path, number, workspace, review, finalization)
    manifest = catalog_share.verify_public(workspace / 'public', exact=True)
    if manifest['plan_sha256'] != util.sha256_file(bundle_path) or manifest['pair'] != number:
        raise ValueError('Public bytes belong to another plan/pair')
    for rid, original in manifest['original_inventory'].items():
        if catalog_share.inventory(batch / rid) != original: raise ValueError('Original pair changed after review')
    asset = catalog_delivery.package(workspace / 'public', workspace / 'package', review)
    original_extraction = workspace / 'before-upload-extraction.json'
    if not original_extraction.exists(): catalog_delivery.offline_extract(workspace / 'public', original_extraction)
    if transfer is None:
        transfer = lambda package, tag, commit: catalog_delivery.publish(package, tag, commit, tag_prefix='continuity-v1-pair-')
    urls = transfer(workspace / 'package', f'continuity-v1-pair-{number:03d}', bundle['source_commit'])
    publication = {'remote_assets_verified': True, 'urls': urls, 'package_sha256': asset['sha256'],
        'asset_manifest': asset, 'plan_sha256': util.sha256_file(bundle_path), 'pair': number}
    publication_path = workspace / 'publication-receipt.json'
    if publication_path.exists():
        if util.read_json(publication_path) != publication: raise ValueError('Retained remote receipt differs')
    else: util.write_new_json(publication_path, publication)
    attempt = 1
    while (workspace / f'roundtrip-{attempt:03d}').exists(): attempt += 1
    trip_root = workspace / f'roundtrip-{attempt:03d}'
    restored = catalog_delivery.roundtrip(asset, urls, trip_root, fetch=fetch)
    if restored['extraction_sha256'] != util.sha256_file(original_extraction):
        raise ValueError('Downloaded offline extraction differs from reviewed bytes')
    for rid, original in manifest['original_inventory'].items():
        if catalog_share.inventory(batch / rid) != original: raise ValueError('Original pair changed during transfer')
    bound_roundtrip = {**restored, 'package_sha256': asset['sha256']}
    roundtrip_path = workspace / f'roundtrip-bound-{attempt:03d}.json'
    util.write_new_json(roundtrip_path, bound_roundtrip)
    # Save the verified identities and retained evidence before deleting any
    # public/transfer copy. A crash after cleanup must not require these copies
    # or another upload, download, evaluator, or model dispatch.
    util.write_new_json(finalization, {'pair': number,
        'plan_sha256': util.sha256_file(bundle_path), 'cohort': bundle['cohort'],
        'run_instances': {b['run_id']: b['run_instance_id'] for b in bindings},
        'review_sha256': util.sha256_file(review), 'attempt': attempt,
        'original_inventory': manifest['original_inventory'],
        'package_sha256': asset['sha256'], 'roundtrip_receipt': str(roundtrip_path),
        'evidence_files': {str(p): util.sha256_file(p) for p in
            (publication_path, roundtrip_path, original_extraction, trip_root / 'extraction.json')}})
    return finish(repo, bundle_path, number, workspace, review, finalization)


def finish(repo, bundle_path, number, workspace, review, finalization):
    """Complete only the saved verified roundtrip, including after owned cleanup."""
    bundle, batch, current, pair, bindings = pair_context(repo, bundle_path, number)
    saved = util.read_json(finalization)
    expected = {'pair': number, 'plan_sha256': util.sha256_file(bundle_path),
        'cohort': bundle['cohort'], 'review_sha256': util.sha256_file(review),
        'run_instances': {b['run_id']: b['run_instance_id'] for b in bindings}}
    if any(saved.get(k) != v for k, v in expected.items()):
        raise ValueError('Retained finalization belongs to another pair, instance or review')
    for name, digest in saved['evidence_files'].items():
        path = Path(name).resolve()
        if not path.is_relative_to(workspace) or util.sha256_file(path) != digest:
            raise ValueError('Retained roundtrip evidence changed or escaped workspace')
    for rid, original in saved['original_inventory'].items():
        if catalog_share.inventory(batch / rid) != original:
            raise ValueError('Original pair changed after verified roundtrip')
    restored = util.read_json(saved['roundtrip_receipt'])
    if restored.get('package_sha256') != saved['package_sha256']:
        raise ValueError('Roundtrip package identity changed')
    attempt = saved['attempt']
    cleanup_path = workspace / f'cleanup-{attempt:03d}.json'
    if cleanup_path.exists():
        cleanup = util.read_json(cleanup_path)
        if (cleanup.get('cleanup_completed') is not True or
                cleanup.get('package_sha256') != saved['package_sha256'] or
                any(Path(p).exists() for p in cleanup.get('targets', []))):
            raise ValueError('Retained cleanup is incomplete or copies reappeared')
    else:
        cleanup = catalog_delivery.cleanup(workspace, repo / 'artifacts/continuity-sharing-v1', restored)
        util.write_new_json(cleanup_path, {**cleanup, 'package_sha256': saved['package_sha256']})
    gate_path = workspace / f'gate-{attempt:03d}.json'
    refs = {**saved['evidence_files'], str(cleanup_path): util.sha256_file(cleanup_path),
            str(finalization): util.sha256_file(finalization)}
    gate = {'pair': number, 'plan_sha256': util.sha256_file(bundle_path),
        'cohort': bundle['cohort'], 'run_instances': {b['run_id']: b['run_instance_id'] for b in bindings},
        'evidence_files': refs, 'publication_receipt': str(workspace / 'publication-receipt.json'),
        'roundtrip_receipt': saved['roundtrip_receipt'], 'cleanup_receipt': str(cleanup_path)}
    if gate_path.exists():
        if util.read_json(gate_path) != gate: raise ValueError('Retained gate differs')
    else: util.write_new_json(gate_path, gate)
    pair_execution.record_pair_gate(batch, number, gate_path)
    return {'status': 'shared_downloaded_restored_extracted_cleaned', 'pair': number,
        'gate': str(gate_path), 'model_called': False, 'originals_unchanged': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('stage', 'share'))
    parser.add_argument('--repo', type=Path, default=next_phase.REPO)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--pair', type=int, required=True)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--review', type=Path)
    args = parser.parse_args()
    if args.mode == 'stage': result = stage(args.repo, args.bundle, args.pair, args.workspace)
    else:
        if not args.review: parser.error('share requires --review of exact public bytes')
        result = share(args.repo, args.bundle, args.pair, args.workspace, args.review)
    print(json.dumps(result, indent=2))


if __name__ == '__main__': main()
