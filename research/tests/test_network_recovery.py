import copy
import json
from pathlib import Path
import tempfile
import unittest

from research.network_recovery import POOL_ERROR, pool_failure, validate_target


class NetworkRecoveryContracts(unittest.TestCase):
    def setUp(self):
        self.state={'run_id':'run','network':'s2-net-0123456789abcdef','worker':'worker','gateway':'gateway','stop_confirmed':True}
        self.manifest={'run_id':'run','stop_confirmed':True}
        self.network={'Name':self.state['network'],'Labels':{'sample2.run':'run'},'Internal':True,'Driver':'bridge','Containers':{}}
        self.container={'name':'worker','labels':{'sample2.run':'run'},'state':{'Running':False},'networks':{self.state['network']:{}}}

    def test_only_stopped_owned_empty_internal_network_is_reclaimable(self):
        validate_target(self.state,self.manifest,self.network,[self.container])
        for field,value in [('Internal',False),('Containers',{'foreign':{}}),('Labels',{'sample2.run':'other'})]:
            bad={**self.network,field:value}
            with self.assertRaises(RuntimeError):validate_target(self.state,self.manifest,bad,[self.container])
        for change in ({'name':'foreign'},{'state':{'Running':True}},{'labels':{'sample2.run':'other'}}):
            with self.assertRaises(RuntimeError):
                validate_target(self.state,self.manifest,self.network,[{**self.container,**change}])

    def test_failed_stop_or_foreign_network_name_is_rejected_even_if_absent(self):
        for change in ({'stop_confirmed':False},{'network':'bridge'}):
            with self.assertRaises(RuntimeError):validate_target({**self.state,**change},self.manifest,None,[])

    def test_recovery_exception_requires_exact_premodel_pool_failure(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'evidence').mkdir();(root/'usage/raw').mkdir(parents=True)
            manifest={'end_reason':'environment_failure','model_called':False,'stop_confirmed':True}
            (root/'manifest.json').write_text(json.dumps(manifest))
            (root/'evidence/runtime-error.json').write_text(json.dumps({'message':POOL_ERROR}))
            self.assertTrue(pool_failure(root))
            (root/'usage/raw/started.jsonl').write_text('{}\n')
            self.assertFalse(pool_failure(root))
            (root/'usage/raw/started.jsonl').write_text('')
            (root/'manifest.json').write_text(json.dumps({**manifest,'model_called':True}))
            self.assertFalse(pool_failure(root))

