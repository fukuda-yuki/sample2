from pathlib import Path
import tempfile
import unittest
from outer.harness import util
from research import acquisition_pipeline as pipeline, live_pilot, resource_origin


class ResourceOriginTests(unittest.TestCase):
    def test_closed_technical_runs_share_budget_but_not_slots_or_attempt_cap(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);rows=[]
            for number in range(2):
                path=root/str(number)/'manifest.json'
                util.write_new_json(path,dict(run_instance_id=str(number),stop_confirmed=True,
                    network_cleanup={'confirmed':True},started_at='2026-10-01T00:00:00+00:00',
                    ended_at='2026-10-01T00:00:02+00:00',duration_seconds=2))
                util.append_line(path.parent/'usage/raw/started.jsonl',dict(request_id='missing'))
                rows.append(dict(manifest=live_pilot.reference(path),raw_usage=util.tree_hashes(path.parent/'usage/raw')))
            origin=root/'origin.json'
            receipt=dict(kind='technical_acceptance_resources_v1',started_at='2026-10-01T00:00:00+00:00',runs=rows)
            util.write_new_json(origin,receipt)
            start,usage=resource_origin.read(live_pilot.reference(origin))
            self.assertEqual(usage['requests'],2);self.assertEqual(usage['dispatched_runs'],2)
            self.assertEqual(usage['accumulated_run_seconds'],4);self.assertEqual(len(usage['unknown_usage_requests']),2)
            budget=pipeline.Budget(dict(usage=usage,root=str(root),started_at=start,
                bounds=dict(request_count=3,observed_tokens=100,accumulated_run_seconds=100,wall_seconds=10**10)))
            with self.assertRaisesRegex(RuntimeError,'requests'):budget.check('new',dict(requests=1))
            util.write_json_atomic(origin,dict(receipt,runs=rows*2))
            with self.assertRaisesRegex(ValueError,'duplicated'):resource_origin.read(live_pilot.reference(origin))
            util.write_json_atomic(origin,receipt)
            util.append_line(root/'0/usage/raw/events.jsonl',dict(request_id='late',usage=None))
            with self.assertRaisesRegex(ValueError,'changed'):resource_origin.read(live_pilot.reference(origin))
