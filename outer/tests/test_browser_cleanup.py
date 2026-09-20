"""Recovery must prove ownership/absence and never re-run an evaluation."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
import io
from unittest.mock import patch

try:
    from . import support
except ImportError:
    import support
from harness import browser_cart, browser_cleanup, cli, evaluate, ownership, runtime, util


class BrowserCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.name = 's2-browser-' + 'a' * 32
        self.network = self.name + '-net'
        self.owner = browser_cleanup.register(self.root, 'instance', 'container', self.name, 'container-id')
        browser_cleanup.register(self.root, 'instance', 'network', self.network, 'network-id')
        self.resources = {
            'container-id': {'Id': 'container-id', 'Name': '/' + self.name,
                             'Config': {'Labels': {'sample2.browser-review': self.owner}}},
            'network-id': {'Id': 'network-id', 'Name': self.network, 'Labels': {'sample2.browser-review': self.owner},
                           'Driver': 'bridge', 'Containers': {}},
        }
        self.commands = []
        self.fail = None

    def docker(self, *args, **kwargs):
        self.commands.append(args)
        kind = 'network' if args[0] == 'network' else 'container'
        key = kind + '-id'
        if args[0] == 'ps' or args[:2] == ('network', 'ls'):
            value = self.resources.get(key)
            data = [] if not value else [{'ID': key, 'Names' if kind == 'container' else 'Name': value['Name'].lstrip('/')}]
            return subprocess.CompletedProcess(args, 0, '\n'.join(json.dumps(v) for v in data), '')
        if args[0] == 'inspect' or args[:2] == ('network', 'inspect'):
            return subprocess.CompletedProcess(args, 0, json.dumps([self.resources[key]]), '')
        if args[0] == 'rm' or args[:2] == ('network', 'rm'):
            if self.fail == kind:
                raise RuntimeError('injected remove failure')
            self.assertEqual(key, args[-1], 'Deletion must use freshly inspected ID, not a recycled name')
            del self.resources[key]
            return subprocess.CompletedProcess(args, 0, key, '')
        raise AssertionError('Unexpected cleanup operation: ' + str(args))

    def clean(self):
        with patch.object(runtime, 'docker', self.docker):
            return browser_cleanup.cleanup(self.root)

    def test_container_and_network_failures_are_retryable_without_observation(self):
        for kind in ('container', 'network'):
            with self.subTest(kind=kind):
                resources = json.loads(json.dumps(self.resources))
                self.fail = kind
                failed = self.clean()
                self.assertFalse(failed['confirmed'])
                self.assertEqual('cleanup_failed', failed['status'])
                self.assertFalse(failed['model_called'])
                self.assertFalse(failed['browser_observed'])
                self.fail = None
                self.assertTrue(self.clean()['confirmed'])
                self.assertTrue(self.clean()['confirmed'], 'An absence-confirmed retry is idempotent')
                self.resources = resources
        self.assertEqual(6, len(util.read_lines(self.root/'browser-cleanup-attempts/index.jsonl')))

    def test_foreign_container_is_not_removed(self):
        self.resources['container-id']['Config']['Labels'] = {'sample2.browser-review': 'foreign'}
        self.assertFalse(self.clean()['confirmed'])
        self.assertIn('container-id', self.resources)
        self.assertFalse(any(c[0] == 'rm' for c in self.commands))

    def test_same_name_with_different_id_is_not_removed(self):
        self.resources['container-id']['Id'] = 'replacement-id'
        self.assertFalse(self.clean()['confirmed'])
        self.assertFalse(any(c[0] == 'rm' for c in self.commands))

    def test_network_with_foreign_endpoint_is_not_removed(self):
        self.resources['network-id']['Containers'] = {'foreign': {}}
        self.assertFalse(self.clean()['confirmed'])
        self.assertIn('network-id', self.resources)

    def test_daemon_failure_is_not_absence(self):
        with patch.object(runtime, 'docker', side_effect=RuntimeError('daemon unavailable')):
            self.assertFalse(browser_cleanup.cleanup(self.root)['confirmed'])
        self.assertEqual(2, len(self.resources))

    def test_active_controller_blocks_recovery(self):
        with ownership.lease(self.root), patch.object(runtime, 'docker') as docker:
            with self.assertRaises(BlockingIOError):
                browser_cleanup.cleanup(self.root)
        docker.assert_not_called()

    def test_quality_pass_cannot_make_score_cli_succeed_after_cleanup_failure(self):
        result = {'scoring_state': 'scored', 'verdict': 'pass', 'quality': 100, 'operation_status': 'cleanup_failed'}
        with patch.object(evaluate, 'score_run', return_value=result), redirect_stdout(io.StringIO()):
            code = cli.main(['--repo', str(self.root), 'score', '--run', 'sample'])
        self.assertEqual(1, code)
        self.assertEqual('pass', result['verdict'])

    def test_cleanup_failure_does_not_mask_a_prior_composition_fault(self):
        for evaluator_code, expected in ((0, 3), (2, 2)):
            with self.subTest(evaluator_code=evaluator_code), \
                    patch.object(browser_cart, '_compose_evaluation', return_value=evaluator_code), \
                    patch.object(browser_cleanup, 'cleanup', return_value={'confirmed': False}):
                code = browser_cart.compose_evaluation({}, self.root, self.root, self.root, self.root, 'instance', 1)
            self.assertEqual(expected, code)


if __name__ == '__main__':
    unittest.main()
