"""Observer status pointer replace race and receipt verification under own pins."""
import os
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from outer.harness import util
from research import resource_supervisor as supervisor


class PublishPointerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'status.json'
        supervisor.publish_pointer(self.path, {'v': 0})

    def flaky(self, failures):
        real = Path.replace; state = {'n': 0}
        def replace(source, target):
            if state['n'] < failures:
                state['n'] += 1
                raise PermissionError(13, 'sharing violation')
            return real(source, target)
        return patch.object(Path, 'replace', replace), state

    @unittest.skipUnless(os.name == 'nt', 'Windows sharing semantics')
    def test_transient_sharing_violation_is_retried(self):
        patcher, state = self.flaky(3)
        with patcher, patch.object(supervisor.time, 'sleep') as sleep:
            supervisor.publish_pointer(self.path, {'v': 1})
        self.assertEqual(util.read_json(self.path), {'v': 1})
        self.assertEqual((state['n'], sleep.call_count), (3, 3))
        self.assertEqual(list(self.path.parent.glob('*.tmp')), [])

    def test_persistent_denial_raises_and_retains_evidence(self):
        patcher, _ = self.flaky(10 ** 6)
        with patcher, patch.object(supervisor.time, 'sleep'), self.assertRaises(PermissionError):
            supervisor.publish_pointer(self.path, {'v': 2})
        self.assertEqual(util.read_json(self.path), {'v': 0})
        self.assertEqual(len(list(self.path.parent.glob('*.tmp'))), 1)

    def test_other_errors_are_not_retried(self):
        def replace(source, target): raise FileNotFoundError(2, 'gone')
        with patch.object(Path, 'replace', replace), patch.object(supervisor.time, 'sleep') as sleep, \
                self.assertRaises(FileNotFoundError):
            supervisor.publish_pointer(self.path, {'v': 3})
        sleep.assert_not_called()

    def test_publish_uses_pointer_writer(self):
        source = Path(supervisor.__file__).read_text(encoding='utf-8')
        body = source[source.index('    def publish(self):'):source.index('    def enroll(self):')]
        self.assertIn("publish_pointer(self.directory / 'status.json'", body)
        self.assertNotIn('write_json_atomic', body)

    def test_concurrent_controller_readers_do_not_fault_writer(self):
        stop = time.monotonic() + 2; errors = []
        def reader():
            while time.monotonic() < stop:
                try: util.read_json(self.path)
                except (PermissionError, FileNotFoundError, ValueError): pass
                time.sleep(0.02)
        threads = [threading.Thread(target=reader) for _ in range(2)]
        for t in threads: t.start()
        n = 0
        while time.monotonic() < stop:
            try: supervisor.publish_pointer(self.path, {'v': n}); n += 1
            except PermissionError as exc: errors.append(exc)
            time.sleep(0.02)
        for t in threads: t.join()
        self.assertEqual(errors, []); self.assertGreater(n, 10)


class StartupReceiptPinTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        phase_path = root / 'phase.json'; util.write_new_json(phase_path, {'kind': 'fixture'})
        self.session = uuid.uuid4().hex
        directory = root / '_observers' / self.session
        self.config = dict(phase=dict(path=str(phase_path), sha256=util.sha256_file(phase_path)),
                           session=self.session, directory=str(directory))
        util.write_new_json(directory / 'config.json', self.config)
        self.historical = 'a' * 64  # Older supervisor source pinned by its own phase.
        self.phase = {'source_pins': {'research/resource_supervisor.py': self.historical}}
        self.receipt = dict(schema_version=1, kind='resource_observer_startup_ready_v1', validated=True,
            session=self.session, phase=self.config['phase'], directory=self.config['directory'],
            config_sha256=util.sha256_file(directory / 'config.json'), observer_pid=1234,
            source_sha256=self.historical, ready_at='t')

    def test_historical_receipt_verifies_under_its_own_phase_pins(self):
        self.assertTrue(supervisor.validate_startup_ready(self.config, self.phase, 1234, self.receipt,
                                                          current_source=False))

    def test_live_verification_still_requires_executing_source(self):
        with self.assertRaises(ValueError):
            supervisor.validate_startup_ready(self.config, self.phase, 1234, self.receipt)
        current = util.sha256_file(supervisor.__file__)
        live = dict(self.receipt, source_sha256=current)
        self.assertTrue(supervisor.validate_startup_ready(
            self.config, {'source_pins': {'research/resource_supervisor.py': current}}, 1234, live))

    def test_historical_receipt_must_match_its_phase_pin_and_bindings(self):
        for change in (dict(source_sha256='b' * 64), dict(observer_pid=99), dict(config_sha256='c' * 64)):
            with self.subTest(change=change), self.assertRaises(ValueError):
                supervisor.validate_startup_ready(self.config, self.phase, 1234, dict(self.receipt, **change),
                                                  current_source=False)


if __name__ == '__main__':
    unittest.main()
