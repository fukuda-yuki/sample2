"""Preservation invariants, re-checked at the porting destination.

The invariants come from sample1 scripts/test_preservation.py. Passing them in
sample1 is not evidence for this copy, so they are run here.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from . import support  # noqa: F401  (puts outer/ on sys.path)
except ImportError:  # started as a top-level module (discover -s outer/tests)
    import support  # noqa: F401
from harness.preserve import digest, pack, restore, safe_name, verify, verify_receipt


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        (self.source / 'a').write_text('original')
        self.archive = self.root / 'archive'

    def test_restore_without_source_and_reference_validation(self):
        common = pack(self.archive, 'common', {'files': self.source})
        run = pack(self.archive, 'run', {'submission': self.source}, references=[common])
        (self.source / 'a').unlink()
        receipt = restore(self.archive, run, self.root / 'restored')
        self.assertEqual((self.root / 'restored/submission/a').read_text(), 'original')
        self.assertEqual(verify_receipt(self.archive, receipt)['reference'], run)
        (self.archive / 'packages/common/payload/files/a').unlink()
        with self.assertRaises(ValueError):
            verify(self.archive, run['package_id'], run['sha256'])

    def test_extra_missing_modified_and_index_tampering(self):
        for mutation in ('extra', 'missing', 'modified', 'index'):
            with self.subTest(mutation=mutation):
                ref = pack(self.archive, mutation, {'a': self.source / 'a'})
                package = self.archive / 'packages' / mutation
                if mutation == 'extra':
                    (package / 'payload/extra').write_text('x')
                if mutation == 'missing':
                    (package / 'payload/a').unlink()
                if mutation == 'modified':
                    (package / 'payload/a').write_text('x')
                if mutation == 'index':
                    (package / 'package.json').write_text('{}')
                with self.assertRaises(ValueError):
                    restore(self.archive, ref, self.root / mutation)

    def test_failed_copy_never_publishes_or_reuses_id(self):
        with patch('harness.preserve.shutil.copy2', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                pack(self.archive, 'interrupted', {'a': self.source / 'a'})
        self.assertFalse((self.archive / 'packages/interrupted').exists())
        with self.assertRaises(FileExistsError):
            pack(self.archive, 'interrupted', {'a': self.source / 'a'})

    def test_interrupted_owned_restoration_is_retained_and_recovered(self):
        ref = pack(self.archive, 'copy-recovery', {'files': self.source})
        target = self.root / 'copy'

        def interrupted(source, destination):
            destination.mkdir()
            (destination / 'partial').write_text('incomplete')
            raise OSError('interrupted')

        with patch('harness.preserve.shutil.copytree', side_effect=interrupted):
            with self.assertRaises(OSError):
                restore(self.archive, ref, target)
        receipt = restore(self.archive, ref, target, resume=True)
        self.assertEqual((target / 'files/a').read_text(), 'original')
        self.assertEqual(len(list(self.root.glob('copy.interrupted-*'))), 1)
        self.assertEqual(verify_receipt(self.archive, receipt)['reference'], ref)
        (target / 'files/a').write_text('changed after completion')
        with self.assertRaises(ValueError):
            restore(self.archive, ref, target, resume=True)

    def test_paths_links_and_same_storage_rejected(self):
        for name in ('../x', '/x', 'a/../x', 'C:x', 'a\\x', 'a//x'):
            with self.assertRaises(ValueError):
                safe_name(name)
        with self.assertRaises(ValueError):
            pack(self.source / 'archive', 'nested', {'all': self.source})
        try:
            (self.source / 'link').symlink_to(self.source / 'a')
        except OSError:
            return
        with self.assertRaises(ValueError):
            pack(self.archive, 'link', {'all': self.source})

    def test_receipt_tampering(self):
        ref = pack(self.archive, 'receipt', {'files': self.source})
        receipt = restore(self.archive, ref, self.root / 'restore')
        (self.archive / receipt['path']).write_text('{}')
        with self.assertRaises(ValueError):
            verify_receipt(self.archive, receipt)

    def test_ensure_package_recovers_without_overwriting(self):
        from harness.preserve import ensure_package
        first = pack(self.archive, 'recover', {'files': self.source})
        again = ensure_package(self.archive, 'recover', {'files': self.source})
        self.assertEqual(first['sha256'], again['sha256'])
        with self.assertRaises(ValueError):
            ensure_package(self.archive, 'recover', {'files': self.source / 'a'})


class PackRunTests(unittest.TestCase):
    def test_missing_and_skipped_are_recorded_separately(self):
        from harness import preserve, util
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        run = root / 'runs' / 'T-1'
        (run / 'frozen').mkdir(parents=True)
        (run / 'frozen' / 'a.txt').write_text('x')
        util.write_new_json(run / 'manifest.json', {'run_id': 'T-1', 'stop_confirmed': True,
                                                   'submission_fixed': True,
                                                   'end_reason': 'completed'})
        result = preserve.pack_run(root / 'archive', run)
        data = verify(root / 'archive', result['package_id'], result['sha256'])
        self.assertIn('snapshot.json', data['metadata']['missing'])
        self.assertIn('workspace', data['metadata']['skipped_by_choice'])
        self.assertNotIn('frozen', data['metadata']['missing'])
        self.assertEqual(digest(run / 'frozen' / 'a.txt'),
                         data['files']['frozen/a.txt']['sha256'])


if __name__ == '__main__':
    unittest.main()
