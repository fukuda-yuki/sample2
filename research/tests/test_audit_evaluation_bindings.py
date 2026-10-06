import json
from pathlib import Path
import tempfile
import unittest

from research import audit_evaluation_bindings as audit


class BindingAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'fixture-run'
        self.root.mkdir()
        self.write('frozen/app.cs', b'// synthetic artifact\n')
        self.write('inputs/prompt.txt', b'synthetic prompt')
        self.write('evaluation-assets/evaluator/Test.dll', b'not executable fixture bytes')
        self.write('evaluation-assets/initial-store.sqlite', b'not a SQLite file; never opened')
        self.js('evaluation-assets/catalog.json', {})
        self.js('evaluation-assets/migration-oracle.json', {'task_id': 'test', 'variant': 'A'})
        self.js('evaluation-assets/requirements.json', {'taskId': 'test', 'specVersion': 'test-1',
                'requirements': [{'id': 'R1', 'checks': [{'id': 'C1'}]}]})
        self.js('inputs-manifest.json', {'inputs': {}})
        files = audit.inventory(self.root / 'evaluation-assets')
        self.condition = {'task_id': 'test', 'semantic_variant': 'A', 'condition_id': 'dummy',
                'evaluation': {'spec_path': 'evaluation-assets/requirements.json',
                 'spec_sha256': files['requirements.json']['sha256'], 'evaluation_version': 'test-1',
                 'assembly': 'Test.dll', 'evaluator_sha256': files['evaluator/Test.dll']['sha256'],
                 'evaluator_build': {k: 'synthetic' for k in ['source_commit', 'source_path', 'command', 'sdk_version', 'sha256_origin']}},
                'runtime_lock': {'evaluator_sha256': files['evaluator/Test.dll']['sha256'],
                 'evaluator_files': {'Test.dll': files['evaluator/Test.dll']}}}
        self.js('condition.json', self.condition)
        frozen = audit.inventory(self.root / 'frozen')
        self.js('snapshot.json', {'frozen': frozen, 'artifact_sha256': audit.tree_digest(frozen)})
        self.manifest = {'task_id': 'test', 'condition_sha256': audit.digest(self.root / 'condition.json'),
                'inputs_manifest_sha256': audit.digest(self.root / 'inputs-manifest.json'),
                'prompt_sha256': audit.digest(self.root / 'inputs/prompt.txt'), 'assets_sha256': files,
                'submission_fixed': True, 'stop_confirmed': True, 'run_instance_id': 'fixture-uuid'}
        self.js('manifest.json', self.manifest)
        self.row = {'run_id': self.root.name, 'evaluation_id': 'fixture-eval', 'directory': 'evaluations/fixture-eval',
                    'evaluation_version': 'test-1', 'spec_sha256': files['requirements.json']['sha256'],
                    'evaluator_sha256': files['evaluator/Test.dll']['sha256'], 'artifact_sha256_outer': audit.tree_digest(frozen),
                    'scoring_state': 'evaluation_incomplete'}
        self.write('evaluations/index.jsonl', (json.dumps(self.row) + '\n').encode())
        self.js('evaluations/fixture-eval/record.json', self.row)
        self.js('evaluations/fixture-eval/evaluator-manifest.json', {'evaluationVersion': 'test-1',
                'evaluatorSha256': self.row['evaluator_sha256'], 'specSha256': self.row['spec_sha256'],
                'artifactSha256': self.row['artifact_sha256_outer'], 'implementedCheckIds': ['C1']})
        self.write('evaluations/fixture-eval/results.jsonl', (json.dumps({'requirementId': 'R1', 'checkId': 'C1', 'judgement': 'blocked'}) + '\n').encode())

    def write(self, relative, data):
        p = self.root / relative
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def js(self, relative, value):
        self.write(relative, (json.dumps(value) + '\n').encode())

    def test_bound_partial_input_is_candidate_but_not_approved_quality(self):
        result = audit.audit_run(self.root)
        self.assertEqual([], result['issues'])
        self.assertTrue(result['asset_binding_eligible_for_separate_reassessment'])
        self.assertEqual({'blocked': 1}, result['evaluations'][0]['judgements'])
        self.assertIn('finite_check_semantics_not_approved_by_hash_or_manifest_ID_match', result['unknowns'])

    def test_hash_corruption_excludes_candidate(self):
        self.write('evaluation-assets/migration-oracle.json', b'{"task_id":"test","variant":"A","tampered":true}')
        result = audit.audit_run(self.root)
        self.assertFalse(result['asset_binding_eligible_for_separate_reassessment'])
        self.assertIn('hash_mismatch', [x['kind'] for x in result['issues']])

    def test_unimplemented_ledger_check_is_binding_issue(self):
        p = 'evaluations/fixture-eval/evaluator-manifest.json'
        value = audit.load(self.root / p)
        value['implementedCheckIds'] = []
        self.js(p, value)
        self.assertTrue(any(x['reference'].endswith('/implementedCheckIds') for x in audit.audit_run(self.root)['issues']))

    def test_absent_manifest_remains_unknown(self):
        (self.root / 'evaluations/fixture-eval/evaluator-manifest.json').unlink()
        result = audit.audit_run(self.root)
        self.assertIn('actual_build_implemented_check_ID_manifest_missing', result['unknowns'])

    def test_audit_does_not_modify_original_files_or_open_sqlite(self):
        before = {str(p.relative_to(self.root)): (audit.digest(p), p.stat().st_mtime_ns)
                  for p in self.root.rglob('*') if p.is_file()}
        audit.audit_run(self.root)
        after = {str(p.relative_to(self.root)): (audit.digest(p), p.stat().st_mtime_ns)
                 for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_foreign_references_rejected(self):
        for name in ['../foreign', 'C:/foreign', '//host/share', 'dir/../../foreign']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                audit.inside(self.root, name)

    def test_unconfirmed_stop_is_not_reassessment_candidate(self):
        self.manifest['stop_confirmed'] = False
        self.js('manifest.json', self.manifest)
        self.assertFalse(audit.audit_run(self.root)['asset_binding_eligible_for_separate_reassessment'])

    def test_duplicate_result_cannot_be_counted_as_complete(self):
        p = self.root / 'evaluations/fixture-eval/results.jsonl'
        self.write(str(p.relative_to(self.root)), p.read_bytes() * 2)
        self.assertIn('saved_results_missing_or_duplicate_check_rows', audit.audit_run(self.root)['unknowns'])

    def test_saved_build_DLL_is_compared_to_actual_bytes(self):
        value = json.loads(json.dumps(self.condition))
        value['evaluation']['evaluator_build']['sha256_origin'] = 'evaluation-assets'
        result = audit.audit_saved_build(value, self.root)
        self.assertTrue(result['saved_build_DLL_matches'])
        self.assertEqual('unknown_without_independent_rebuild', result['compile_source_to_binary'])
        self.write('evaluation-assets/evaluator/Test.dll', b'tampered build bytes')
        self.assertFalse(audit.audit_saved_build(value, self.root)['saved_build_DLL_matches'])


if __name__ == '__main__':
    unittest.main()
