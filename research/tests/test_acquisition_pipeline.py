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
    def test_four_single_run_acquisitions_overlap_one_evaluator(self):
        barrier=threading.Barrier(4);lock=threading.Lock();active=0;peak=0;scored=[]
        def acquire(n):
            barrier.wait(timeout=3)
            return {'acquired':True}
        def evaluate(n,result):
            nonlocal active,peak
            with lock:active+=1;peak=max(peak,active)
            time.sleep(.01)
            with lock:active-=1;scored.append(n)
            return {}
        pipeline.dispatch_pipeline(range(4),acquire,evaluate,lambda *_:None,lambda *_:None,capacity=4)
        self.assertEqual(sorted(scored),list(range(4)));self.assertEqual(peak,1)

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

    def test_saved_acquisition_is_held_but_authorized_exclusion_can_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            attempts=[]
            for slot, acquired in ((24,False),(46,True),(73,True)):
                batch=Path(directory)/str(slot)
                util.write_new_json(batch/'pipeline-acquisition.json',
                    {'acquired':acquired,'attempt':str(slot)})
                attempts.append({'slot':slot,'record':str(batch/'pipeline-attempt.json')})
            decision=dict(accepted=False,slot=46,attempt='46',quality=None,
                classification='excluded_incomplete_evaluation_user_authorized_reacquisition',
                retry_requires_new_uuids=True)
            util.write_new_json(Path(directory)/'46/pipeline-evaluation.json',decision)
            accepted=set(range(1,101))-{24,46,73,86}
            pending,held=pipeline.pending_acquisition_slots({'attempted_slots':[]},attempts,accepted)
            self.assertEqual(pending,[86,24,46]);self.assertEqual(held,{73})
            # An unrelated/stale exclusion cannot authorize another trial.
            decision['attempt']='other'
            util.write_json_atomic(Path(directory)/'46/pipeline-evaluation.json',decision)
            pending,held=pipeline.pending_acquisition_slots({'attempted_slots':[]},attempts,accepted)
            self.assertEqual(pending,[86,24]);self.assertEqual(held,{46,73})

    def test_new_campaign_does_not_inherit_individual_exclusion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            util.write_new_json(root/'pipeline-acquisition.json', dict(acquired=True, attempt='old'))
            util.write_new_json(root/'pipeline-evaluation.json', dict(accepted=False, slot=1, attempt='old',
                classification='excluded_incomplete_evaluation_user_authorized_reacquisition', retry_requires_new_uuids=True))
            pending, held = pipeline.pending_acquisition_slots(dict(campaign_plan={}, pair_count=1, attempted_slots=[]),
                [dict(slot=1, record=str(root/'pipeline-attempt.json'))], set())
            self.assertEqual(pending, []); self.assertEqual(held, {1})

    def test_missing_usage_and_duration_stay_unknown_and_duplicate_run_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = dict(run_instance_id='one', started_at='2026-10-10T00:00:00+00:00', ended_at='2026-10-10T00:00:02+00:00')
            util.write_new_json(root/'run/manifest.json', manifest)
            util.append_line(root/'run/usage/raw/started.jsonl', dict(request_id='incomplete'))
            result = pipeline.usage_for(root)
            self.assertEqual(result['unknown_usage_requests'][0]['status'], 'missing_terminal_event')
            self.assertEqual(result['missing_duration_runs'], ['one'])
            self.assertEqual(result['observed_tokens'], 0)
            util.write_new_json(root/'copy/manifest.json', manifest)
            with self.assertRaisesRegex(ValueError, 'Duplicate Run UUID'): pipeline.usage_for(root)

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
