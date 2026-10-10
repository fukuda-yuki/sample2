"""Exact source-byte equivalence for the batched read-only Git transport."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from research.repaired_runtime import _committed_files


class CommittedFileBatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        (self.repo/'one').write_bytes(b'first\r\n')
        (self.repo/'two').write_bytes(b'\x00second\n')

    def framed(self, content):
        return b'a'*40 + b' blob ' + str(len(content)).encode() + b'\n' + content + b'\n'

    def test_one_process_exact_binary_bytes(self):
        output=self.framed(b'first\r\n')+self.framed(b'\x00second\n')
        with patch('subprocess.run',return_value=subprocess.CompletedProcess([],0,output,b'')) as run:
            _committed_files(self.repo,'c'*40,['one','two'])
        self.assertEqual(run.call_count,1)
        self.assertEqual(run.call_args.kwargs['input'], ('c'*40+':one\n'+'c'*40+':two\n').encode())
        self.assertEqual(run.call_args.args[0][-2:],['cat-file','--batch'])

    def test_missing_nonblob_truncated_extra_or_changed_rejected(self):
        cases = [b'commit:one missing\n', b'a'*40+b' tree 1\nx\n',
            b'header without newline', b'a'*40+b' blob 99\nshort\n',
            self.framed(b'first\r\n')+b'extra',self.framed(b'changed')]
        for output in cases:
            with self.subTest(output=output),patch('subprocess.run',return_value=subprocess.CompletedProcess([],0,output,b'')):
                with self.assertRaises(ValueError):_committed_files(self.repo,'c'*40,['one'])

    def test_linebreak_injection_rejected_without_process(self):
        for commit,names in [('c\nother',['one']),('c',['one\nother'])]:
            with patch('subprocess.run') as run:
                with self.assertRaises(ValueError):_committed_files(self.repo,commit,names)
                run.assert_not_called()


if __name__=='__main__':unittest.main()
