"""New-cohort public staging and identity-bound roundtrip gate; never models.

Staging is local. Publishing is a separate explicit command with exact-byte
review, using existing Release reconciliation, anonymous download, offline
extraction, and ownership-limited cleanup. Old catalog release tags are unused.
"""
import argparse
import json
from pathlib import Path
import shutil

from outer.harness import machine, profiles, util
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


def release_prefix(bundle_path, bundle, phase=None):
    """Keep distinct frozen bundles and technical fixtures off each other's tags."""
    technical = bundle.get('kind') == 'continuity_sharing_technical_fixture'
    if technical and not bundle['cohort'].startswith('runs/_technical-sharing-'):
        raise ValueError('Technical sharing fixture must remain outside research cohorts')
    if not technical and bundle.get('kind') != 'continuity_prospective_bundle':
        raise ValueError('Sharing requires a frozen research bundle or explicit technical fixture')
    prefix = ('technical-continuity' if technical else
        'source-info-v5-100p2' if bundle.get('plan', {}).get('plan_id') == next_phase.V5_ID else 'source-info-v2')
    digest = phase['phase_sha256'] if phase else util.sha256_file(bundle_path)
    if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('Exact phase/bundle SHA-256 required for publication tag')
    return prefix + '-' + digest[:12] + '-pair-'


def phase_remote_identity(remote, tag, phase):
    """Resolve actual remote tag objects before reusing a new-phase release."""
    if (not remote or remote.get('draft') or remote.get('tag_name') != tag
            or remote.get('target_commitish') != phase['source_commit']):
        raise ValueError('Remote phase release source identity differs')
    obj = json.loads(catalog_delivery.gh('api',
        f'repos/{catalog_delivery.REPOSITORY}/git/ref/tags/{tag}'))['object']
    for _ in range(5):
        if obj.get('type') == 'commit':
            if obj.get('sha') != phase['source_commit']:
                raise ValueError('Actual remote tag points to a different phase commit')
            return {'target_commitish': remote['target_commitish'], 'tag_commit': obj['sha']}
        if obj.get('type') != 'tag': break
        obj = json.loads(catalog_delivery.gh('api',
            f'repos/{catalog_delivery.REPOSITORY}/git/tags/{obj["sha"]}'))['object']
    raise ValueError('Remote phase tag cannot be resolved to its exact commit')


def clocked(workspace, bundle_path, number, bundle, bindings, stage_name, operation, *, phase=None):
    phases = {b.get('phase_sha256') for b in bindings}
    if phase:
        phases.add(phase['phase_sha256'])
    if len(phases) != 1:
        raise ValueError('Mixed execution phases in public operation')
    phase_digest = next(iter(phases))
    return machine.timed_stage(Path(workspace) / 'public-gate-timing.jsonl', stage_name, operation,
        binding={'pair': number, 'plan_sha256': util.sha256_file(bundle_path),
            'cohort': bundle['cohort'],
            'run_instances': {b['run_id']: b['run_instance_id'] for b in bindings},
            **({'phase_sha256': phase_digest} if phase_digest else {})})


def stage(repo, bundle_path, number, destination, *, context=None, phase=None):
    repo, destination = Path(repo).resolve(), Path(destination).resolve()
    if phase and not callable(context):
        raise ValueError('Phase staging requires the authoritative central context')
    bundle, batch, current, pair, bindings = (context or pair_context)(repo, bundle_path, number)
    release_prefix(bundle_path, bundle, phase)
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
        'evaluator_called': False, 'complete_research_corpus': False,
        **({'execution_phase': phase} if phase else {})}
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
            if (relative.startswith('frozen/') and relative.lower().endswith(
                    ('.sqlite', '.sqlite3', '.db', '-wal', '-shm', '-journal'))):
                reason = ('Submitted static databases remain in the complete local frozen package; '
                    'this public evidence slice records their hashes and omissions and does not '
                    'provide runnable application or database/evaluator replay.')
            if reason:
                manifest['excluded'].append({'path': name, **originals[rid][relative], 'reason': reason})
            else:
                copy(source, name, originals[rid][relative]['sha256'])
    task_profile = profiles.read(repo, 'tasks', pair['task'])
    family = bundle['plan'].get('task_hierarchy', {}).get(pair['task'], {}).get('family', 'music-store-continuity')
    public_request = 'research/tasks/' + family + '/public-request.txt'
    for name in ('research/__init__.py', 'research/catalog_allocation_review.py', 'research/catalog_share.py',
            'research/sql/catalog_otel_requests.sql', next_phase.protocol_path(bundle['plan']),
            'research/tasks/candidate-register.json', public_request, task_profile['evaluation']['spec_path']):
        copy(repo / name, name)
    copy(repo / 'research/sharing/CONTINUITY-README.md', 'README.md')
    if phase:
        # This is a new reviewed public copy; the historical private plan and
        # original five pairs are not edited or reinterpreted.
        readme = public / 'README.md'
        readme.write_text(readme.read_text(encoding='utf-8') +
            '\n## Prospectively amended execution phase\n\n'
            'The original v5 allocation and its first five pairs remain historical records. '
            'This pair belongs to the separately approved central fixed-wave phase for '
            + ('original pairs ' + str(max(phase['completed_earlier_pairs']) + 1) + '–100: two pairs/four Runs under unchanged operational health criteria. '
               if phase.get('maximum_pairs') == 2 else
               'original pairs 6–100: initially two pairs/four Runs, optionally four pairs/eight Runs under predeclared operational health criteria. ')
            + 'Internal Run concurrency '
            'remains one. All wave implementations stop before serial evaluation and '
            'publication gates. No additional samples or regenerated earlier Runs are included. '
            'STUDY.json and MANIFEST.json identify the execution phase and evaluator '
            'implementation separately from the original allocation.\n', encoding='utf-8')
        entry = next(e for e in manifest['files'] if e['path'] == 'README.md')
        entry.update(sha256=util.sha256_file(readme), bytes=readme.stat().st_size,
                     transformation='historical_readme_with_explicit_prospective_phase_addendum')
    copy(repo / 'research/sharing/THIRD-PARTY-NOTICES.md', 'THIRD-PARTY-NOTICES.md')
    for name in ('MS-PL.txt', 'OpenCode-MIT.txt'):
        copy(repo / 'research/sharing/LICENSES' / name, 'LICENSES/' + name)
    task_assets = (repo / task_profile['evaluation']['catalog_path']).parents[1]
    source_root = task_assets / 'inputs/legacy-source'
    for name in ('readme.txt', 'README.md', 'LICENSE', 'LICENSE.txt'):
        attribution = source_root / name
        if attribution.is_file(): copy(attribution, 'UPSTREAM/' + name)
    portable = public / 'STUDY.json'
    util.write_new_json(portable, {'plan': bundle['plan'], 'assignments': bundle['assignments'],
        'source_commit': bundle['source_commit'], 'original_bundle_sha256': util.sha256_file(bundle_path),
        **({'execution_phase': phase} if phase else {}),
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


def share(repo, bundle_path, number, workspace, review, *, transfer=None, fetch=catalog_delivery.download,
          context=None, phase=None, record_gate=None):
    repo, workspace = Path(repo).resolve(), Path(workspace).resolve()
    if phase and (not callable(context) or not callable(record_gate)):
        raise ValueError('Phase sharing requires central context and gate recorder')
    allowed = repo / 'artifacts/continuity-sharing-v1'
    if workspace == allowed or not workspace.is_relative_to(allowed):
        raise ValueError('Use the designated owned continuity sharing workspace')
    bundle, batch, current, pair, bindings = (context or pair_context)(repo, bundle_path, number)
    if number in current['gates']: return {'status': 'gate_already_complete', 'model_called': False}
    finalization = workspace / 'finalization.json'
    if finalization.exists():
        return finish(repo, bundle_path, number, workspace, review, finalization,
                      context=context, phase=phase, record_gate=record_gate)
    manifest = catalog_share.verify_public(workspace / 'public', exact=True)
    if manifest['plan_sha256'] != util.sha256_file(bundle_path) or manifest['pair'] != number:
        raise ValueError('Public bytes belong to another plan/pair')
    if manifest.get('execution_phase') != phase:
        raise ValueError('Public bytes belong to another execution phase')
    for rid, original in manifest['original_inventory'].items():
        if catalog_share.inventory(batch / rid) != original: raise ValueError('Original pair changed after review')
    asset = clocked(workspace, bundle_path, number, bundle, bindings, 'package_including_compression',
        lambda: catalog_delivery.package(workspace / 'public', workspace / 'package', review))
    original_extraction = workspace / 'before-upload-extraction.json'
    if not original_extraction.exists():
        clocked(workspace, bundle_path, number, bundle, bindings, 'before_upload_offline_extract',
            lambda: catalog_delivery.offline_extract(workspace / 'public', original_extraction))
    prefix = release_prefix(bundle_path, bundle, phase)
    actual_transport = transfer is None and fetch is catalog_delivery.download
    if transfer is None:
        def transfer(package, tag, commit):
            if phase:
                existing = catalog_delivery.release(tag)
                if existing: phase_remote_identity(existing, tag, phase)
            return catalog_delivery.publish(package, tag, commit, tag_prefix=prefix)
    urls = clocked(workspace, bundle_path, number, bundle, bindings, 'publication_and_remote_hash_check',
        lambda: transfer(workspace / 'package', prefix + f'{number:03d}',
                         phase['source_commit'] if phase else bundle['source_commit']))
    publication = {'remote_assets_verified': True, 'urls': urls, 'package_sha256': asset['sha256'],
        'asset_manifest': asset, 'plan_sha256': util.sha256_file(bundle_path), 'pair': number,
        **({'phase_sha256': phase['phase_sha256']} if phase else {})}
    if bundle['plan']['plan_id'] == next_phase.V5_ID:
        # v5 live acceptance cannot use the injectable local rehearsal path.
        publication['transport_mode'] = ('github-release-anonymous-download-v1'
            if actual_transport else 'injected-transport')
        if actual_transport:
            remote_path = workspace / 'actual-remote-readback.json'
            if not remote_path.exists():
                remote = catalog_delivery.release(prefix + f'{number:03d}')
                if not remote or remote.get('draft'):
                    raise ValueError('Actual v5 release readback missing')
                identity = phase_remote_identity(remote, prefix + f'{number:03d}', phase) if phase else {}
                util.write_new_json(remote_path, {'tag_name': remote['tag_name'],
                    'release_id': remote['id'], 'html_url': remote['html_url'],
                    **identity,
                    'assets': [{k: row[k] for k in ('id', 'name', 'size', 'digest', 'browser_download_url')}
                        for row in remote['assets']]})
            publication['actual_remote_readback'] = next_phase.reference(remote_path)
    publication_path = workspace / 'publication-receipt.json'
    if publication_path.exists():
        if util.read_json(publication_path) != publication: raise ValueError('Retained remote receipt differs')
    else: util.write_new_json(publication_path, publication)
    attempt = 1
    while (workspace / f'roundtrip-{attempt:03d}').exists(): attempt += 1
    trip_root = workspace / f'roundtrip-{attempt:03d}'
    restored = clocked(workspace, bundle_path, number, bundle, bindings, 'download_restore_offline_extract',
        lambda: catalog_delivery.roundtrip(asset, urls, trip_root, fetch=fetch))
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
    evidence_paths = [publication_path, roundtrip_path, original_extraction, trip_root / 'extraction.json']
    if publication.get('actual_remote_readback'):
        evidence_paths.append(Path(publication['actual_remote_readback']['path']))
    util.write_new_json(finalization, {'pair': number,
        'plan_sha256': util.sha256_file(bundle_path), 'cohort': bundle['cohort'],
        'run_instances': {b['run_id']: b['run_instance_id'] for b in bindings},
        **({'phase_sha256': phase['phase_sha256']} if phase else {}),
        'review_sha256': util.sha256_file(review), 'attempt': attempt,
        'original_inventory': manifest['original_inventory'],
        'package_sha256': asset['sha256'], 'roundtrip_receipt': str(roundtrip_path),
        'evidence_files': {str(p): util.sha256_file(p) for p in evidence_paths}})
    return finish(repo, bundle_path, number, workspace, review, finalization,
                  context=context, phase=phase, record_gate=record_gate)


def finish(repo, bundle_path, number, workspace, review, finalization, *, context=None,
           phase=None, record_gate=None):
    """Complete only the saved verified roundtrip, including after owned cleanup."""
    bundle, batch, current, pair, bindings = (context or pair_context)(repo, bundle_path, number)
    saved = util.read_json(finalization)
    expected = {'pair': number, 'plan_sha256': util.sha256_file(bundle_path),
        'cohort': bundle['cohort'], 'review_sha256': util.sha256_file(review),
        'run_instances': {b['run_id']: b['run_instance_id'] for b in bindings},
        **({'phase_sha256': phase['phase_sha256']} if phase else {})}
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
        cleanup = clocked(workspace, bundle_path, number, bundle, bindings, 'owned_copy_cleanup',
            lambda: catalog_delivery.cleanup(workspace, repo / 'artifacts/continuity-sharing-v1', restored))
        util.write_new_json(cleanup_path, {**cleanup, 'package_sha256': saved['package_sha256']})
    gate_path = workspace / f'gate-{attempt:03d}.json'
    refs = {**saved['evidence_files'], str(cleanup_path): util.sha256_file(cleanup_path),
            str(finalization): util.sha256_file(finalization)}
    gate = {'pair': number, 'plan_sha256': util.sha256_file(bundle_path),
        'cohort': bundle['cohort'], 'run_instances': {b['run_id']: b['run_instance_id'] for b in bindings},
        'evidence_files': refs, 'publication_receipt': str(workspace / 'publication-receipt.json'),
        'roundtrip_receipt': saved['roundtrip_receipt'], 'cleanup_receipt': str(cleanup_path),
        **({'phase_sha256': phase['phase_sha256']} if phase else {})}
    if gate_path.exists():
        if util.read_json(gate_path) != gate: raise ValueError('Retained gate differs')
    else: util.write_new_json(gate_path, gate)
    if record_gate is None:
        if phase: raise ValueError('Phase gate requires the authoritative central recorder')
        pair_execution.record_pair_gate(batch, number, gate_path)
    else:
        record_gate(batch, number, gate_path)
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
        bundle, _, _, _, bindings = pair_context(args.repo, args.bundle, args.pair)
        workspace = args.workspace.resolve()
        allowed = args.repo.resolve() / 'artifacts/continuity-sharing-v1'
        if workspace == allowed or not workspace.is_relative_to(allowed):
            raise ValueError('Public gate clock must stay inside the owned sharing workspace')
        result = clocked(workspace, args.bundle, args.pair, bundle, bindings, 'local_public_gate',
            lambda: share(args.repo, args.bundle, args.pair, workspace, args.review))
    print(json.dumps(result, indent=2))


if __name__ == '__main__': main()
