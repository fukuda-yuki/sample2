"""New source archives do not inherit Windows checkout newline conversion."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import support
from harness import runtime, util


class SourceArchiveByteTests(unittest.TestCase):
    def test_production_archive_preserves_lf_under_crlf_cache_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); fixture=root/'git-fixture'; fixture.mkdir()
            original=b'Apache fixture\nLicense second line\n'
            runtime.command(['git','init','-q',str(fixture)])
            (fixture/'LICENSE').write_bytes(original)
            runtime.command(['git','-c','core.autocrlf=false','-C',str(fixture),'add','LICENSE'])
            runtime.command(['git','-c','user.name=fixture','-c','user.email=fixture@example.invalid',
                             '-C',str(fixture),'commit','-qm','Fixture source bytes'])
            revision=runtime.command(['git','-C',str(fixture),'rev-parse','HEAD']).stdout.strip()
            ordinary_command=runtime.command
            def local_source_command(args,**kwargs):
                if 'fetch' in args:
                    cache=Path(args[2])
                    ordinary_command(['git','-C',str(cache),'config','core.autocrlf','true'])
                    ordinary_command(['git','-C',str(cache),'config','core.eol','crlf'])
                    args=list(args); args[-2]=str(fixture)
                return ordinary_command(args,**kwargs)
            task={'start_state':{'source_repository':'fixture/source','source_commit':revision}}
            with patch.object(runtime,'command',side_effect=local_source_command):
                prepared=runtime.source(root/'repo',task)
            self.assertEqual((prepared/'LICENSE').read_bytes(),original)
            metadata=util.read_json(prepared.parent/(revision+'.json'))
            self.assertEqual(metadata['archive_configuration'],{'core.autocrlf':False,'core.eol':'lf'})
            self.assertEqual(metadata['files'],util.tree_hashes(prepared))
            before=(prepared/'LICENSE').read_bytes()
            self.assertEqual(runtime.source(root/'repo',task),prepared)
            self.assertEqual((prepared/'LICENSE').read_bytes(),before)


if __name__ == '__main__': unittest.main()
