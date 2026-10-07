from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, Mock

from outer.harness import util
from research import acquisition_pipeline as pipeline
from research import acquisition_readiness as readiness


class PipelineTests(unittest.TestCase):
    def test_next_acquisition_overlaps_previous_evaluation_and_limits_hold(self):
        evaluation_started = threading.Event()
        third_started = threading.Event()
        lock = threading.Lock()
        active = {'generation':0, 'evaluation':0}
        peak = dict(active); accepted=[]
        def acquire(n):
            with lock:
                active['generation']+=1; peak['generation']=max(peak['generation'],active['generation'])
            if n > 2:
                self.assertTrue(evaluation_started.wait(3))
                third_started.set()
            time.sleep(.03)
            with lock:active['generation']-=1
            return {'acquired':True}
        def evaluate(n, result):
            with lock:
                active['evaluation']+=1; peak['evaluation']=max(peak['evaluation'],active['evaluation'])
            evaluation_started.set()
            self.assertTrue(third_started.wait(3), 'Next model pair was blocked by evaluation')
            with lock:active['evaluation']-=1
            return {'accepted':True,'quality':0}
        pipeline.dispatch_pipeline(range(1,7),acquire,evaluate,lambda *_:None,
                                   lambda n,result:accepted.append((n,result['quality'])))
        self.assertEqual(peak,{'generation':2,'evaluation':1})
        self.assertEqual(sorted(accepted),[(n,0) for n in range(1,7)])

    def test_failed_acquisition_is_recorded_and_not_sent_to_evaluator(self):
        failed=[];scored=[]
        pipeline.dispatch_pipeline([1,2],lambda n:{'acquired':n==2},
            lambda n,r:scored.append(n) or {},lambda n,r:failed.append((n,r['acquired'])),lambda *_:None)
        self.assertEqual(scored,[2]); self.assertEqual(sorted(failed),[(1,False),(2,True)])

    def test_unknown_usage_is_retained_separately_from_observed_lower_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'run'
            util.write_new_json(root/'manifest.json',{'run_instance_id':'one','started_at':'2026-10-01T00:00:00+00:00',
                'ended_at':'2026-10-01T00:00:02+00:00','duration_seconds':2})
            util.append_line(root/'usage/raw/started.jsonl',{'request_id':'a'})
            util.append_line(root/'usage/raw/started.jsonl',{'request_id':'b'})
            util.append_line(root/'usage/raw/events.jsonl',{'request_id':'a','usage':{'input_tokens':100,'output_tokens':5}})
            util.append_line(root/'usage/raw/events.jsonl',{'request_id':'b','status':'cancelled','usage':None})
            result=pipeline.usage_for(directory)
        self.assertEqual(result['requests'],2); self.assertEqual(result['observed_tokens'],105)
        self.assertEqual(result['unknown_usage_requests'][0]['request_id'],'b')
        self.assertIsNone(result['unknown_usage_requests'][0]['observed_tokens'])

    def test_static_pipeline_validation_cached_but_changed_plan_revalidated(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'plan.json'; repo=Path(directory)
            value={'operational_pipeline':True,'source_pins':{}}
            util.write_new_json(path,value)
            with patch.object(readiness.live_pilot,'verify_pins') as pins,\
                 patch.object(readiness,'_verify_main_phase_static',return_value=value) as validate:
                readiness.verify_pipeline_phase(path,repo);readiness.verify_pipeline_phase(path,repo)
                self.assertEqual(validate.call_count,1);self.assertEqual(pins.call_count,2)
                util.write_json_atomic(path,dict(value,phase_id='changed'))
                readiness.verify_pipeline_phase(path,repo)
                self.assertEqual(validate.call_count,2)


if __name__=='__main__':unittest.main()
