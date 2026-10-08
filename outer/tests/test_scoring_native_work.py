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

    def test_native_initializer_only_mounts_owned_scratch_and_keeps_app_user(self):
        import json
        detail={'Mounts':[{'Destination':'/work','Type':'volume','Name':'owned-volume'}],
                'Config':{'User':'1000:1000'},'Image':'sha256:test'}
        replies=[SimpleNamespace(stdout=json.dumps([detail]),returncode=0),SimpleNamespace(returncode=0),SimpleNamespace(returncode=0)]
        with tempfile.TemporaryDirectory() as d,patch.object(runtime,'command') as create,patch.object(runtime,'docker',side_effect=replies) as docker:
            result=runtime.prepare_native_container(['docker','run','--name','owned','image','dotnet','app'], '/work',Path(d)/'receipt.json')
            self.assertEqual(['docker','start','-a','owned'],result)
            self.assertNotIn('--user',create.call_args.args[0])
            init=docker.call_args_list[1].args
            self.assertIn('type=volume,source=owned-volume,target=/owned',init)
            self.assertEqual(('chmod','0777','/owned'),init[-3:])
            self.assertEqual(('rm','-f','owned-volume-init'),docker.call_args_list[-1].args)
