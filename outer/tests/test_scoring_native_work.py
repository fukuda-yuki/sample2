import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from . import support
from harness import evaluate, runtime

class NativeWorkTests(unittest.TestCase):
    def test_native_work_preserves_read_only_artifact_and_has_private_volume(self):
        c={'evaluation':{'assembly':'Education.Evaluator.dll'},'runtime_lock':{'images':{'evaluator':'image'}}}
        _,cmd=runtime.scoring_command(c,Path('artifact'),Path('out'),Path('work'),Path('assets'),'education-1.1.0',1,native_work=True)
        self.assertIn('type=volume,destination=/work',cmd)
        self.assertTrue(any('target=/artifact,readonly' in str(x) for x in cmd))
        self.assertFalse(any('target=/work' in str(x) for x in cmd))
    def test_export_failure_still_removes_exact_container_and_volume(self):
        with patch.object(runtime,'docker',side_effect=[OSError('copy failed'),SimpleNamespace(returncode=0)]) as docker:
            with self.assertRaises(OSError):evaluate.finish_scoring_container('owned',True,Path('work'),Path('out'))
        self.assertEqual(('rm','-f','-v','owned'),docker.call_args_list[-1].args)
    def test_success_exports_before_cleanup(self):
        with tempfile.TemporaryDirectory() as d,patch.object(runtime,'docker',return_value=SimpleNamespace(returncode=0)) as docker:
            evaluate.finish_scoring_container('owned',True,Path(d),Path(d))
            self.assertTrue((Path(d)/'native-work-export.json').is_file())
            self.assertEqual('stop',docker.call_args_list[0].args[0])
            self.assertEqual('cp',docker.call_args_list[1].args[0])
            self.assertEqual('rm',docker.call_args_list[2].args[0])
