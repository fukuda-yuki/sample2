"""An absent publish cannot invent product failure or mask an observer fault."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

try:
    from . import support
except ImportError:
    import support
from harness import browser_cart, education_browser, util


class BrowserPrerequisiteTests(unittest.TestCase):
    families = ((browser_cart, '1.3.0', 'MS1-CONT-A', 'R-001', 'C-001', 'browserCartCoverage'),
                (education_browser, 'education-1.0.0', 'CU1-ENR-C', 'EDU-R-001', 'E-001', 'browserReviewCoverage'),
                (education_browser, 'education-1.0.0', 'CU1-ENR-D', 'EDU-R-001', 'E-001', 'browserReviewCoverage'))

    def fixture(self, family):
        module, version, task, requirement, check, coverage = family
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        frozen, baseline, published, assets, out = (root/p for p in ('frozen','baseline','publish','assets','output'))
        for path in (frozen, baseline, published, assets/'evaluator', out): path.mkdir(parents=True)
        (frozen/'Program.cs').write_text('// saved synthetic target', encoding='utf-8')
        (assets/'evaluator/evaluator.dll').write_bytes(b'synthetic evaluator identity')
        (assets/'initial-store.sqlite').write_bytes(b'synthetic unused browser setup')
        util.write_new_json(assets/'requirements.json', {'taskId':task, 'requirements':[]})
        artifact, spec = util.artifact_hash(frozen), util.sha256_file(assets/'requirements.json')
        condition = {'schema_version':2, 'task_id':task,
                     'evaluation':{'evaluation_version':version, 'spec_sha256':spec, 'assembly':'evaluator.dll'},
                     'runtime_lock':{'images':{'evaluator':'synthetic-image'}}}
        output = {'taskId':task, 'evaluationVersion':version, 'artifactPath':'/artifact',
                  'artifactSha256':artifact, 'specSha256':spec, 'verdict':'fail_critical',
                  'quality':0, 'researchStatus':'incomplete', 'evaluatorFaults':[], 'criticalFailed':[requirement],
                  'requirements':[{'id':requirement,'judgement':'fail'}]}
        util.write_new_json(baseline/'evaluation.json', output)
        util.write_new_json(baseline/'evaluator-manifest.json', {'evaluatorSha256':util.sha256_file(assets/'evaluator/evaluator.dll')})
        (baseline/'results.jsonl').write_text(json.dumps({'requirementId':requirement,'checkId':check,'judgement':'fail'})+'\n',encoding='utf-8')
        return root, condition, frozen, baseline, published, assets, out, output

    def run_adapter(self, family, fixture):
        module = family[0]
        root, condition, frozen, baseline, published, assets, out, original = fixture
        # Any attempted launch here is an observer fault. The product-prerequisite
        # case must bypass launch/composition altogether.
        with patch.object(module.runtime, 'docker', side_effect=RuntimeError('Observer dependency unavailable')) as launch:
            if module is browser_cart:
                with patch.object(module, 'compose_evaluation', side_effect=RuntimeError('Observer unavailable')):
                    code = module.complete_evaluation(root, condition, frozen, baseline, published, assets, out, 'instance', 1)
            else:
                code = module.complete_evaluation(root, condition, frozen, baseline, published, assets, out, 'instance', 1)
        return code, util.read_json(out/'evaluation.json'), launch.call_count

    def test_bound_build_failure_without_publish_is_incomplete_product_failure_for_both_families(self):
        for family in self.families:
            with self.subTest(task=family[2]):
                fixture = self.fixture(family)
                before = util.tree_hashes(fixture[3])
                code, output, launches = self.run_adapter(family, fixture)
                self.assertEqual(0, code); self.assertEqual(0, launches)
                self.assertEqual('not_run_product_prerequisite', output[family[5]])
                self.assertEqual('fail_critical', output['verdict']); self.assertIsNone(output['quality'])
                self.assertEqual('incomplete', output['researchStatus']); self.assertEqual([], output['evaluatorFaults'])
                self.assertEqual(before, util.tree_hashes(fixture[3]))
                out = fixture[6]; self.assertFalse((out/'browser-fault.json').exists())
                self.assertTrue(util.read_json(out/'browser-cleanup.json')['confirmed'])
                failure = family[0].stored_failure(out, 'instance', output['artifactSha256'], output['specSha256'],
                                                  util.sha256_file(out/'evaluation.json'), baseline_directory=fixture[3])
                self.assertEqual({'verdict':'fail_critical','requirements':[family[3]],'source':'http-only'}, failure)

    def test_missing_publish_without_confirmed_build_check_keeps_observer_fault(self):
        for family in self.families:
            with self.subTest(task=family[2]):
                fixture = self.fixture(family)
                (fixture[3]/'results.jsonl').write_text(json.dumps({'requirementId':family[3],'checkId':family[4],'judgement':'pass'})+'\n')
                code, output, _ = self.run_adapter(family, fixture)
                self.assertEqual(2, code); self.assertNotEqual('not_run_product_prerequisite', output[family[5]])
                self.assertTrue(output['evaluatorFaults'])

    def test_bound_build_failure_with_published_application_keeps_real_observer_fault(self):
        for family in self.families:
            with self.subTest(task=family[2]):
                fixture = self.fixture(family)
                (fixture[4]/'App.runtimeconfig.json').write_text('{}'); (fixture[4]/'App.dll').write_bytes(b'published')
                code, output, launches = self.run_adapter(family, fixture)
                self.assertEqual(2, code); self.assertGreaterEqual(launches, 1)
                self.assertNotEqual('not_run_product_prerequisite', output[family[5]])
                self.assertTrue(output['evaluatorFaults'])

    def test_unbound_or_faulting_baseline_never_becomes_product_prerequisite(self):
        for family in self.families:
            for changed in ('task', 'dll', 'observer'):
                with self.subTest(task=family[2], changed=changed):
                    fixture = self.fixture(family)
                    if changed == 'dll': util.write_json_atomic(fixture[3]/'evaluator-manifest.json', {'evaluatorSha256':'other'})
                    else:
                        output = fixture[7]
                        if changed == 'task': output['taskId'] = 'other'
                        else: output['evaluatorFaults'] = ['SDK observer unavailable']
                        util.write_json_atomic(fixture[3]/'evaluation.json', output)
                    code, output, _ = self.run_adapter(family, fixture)
                    self.assertEqual(2, code); self.assertNotEqual('not_run_product_prerequisite', output[family[5]])
                    self.assertTrue(output['evaluatorFaults'])


if __name__ == '__main__': unittest.main()
