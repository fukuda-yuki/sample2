"""Synthetic provider faults through the ordinary attempt/usage/retry path."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from outer.harness import util
from research import acquisition_pipeline as pipeline, live_pilot, pair_execution, technical_retry as retry


class TechnicalRetryTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.batch=Path(temporary.name);self.root=self.batch/'run'
        self.case=dict(run_id='run',run_instance_id='instance',pair=1,slot=1)
        util.write_new_json(self.batch/'phase.json',dict(assignments=[dict(cases=[self.case])]))
        util.write_new_json(self.batch/'pipeline-attempt.json',dict(phase=live_pilot.reference(self.batch/'phase.json')))
        self.manifest=dict(self.case,stop_confirmed=True,network_cleanup={'confirmed':True},
            end_reason='provider_failure',started_at='2026-10-11T00:00:00+00:00',
            ended_at='2026-10-11T00:00:02+00:00',duration_seconds=2)
        util.write_new_json(self.root/'manifest.json',self.manifest)
        journal=self.batch/'_control/pair-journal.jsonl'
        pair_execution.append(journal,dict(kind='pair_reserved',assignments=[self.case]))
        pair_execution.append(journal,dict(kind='dispatch',**self.case))
        self.event=dict(run_id='run',session_id='instance',request_id='request',status='transport_error',
            http_status=503,error_type='ValueError',usage=None,policy_error='response_model_mismatch')
        util.append_line(self.root/'usage/raw/started.jsonl',dict(self.event))
        util.append_line(self.root/'usage/raw/events.jsonl',self.event)
        util.append_line(self.root/'usage/raw/failure.jsonl',dict(request_id='request'))

    def save(self):
        usage=pipeline.usage_for(self.batch)
        saved=dict(acquired=False,usage=usage,technical_retry_evidence=retry.seal(self.batch,usage))
        util.write_new_json(self.batch/'pipeline-acquisition.json',saved)
        return saved

    def test_sealed_retry_preserves_unknown_usage_and_revalidates_unchanged_evidence(self):
        saved=self.save();self.assertTrue(retry.eligible(self.batch,saved))
        self.assertEqual(saved['usage']['observed_tokens'],0)
        self.assertEqual(saved['usage']['requests'],1)
        self.assertEqual(saved['usage']['dispatched_runs'],1)
        self.assertIsNone(saved['usage']['unknown_usage_requests'][0]['observed_tokens'])
        config=dict(template={'staged_retry':dict(retry_budget='shared_reserved_attempts',technical_failure_policy=retry.POLICY)},attempted_slots=[],pair_count=1)
        attempts=[dict(slot=1,record=str(self.batch/'pipeline-attempt.json'))]
        with patch.object(pipeline,'confirm_owned_stopped') as stopped:
            self.assertEqual(([1],set()),pipeline.pending_acquisition_slots(config,attempts,set()))
            stopped.assert_called_once_with(self.batch)
        with patch.object(pipeline,'confirm_owned_stopped'):
            self.assertEqual(([1],set()),pipeline.pending_acquisition_slots(config,attempts*6,set()))
        util.append_line(self.root/'usage/raw/events.jsonl',dict(self.event,request_id='new'))
        self.assertFalse(retry.eligible(self.batch,saved))

    def test_quality_build_early_completion_boundary_and_budget_never_retry(self):
        for reason in ('completed','agent_error','boundary_unknown','timeout','stop_unconfirmed'):
            with self.subTest(reason=reason):
                util.write_json_atomic(self.root/'manifest.json',dict(self.manifest,end_reason=reason))
                self.assertIsNone(retry.classify(self.batch))

    def test_auth_model_identity_and_unknown_cause_are_not_infrastructure(self):
        path=self.root/'usage/raw/events.jsonl'
        for changes in ({'http_status':401},{'http_status':400},{'session_id':'foreign'},
                        {'policy_error':'credential_echo_redacted'},
                        {'response_model_id':'wrong-model'},
                        {'http_status':None,'error_type':'ValueError'}):
            with self.subTest(changes=changes):
                path.unlink();util.append_line(path,dict(self.event,**changes))
                self.assertIsNone(retry.classify(self.batch))

    def test_network_timeout_and_rate_limit_are_confirmed_but_cleanup_must_be_complete(self):
        path=self.root/'usage/raw/events.jsonl'
        for changes in ({'http_status':429},{'http_status':None,'error_type':'TimeoutError'}):
            path.unlink();util.append_line(path,dict(self.event,**changes))
            self.assertIsNotNone(retry.classify(self.batch))
        util.write_json_atomic(self.root/'manifest.json',dict(self.manifest,network_cleanup={'confirmed':False}))
        self.assertIsNone(retry.classify(self.batch))

    def test_saved_acquisition_never_retries_even_with_old_technical_evidence(self):
        saved=self.save();saved['acquired']=True
        util.write_json_atomic(self.batch/'pipeline-acquisition.json',saved)
        config=dict(campaign_plan={},template={'staged_retry':dict(retry_budget='shared_reserved_attempts',technical_failure_policy=retry.POLICY)},attempted_slots=[],pair_count=1)
        self.assertEqual(([],{1}),pipeline.pending_acquisition_slots(config,
            [dict(slot=1,record=str(self.batch/'pipeline-attempt.json'))],set()))

    def test_typed_docker_allocation_failure_needs_no_provider_usage_and_confirmed_stop(self):
        import shutil
        shutil.rmtree(self.root/'usage')
        util.write_json_atomic(self.root/'manifest.json',dict(self.manifest,end_reason='environment_failure'))
        util.write_new_json(self.root/'evidence/infrastructure-failure.json',dict(
            kind='owned_docker_allocation_failure_v1',run_id='run',run_instance_id='instance',phase='allocation',operation='create'))
        self.assertEqual(retry.classify(self.batch)['causes'][0]['kind'],'docker_allocation')
        util.append_line(self.root/'usage/raw/started.jsonl',dict(request_id='unexpected'))
        self.assertIsNone(retry.classify(self.batch))

    def test_worker_exit_is_retryable_only_with_owned_docker_oom_proof(self):
        util.write_json_atomic(self.root/'manifest.json',dict(self.manifest,end_reason='agent_error'))
        self.assertIsNone(retry.classify(self.batch))
        path=self.root/'evidence/infrastructure-failure.json'
        evidence=dict(kind='owned_worker_oom_v1',run_id='run',run_instance_id='instance',oom_killed=True)
        util.write_new_json(path,evidence)
        self.assertEqual(retry.classify(self.batch)['causes'][0]['kind'],'owned_worker_oom')
        util.write_json_atomic(path,dict(evidence,oom_killed=False))
        self.assertIsNone(retry.classify(self.batch))
