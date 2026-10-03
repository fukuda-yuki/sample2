import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from outer.harness import util
from outer.harness.security import child_environment
from research.catalog_environment import activated, validate


class CatalogEnvironmentTests(unittest.TestCase):
    def test_scoring_receives_pinned_paths_and_restores_host_on_failure(self):
        import os
        from research.next_phase_execution import browser_postprocess
        env = {'NODE_PATH': 'pinned-modules', 'SAMPLE2_BROWSER_EXECUTABLE': 'pinned-browser'}
        def ordinary(repo, batch, rid, archive):
            self.assertEqual(os.environ['NODE_PATH'], 'pinned-modules')
            self.assertEqual(os.environ['SAMPLE2_BROWSER_EXECUTABLE'], 'pinned-browser')
            self.assertEqual(os.environ['SAMPLE2_NODE'], 'pinned-node')
            actual = child_environment({k: os.environ[k] for k in env})
            self.assertNotIn('fixture-secret', actual.values())
            raise RuntimeError('scorer fault must restore host paths')
        with patch.dict(os.environ, {'NODE_PATH': 'before', 'SAMPLE2_BROWSER_EXECUTABLE': 'before-browser', 'SAMPLE2_NODE': 'before-node',
                'OPENCODE_GO_API_KEY': 'fixture-secret'}), patch('research.catalog_environment.validate', return_value=env), patch('outer.harness.machine.postprocess', side_effect=ordinary):
            callback = browser_postprocess({'browser': {'record': {'fixture': True, 'node_path': 'pinned-node'}}})
            with self.assertRaises(RuntimeError): callback('.', '.', 'fixture', '.')
            self.assertEqual(os.environ['NODE_PATH'], 'before')
            self.assertEqual(os.environ['SAMPLE2_BROWSER_EXECUTABLE'], 'before-browser')
            self.assertEqual(os.environ['SAMPLE2_NODE'], 'before-node')

    def test_pinned_dependency_change_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name in ('node.exe','chrome.exe','probe.json','modules/playwright/index.js',
                         'modules/playwright-core/index.js','inner/browser/cart-review.cjs'):
                file=root/name; file.parent.mkdir(parents=True,exist_ok=True); file.write_text('fixed')
            record={'environment':{'NODE_PATH':str(root/'modules'),'SAMPLE2_BROWSER_EXECUTABLE':str(root/'chrome.exe')},
                'node_path':str(root/'node.exe'),'node_sha256':util.sha256_file(root/'node.exe'),
                'browser_sha256':util.sha256_file(root/'chrome.exe'),
                'collector_sha256':util.sha256_file(root/'inner/browser/cart-review.cjs'),
                'dependency_hashes':{n:util.tree_hashes(root/'modules'/n) for n in ('playwright','playwright-core')},
                'probe_file':str(root/'probe.json'),'probe_sha256':util.sha256_file(root/'probe.json')}
            with patch('shutil.which',return_value=str(root/'node.exe')):
                self.assertEqual(validate(record,root),record['environment'])
                (root/'modules/playwright/index.js').write_text('changed')
                with self.assertRaises(ValueError): validate(record,root)

    def test_forwarding_browser_paths_does_not_forward_provider_credentials(self):
        import os
        env={'NODE_PATH':'existing-modules','SAMPLE2_BROWSER_EXECUTABLE':'existing-browser'}
        with patch.dict(os.environ,{'OPENCODE_GO_API_KEY':'do-not-copy','UNRELATED_SECRET':'do-not-copy'}):
            actual=child_environment(env)
        self.assertEqual(actual['NODE_PATH'],env['NODE_PATH'])
        self.assertEqual(actual['SAMPLE2_BROWSER_EXECUTABLE'],env['SAMPLE2_BROWSER_EXECUTABLE'])
        self.assertNotIn('do-not-copy',actual.values())

    def test_extra_environment_fields_are_rejected_before_reading_dependencies(self):
        with self.assertRaises(ValueError):
            validate({'environment':{'NODE_PATH':'modules','SAMPLE2_BROWSER_EXECUTABLE':'browser','UNRELATED_SECRET':'x'}},'.')
