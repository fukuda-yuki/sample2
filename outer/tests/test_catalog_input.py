"""The installed packet and the gateway's fail-closed transmission boundary."""
import copy
from pathlib import Path
import tempfile
import unittest

from support import write_text
from harness import catalog_input, gateway, profiles, util

REPO = Path(__file__).resolve().parents[2]


class CatalogInputTests(unittest.TestCase):
    def test_only_packet_differs_and_legacy_runtime_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_text(Path(tmp)/'common.json', '{"common":"same"}\n')
            write_text(Path(tmp)/'raw-first.txt', 'CATALOG_SOURCE header\nsource\n')
            prompts = []
            for arm in ('catalog-expanded', 'catalog-compact'):
                c = profiles.resolve(REPO, 'MS1-001', arm, 'deepseek-catalog-v1')
                prompts.append(profiles.prepare_prompt(c, tmp, tmp)[0])
                self.assertNotIn(arm, prompts[-1])
            self.assertEqual(prompts[0], prompts[1] + (Path(tmp)/'raw-first.txt').read_text())
            self.assertIn('/inputs/legacy-source', prompts[0])
        with self.assertRaises(ValueError):
            profiles.resolve(REPO, 'MS1-001', 'catalog-compact', 'deepseek')
        old = profiles.read(REPO, 'runtimes', 'deepseek')
        new = profiles.read(REPO, 'runtimes', 'deepseek-catalog-v1')
        for key in old.keys() - {'id'}:
            self.assertEqual(old[key], new[key], key)

    def test_gateway_refuses_truncation_duplicates_or_wrong_role(self):
        expected = 'common\nCATALOG_SOURCE header\n' + 'line\n' * 20000
        request = {'messages': [{'role': 'system', 'content': 'unchanged'},
                                {'role': 'user', 'content': expected}]}
        self.assertTrue(gateway.check_initial_input(request, expected)['verified'])
        for value in (expected[:-1], expected + expected, expected + 'CATALOG_SOURCE extra'):
            damaged = copy.deepcopy(request)
            damaged['messages'][1]['content'] = value
            self.assertFalse(gateway.check_initial_input(damaged, expected)['verified'])
        request['messages'][1]['role'] = 'tool'
        self.assertFalse(gateway.check_initial_input(request, expected)['verified'])

    def test_compact_refuses_an_added_source_packet(self):
        body = {'messages':[{'role':'user','content':'common\nCATALOG_SOURCE extra'}]}
        self.assertFalse(gateway.check_initial_input(body, 'common\n')['verified'])


if __name__ == '__main__':
    unittest.main()
