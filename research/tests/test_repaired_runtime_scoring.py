"""Actual score_run admission; mocked Git/process leaves, no evaluator/model."""
import copy
import json
import shutil
from unittest import TestCase
from unittest.mock import patch

from outer.harness import evaluate, util
from research import repaired_runtime
from research.tests import test_repaired_runtime as preparation_fixture


class RepairedScoringTests(TestCase):
    def fixture(self, education=False):
        f = preparation_fixture.RepairedRuntimeTests('test_valid_rebind_preserves_original_false_clean_fact_and_current_commit')
        f.setUp()
        self.addCleanup(f.doCleanups)
        if education:
            f.family = repaired_runtime.FAMILIES['education']
            f.make_fixture()
            f.receipt['sources'] = f.receipt.pop('source_files')
            f.receipt['bundle_files'] = f.receipt.pop('deployable_files')
            f.receipt.pop('source_commit')
            f.receipt.pop('source_worktree_clean_at_start')
            f.receipt['source_identity'] = 'exact_inventory_not_a_claimed_commit'
            f.receipt_path.write_text(json.dumps(f.receipt), encoding='utf-8')
            f.options['accepted_receipt_sha256'] = util.sha256_file(f.receipt_path)
        lock = f.prepare()
        root = f.base / 'runs' / 'finite-run'
        root.mkdir(parents=True)
        for name in ('inputs', 'profiles', 'frozen'):
            (root / name).mkdir()
        (root / 'frozen/source.cs').write_text('saved artifact', encoding='utf-8')
        (root / 'inputs/prompt.txt').write_text('same original prompt', encoding='utf-8')
        util.write_new_json(root / 'context.json', {})
        util.write_new_json(root / 'profiles/task.json', f.task)
        util.write_new_json(root / 'profiles/runtime.json', f.profile)
        assets = root / 'evaluation-assets'
        shutil.copytree(f.root / 'evaluator', assets / 'evaluator')
        for key, dest in [('spec_path', 'requirements.json'), ('catalog_path', 'catalog.json')]:
            shutil.copyfile(f.repo / f.task['evaluation'][key], assets / dest)
        condition = copy.deepcopy(f.task)
        condition.update(schema_version=2, task_profile_revision='evaluators-20261006',
                         runtime=f.profile, runtime_lock=lock)
        condition['evaluation'].update(executor='docker', spec_path='evaluation-assets/requirements.json',
            catalog_path='evaluation-assets/catalog.json', evaluator_sha256=lock['evaluator_sha256'],
            evaluator_build=copy.deepcopy(lock['evaluator_build']))
        util.write_new_json(root / 'condition.json', condition)
        util.write_new_json(root / 'snapshot.json', {'run_id': 'finite-run', 'artifact_sha256': util.artifact_hash(root / 'frozen')})
        util.write_new_json(root / 'manifest.json', {'run_id': 'finite-run', 'run_instance_id': '1'*32,
            'stop_confirmed': True, 'submission_fixed': True})
        self.freeze(root)
        return f, root, condition

    def freeze(self, root):
        manifest = util.read_json(root / 'manifest.json')
        manifest.update(condition_sha256=util.sha256_file(root/'condition.json'),
            input_files=util.tree_hashes(root/'inputs'), profile_files=util.tree_hashes(root/'profiles'),
            assets_sha256=util.tree_hashes(root/'evaluation-assets'),
            context_sha256=util.sha256_file(root/'context.json'))
        (root/'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')

    def score(self, f, root, *, dirty=False):
        with patch.object(repaired_runtime, 'FAMILIES', {'fixture': f.family}), \
                patch.object(repaired_runtime, '_git', return_value=' M source' if dirty else ''), \
                patch.object(repaired_runtime, '_committed_files'), \
                patch('outer.harness.runtime.scoring_command', return_value=(None, ['finite-providerless'])), \
                patch.object(evaluate, 'run_evaluator', return_value=(0, False)) as process:
            result = evaluate.score_run(f.repo, root.parent, root.name)
            self.assertEqual(process.call_count, 1)
            self.assertEqual(result['scoring_state'], 'evaluator_fault')
            self.assertTrue((root/'evaluation-work/001').is_dir())
            return result

    def reject(self, f, root, *, dirty=False):
        with patch.object(evaluate, 'run_evaluator') as process:
            with self.assertRaises((ValueError, RuntimeError)):
                self.score(f, root, dirty=dirty)
            process.assert_not_called()
        self.assertFalse((root/'evaluations').exists())
        self.assertFalse((root/'evaluation-work').exists())

    def test_historical_false_clean_reaches_actual_score_run_without_relabeling(self):
        f, root, condition = self.fixture()
        before = util.sha256_file(root/'condition.json')
        self.assertIs(condition['evaluation']['evaluator_build']['clean_worktree'], False)
        self.score(f, root)
        self.assertEqual(before, util.sha256_file(root/'condition.json'))

    def test_historical_missing_clean_inventory_identity_reaches_actual_score_run(self):
        f, root, condition = self.fixture(education=True)
        self.assertIsNone(condition['evaluation']['evaluator_build']['clean_worktree'])
        self.score(f, root)

    def test_current_dirty_applicability_is_rejected(self):
        f, root, _ = self.fixture()
        self.reject(f, root, dirty=True)

    def test_bound_build_cannot_be_relabelled_clean(self):
        f, root, condition = self.fixture()
        condition['evaluation']['evaluator_build']['clean_worktree'] = True
        (root/'condition.json').write_text(json.dumps(condition), encoding='utf-8')
        self.freeze(root)
        self.reject(f, root)

    def test_copied_dependency_tamper_is_rejected_even_if_manifest_refrozen(self):
        f, root, _ = self.fixture()
        (root/'evaluation-assets/evaluator/dependency.dll').write_bytes(b'tampered')
        self.freeze(root)
        self.reject(f, root)

    def test_embedded_lock_must_equal_prepared_lock(self):
        f, root, condition = self.fixture()
        condition['runtime_lock']['controller_source_commit'] = 'd'*40
        (root/'condition.json').write_text(json.dumps(condition), encoding='utf-8')
        self.freeze(root)
        self.reject(f, root)

    def test_current_controller_bytes_changed_reject_old_frozen_lock(self):
        f, root, _ = self.fixture()
        f.write('outer/harness/gateway.py', 'amended controller requires new lock')
        self.reject(f, root)

    def test_frozen_profile_mismatch_is_rejected(self):
        f, root, _ = self.fixture()
        task = util.read_json(root/'profiles/task.json')
        task['migration_request'] = 'different public request'
        (root/'profiles/task.json').write_text(json.dumps(task), encoding='utf-8')
        self.freeze(root)
        self.reject(f, root)

    def test_catalog_tamper_is_rejected_even_if_manifest_refrozen(self):
        f, root, _ = self.fixture()
        (root/'evaluation-assets/catalog.json').write_text('{"wrong":true}', encoding='utf-8')
        self.freeze(root)
        self.reject(f, root)

    def test_missing_pinned_evaluator_cannot_use_repaired_gate(self):
        f, root, condition = self.fixture()
        condition['evaluation'].pop('evaluator_sha256')
        (root/'condition.json').write_text(json.dumps(condition), encoding='utf-8')
        self.freeze(root)
        self.reject(f, root)

    def test_stripped_repaired_tags_and_forged_clean_cannot_fall_back_to_legacy(self):
        f, root, condition = self.fixture()
        condition['runtime_lock'].pop('repaired_runtime_binding')
        condition['evaluation']['evaluator_build'].pop('binding_kind')
        condition['evaluation']['evaluator_build']['clean_worktree'] = True
        (root/'condition.json').write_text(json.dumps(condition), encoding='utf-8')
        self.freeze(root)
        self.reject(f, root)

    def test_revision_alone_requires_strict_gate_with_runtime_id_and_tags_removed(self):
        f, root, condition = self.fixture()
        condition['runtime_lock'].pop('repaired_runtime_binding')
        condition['evaluation']['evaluator_build'].pop('binding_kind')
        condition['evaluation']['evaluator_build']['clean_worktree'] = True
        condition['runtime'].pop('id')
        (root/'condition.json').write_text(json.dumps(condition), encoding='utf-8')
        self.freeze(root)
        self.reject(f, root)

    def test_copied_build_receipt_tamper_is_rejected_even_if_manifest_refrozen(self):
        f, root, _ = self.fixture()
        (root/'evaluation-assets/evaluator/build-receipt.json').write_text('{}', encoding='utf-8')
        self.freeze(root)
        self.reject(f, root)

    def test_evaluation_version_and_project_drift_rejected_before_directories(self):
        for key, value in [('evaluation_version', '9.0.0'), ('project', 'foreign/Foreign.csproj')]:
            with self.subTest(key=key):
                f, root, condition = self.fixture()
                condition['evaluation'][key] = value
                (root/'condition.json').write_text(json.dumps(condition), encoding='utf-8')
                self.freeze(root)
                self.reject(f, root)
