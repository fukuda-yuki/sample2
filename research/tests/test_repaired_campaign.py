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

    def test_owned_policy_changes_only_next_wave_admission(self):
        owned,legacy=c.policy(),c.legacy_policy()
        self.assertEqual(owned['next_wave_requires'],c.OWNED_NEXT_WAVE)
        self.assertEqual(legacy['next_wave_requires'],c.LEGACY_NEXT_WAVE)
        self.assertEqual({k:v for k,v in owned.items() if k!='next_wave_requires'},
                         {k:v for k,v in legacy.items() if k!='next_wave_requires'})
        self.assertFalse(owned['balance']);self.assertFalse(owned['paid_fallback'])
        self.assertTrue(c.owned_policy({'policy':owned}));self.assertFalse(c.owned_policy({'policy':legacy}))

    def test_observer_snapshot_retries_only_transient_permission_denial(self):
        monitor=Mock();monitor.snapshot.side_effect=[PermissionError('sharing violation'),{'host_healthy':True}]
        with patch.object(c.time,'sleep'):
            self.assertEqual(c._observer_snapshot(monitor),{'host_healthy':True})
        monitor=Mock();monitor.snapshot.side_effect=PermissionError('persistent')
        with patch.object(c.time,'sleep'),self.assertRaises(PermissionError):
            c._observer_snapshot(monitor)
        self.assertEqual(monitor.snapshot.call_count,c.OBSERVER_READ_RETRIES)
        monitor=Mock();monitor.snapshot.side_effect=RuntimeError('Independent observer status stale or unbound')
        with self.assertRaisesRegex(RuntimeError,'stale'):c._observer_snapshot(monitor)
        self.assertEqual(monitor.snapshot.call_count,1)

    def test_owned_closure_is_refused_under_legacy_policy(self):
        from outer.harness import util
        with tempfile.TemporaryDirectory() as tmp:
            wave=Path(tmp)/'waves/w/spec.json';wave.parent.mkdir(parents=True);util.write_new_json(wave,{'pairs':[1]})
            closure=wave.parent/'closure.json'
            util.write_new_json(closure,dict(wave=c.live_pilot.reference(wave),closed=True,closure_kind=c.OWNED_CLOSURE_KIND))
            with patch.object(c,'wave_spec',return_value={'pairs':[1]}), \
                 patch.object(c,'validate',return_value={'policy':c.legacy_policy()}):
                with self.assertRaisesRegex(ValueError,'owned closure campaign policy'):
                    c.verify_closure(Path(tmp),Path(tmp)/'plan.json',wave,closure)

    def test_owned_close_never_calls_publication_or_sharing(self):
        from research import acquisition_sharing
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp)/'waves/w';d.mkdir(parents=True);(d/'spec.json').write_text('{}')
            c.util.write_new_json(d/'_launcher/result.json',dict(operational_complete=True,owned_closure_confirmed=True,
                plan=None,wave=None,verification={'confirmed':True,'evidence':None}))
            p={'batch':tmp,'policy':c.policy()}
            with patch.object(c,'validate',return_value=p),patch.object(c,'wave_spec',return_value={'pairs':[1],'epoch_plan':{}}), \
                 patch.object(c,'document',return_value={}),patch.object(c.live_pilot,'reference',return_value=None), \
                 patch.object(c.live_pilot,'checked'), \
                 patch.object(c,'_close_wave_owned',return_value={'owned':True}) as owned, \
                 patch.object(acquisition_sharing,'validate_gate',side_effect=AssertionError('no publication gate')), \
                 patch.object(catalog_delivery,'publish',side_effect=AssertionError('no publication')):
                self.assertEqual(c._close_wave(Path(tmp),Path(tmp)/'plan.json',d/'spec.json'),{'owned':True})
            owned.assert_called_once()

    def test_predecessor_recovery_only_revisits_held_latest_attempt(self):
        from research import campaign_transition
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'succ';root.mkdir()
            wave=Path(tmp)/'old/waves/w/spec.json';wave.parent.mkdir(parents=True);c.util.write_new_json(wave,{'pairs':[5,6]})
            ref=c.live_pilot.reference(wave)
            p={'batch':str(root),'policy':c.policy(),'protected_roots':[],
               'predecessor':{'source_repo':str(Path(tmp)/'old-source'),'plan':ref,'history':{}}}
            for disposition,message in [('replacement_eligible','Only a held'),('accept_same_attempt','Only a held')]:
                events=[dict(kind='pair_attempt_reserved',slot=n,wave=ref) for n in (5,6)]+[
                    dict(kind='pair_recovery_decision',slot=n,wave=ref,decision={'disposition':disposition}) for n in (5,6)]
                with self.subTest(disposition=disposition), \
                     patch.object(c,'validate',return_value=p),patch.object(c,'ledger',return_value=events), \
                     patch.object(c.live_pilot,'checked',side_effect=lambda r:Path(r['path'])), \
                     patch.object(campaign_transition,'_history',return_value=({'waves':[{'wave':ref}]},[])):
                    with self.assertRaisesRegex(ValueError,message):
                        c.reconcile_predecessor_recovery(Path(tmp)/'new-source',Path(tmp)/'plan.json',wave,Path(tmp)/'short')
            with patch.object(c,'validate',return_value=dict(p,policy=c.legacy_policy())):
                with self.assertRaisesRegex(ValueError,'owned-policy successor'):
                    c.reconcile_predecessor_recovery(Path(tmp)/'new-source',Path(tmp)/'plan.json',wave,Path(tmp)/'short')

    def test_predecessor_recovery_destination_never_overlaps_sources_or_evidence(self):
        from research import campaign_transition
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'succ';root.mkdir()
            wave=Path(tmp)/'old/waves/w/spec.json';wave.parent.mkdir(parents=True);c.util.write_new_json(wave,{'pairs':[5]})
            ref=c.live_pilot.reference(wave)
            p={'batch':str(root),'policy':c.policy(),'protected_roots':[str(Path(tmp)/'old')],
               'predecessor':{'source_repo':str(Path(tmp)/'old-source'),'plan':ref,'history':{}}}
            with patch.object(c,'validate',return_value=p), \
                 patch.object(campaign_transition,'_history',return_value=({'waves':[{'wave':ref}]},[])):
                for target in (Path(tmp)/'old/recovery',Path(tmp)/'old-source/recovery',Path(tmp)/'new-source/r'):
                    with self.subTest(target=target),self.assertRaisesRegex(ValueError,'overlaps protected'):
                        c.reconcile_predecessor_recovery(Path(tmp)/'new-source',Path(tmp)/'plan.json',wave,target)

    def inherited_fixture(self, tmp):
        wave=Path(tmp)/'old/waves/w/spec.json';wave.parent.mkdir(parents=True);c.util.write_new_json(wave,{'pairs':[6]})
        ref=c.live_pilot.reference(wave);closure=wave.parent/'closure.json'
        recovery={'path':str(Path(tmp)/'r/closure.json'),'sha256':'0'*64}
        c.util.write_new_json(closure,dict(wave=ref,closed=True,recovery=recovery))
        p={'batch':str(Path(tmp)/'succ'),'policy':c.policy(),
           'predecessor':{'source_repo':str(Path(tmp)/'old-source'),'plan':{'path':str(Path(tmp)/'old-plan.json'),'sha256':'1'*64},'history':{}}}
        decision=dict(kind='pair_recovery_decision',slot=6,wave=ref,decision={'disposition':'replacement_eligible'},
                      closure=c.live_pilot.reference(closure),not_before='2026-01-01T00:00:00+00:00')
        return wave,ref,closure,recovery,p,decision

    def test_inherited_replacement_decision_is_verified_under_predecessor_campaign(self):
        from research import campaign_transition, campaign_recovery
        with tempfile.TemporaryDirectory() as tmp:
            wave,ref,closure,recovery,p,decision=self.inherited_fixture(tmp)
            with patch.object(campaign_transition,'history_events',return_value=[decision]), \
                 patch.object(campaign_transition,'_history',return_value=({'waves':[{'wave':ref}]},[])), \
                 patch.object(c.live_pilot,'checked',side_effect=lambda r:Path(r['path'])), \
                 patch.object(campaign_recovery,'validate_closure',return_value={'decisions':{}}) as validate:
                self.assertTrue(c._inherited_decision(p,decision))
                c._verify_inherited_recovery(Path(tmp)/'new',p,c.util.read_json(closure),decision['closure'])
            validate.assert_called_once_with(Path(tmp)/'old-source',Path(tmp)/'old-plan.json',wave,recovery)

    def test_inherited_decision_requires_retained_predecessor_wave_and_its_own_wrapper(self):
        from research import campaign_transition, campaign_recovery
        with tempfile.TemporaryDirectory() as tmp:
            wave,ref,closure,recovery,p,decision=self.inherited_fixture(tmp)
            foreign=Path(tmp)/'elsewhere/closure.json';c.util.write_new_json(foreign,c.util.read_json(closure))
            cases=[({'waves':[]},closure),({'waves':[{'wave':ref}]},foreign)]
            for history,location in cases:
                with self.subTest(location=location), \
                     patch.object(campaign_transition,'_history',return_value=(history,[])), \
                     patch.object(c.live_pilot,'checked',side_effect=lambda r:Path(r['path'])), \
                     patch.object(campaign_recovery,'validate_closure',side_effect=AssertionError('not reached')):
                    with self.assertRaisesRegex(ValueError,'Foreign inherited'):
                        c._verify_inherited_recovery(Path(tmp)/'new',p,c.util.read_json(location),c.live_pilot.reference(location))
            with patch.object(campaign_transition,'history_events',return_value=[]):
                self.assertFalse(c._inherited_decision(p,decision))
            self.assertFalse(c._inherited_decision({k:v for k,v in p.items() if k!='predecessor'},decision))


    def ancestor_fixture(self, tmp, older_has_wave=True):
        wave,ref,closure,recovery,p,decision=self.inherited_fixture(tmp)
        older={'path':str(Path(tmp)/'older-plan.json'),'sha256':'2'*64}
        c.util.write_new_json(Path(tmp)/'old-plan.json',{'policy':c.policy(),'predecessor':{
            'source_repo':str(Path(tmp)/'older-source'),'plan':older,'history':{'level':2}}})
        histories={1:({'waves':[]},[]),2:({'waves':[{'wave':ref}] if older_has_wave else []},[])}
        history=lambda h:histories[h.get('level',1)]
        return wave,ref,closure,recovery,p,decision,history

    def test_inherited_decision_of_an_older_ancestor_is_verified_under_that_ancestor(self):
        from research import campaign_transition, campaign_recovery
        with tempfile.TemporaryDirectory() as tmp:
            wave,ref,closure,recovery,p,decision,history=self.ancestor_fixture(tmp)
            with patch.object(campaign_transition,'_history',side_effect=history), \
                 patch.object(c.live_pilot,'checked',side_effect=lambda r:Path(r['path'])), \
                 patch.object(campaign_recovery,'validate_closure',return_value={'decisions':{}}) as validate:
                c._verify_inherited_recovery(Path(tmp)/'new',p,c.util.read_json(closure),decision['closure'])
            validate.assert_called_once_with(Path(tmp)/'older-source',Path(tmp)/'older-plan.json',wave,recovery)

    def test_ancestor_walk_without_retained_wave_or_with_cycle_stays_foreign(self):
        from research import campaign_transition, campaign_recovery
        with tempfile.TemporaryDirectory() as tmp:
            wave,ref,closure,recovery,p,decision,history=self.ancestor_fixture(tmp,older_has_wave=False)
            c.util.write_json_atomic(Path(tmp)/'older-plan.json',{'policy':c.policy()})
            for case in ('chain_ends','cycle'):
                if case=='cycle':
                    c.util.write_json_atomic(Path(tmp)/'older-plan.json',{'policy':c.policy(),'predecessor':p['predecessor']})
                with self.subTest(case=case), \
                     patch.object(campaign_transition,'_history',side_effect=history), \
                     patch.object(c.live_pilot,'checked',side_effect=lambda r:Path(r['path'])), \
                     patch.object(campaign_recovery,'validate_closure',side_effect=AssertionError('not reached')):
                    with self.assertRaisesRegex(ValueError,'Foreign inherited'):
                        c._verify_inherited_recovery(Path(tmp)/'new',p,c.util.read_json(closure),decision['closure'])

    def test_ancestor_walk_keeps_wrapper_location_and_shape_checks(self):
        from research import campaign_transition, campaign_recovery
        with tempfile.TemporaryDirectory() as tmp:
            wave,ref,closure,recovery,p,decision,history=self.ancestor_fixture(tmp)
            foreign=Path(tmp)/'elsewhere/closure.json';c.util.write_new_json(foreign,c.util.read_json(closure))
            bad_shape=dict(c.util.read_json(closure),closed=False)
            for saved,location in ((c.util.read_json(foreign),foreign),(bad_shape,closure)):
                with self.subTest(location=location), \
                     patch.object(campaign_transition,'_history',side_effect=history), \
                     patch.object(c.live_pilot,'checked',side_effect=lambda r:Path(r['path'])), \
                     patch.object(campaign_recovery,'validate_closure',side_effect=AssertionError('not reached')):
                    with self.assertRaisesRegex(ValueError,'Foreign inherited'):
                        c._verify_inherited_recovery(Path(tmp)/'new',p,saved,c.live_pilot.reference(location))


if __name__=='__main__':unittest.main()
