"""Fault-injection tests through the same driver/storage/transfer paths used live.

Only the dispatch and remote transport boundaries are synthetic. No model,
evaluator, provider credential or GitHub write is used by this suite.
"""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from outer.harness import browser_cleanup, evaluate, runtime, util
from research import catalog_delivery as delivery, catalog_execution as execution, catalog_share as sharing, catalog_storage as storage
from research.catalog_allocation_review import read, sha256, write_new
from research.catalog_confirmatory import allocation

REPO = Path(__file__).resolve().parents[2]


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.batch = self.repo / 'runs/test-cohort'
        self.batch.parent.mkdir()
        sources = ('research/__init__.py', 'research/catalog_share.py', 'research/catalog_allocation_review.py',
            'research/sql/catalog_otel_requests.sql', 'inner/spec/requirements.json', *execution.REQUIRED_CODE)
        for name in sources:
            target = self.repo / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO / name, target)
        shutil.copytree(REPO / 'research/sharing', self.repo / 'research/sharing')
        self.plan = deepcopy(read(REPO / 'research/protocols/ms1-catalog-comparison-v2.json'))
        self.plan['probe'] = 'artifacts/catalog-pilot/20260920/connection-01'
        self.plan.update(pairs=2, runs_per_condition=2, maximum_runs=4, runs_dir='runs/test-cohort',
            slots=allocation(2, self.plan['randomization_seed']))
        self.plan['execution'] = {'storage': {'basis_verified': True, 'evidence_sha256': 'a' * 64,
            **{k: 100 for k in execution.STORAGE_KEYS}}, 'staging_root': 'artifacts/staging',
            'code_hashes': {n: sha256(self.repo / n) for n in execution.REQUIRED_CODE}, 'github_target_commit': 'b' * 40}
        # The staged code contract includes this fixed requirement version.
        target = self.repo / 'inner/spec/requirements-1.2.0.json'
        shutil.copyfile(REPO / 'inner/spec/requirements-1.2.0.json', target)
        self.plan_path = self.repo / 'research/protocols/fixture.json'
        write_new(self.plan_path, self.plan)
        self.approval = self.repo / 'test-only-approval.json'
        write_new(self.approval, {'authorized': True, 'approved_by': 'user',
            'authorization_reference': 'synthetic fixture, not actual experiment approval',
            'approved_at_utc': '2026-09-22T00:00:00Z', 'plan_sha256': sha256(self.plan_path)})
        self.sent = []
        self.stops = []

    def dispatch(self, plan, case, batch, env, repo):
        self.sent.append(case['run_id'])
        root = batch / case['run_id']
        write_new(root / 'manifest.json', {'run_id': case['run_id'], 'synthetic': True})
        return {'stops': list(self.stops), 'row': {'verdict': 'fail'}, 'cli_exit_code': 0}

    def execute(self, **kwargs):
        return execution.execute(self.plan_path, self.approval, repo=self.repo,
            dispatch=kwargs.pop('dispatch', self.dispatch), verify=lambda *_: {}, **kwargs)

    @property
    def journal(self):
        return self.batch / '_control/journal.jsonl'

    def recovery(self, **updates):
        proof = self.repo / f'proof-{len(list(self.repo.glob("proof-*.json")))}.json'
        write_new(proof, {'synthetic_recovery': True})
        record = {'plan_sha256': sha256(self.plan_path), 'journal_sha256': sha256(self.journal),
            'verified': True, 'owned_resources_reconciled': True, 'api_or_environment_recovered': True,
            'in_flight_processes_stopped': True, 'explanation': 'Synthetic fault recovery',
            'evidence_files': {str(proof): sha256(proof)}, **updates}
        path = self.repo / f'recovery-{proof.name}'
        write_new(path, record)
        return path

    def test_no_approval_or_wrong_plan_never_reaches_dispatch(self):
        with self.assertRaisesRegex(ValueError, 'Separate user'):
            execution.execute(self.plan_path, None, repo=self.repo)
        self.assertFalse(self.batch.exists())
        self.plan['pairs'] = 320
        self.plan_path.write_text(__import__('json').dumps(self.plan), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'bound'):
            self.execute()
        self.assertFalse(self.sent)

    def test_quota_failure_stops_then_resumes_only_unsent_slot(self):
        self.stops = ['authentication_or_quota']
        self.assertEqual(self.execute()['reason'], 'run_fault')
        self.assertEqual(self.execute()['reason'], 'run_fault')
        self.assertEqual(self.sent, [self.plan['slots'][0]['run_id']])
        evidence = self.recovery()
        execution.recover(self.plan_path, evidence, repo=self.repo, verify=lambda *_: {})
        self.stops = []
        result = self.execute()
        self.assertEqual(result['reason'], 'public_review_required')
        self.assertEqual(self.sent, [s['run_id'] for s in self.plan['slots'][:2]])
        self.assertTrue((Path(result['workspace']) / 'public/MANIFEST.json').exists())

    def test_uncertain_dispatch_is_retained_and_never_replayed(self):
        def crash(*args):
            self.sent.append(args[1]['run_id'])
            raise OSError('Simulated lost process result')
        self.assertEqual(self.execute(dispatch=crash)['reason'], 'uncertain_dispatch')
        self.assertEqual(self.execute()['reason'], 'uncertain_dispatch_requires_reconciliation')
        evidence = self.recovery()
        execution.recover(self.plan_path, evidence, repo=self.repo, verify=lambda *_: {})
        self.execute()
        self.assertEqual(self.sent, [s['run_id'] for s in self.plan['slots'][:2]])
        manifest = read(execution.pair_workspace(self.plan, 1, self.repo) / 'public/MANIFEST.json')
        self.assertEqual(manifest['missing_run_directories'], [self.sent[0]])
        data = sharing.extract(execution.pair_workspace(self.plan, 1, self.repo) / 'public')
        self.assertEqual(len(data['runs']), 2)
        self.assertTrue(all(r['requests'] is None for r in data['runs']))

    def test_fresh_disk_check_between_members_and_recovery(self):
        good = {**self.plan['execution']['storage'], 'checked_at_utc': execution.now(), 'free_bytes': 700}
        bad = {**good, 'free_bytes': 699}
        with patch.object(execution, 'storage_record', side_effect=[good, bad]):
            self.assertEqual(self.execute()['reason'], 'storage')
        self.assertEqual(len(self.sent), 1)
        execution.recover(self.plan_path, self.recovery(), repo=self.repo, verify=lambda *_: {})
        self.execute()
        self.assertEqual(len(self.sent), 2)

    def test_recovery_rejects_stale_journal_or_changed_original(self):
        self.stops = ['authentication_or_quota']
        self.execute()
        evidence = self.recovery(journal_sha256='0' * 64)
        with self.assertRaisesRegex(ValueError, 'exact pause'):
            execution.recover(self.plan_path, evidence, repo=self.repo, verify=lambda *_: {})
        evidence = self.recovery()
        (self.batch / self.sent[0] / 'manifest.json').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'Preserved result'):
            execution.recover(self.plan_path, evidence, repo=self.repo, verify=lambda *_: {})
        self.assertEqual(len(self.sent), 1)

    def cleanup_pause(self):
        def dispatch(*args):
            result = self.dispatch(*args)
            root = self.batch / self.sent[-1]
            out = root / 'evaluations/attempt-1-test'
            write_new(out / 'evaluation.json', {'verdict': 'fail', 'original': True})
            write_new(root / 'frozen/source.json', {'original': True})
            write_new(root / 'usage/raw/request.json', {'original': True})
            browser_cleanup.register(out, 'test-instance', 'container', 's2-browser-' + 'a' * 32, 'id')
            with patch.object(runtime, 'docker', side_effect=RuntimeError('injected daemon failure')):
                self.assertFalse(browser_cleanup.cleanup(out)['confirmed'])
            return {**result, 'stops': ['browser_cleanup_failed']}
        self.execute(dispatch=dispatch)
        root = self.batch / self.sent[-1]
        out = root / 'evaluations/attempt-1-test'
        with patch.object(runtime, 'docker', return_value=subprocess.CompletedProcess([], 0, '', '')):
            self.assertTrue(browser_cleanup.cleanup(out)['confirmed'])
        return root, [{'kind': 'browser_cleanup', 'directory': 'evaluations/attempt-1-test'}]

    def test_real_cleanup_receipts_append_then_only_unsent_slot_resumes(self):
        root, operations = self.cleanup_pause()
        seal = self.batch / '_control' / (root.name + '.seal.json')
        old_seal = seal.read_bytes()
        execution.recover(self.plan_path, self.recovery(operations=operations), repo=self.repo, verify=lambda *_: {})
        delta = execution.events(self.journal)[-1]['run_delta']
        index = 'evaluations/attempt-1-test/browser-cleanup-attempts/index.jsonl'
        self.assertGreater(delta['changes'][index]['appended_byte_range'][0], 0)
        self.assertNotEqual(delta['changes'][index]['before']['sha256'], delta['changes'][index]['after']['sha256'])
        self.assertEqual(seal.read_bytes(), old_seal)
        self.execute()
        self.assertEqual(self.sent, [s['run_id'] for s in self.plan['slots'][:2]])

    def test_cleanup_additions_need_declared_operation(self):
        self.cleanup_pause()
        with self.assertRaisesRegex(ValueError, 'Preserved result'):
            execution.recover(self.plan_path, self.recovery(), repo=self.repo, verify=lambda *_: {})

    def test_cleanup_does_not_allow_original_edits_or_unrelated_additions(self):
        root, operations = self.cleanup_pause()
        for name in ('frozen/source.json', 'usage/raw/request.json',
                     'evaluations/attempt-1-test/evaluation.json',
                     'evaluations/attempt-1-test/browser-cleanup-attempts/index.jsonl'):
            with self.subTest(name=name):
                path = root / name
                original = path.read_bytes()
                path.write_bytes(original.replace(b'original', b'modified') if 'index' not in name else b'{}\n' + original)
                with self.assertRaisesRegex(ValueError, 'Preserved result'):
                    execution.recover(self.plan_path, self.recovery(operations=operations), repo=self.repo, verify=lambda *_: {})
                path.write_bytes(original)
        write_new(root / 'evaluations/attempt-1-test/browser-cleanup-attempts/unrelated.json', {})
        with self.assertRaisesRegex(ValueError, 'Unexpected cleanup'):
            execution.recover(self.plan_path, self.recovery(operations=operations), repo=self.repo, verify=lambda *_: {})

    def test_later_recovery_protects_previously_accepted_additions(self):
        root, operations = self.cleanup_pause()
        execution.recover(self.plan_path, self.recovery(operations=operations), repo=self.repo, verify=lambda *_: {})
        delta = execution.events(self.journal)[-1]['run_delta']
        execution.append(self.journal, {'kind': 'pause', 'reason': 'storage'})
        result = root / next(n for n in delta['changes'] if n.endswith('-result.json'))
        old = result.read_bytes()
        result.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'Preserved result'):
            execution.recover(self.plan_path, self.recovery(), repo=self.repo, verify=lambda *_: {})
        result.write_bytes(old)
        execution.recover(self.plan_path, self.recovery(), repo=self.repo, verify=lambda *_: {})

    def evaluation_pause(self):
        def dispatch(*args):
            result = self.dispatch(*args)
            root = self.batch / self.sent[-1]
            write_new(root / 'frozen/source.json', {'original': True})
            artifact = util.artifact_hash(root / 'frozen')
            write_new(root / 'snapshot.json', {'artifact_sha256': artifact})
            write_new(root / 'condition.json', {'evaluation': {'evaluation_version': '1.2.0',
                'spec_sha256': 'a' * 64, 'evaluator_sha256': 'b' * 64}})
            self.evaluation_record(root, 1)
            return {**result, 'stops': ['evaluation_recovery_required']}
        self.execute(dispatch=dispatch)
        return self.batch / self.sent[-1]

    def evaluation_record(self, root, sequence):
        directory = f'evaluations/fault-{sequence:03d}-synthetic'
        record = {'run_id': root.name, 'sequence': sequence, 'directory': directory,
            'scoring_state': 'evaluator_fault', 'evaluation_version': '1.2.0',
            'spec_sha256': 'a' * 64, 'evaluator_sha256': 'b' * 64,
            'artifact_sha256_outer': util.artifact_hash(root / 'frozen')}
        write_new(root / directory / 'evaluation.json', {'synthetic': True})
        evaluate._write_record(root / directory, record)
        evaluate._append_index(root, record)
        write_new(root / f'evaluation-work/{sequence:03d}/evidence.json', {'synthetic': True})
        log = root / f'evidence/scoring-{sequence:03d}-stdout.log'
        log.parent.mkdir(exist_ok=True)
        log.write_text('synthetic subprocess output')
        return {'kind': 'evaluation', 'directory': directory, 'sequence': sequence,
            'authorization_reference': 'Synthetic record writer only; no real evaluation authorized'}

    def test_evaluation_recovery_keeps_original_attempt_and_append_prefix(self):
        root = self.evaluation_pause()
        original = sharing.inventory(root)
        operation = self.evaluation_record(root, 2)
        execution.recover(self.plan_path, self.recovery(operations=[operation]), repo=self.repo, verify=lambda *_: {})
        for name, item in original.items():
            if name != 'evaluations/index.jsonl':
                self.assertEqual(sharing.inventory(root)[name], item)
        self.execute()
        self.assertEqual(self.sent, [s['run_id'] for s in self.plan['slots'][:2]])

    def test_evaluation_recovery_refuses_rewritten_index_or_changed_conditions(self):
        root = self.evaluation_pause()
        operation = self.evaluation_record(root, 2)
        index = root / 'evaluations/index.jsonl'
        original = index.read_bytes()
        index.write_bytes(original.replace(b'evaluator_fault', b'scored', 1))
        with self.assertRaisesRegex(ValueError, 'append-only'):
            execution.recover(self.plan_path, self.recovery(operations=[operation]), repo=self.repo, verify=lambda *_: {})
        index.write_bytes(original)
        record_path = root / operation['directory'] / 'record.json'
        record_path.write_text(record_path.read_text().replace('b' * 64, 'c' * 64))
        with self.assertRaisesRegex(ValueError, 'fixed artifact'):
            execution.recover(self.plan_path, self.recovery(operations=[operation]), repo=self.repo, verify=lambda *_: {})

    def test_evaluation_recovery_retains_two_rescore_limit(self):
        root = self.evaluation_pause()
        for sequence in (2, 3):
            operation = self.evaluation_record(root, sequence)
            execution.recover(self.plan_path, self.recovery(operations=[operation]), repo=self.repo, verify=lambda *_: {})
            execution.append(self.journal, {'kind': 'pause', 'reason': 'run_fault'})
        operation = self.evaluation_record(root, 4)
        with self.assertRaisesRegex(ValueError, 'two-rescore'):
            execution.recover(self.plan_path, self.recovery(operations=[operation]), repo=self.repo, verify=lambda *_: {})

    def test_concurrent_driver_and_incomplete_journal_refused(self):
        with execution.exclusive(self.batch / '_control'):
            with self.assertRaises(OSError):
                self.execute()
        self.execute()
        with self.journal.open('ab') as stream:
            stream.write(b'{"kind":"dispatch"')
        with self.assertRaisesRegex(ValueError, 'Incomplete journal'):
            self.execute()
        self.assertEqual(len(self.sent), 2)

    def test_retention_refuses_live_or_unclean_run_before_touching_files(self):
        root = self.batch / 'incomplete-run'
        root.mkdir(parents=True)
        for manifest in ({'stop_confirmed': False, 'network_cleanup': {'confirmed': True}},
                         {'stop_confirmed': True, 'network_cleanup': {'confirmed': False}}):
            (root / 'manifest.json').write_text(__import__('json').dumps(manifest), encoding='utf-8')
            with patch.object(storage, 'compress_tree') as compress, patch.object(storage.preserve, 'verify') as verify:
                with self.assertRaisesRegex(ValueError, 'stopped'):
                    storage.retain_completed(self.batch, root.name)
                compress.assert_not_called()
                verify.assert_not_called()

    def test_retention_rejects_foreign_tree_and_detects_byte_changes(self):
        root = self.batch / 'stopped-run'
        root.mkdir(parents=True)
        payload = root / 'payload.txt'
        payload.write_text('original bytes')
        with patch.object(storage.subprocess, 'run') as command:
            with self.assertRaisesRegex(ValueError, 'owned'):
                storage.compress_tree(self.repo, self.batch)
            command.assert_not_called()
        def damaged_compression(*args, **kwargs):
            payload.write_text('unexpected byte change')
        with patch.object(storage, 'stored_bytes', side_effect=lambda p: Path(p).stat().st_size), \
                patch.object(storage.subprocess, 'run', side_effect=damaged_compression):
            with self.assertRaisesRegex(ValueError, 'bytes changed'):
                storage.compress_tree(root, self.batch)

    def review(self, workspace):
        path = workspace / 'review.json'
        write_new(path, {'publication_approved': True, 'reviewed_inventory': sharing.inventory(workspace / 'public'),
            'scope': 'Synthetic test material only; no actual future Run publication approved.'})
        return path

    def transport(self, package, tag, target):
        remote = self.repo / ('remote-' + tag)
        remote.mkdir()
        asset = read(package / 'pair.manifest.json')
        names = [p['name'] for p in asset['parts']] + ['pair.manifest.json', 'public-review.json', 'scan.json']
        for name in names:
            shutil.copyfile(package / name, remote / name)
        return {name: str(remote / name) for name in names}

    def test_pair_publication_restore_cleanup_is_required_before_next_pair(self):
        self.execute()
        self.assertEqual(self.execute()['reason'], 'pair_publication_required')
        self.assertEqual(len(self.sent), 2)
        original = {name: sharing.inventory(self.batch / name) for name in self.sent}
        workspace = execution.pair_workspace(self.plan, 1, self.repo)
        with patch.object(sharing, 'known_secret', return_value=b'synthetic-unlogged-key'):
            result = execution.share_pair(self.plan_path, 1, self.review(workspace), repo=self.repo,
                transfer=self.transport, fetch=lambda source, target: shutil.copyfile(source, target))
        self.assertTrue(result['originals_unchanged'])
        self.assertFalse((workspace / 'public').exists())
        self.assertFalse((workspace / 'package').exists())
        self.assertTrue((workspace / 'delivery-001.json').exists())
        delivered = read(workspace / 'delivery-001.json')
        plan_entry = next(item for item in delivered['public_manifest']['files'] if item['path'] == 'research/protocols/fixture.json')
        self.assertEqual(plan_entry['sha256'], sha256(self.plan_path))
        for name, saved in original.items():
            self.assertEqual(sharing.inventory(self.batch / name), saved)
        self.execute()
        self.assertEqual(self.sent, [s['run_id'] for s in self.plan['slots']])

    def finish_pair(self, workspace, review=None):
        review = review or self.review(workspace)
        with patch.object(sharing, 'known_secret', return_value=b'synthetic-unlogged-key'):
            execution.share_pair(self.plan_path, 1, review, repo=self.repo,
                transfer=self.transport, fetch=lambda source, target: shutil.copyfile(source, target))
        self.execute()
        self.assertEqual(self.sent, [s['run_id'] for s in self.plan['slots']])

    def test_interrupted_public_copy_is_preserved_and_same_pair_can_finish(self):
        calls = []
        original_copy = sharing.public_bytes
        def interrupted(source):
            calls.append(source)
            if len(calls) == 2:
                raise OSError('injected copy interruption before manifest')
            return original_copy(source)
        with patch.object(sharing, 'public_bytes', side_effect=interrupted):
            with self.assertRaisesRegex(OSError, 'copy interruption'):
                self.execute()
        workspace = execution.pair_workspace(self.plan, 1, self.repo)
        partial = sharing.inventory(workspace)
        self.assertNotIn('public/MANIFEST.json', partial)
        originals = {n: sharing.inventory(self.batch / n) for n in self.sent}
        self.assertEqual(self.execute()['reason'], 'pair_publication_required')
        self.assertEqual(len(self.sent), 2)
        retained = next(p for p in workspace.parent.glob('pair-001.incomplete-*') if p.is_dir())
        self.assertEqual(sharing.inventory(retained), partial)
        receipt = read(retained.with_name(retained.name + '.json'))
        self.assertEqual(receipt['files'], partial)
        self.assertEqual(receipt['operation'], 'stage')
        self.finish_pair(workspace)
        self.assertTrue(retained.exists())
        for n, saved in originals.items():
            self.assertEqual(sharing.inventory(self.batch / n), saved)

    def test_failed_scan_is_retained_then_same_review_retries_without_dispatch(self):
        self.execute()
        workspace = execution.pair_workspace(self.plan, 1, self.repo)
        review = self.review(workspace)
        originals = {n: sharing.inventory(self.batch / n) for n in self.sent}
        with patch.object(sharing, 'known_secret', return_value=None), patch.object(delivery, 'publish') as publish:
            with self.assertRaisesRegex(ValueError, 'scan failed'):
                execution.share_pair(self.plan_path, 1, review, repo=self.repo, transfer=publish)
            publish.assert_not_called()
        partial = sharing.inventory(workspace / 'package')
        self.assertFalse(read(workspace / 'package/scan.json')['pass'])
        self.assertNotIn('pair.manifest.json', partial)
        self.finish_pair(workspace, review)
        retained = next(p for p in workspace.glob('package.incomplete-*') if p.is_dir())
        self.assertEqual(sharing.inventory(retained), partial)
        for n, saved in originals.items():
            self.assertEqual(sharing.inventory(self.batch / n), saved)

    def test_interrupted_zip_is_retained_then_same_pair_finishes(self):
        self.execute()
        workspace = execution.pair_workspace(self.plan, 1, self.repo)
        review = self.review(workspace)
        original_write = delivery.zipfile.ZipFile.write
        calls = []
        def interrupted(archive, *args, **kwargs):
            calls.append(args)
            if len(calls) == 2:
                raise OSError('injected ZIP interruption')
            return original_write(archive, *args, **kwargs)
        with patch.object(sharing, 'known_secret', return_value=b'synthetic-unlogged-key'), \
                patch.object(delivery.zipfile.ZipFile, 'write', interrupted), patch.object(delivery, 'publish') as publish:
            with self.assertRaisesRegex(OSError, 'ZIP interruption'):
                execution.share_pair(self.plan_path, 1, review, repo=self.repo, transfer=publish)
            publish.assert_not_called()
        partial = sharing.inventory(workspace / 'package')
        self.assertIn('pair.zip', partial)
        self.assertNotIn('pair.manifest.json', partial)
        self.assertEqual(self.execute()['reason'], 'pair_publication_required')
        self.assertEqual(len(self.sent), 2)
        self.finish_pair(workspace, review)
        retained = next(p for p in workspace.glob('package.incomplete-*') if p.is_dir())
        self.assertEqual(sharing.inventory(retained), partial)

    def test_truncated_completion_manifest_is_quarantined_on_retry(self):
        self.execute()
        workspace = execution.pair_workspace(self.plan, 1, self.repo)
        review = self.review(workspace)
        package = workspace / 'package'
        package.mkdir()
        (package / 'pair.manifest.json').write_text('{"incomplete":')
        self.finish_pair(workspace, review)
        retained = next(p for p in workspace.glob('package.incomplete-*') if p.is_dir())
        self.assertEqual((retained / 'pair.manifest.json').read_text(), '{"incomplete":')

    def test_completed_package_is_verified_before_reuse_and_upload(self):
        self.execute()
        workspace = execution.pair_workspace(self.plan, 1, self.repo)
        review = self.review(workspace)
        with patch.object(sharing, 'known_secret', return_value=b'synthetic-unlogged-key'):
            asset = delivery.package(workspace / 'public', workspace / 'package', review)
        with patch.object(delivery, 'scan', side_effect=AssertionError('Completed package should be reused')):
            self.assertEqual(delivery.package(workspace / 'public', workspace / 'package', review), asset)
        (workspace / 'package/pair.zip').write_bytes(b'corrupt')
        with patch.object(delivery, 'publish') as publish:
            with self.assertRaisesRegex(ValueError, 'Local package changed'):
                execution.share_pair(self.plan_path, 1, review, repo=self.repo, transfer=publish)
            publish.assert_not_called()
        self.assertFalse(list(workspace.glob('package.incomplete-*')))
        self.assertEqual(len(self.sent), 2)

    def test_incomplete_package_requires_full_creation_space_before_retry(self):
        self.execute()
        workspace = execution.pair_workspace(self.plan, 1, self.repo)
        review = self.review(workspace)
        write_new(workspace / 'package/scan.json', {'pass': False})
        size = sum(item['bytes'] for item in sharing.inventory(workspace / 'public').values())
        zip_bound = size + size // 100 + 1024 * 1024
        disk = shutil.disk_usage(workspace)._replace(free=size + 3 * zip_bound)
        with patch.object(shutil, 'disk_usage', return_value=disk), patch.object(delivery, 'publish') as publish:
            with self.assertRaisesRegex(ValueError, 'Insufficient physical space'):
                execution.share_pair(self.plan_path, 1, review, repo=self.repo, transfer=publish)
            publish.assert_not_called()
        self.assertEqual(len(self.sent), 2)
        self.assertFalse(read(workspace / 'package/scan.json')['pass'])

    def test_completed_public_copy_requires_exact_inventory_and_unchanged_originals(self):
        self.execute()
        workspace = execution.pair_workspace(self.plan, 1, self.repo)
        self.assertEqual(execution.prepare_pair(self.plan_path, 1, self.repo), workspace)
        write_new(workspace / 'public/unexpected.json', {})
        with self.assertRaisesRegex(ValueError, 'exactly'):
            execution.prepare_pair(self.plan_path, 1, self.repo)
        (workspace / 'public/unexpected.json').unlink()
        (self.batch / self.sent[0] / 'manifest.json').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'Original pair changed'):
            execution.prepare_pair(self.plan_path, 1, self.repo)

    def test_review_change_or_corrupt_download_cannot_release_next_pair(self):
        self.execute()
        workspace = execution.pair_workspace(self.plan, 1, self.repo)
        review = self.review(workspace)
        (workspace / 'public/unreviewed.txt').write_text('extra')
        with patch.object(sharing, 'known_secret', return_value=b'synthetic-unlogged-key'):
            with self.assertRaisesRegex(ValueError, 'exactly'):
                execution.share_pair(self.plan_path, 1, review, repo=self.repo, transfer=self.transport)
        (workspace / 'public/unreviewed.txt').unlink()
        def corrupt(source, target):
            Path(target).write_bytes(b'bad download')
        with patch.object(sharing, 'known_secret', return_value=b'synthetic-unlogged-key'):
            with self.assertRaisesRegex(ValueError, 'Downloaded part'):
                execution.share_pair(self.plan_path, 1, review, repo=self.repo, transfer=self.transport, fetch=corrupt)
        self.assertTrue((workspace / 'public').exists())
        self.assertEqual(self.execute()['reason'], 'pair_publication_required')
        self.assertEqual(len(self.sent), 2)

    def test_multipart_roundtrip_and_foreign_cleanup_rejection(self):
        self.execute()
        workspace = execution.pair_workspace(self.plan, 1, self.repo)
        review = self.review(workspace)
        with patch.object(sharing, 'known_secret', return_value=b'synthetic-unlogged-key'):
            asset = delivery.package(workspace / 'public', workspace / 'package', review, part_bytes=2048)
        self.assertGreater(len(asset['parts']), 1)
        urls = self.transport(workspace / 'package', 'multipart', 'unused')
        result = delivery.roundtrip(asset, urls, workspace / 'roundtrip-001', fetch=lambda s,t: shutil.copyfile(s,t))
        self.assertTrue(result['hashes_match'])
        self.assertEqual(len(result['metadata_hashes']), 3)
        with self.assertRaisesRegex(ValueError, 'inside'):
            delivery.cleanup(self.repo, self.repo / 'artifacts/staging', result)
        self.assertTrue(self.batch.exists())

    def test_long_windows_evaluation_path_is_not_reported_missing(self):
        root = self.repo / ('nested-' + 'x' * 65) / ('run-' + 'y' * 65)
        self.assertTrue(root.resolve().is_relative_to(self.repo.resolve()))
        self.addCleanup(shutil.rmtree, sharing.native(root))
        directory = 'evaluations/evaluator_fault-001-' + 'z' * 64
        evaluation = sharing.native(root / directory / 'evaluation.json')
        evaluation.parent.mkdir(parents=True)
        write_new(evaluation, {'verdict': 'error'})
        index = sharing.native(root / 'evaluations/index.jsonl')
        index.write_text(__import__('json').dumps({'directory': directory, 'adopted': False}) + '\n', encoding='utf-8')
        self.assertGreater(len(str(root / directory / 'evaluation.json')), 260)
        self.assertEqual(len(sharing.saved_attempts(root)), 1)

    def test_publish_reconciles_existing_assets_and_refuses_mismatch(self):
        self.execute()
        workspace = execution.pair_workspace(self.plan, 1, self.repo)
        with patch.object(sharing, 'known_secret', return_value=b'synthetic-unlogged-key'):
            asset = delivery.package(workspace / 'public', workspace / 'package', self.review(workspace))
        names = [p['name'] for p in asset['parts']] + ['pair.manifest.json', 'public-review.json', 'scan.json']
        remote = {'draft': False, 'assets': [{'name': n, 'size': (workspace / 'package' / n).stat().st_size,
            'digest': 'sha256:' + sha256(workspace / 'package' / n), 'browser_download_url': 'synthetic/' + n} for n in names]}
        with patch.object(delivery, 'release', return_value=remote), patch.object(delivery, 'gh') as mutation:
            delivery.publish(workspace / 'package', 'catalog-comparison-v2-pair-001', 'b' * 40)
            mutation.assert_not_called()
            remote['assets'][0]['digest'] = 'sha256:' + '0' * 64
            with self.assertRaisesRegex(ValueError, 'remote asset'):
                delivery.publish(workspace / 'package', 'catalog-comparison-v2-pair-001', 'b' * 40)
            mutation.assert_not_called()

    def test_verified_delivery_survives_interruption_after_cleanup(self):
        self.execute()
        workspace = execution.pair_workspace(self.plan, 1, self.repo)
        review = self.review(workspace)
        original_append = execution.append
        def lose_checkpoint(path, event):
            if event['kind'] == 'pair_shared':
                raise OSError('Simulated interruption after verified cleanup')
            return original_append(path, event)
        with patch.object(sharing, 'known_secret', return_value=b'synthetic-unlogged-key'), patch.object(execution, 'append', side_effect=lose_checkpoint):
            with self.assertRaisesRegex(OSError, 'interruption'):
                execution.share_pair(self.plan_path, 1, review, repo=self.repo,
                    transfer=self.transport, fetch=lambda s,t: shutil.copyfile(s,t))
        self.assertFalse((workspace / 'public').exists())
        with patch.object(delivery, 'gh', side_effect=AssertionError('No second publication')):
            result = execution.share_pair(self.plan_path, 1, review, repo=self.repo)
        self.assertTrue(result['recovered_finalization'])
        self.execute()
        self.assertEqual(len(self.sent), 4)

    def test_uncertain_upload_acknowledgment_is_read_back_without_duplicate_write(self):
        self.execute()
        workspace = execution.pair_workspace(self.plan, 1, self.repo)
        with patch.object(sharing, 'known_secret', return_value=b'synthetic-unlogged-key'):
            delivery.package(workspace / 'public', workspace / 'package', self.review(workspace))
        remote = {'draft': False, 'assets': []}
        uploads = []
        def write_remote(*args):
            self.assertEqual(args[:2], ('release', 'upload'))
            source = Path(args[3])
            uploads.append(source.name)
            remote['assets'].append({'name': source.name, 'size': source.stat().st_size,
                'digest': 'sha256:' + sha256(source), 'browser_download_url': 'synthetic/' + source.name})
            if len(uploads) == 1:
                raise RuntimeError('Remote wrote the asset but acknowledgment was lost')
            return ''
        with patch.object(delivery, 'release', return_value=remote), patch.object(delivery, 'gh', side_effect=write_remote):
            with self.assertRaisesRegex(RuntimeError, 'acknowledgment'):
                delivery.publish(workspace / 'package', 'catalog-comparison-v2-pair-001', 'b' * 40)
            delivery.publish(workspace / 'package', 'catalog-comparison-v2-pair-001', 'b' * 40)
        self.assertEqual(len(uploads), 4)
        self.assertEqual(len(set(uploads)), 4)


if __name__ == '__main__':
    unittest.main()
