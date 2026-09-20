import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from outer.harness import util
from outer.harness.security import child_environment
from research.catalog_environment import validate


class CatalogEnvironmentTests(unittest.TestCase):
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
