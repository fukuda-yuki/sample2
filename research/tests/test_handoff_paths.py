from pathlib import Path
import tempfile
import unittest
import zipfile

from outer.harness.preserve import native_path
from research.handoff import files_in
from research.validate import digest, read, file_exists


class HandoffPathTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        # TemporaryDirectory also needs its extended path for teardown.
        self.tmp.name=str(native_path(self.tmp.name))
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.name='/'.join(['long-directory-'+str(i) for i in range(20)])+'/original.json'
        self.file=self.root/self.name
        native_path(self.file).parent.mkdir(parents=True)
        native_path(self.file).write_bytes(b'{"preserved":true}')

    def test_long_original_is_enumerated_hashed_and_zipped(self):
        entries=list(files_in(self.root))
        self.assertEqual([name for name,p in entries],[self.name])
        with zipfile.ZipFile(self.root/'test.zip','w') as archive:
            for name,path in entries:archive.write(path,name)
        with zipfile.ZipFile(self.root/'test.zip') as archive:
            self.assertEqual(archive.read(self.name),b'{"preserved":true}')

    def test_auditor_reads_long_original_without_treating_it_as_missing(self):
        self.assertTrue(file_exists(self.file))
        self.assertEqual(read(self.file),{'preserved':True})
        self.assertEqual(digest(self.file),digest(native_path(self.file)))

    def test_parent_relative_output_is_normalized_before_extended_prefix(self):
        sibling=self.root/'correction-output';sibling.mkdir()
        (sibling/'requirements.json').write_bytes(b'{"requirements":29}')
        nested=self.root/'staging';nested.mkdir()
        path=nested/'..'/'correction-output'/'requirements.json'
        self.assertEqual(read(path),{'requirements':29})
        self.assertEqual(digest(path),digest(sibling/'requirements.json'))
