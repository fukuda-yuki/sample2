import copy
from pathlib import Path
import tempfile
import threading
import time
import os
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch
from unittest.mock import Mock

from research import repaired_campaign as c
from research import catalog_delivery


class CampaignTests(unittest.TestCase):
    def test_first_supervisor_exception_is_preserved_before_stop(self):
        from outer.harness import util
        with tempfile.TemporaryDirectory() as tmp:
            w=object.__new__(c.CampaignWatch);w.wave_dir=Path(tmp)
            (w.wave_dir/'spec.json').write_text('{}')
            w.campaign={'_plan_sha256':'a'*64};w.done=Mock()
            w.done.wait.return_value=False
            w.check=Mock(side_effect=RuntimeError('Independent observer status stale or unbound'))
            def stopped(reason):
                evidence=util.read_json(w.wave_dir/'watcher-exception.json')
                self.assertEqual(reason,'RuntimeError')
                self.assertEqual(evidence['message'],'Independent observer status stale or unbound')
                self.assertIn('RuntimeError',evidence['traceback'])
            w.latch=Mock(side_effect=stopped)
            w._loop();w.latch.assert_called_once_with('RuntimeError')

    def test_exception_evidence_write_failure_does_not_suppress_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            w=object.__new__(c.CampaignWatch);w.wave_dir=Path(tmp)
            (w.wave_dir/'spec.json').write_text('{}')
            w.campaign={'_plan_sha256':'a'*64};w.done=Mock();w.done.wait.return_value=False
            w.check=Mock(side_effect=RuntimeError('observer fault'));w.latch=Mock()
            with patch.object(c.util,'write_new_json',side_effect=OSError('disk unavailable')):
                w._loop()
            w.latch.assert_called_once_with('RuntimeError')

    def test_inherited_attempts_keep_the_same_finite_budget(self):
        from research import campaign_transition
        with tempfile.TemporaryDirectory() as tmp:
            p={'batch':tmp,'predecessor':{'history':{}}}
            old=[{'kind':'pair_attempt_reserved'} for _ in range(300)]
            with patch.object(campaign_transition,'history_events',return_value=old),patch.object(c,'validate',return_value=p):
                self.assertEqual(c.ledger(p),old)
                with self.assertRaisesRegex(ValueError,'budget exhausted'):
                    c.reserve_wave(Path(tmp),Path(tmp)/'plan.json',{},[1])

    def test_logical_slot_keeps_task_order_and_stratum(self):
        pair=dict(pair=1,task='MS1-CONT-B',source_family='music',cases=[
            dict(pair=1,slot=1,condition='explore',attempt=6001,run_id='a',run_instance_id='b'),
            dict(pair=1,slot=2,condition='preload',attempt=6001,run_id='c',run_instance_id='d')])
        changed=copy.deepcopy(pair)
        changed['cases'][0].update(run_id='x',run_instance_id='y',attempt=7001)
        self.assertEqual(c.logical(pair),c.logical(changed))
        changed['cases'].reverse()
        self.assertNotEqual(c.logical(pair),c.logical(changed))
        self.assertEqual(pair['cases'][0]['run_id'],'a')

    def test_quality_replacement_and_arm_composition_prohibited(self):
        policy=c.policy()
        self.assertTrue(policy['quality_failure_is_valid'])
        self.assertFalse(policy['low_quality_replacement'])
        self.assertFalse(policy['cross_attempt_arm_composition'])
        self.assertEqual(policy['initial_denominator'],100)

    def test_global_four_run_admission_cap(self):
        w=object.__new__(c.CampaignWatch);w.lock=threading.RLock();w.bindings=[None]*4
        with self.assertRaisesRegex(ValueError,'limit 4'):w.register(Path('.'),{})

    def test_usage_accumulates_prior_failed_attempts(self):
        w=object.__new__(c.CampaignWatch)
        w.prior=dict(requests=7,observed_tokens=90,accumulated_run_seconds=42)
        with patch.object(c.live_pilot.PilotWatch,'counters',return_value=dict(
                requests=2,observed_tokens=30,accumulated_run_seconds=8,http_inflight=4)):
            observed=w.counters()
        self.assertEqual(observed['requests'],9)
        self.assertEqual(observed['observed_tokens'],120)
        self.assertEqual(observed['accumulated_run_seconds'],50)
        self.assertEqual(observed['http_inflight'],4)

    def test_stop_latched_before_owned_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            w=object.__new__(c.CampaignWatch);w.lock=threading.RLock()
            w.campaign={'batch':tmp,'_plan_sha256':'a'*64};w.wave_dir=Path(tmp)/'wave'
            w.wave_dir.mkdir();(w.wave_dir/'spec.json').write_text('{}')
            def stopped(_self,reason):
                self.assertTrue((Path(tmp)/'_control/dispatch-stop.json').exists())
                self.assertTrue((Path(tmp)/'_control/stop-events/wave.json').exists())
            with patch.object(c.live_pilot.PilotWatch,'latch',stopped):w.latch('test_stop')

    def test_browser_activation_is_serial_and_restores_environment(self):
        from research import catalog_environment
        initial={name:os.environ.get(name) for name in ('SAMPLE2_BROWSER_EXECUTABLE','NODE_PATH','SAMPLE2_NODE')}
        active=0;peak=0
        def process():
            nonlocal active,peak
            with catalog_environment.activated({'node_path':'node-fixed'},Path('.')):
                active+=1;peak=max(peak,active)
                time.sleep(0.03)
                self.assertEqual(os.environ['SAMPLE2_BROWSER_EXECUTABLE'],'browser-fixed')
                active-=1
        wrapped=c.live_pilot.serialized_postprocess(process,threading.Lock())
        with patch.object(catalog_environment,'validate',return_value=dict(
                SAMPLE2_BROWSER_EXECUTABLE='browser-fixed',NODE_PATH='modules-fixed')):
            with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(lambda _:wrapped(),range(2)))
        self.assertEqual(peak,1)
        self.assertEqual(initial,{name:os.environ.get(name) for name in initial})

    def test_cross_epoch_worker_rejected_by_campaign_lock(self):
        from research import pair_execution
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with pair_execution.exclusive(root/'_control'):
                with patch.object(c,'validate',return_value={'batch':tmp}):
                    with self.assertRaises((OSError,ValueError,RuntimeError)):
                        c.execute_wave(root,root/'p.json',root/'other/spec.json',123)

    def test_closed_wave_ledger_replay_is_idempotent_and_quality_zero_valid(self):
        from outer.harness import util
        with tempfile.TemporaryDirectory() as tmp:
            p={'batch':tmp};ref={'path':'wave','sha256':'a'*64};w={'pairs':[1], 'epoch_plan':{'x':1}}
            c.pair_execution.append(Path(tmp)/'attempts.jsonl',dict(kind='pair_attempt_reserved',slot=1,
                pair_attempt=1,wave=ref))
            closure=dict(wave=ref,gates={'1':{'gate':1}},observations={'1':{
                arm:dict(classification='already_evaluable',quality=0,verdict='fail') for arm in ('explore','preload')}})
            c._record_closed_wave(p,w,closure);c._record_closed_wave(p,w,closure)
            accepted=[e for e in c.ledger(p) if e['kind']=='pair_accepted']
            self.assertEqual(len(accepted),1);self.assertTrue(accepted[0]['quality_complete'])

    def test_product_failure_null_stays_valid_and_partial_technical_is_not_accepted(self):
        for classification,count in [('normal_product_failure_partial_observation',1),('technical_observation_incomplete',0)]:
            with self.subTest(classification=classification),tempfile.TemporaryDirectory() as tmp:
                p={'batch':tmp};ref={'path':'wave','sha256':'a'*64};w={'pairs':[1],'epoch_plan':{}}
                c.pair_execution.append(Path(tmp)/'attempts.jsonl',dict(kind='pair_attempt_reserved',slot=1,
                    pair_attempt=1,wave=ref))
                closure=dict(wave=ref,gates={'1':{}},observations={'1':{arm:dict(
                    classification=classification,quality=None) for arm in ('explore','preload')}})
                c._record_closed_wave(p,w,closure)
                accepted=[e for e in c.ledger(p) if e['kind']=='pair_accepted']
                self.assertEqual(len(accepted),count)
                if accepted:self.assertFalse(accepted[0]['quality_complete'])

    def test_prior_wave_without_gate_blocks_reservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); spec=root/'waves/w/spec.json';spec.parent.mkdir(parents=True);spec.write_text('{}')
            with patch.object(c,'validate',return_value={'batch':tmp}),patch.object(c,'ledger',return_value=[]):
                with self.assertRaisesRegex(ValueError,'closure pending'):
                    c.reserve_wave(root,root/'plan.json',{},[1,2])

    def test_attempt_budget_is_finite(self):
        with tempfile.TemporaryDirectory() as tmp:
            prior=[{'kind':'pair_attempt_reserved'}]*300
            with patch.object(c,'validate',return_value={'batch':tmp}),patch.object(c,'ledger',return_value=prior):
                with self.assertRaisesRegex(ValueError,'budget exhausted'):
                    c.reserve_wave(Path(tmp),Path(tmp)/'plan.json',{},[1])

    def test_repaired_release_prefix_reaches_package_validation(self):
        # No network request; validates the real production prefix rather than a mock publish.
        with patch.object(catalog_delivery,'verify_package',side_effect=RuntimeError('package-check')):
            with self.assertRaisesRegex(RuntimeError,'package-check'):
                catalog_delivery.publish(Path('.'),'source-info-repaired-v6-abcdef012345-pair-001',
                    'a'*40,tag_prefix='source-info-repaired-v6-abcdef012345-pair-')

    def test_unscoped_release_prefix_stays_rejected(self):
        with self.assertRaises(ValueError):
            catalog_delivery.publish(Path('.'),'arbitrary-001','a'*40,tag_prefix='arbitrary-')


if __name__=='__main__':unittest.main()
