"""Finite same-version copy/amendment boundaries; no app/Docker/model execution."""
import copy
from contextlib import closing
import json
import shutil
import sqlite3
from unittest import TestCase
from unittest.mock import patch

from outer.harness import util
from research import live_pilot, repaired_runtime, saved_postprocessing_recovery as subject
from research.tests import test_repaired_runtime_scoring as scoring_fixture


class SavedPostprocessingRecoveryTests(TestCase):
    def setUp(self):
        self.fixture = scoring_fixture.RepairedScoringTests('test_historical_false_clean_reaches_actual_score_run_without_relabeling')
        self.addCleanup(self.fixture.doCleanups)
        self.f, root, condition = self.fixture.fixture()
        self.source = self.f.base/'original/pair-1'/root.name
        self.source.parent.mkdir(parents=True)
        shutil.move(root, self.source)
        self.f.write('research/saved_postprocessing_recovery.py', 'frozen fixture source')
        self.f.write('inner/browser/cart-review.cjs', 'frozen finite collector')
        (self.source/'usage/raw').mkdir(parents=True)
        (self.source/'usage/raw/original.json').write_text('original provider bytes', encoding='utf-8')
        util.append_line(self.source/'usage/events.jsonl',dict(request_id='finite-request',
            model_id='deepseek-v4.1-flash',status='completed',started_at='2026-10-06T00:00:00+00:00',
            usage=dict(input_tokens=82,output_tokens=58)))
        original_lock = copy.deepcopy(condition['runtime_lock'])
        original_lock['controller_source_commit'] = 'b'*40
        original_lock['repaired_runtime_binding']['current_applicability']['source_commit'] = 'b'*40
        self.old_lock = self.f.base/'historical-lock.json'
        util.write_new_json(self.old_lock, original_lock)
        condition['runtime_lock'] = original_lock
        util.write_json_atomic(self.source/'condition.json', condition)
        self.fixture.freeze(self.source)
        self.binding = dict(pair=1, slot=1, task='MS1-CONT-A', condition='explore', attempt=1,
            run_id=self.source.name, run_instance_id='1'*32)
        browser=self.f.base/'browser.json'; util.write_new_json(browser,{})
        self.plan = dict(kind=live_pilot.KIND, batch=str(self.source.parent.parent),
            assignments=[dict(pair=1, cases=[self.binding, dict(self.binding, slot=2,
                run_id='other-preload', run_instance_id='2'*32, condition='preload')]), dict(pair=2,cases=[])],
            runtime_locks={self.f.runtime_id: live_pilot.reference(self.old_lock)}, browser_pin=live_pilot.reference(browser))
        self.planpath = self.f.base/'original-plan.json'
        util.write_new_json(self.planpath, self.plan)
        self.planref = live_pilot.reference(self.planpath)
        self.dispatch = dict(self.binding, plan_sha256=self.planref['sha256'])
        self.terminal = dict(run_id=self.source.name, run_instance_id='1'*32, native_session_id='actual-native-fixture')
        for patcher in (
            patch.object(repaired_runtime, 'FAMILIES', {'fixture':self.f.family}),
            patch.object(repaired_runtime, '_git', return_value=''),
            patch.object(repaired_runtime, '_committed_files'),
            patch.object(live_pilot, 'PIN_FILES', ()),
            patch.object(subject.pair_execution, 'state', return_value={'dispatch':{self.source.name:self.dispatch}}),
            patch.object(live_pilot, 'validate_owned_terminal', return_value=self.terminal)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.destination = self.f.base/'technical'

    def prepare(self):
        return subject.prepare(repo=self.f.repo, source=self.source, destination=self.destination,
                               original_plan_ref=self.planref)

    def test_complete_copy_only_declared_amendments_same_version_original_unchanged(self):
        before = subject.byte_inventory(self.source)
        ref = self.prepare()
        a, root, source, _ = subject._inputs(self.f.repo, ref, self.planref)
        self.assertNotEqual(a['assessment_id'], a['source_run_instance_id'])
        self.assertEqual(a['evaluation_version'], '1.6.0')
        self.assertEqual(a['model_dispatch_count'], 0)
        self.assertFalse(a['original_pilot_adoption'])
        self.assertEqual(subject.byte_inventory(source), before)
        self.assertEqual(subject.byte_inventory(root/'usage'), subject.byte_inventory(source/'usage'))
        self.assertIs(util.read_json(root/'condition.json')['evaluation']['evaluator_build']['clean_worktree'], False)
        changed = {name for name, sha in before.items() if subject.byte_inventory(root)[name] != sha}
        self.assertEqual(changed, {'condition.json','manifest.json'})

    def test_foreign_source_rejected_before_copy(self):
        with self.assertRaises(ValueError):
            subject.prepare(repo=self.f.repo, source=self.f.base/'foreign', destination=self.destination,
                            original_plan_ref=self.planref)
        self.assertFalse(self.destination.exists())

    def test_overlapping_destination_rejected(self):
        with self.assertRaises(ValueError):
            subject.prepare(repo=self.f.repo, source=self.source, destination=self.source/'new',
                            original_plan_ref=self.planref)

    def test_controller_amendment_cannot_change_build(self):
        lock = util.read_json(self.f.root/'lock.json')
        lock['evaluator_build']['clean_worktree'] = True
        util.write_json_atomic(self.f.root/'lock.json', lock)
        with self.assertRaises(ValueError): self.prepare()
        self.assertFalse(self.destination.exists())

    def test_original_changes_after_copy_refuse_before_postprocessing(self):
        ref = self.prepare()
        (self.source/'usage/raw/original.json').write_text('changed', encoding='utf-8')
        with patch.object(subject.machine,'postprocess') as process:
            with self.assertRaises(ValueError):
                subject.execute(repo=self.f.repo, assessment_ref=ref, original_plan_ref=self.planref)
            process.assert_not_called()

    def test_derivative_input_change_refused_even_manifest_refrozen(self):
        ref = self.prepare()
        a = util.read_json(live_pilot.checked(ref)); root = subject.Path(a['run_path'])
        (root/'inputs/prompt.txt').write_text('different prompt', encoding='utf-8')
        self.fixture.freeze(root)
        with self.assertRaises(ValueError): subject._inputs(self.f.repo, ref, self.planref)

    def test_derivative_only_declared_runtime_lock_amendment(self):
        ref = self.prepare()
        a = util.read_json(live_pilot.checked(ref)); root = subject.Path(a['run_path'])
        condition = util.read_json(root/'condition.json'); condition['runtime']['model_id']='different-model'
        util.write_json_atomic(root/'condition.json',condition)
        self.fixture.freeze(root)
        with self.assertRaises(ValueError): subject._inputs(self.f.repo, ref, self.planref)

    def test_uncertain_attempt_never_automatically_repeated(self):
        ref = self.prepare(); a = util.read_json(live_pilot.checked(ref)); root = subject.Path(a['run_path'])
        (root/'evaluation-work/001').mkdir(parents=True)
        (root/'evaluation-work/001/uncertain.log').write_text('attempt exists')
        with patch.object(subject.machine,'postprocess') as process:
            with self.assertRaises(ValueError):
                subject.execute(repo=self.f.repo,assessment_ref=ref,original_plan_ref=self.planref)
            process.assert_not_called()

    def test_copy_protects_native_raw_workspace_not_just_frozen_artifact(self):
        ref = self.prepare(); a = util.read_json(live_pilot.checked(ref)); root = subject.Path(a['run_path'])
        (root/'usage/raw/original.json').write_text('modified native provenance')
        with self.assertRaises(ValueError): subject._unchanged_copy(a,root)

    def test_processing_exception_is_durable_not_complete_and_not_repeated(self):
        ref = self.prepare()
        with patch.object(subject.catalog_environment,'activated') as env, \
                patch.object(subject.machine,'postprocess',side_effect=RuntimeError('finite error')) as process, \
                patch.object(live_pilot,'checked',side_effect=lambda ref: subject.Path(ref['path'])):
            # Browser plan leaf is finite; ordinary postprocess error is recorded.
            browser = self.f.base/'browser.json'
            plan = copy.deepcopy(self.plan); plan['browser_pin']=live_pilot.reference(browser)
            with patch.object(subject,'_inputs',return_value=(*subject._inputs(self.f.repo,ref,self.planref)[:3],plan)):
                resultref=subject.execute(repo=self.f.repo,assessment_ref=ref,original_plan_ref=self.planref)
            result=util.read_json(live_pilot.checked(resultref))
            self.assertFalse(result['operational_complete']); self.assertEqual(result['error_type'],'RuntimeError')
            self.assertEqual(result['native_session_id'],self.terminal['native_session_id'])
            self.assertEqual(process.call_count,1)
        with self.assertRaises(FileExistsError):
            subject.execute(repo=self.f.repo,assessment_ref=ref,original_plan_ref=self.planref)

    def test_single_duplicate_or_foreign_source_receipts_cannot_open_education(self):
        row=dict(source_run_id=self.binding['run_id'],source_run_instance_id='1'*32,assessment_id='a'*32)
        for rows in ([row], [row,row], [row,dict(row,source_run_instance_id='9'*32,assessment_id='b'*32)]):
            with self.subTest(rows=len(rows)), self.assertRaises(ValueError):
                subject._exact_two(rows,self.planref)

    def test_evaluator_fault_result_never_ready(self):
        path=self.f.base/'failure.json'
        util.write_new_json(path,dict(kind=subject.KIND,schema_version=1,original_plan=self.planref,
            operational_complete=False,error_type='RuntimeError',source_unchanged=True,
            model_dispatch_count=0,acquisition_count_increment=0,original_pilot_adoption=False))
        with self.assertRaises(ValueError): subject._validate_one(self.f.repo,live_pilot.reference(path),self.planref)

    def pipeline_fixture(self, ref=None):
        ref=ref or self.prepare(); a=util.read_json(live_pilot.checked(ref)); root=subject.Path(a['run_path'])
        directory=root/'evaluations'/'finite-evaluation'; directory.mkdir(parents=True)
        artifact=util.artifact_hash(root/'frozen'); spec=a['spec_sha256']; instance=a['source_run_instance_id']
        output=dict(taskId='MS1-CONT-A',artifactPath='/artifact',artifactSha256=artifact,specSha256=spec,
            evaluationVersion='1.6.0',evaluationId='e'*32,reviewRunInstanceId=instance,
            quality=None,researchStatus='incomplete',verdict='fail_critical',evaluatorFaults=[])
        review=directory/'browser-cart'; review.mkdir()
        request=dict(runInstanceId=instance,artifactSha256=artifact,specSha256=spec,evaluationVersion='1.6.0',baseUrl='http://127.0.0.1:1234')
        util.write_new_json(review/'request.json',request)
        util.write_new_json(review/'receipt.json',dict(request,actor='agent',faults=[],removals=[],
            requestSha256=util.sha256_file(review/'request.json')))
        output['browserCartEvidenceSha256']=util.sha256_file(review/'receipt.json')
        util.write_new_json(directory/'evaluation.json',output)
        util.write_new_json(directory/'evaluator-manifest.json',dict(evaluatorSha256=a['evaluator_sha256']))
        util.write_new_json(directory/'browser-cleanup.json',dict(confirmed=True,run_instance_id=instance))
        util.write_new_json(directory/'browser-intent.json',dict(run_instance_id=instance,model_called=False,
            artifact_sha256=artifact,spec_sha256=spec,evaluator_sha256=a['evaluator_sha256'],
            collector_sha256=a['controller_files']['inner/browser/cart-review.cjs']))
        record=subject.evaluate._base_record(root.name,1,'1.6.0',3,artifact,spec,'evaluation_incomplete',output,[],
            ['finite'],evaluator_sha256=a['evaluator_sha256'])
        record.update(directory='evaluations/finite-evaluation',evaluation_sha256=util.sha256_file(directory/'evaluation.json'))
        util.append_line(root/'evaluations/index.jsonl',record)
        events=util.read_lines(root/'usage/events.jsonl')
        telemetry=root/'telemetry'; telemetry.mkdir()
        payload=subject.monitor.payload(events,root.name,util.read_json(root/'manifest.json'))
        util.write_new_json(telemetry/'gateway.otlp.json',payload)
        with closing(sqlite3.connect(telemetry/'monitor.db')) as db:
            db.execute('CREATE TABLE raw_records (id INTEGER,payload_json TEXT)')
            db.execute('INSERT INTO raw_records VALUES(1,?)',(json.dumps(payload),))
            db.commit()
        totals=subject.monitor.usage_totals(events)
        normalized=dict(experiment_id=root.name,turn_count=1,input_tokens=82,output_tokens=58)
        util.write_new_json(telemetry/'normalized-readback.json',[normalized])
        util.write_new_json(root/'telemetry-link.json',dict(verified=True,usage_complete=True,
            raw_sha256=util.sha256_file(telemetry/'gateway.otlp.json'),raw_record_ids=[1],
            request_count=1,usage_totals=totals,readback={'input_tokens':{'matched':True}}))
        archive=live_pilot.checked(ref).parent/'archive'
        package=subject.preserve.pack(archive,'finite-package',
            {p.name:p for p in root.iterdir() if p.name!='postprocess-timing.jsonl'},
            metadata=dict(missing=[],kind='run',run_id=root.name,stop_confirmed=True,submission_fixed=True))
        util.write_new_json(root/'archive-reference.json',package)
        row=dict(scoring={'state':'evaluation_incomplete'},operation_status='evaluation_incomplete',quality=None,
                 confirmed_product_failure={'verdict':'fail_critical'})
        return a,root,archive,directory,row

    def test_partial_known_product_failure_is_not_promoted_or_erased(self):
        a,root,archive,_,row=self.pipeline_fixture()
        with patch.object(subject.aggregate,'row_for',return_value=row):
            result=subject._pipeline(root,archive,a)
        self.assertIsNone(result['row']['quality'])
        self.assertEqual(result['scoring']['scoring_state'],'evaluation_incomplete')
        self.assertEqual(result['row']['confirmed_product_failure']['verdict'],'fail_critical')

    def test_pipeline_rejects_actual_observer_fault_not_product_failure(self):
        a,root,archive,directory,row=self.pipeline_fixture()
        output=util.read_json(directory/'evaluation.json'); output['evaluatorFaults']=['finite observer failure']
        util.write_json_atomic(directory/'evaluation.json',output)
        record=subject.evaluate.last_scoring(root); record['evaluation_sha256']=util.sha256_file(directory/'evaluation.json')
        util.append_line(root/'evaluations/index.jsonl',record)
        with patch.object(subject.aggregate,'row_for',return_value=row), self.assertRaises(ValueError):
            subject._pipeline(root,archive,a)

    def test_monitor_database_payload_tamper_rejected_even_verified_receipt(self):
        a,root,archive,_,row=self.pipeline_fixture()
        with closing(sqlite3.connect(root/'telemetry/monitor.db')) as db:
            db.execute('UPDATE raw_records SET payload_json=?', ('{}',))
            db.commit()
        with patch.object(subject.aggregate,'row_for',return_value=row), self.assertRaises(ValueError):
            subject._pipeline(root,archive,a)

    def test_monitor_normalized_wrong_tokens_rejected(self):
        a,root,archive,_,row=self.pipeline_fixture()
        util.write_json_atomic(root/'telemetry/normalized-readback.json',[dict(experiment_id=root.name,turn_count=1,input_tokens=1,output_tokens=58)])
        with patch.object(subject.aggregate,'row_for',return_value=row), self.assertRaises(ValueError):
            subject._pipeline(root,archive,a)

    def test_browser_cleanup_unknown_rejected(self):
        a,root,archive,directory,row=self.pipeline_fixture()
        util.write_json_atomic(directory/'browser-cleanup.json',dict(confirmed=False))
        with patch.object(subject.aggregate,'row_for',return_value=row), self.assertRaises(ValueError):
            subject._pipeline(root,archive,a)

    def test_browser_receipt_identity_tamper_rejected_even_hash_refrozen(self):
        a,root,archive,directory,row=self.pipeline_fixture()
        receipt=util.read_json(directory/'browser-cart/receipt.json'); receipt['runInstanceId']='9'*32
        util.write_json_atomic(directory/'browser-cart/receipt.json',receipt)
        output=util.read_json(directory/'evaluation.json'); output['browserCartEvidenceSha256']=util.sha256_file(directory/'browser-cart/receipt.json')
        util.write_json_atomic(directory/'evaluation.json',output)
        record=subject.evaluate.last_scoring(root); record['evaluation_sha256']=util.sha256_file(directory/'evaluation.json')
        util.append_line(root/'evaluations/index.jsonl',record)
        with patch.object(subject.aggregate,'row_for',return_value=row), self.assertRaises(ValueError):
            subject._pipeline(root,archive,a)

    def test_archive_payload_tamper_rejected(self):
        a,root,archive,_,row=self.pipeline_fixture()
        (archive/'packages/finite-package/payload/evaluations/finite-evaluation/evaluation.json').write_text('{}')
        with patch.object(subject.aggregate,'row_for',return_value=row), self.assertRaises(ValueError):
            subject._pipeline(root,archive,a)

    def test_one_shot_ordinary_postprocess_derivative_receipt_validates_original_unchanged(self):
        ref=self.prepare()
        before=subject.byte_inventory(self.source)
        row=dict(scoring={'state':'evaluation_incomplete'},operation_status='evaluation_incomplete',quality=None,
                 confirmed_product_failure={'verdict':'fail_critical'})
        with patch.object(subject.catalog_environment,'activated'), \
                patch.object(subject.machine,'postprocess',side_effect=lambda *args:self.pipeline_fixture(ref)) as process, \
                patch.object(subject.aggregate,'row_for',return_value=row):
            resultref=subject.execute(repo=self.f.repo,assessment_ref=ref,original_plan_ref=self.planref)
            validated=subject._validate_one(self.f.repo,resultref,self.planref)
        self.assertEqual(process.call_count,1)
        self.assertTrue(validated['operational_complete'])
        self.assertIsNone(validated['pipeline']['row']['quality'])
        self.assertEqual(subject.byte_inventory(self.source),before)
        self.assertEqual(validated['model_dispatch_count'],0)
