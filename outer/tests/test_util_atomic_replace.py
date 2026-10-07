"""Bounded Windows sharing-violation retry of the atomic JSON replacement."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from outer.harness import util


class AtomicReplaceRetryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'status.json'
        util.write_json_atomic(self.path, {'v': 0})

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
        with patcher, patch.object(util.time, 'sleep') as sleep:
            util.write_json_atomic(self.path, {'v': 1})
        self.assertEqual(util.read_json(self.path), {'v': 1})
        self.assertEqual(state['n'], 3); self.assertEqual(sleep.call_count, 3)
        self.assertEqual(list(self.path.parent.glob('*.tmp')), [])

    def test_persistent_denial_still_raises_and_retains_temp(self):
        patcher, _ = self.flaky(10 ** 6)
        with patcher, patch.object(util.time, 'sleep'), self.assertRaises(PermissionError):
            util.write_json_atomic(self.path, {'v': 2})
        self.assertEqual(util.read_json(self.path), {'v': 0})
        self.assertEqual(len(list(self.path.parent.glob('*.tmp'))), 1)

    def test_other_errors_are_not_retried(self):
        def replace(source, target): raise FileNotFoundError(2, 'gone')
        with patch.object(Path, 'replace', replace), patch.object(util.time, 'sleep') as sleep, \
                self.assertRaises(FileNotFoundError):
            util.write_json_atomic(self.path, {'v': 3})
        sleep.assert_not_called()

    def test_real_concurrent_reader_does_not_break_writer(self):
        import threading, time
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
            try: util.write_json_atomic(self.path, {'v': n}); n += 1
            except PermissionError as exc: errors.append(exc)
            time.sleep(0.02)
        for t in threads: t.join()
        self.assertEqual(errors, []); self.assertGreater(n, 10)


if __name__ == '__main__':
    unittest.main()
