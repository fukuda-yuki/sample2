"""Boundary adapter fixtures: no Docker process, credentials or model calls."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch

import support
from harness import gateway, profiles, runtime, staged_input as staged, staged_runtime, util
from test_staged_input import StageFixture

REPO=Path(__file__).resolve().parents[2]

class BoundaryTests(StageFixture):
    def setup_boundary(self, ids=('call',), children=()):
        self.controller.contract['boundary_contract']['snapshot_policy']=self.policy
        self.controller.start();self.controller.bind_session('native')
        self.before=staged.snapshot(self.root/'workspace',self.policy)
        self.barrier={'barrier_id':'b','request_id':'request','request_sha256':'hash',
            'run_id':'R','run_instance_id':'instance','tool_call_ids':list(ids)}
        self.events=[{'type':'tool_use','sessionID':'native','part':{'sessionID':'native',
            'messageID':'message','callID':i,'state':{'status':'completed'}}} for i in ids]
        self.transport=Mock(children=Mock(return_value=list(children)),send=Mock(side_effect=self.ack))

    def observe(self):
        return staged_runtime.observe_boundary(self.controller,self.transport,self.barrier,self.events,self.before)

    def test_failed_tool_change_delivers_once_then_releases_with_native_ack(self):
        self.setup_boundary();self.events[0]['part']['state']['status']='error'
        (self.root/'workspace/Program.cs').write_text('synthetic change')
        after,delivered=self.observe()
        self.assertTrue(delivered);self.assertNotEqual(after,self.before)
        self.transport.send.assert_called_once()
        self.transport.release.assert_called_once_with('b','additional-native-message')
        with self.assertRaises(ValueError):self.observe()
        self.transport.send.assert_called_once()

    def test_readonly_tool_records_snapshot_and_releases_without_delivering(self):
        self.setup_boundary();after,delivered=self.observe()
        self.assertFalse(delivered);self.assertEqual(self.before,after)
        self.transport.send.assert_not_called();self.transport.release.assert_called_once_with('b')
        self.assertEqual('unchanged_boundary',self.controller.events()[-1]['kind'])

    def test_parallel_mutation_holds_first_boundary_without_later_substitution(self):
        self.setup_boundary(('a','b'));(self.root/'workspace/Program.cs').write_text('synthetic change')
        with self.assertRaisesRegex(ValueError,'ambiguous'):self.observe()
        self.transport.send.assert_not_called();self.transport.release.assert_not_called()
        self.assertEqual('boundary_unknown',self.controller.events()[-1]['kind'])
        self.assertIsNone(self.controller.status()['terminal'])
        self.controller.finish('boundary_unknown',stop_confirmed=True)

    def test_unfinished_tools_or_live_children_do_not_establish_quiescence(self):
        self.setup_boundary(('a','b'));self.events.pop()
        (self.root/'workspace/Program.cs').write_text('synthetic change')
        self.assertEqual((self.before,False),self.observe())
        self.transport.release.assert_not_called();self.transport.send.assert_not_called()
        self.events[0]['part']['callID']='call';self.barrier['tool_call_ids']=['call']
        self.transport.children.return_value=[123]
        self.assertEqual((self.before,False),self.observe())
        self.transport.send.assert_not_called()

    def test_lost_ack_never_releases_model_loop(self):
        self.setup_boundary();(self.root/'workspace/Program.cs').write_text('synthetic change')
        self.transport.send.side_effect=TimeoutError()
        with self.assertRaises(RuntimeError):self.observe()
        self.transport.release.assert_not_called()
        self.assertEqual('unknown',self.controller.status()['delivery_state'])

    def test_foreign_session_never_dispatches(self):
        self.setup_boundary();self.events[0]['sessionID']='foreign'
        with self.assertRaises(ValueError):self.observe()
        self.transport.send.assert_not_called()

    def test_docker_api_requires_owned_mount_and_sends_future_body_only_on_stdin(self):
        self.setup_boundary(); owner=Mock()
        owner._owned_container.return_value={'State':{'Running':True},
            'Mounts':[{'Destination':'/workspace','Source':str(self.root/'workspace')}]}
        state={'worker':'owned-worker','gateway':'owned-gateway','run_id':'R','run_instance_id':'instance'}
        transport=staged_runtime.DockerTransport(self.root,state,self.controller,owner,'toy-model')
        with patch.object(staged_runtime.subprocess,'run',return_value=Mock(returncode=0,stdout='{}')) as child:
            transport.api('worker','/session/native/message',{'noReply':True,'parts':[{'text':self.additional}]})
            args,kwargs=child.call_args
            self.assertNotIn(self.additional,str(args));self.assertNotIn(self.additional,str(kwargs['env']))
            self.assertEqual(self.additional,json.loads(kwargs['input'])['body']['parts'][0]['text'])
            self.assertLessEqual(kwargs['timeout'],10.5)
            owner._owned_container.return_value['Mounts'][0]['Source']=str(self.root/'foreign')
            with self.assertRaises(ValueError):transport.api('worker','/session')
            self.assertEqual(1,child.call_count)

class StreamFenceTests(unittest.TestCase):
    def test_every_chunk_split_preserves_bytes_and_withholds_terminal_marker(self):
        raw=b'data: {"choices":[]}\r\n\r\ndata: [DONE]\r\n\r\n'
        prefix=raw[:raw.index(b'data: [DONE]')]
        for at in range(len(raw)+1):
            fence=gateway.ResponseEndFence()
            visible=fence.feed(raw[:at])+fence.feed(raw[at:])+fence.feed(b'',final=True)
            self.assertTrue(fence.ended);self.assertEqual(prefix,visible);self.assertEqual(raw,visible+fence.tail)
        fence=gateway.ResponseEndFence()
        visible=b''.join(fence.feed(bytes([c])) for c in raw)+fence.feed(b'',final=True)
        self.assertEqual(prefix,visible);self.assertEqual(raw,visible+fence.tail)

class ProducerTests(unittest.TestCase):
    def test_create_keeps_exact_full_request_private_and_only_initial_prompt_in_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);repo=root/'repo'
            shutil.copytree(REPO/'outer/profiles',repo/'outer/profiles')
            shutil.copytree(REPO/'inner/spec',repo/'inner/spec')
            task=profiles.read(repo,'tasks','MS1-001');task['migration_request']='Synthetic part one.\nSynthetic part two.\n'
            util.write_json_atomic(repo/'outer/profiles/tasks/MS1-001.json',task)
            profile=profiles.read(repo,'runtimes','deepseek');profile['prompt_transport']='stdin'
            util.write_json_atomic(repo/'outer/profiles/runtimes/deepseek.json',profile)
            source=repo/'artifacts/sources'/task['start_state']['source_commit'];source.mkdir(parents=True)
            (source/'Original.cs').write_text('// original source');(source/'original.sqlite').write_bytes(b'original database')
            util.write_new_json(source.parent/(source.name+'.json'),{'files':util.tree_hashes(source)})
            prepared=repo/'artifacts/runtime/MS1-001';bundle=prepared/'evaluator';bundle.mkdir(parents=True)
            (bundle/'MusicStore.Evaluator.dll').write_bytes(b'nonexecutable synthetic fixture')
            util.write_new_json(prepared/'lock.json',{'opencode_version':'1.17.11','versions':{},'images':{},
                'controller_files':runtime.controller_files(REPO),'evaluator_files':util.tree_hashes(bundle),
                'evaluator_sha256':util.sha256_file(bundle/'MusicStore.Evaluator.dll'),'evaluator_build':{'clean_worktree':True}})
            policy={'suffixes':['.cs'],'excluded_directories':['obj']}
            partition={'kind':'staged_request_partition_v1','request_sha256':util.sha256_bytes(task['migration_request'].encode()),
                'sections':[{'id':'a','text':'Synthetic part one.\n'},{'id':'b','text':'Synthetic part two.\n'}],
                'initial_ids':['a'],'additional_ids':['b'],'boundary_contract':{
                    'transport':'opencode-server-response-barrier-v1','snapshot_policy':policy,'snapshot_policy_sha256':staged.digest(policy)}}
            with self.assertRaises(ValueError):profiles.create(repo,root/'runs','MS1-001','staged-explore',1)
            manifest=profiles.create(repo,root/'runs','MS1-001','staged-explore',1,staged_plan=partition)
            runroot=root/'runs'/manifest['run_id'];condition=profiles.validate_run(runroot)
            self.assertEqual(task['migration_request'],condition['migration_request'])
            controller=staged.Controller(Path(manifest['staged_input']['contract_path']).parent);controller.audit_mounts()
            prompt=(runroot/'inputs/prompt.txt').read_text()
            self.assertIn('Synthetic part one.',prompt);self.assertNotIn('Synthetic part two.',prompt)
            self.assertEqual([],util.read_json(runroot/'context.json')['blocks'])
            self.assertEqual(util.tree_hashes(source),util.tree_hashes(runroot/'inputs/legacy-source'))
            self.assertEqual('Synthetic part two.\n',(controller.root/'additional.txt').read_text())
            # Runtime owns the existing Run. Only the gateway sees /stage;
            # the native server is loopback-only with the original pinned model.
            process=Mock();process.poll.return_value=0;process.returncode=0
            fake_docker=Mock(return_value=Mock(stdout='network-id',returncode=0))
            def execute(*args):
                args[2].bind_session('native');return 0,'completed'
            with patch.object(runtime,'docker',fake_docker),patch.object(runtime,'image_id'),\
                    patch.object(runtime,'isolation_probe'),patch.object(runtime,'_gateway_credential',return_value='synthetic'),\
                    patch.object(runtime.subprocess,'Popen',return_value=process),patch.object(runtime,'stop_owned',return_value=True),\
                    patch.object(runtime,'record_cleanup',return_value={}),patch('harness.live_usage.update_manifest_evidence'),\
                    patch('harness.live_usage.collect'),patch.object(staged_runtime,'execute',side_effect=execute):
                # Empty image map is adequate for producer tests; add synthetic
                # names only for the mocked Docker command-construction fixture.
                condition['runtime_lock']['images']={'worker':'synthetic-worker','gateway':'synthetic-gateway'}
                with patch.object(profiles,'validate_run',return_value=condition):runtime.start(REPO,root/'runs',manifest['run_id'])
            calls=[list(c.args) for c in fake_docker.call_args_list if c.args[0]=='create']
            worker=next(c for c in calls if 'synthetic-worker' in c);proxy=next(c for c in calls if 'synthetic-gateway' in c)
            self.assertIn('serve',worker);self.assertIn('127.0.0.1',worker)
            self.assertFalse(any('target=/stage' in str(c) for c in worker))
            self.assertTrue(any('target=/stage' in str(c) for c in proxy));self.assertIn('--staged-input',proxy)
            self.assertIsNotNone(controller.status()['terminal'])
            self.assertEqual(1,len([e for e in controller.events() if e['kind']=='started']))

class GatewayBarrierTests(StageFixture):
    def setUp(self):
        super().setUp()
        self.proxy=gateway.Gateway(('127.0.0.1',0),self.root/'usage/raw','R','toy-model','synthetic',
            session_id='instance',expected_prompt=self.root/'inputs/prompt.txt',staged_input=self.controller.root)
        self.addCleanup(self.proxy.server_close)
        self.proxy.stage['boundary_contract']['transport']='opencode-server-response-barrier-v1'
        self.raw=b'data: {"choices":[{"delta":{"tool_calls":[{"id":"call"}]}}]}\n\ndata: [DONE]\n\n'
        self.event={'request_id':'request','request_sha256':'hash'}

    def hold(self):
        import threading,time
        self.faults=[]
        def target():
            try:self.proxy.hold_response_end(self.event,self.raw)
            except Exception as error:self.faults.append(error)
        thread=threading.Thread(target=target);thread.start()
        self.addCleanup(lambda:(self.proxy.stage_barrier_event.set(),thread.join(2)))
        for _ in range(100):
            barrier=self.proxy.inspect_stage_barrier()
            if barrier:return thread,barrier
            time.sleep(.01)
        self.fail('Fixture barrier failed to hold')

    def test_readonly_release_preserves_ids_and_duplicate_or_foreign_release_fails(self):
        thread,barrier=self.hold();self.assertTrue(thread.is_alive())
        with self.assertRaises(ValueError):self.proxy.release_stage_barrier('foreign')
        self.proxy.release_stage_barrier(barrier['barrier_id']);thread.join(2)
        self.assertFalse(thread.is_alive());self.assertEqual([],self.faults)
        with self.assertRaises(ValueError):self.proxy.release_stage_barrier(barrier['barrier_id'])
        rows=util.read_lines(self.root/'usage/raw/response-barriers.jsonl')
        self.assertEqual(['held','released'],[r['kind'] for r in rows])
        self.assertEqual(['call'],rows[0]['tool_call_ids'])

    def test_arm_requires_owned_live_barrier_and_ack_before_release(self):
        payload={k:self.proxy.stage[k] for k in ('run_id','run_instance_id','delivery_id','contract_sha256','additional_sha256')}
        payload.update(native_session_id='native',barrier_id='missing')
        with self.assertRaises(ValueError):self.proxy.arm_stage(payload)
        thread,barrier=self.hold();payload['barrier_id']=barrier['barrier_id']
        self.proxy.arm_stage(payload)
        with self.assertRaises(ValueError):self.proxy.release_stage_barrier(barrier['barrier_id'])
        self.proxy.release_stage_barrier(barrier['barrier_id'],'native-message');thread.join(2)
        self.assertEqual([],self.faults)

    def test_stop_wakes_boundary_waiter_and_disallows_native_release(self):
        thread,barrier=self.hold();self.proxy.close_admission();thread.join(2)
        self.assertFalse(thread.is_alive());self.assertIsInstance(self.faults[0],TimeoutError)
        with self.assertRaises(ValueError):self.proxy.release_stage_barrier(barrier['barrier_id'])
        self.assertEqual(['held'],[r['kind'] for r in util.read_lines(self.root/'usage/raw/response-barriers.jsonl')])
