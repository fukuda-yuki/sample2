"""Independent storage/adoption review regressions; no actual containers/keys.

The browser normal fixture tests harness binding, not real UI semantics.
"""
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from outer.harness import education_browser, util
from research import saved_reassessment as reassess
from research.tests import test_saved_reassessment as fixtures


class ReassessmentBoundaryReviewTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.SavedReassessmentTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root, self.source = self.fixture.root, self.fixture.source
        self.repo = Path(reassess.__file__).resolve().parents[1]
        # Opaque bytes: this review never opens an original SQLite connection.
        for name in ('school.sqlite', 'school.sqlite-wal', 'school.sqlite-shm'):
            (self.source / name).write_bytes(('original:' + name).encode())
        for folder in ('bin', 'obj'):
            (self.source / 'frozen' / folder).mkdir()
            (self.source / 'frozen' / folder / 'old.bin').write_bytes(b'original ignored-build bytes')
        self.before = reassess.byte_inventory(self.source)
        self.name = 's2-score-' + '1' * 32

    def execute_mock(self, stage, run, compose=None, cleanup=None):
        with patch.object(reassess.runtime, 'scoring_command',
                return_value=(self.name, ['docker', 'run', '--name', self.name, 'dummy'])), \
             patch.object(reassess.evaluate, 'run_evaluator', side_effect=run), \
             patch.object(reassess.browser_cleanup, 'cleanup',
                side_effect=cleanup or (lambda *a, **k: {'confirmed': True})), \
             patch.object(reassess.browser_review, 'complete_evaluation', side_effect=compose):
            return reassess.execute(stage, repo=self.repo)

    def result(self, stage):
        a = util.read_json(stage/'assessment.json')
        return {'taskId': 'EDU', 'artifactPath': '/artifact',
            'artifactSha256': a['source_artifact_sha256'], 'specSha256': a['new_spec_sha256'],
            'evaluationVersion': a['evaluation_version'], 'quality': 1, 'researchStatus': 'complete',
            'verdict': 'pass', 'reviewRunInstanceId': a['assessment_id'],
            'browserReviewCoverage': education_browser.OBSERVED}

    def run_http(self, stage):
        def run(*args):
            util.write_new_json(stage/'output/http-only/evaluation.json', {'researchStatus': 'incomplete'})
            return 0, False
        return run

    def compose(self, stage, *, valid=True):
        def compose(*args):
            out = stage/'output'
            result = self.result(stage)
            assessment = util.read_json(stage/'assessment.json')
            if valid:
                review = out/'browser-school'; review.mkdir()
                receipt = {'schemaVersion': 2, 'actor': 'agent', 'action': 'create-edit-save',
                    'runInstanceId': assessment['assessment_id'],
                    'artifactSha256': assessment['source_artifact_sha256'],
                    'specSha256': assessment['new_spec_sha256'],
                    'evaluationVersion': assessment['evaluation_version'],
                    'baseUrl': 'http://127.0.0.1:1234', 'faults': [], 'productFailures': []}
                request = {key:receipt[key] for key in
                    ('runInstanceId', 'artifactSha256', 'specSha256', 'evaluationVersion', 'baseUrl')}
                util.write_new_json(review/'request.json', request)
                receipt['requestSha256'] = util.sha256_file(review/'request.json')
                for name in education_browser.REFERENCES:
                    path = review/(name + '.fixture')
                    path.write_bytes(('bound toy evidence:' + name).encode())
                    receipt[name] = {'path': path.name, 'sha256': util.sha256_file(path)}
                util.write_new_json(review/'receipt.json', receipt)
                result['browserReviewEvidenceSha256'] = util.sha256_file(review/'receipt.json')
                util.write_new_json(out/'browser-cleanup.json',
                    {'confirmed': True, 'run_instance_id': assessment['assessment_id']})
            else:
                result.update(reviewRunInstanceId='foreign', browserReviewCoverage='not_observed')
            util.write_new_json(out/'evaluation.json', result)
            util.write_new_json(out/'evaluator-manifest.json',
                {'evaluatorSha256': assessment['evaluator_sha256']})
            return 0
        return compose

    def test_complete_bound_normal_result_and_missing_foreign_evidence_symmetry(self):
        for valid in (True, False):
            stage = self.fixture.prepare()
            result = self.execute_mock(stage, self.run_http(stage), self.compose(stage, valid=valid))
            with self.subTest(valid=valid):
                self.assertEqual(result['adopted'], valid)
                self.assertEqual(result['quality'], 1 if valid else None)
                self.assertTrue(result['source_unchanged'])
                self.assertEqual(reassess.byte_inventory(self.source), self.before)

    def test_malformed_partial_output_has_terminal_receipt_raw_preserved_no_overwrite(self):
        stage = self.fixture.prepare()
        def run(*args):
            (stage/'output/http-only/evaluation.json').write_bytes(b'{not JSON')
            return 2, False
        result = self.execute_mock(stage, run)
        self.assertFalse(result['adopted'])
        self.assertIsNone(result['quality'])
        self.assertEqual(result['operation_status'], 'postprocessing_fault')
        self.assertEqual((stage/'output/http-only/evaluation.json').read_bytes(), b'{not JSON')
        self.assertTrue((stage/'result.json').is_file())
        self.assertEqual(reassess.byte_inventory(self.source), self.before)
        with self.assertRaises(FileExistsError): reassess.execute(stage, repo=self.repo)

    def test_failed_launch_never_removes_foreign_same_name_container(self):
        stage = self.fixture.prepare(); calls = []
        def docker(*args, **kwargs):
            calls.append(args)
            if args[:2] == ('ps', '-a'):
                return SimpleNamespace(returncode=0, stdout=json.dumps({'Names':self.name,'ID':'foreign-id'}))
            if args[0] == 'inspect':
                value = {'Name':'/'+self.name,'Id':'foreign-id',
                         'Config':{'Labels':{'sample2.browser-review':'foreign-owner'}}}
                return SimpleNamespace(returncode=0, stdout=json.dumps([value]))
            self.fail('Unexpected Docker mutation: ' + repr(args))
        with patch.object(reassess.runtime, 'scoring_command',
                return_value=(self.name, ['docker', 'run', '--name', self.name, 'dummy'])), \
             patch.object(reassess.evaluate, 'run_evaluator', return_value=(125, False)), \
             patch.object(reassess.runtime, 'docker', side_effect=docker):
            result = reassess.execute(stage, repo=self.repo)
        self.assertFalse(result['adopted'])
        self.assertFalse(result['cleanup_confirmed'])
        self.assertFalse(any(call[0] == 'rm' for call in calls))
        self.assertTrue(any(call[0] == 'inspect' for call in calls))
        self.assertEqual(reassess.byte_inventory(self.source), self.before)

    def test_original_assets_corruption_refused_before_assessment_output(self):
        util.write_json_atomic(self.source/'evaluation-assets/catalog.json', {'corrupted':'oracle asset'})
        with self.assertRaises(ValueError): self.fixture.prepare()
        self.assertFalse((self.root/'assessments').exists())

    def test_original_sidecars_and_binobj_unchanged_after_interrupt(self):
        stage = self.fixture.prepare()
        def run(*args): raise KeyboardInterrupt()
        result = self.execute_mock(stage, run)
        self.assertEqual(result['operation_status'], 'interrupted')
        self.assertFalse(result['adopted'])
        self.assertEqual(reassess.byte_inventory(self.source), self.before)
        with self.assertRaises(FileExistsError): reassess.execute(stage, repo=self.repo)

    def test_nested_evaluator_named_assets_are_copied_without_omission(self):
        folder = self.source/'evaluation-assets/auxiliary/evaluator'
        folder.mkdir(parents=True)
        (folder/'expected.bin').write_bytes(b'independent oracle auxiliary bytes')
        manifest = util.read_json(self.source/'manifest.json')
        manifest['assets_sha256'] = util.tree_hashes(self.source/'evaluation-assets')
        util.write_json_atomic(self.source/'manifest.json', manifest)
        before = reassess.byte_inventory(self.source)
        stage = self.fixture.prepare()
        self.assertEqual((stage/'evaluation-assets/auxiliary/evaluator/expected.bin').read_bytes(),
                         b'independent oracle auxiliary bytes')
        self.assertEqual(reassess.byte_inventory(self.source), before)

    def test_missing_or_changed_actual_dll_rejected_before_execution(self):
        with self.assertRaises(ValueError): self.fixture.prepare(assembly='Missing.dll')
        self.assertFalse((self.root/'assessments').exists())
        stage = self.fixture.prepare()
        (stage/'evaluation-assets/evaluator/New.dll').write_bytes(b'foreign changed build')
        with patch.object(reassess.evaluate, 'run_evaluator') as runner:
            with self.assertRaises(ValueError): reassess.execute(stage, repo=self.repo)
        runner.assert_not_called()
        self.assertFalse((stage/'output').exists())
        self.assertEqual(reassess.byte_inventory(self.source), self.before)

    def test_failed_source_verification_is_unknown_and_has_terminal_receipt(self):
        stage = self.fixture.prepare()
        real_inventory = reassess.byte_inventory
        source_reads = 0
        def inventory(path):
            nonlocal source_reads
            if Path(path).resolve() == self.source:
                source_reads += 1
                if source_reads > 1: raise PermissionError('injected finite source verification fault')
            return real_inventory(path)
        with patch.object(reassess, 'byte_inventory', side_effect=inventory):
            result = self.execute_mock(stage, lambda *args: (2, False))
        self.assertIsNone(result['source_unchanged'])
        self.assertEqual(result['operation_status'], 'source_invariance_unverified')
        self.assertFalse(result['adopted'])
        self.assertIsNone(result['quality'])
        self.assertTrue((stage/'result.json').is_file())
        self.assertEqual(real_inventory(self.source), self.before)

    def test_relocated_stage_inside_original_refused_before_output_creation(self):
        stage = self.fixture.prepare()
        relocated = self.source/'accidental-assessment'
        shutil.copytree(stage, relocated)
        # Mock only the inventory to model an already-bound relocated stage;
        # the containment fence must reject independently before any write.
        real_inventory = reassess.byte_inventory
        def inventory(path):
            return self.before if Path(path).resolve() == self.source else real_inventory(path)
        with patch.object(reassess, 'byte_inventory', side_effect=inventory), \
             patch.object(reassess.evaluate, 'run_evaluator') as runner:
            with self.assertRaises(ValueError): reassess.execute(relocated, repo=self.repo)
        runner.assert_not_called()
        self.assertFalse((relocated/'output').exists())


if __name__ == '__main__': unittest.main()
