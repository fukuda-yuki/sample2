"""Finite private-controller and gateway fixtures; never a model or saved Run."""
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

import support
from harness import gateway, live_usage, ownership, staged_input as staged, util


class StageFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)/'run'
        for name in ('inputs', 'workspace', 'state', 'usage/raw', 'evidence'):
            (self.root/name).mkdir(parents=True)
        self.initial = 'Synthetic initial requirement.\n'
        self.additional = 'Synthetic later requirement.\n'
        self.policy = {'suffixes':['.cs'], 'excluded_directories':['obj','logs']}
        _,_,partition=staged.split_sections([{'id':'a','text':self.initial},{'id':'b','text':self.additional}],['a'],['b'])
        (self.root/'inputs/prompt.txt').write_text(self.initial)
        self.options = dict(run_id='R', run_instance_id='instance', task='toy', condition='staged-toy',
            workspace=self.root/'workspace', worker_roots=[self.root/p for p in ('inputs', 'state')],
            initial_prompt=self.initial, additional_prompt=self.additional, budget_seconds=30,
            boundary_contract={'kind':'synthetic-pre-request-fence','snapshot_policy_sha256':staged.digest(self.policy)}, partition=partition)
        self.controller = staged.create(Path(self.tmp.name)/'controller', **self.options)
        util.write_new_json(self.root/'context.json', {'method':'explore','blocks':[]})
        util.write_new_json(self.root/'manifest.json', {'schema_version':2, 'run_id':'R',
            'run_instance_id':'instance', 'task_id':'toy', 'condition_id':'staged-toy', 'started_at':None,
            'stop_confirmed':True, 'context_sha256':util.sha256_file(self.root/'context.json')})
        util.write_new_json(self.root/'evidence/isolation.json', {'verified':True})
        util.append_line(self.root/'evidence/agent.jsonl', {'type':'step_finish','sessionID':'native'})
        self.controller.bind_run(self.root)

    def reach_boundary(self, *, status='completed', fence=None):
        self.controller.start(); self.controller.bind_session('native')
        before = staged.snapshot(self.root/'workspace', self.policy)
        (self.root/'workspace/Program.cs').write_text('// synthetic change')
        after = staged.snapshot(self.root/'workspace', self.policy)
        tool = {'sessionID':'native','messageID':'message','callID':'call','state':{'status':status}}
        fence = fence or {'native_session_id':'native','run_instance_id':'instance','barrier_id':'barrier',
            'next_request_blocked':True,'active_tools':[],'children_exited':True}
        return self.controller.boundary(tool, before, after, fence)

    def ack(self, payload, remaining):
        self.assertGreater(remaining,0); self.assertLessEqual(remaining,30)
        return {**{k:payload[k] for k in ('workspace','native_session_id','run_instance_id','delivery_id')},
                'native_message_id':'additional-native-message'}


class ControllerTests(StageFixture):
    def test_exact_partition_preserves_bytes_and_rejects_loss_duplication_or_reordering(self):
        sections=[{'id':'a','text':'a\r\n'},{'id':'b','text':'β\n'},{'id':'c','text':'c'}]
        initial, additional, proof=staged.split_sections(sections,['a','c'],['b'])
        self.assertEqual(('a\r\nc','β\n'),(initial,additional))
        self.assertEqual(staged.digest(sections),proof['sections_sha256'])
        for a,b in [(['a'],['b']),(['a','b'],['b','c']),(['c','a'],['b']),([],['a','b','c'])]:
            with self.assertRaises(ValueError): staged.split_sections(sections,a,b)

    def test_future_text_outside_mounts_and_json_escaped_leak_rejected(self):
        with self.assertRaises(ValueError): staged.create(self.root/'inputs/future',**self.options)
        util.write_new_json(self.root/'inputs/profile.json',{'migration_request':self.initial+self.additional})
        with self.assertRaisesRegex(ValueError,'serialized'): self.controller.audit_mounts()
        self.assertEqual(self.additional,(self.controller.root/'additional.txt').read_text())

    def test_one_dispatch_ack_is_not_provider_delivery_and_recovery_never_resends(self):
        self.assertTrue(self.reach_boundary())
        state=self.controller.dispatch(self.ack)
        self.assertEqual('acknowledged',state['delivery_state'])
        self.assertNotIn('delivered',state)
        recovered=staged.Controller(self.controller.root)
        with self.assertRaisesRegex(ValueError,'No replay'): recovered.dispatch(self.ack)
        self.assertFalse(recovered.status()['retry_allowed'])

    def test_ack_loss_and_crash_after_intent_remain_unknown(self):
        self.reach_boundary()
        def lost(*_): raise TimeoutError('synthetic lost ACK')
        self.assertEqual('unknown',self.controller.dispatch(lost)['delivery_state'])
        with self.assertRaises(ValueError): staged.Controller(self.controller.root).dispatch(self.ack)

    def test_foreign_native_ack_cannot_claim_acknowledgement(self):
        self.reach_boundary()
        self.assertEqual('unknown',self.controller.dispatch(lambda p,t:dict(self.ack(p,t),native_session_id='foreign'))['delivery_state'])

    def test_failed_tool_with_real_implementation_change_can_reach_boundary(self):
        self.assertTrue(self.reach_boundary(status='error'))

    def test_no_safe_quiescent_fence_means_no_additional_send(self):
        fence={'native_session_id':'native','run_instance_id':'instance','barrier_id':'b',
               'next_request_blocked':False,'active_tools':['other'],'children_exited':False}
        with self.assertRaises(ValueError): self.reach_boundary(fence=fence)
        with self.assertRaises(ValueError): self.controller.dispatch(self.ack)
        self.assertIn('boundary_unknown',[e['kind'] for e in self.controller.events()])

    def test_original_source_and_database_remain_worker_readable(self):
        source=self.root/'inputs/legacy-source';source.mkdir();(source/'Old.cs').write_text('// synthetic original')
        database=self.root/'inputs/original.sqlite';database.write_bytes(b'synthetic original database bytes')
        before=util.tree_hashes(self.root/'inputs')
        self.controller.audit_mounts()
        self.assertEqual(before,util.tree_hashes(self.root/'inputs'))
        self.assertTrue((source/'Old.cs').is_file());self.assertTrue(database.is_file())

    def test_boundary_hashes_do_not_count_build_output_or_logs(self):
        before=staged.snapshot(self.root/'workspace',self.policy)
        (self.root/'workspace/obj').mkdir(); (self.root/'workspace/obj/generated.cs').write_text('synthetic')
        (self.root/'workspace/build.log').write_text('build success')
        self.assertEqual(before,staged.snapshot(self.root/'workspace',self.policy))

    def test_original_deadline_survives_controller_reconstruction_and_prevents_late_send(self):
        self.reach_boundary(); deadline=self.controller.status()['deadline_unix']
        recovered=staged.Controller(self.controller.root,clock=lambda:deadline+1)
        self.assertEqual(0,recovered.remaining())
        with self.assertRaises(ValueError): recovered.dispatch(self.ack)
        with self.assertRaises(ValueError): recovered.start()
        result=recovered.finish('timeout_before_additional_input',stop_confirmed=True)
        self.assertEqual('not_sent',result['delivery_state'])
        self.assertTrue(result['terminal']['stop_confirmed'])

    def test_monotonic_budget_cannot_be_extended_by_a_slow_wall_clock(self):
        self.reach_boundary();events=self.controller.events();started=next(e for e in events if e['kind']=='started')
        recovered=staged.Controller(self.controller.root,clock=lambda:events[-1]['at_unix']+1,
                                   monotonic=lambda:started['deadline_monotonic']+1)
        self.assertEqual(0,recovered.remaining())
        with self.assertRaises(ValueError): recovered.dispatch(self.ack)

    def test_stop_during_send_can_be_recorded_without_waiting_for_send_lock(self):
        self.reach_boundary()
        def sending(payload,remaining):
            self.controller.stop('operator_stop')
            return self.ack(payload,remaining)
        result=self.controller.dispatch(sending)
        self.assertTrue(result['stop_requested'])
        with self.assertRaises(ValueError): self.controller.dispatch(self.ack)

    def test_early_completion_before_boundary_is_not_discarded(self):
        self.controller.start(); self.controller.bind_session('native')
        state=self.controller.finish('agent_completed_before_boundary',stop_confirmed=True)
        self.assertFalse(state['boundary_reached']); self.assertEqual('not_sent',state['delivery_state'])
        with self.assertRaises(ValueError): self.controller.dispatch(self.ack)

    def test_writer_lock_and_damaged_journal_hold_instead_of_replaying(self):
        with ownership.lease(self.controller.root):
            with self.assertRaises(BlockingIOError): self.controller.start()
        with (self.controller.root/'events.jsonl').open('ab') as stream: stream.write(b'{"interrupted":')
        with self.assertRaisesRegex(ValueError,'Interrupted'): self.controller.status()


class GatewayStageTests(StageFixture):
    def setUp(self):
        super().setUp(); self.received=[]
        received=self.received
        class FakeProvider(BaseHTTPRequestHandler):
            def log_message(self,*_): pass
            def do_POST(self):
                received.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
                self.wfile.write(b'data: {"model":"toy-model","usage":{"prompt_tokens":10,"completion_tokens":2}}\n\ndata: [DONE]\n\n')
        self.provider=ThreadingHTTPServer(('127.0.0.1',0),FakeProvider)
        self.proxy=gateway.Gateway(('127.0.0.1',0),self.root/'usage/raw','R','toy-model','synthetic-secret',
            upstream_host='127.0.0.1',upstream_port=self.provider.server_port,tls=False,session_id='instance',
            expected_prompt=self.root/'inputs/prompt.txt',staged_input=self.controller.root)
        for server in (self.provider,self.proxy):
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            self.addCleanup(server.server_close);self.addCleanup(server.shutdown)

    def post(self,body,path='/v1/chat/completions'):
        client=http.client.HTTPConnection('127.0.0.1',self.proxy.server_port,timeout=5)
        try:
            client.request('POST',path,json.dumps(body));response=client.getresponse();data=response.read()
            return response.status,data
        finally: client.close()

    def request(self,extra=None,role='user'):
        messages=[{'role':'user','content':self.initial}]
        if extra is not None: messages.append({'role':role,'content':extra})
        return self.post({'model':'toy-model','stream':True,'messages':messages})

    def arm(self,payload,remaining):
        body={k:payload[k] for k in ('run_id','run_instance_id','delivery_id','contract_sha256','additional_sha256','native_session_id','barrier_id')}
        self.assertEqual(200,self.post(body,'/control/staged-input')[0])
        self.assertEqual(200,self.post(body,'/control/staged-input')[0]) # same writer is idempotent
        return self.ack(payload,remaining)

    def test_real_gateway_records_stage_input_and_usage_reconciles_all_requests_once(self):
        self.assertEqual(200,self.request()[0]);self.reach_boundary();self.controller.dispatch(self.arm)
        self.assertEqual(200,self.request(self.additional)[0]);self.assertEqual(200,self.request(self.additional)[0])
        self.controller.finish('completed',stop_confirmed=True)
        self.proxy.shutdown();self.proxy.server_close()
        normalized=live_usage.collect(self.root)
        self.assertEqual(36,normalized['observed_tokens']);self.assertEqual(3,normalized['observed_call_count'])
        self.assertTrue(normalized['input_reached'],normalized['inventory_issues'])
        proof=normalized['staged_input'];self.assertTrue(proof['native_acknowledged'])
        self.assertEqual(proof['first_observed_request']['request_id'],proof['first_transmitted_request']['request_id'])
        self.assertEqual(3,len(self.received))
        self.assertNotIn(self.additional,json.dumps(proof))

    def test_native_ack_alone_does_not_claim_delivery_and_usage_before_boundary_is_retained(self):
        self.request();self.reach_boundary();self.controller.dispatch(self.arm)
        self.controller.finish('stopped_before_additional_request',stop_confirmed=True)
        self.proxy.shutdown();self.proxy.server_close()
        normalized=live_usage.collect(self.root)
        self.assertEqual(12,normalized['observed_tokens']);self.assertFalse(normalized['input_reached'])
        self.assertTrue(normalized['staged_input']['native_acknowledged'])
        self.assertIsNone(normalized['staged_input']['first_transmitted_request'])

    def test_lost_native_ack_keeps_unknown_send_but_independent_gateway_delivery_is_observed(self):
        self.request();self.reach_boundary()
        def lost(payload,remaining):
            self.arm(payload,remaining);self.assertEqual(200,self.request(self.additional)[0]);raise TimeoutError()
        self.assertEqual('unknown',self.controller.dispatch(lost)['delivery_state'])
        self.controller.finish('native_ack_lost',stop_confirmed=True)
        self.proxy.shutdown();self.proxy.server_close()
        normalized=live_usage.collect(self.root)
        self.assertTrue(normalized['input_reached'],normalized['inventory_issues'])
        self.assertFalse(normalized['staged_input']['native_acknowledged'])
        self.assertEqual(24,normalized['observed_tokens'])
        with self.assertRaises(ValueError): self.controller.dispatch(self.ack)

    def test_gateway_proof_tampering_is_detected_by_original_request_bytes(self):
        self.request();self.reach_boundary();self.controller.dispatch(self.arm);self.request(self.additional)
        self.controller.finish('completed',stop_confirmed=True)
        self.proxy.shutdown();self.proxy.server_close()
        path=self.root/'usage/raw/staged-input.jsonl';rows=util.read_lines(path)
        rows[-1]['receipt']['locations'][0]['message']=99
        path.write_text(''.join(json.dumps(r)+'\n' for r in rows))
        normalized=live_usage.collect(self.root)
        self.assertFalse(normalized['input_reached']);self.assertIn('stage_request_proof_mismatch',normalized['inventory_issues'])
        self.assertEqual(24,normalized['observed_tokens'])

    def test_future_input_before_controller_intent_is_blocked_before_upstream(self):
        self.assertEqual(502,self.request(self.additional)[0]);self.assertEqual([],self.received)
        self.proxy.shutdown();self.proxy.server_close()
        self.assertEqual('known_no_send',util.read_lines(self.root/'usage/raw/events.jsonl')[0]['send_evidence'])

    def test_wrong_role_duplicate_and_missing_input_after_arm_are_not_forwarded(self):
        self.request();self.reach_boundary();self.controller.dispatch(self.arm)
        self.assertEqual(502,self.request(self.additional*2)[0]);self.assertEqual(1,len(self.received))

    def test_assistant_echo_is_not_additional_user_input(self):
        self.request();self.reach_boundary();self.controller.dispatch(self.arm)
        self.assertEqual(502,self.request(self.additional,role='assistant')[0]);self.assertEqual(1,len(self.received))

    def test_foreign_controller_arm_and_nonloopback_cannot_enable_input(self):
        self.reach_boundary()
        def denied(payload,remaining):
            body={k:payload[k] for k in ('run_id','run_instance_id','delivery_id','contract_sha256','additional_sha256','native_session_id','barrier_id')}
            self.assertEqual(403,self.post(dict(body,run_instance_id='foreign'),'/control/staged-input')[0])
            handler=object.__new__(gateway.Handler);handler.server=self.proxy;handler.path='/control/staged-input'
            handler.client_address=('192.0.2.1',1);handler.connection=type('Connection',(),{'settimeout':lambda *_:None})()
            handler.headers={'Content-Length':'1'};handler.send_error=lambda status,*_:self.assertEqual(403,status)
            handler.do_POST();self.assertIsNone(self.proxy.stage_arm)
            raise TimeoutError()
        self.controller.dispatch(denied)

    def test_boundary_missed_does_not_send_the_old_request_or_retry_it(self):
        self.request();self.reach_boundary();self.controller.dispatch(self.arm)
        self.assertEqual(502,self.request()[0]);self.assertEqual(1,len(self.received))
        self.assertEqual(403,self.request(self.additional)[0])

    def test_stop_fence_wins_over_new_stage_arm(self):
        self.proxy.close_admission();self.reach_boundary()
        def rejected(payload,remaining):
            body={k:payload[k] for k in ('run_id','run_instance_id','delivery_id','contract_sha256','additional_sha256','native_session_id','barrier_id')}
            self.assertEqual(403,self.post(body,'/control/staged-input')[0]);raise TimeoutError()
        self.assertEqual('unknown',self.controller.dispatch(rejected)['delivery_state'])
        self.assertEqual([],self.received)


if __name__ == '__main__': unittest.main()
