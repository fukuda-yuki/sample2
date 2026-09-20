"""Batch drift must be refused before any paid model dispatch."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from support import util
from harness import machine


class AcceptanceContractTests(unittest.TestCase):
    def test_browser_cleanup_failure_stops_batch_before_next_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            row = {'run_id': 'one', 'execution': {'state': 'completed'}, 'scoring': {'state': 'scored'},
                   'network_cleanup': {'confirmed': True}, 'operation_status': 'cleanup_failed'}
            with patch.object(machine, 'expected_conditions', return_value={}), \
                    patch.object(machine, 'execute', return_value=row) as execute, \
                    patch.object(machine.run, 'read_usage', return_value={'usage_complete': True, 'input_reached': True}), \
                    patch.object(machine.util, 'read_json', return_value={'verified': True}):
                with self.assertRaisesRegex(RuntimeError, 'Acceptance paused'):
                    machine.acceptance(tmp, tmp, 'MS1-001', 'deepseek')
            self.assertEqual(1, execute.call_count)

    def test_restored_scoring_cleanup_failure_cannot_complete_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            row = {'run_id': 'one', 'execution': {'state': 'completed'}, 'scoring': {'state': 'scored'},
                   'network_cleanup': {'confirmed': True}, 'operation_status': 'complete', 'archive': {}}
            scoring = {'directory': 'evaluations/scored', 'quality': 100, 'verdict': 'pass', 'artifact_sha256_outer': 'artifact'}
            with patch.object(machine, 'expected_conditions', return_value={}), \
                    patch.object(machine, 'execute', return_value=row), \
                    patch.object(machine.run, 'read_usage', return_value={'usage_complete': True, 'input_reached': True}), \
                    patch.object(machine.util, 'read_json', return_value={'verified': True, 'requirements': []}), \
                    patch.object(machine.preserve, 'restore'), \
                    patch.object(machine.evaluate, 'last_scoring', return_value=scoring), \
                    patch.object(machine.evaluate, 'score_run', return_value=scoring), \
                    patch.object(machine.aggregate, 'row_for', return_value={'operation_status': 'cleanup_failed'}):
                with self.assertRaisesRegex(RuntimeError, 'Restored evaluation cleanup failed'):
                    machine.acceptance(tmp, tmp, 'MS1-001', 'deepseek')

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
