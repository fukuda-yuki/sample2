"""Finite synthetic readiness controls; no provider, Docker, or real acquisition."""
from collections import Counter
from contextlib import contextmanager
import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import uuid
from unittest.mock import Mock, patch

from outer.harness import profiles, run, util
from research import acquisition_readiness as readiness
from research import catalog_environment, live_pilot, next_phase, pair_execution, repaired_runtime

ROOT = Path(__file__).resolve().parents[2]


class ReadinessFixture(unittest.TestCase):
    MAIN_PINS = True

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = self.root / 'repo'; self.repo.mkdir()
        self.protected = self.root / 'original'; self.protected.mkdir()
        (self.protected / 'immutable.txt').write_text('original sentinel\n', encoding='utf-8')
        self.plan_path = self.root / 'plan.json'
        self.plan = dict(schema_version=1, kind=readiness.KIND, phase_id=uuid.uuid4().hex,
            task_revision=readiness.REVISION, require_fixed_instances=True, pair_concurrency=2,
            source_commit='a'*40, batch=str(self.root / 'fresh'), cohort='runs/fresh-repaired',
            protected_roots=[str(self.protected)], runtime_by_task=dict(readiness.RUNTIMES),
            bounds=dict(readiness.BOUNDS), thresholds=dict(live_pilot.DEFAULT_THRESHOLDS),
            settings=dict(model_id='deepseek-v4.1-flash', provider='opencode-go',
                          use_balance=False, paid_fallback=False),
            source_pins={}, assignments=readiness.assignments(), runtime_locks={})
        names = (*live_pilot.PIN_FILES, *(readiness.EXTRA_PINS if self.MAIN_PINS else ()))
        for name in names:
            target = self.repo / name; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
            self.plan['source_pins'][name] = util.sha256_file(target)
        self.plan['launch_supervisor'] = live_pilot.reference(self.repo/'research/live_pilot_launcher.py')
        for task in readiness.TASKS:
            relative = f'outer/profiles/task-revisions/{readiness.REVISION}/{task}.json'
            target = self.repo / relative; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)
        for runtime_id in set(readiness.RUNTIMES.values()):
            relative = f'outer/profiles/runtimes/{runtime_id}.json'
            target = self.repo / relative; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)
            task = next(t for t in readiness.TASKS if readiness.RUNTIMES[t] == runtime_id)
            runtime = profiles.read(self.repo, 'runtimes', runtime_id)
            ledger = profiles.task_profile(self.repo, task, readiness.REVISION)
            lock = dict(task_profile_revision=readiness.REVISION, runtime_profile_id=runtime_id,
                evaluator_version=ledger['evaluation']['evaluation_version'],
                evaluator_project=ledger['evaluation']['project'])
            path = profiles.runtime_root(self.repo, task, runtime) / 'lock.json'
            util.write_new_json(path, lock)
            self.plan['runtime_locks'][runtime_id] = live_pilot.reference(path)
        for key, name in (('resource_monitor', 'wave_resource_monitor.py'),
                          ('resource_probe', 'wave_resource_probe.py'), ('browser_pin', 'browser.json')):
            path = self.root / name; path.write_text('{}\n', encoding='utf-8')
            self.plan[key] = live_pilot.reference(path)
        self.write_plan()
        self.runtime_binding = self.mock_boundary(repaired_runtime, 'validate_repaired_runtime_binding', return_value=None)
        self.dispatch = self.mock_boundary(live_pilot, 'execute_owned_pair_scope', side_effect=AssertionError('dispatch forbidden'))
        self.mock_boundary(live_pilot.runtime, 'docker', side_effect=AssertionError('Docker forbidden'))
        self.mock_boundary(profiles, 'create', side_effect=AssertionError('real Run preparation forbidden'))

    def mock_boundary(self, target, name, **options):
        boundary = patch.object(target, name, **options)
        value = boundary.start(); self.addCleanup(boundary.stop)
        return value

    def write_plan(self):
        util.write_json_atomic(self.plan_path, self.plan)

    def reject_before_writes(self, change):
        original = copy.deepcopy(self.plan)
        change(self.plan); self.write_plan()
        before = util.tree_hashes(self.root)
        with patch.object(util, 'write_new_json') as writer:
            with self.assertRaises(ValueError):
                readiness.verify_main_phase(self.plan_path, self.repo)
            with self.assertRaises(ValueError):
                readiness.create(self.repo, self.plan_path)
            writer.assert_not_called()
        self.assertEqual(before, util.tree_hashes(self.root))
        self.dispatch.assert_not_called()
        self.plan = original; self.write_plan()

    def allocate(self):
        return readiness.create(self.repo, self.plan_path)

    def approval(self, **changes):
        authorization = self.root / 'synthetic-user-authorization.txt'
        if not authorization.exists():
            authorization.write_text('Synthetic fixture only; no real acquisition permission.\n', encoding='utf-8')
        approval = dict(plan_sha256=util.sha256_file(self.plan_path), authorized=True,
            approved_by='user', authorization_reference=live_pilot.reference(authorization),
            scope='new_100_pairs_200_runs')
        approval.update(changes)
        path = self.root / 'approval.json'; util.write_json_atomic(path, approval)
        return path

    @contextmanager
    def admission_boundaries(self):
        watch = Mock(); watch.finish.return_value = True; watch.fault = None
        watch.latch.side_effect = lambda reason:setattr(watch,'fault',reason)
        def git(repo, *args):
            self.assertEqual(Path(repo), self.repo)
            return self.plan['source_commit'] if args == ('rev-parse', 'HEAD') else ''
        with patch.object(next_phase, 'git', side_effect=git), \
             patch.object(readiness, 'pilot_ready', return_value={'ready': True}) as pilot, \
             patch.object(catalog_environment, 'validate') as browser, \
             patch.object(live_pilot, 'PilotWatch', return_value=watch) as factory:
            yield pilot, browser, factory, watch

    def assert_no_execution_intent(self):
        self.assertFalse(list(Path(self.plan['batch']).glob('pair-*/execution-intent.json')))
        self.dispatch.assert_not_called()


class MainReadinessControls(ReadinessFixture):
    def test_fixed_assignment_balance_and_unique_instances(self):
        protocol = ROOT / readiness.BASE_PROTOCOL
        self.assertEqual(util.sha256_file(protocol), readiness.BASE_PROTOCOL_SHA256)
        original = next_phase.assignments(util.read_json(protocol))
        cases = [case for pair in self.plan['assignments'] for case in pair['cases']]
        self.assertEqual(len(self.plan['assignments']), 100)
        self.assertEqual(len(cases), 200)
        self.assertEqual(Counter(pair['cases'][0]['task'] for pair in self.plan['assignments']),
                         Counter({task: 25 for task in readiness.TASKS}))
        self.assertEqual(Counter(pair['cases'][0]['condition'] for pair in self.plan['assignments']),
                         Counter(explore=50, preload=50))
        first_explore = {task: sum(pair['cases'][0]['condition'] == 'explore'
            for pair in self.plan['assignments'] if pair['cases'][0]['task'] == task) for task in readiness.TASKS}
        self.assertEqual(first_explore, {'MS1-CONT-A': 13, 'MS1-CONT-B': 12, 'CU1-ENR-C': 13, 'CU1-ENR-D': 12})
        self.assertEqual(len({case['run_id'] for case in cases}), 200)
        identities = {case['run_instance_id'] for case in cases}
        self.assertEqual(len(identities), 200)
        self.assertFalse(identities & {case['run_instance_id'] for pair in readiness.assignments() for case in pair['cases']})
        self.assertFalse(identities & {case['run_instance_id'] for pair in original for case in pair['cases']})
        for number, (pair, baseline) in enumerate(zip(self.plan['assignments'], original), 1):
            self.assertEqual(pair['pair'], number)
            self.assertEqual({key:value for key,value in pair.items() if key!='cases'},
                             {key:value for key,value in baseline.items() if key!='cases'})
            self.assertEqual({case['condition'] for case in pair['cases']}, {'explore', 'preload'})
            self.assertEqual(len({case['task'] for case in pair['cases']}), 1)
            self.assertEqual(len({case['attempt'] for case in pair['cases']}), 1)
            self.assertEqual(pair['analysis_session'], (number-1)//4+1)
            for case, old_case in zip(pair['cases'], baseline['cases']):
                self.assertEqual({key:value for key,value in case.items() if key not in ('attempt','run_id','run_instance_id')},
                                 {key:value for key,value in old_case.items() if key not in ('attempt','run_id','run_instance_id')})
                self.assertEqual(case['attempt'], 6000+number)
                self.assertEqual(case['run_id'], f"{case['task']}-{case['condition']}-{case['attempt']:03d}")
        for task in readiness.TASKS:
            for arm in ('explore', 'preload'):
                self.assertEqual(sorted(case['attempt'] for case in cases if case['task'] == task and case['condition'] == arm),
                    sorted(6000+pair['pair'] for pair in original if pair['task']==task))

    def test_read_only_check_and_exclusive_allocation_do_not_dispatch(self):
        before = util.tree_hashes(self.root)
        self.assertEqual(readiness.verify_main_phase(self.plan_path, self.repo), self.plan)
        self.assertEqual(before, util.tree_hashes(self.root))
        self.assertEqual(self.runtime_binding.call_count, 4)
        result = self.allocate()
        self.assertTrue(result['allocated']); self.assertFalse(result['model_dispatched'])
        self.assertFalse(result['automatic_main_start'])
        phases = list(Path(self.plan['batch']).glob('pair-*/phase.json'))
        self.assertEqual(len(phases), 100)
        for pair in self.plan['assignments']:
            phase = util.read_json(Path(self.plan['batch']) / f"pair-{pair['pair']}/phase.json")
            self.assertEqual(phase['assignments'], [pair])
            self.assertEqual(phase['original_bundle'], live_pilot.reference(self.plan_path))
            self.assertEqual(phase['runtime'], readiness.RUNTIMES[pair['cases'][0]['task']])
        allocated = util.tree_hashes(self.root)
        with self.assertRaises(FileExistsError): self.allocate()
        self.assertEqual(allocated, util.tree_hashes(self.root))
        self.dispatch.assert_not_called()

    def test_old_or_protected_roots_and_traversal_rejected_before_writes(self):
        for root in (self.repo, self.repo / 'runs', self.protected, self.protected / 'new', self.root):
            with self.subTest(root=root): self.reject_before_writes(lambda p:p.update(batch=str(root)))
        self.reject_before_writes(lambda p:p.update(cohort='../old'))
        self.reject_before_writes(lambda p:p.update(batch=str(self.root / 'fresh' / '..' / 'original')))

    def test_revision_runtime_uuid_assignment_and_pin_rejections_before_writes(self):
        mutations = [lambda p:p.update(kind=live_pilot.KIND), lambda p:p.update(task_revision='old'),
            lambda p:p.update(require_fixed_instances=False), lambda p:p.update(pair_concurrency=True),
            lambda p:p['runtime_by_task'].update({'MS1-CONT-A':'deepseek-migration-v1'}),
            lambda p:p['assignments'][1]['cases'][0].update(run_instance_id=p['assignments'][0]['cases'][0]['run_instance_id']),
            lambda p:p['assignments'][0]['cases'][0].update(run_instance_id='foreign'),
            lambda p:p['assignments'][0]['cases'][0].update(
                run_instance_id=next(iter(readiness.protected_instance_ids()))),
            lambda p:p['assignments'][0]['cases'][0].update(attempt=True),
            lambda p:p['assignments'][0]['cases'][0].update(run_id='../original'),
            lambda p:p['assignments'][0]['cases'][0].update(condition='preload'),
            lambda p:p['assignments'][0].update(analysis_session=2),
            lambda p:p['assignments'][0].update(source_family='foreign'),
            lambda p:p['assignments'][0]['cases'][0].update(slot=2),
            lambda p:p['assignments'][0]['cases'].reverse(),
            lambda p:p['assignments'].reverse(),
            lambda p:p['assignments'].pop(), lambda p:p['source_pins'].pop(readiness.EXTRA_PINS[0]),
            lambda p:p['source_pins'].update({live_pilot.PIN_FILES[0]:'f'*64}),
            lambda p:p['resource_probe'].update(sha256='f'*64),
            lambda p:p['bounds'].update(max_runs=True), lambda p:p['bounds'].update(max_pairs=99),
            lambda p:p['settings'].update(use_balance=0), lambda p:p['settings'].update(paid_fallback=0),
            lambda p:p['settings'].update(model_id='other-model')]
        for number, change in enumerate(mutations):
            with self.subTest(case=number): self.reject_before_writes(change)

    def test_runtime_lock_reference_and_ledger_guards_precede_allocation(self):
        runtime_id = readiness.RUNTIMES['MS1-CONT-A']
        ref = self.plan['runtime_locks'][runtime_id]
        path = Path(ref['path']); original = util.read_json(path)
        for key, value in (('runtime_profile_id','deepseek'), ('task_profile_revision','old'),
                           ('evaluator_version','1.3.0'), ('evaluator_project','Foreign.csproj')):
            with self.subTest(key=key):
                wrong = {**original, key:value}; util.write_json_atomic(path, wrong)
                self.plan['runtime_locks'][runtime_id] = live_pilot.reference(path); self.write_plan()
                self.reject_before_writes(lambda p:None)
                util.write_json_atomic(path, original)
                self.plan['runtime_locks'][runtime_id] = live_pilot.reference(path); self.write_plan()
        self.reject_before_writes(lambda p:p['runtime_locks'][runtime_id].update(sha256='f'*64))
        foreign = self.root / 'foreign-lock.json'; util.write_new_json(foreign, original)
        self.reject_before_writes(lambda p:p['runtime_locks'].update({runtime_id:live_pilot.reference(foreign)}))

    def test_bound_launcher_requires_exact_owned_source_before_allocation(self):
        self.reject_before_writes(lambda p:p['launch_supervisor'].update(sha256='f'*64))
        foreign = self.root / 'foreign-launcher.py'
        shutil.copyfile(self.repo / 'research/live_pilot_launcher.py', foreign)
        self.assertEqual(util.sha256_file(foreign), self.plan['launch_supervisor']['sha256'])
        self.reject_before_writes(lambda p:p.update(launch_supervisor=live_pilot.reference(foreign)))


class MainAdmissionControls(ReadinessFixture):
    def setUp(self):
        super().setUp()
        # Real ref/hash checks remain exercised. Pipeline admission is mocked
        # here; its durable synthetic journal controls are covered separately.
        for key in ('readiness_pilot_plan', 'readiness_pilot_result'):
            path = self.root / (key + '.json'); util.write_new_json(path, {'synthetic': True})
            self.plan[key] = live_pilot.reference(path)
        self.write_plan(); self.allocate()

    def test_new_exact_100_scope_and_user_authorization_are_required_before_admission(self):
        for changes in ({'scope':'four_run_pilot'}, {'scope':'old_100_pairs'}, {'authorized':1},
                        {'approved_by':'agent'}, {'plan_sha256':'f'*64}, {'authorization_reference':None}):
            with self.subTest(changes=changes), self.admission_boundaries() as (pilot,browser,factory,watch):
                with self.assertRaisesRegex(ValueError, 'authorization'):
                    readiness.execute_pair(self.repo, self.plan_path, 1, self.approval(**changes))
                pilot.assert_not_called(); browser.assert_not_called(); factory.assert_not_called()
                self.assert_no_execution_intent()

    def test_clean_exact_source_and_operational_pilot_are_mandatory(self):
        approval = self.approval()
        for args in (('rev-parse','HEAD'), ('status','--porcelain')):
            with self.subTest(args=args), self.admission_boundaries() as (pilot,browser,factory,watch):
                with patch.object(next_phase,'git',side_effect=lambda repo,*got: 'foreign' if got==args else self.plan['source_commit'] if got==('rev-parse','HEAD') else ''):
                    with self.assertRaisesRegex(ValueError,'Clean exact'):
                        readiness.execute_pair(self.repo,self.plan_path,1,approval)
                factory.assert_not_called(); self.assert_no_execution_intent()
        with self.admission_boundaries() as (pilot,browser,factory,watch):
            pilot.side_effect = ValueError('Actual pilot incomplete')
            with self.assertRaisesRegex(ValueError,'Actual pilot'):
                readiness.execute_pair(self.repo,self.plan_path,1,approval)
            browser.assert_not_called(); factory.assert_not_called(); self.assert_no_execution_intent()

    def test_pending_or_fabricated_predecessor_gate_cannot_admit_pair_two(self):
        approval = self.approval()
        with self.admission_boundaries() as (pilot,browser,factory,watch):
            with self.assertRaisesRegex(ValueError,'publication gate pending'):
                readiness.execute_pair(self.repo,self.plan_path,2,approval)
            factory.assert_not_called(); self.assert_no_execution_intent()
        journal = Path(self.plan['batch']) / 'pair-1/_control/pair-journal.jsonl'
        util.append_line(journal, {'kind':'pair_gate','pair':1,'receipt':'fake','receipt_sha256':'f'*64})
        with self.admission_boundaries() as (pilot,browser,factory,watch):
            with self.assertRaisesRegex(ValueError,'exactly two terminal results'):
                readiness.execute_pair(self.repo,self.plan_path,2,approval)
            factory.assert_not_called(); self.assert_no_execution_intent()

    def test_stop_later_reservation_or_existing_current_event_prevents_replay(self):
        approval = self.approval(); base = Path(self.plan['batch'])
        stop = base / '_control/dispatch-stop.json'; util.write_new_json(stop, {'reason':'synthetic stop'})
        with self.admission_boundaries() as (_,_,factory,_):
            with self.assertRaisesRegex(ValueError,'STOP latched'):
                readiness.execute_pair(self.repo,self.plan_path,1,approval)
            factory.assert_not_called(); self.assert_no_execution_intent()
        stop.unlink()
        later = base / 'pair-100/_control/pair-journal.jsonl'
        util.append_line(later, {'kind':'pair_reserved'})
        with self.admission_boundaries() as (_,_,factory,_):
            with self.assertRaisesRegex(ValueError,'Later pair'):
                readiness.execute_pair(self.repo,self.plan_path,1,approval)
            factory.assert_not_called(); self.assert_no_execution_intent()
        later.unlink()
        current = base / 'pair-1/_control/pair-journal.jsonl'
        current.parent.mkdir(parents=True, exist_ok=True)
        for kind in ('pair_reserved','dispatch','implemented','result'):
            with self.subTest(kind=kind), self.admission_boundaries() as (_,_,factory,_):
                current.write_text('', encoding='utf-8'); util.append_line(current, {'kind':kind})
                with self.assertRaisesRegex(ValueError,'No main pair resend'):
                    readiness.execute_pair(self.repo,self.plan_path,1,approval)
                factory.assert_not_called(); self.assert_no_execution_intent()

    def test_pair_number_is_typed_and_exact(self):
        for number in (True,0,101,'1'):
            with self.subTest(number=number), self.admission_boundaries() as (_,_,factory,_):
                with self.assertRaisesRegex(ValueError,'Fixed pair number'):
                    readiness.execute_pair(self.repo,self.plan_path,number,self.approval())
                factory.assert_not_called(); self.assert_no_execution_intent()

    def test_one_owned_pair_only_and_watcher_shutdown_are_observed(self):
        with self.admission_boundaries() as (pilot,browser,factory,watch):
            self.dispatch.side_effect = None
            self.dispatch.return_value = {'reason':'pair_publication_restore_cleanup_required'}
            result = readiness.execute_pair(self.repo,self.plan_path,1,self.approval())
            self.assertEqual(result, {'reason':'pair_publication_restore_cleanup_required'})
            pilot.assert_called_once_with(self.repo,self.plan['readiness_pilot_plan'],self.plan['readiness_pilot_result'])
            browser.assert_called_once(); watch.start.assert_called_once(); watch.finish.assert_called_once()
            self.dispatch.assert_called_once_with(self.repo,self.plan_path,
                Path(self.plan['batch'])/'pair-1/phase.json',budget_watch=watch)
            self.assertEqual(len(list(Path(self.plan['batch']).glob('pair-*/execution-intent.json'))),1)
            self.assertFalse(list(Path(self.plan['batch']).glob('pair-*/*/manifest.json')))
            receipt=util.read_json(Path(self.plan['batch'])/'pair-1/pair-result.json')
            self.assertTrue(receipt['pair_operational_complete'])
            self.assertTrue(receipt['watcher_shutdown_verified'])
            self.assertFalse(receipt['automatic_next_pair_start'])
            # A retained intent also fences an uncertain attempt with no journal.
            self.dispatch.reset_mock(); factory.reset_mock()
            with self.assertRaises(FileExistsError):
                readiness.execute_pair(self.repo,self.plan_path,1,self.approval())
            factory.assert_not_called(); self.dispatch.assert_not_called()

    def test_cli_check_cannot_claim_start_ready_from_design_or_bogus_pilot_refs(self):
        for design_only in (True,False):
            with self.subTest(design_only=design_only):
                original=copy.deepcopy(self.plan)
                if design_only:
                    self.plan.pop('readiness_pilot_plan');self.plan.pop('readiness_pilot_result')
                    self.write_plan()
                before=util.tree_hashes(self.root)
                with patch.object(sys,'argv',['readiness','check',str(self.plan_path),'--repo',str(self.repo)]):
                    with self.assertRaises((KeyError,ValueError)):readiness.main()
                self.assertEqual(before,util.tree_hashes(self.root));self.dispatch.assert_not_called()
                self.plan=original;self.write_plan()

    def test_unknown_watcher_shutdown_cannot_create_complete_pair_receipt(self):
        with self.admission_boundaries() as (_,_,_,watch):
            watch.finish.return_value=False
            self.dispatch.side_effect=None
            self.dispatch.return_value={'reason':'pair_publication_restore_cleanup_required'}
            readiness.execute_pair(self.repo,self.plan_path,1,self.approval())
            watch.latch.assert_called_once_with('watcher_shutdown_unconfirmed')
            receipt=util.read_json(Path(self.plan['batch'])/'pair-1/pair-result.json')
            self.assertFalse(receipt['pair_operational_complete'])
            self.assertFalse(receipt['watcher_shutdown_verified'])
            self.assertEqual(receipt['fault'],'watcher_shutdown_unconfirmed')
            self.assertFalse(receipt['automatic_next_pair_start'])


class PilotEvidenceControls(ReadinessFixture):
    # pilot_ready validates the pilot controller pins, not main publication pins.
    MAIN_PINS = False

    def setUp(self):
        super().setUp()
        # Exercise validate_owned_terminal itself. Only its read-only resource
        # observations are synthetic: no real Docker process is invoked.
        self.resource_probe = self.mock_boundary(live_pilot.runtime, 'docker',
            return_value=Mock(returncode=0, stdout=''))

    def owned_fixture(self, root, case):
        task = profiles.task_profile(self.repo, case['task'], readiness.REVISION)
        runtime = profiles.read(self.repo, 'runtimes', readiness.RUNTIMES[case['task']])
        condition = {**task, 'schema_version':2, 'runtime':runtime,
                     'task_profile_revision':readiness.REVISION}
        util.write_new_json(root/'condition.json',condition)
        util.write_new_json(root/'context.json',{'synthetic':True})
        util.write_new_json(root/'profiles/task.json',task)
        util.write_new_json(root/'profiles/runtime.json',runtime)
        util.write_new_json(root/'evaluation-assets/requirements.json',util.read_json(ROOT/task['evaluation']['spec_path']))
        (root/'inputs').mkdir()
        (root/'inputs/prompt.txt').write_text('Synthetic public input; never dispatched.\n',encoding='utf-8')
        identity=dict(run_id=case['run_id'],run_instance_id=case['run_instance_id'])
        network='s2-net-'+case['run_instance_id'][:16]
        network_id=case['run_instance_id']*2
        cleanup=dict(**identity,network=network,network_id=network_id,confirmed=True,status='absent')
        util.write_new_json(root/'runtime.json',dict(**identity,stop_confirmed=True,
            network=network,network_id=network_id,worker='s2-worker-'+case['run_instance_id'][:16],
            gateway='s2-gateway-'+case['run_instance_id'][:16]))
        util.write_new_json(root/'evidence/network-cleanup/final-result.json',cleanup)
        util.write_new_json(root/'usage/normalized.json',dict(usage_complete=True,input_reached=True,
            run_instance_id=case['run_instance_id']))
        util.write_new_json(root/'usage/provenance.json',dict(**identity,expected_sessions=[case['run_instance_id']],
            inventory_complete=True,native_agent_session_ids=['synthetic-native-'+case['run_instance_id']],native_step_count=1))
        manifest=dict(**identity,schema_version=2,stop_confirmed=True,assignment=case,network_cleanup=cleanup,
            condition_sha256=util.sha256_file(root/'condition.json'),prompt_sha256=util.sha256_file(root/'inputs/prompt.txt'),
            context_sha256=util.sha256_file(root/'context.json'),input_files=util.tree_hashes(root/'inputs'),
            profile_files=util.tree_hashes(root/'profiles'),assets_sha256=util.tree_hashes(root/'evaluation-assets'))
        util.write_new_json(root/'manifest.json',manifest)
        return manifest

    def observer_fixture(self, plan, plan_ref, pair, child, bindings):
        phase=child/'phase.json';phase_hash=util.sha256_file(phase)
        session=uuid.uuid4().hex;directory=Path(plan['batch'])/'_observers'/session
        scope=dict(session=session,phase_sha256=phase_hash,generation=1,pairs=[pair['pair']],bindings=bindings)
        request=directory/'scope-000001.json';util.write_new_json(request,scope)
        util.write_new_json(directory/'scope-ack-000001.json',dict(session=session,generation=1,
            accepted=True,scope_sha256=util.sha256_file(request)))
        util.write_new_json(directory/'config.json',dict(session=session,directory=str(directory),phase=live_pilot.reference(phase)))
        shutdown=dict(session=session,phase_sha256=phase_hash,generation=1,
            dispatched=sorted(case['run_id'] for case in pair['cases']))
        util.write_new_json(directory/'shutdown.json',shutdown)
        util.write_new_json(directory/'shutdown-ack.json',dict(**shutdown,
            owned_resources_resolved=True,monitor_stop_confirmed=True,fault_latched=False))
        sample=directory/'samples/original-resource.json'
        util.write_new_json(sample,{'synthetic_readonly_resource_sample':True})
        status=directory/'envelopes/final.json'
        util.write_new_json(status,dict(session=session,phase_sha256=phase_hash,generation=1,
            sampled_scope_generation=1,snapshot=dict(host_healthy=True,resource_healthy=True,
                evidence_files={str(sample):util.sha256_file(sample)})))
        util.write_new_json(directory/'status.json',live_pilot.reference(status))
        util.write_new_json(child/'observer-terminal.json',dict(plan_sha256=plan_ref['sha256'],
            phase_sha256=phase_hash,plan=plan_ref,phase=live_pilot.reference(phase),session=session,
            directory=str(directory),generation=1,observer_ack_verified=True,observer_exit_code=0,
            evidence_files={name:record['sha256'] for name,record in util.tree_hashes(directory).items()}))

    def synthetic_saved_pilot(self):
        plan = copy.deepcopy(self.plan)
        plan.update(kind=live_pilot.KIND,batch=str(self.root/'pilot'),bounds=dict(live_pilot.BOUNDS),
            runtime_by_task={task:readiness.RUNTIMES[task] for task in ('MS1-CONT-A','CU1-ENR-C')})
        plan['assignments'] = []
        for number,task in enumerate(('MS1-CONT-A','CU1-ENR-C'),1):
            plan['assignments'].append(dict(pair=number,cases=[dict(pair=number,slot=slot,task=task,
                condition=arm,attempt=1,run_id=run.run_id_for(task,arm,1),run_instance_id=uuid.uuid4().hex)
                for slot,arm in enumerate(('explore','preload'),1)]))
        path = self.root/'pilot-plan.json'; util.write_new_json(path,plan)
        plan_ref=live_pilot.reference(path)
        for pair in plan['assignments']:
            child=Path(plan['batch'])/f"pair-{pair['pair']}"
            phase=child/'phase.json';util.write_new_json(phase,live_pilot.observer_phase(plan,plan_ref,pair['pair']))
            phase_data=util.read_json(phase)
            journal=child/'_control/pair-journal.jsonl'
            bindings=[]
            for case in pair['cases']:
                manifest=self.owned_fixture(child/case['run_id'],case)
                bindings.append(dict(**case,plan_sha256=plan_ref['sha256'],phase_sha256=util.sha256_file(phase),
                    cohort=phase_data['cohort'],runtime=phase_data['runtime'],
                    condition_sha256=manifest['condition_sha256'],input_sha256=manifest['prompt_sha256']))
            pair_execution.append(journal,{'kind':'pair_reserved','assignments':bindings})
            for binding in bindings:
                pair_execution.append(journal,{'kind':'dispatch',**binding})
            for binding in bindings:
                root=child/binding['run_id']
                event=dict(run_id=binding['run_id'],session_id=binding['run_instance_id'],request_id='synthetic-1',
                    model_id='deepseek-v4.1-flash',response_model_id='deepseek-v4.1-flash',
                    status='completed',usage_complete=True,send_evidence='observed_send',http_status=200,
                    usage=dict(input_tokens=10,output_tokens=3))
                for name in ('started','events'):util.append_line(root/f'usage/raw/{name}.jsonl',event)
                util.append_line(root/'evidence/agent.jsonl',dict(type='step_finish',
                    sessionID='synthetic-native-'+binding['run_instance_id']))
                util.write_new_json(root/'snapshot.json',{'synthetic':True})
                implementation=dict(run_id=binding['run_id'],
                    run_instance_id=binding['run_instance_id'],stop_confirmed=True,
                    raw=util.tree_hashes(root/'usage/raw'),snapshot_sha256=util.sha256_file(root/'snapshot.json'))
                util.write_new_json(root/'implementation-receipt.json',implementation)
                pair_execution._record_implementation(journal,binding,implementation,child)
                row={'scoring':{'state':'complete'},'operation_status':'complete',
                     'synthetic_product_pass':False}
                receipt=child/'_control'/('result-'+binding['run_id']+'.json')
                util.write_new_json(receipt,{**binding,'row':row})
                pair_execution.append(journal,{'kind':'result',**binding,'row':row,
                    'receipt':str(receipt),'receipt_sha256':util.sha256_file(receipt)})
            self.observer_fixture(plan,plan_ref,pair,child,bindings)
            proofs=[live_pilot.validate_owned_terminal(child/b['run_id'],b) for b in bindings]
            util.write_new_json(child/'owned-terminal-proof.json',dict(plan_sha256=plan_ref['sha256'],
                phase_sha256=util.sha256_file(phase),runs=proofs))
        result=self.root/'pilot-result.json'
        util.write_new_json(result,dict(kind=live_pilot.KIND,plan_sha256=util.sha256_file(path),
            pilot_operational_complete=True,fault=None,watcher_shutdown_verified=True))
        result_ref=live_pilot.reference(result)
        self.launcher_fixture(plan,plan_ref,result_ref)
        return plan,plan_ref,result_ref

    def launcher_fixture(self, plan, plan_ref, result_ref):
        directory=Path(plan['batch'])/'_launcher'
        authorization=self.root/'synthetic-pilot-permission.txt'
        authorization.write_text('Synthetic unit fixture; no actual launch permission.\n',encoding='utf-8')
        approval=self.root/'pilot-approval.json'
        util.write_new_json(approval,dict(plan_sha256=plan_ref['sha256'],authorized=True,
            approved_by='user',authorization_reference=live_pilot.reference(authorization)))
        intent=dict(schema_version=1,kind='live_pilot_launcher_v1',launch_id=uuid.uuid4().hex,
            plan=plan_ref,phase_id=plan['phase_id'],approval=live_pilot.reference(approval),
            selected_pair=None,controller_source_commit=plan['source_commit'],
            source_sha256=util.sha256_file(self.repo/'research/live_pilot_launcher.py'),
            launcher_pid=42,parent_pid=43,started_at=run.now(),command=[str(Path(sys.executable).resolve()),
                '-B','-X','utf8','-m','research.live_pilot','execute',plan_ref['path'],
                '--repo',str(self.repo.resolve()),'--approval',str(approval)])
        util.write_new_json(directory/'intent.json',intent)
        util.write_new_json(directory/'registration.json',{**intent,'child_pid':44})
        terminal=readiness._pilot_pipeline_evidence(self.repo,plan_ref,result_ref)
        util.write_new_json(directory/'terminal-proof.json',terminal)
        util.write_new_json(directory/'result.json',dict(kind='live_pilot_launcher_result_v1',
            **{key:intent[key] for key in ('approval','controller_source_commit','launch_id','launcher_pid','plan','source_sha256')},
            child_pid=44,verification_child_pid=45,watcher_shutdown_verified=True,operational_complete=True,
            child_exit_code=0,verification_child_exit_code=0,stop_requested=False,selected_pair=None,
            model_runs=4,new_main_authorized=False,terminal_proof=live_pilot.reference(directory/'terminal-proof.json')))

    def test_durable_four_run_journal_evidence_is_read_only_and_not_main_permission(self):
        plan,plan_ref,result_ref=self.synthetic_saved_pilot()
        before=util.tree_hashes(self.root)
        result=readiness.pilot_ready(self.repo,plan_ref,result_ref)
        self.assertTrue(result['ready']);self.assertEqual(result['model_runs'],4)
        self.assertFalse(result['product_quality_guaranteed']);self.assertFalse(result['new_main_authorized'])
        self.assertEqual(before,util.tree_hashes(self.root));self.dispatch.assert_not_called()

    def test_pilot_ack_stop_usage_requests_fault_and_identity_are_required(self):
        plan,plan_ref,result_ref=self.synthetic_saved_pilot()
        child=Path(plan['batch'])/'pair-1';case=plan['assignments'][0]['cases'][0];root=child/case['run_id']
        terminal=child/'observer-terminal.json';normalized=root/'usage/normalized.json'
        event=root/'usage/raw/events.jsonl';manifest=root/'manifest.json'
        controls=[(terminal,{'observer_ack_verified':False}), (normalized,{'usage_complete':False}),
                  (event,None),(manifest,{**util.read_json(manifest),'run_instance_id':'f'*32})]
        for path,wrong in controls:
            with self.subTest(path=path.name):
                original=path.read_bytes()
                if wrong is None:path.write_text('',encoding='utf-8')
                else:util.write_json_atomic(path,wrong)
                before=util.tree_hashes(self.root)
                with self.assertRaises(ValueError):readiness.pilot_ready(self.repo,plan_ref,result_ref)
                self.assertEqual(before,util.tree_hashes(self.root));path.write_bytes(original)
        result_path=Path(result_ref['path']);original=util.read_json(result_path)
        for changes in ({'fault':'observer failure'},{'pilot_operational_complete':False},{'watcher_shutdown_verified':False}):
            with self.subTest(changes=changes):
                util.write_json_atomic(result_path,{**original,**changes})
                with self.assertRaises(ValueError):readiness.pilot_ready(self.repo,plan_ref,live_pilot.reference(result_path))
        self.dispatch.assert_not_called()

    def test_durable_stop_and_scoring_receipt_content_are_rechecked(self):
        plan,plan_ref,result_ref=self.synthetic_saved_pilot()
        child=Path(plan['batch'])/'pair-1'
        rid=plan['assignments'][0]['cases'][0]['run_id']
        journal=child/'_control/pair-journal.jsonl'
        original_journal=journal.read_bytes()
        for kind in ('implemented','result'):
            with self.subTest(kind=kind):
                events=pair_execution.events(journal)
                entry=next(e for e in events if e.get('run_id')==rid and e['kind']==kind)
                receipt_path=Path(entry['receipt_path'] if kind=='implemented' else entry['receipt'])
                original_receipt=receipt_path.read_bytes()
                receipt=util.read_json(receipt_path)
                if kind=='implemented':
                    receipt['receipt']['stop_confirmed']=False
                    entry['receipt']=receipt['receipt']
                else:
                    receipt['row']['scoring']['state']='evaluator_fault'
                    entry['row']=receipt['row']
                util.write_json_atomic(receipt_path,receipt)
                entry['receipt_sha256']=util.sha256_file(receipt_path)
                journal.write_text(''.join(json.dumps(event)+'\n' for event in events),encoding='utf-8')
                with self.assertRaisesRegex(ValueError,'Pilot stop/usage/evaluator fault'):
                    readiness.pilot_ready(self.repo,plan_ref,result_ref)
                journal.write_bytes(original_journal);receipt_path.write_bytes(original_receipt)
        self.dispatch.assert_not_called()

    def test_observer_flags_alone_and_stale_original_samples_cannot_satisfy_pilot(self):
        plan,plan_ref,result_ref=self.synthetic_saved_pilot()
        terminal=Path(plan['batch'])/'pair-1/observer-terminal.json'
        original=terminal.read_bytes()
        util.write_json_atomic(terminal,{'observer_ack_verified':True,'observer_exit_code':0})
        with self.assertRaises(ValueError):readiness.pilot_ready(self.repo,plan_ref,result_ref)
        terminal.write_bytes(original)
        directory=Path(util.read_json(terminal)['directory'])
        sample=directory/'samples/original-resource.json'
        sample.write_text('stale synthetic sample\n',encoding='utf-8')
        before=util.tree_hashes(self.root)
        with self.assertRaisesRegex(ValueError,'Observer evidence pin changed'):
            readiness.pilot_ready(self.repo,plan_ref,result_ref)
        self.assertEqual(before,util.tree_hashes(self.root));self.dispatch.assert_not_called()

    def test_hash_rebound_foreign_ack_or_unhealthy_generation_is_rejected(self):
        plan,plan_ref,result_ref=self.synthetic_saved_pilot()
        terminal=Path(plan['batch'])/'pair-1/observer-terminal.json'
        original_terminal=terminal.read_bytes()
        directory=Path(util.read_json(terminal)['directory'])
        controls=[('shutdown-ack.json',lambda v:v.update(session='f'*32)),
                  ('shutdown-ack.json',lambda v:v.update(owned_resources_resolved=False)),
                  ('envelopes/final.json',lambda v:v.update(sampled_scope_generation=2)),
                  ('envelopes/final.json',lambda v:v['snapshot'].update(resource_healthy=False))]
        for relative,mutate in controls:
            with self.subTest(relative=relative, mutation=controls.index((relative,mutate))):
                target=directory/relative;original=target.read_bytes()
                pointer=directory/'status.json';original_pointer=pointer.read_bytes()
                value=util.read_json(target);mutate(value);util.write_json_atomic(target,value)
                proof=util.read_json(terminal);proof['evidence_files'][relative]=util.sha256_file(target)
                if relative=='envelopes/final.json':
                    util.write_json_atomic(pointer,live_pilot.reference(target))
                    proof['evidence_files']['status.json']=util.sha256_file(pointer)
                util.write_json_atomic(terminal,proof)
                before=util.tree_hashes(self.root)
                with self.assertRaises(ValueError):readiness.pilot_ready(self.repo,plan_ref,result_ref)
                self.assertEqual(before,util.tree_hashes(self.root))
                target.write_bytes(original);pointer.write_bytes(original_pointer);terminal.write_bytes(original_terminal)
        self.dispatch.assert_not_called()

    def test_owned_proof_mismatch_source_tamper_and_unobservable_resources_cannot_pass(self):
        plan,plan_ref,result_ref=self.synthetic_saved_pilot()
        child=Path(plan['batch'])/'pair-1';owned=child/'owned-terminal-proof.json'
        original=owned.read_bytes();proof=util.read_json(owned)
        proof['runs'][0]['run_instance_id']='f'*32;util.write_json_atomic(owned,proof)
        with self.assertRaisesRegex(ValueError,'Owned terminal/provenance proof changed'):
            readiness.pilot_ready(self.repo,plan_ref,result_ref)
        owned.write_bytes(original)
        condition=child/plan['assignments'][0]['cases'][0]['run_id']/'condition.json'
        original_condition=condition.read_bytes();condition.write_bytes(original_condition+b'\n')
        with self.assertRaisesRegex(ValueError,'Frozen condition changed'):
            readiness.pilot_ready(self.repo,plan_ref,result_ref)
        condition.write_bytes(original_condition)
        self.resource_probe.return_value=Mock(returncode=1,stdout='')
        with self.assertRaisesRegex(RuntimeError,'absence unobservable'):
            readiness.pilot_ready(self.repo,plan_ref,result_ref)
        self.dispatch.assert_not_called()

    def test_missing_or_foreign_bounded_launcher_cannot_authorize_main_readiness(self):
        plan,plan_ref,result_ref=self.synthetic_saved_pilot()
        directory=Path(plan['batch'])/'_launcher'
        originals={name:(directory/name).read_bytes() for name in (
            'intent.json','registration.json','result.json','terminal-proof.json')}
        intent_path=directory/'intent.json';intent_path.unlink()
        with self.assertRaises(FileNotFoundError):readiness.pilot_ready(self.repo,plan_ref,result_ref)
        intent_path.write_bytes(originals['intent.json'])
        foreign_approval=self.root/'foreign-pilot-approval.json'
        util.write_new_json(foreign_approval,dict(plan_sha256='f'*64,authorized=True,
            approved_by='user',authorization_reference=plan_ref))
        def foreign_command(value):value['command'][5]='research.foreign'
        def bad_approval(value):
            value['approval']=live_pilot.reference(foreign_approval)
            value['command'][-1]=str(foreign_approval)
        controls=[('intent.json',foreign_command),('intent.json',bad_approval),
                  ('result.json',lambda v:v.update(source_sha256='f'*64)),
                  ('result.json',lambda v:v.update(child_exit_code=False)),
                  ('result.json',lambda v:v.update(verification_child_exit_code=False)),
                  ('result.json',lambda v:v.update(child_pid=999)),
                  ('result.json',lambda v:v.update(model_runs=2)),
                  ('result.json',lambda v:v.update(new_main_authorized=True)),
                  ('terminal-proof.json',lambda v:v.update(ready=False))]
        for number,(relative,mutate) in enumerate(controls):
            with self.subTest(case=number):
                target=directory/relative;value=util.read_json(target);mutate(value)
                util.write_json_atomic(target,value)
                if relative=='intent.json':
                    util.write_json_atomic(directory/'registration.json',{**value,'child_pid':44})
                if relative=='terminal-proof.json':
                    result=util.read_json(directory/'result.json')
                    result['terminal_proof']=live_pilot.reference(target)
                    util.write_json_atomic(directory/'result.json',result)
                before=util.tree_hashes(self.root)
                with self.assertRaises(ValueError):readiness.pilot_ready(self.repo,plan_ref,result_ref)
                self.assertEqual(before,util.tree_hashes(self.root))
                for name,raw in originals.items():(directory/name).write_bytes(raw)
        self.dispatch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
