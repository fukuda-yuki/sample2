"""Stopped postprocessing and local gate stages have separate durable clocks."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import support
from harness import machine, monitor, util


class PostprocessTimingTests(unittest.TestCase):
    def test_serial_heavy_stages_have_separate_identity_bound_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            batch=Path(tmp); root=batch/'R'
            util.write_new_json(root/'manifest.json',{'run_id':'R','run_instance_id':'I','stop_confirmed':True,
                'assignment':{'plan_sha256':'a'*64,'cohort':'technical'},'network_cleanup':{'confirmed':True}})
            order=[]
            def record(stage,value): order.append(stage); return value
            with patch.object(machine.evaluate,'last_scoring',return_value=None), \
                 patch.object(machine.evaluate,'used_sequences',return_value=[]), \
                 patch.object(machine.evaluate,'score_run',side_effect=lambda *a:record('scoring',{})), \
                 patch.object(monitor,'link',side_effect=lambda *a:record('monitor',{})), \
                 patch.object(machine.preserve,'pack_run',side_effect=lambda *a,**k:record('archive',{'package_id':'P','sha256':'b'*64})), \
                 patch.object(machine.aggregate,'row_for',return_value={'run_id':'R'}), \
                 patch.object(machine.time,'perf_counter',side_effect=[10,12,20,23,30,34]):
                row=machine.postprocess(batch,batch,'R',batch/'archive')
            self.assertEqual(order,['scoring','monitor','archive'])
            events=util.read_lines(root/'postprocess-timing.jsonl')
            ends=[e for e in events if e['event']=='stage_completed']
            self.assertEqual([e['stage'] for e in ends],['scoring','monitor_import_including_build','archive_pack_including_compression'])
            self.assertEqual([e['duration_seconds'] for e in ends],[2,3,4])
            self.assertTrue(all(e['run_instance_id']=='I' and e['plan_sha256']=='a'*64 for e in events))
            self.assertEqual(row['postprocessing']['receipt_sha256'],util.sha256_file(root/'postprocess-timing.jsonl'))

    def test_local_public_gate_clock_preserves_failure_and_never_invents_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            receipt=Path(tmp)/'gate-timing.jsonl'
            binding={'cohort':'technical','pair':1,'run_instances':{'A':'IA','B':'IB'},'plan_sha256':'a'*64}
            def fail(): raise RuntimeError('private error details are not a timing receipt')
            with patch.object(machine.time,'perf_counter',side_effect=[5,8]), self.assertRaises(RuntimeError):
                machine.timed_stage(receipt,'local_public_gate',fail,binding=binding)
            events=util.read_lines(receipt)
            self.assertEqual([e['event'] for e in events],['stage_started','stage_failed'])
            self.assertEqual(events[-1]['duration_seconds'],3)
            self.assertEqual(events[-1]['run_instances'],binding['run_instances'])
            self.assertNotIn('private error',receipt.read_text(encoding='utf-8'))

    def test_unconfirmed_run_has_no_heavy_stage_clock(self):
        with tempfile.TemporaryDirectory() as tmp:
            batch=Path(tmp); root=batch/'R'
            util.write_new_json(root/'manifest.json',{'run_id':'R','run_instance_id':'I','stop_confirmed':False})
            with self.assertRaises(RuntimeError): machine.postprocess(batch,batch,'R',batch/'archive')
            self.assertFalse((root/'postprocess-timing.jsonl').exists())


if __name__ == '__main__': unittest.main()
