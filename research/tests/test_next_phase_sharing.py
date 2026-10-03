from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from outer.harness import util
from research import next_phase_sharing as sharing
from research import next_phase, pair_execution


class SharingRecoveryTests(unittest.TestCase):
    def test_bundle_specific_release_tags_separate_technical_and_research(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bundle.json'
            util.write_new_json(path, {'identity': 1})
            research = {'kind': 'continuity_prospective_bundle', 'cohort': 'runs/source-info-v2'}
            technical = {'kind': 'continuity_sharing_technical_fixture', 'cohort': 'runs/_technical-sharing-test'}
            first = sharing.release_prefix(path, research)
            self.assertTrue(first.startswith('source-info-v2-'))
            self.assertNotEqual(first, sharing.release_prefix(path, technical))
            path.write_text('{"identity":2}', encoding='utf-8')
            self.assertNotEqual(first, sharing.release_prefix(path, research))
            technical['cohort'] = 'runs/source-info-v2'
            with self.assertRaises(ValueError): sharing.release_prefix(path, technical)

    def test_normal_stage_package_restore_offline_extract_and_owned_cleanup(self):
        """Real local byte pipeline; only the external transport is simulated."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = next_phase.REPO
            names = ['research/__init__.py', 'research/catalog_allocation_review.py',
                'research/catalog_share.py', 'research/sql/catalog_otel_requests.sql', next_phase.PLAN,
                'research/tasks/candidate-register.json',
                'research/tasks/music-store-continuity/public-request.txt',
                'outer/profiles/tasks/MS1-CONT-A.json',
                'research/sharing/CONTINUITY-README.md', 'research/sharing/THIRD-PARTY-NOTICES.md',
                'research/sharing/LICENSES/MS-PL.txt', 'research/sharing/LICENSES/OpenCode-MIT.txt']
            profile = util.read_json(source / 'outer/profiles/tasks/MS1-CONT-A.json')
            names.append(profile['evaluation']['spec_path'])
            for name in names:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source / name, target)
            plan = util.read_json(root / next_phase.PLAN)
            pair = next(p for p in next_phase.assignments(plan) if p['task'] == 'MS1-CONT-A')
            pair = {**pair, 'pair': 1, 'cases': [{**c, 'pair': 1} for c in pair['cases']]}
            bundle_path = root / 'bundle.json'
            util.write_new_json(bundle_path, {'kind': 'continuity_sharing_technical_fixture',
                'plan': plan, 'cohort': 'runs/_technical-sharing-test',
                'assignments': [pair], 'source_commit': 'explicit-synthetic-fixture'})
            batch = root / 'runs/_technical-sharing-test'
            def prepare(binding):
                manifest = {**binding, 'schema_version': 1, 'synthetic': True,
                    'prompt_sha256': 'fixture-input', 'condition_sha256': 'fixture-condition',
                    'model_called': False}
                util.write_new_json(batch / binding['run_id'] / 'manifest.json', manifest)
                util.write_new_json(batch / binding['run_id'] / 'usage/normalized.json',
                    {'run_id': binding['run_id'], 'run_instance_id': binding['run_instance_id'],
                     'usage_complete': False, 'total_tokens': None, 'fixture': True})
                static = batch / binding['run_id'] / 'frozen/App_Data'
                static.mkdir(parents=True)
                for name in ('submitted.sqlite3', 'submitted.db'):
                    (static / name).write_bytes(b'independent static database fixture')
                return manifest
            def implement(repo, batch, rid):
                manifest = util.read_json(batch / rid / 'manifest.json')
                return {'run_id': rid, 'run_instance_id': manifest['run_instance_id'],
                    'stop_confirmed': True, 'raw': {}, 'fixture': True, 'model_called': False}
            def postprocess(repo, batch, rid, archive):
                return {'run_id': rid, 'scoring': {'state': 'scored'},
                    'verdict': 'blocked', 'quality': None, 'fixture': True}
            dispatch = {'plan_sha256': util.sha256_file(bundle_path), 'cohort': 'runs/_technical-sharing-test',
                'runtime': 'explicit-no-worker-fixture'}
            pair_execution.execute_pair(dispatch, pair['cases'], batch, repo=root,
                prepare=prepare, implement=implement, postprocess=postprocess)
            work = root / 'artifacts/continuity-sharing-v1/technical-fixture'
            sharing.stage(root, bundle_path, 1, work)
            staged = util.read_json(work / 'public/MANIFEST.json')
            omitted = [entry for entry in staged['excluded'] if
                entry['path'].endswith(('submitted.sqlite3', 'submitted.db'))]
            self.assertEqual(len(omitted), 4)
            for entry in omitted:
                source = root / entry['path']
                self.assertTrue(source.is_file())
                self.assertEqual(entry['sha256'], util.sha256_file(source))
                self.assertFalse((work / 'public' / entry['path']).exists())
                self.assertIn('does not provide runnable application', entry['reason'])
            original = {c['run_id']: sharing.catalog_share.inventory(batch / c['run_id']) for c in pair['cases']}
            review = work / 'exact-review.json'
            util.write_new_json(review, {'publication_approved': True,
                'reviewer': 'automated synthetic transport test, not human acceptance',
                'reviewed_inventory': sharing.catalog_share.inventory(work / 'public')})
            remote = root / 'simulated-remote'
            remote.mkdir()
            def transfer(package, tag, commit):
                asset = sharing.catalog_delivery.verify_package(package)
                names = [p['name'] for p in asset['parts']] + ['pair.manifest.json', 'public-review.json', 'scan.json']
                for name in names: shutil.copyfile(package / name, remote / name)
                return {name: 'https://github.com/fukuda-yuki/sample2/releases/download/' + tag + '/' + name for name in names}
            def fetch(url, target):
                shutil.copyfile(remote / url.rsplit('/', 1)[-1], target)
            # This canary is synthetic, never a call to the real credential path.
            with patch('research.catalog_share.known_secret', return_value=b'explicit-synthetic-scan-canary'):
                result = sharing.share(root, bundle_path, 1, work, review, transfer=transfer, fetch=fetch)
            self.assertTrue(result['originals_unchanged'])
            extracted = util.read_json(work / 'before-upload-extraction.json')
            self.assertEqual(len(extracted['runs']), 2)
            self.assertTrue(all(r['requests'] is None and r['sqlite'] is None for r in extracted['runs']))
            self.assertFalse(extracted['model_called'])
            self.assertFalse(extracted['evaluator_called'])
            self.assertEqual(extracted['human_review'], 'not_run')
            self.assertFalse((work / 'public').exists())
            self.assertFalse((work / 'package').exists())
            for rid, hashes in original.items(): self.assertEqual(sharing.catalog_share.inventory(batch / rid), hashes)
            self.assertIn(1, pair_execution.state(batch / '_control/pair-journal.jsonl')['gates'])
            stages = util.read_lines(work / 'public-gate-timing.jsonl')
            completed = [e for e in stages if e['event'] == 'stage_completed']
            self.assertEqual([e['stage'] for e in completed], ['package_including_compression',
                'before_upload_offline_extract', 'publication_and_remote_hash_check',
                'download_restore_offline_extract', 'owned_copy_cleanup'])
            self.assertTrue(all(e['duration_seconds'] >= 0 and e['plan_sha256'] == dispatch['plan_sha256'] for e in completed))

    def fixture(self, root):
        work = root / 'artifacts/continuity-sharing-v1/pair-001'
        work.mkdir(parents=True)
        bundle, review = root / 'bundle.json', root / 'review.json'
        util.write_new_json(bundle, {'fixed': True})
        util.write_new_json(review, {'publication_approved': True})
        evidence = work / 'roundtrip-bound-001.json'
        util.write_new_json(evidence, {'package_sha256': 'package', 'hashes_match': True,
            'extraction_sockets_blocked': True, 'workspace': str(work / 'roundtrip-001')})
        saved = work / 'finalization.json'
        util.write_new_json(saved, {'pair': 1, 'plan_sha256': util.sha256_file(bundle),
            'cohort': 'runs/continuity-v1', 'review_sha256': util.sha256_file(review),
            'run_instances': {'run': 'instance'}, 'attempt': 1,
            'original_inventory': {'run': {}}, 'package_sha256': 'package',
            'roundtrip_receipt': str(evidence),
            'evidence_files': {str(evidence): util.sha256_file(evidence)}})
        context = ({'cohort': 'runs/continuity-v1'}, root / 'runs/continuity-v1',
            {'gates': {}}, {}, [{'run_id': 'run', 'run_instance_id': 'instance'}])
        return work, bundle, review, saved, evidence, context

    def test_cleanup_completed_before_journal_write_resumes_without_transfer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            work, bundle, review, saved, evidence, context = self.fixture(root)
            cleanup = {'cleanup_completed': True, 'targets': [], 'original_runs_deleted': False}
            with patch.object(sharing, 'pair_context', return_value=context), patch.object(sharing.catalog_share, 'inventory', return_value={}), patch.object(sharing.catalog_delivery, 'cleanup', return_value=cleanup) as clean, patch.object(sharing.pair_execution, 'record_pair_gate', side_effect=[RuntimeError('crash after owned cleanup'), None]) as gate, patch.object(sharing.catalog_delivery, 'publish') as publish:
                with self.assertRaises(RuntimeError): sharing.finish(root, bundle, 1, work, review, saved)
                result = sharing.share(root, bundle, 1, work, review)
                self.assertEqual(result['status'], 'shared_downloaded_restored_extracted_cleaned')
                self.assertEqual(clean.call_count, 1)
                self.assertEqual(gate.call_count, 2)
                publish.assert_not_called()

    def test_changed_retained_receipt_cannot_complete_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            work, bundle, review, saved, evidence, context = self.fixture(root)
            evidence.write_text('{}', encoding='utf-8')
            with patch.object(sharing, 'pair_context', return_value=context), patch.object(sharing.pair_execution, 'record_pair_gate') as gate:
                with self.assertRaises(ValueError): sharing.finish(root, bundle, 1, work, review, saved)
                gate.assert_not_called()


if __name__ == '__main__': unittest.main()
