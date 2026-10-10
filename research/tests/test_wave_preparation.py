"""Finite prospective-view checks; no Run, Docker, compiler or model calls."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from outer.harness import util
from research import wave_execution as execution


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.view = self.root / 'view'; self.view.mkdir()
        self.tasks = ['MS1-CONT-A', 'MS1-CONT-B', 'CU1-ENR-C', 'CU1-ENR-D']
        spec = self.view / 'inner/spec/criteria.json'; spec.parent.mkdir(parents=True); spec.write_bytes(b'unchanged strict criteria')
        other = self.view / 'inner/evaluator/Other.cs'; other.parent.mkdir(parents=True); other.write_bytes(b'unchanged other source')
        program = self.view / execution.EDUCATION_SOURCE; program.parent.mkdir(parents=True); program.write_bytes(b'fixture diagnostics revision')
        source_digest = util.sha256_file(program)
        self.constant = patch.object(execution, 'NEW_EDUCATION_SOURCE_SHA256', source_digest)
        self.constant.start(); self.addCleanup(self.constant.stop)
        self.original = {'plan': {'task_ids': self.tasks}, 'runtime_locks': {}, 'pinned_files': {
            execution.EDUCATION_SOURCE: execution.OLD_EDUCATION_SOURCE_SHA256,
            'inner/spec/criteria.json': util.sha256_file(spec), 'inner/evaluator/Other.cs': util.sha256_file(other)}}
        references = {}
        for task in self.tasks:
            root = self.view / 'artifacts/runtime' / task; evaluator = root / 'evaluator'; evaluator.mkdir(parents=True)
            dll = evaluator / ('MusicStore.Evaluator.dll' if task.startswith('MS1') else 'Education.Evaluator.dll')
            dll.write_bytes(b'old music' if task.startswith('MS1') else b'new education')
            lock = {'images': {'worker': 'unchanged', 'gateway': 'unchanged'}, 'controller_files': {'runtime': 'unchanged'},
                'opencode_version': 'unchanged', 'versions': {}, 'build_id': 'original', 'created_at': 'original',
                'evaluator_files': util.tree_hashes(evaluator), 'evaluator_sha256': util.sha256_file(dll),
                'evaluator_build': {'clean_worktree': True, 'implementation_revision': execution.DIAGNOSTICS_REVISION}}
            old = {**lock, 'evaluator_build': {'clean_worktree': True}}
            self.original['runtime_locks'][task] = lock if task.startswith('MS1') else old
            path = root / 'lock.json'; util.write_new_json(path, lock)
            references[task] = {'path': str(path), 'sha256': util.sha256_file(path)}
        original = self.root / 'original.json'; util.write_new_json(original, self.original)
        rows = []
        for task in self.tasks:
            inputs = self.view / 'assets' / task / 'inputs'
            for name in ('legacy-source', 'existing-business'):
                (inputs / name).mkdir(parents=True); (inputs / name / 'file').write_bytes(b'fixed input')
            for arm in ('explore', 'preload'):
                rows.append({'task': task, 'arm': arm, 'prompt_sha256': util.sha256_bytes(b'fixed prompt'),
                    'model_input_files': {n: util.tree_hashes(inputs / n) for n in ('legacy-source', 'existing-business')},
                    'public_and_hidden_profile_bytes_unchanged': True})
        equivalence = self.root / 'equivalence.json'
        util.write_new_json(equivalence, {'original_bundle_sha256': util.sha256_file(original),
            'eight_task_arm_prompt_and_model_input_equivalence': rows, 'model_called': False,
            'run_created': False, 'source_originals_changed': False})
        acceptance = self.root / 'acceptance.json'; util.write_new_json(acceptance, {'finite_checks_passed': True})
        self.witness = {'kind': 'prospective_preparation_view_diagnostics_v1',
            'original_bundle_sha256': util.sha256_file(original), 'implementation_revision': execution.DIAGNOSTICS_REVISION,
            'old_source_sha256': execution.OLD_EDUCATION_SOURCE_SHA256, 'new_source_sha256': source_digest,
            'new_evaluator_sha256': self.original['runtime_locks']['CU1-ENR-C']['evaluator_sha256'],
            'criteria_unchanged': True, 'criteria_pins': {'inner/spec/criteria.json': util.sha256_file(spec)},
            'runtime_locks': references,
            'equivalence_receipt': {'path': str(equivalence), 'sha256': util.sha256_file(equivalence)},
            'nonlive_acceptance': {'path': str(acceptance), 'sha256': util.sha256_file(acceptance)}}
        self.witness_path = self.root / 'witness.json'; util.write_new_json(self.witness_path, self.witness)
        self.phase = {'original_bundle': {'path': str(original), 'sha256': util.sha256_file(original)},
            'runtime': 'fixture', 'preparation_view': {'path': str(self.view),
                'witness': {'path': str(self.witness_path), 'sha256': util.sha256_file(self.witness_path)}}}
        self.read = patch.object(execution.profiles, 'read', return_value={}); self.read.start(); self.addCleanup(self.read.stop)
        self.resolve = patch.object(execution.profiles, 'resolve', side_effect=lambda view, task, arm, runtime:
            {'task_input_adapter': 'migration-v1', 'evaluation': {'catalog_path': 'assets/' + task + '/evaluation/catalog.json'}})
        self.resolve.start(); self.addCleanup(self.resolve.stop)
        self.prompt = patch.object(execution.profiles, 'prepare_prompt', return_value=('fixed prompt', {}))
        self.prompt_mock = self.prompt.start(); self.addCleanup(self.prompt.stop)

    def save_witness(self):
        util.write_json_atomic(self.witness_path, self.witness)
        self.phase['preparation_view']['witness']['sha256'] = util.sha256_file(self.witness_path)

    def test_exact_diagnostics_source_compiled_tree_and_all_eight_inputs_pass(self):
        self.assertEqual(execution.validate_preparation(self.view, self.phase), self.witness)

    def test_false_criteria_unknown_revision_or_wrong_original_source_rejected(self):
        for key, value in (('criteria_unchanged', False), ('implementation_revision', 'other'),
                ('old_source_sha256', 'b' * 64), ('new_source_sha256', 'a' * 64), ('criteria_pins', {})):
            with self.subTest(key=key):
                old = self.witness[key]; self.witness[key] = value; self.save_witness()
                with self.assertRaises(ValueError): execution.validate_preparation(self.view, self.phase)
                self.witness[key] = old; self.save_witness()

    def test_other_inner_source_and_strict_criteria_mutations_rejected(self):
        for name in ('inner/evaluator/Other.cs', 'inner/spec/criteria.json'):
            with self.subTest(name=name):
                path = self.view / name; old = path.read_bytes(); path.write_bytes(b'changed')
                with self.assertRaises(ValueError): execution.validate_preparation(self.view, self.phase)
                path.write_bytes(old)

    def test_changed_model_input_or_prompt_is_rejected(self):
        path = self.view / 'assets/CU1-ENR-C/inputs/existing-business/file'; path.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'prompt/model input'): execution.validate_preparation(self.view, self.phase)
        path.write_bytes(b'fixed input'); self.prompt_mock.return_value = ('changed prompt', {})
        with self.assertRaisesRegex(ValueError, 'prompt/model input'): execution.validate_preparation(self.view, self.phase)

    def test_gateway_worker_images_cannot_change_even_with_rehashed_lock_witness(self):
        ref = self.witness['runtime_locks']['CU1-ENR-C']; lock = util.read_json(ref['path'])
        lock['images']['worker'] = 'changed'; util.write_json_atomic(ref['path'], lock)
        ref['sha256'] = util.sha256_file(ref['path']); self.save_witness()
        with self.assertRaisesRegex(ValueError, 'only the witnessed evaluator'): execution.validate_preparation(self.view, self.phase)

    def test_compiled_dll_tampering_or_changed_acceptance_evidence_rejected(self):
        path = self.view / 'artifacts/runtime/CU1-ENR-C/evaluator/Education.Evaluator.dll'
        path.write_bytes(b'changed dll')
        with self.assertRaisesRegex(ValueError, 'evaluator tree changed'): execution.validate_preparation(self.view, self.phase)
        path.write_bytes(b'new education'); Path(self.witness['nonlive_acceptance']['path']).write_bytes(b'changed receipt')
        with self.assertRaisesRegex(ValueError, 'evidence missing or changed'): execution.validate_preparation(self.view, self.phase)

    def test_preflight_only_allows_the_witnessed_inner_program_change(self):
        names = ('research/wave_plan.py', 'research/wave_dispatch.py', 'research/wave_execution.py', 'research/pair_execution.py')
        self.phase['source_pins'] = {execution.EDUCATION_SOURCE: execution.NEW_EDUCATION_SOURCE_SHA256}
        for name in names:
            path = self.view / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'fixture controller')
            self.phase['source_pins'][name] = util.sha256_file(path)
        with patch.object(execution.wave_plan, 'validate', return_value=self.original):
            self.assertEqual(execution.preflight(self.view, self.phase), self.original)
            path = self.view / 'inner/evaluator/Other.cs'; path.write_bytes(b'changed source')
            self.phase['source_pins']['inner/evaluator/Other.cs'] = util.sha256_file(path)
            with self.assertRaisesRegex(ValueError, 'frozen source/criteria/input'): execution.preflight(self.view, self.phase)

    def test_original_bundle_and_witness_bytes_must_remain_exact(self):
        Path(self.phase['original_bundle']['path']).write_bytes(b'changed original')
        with self.assertRaisesRegex(ValueError, 'Original bundle bytes'): execution.validate_preparation(self.view, self.phase)

    def test_phase_pinned_sharing_adapter_test_is_the_only_allowed_test_change(self):
        allowed = 'research/tests/test_next_phase_sharing.py'
        required = ('research/wave_plan.py', 'research/wave_dispatch.py', 'research/wave_execution.py', 'research/pair_execution.py')
        pins = {}
        for name in (*required, allowed):
            path = self.root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'new researcher code')
            pins[name] = util.sha256_file(path)
        original = {'pinned_files': {allowed: 'a' * 64}}
        phase = {'source_pins': pins}
        with patch.object(execution.wave_plan, 'validate', return_value=original):
            self.assertEqual(execution.preflight(self.root, phase), original)
            denied = 'research/tests/test_other.py'; path = self.root / denied; path.write_bytes(b'changed unrelated test')
            pins[denied] = util.sha256_file(path); original['pinned_files'][denied] = 'b' * 64
            with self.assertRaisesRegex(ValueError, 'cannot alter original'): execution.preflight(self.root, phase)


if __name__ == '__main__': unittest.main()
