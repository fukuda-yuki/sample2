"""Revision lookup and pre-copy dispatch controls; no prepared sources or workers."""
import copy
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from outer.harness import migration_input, profiles, run, util

ROOT = Path(__file__).resolve().parents[2]
REVISION = 'evaluators-20261006'
TASKS = ('MS1-CONT-A', 'MS1-CONT-B', 'CU1-ENR-C', 'CU1-ENR-D')


def runtime_id(task_id):
    return ('deepseek-music-repaired-v1' if task_id.startswith('MS1-')
            else 'deepseek-education-repaired-v1')


class TaskProfileRevisionControls(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name) / 'repo'
        self.runs = Path(self.temporary.name) / 'runs'
        files = [f'outer/profiles/tasks/{task}.json' for task in TASKS]
        files += [f'outer/profiles/task-revisions/{REVISION}/{task}.json' for task in TASKS]
        files += [f'outer/profiles/interventions/{arm}.json' for arm in ('explore', 'preload', 'explained')]
        files += [f'outer/profiles/runtimes/{name}.json' for name in (
            'deepseek', 'deepseek-music-repaired-v1', 'deepseek-education-repaired-v1')]
        for relative in files:
            destination = self.repo / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, destination)

    def revision_path(self, task_id):
        return self.repo / 'outer/profiles/task-revisions' / REVISION / (task_id + '.json')

    def condition(self, task_id, *, revised=True):
        options = {'task_revision': REVISION} if revised else {}
        return profiles.resolve(self.repo, task_id, 'explore', runtime_id(task_id), **options)

    def write_lock(self, task_id, *, revised=True):
        condition = self.condition(task_id, revised=revised)
        lock = {'opencode_version': condition['runtime']['opencode_version'],
                'evaluator_build': {'clean_worktree': True}}
        if revised:
            lock.update(task_profile_revision=REVISION,
                        evaluator_version=condition['evaluation']['evaluation_version'],
                        evaluator_project=condition['evaluation']['project'])
        path = profiles.runtime_root(self.repo, task_id, condition['runtime']) / 'lock.json'
        util.write_json_atomic(path, lock)
        return path, lock

    def assert_create_rejected_before_input_copy(self, task_id, *, revised=True):
        options = {'task_revision': REVISION} if revised else {}
        with patch.object(migration_input, 'prepare', side_effect=AssertionError('input preparation reached')) as prepare, \
             patch.object(run, 'create_run', side_effect=AssertionError('Run creation reached')) as create, \
             patch.object(profiles.shutil, 'copytree', side_effect=AssertionError('input copy reached')) as tree, \
             patch.object(profiles.shutil, 'copy2', side_effect=AssertionError('asset copy reached')) as files:
            with self.assertRaisesRegex(ValueError, 'Prepared evaluator revision'):
                profiles.create(self.repo, self.runs, task_id, 'explore', 1,
                                runtime_id(task_id), **options)
            for boundary in (prepare, create, tree, files):
                boundary.assert_not_called()
        self.assertFalse(self.runs.exists())

    def test_default_lookup_and_resolution_keep_original_task_versions(self):
        for task_id in TASKS:
            with self.subTest(task=task_id):
                original = util.read_json(self.repo / 'outer/profiles/tasks' / (task_id + '.json'))
                self.assertEqual(profiles.read(self.repo, 'tasks', task_id), original)
                self.assertEqual(profiles.task_profile(self.repo, task_id), original)
                condition = profiles.resolve(self.repo, task_id, 'explore')
                self.assertEqual(condition['evaluation'], original['evaluation'])
                self.assertEqual(condition['runtime']['id'], 'deepseek')
                self.assertNotIn('task_profile_revision', condition)
                self.assertNotIn('revision_id', condition)

    def test_explicit_revision_resolves_all_canonical_tasks_without_changing_public_prompt(self):
        source = Path(self.temporary.name) / 'public-source'
        source.mkdir()
        (source / 'INSTALLATION-NOTE.txt').write_text('Synthetic public source.\n', encoding='utf-8')
        for task_id in TASKS:
            task = profiles.read(self.repo, 'tasks', task_id, task_revision=REVISION)
            self.assertEqual(task, profiles.task_profile(self.repo, task_id, REVISION))
            self.assertEqual(task['task_id'], task_id)
            self.assertEqual(task['canonical_task_id'], task_id)
            for arm in ('explore', 'preload', 'explained'):
                with self.subTest(task=task_id, arm=arm):
                    old = profiles.resolve(self.repo, task_id, arm, runtime_id(task_id))
                    new = profiles.resolve(self.repo, task_id, arm, runtime_id(task_id), task_revision=REVISION)
                    self.assertEqual(new['task_profile_revision'], REVISION)
                    self.assertEqual(new['revision_id'], REVISION)
                    self.assertEqual(new['evaluation']['evaluation_version'],
                                     '1.6.0' if task_id.startswith('MS1-') else 'education-1.1.0')
                    for key in ('task_id', 'family_id', 'semantic_variant', 'start_state',
                                'migration_request', 'input_policy', 'context_files'):
                        self.assertEqual(new[key], old[key])
                    self.assertEqual(profiles.prepare_prompt(new, source), profiles.prepare_prompt(old, source))

    def test_identifier_traversal_is_rejected_for_both_task_and_revision(self):
        for value in ('../tasks', '..\\tasks', '/absolute', 'C:\\escape', '', '.', True, 7):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    profiles.read(self.repo, 'tasks', 'MS1-CONT-A', task_revision=value)
                with self.assertRaises(ValueError):
                    profiles.read(self.repo, 'tasks', value, task_revision=REVISION)
        with self.assertRaises(ValueError):
            profiles.read(self.repo, 'runtimes', 'deepseek', task_revision=REVISION)

    def test_unknown_revision_and_unknown_task_do_not_fall_back(self):
        with self.assertRaises(FileNotFoundError):
            profiles.resolve(self.repo, 'MS1-CONT-A', 'explore', runtime_id('MS1-CONT-A'),
                             task_revision='evaluators-20990101')
        with self.assertRaises(FileNotFoundError):
            profiles.task_profile(self.repo, 'MS1-CONT-Z', REVISION)

    def test_mismatched_revision_task_and_canonical_identity_are_rejected(self):
        for task_id in TASKS:
            path = self.revision_path(task_id)
            original = util.read_json(path)
            for key in ('revision_id', 'task_id', 'canonical_task_id'):
                with self.subTest(task=task_id, key=key):
                    wrong = copy.deepcopy(original)
                    wrong[key] = 'foreign-profile'
                    util.write_json_atomic(path, wrong)
                    with self.assertRaisesRegex(ValueError, 'Task revision identity'):
                        self.condition(task_id)
                    util.write_json_atomic(path, original)

    def test_revised_create_rejects_wrong_version_project_and_revision_before_inputs(self):
        for task_id in TASKS:
            original_version = self.condition(task_id, revised=False)['evaluation']['evaluation_version']
            for key, value in (('evaluator_version', original_version),
                               ('evaluator_version', '1.7.0'),
                               ('evaluator_project', 'Foreign.Evaluator/Foreign.Evaluator.csproj'),
                               ('task_profile_revision', 'foreign-revision'),
                               ('evaluator_version', None), ('evaluator_project', None),
                               ('task_profile_revision', None),
                               ('evaluator_version', True), ('evaluator_project', True),
                               ('task_profile_revision', True)):
                with self.subTest(task=task_id, key=key, value=value):
                    path, lock = self.write_lock(task_id)
                    lock[key] = value
                    util.write_json_atomic(path, lock)
                    self.assert_create_rejected_before_input_copy(task_id)

    def test_default_old_profile_cannot_consume_new_revision_lock(self):
        for task_id in TASKS:
            with self.subTest(task=task_id):
                self.write_lock(task_id)
                self.assert_create_rejected_before_input_copy(task_id, revised=False)

    def test_correct_revision_lock_reaches_input_boundary_with_new_condition(self):
        for task_id in TASKS:
            with self.subTest(task=task_id):
                self.write_lock(task_id)
                with patch.object(migration_input, 'prepare', side_effect=RuntimeError('owned input boundary')) as prepare, \
                     patch.object(run, 'create_run') as create:
                    with self.assertRaisesRegex(RuntimeError, 'owned input boundary'):
                        profiles.create(self.repo, self.runs, task_id, 'explore', 1,
                                        runtime_id(task_id), task_revision=REVISION)
                    condition = prepare.call_args.args[1]
                    self.assertEqual(condition['task_profile_revision'], REVISION)
                    self.assertEqual(condition['evaluation'], self.condition(task_id)['evaluation'])
                    create.assert_not_called()
                self.assertFalse(self.runs.exists())

    def test_default_old_profile_with_old_lock_still_reaches_input_boundary(self):
        for task_id in TASKS:
            with self.subTest(task=task_id):
                original = profiles.resolve(self.repo, task_id, 'explore')
                lock_path = profiles.runtime_root(self.repo, task_id, original['runtime']) / 'lock.json'
                util.write_json_atomic(lock_path, {
                    'opencode_version': original['runtime']['opencode_version'],
                    'evaluator_build': {'clean_worktree': True}})
                with patch.object(migration_input, 'prepare', side_effect=RuntimeError('owned input boundary')) as prepare, \
                     patch.object(run, 'create_run') as create:
                    with self.assertRaisesRegex(RuntimeError, 'owned input boundary'):
                        profiles.create(self.repo, self.runs, task_id, 'explore', 1)
                    self.assertNotIn('task_profile_revision', prepare.call_args.args[1])
                    self.assertEqual(prepare.call_args.args[1]['evaluation'], original['evaluation'])
                    self.assertEqual(prepare.call_args.args[1]['runtime']['id'], 'deepseek')
                    create.assert_not_called()
                self.assertFalse(self.runs.exists())


if __name__ == '__main__':
    unittest.main()
