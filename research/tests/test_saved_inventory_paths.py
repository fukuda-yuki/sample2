"""Offline inventory coverage for Windows paths; no acquisition or scoring."""
import hashlib
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from outer.harness import preserve, util
from research import campaign_recovery as recovery


class SavedInventoryPathTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='saved-inventory-'))
        # Extended paths also let the fixture clean up its own deep descendants.
        self.addCleanup(shutil.rmtree, preserve.native_path(self.root))

    def put(self, relative, data):
        path = preserve.native_path(self.root / relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def test_normal_paths_match_previous_inventory_exactly(self):
        for name in ('plain.txt', 'bin/product.dll', 'obj/build.dat', 'state/session.db-wal'):
            self.put(name, name.encode())
        root = self.root.resolve()
        previous = {p.relative_to(root).as_posix(): util.sha256_file(p)
                    for p in sorted(root.rglob('*')) if p.is_file()}
        self.assertEqual(recovery.complete_byte_inventory(root), previous)

    def test_all_files_beyond_260_characters_are_included(self):
        relative = Path('deep')
        while len(str(self.root / relative / 'evidence.json')) <= 300:
            relative /= 'a' * 70
        records = {'normal.txt': b'short', (relative / 'evidence.json').as_posix(): b'long',
                   (relative / 'bin/product.dll').as_posix(): b'binary',
                   (relative / 'state/session.db-wal').as_posix(): b'sidecar'}
        for name, data in records.items():
            self.put(name, data)
        expected = {name: hashlib.sha256(data).hexdigest() for name, data in records.items()}
        self.assertGreater(len(str(self.root / relative / 'evidence.json')), 260)
        self.assertEqual(recovery.complete_byte_inventory(self.root), expected)
        self.assertEqual(recovery.complete_byte_inventory(preserve.native_path(self.root)), expected)

    def test_symbolic_link_is_rejected_before_hashing(self):
        self.put('linked-evidence', b'placeholder')
        original = Path.is_symlink
        with patch.object(Path, 'is_symlink', lambda p: p.name == 'linked-evidence' or original(p)):
            with self.assertRaisesRegex(ValueError, 'Links forbidden'):
                recovery.complete_byte_inventory(self.root)

    @unittest.skipUnless(os.name == 'nt', 'Windows junction regression')
    def test_actual_windows_junction_is_rejected(self):
        import _winapi
        inventory = self.root / 'inventory'
        outside = self.root / 'outside'
        inventory.mkdir(); outside.mkdir()
        (outside / 'foreign.txt').write_bytes(b'not part of the inventory')
        junction = inventory / 'junction'
        _winapi.CreateJunction(str(outside), str(junction))
        self.assertTrue(junction.is_junction())
        with self.assertRaisesRegex(ValueError, 'Links forbidden'):
            recovery.complete_byte_inventory(inventory)


if __name__ == '__main__':
    unittest.main()
