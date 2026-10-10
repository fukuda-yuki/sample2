"""Finite preparation boundaries; Docker operations are mocked, not host proof."""
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from outer.harness import util
from research import repaired_runtime as subject


class RepairedRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / 'repo'
        self.repo.mkdir()
        self.family = subject.FAMILIES['music']
        self.make_fixture()

    def write(self, relative, value):
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(value, dict):
            path.write_text(json.dumps(value), encoding='utf-8')
        else:
            path.write_text(value, encoding='utf-8')
        return path

    def make_fixture(self):
        family = self.family
        self.task_id = family['tasks'][0]
        self.runtime_id = family['runtime_id']
        self.commit = 'c' * 40
        self.profile = dict(subject.FIXED_RUNTIME, id=self.runtime_id, artifact_namespace=family['namespace'])
        self.write('outer/profiles/runtimes/' + self.runtime_id + '.json', self.profile)
        self.write('outer/harness/gateway.py', 'gateway')
        self.write('research/repaired_runtime.py', 'fixture helper')
        source_name = 'inner/evaluator/' + family['project'] + '/Program.cs'
        project_name = 'inner/evaluator/' + family['project'] + '/' + family['project'] + '.csproj'
        self.write(source_name, 'source')
        self.write(project_name, 'project')
        self.write('inner/spec/revised.json', '{}')
        self.write('artifacts/sources/' + self.commit + '/source.txt', 'upstream')
        source_root = self.repo / 'artifacts/sources' / self.commit
        self.write('artifacts/sources/' + self.commit + '.json', {'files': util.tree_hashes(source_root)})
        self.write('artifacts/assets/evaluation/catalog.json', '{}')
        self.write('artifacts/assets/inputs/legacy-source/source.txt', 'overlay')
        self.write('artifacts/assets/inputs/existing-business/initial.sqlite', 'raw database')
        asset_files = {name: entry['sha256'] for name, entry in util.tree_hashes(self.repo / 'artifacts/assets').items()
                       if name != 'preparation.json'}
        self.write('artifacts/assets/preparation.json', {'task_id': self.task_id,
            'base_source_commit': self.commit, 'files': asset_files,
            'public_request_sha256': util.sha256_bytes(b'public request')})
        self.task = {'task_id': self.task_id, 'canonical_task_id': self.task_id,
            'revision_id': 'evaluators-20261006', 'environment': {'sdk': '8.0.425'},
            'migration_request': 'public request', 'start_state': {'source_commit': self.commit},
            'evaluation': {'assembly': family['assembly'], 'evaluation_version': family['version'],
                'project': family['project'] + '/' + family['project'] + '.csproj',
                'catalog_path': 'artifacts/assets/evaluation/catalog.json',
                'spec_path': 'inner/spec/revised.json',
                'spec_sha256': util.sha256_file(self.repo / 'inner/spec/revised.json')}}
        self.write('outer/profiles/task-revisions/evaluators-20261006/' + self.task_id + '.json', self.task)
        self.bundle = self.base / 'accepted' / family['project']
        self.bundle.mkdir(parents=True)
        (self.bundle / family['assembly']).write_bytes(b'accepted assembly fixture')
        (self.bundle / 'dependency.dll').write_bytes(b'unchanged dependency')
        # Production has immutable eb627/ff09; only fixture hash is substituted.
        self.family = dict(family, tasks=(self.task_id,), assembly_sha256=util.sha256_file(self.bundle / family['assembly']))
        self.receipt = {'evaluation_version': family['version'], 'sdk': '8.0.425',
            'source_commit': 'a' * 40, 'source_worktree_clean_at_start': False,
            'commands': [{'actual': 'accepted original compile path'}],
            'source_files': [{'path': name, 'sha256': util.sha256_file(self.repo / name)}
                             for name in (source_name, project_name)],
            'deployable_files': [{'path': name, **entry} for name, entry in util.tree_hashes(self.bundle).items()]}
        self.receipt_path = self.base / 'receipt.json'
        self.receipt_path.write_text(json.dumps(self.receipt), encoding='utf-8')
        self.old = {'versions': {'dotnet': '8.0.425', 'opencode': '1.17.11'},
            'controller_files': {'gateway.py': util.sha256_file(self.repo / 'outer/harness/gateway.py')},
            'images': {key: 'sha256:' + digit * 64 for key, digit in [('worker', '1'), ('evaluator', '2'), ('gateway', '3')]},
            'evaluator_build': {'source_commit': 'b' * 40, 'command': 'old SDK image build'}}
        self.old_path = self.base / 'old-lock.json'
        self.old_path.write_text(json.dumps(self.old), encoding='utf-8')
        self.options = {'task_id': self.task_id, 'task_revision': 'evaluators-20261006',
            'runtime_id': self.runtime_id, 'prior_lock': self.old_path,
            'prior_lock_sha256': util.sha256_file(self.old_path), 'accepted_bundle': self.bundle,
            'accepted_receipt': self.receipt_path, 'accepted_receipt_sha256': util.sha256_file(self.receipt_path),
            'controller_source_commit': self.commit}
        self.root = self.repo / 'artifacts/runtime' / family['namespace']

    def prepare(self, *, image=None, docker=None, git=None):
        def version(*args):
            return SimpleNamespace(stdout='8.0.425' if args[-2] == 'dotnet' else '1.17.11')
        def git_result(repo, *args):
            return self.commit if args == ('rev-parse', 'HEAD') else ''
        with patch.object(subject, 'FAMILIES', {'fixture': self.family}), \
                patch.object(subject, '_git', side_effect=git or git_result), \
                patch.object(subject, '_committed_files') as committed, \
                patch.object(subject.runtime, 'image_id', side_effect=image or (lambda value: value)), \
                patch.object(subject.runtime, 'docker', side_effect=docker or version) as probe:
            result = subject.prepare_repaired_runtime(self.repo, **self.options)
            self.assertEqual(committed.call_count, 2)
            for call in probe.call_args_list:
                self.assertEqual(call.args[:4], ('run', '--rm', '--network', 'none'))
            return result

    def reject(self, **mocks):
        with self.assertRaises((ValueError, FileExistsError)):
            self.prepare(**mocks)
        self.assertFalse(self.root.exists())

    def validate(self, lock, *, dirty=False):
        with patch.object(subject, 'FAMILIES', {'fixture': self.family}), \
                patch.object(subject, '_git', return_value=' M file' if dirty else ''), \
                patch.object(subject, '_committed_files'):
            return subject.validate_repaired_runtime_binding(self.repo, lock)

    def test_valid_rebind_preserves_original_false_clean_fact_and_current_commit(self):
        before = util.tree_hashes(self.bundle)
        lock = self.prepare()
        self.assertFalse(lock['evaluator_build']['clean_worktree'])
        self.assertTrue(lock['controller_clean_worktree'])
        self.assertEqual(lock['controller_source_commit'], self.commit)
        self.assertEqual(lock['evaluator_build']['source_commit'], 'a' * 40)
        self.assertEqual(lock['image_reuse']['prior_evaluator_build'], self.old['evaluator_build'])
        self.assertFalse(lock['image_reuse']['image_embedded_evaluator_used_for_scoring'])
        self.assertEqual(before, util.tree_hashes(self.bundle))
        self.assertEqual(lock, util.read_json(self.root / 'lock.json'))
        self.assertTrue(self.validate(lock))

    def test_education_inventory_identity_is_preserved_without_invented_commit(self):
        self.family = subject.FAMILIES['education']
        self.make_fixture()
        self.receipt['sources'] = self.receipt.pop('source_files')
        self.receipt['bundle_files'] = self.receipt.pop('deployable_files')
        self.receipt.pop('source_commit')
        self.receipt.pop('source_worktree_clean_at_start')
        self.receipt['source_identity'] = 'exact_inventory_not_a_claimed_commit'
        self.receipt_path.write_text(json.dumps(self.receipt), encoding='utf-8')
        self.options['accepted_receipt_sha256'] = util.sha256_file(self.receipt_path)
        lock = self.prepare()
        self.assertIsNone(lock['evaluator_build']['source_commit'])
        self.assertIsNone(lock['evaluator_build']['clean_worktree'])
        self.assertEqual(lock['evaluator_build']['source_identity'], self.receipt['source_identity'])
        self.assertTrue(self.validate(lock))

    def test_validator_rejects_changed_current_controller(self):
        lock = self.prepare()
        self.write('outer/harness/gateway.py', 'different controller')
        with self.assertRaises(ValueError):
            self.validate(lock)

    def test_validator_rejects_changed_copied_bundle(self):
        lock = self.prepare()
        (self.root / 'evaluator/dependency.dll').write_bytes(b'different dependency')
        with self.assertRaises(ValueError):
            self.validate(lock)

    def test_validator_rejects_fabricated_historical_clean_fact(self):
        lock = self.prepare()
        lock['evaluator_build']['clean_worktree'] = True
        with self.assertRaises(ValueError):
            self.validate(lock)

    def test_validator_rejects_missing_source_coverage(self):
        lock = self.prepare()
        lock['repaired_runtime_binding']['current_applicability']['files'].pop('research/repaired_runtime.py')
        with self.assertRaises(ValueError):
            self.validate(lock)

    def test_validator_rejects_current_dirty_tree(self):
        lock = self.prepare()
        with self.assertRaises(ValueError):
            self.validate(lock, dirty=True)

    def test_validator_allows_unrelated_later_commit_without_changing_any_pinned_file(self):
        lock = self.prepare()
        # Validator has no HEAD-equality test; immutable Git blobs + current
        # pinned bytes are the attribution boundary after unrelated commits.
        self.assertTrue(self.validate(lock))

    def test_reject_actual_image_identity_mismatch_before_write(self):
        self.reject(image=lambda value: 'sha256:' + 'f' * 64)

    def test_reject_actual_version_mismatch_before_write(self):
        self.reject(docker=lambda *args: SimpleNamespace(stdout='wrong version'))

    def test_reject_gateway_source_mismatch_before_write(self):
        self.write('outer/harness/gateway.py', 'changed gateway')
        self.reject()

    def test_reject_evaluator_source_mismatch_before_write(self):
        self.write('inner/evaluator/' + self.family['project'] + '/Program.cs', 'new semantics')
        self.reject()

    def test_reject_uninventoried_evaluator_source_before_write(self):
        self.write('inner/evaluator/' + self.family['project'] + '/Extra.cs', 'new dependency')
        self.reject()

    def test_reject_uninventoried_nested_evaluator_source_before_write(self):
        self.write('inner/evaluator/' + self.family['project'] + '/nested/Extra.cs', 'unbound code')
        self.reject()

    def test_reject_runtime_budget_mismatch_before_write(self):
        self.profile['provider_timeout_seconds'] = 120
        self.write('outer/profiles/runtimes/' + self.runtime_id + '.json', self.profile)
        self.reject()

    def test_reject_bundle_mismatch_before_write(self):
        (self.bundle / 'dependency.dll').write_bytes(b'tampered dependency')
        self.reject()

    def test_reject_receipt_pin_mismatch_before_write(self):
        self.options['accepted_receipt_sha256'] = '0' * 64
        self.reject()

    def test_reject_dirty_or_wrong_commit_before_write(self):
        self.reject(git=lambda repo, *args: self.commit if args[0] == 'rev-parse' else ' M source')
        self.reject(git=lambda repo, *args: 'd' * 40 if args[0] == 'rev-parse' else '')

    def test_reject_variant_input_change_before_write(self):
        self.write('artifacts/assets/inputs/existing-business/initial.sqlite', 'changed data')
        self.reject()

    def test_reject_ledger_change_before_write(self):
        self.write('inner/spec/revised.json', '{"changed":true}')
        self.reject()

    def test_existing_namespace_never_overwritten(self):
        self.root.mkdir(parents=True)
        retained = self.root / 'lock.json'
        retained.write_text('retain old binding')
        with self.assertRaises(FileExistsError):
            self.prepare()
        self.assertEqual(retained.read_text(), 'retain old binding')


if __name__ == '__main__':
    unittest.main()
