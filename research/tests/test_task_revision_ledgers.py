"""Bounded readiness controls for new ledgers; no evaluator or model execution."""
import copy
from pathlib import Path
import tempfile
import unittest

from outer.harness import profiles, util
from research import repair_spec
from research.saved_reassessment import requirement_inventory

ROOT = Path(__file__).resolve().parents[2]
REVISION = 'evaluators-20261006'
TASKS = ('MS1-CONT-A', 'MS1-CONT-B', 'CU1-ENR-C', 'CU1-ENR-D')
OLD_HASHES = {
    'outer/profiles/tasks/MS1-CONT-A.json': 'afca10fb73efa2f7aceb99f2ed221f8dfb877ab109896a63683445ae34c77ee7',
    'outer/profiles/tasks/MS1-CONT-B.json': 'a71d55c05b5bc7be517f783c414e7856d838063a2dd45a2c87193ebe8af736a4',
    'outer/profiles/tasks/CU1-ENR-C.json': '839fc520c95d141614d51c8923dfc4a6bff6b77383b616a79234669dac7c629f',
    'outer/profiles/tasks/CU1-ENR-D.json': '688d9489dba29a5fd406672c386c93d786845e7b8f746cca9e7ec26189f4a4f8',
    'inner/spec/requirements-cont-A-1.3.0.json': '47175ebbe5eaf3e21267396f5c9e0626a90857111da98623ecb54bc884afe16e',
    'inner/spec/requirements-cont-B-1.3.0.json': '30d0476b4f47b77e74622c4ea0d1257f5af4c3772c2f33c7aba15a8a7e5e2d9e',
    'inner/spec/requirements-cu-C-education-1.0.0.json': 'e170ceab2b2b0a57ac19b268c221151ece851971d8c86de1666915ecbeab76df',
    'inner/spec/requirements-cu-D-education-1.0.0.json': '21d57e0786c7e8329b9a47545b6e5d72262eb0b2342e8ee29edd4a4ba44e198a',
}
ACCEPTED_EDUCATION = {
    'CU1-ENR-C': '15e94d08bc1454e7d91faa69969dcbd50007debf529d427fe38e1cd01e180fce',
    'CU1-ENR-D': '32538012e928e308bdeeb2e798fd3b1647c6c5324ddf17a92686933cdc6e5fff',
}


def task_pair(task_id):
    return (util.read_json(ROOT / 'outer/profiles/tasks' / (task_id + '.json')),
            util.read_json(ROOT / 'outer/profiles/task-revisions' / REVISION / (task_id + '.json')))


class TaskRevisionLedgerControls(unittest.TestCase):
    def test_frozen_profiles_and_ledgers_remain_byte_identical(self):
        for path, expected in OLD_HASHES.items():
            with self.subTest(path=path):
                self.assertEqual(util.sha256_file(ROOT / path), expected)

    def test_profiles_change_only_explicit_revision_and_evaluation_binding(self):
        bindings = set()
        for task_id in TASKS:
            with self.subTest(task=task_id):
                old, new = task_pair(task_id)
                self.assertEqual(new['task_id'], task_id)
                self.assertEqual(new['canonical_task_id'], task_id)
                self.assertEqual(new['revision_id'], REVISION)
                version = '1.6.0' if task_id.startswith('MS1-') else 'education-1.1.0'
                expected_path = (f'inner/spec/requirements-cont-{task_id[-1]}-1.6.0.json'
                    if task_id.startswith('MS1-') else
                    f'inner/spec/requirements-cu-{task_id[-1]}-education-1.1.0.json')
                self.assertEqual(new['evaluation']['evaluation_version'], version)
                self.assertEqual(new['evaluation']['spec_path'], expected_path)
                spec = ROOT / expected_path
                self.assertEqual(new['evaluation']['spec_sha256'], util.sha256_file(spec))
                self.assertEqual(util.read_json(spec)['taskId'], task_id)
                restored = copy.deepcopy(new)
                restored.pop('canonical_task_id'); restored.pop('revision_id')
                for key in ('evaluation_version', 'spec_path', 'spec_sha256'):
                    restored['evaluation'][key] = old['evaluation'][key]
                self.assertEqual(restored, old)
                bindings.add((expected_path, new['evaluation']['spec_sha256']))
        self.assertEqual(len(bindings), 4)
        self.assertEqual(len({digest for _, digest in bindings}), 4)

    def test_ledgers_match_declared_repair_and_preserve_requirements_and_oracles(self):
        for task_id in TASKS:
            with self.subTest(task=task_id):
                old, new = task_pair(task_id)
                original = util.read_json(ROOT / old['evaluation']['spec_path'])
                revised = util.read_json(ROOT / new['evaluation']['spec_path'])
                expected = copy.deepcopy(original)
                for _ in range(3 if task_id.startswith('MS1-') else 1):
                    expected = repair_spec.revised(expected)
                self.assertEqual(revised, expected)
                self.assertEqual(requirement_inventory(revised), requirement_inventory(original))
                self.assertEqual(revised['migrationContract'], original['migrationContract'])
                self.assertEqual(revised['sourceRepository'], original['sourceRepository'])
                self.assertEqual(revised['sourceCommit'], original['sourceCommit'])
                if task_id in ACCEPTED_EDUCATION:
                    self.assertEqual(util.sha256_file(ROOT / new['evaluation']['spec_path']),
                                     ACCEPTED_EDUCATION[task_id])

    def test_public_prompt_and_model_input_policy_do_not_include_revision_or_private_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'INSTALLATION-NOTE.txt').write_text(
                'Synthetic public source boundary for prompt equivalence.\n', encoding='utf-8')
            for task_id in TASKS:
                old, new = task_pair(task_id)
                self.assertEqual(new['input_policy'], old['input_policy'])
                self.assertEqual(new['input_policy']['allowlist'], ['legacy-source', 'existing-business'])
                self.assertIn('migration-oracle.json', new['input_policy']['denied'])
                self.assertEqual(new['evaluation']['extra_assets'], old['evaluation']['extra_assets'])
                for method in ('explore', 'preload', 'explained'):
                    with self.subTest(task=task_id, method=method):
                        conditions = []
                        for task in (old, new):
                            condition = copy.deepcopy(task)
                            condition.update(runtime={'input_mount': '/inputs'},
                                             intervention={'method': method})
                            conditions.append(condition)
                        before = profiles.prepare_prompt(conditions[0], Path(directory))
                        after = profiles.prepare_prompt(conditions[1], Path(directory))
                        self.assertEqual(before, after)
                        self.assertNotIn('measurementRevision', after[0])
                        self.assertNotIn('migration-oracle.json', after[0])
                        self.assertNotIn(REVISION, after[0])


if __name__ == '__main__':
    unittest.main()
