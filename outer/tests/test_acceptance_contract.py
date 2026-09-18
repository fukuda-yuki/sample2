"""Batch drift must be refused before any paid model dispatch."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from harness import machine, util


class AcceptanceContractTests(unittest.TestCase):
    def test_changed_task_runtime_lock_or_intervention_cannot_dispatch(self):
        for name in ('task','runtime','intervention','runtime_lock'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)/'MS1-001-explore-001'
                root.mkdir()
                for item in ('task','runtime','intervention'):
                    util.write_new_json(root/'profiles'/(item+'.json'), {'original':True})
                util.write_new_json(root/'condition.json', {'runtime_lock':{'original':True}})
                digest = machine.fingerprint({'original':True})
                expected = {'task':digest,'runtime':digest,'runtime_lock':digest,
                            'interventions':{'explore':digest}}
                if name == 'runtime_lock':
                    util.write_json_atomic(root/'condition.json', {'runtime_lock':{'original':False}})
                else:
                    util.write_json_atomic(root/'profiles'/(name+'.json'), {'original':False})
                with patch.object(machine.profiles,'create',return_value={'run_id':root.name}), \
                     patch.object(machine.runtime,'start') as start, \
                     patch.object(machine.preserve,'pack_run',return_value={'retained':True}) as pack:
                    with self.assertRaisesRegex(ValueError,'conditions changed'):
                        machine.execute(tmp, root.parent, 'MS1-001','explore',1,'deepseek',
                                        Path(tmp)/'archive', expected=expected)
                    start.assert_not_called()
                    self.assertTrue(list(root.glob('pipeline-error-*.json')))
                    self.assertIn('workspace',pack.call_args.kwargs['include'])


if __name__ == '__main__':
    unittest.main()
