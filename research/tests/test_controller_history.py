import subprocess, tempfile, unittest
from pathlib import Path
from unittest import mock

from research import campaign_recovery as recovery
from outer.harness import util


def git(repo, *args):
    return subprocess.run(['git', '-c', 'core.autocrlf=false', *args], cwd=repo, check=True,
                          capture_output=True, text=True).stdout.strip()


class ControllerHistoryTests(unittest.TestCase):
    """A recorded controller stays verifiable after its checkout advances."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)/'code'; (self.repo/'research').mkdir(parents=True)
        git(self.repo, 'init', '-q'); git(self.repo, 'config', 'user.email', 't@t'); git(self.repo, 'config', 'user.name', 't')
        self.file = self.repo/'research'/'campaign_recovery.py'
        self.file.write_bytes(b'version = 1\n'); git(self.repo, 'add', '-A'); git(self.repo, 'commit', '-qm', 'a')
        self.first = git(self.repo, 'rev-parse', 'HEAD')
        self.pins = {'research/campaign_recovery.py': util.sha256_file(self.file)}
        patcher = mock.patch.object(recovery, '_controller_names', return_value=set()); patcher.start(); self.addCleanup(patcher.stop)

    def value(self, commit=None, pins=None):
        pins = pins or self.pins
        return dict(kind=recovery.CONTROLLER_KIND, source_repo=str(self.repo), source_commit=commit or self.first,
                    source_pins=pins, pins_sha256=recovery._pins_digest(pins), entrypoint='research/campaign_recovery.py',
                    clean_committed_at_creation=True)

    def advance(self):
        self.file.write_bytes(b'version = 2\n'); git(self.repo, 'commit', '-qam', 'b')

    def test_current_checkout_still_strict(self):
        self.assertEqual(recovery._validate_controller(self.value(), {}), self.value())

    def test_advanced_checkout_verifies_recorded_commit_from_history(self):
        self.advance()
        self.assertEqual(recovery._validate_controller(self.value(), {}), self.value())

    def test_advanced_checkout_with_wrong_pin_rejected(self):
        self.advance()
        with self.assertRaisesRegex(ValueError, 'source changed'):
            recovery._validate_controller(self.value(pins={'research/campaign_recovery.py': 'f'*64}), {})

    def test_dirty_advanced_checkout_rejected(self):
        self.advance(); self.file.write_bytes(b'dirty\n')
        with self.assertRaisesRegex(ValueError, 'checkout changed'):
            recovery._validate_controller(self.value(), {})

    def test_commit_not_in_checkout_history_rejected(self):
        git(self.repo, 'checkout', '-qb', 'side'); self.file.write_bytes(b'side\n'); git(self.repo, 'commit', '-qam', 's')
        side = git(self.repo, 'rev-parse', 'HEAD')
        pins = {'research/campaign_recovery.py': util.sha256_file(self.file)}
        git(self.repo, 'checkout', '-q', '-'); self.advance()
        with self.assertRaisesRegex(ValueError, 'checkout changed: commit is not retained history'):
            recovery._validate_controller(self.value(commit=side, pins=pins), {})


if __name__ == '__main__':
    unittest.main()
