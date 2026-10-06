"""Finite independent-trial contracts; no model/provider or Docker calls."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
import copy
import tempfile
import unittest
import uuid
import sys
import subprocess
from unittest.mock import patch
from contextlib import ExitStack
from outer.harness import util,run
from research import education_readiness_trial as trial,live_pilot,live_pilot_launcher,pair_execution


class TrialControls(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.base=self.root/'trial'; self.base.mkdir()
        self.plan=dict(kind=trial.KIND,batch=str(self.base),phase_id=uuid.uuid4().hex,bounds=dict(trial.BOUNDS),
            independent_technical_trial=True,old_pilot_adoption=False,assignments=[dict(pair=1,cases=[
                dict(pair=1,slot=i,attempt=7001,task='CU1-ENR-C',condition=arm,
                    run_id=run.run_id_for('CU1-ENR-C',arm,7001),run_instance_id=uuid.uuid4().hex)
                for i,arm in enumerate(('explore','preload'),1)])])

    def test_exact_two_new_run_scope_and_remaining_budget(self):
        self.assertEqual(live_pilot_launcher.selected_pairs(self.plan),self.plan['assignments'])
        with self.assertRaises(ValueError):live_pilot_launcher.selected_pairs(self.plan,1)
        self.assertEqual(trial.BOUNDS['request_count'],460)
        self.assertEqual(trial.BOUNDS['observed_tokens'],18053732)
        self.assertEqual(trial.WHOLE_SECONDS,trial.BOUNDS['wall_seconds']+trial.CLEANUP_SECONDS)

    def test_fresh_clock_requires_owned_launcher_intent_not_old_clock_or_plan(self):
        ref={'path':str(self.root/'plan.json'),'sha256':'f'*64}
        with self.assertRaises((FileNotFoundError,ValueError)):trial.launch_origin(self.plan,ref)
        start=(datetime.now(timezone.utc)-timedelta(seconds=100)).isoformat()
        util.write_new_json(self.base/'_launcher/intent.json',dict(plan=ref,phase_id=self.plan['phase_id'],started_at=start,
            whole_deadline_utc=(datetime.fromisoformat(start)+timedelta(seconds=trial.WHOLE_SECONDS)).isoformat(),
            wall_threshold_seconds=trial.BOUNDS['wall_seconds'],cleanup_reserve_seconds=trial.CLEANUP_SECONDS))
        self.assertEqual(trial.launch_origin(self.plan,ref),start)
        self.assertLess(trial.remaining_wall(self.plan,ref),5061)
        old=copy.deepcopy(self.plan); old['original_wall_start_utc']='2026-10-06T07:36:04+00:00'
        self.assertEqual(trial.remaining_wall(old,ref)//1,trial.remaining_wall(self.plan,ref)//1)
        util.write_json_atomic(self.base/'_launcher/intent.json',dict(plan={'sha256':'foreign'},phase_id=self.plan['phase_id'],started_at=start))
        with self.assertRaises(ValueError):trial.launch_origin(self.plan,ref)

    def test_watch_registers_only_trial_and_preserves_original_files(self):
        original=self.root/'original';original.mkdir();(original/'STOP').write_text('permanent')
        before=util.tree_hashes(original)
        start=datetime.now(timezone.utc).isoformat();watch=trial.TrialWatch(self.plan,'f'*64,wall_started_at=start)
        for c in self.plan['assignments'][0]['cases']:watch.register(self.base/'pair-1',c)
        with self.assertRaises(ValueError):watch.register(self.base/'pair-1',self.plan['assignments'][0]['cases'][0])
        watch.latch('finite test')
        self.assertEqual(before,util.tree_hashes(original))

    def test_whole_window_includes_cleanup_and_refuses_clock_reset(self):
        start=datetime.now(timezone.utc)
        self.assertEqual(trial.validate_elapsed(start.isoformat(),(start+timedelta(seconds=5400)).isoformat()),5400)
        for seconds in (-1,5400.001):
            with self.assertRaises(ValueError):trial.validate_elapsed(start.isoformat(),(start+timedelta(seconds=seconds)).isoformat())
        with self.assertRaises(ValueError):trial.validate_elapsed(start.replace(tzinfo=None).isoformat(),start.isoformat())

    def test_readiness_main_trial_failure_never_uses_old_pilot_or_recovery(self):
        from research import acquisition_readiness as main,readiness_recovery
        p=dict(readiness_education_trial_plan={'path':'p','sha256':'f'*64},
               readiness_education_trial_result={'path':'r','sha256':'e'*64})
        with patch.object(trial,'ready',side_effect=ValueError('not ready')),patch.object(main,'pilot_ready') as old,patch.object(readiness_recovery,'ready') as rec:
            with self.assertRaisesRegex(ValueError,'not ready'):main.readiness_for_main(self.root,p)
            old.assert_not_called();rec.assert_not_called()
        for bad in ({'readiness_education_trial_plan':p['readiness_education_trial_plan']},
                    {**p,'readiness_recovery_plan':p['readiness_education_trial_plan']}):
            with self.assertRaises(ValueError):main.readiness_for_main(self.root,bad)

    def test_trial_observer_kind_requires_startup_handshake(self):
        from research import resource_supervisor
        self.assertIn(trial.OBSERVER_KIND,resource_supervisor.STARTUP_KINDS)
        p={**self.plan,'cohort':'trial','runtime_by_task':{'CU1-ENR-C':'education'},'source_pins':{},
            'resource_monitor':{},'resource_probe':{},'thresholds':{}}
        ref={'path':str(self.root/'plan'),'sha256':'f'*64};phase=live_pilot.observer_phase(p,ref,1)
        self.assertEqual(phase['kind'],trial.OBSERVER_KIND);self.assertEqual(phase['owner_kind'],trial.KIND)
        with patch.object(live_pilot,'checked',return_value=self.root/'plan'),patch.object(live_pilot,'owner_plan',return_value=p):
            live_pilot.validate_observer_phase(phase,self.root)
            phase['kind']=live_pilot.OBSERVER_KIND
            with self.assertRaises(ValueError):live_pilot.validate_observer_phase(phase,self.root)

    def test_observed_remaining_caps_and_cutoff_raise_without_original_enrollment(self):
        watch=trial.TrialWatch(self.plan,'f'*64,wall_started_at=datetime.now(timezone.utc).isoformat())
        normal=dict(requests=0,observed_tokens=0,accumulated_run_seconds=0,longest_active_run_seconds=0,
            wall_seconds=0,disk_free_bytes=10**12,http_inflight=0)
        for key,limit in [('requests',460),('observed_tokens',18053732),('wall_seconds',5160),('accumulated_run_seconds',3600)]:
            with patch.object(watch,'counters',return_value={**normal,key:limit}),self.assertRaisesRegex(RuntimeError,'Observed threshold'):
                watch.check()
        self.assertEqual(watch.bindings,[])

    def test_launcher_preflight_is_excluded_from_new_durable_period(self):
        from research.tests.test_live_pilot_launcher import Child
        self.plan['source_commit']='a'*40;repo=self.root/'repo';repo.mkdir();source=repo/'research/live_pilot_launcher.py'
        source.parent.mkdir();source.write_text('source')
        path=self.root/'plan.json';util.write_new_json(path,self.plan);ref=live_pilot.reference(path)
        approval=self.root/'approved.json';util.write_new_json(approval,{'scope':'education_two_run_technical_trial'})
        start=datetime.now(timezone.utc).isoformat()
        # preflight consumes a mocked 1000 seconds; the start passed to the
        # supervisor must be the post-preflight monotonic value, 2000.
        with patch.object(live_pilot_launcher,'preflight',return_value=(repo,self.plan,ref,live_pilot.reference(approval))),\
                patch.object(live_pilot_launcher.time,'monotonic',side_effect=[1000,2000]),\
                patch.object(live_pilot_launcher.run,'now',return_value=start),\
                patch.object(live_pilot_launcher,'popen',return_value=Child(code=0)),\
                patch.object(live_pilot_launcher,'supervise',return_value={'operational_complete':False}) as supervisor:
            live_pilot_launcher.launch(repo,path,approval)
        self.assertEqual(supervisor.call_args.args[5],2000)
        intent=util.read_json(self.base/'_launcher/intent.json')
        self.assertEqual(intent['command'][5],'research.education_readiness_trial')
        self.assertEqual(intent['whole_deadline_utc'],(datetime.fromisoformat(start)+timedelta(seconds=5400)).isoformat())
        self.assertEqual(trial.launch_origin(self.plan,ref),start)

    def test_nonprompt_database_input_tamper_rejected_even_with_equal_prompt(self):
        files={'prompt.txt':'a'*64,'legacy-source/App/App.db':'b'*64}
        p=dict(expected_input_sha256_by_arm={'explore':'a'*64},expected_input_files_by_arm={'explore':files})
        binding={'condition':'explore','input_sha256':'a'*64};trial.validate_input(p,binding,{'input_files':files})
        wrong=dict(files);wrong['legacy-source/App/App.db']='f'*64
        with self.assertRaisesRegex(ValueError,'full inputs'):trial.validate_input(p,binding,{'input_files':wrong})

    def test_cleanup_waits_and_repeated_cleanup_share_absolute_deadline(self):
        from research.tests.test_live_pilot_launcher import Child
        class Slow(Child):
            def __init__(self):super().__init__();self.waits=[]
            def terminate(self):self.terminated=True
            def kill(self):self.killed=True
            def wait(self,timeout=None):
                self.waits.append(timeout);raise subprocess.TimeoutExpired('owned child',timeout)
        child=Slow()
        with patch.object(live_pilot_launcher.time,'monotonic',return_value=99.5):
            outcome=live_pilot_launcher._terminate(child,100)
        self.assertTrue(outcome['unknown']);self.assertTrue(all(0<=s<=.5 for s in child.waits))
        directory=self.base/'_launcher';directory.mkdir()
        rows=[dict(run_id=c['run_id'],run_instance_id=c['run_instance_id'],root=str(self.base/'pair-1'/c['run_id']),status='owned_allocated') for c in self.plan['assignments'][0]['cases']]
        with patch.object(live_pilot_launcher.time,'monotonic',return_value=100),patch.object(live_pilot_launcher,'owned_runs',return_value=rows),\
                patch.object(live_pilot_launcher,'observer_disposition',return_value={'manual_resolution_required':True}),\
                patch.object(live_pilot_launcher,'popen') as spawn:
            for reason in ('first_fault','second_result_write_fault'):
                stopped=live_pilot_launcher.stop_owned(self.plan,{'sha256':'f'*64},self.root,directory,child,reason,whole_deadline=100)
                self.assertTrue(stopped['observer_disposition']['manual_resolution_required'])
                self.assertTrue(stopped['child']['unknown']);self.assertTrue(all(r['unknown'] for r in stopped['owned_stops']))
        spawn.assert_not_called();self.assertTrue(all(s==0 for s in child.waits[2:]))

    def test_saved_terminal_proof_recomputes_identically_with_later_clock_and_disk(self):
        # Full resources/evaluators are tested separately. Here only those
        # expensive leaves are replaced; source/PID/approval/command/proof/wall
        # joins are real files, as in _verify followed by later ready().
        repo=self.root/'source';repo.mkdir();launcher=repo/'research/live_pilot_launcher.py'
        launcher.parent.mkdir();launcher.write_text('fixture launcher')
        self.plan.update(source_commit='a'*40,saved_music_postprocessing={'path':'saved','sha256':'c'*64},original_plan={'path':'original','sha256':'d'*64})
        path=self.root/'plan.json';util.write_new_json(path,self.plan);ref=live_pilot.reference(path)
        approved=self.root/'approval.json';util.write_new_json(approved,dict(plan_sha256=ref['sha256'],authorized=True,approved_by='user',
            authorization_reference='finite technical fixture',scope='education_two_run_technical_trial'))
        start=datetime.now(timezone.utc)-timedelta(seconds=10);directory=self.base/'_launcher'
        intent=dict(kind='live_pilot_launcher_v1',schema_version=1,launch_id=uuid.uuid4().hex,launcher_pid=1,parent_pid=2,
            source_sha256=util.sha256_file(launcher),controller_source_commit='a'*40,plan=ref,approval=live_pilot.reference(approved),
            phase_id=self.plan['phase_id'],selected_pair=None,started_at=start.isoformat(),
            whole_deadline_utc=(start+timedelta(seconds=5400)).isoformat(),wall_threshold_seconds=5160,cleanup_reserve_seconds=240,
            command=[sys.executable,'-B','-X','utf8','-m','research.education_readiness_trial','execute',ref['path'],
                     '--repo',str(repo),'--approval',str(approved)])
        util.write_new_json(directory/'intent.json',intent);util.write_new_json(directory/'registration.json',{**intent,'child_pid':3})
        util.write_new_json(self.base/'result.json',dict(kind=trial.KIND,plan_sha256=ref['sha256'],trial_operational_complete=True,
            fault=None,watcher_shutdown_verified=True,original_unchanged=True,old_pilot_adoption=False,automatic_main_start=False,
            finished_at=(start+timedelta(seconds=5)).isoformat(),new_model_runs=2))
        resultref=live_pilot.reference(self.base/'result.json');dispatch={c['run_id']:c for c in self.plan['assignments'][0]['cases']}
        for c in dispatch.values():util.write_new_json(self.base/'pair-1'/c['run_id']/'manifest.json',{'duration_seconds':2})
        normal=dict(requests=3,observed_tokens=17,accumulated_run_seconds=4,http_inflight=0,longest_active_run_seconds=0)
        with patch.object(trial,'validate_plan',return_value=self.plan),patch.object(trial,'sealed_sources',return_value=({},set())),\
                patch.object(live_pilot_launcher,'verify_pair_terminal'),patch.object(pair_execution,'state',return_value={'dispatch':dispatch}),\
                patch.object(trial.TrialWatch,'restore_completed'),patch.object(trial.TrialWatch,'counters',side_effect=[
                    {**normal,'wall_seconds':10,'disk_free_bytes':100000},{**normal,'wall_seconds':400,'disk_free_bytes':200000},
                    {**normal,'wall_seconds':800,'disk_free_bytes':300000}]):
            proof=trial.pipeline_evidence(repo,ref,resultref);util.write_new_json(directory/'terminal-proof.json',proof)
            util.write_new_json(directory/'verification-registration.json',{'pid':4})
            launched=dict(kind='live_pilot_launcher_result_v1',plan=ref,approval=intent['approval'],source_sha256=intent['source_sha256'],
                controller_source_commit='a'*40,launch_id=intent['launch_id'],launcher_pid=1,child_pid=3,selected_pair=None,
                operational_complete=True,watcher_shutdown_verified=True,stop_requested=False,new_main_authorized=False,model_runs=2,
                child_exit_code=0,verification_child_exit_code=0,verification_child_pid=4,elapsed_seconds=10,
                finished_at=(start+timedelta(seconds=10)).isoformat(),terminal_proof=live_pilot.reference(directory/'terminal-proof.json'))
            util.write_new_json(directory/'result.json',launched)
            self.assertTrue(trial.ready(repo,ref,resultref)['ready'])
            util.write_json_atomic(directory/'result.json',{**launched,'finished_at':(start+timedelta(seconds=5401)).isoformat()})
            with self.assertRaisesRegex(ValueError,'5400-second'):trial.ready(repo,ref,resultref)


class TrialPlanGuards(unittest.TestCase):
    def setUp(self):
        from research.tests.test_live_pilot import PlanBoundaries
        fixture=PlanBoundaries();fixture.setUp();self.addCleanup(fixture.doCleanups)
        self.fixture=fixture;self.repo=fixture.repo;self.root=fixture.root
        self.old=copy.deepcopy(fixture.plan)
        oldpath=self.root/'old.json';util.write_new_json(oldpath,self.old)
        self.plan=copy.deepcopy(fixture.plan);self.plan.update(kind=trial.KIND,bounds=dict(trial.BOUNDS),
            batch=str(self.root/'new-trial'),cohort='runs/independent-education-trial',
            phase_id=uuid.uuid4().hex,independent_technical_trial=True,old_pilot_adoption=False,
            sent_run_replay_authorized=False,whole_seconds=5400,cleanup_reserve_seconds=240,
            original_plan=live_pilot.reference(oldpath))
        self.plan['protected_roots'].append(self.old['batch'])
        self.plan['assignments']=[dict(pair=1,cases=[dict(pair=1,slot=i,task='CU1-ENR-C',condition=arm,
            attempt=7001,run_id=run.run_id_for('CU1-ENR-C',arm,7001),run_instance_id=uuid.uuid4().hex)
            for i,arm in enumerate(('explore','preload'),1)])]
        self.plan['case_lineage']=[dict(run_instance_id=c['run_instance_id'],source_case=s)
            for c,s in zip(self.plan['assignments'][0]['cases'],self.old['assignments'][1]['cases'])]
        self.plan['saved_music_postprocessing']={};self.plan['launch_supervisor']=live_pilot.reference(self.repo/'research/live_pilot_launcher.py')
        for name in trial.EXTRA_PINS:
            path=self.repo/name;path.write_text(name);self.plan['source_pins'][name]=util.sha256_file(path)
        rows=[dict(source_run_instance_id=c['run_instance_id'],assessment_id=uuid.uuid4().hex,
                   model_dispatch_count=0,acquisition_count_increment=0,original_pilot_adoption=False)
              for c in self.old['assignments'][0]['cases']]
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(trial,'sealed_sources',return_value=(self.old,set())))
        self.stack.enter_context(patch('research.saved_postprocessing_recovery.validate_saved_music_postprocessing',return_value=rows))

    def validate(self,plan=None):return trial.validate_plan(plan or self.plan,self.repo)

    def test_positive_trial_uses_real_common_source_runtime_namespace_guards(self):
        self.assertEqual(self.validate()['kind'],trial.KIND)

    def test_caps_booleans_lineage_old_uuid_and_traversal_reject_no_writes(self):
        changes=[lambda p:p['bounds'].update(max_runs=4),lambda p:p['bounds'].update(request_count=True),
            lambda p:p.update(whole_seconds=5401),lambda p:p.update(cleanup_reserve_seconds=True),
            lambda p:p.update(independent_technical_trial=False),lambda p:p.update(old_pilot_adoption=True),
            lambda p:p['case_lineage'][0]['source_case'].update(condition='preload'),
            lambda p:p['assignments'][0]['cases'][0].update(run_instance_id=self.old['assignments'][1]['cases'][0]['run_instance_id']),
            lambda p:p['assignments'][0]['cases'][0].update(run_id='../original'),
            lambda p:p.update(batch=str(self.fixture.protected)),lambda p:p['thresholds'].update(cpu_percent_max=float('nan'))]
        before=util.tree_hashes(self.root)
        for change in changes:
            p=copy.deepcopy(self.plan);change(p)
            with self.subTest(change=change),patch.object(util,'write_new_json') as writer,self.assertRaises(ValueError):self.validate(p)
            writer.assert_not_called()
        self.assertEqual(before,util.tree_hashes(self.root))

    def test_missing_new_pin_and_changed_runtime_lock_reject_before_allocation(self):
        p=copy.deepcopy(self.plan);del p['source_pins'][trial.EXTRA_PINS[0]]
        with self.assertRaises(ValueError):self.validate(p)
        path=Path(self.plan['runtime_locks']['deepseek-education-repaired-v1']['path']);path.write_text('tampered lock')
        before=util.tree_hashes(self.root)
        with self.assertRaises(ValueError):self.validate()
        self.assertEqual(before,util.tree_hashes(self.root))

    def test_main_excludes_original_four_and_trial_two_uuid(self):
        from research import acquisition_readiness as main
        path=self.root/'trial.json';util.write_new_json(path,self.plan)
        result=self.root/'result.json';util.write_new_json(result,{})
        owner=dict(readiness_education_trial_plan=live_pilot.reference(path),readiness_education_trial_result=live_pilot.reference(result))
        ids=main.readiness_instance_ids(owner)
        self.assertEqual(len(ids),6)
        self.assertTrue({c['run_instance_id'] for c in self.plan['assignments'][0]['cases']}<=ids)


class ActualSealedSources(unittest.TestCase):
    def test_actual_prepared_zero_send_original_bytes_inputs_and_ack_readonly(self):
        evidence=Path(live_pilot.__file__).resolve().parents[2]/'evaluator-repair-evidence-20261006'
        pre=evidence/'education-independent-trial-zero-send-precheck-v1/result.json'
        if not pre.is_file():self.skipTest('Local sealed acceptance evidence unavailable')
        original=live_pilot.reference(evidence/'repaired-live-pilot-preparation-v1/fixed-plan.json')
        old=trial.document(original);close=trial.document(live_pilot.reference(evidence/'finite-pilot-bounded-stop-sealed-v1/closeout.json'))
        roots=[old['batch'],str(trial.document(live_pilot.reference(evidence/'recovery-live-pilot-preparation-v1/fixed-plan.json'))['batch']),close['failed_batch']]
        p=dict(original_plan=original,original_closeout=live_pilot.reference(evidence/'failed-repaired-pilot-sealed-v1/closeout.json'),
            prior_recovery_closeouts=[live_pilot.reference(evidence/'failed-recovery-observer-startup-sealed-v1/closeout.json')],
            prepared_no_send_closeout=live_pilot.reference(evidence/'finite-pilot-bounded-stop-sealed-v1/closeout.json'),
            zero_send_precheck=live_pilot.reference(pre),protected_roots=roots,phase_id=uuid.uuid4().hex,
            original_wall_start_utc='2026-10-06T07:36:04.941047+00:00',
            carried=dict(sent_runs=2,requests=140,observed_tokens=11946268,accumulated_run_seconds=2102.502),
            expected_input_sha256_by_arm={item['source_case']['condition']:trial.document(item['manifest'])['prompt_sha256'] for item in trial.document(live_pilot.reference(pre))['cases']})
        p['expected_input_files_by_arm']={item['source_case']['condition']:trial.document(item['manifest'])['input_files'] for item in trial.document(live_pilot.reference(pre))['cases']}
        actual=live_pilot.validate_owned_terminal
        # Only current Docker absence observation is omitted; all saved native,
        # raw, assets, source inventories, exact counts and ACK bytes stay real.
        with patch.object(live_pilot,'validate_owned_terminal',side_effect=lambda root,binding:actual(root,binding,observe_resources=False)),patch.object(util,'write_new_json') as writer:
            checked,natives=trial.sealed_sources(p)
        writer.assert_not_called();self.assertEqual(checked['phase_id'],old['phase_id']);self.assertEqual(len(natives),2)
        wrong=copy.deepcopy(p);wrong['expected_input_sha256_by_arm']['explore']='f'*64
        with patch.object(live_pilot,'validate_owned_terminal',side_effect=lambda root,binding:actual(root,binding,observe_resources=False)),self.assertRaisesRegex(ValueError,'input hashes'):
            trial.sealed_sources(wrong)


if __name__=='__main__':unittest.main()
