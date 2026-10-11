"""Candidate transport experiment: real frozen binary, fake provider, real gateway.

By default the fake provider supplies the response barrier; --gateway-barrier
uses the actual gateway implementation. Neither establishes Docker isolation,
parallel-tool safety or approval
to change the acquisition runner. All prompts/state are temporary and synthetic.
"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from outer.harness import gateway, live_usage, profiles, runtime, staged_input, util


def probe(executable, *, gateway_barrier=False):
    executable = Path(executable).resolve(strict=True)
    repo = Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory(prefix='staged-server-fixture-') as directory:
        scratch = Path(directory); root = scratch/'run'
        for name in ('inputs','workspace','state','usage/raw','evidence'): (root/name).mkdir(parents=True)
        initial = 'Synthetic initial requirement: implement stage one.'
        additional = 'Synthetic additional requirement: implement stage two in the same file.'
        (root/'inputs/prompt.txt').write_text(initial)
        policy = {'suffixes':['.cs'], 'excluded_directories':['obj','bin']}
        _,_,partition = staged_input.split_sections([{'id':'a','text':initial},{'id':'b','text':additional}],['a'],['b'])
        boundary_contract={'kind':'synthetic-provider-response-barrier','snapshot_policy_sha256':staged_input.digest(policy)}
        if gateway_barrier: boundary_contract['transport']='opencode-server-response-barrier-v1'
        controller = staged_input.create(scratch/'controller', run_id='synthetic', run_instance_id='synthetic-instance',
            task='toy',condition='staged-toy',workspace=root/'workspace',worker_roots=[root/'inputs',root/'state'],
            initial_prompt=initial,additional_prompt=additional,budget_seconds=90,
            boundary_contract=boundary_contract,partition=partition)
        util.write_new_json(root/'context.json', {'method':'explore','blocks':[]})
        util.write_new_json(root/'manifest.json', {'schema_version':2,'run_id':'synthetic','run_instance_id':'synthetic-instance',
            'task_id':'toy','condition_id':'staged-toy','started_at':None,'stop_confirmed':False,
            'context_sha256':util.sha256_file(root/'context.json')})
        controller.bind_run(root)
        env = {'PATH':os.defpath,'HOME':str(scratch/'home'),'XDG_CONFIG_HOME':str(scratch/'config'),
            'XDG_DATA_HOME':str(root/'state'),'XDG_CACHE_HOME':str(scratch/'cache'),'TMPDIR':str(scratch),
            'OPENCODE_CONFIG':str(scratch/'opencode.json'),'OPENCODE_DISABLE_AUTOUPDATE':'true',
            'OPENCODE_DISABLE_MODELS_FETCH':'true','OPENCODE_DISABLE_DEFAULT_PLUGINS':'true'}
        version = subprocess.check_output([str(executable),'--version'],env=env,cwd=root/'workspace',text=True,timeout=30).strip()
        if version != '1.17.11': raise ValueError('Frozen binary required')
        release = threading.Event(); holding = threading.Event(); requests = []
        class FakeProvider(BaseHTTPRequestHandler):
            def log_message(self,*_): pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length']))); requests.append(body)
                number=len(requests)
                self.send_response(200); self.send_header('Content-Type','text/event-stream'); self.end_headers()
                if number <= 2:
                    delta={'role':'assistant','tool_calls':[{'index':0,'id':'synthetic-write-'+str(number),'type':'function',
                        'function':{'name':'write','arguments':json.dumps({'filePath':str(root/'workspace/Program.cs'),
                            'content':'// synthetic stage '+str(number)+'\n'})}}]}
                else: delta={'role':'assistant','content':'Synthetic completion.'}
                item={'id':'synthetic-'+str(number),'model':body['model'],'object':'chat.completion.chunk','created':1,
                      'choices':[{'index':0,'delta':delta,'finish_reason':None}]}
                self.wfile.write(('data: '+json.dumps(item)+'\n\n').encode())
                item['choices']=[{'index':0,'delta':{},'finish_reason':'tool_calls' if number<=2 else 'stop'}]
                item['usage']={'prompt_tokens':10,'completion_tokens':2,'total_tokens':12}
                self.wfile.write(('data: '+json.dumps(item)+'\n\n: synthetic stream padding for redaction buffer\n\n').encode()); self.wfile.flush()
                if number == 1 and not gateway_barrier:
                    holding.set()
                    if not release.wait(30): return
                self.wfile.write(b'data: [DONE]\n\n'); self.wfile.flush()
        upstream=ThreadingHTTPServer(('127.0.0.1',0),FakeProvider)
        condition=profiles.resolve(repo,'MS1-001','explore'); model=condition['runtime']['model_id']
        proxy=gateway.Gateway(('127.0.0.1',0),root/'usage/raw','synthetic',model,'synthetic-canary',
            session_id='synthetic-instance',upstream_host='127.0.0.1',upstream_port=upstream.server_port,tls=False,
            expected_prompt=root/'inputs/prompt.txt',staged_input=controller.root)
        for server in (upstream,proxy): threading.Thread(target=server.serve_forever,daemon=True).start()
        config=runtime.opencode_config(condition)
        config['provider']['sample2']['options']['baseURL']=f'http://127.0.0.1:{proxy.server_port}/v1'
        util.write_new_json(scratch/'opencode.json',config)
        with socket.socket() as reserve: reserve.bind(('127.0.0.1',0)); port=reserve.getsockname()[1]
        address=f'http://127.0.0.1:{port}'
        def api(path,body=None):
            request=urllib.request.Request(address+path,data=json.dumps(body).encode() if body is not None else None,
                headers={'Content-Type':'application/json','x-opencode-directory':str(root/'workspace')})
            with urllib.request.urlopen(request,timeout=max(.1,min(10,controller.remaining()))) as response:
                return json.loads(response.read())
        native=client=None
        native_log=(scratch/'server.log').open('wb'); client_error=(scratch/'client.log').open('wb')
        output=(root/'evidence/agent.jsonl').open('wb')
        controller.start()
        try:
            native=subprocess.Popen([str(executable),'serve','--pure','--hostname','127.0.0.1','--port',str(port)],
                cwd=root/'workspace',env=env,stdout=native_log,stderr=subprocess.STDOUT)
            while True:
                try: api('/global/health'); break
                except OSError:
                    if native.poll() is not None or controller.remaining()<50: raise RuntimeError('Isolated native server failed')
                    time.sleep(.05)
            session=api('/session',{'title':'synthetic staged server fixture','permission':[
                {'permission':p,'pattern':'*','action':'deny'} for p in ('question','plan_enter','plan_exit')]})['id']
            controller.bind_session(session)
            before=staged_input.snapshot(root/'workspace',policy)
            client=subprocess.Popen([str(executable),'run','--attach',address,'--dir',str(root/'workspace'),
                '--session',session,'--pure','--format','json','--model','sample2/'+model],
                cwd=root/'workspace',env=env,stdin=subprocess.PIPE,stdout=output,stderr=client_error)
            client.stdin.write(initial.encode()); client.stdin.close()
            while True:
                events,_=live_usage.journal(root/'evidence/agent.jsonl')
                terminals=[e['part'] for e in events if e.get('type')=='tool_use' and e.get('part',{}).get('state',{}).get('status') in ('completed','error')]
                if terminals: break
                if client.poll() is not None or controller.remaining()<35: raise RuntimeError('No tool terminal under held response')
                time.sleep(.02)
            barrier=None
            if gateway_barrier:
                while not (barrier:=proxy.inspect_stage_barrier()):
                    if proxy.failed.is_set() or controller.remaining()<30: raise ValueError('Gateway response barrier missing')
                    time.sleep(.01)
            if len(terminals)!=1 or len(requests)!=1 or not (barrier or holding.is_set()): raise ValueError('Synthetic boundary not exclusive')
            # Some kernels omit /proc/PID/task/TID/children. Observe the process
            # table independently; this finite case has only the awaited built-in
            # write tool, with LSP/plugins/subagents disabled by the same config.
            processes=[tuple(map(int,line.split())) for line in subprocess.check_output(['ps','-eo','pid=,ppid='],text=True).splitlines()]
            children=[pid for pid,parent in processes if parent==native.pid]
            if children: raise ValueError('Native child process still active')
            after=staged_input.snapshot(root/'workspace',policy)
            controller.audit_mounts()
            controller.boundary(terminals[0],before,after,{**(barrier or {}),'native_session_id':session,'run_instance_id':'synthetic-instance',
                'barrier_id':barrier['barrier_id'] if barrier else 'synthetic-response-1',
                'next_request_blocked':True,'active_tools':[],'children_exited':True,
                'completed_tool_call_ids':[terminals[0]['callID']]})
            def send(payload,remaining):
                proxy.arm_stage({k:payload[k] for k in ('run_id','run_instance_id','delivery_id','contract_sha256','additional_sha256','native_session_id','barrier_id')})
                answer=api('/session/'+session+'/message',{'noReply':True,'parts':[{'type':'text','text':payload['text']}],
                    'model':{'providerID':'sample2','modelID':model}})
                current=api('/session/'+session)
                return {'run_instance_id':'synthetic-instance','workspace':current['directory'],
                    'native_session_id':answer['info']['sessionID'],'native_message_id':answer['info']['id'],
                    'delivery_id':payload['delivery_id']}
            status=controller.dispatch(send)
            if status['delivery_state']!='acknowledged': raise ValueError('Native additional message not acknowledged')
            messages=api('/session/'+session+'/message')
            added=[m for m in messages if m['info']['role']=='user' and any(p.get('text')==additional for p in m['parts'])]
            if len(added)!=1 or len(requests)!=1: raise ValueError('Additional message not unique before response release')
            if gateway_barrier:
                ack=next(e for e in controller.events() if e['kind']=='acknowledged')
                proxy.release_stage_barrier(barrier['barrier_id'],ack['native_message_id'])
            else: release.set()
            client.wait(timeout=controller.remaining())
            if client.returncode: raise RuntimeError('Attached native CLI failed')
            final=staged_input.snapshot(root/'workspace',policy)
            native.terminate(); native.wait(timeout=10)
            proxy.shutdown(); proxy.server_close()
            controller.finish('synthetic_completed',stop_confirmed=True)
            manifest=util.read_json(root/'manifest.json'); manifest['stop_confirmed']=True;util.write_json_atomic(root/'manifest.json',manifest)
            # Synthetic prerequisite for exercising the actual collector, never
            # evidence that the local processes had production Docker isolation.
            util.write_new_json(root/'evidence/isolation.json',{'verified':True,'synthetic':True})
            normalized=live_usage.collect(root)
            result={'synthetic':True,'model_called':False,'real_opencode_version':version,
                'executable_sha256':util.sha256_file(executable),
                'transport_candidate':'fixed_server_api_with_'+('real_gateway' if gateway_barrier else 'fake_provider')+'_response_barrier',
                'native_session_count':len({e['sessionID'] for e in live_usage.journal(root/'evidence/agent.jsonl')[0] if 'sessionID' in e}),
                'native_additional_message_count':len(added),'request_count':len(requests),
                'additional_absent_first_request':not gateway.check_additional_input(requests[0],additional)['locations'],
                'additional_in_next_request':gateway.check_additional_input(requests[1],additional)['verified'],
                'initial_history_in_next_request':gateway.check_initial_input(requests[1],initial)['verified'],
                'implementation_changed_after_delivery':after['sha256']!=final['sha256'],
                'native_children_observed_at_boundary':len(children),
                'final_file':(root/'workspace/Program.cs').read_text().strip(),
                'observed_tokens':normalized['observed_tokens'],'gateway_additional_input_reached':normalized['input_reached'],
                'evidence_issues':normalized['inventory_issues'],'gateway_barrier_fixture_verified':gateway_barrier,
                'production_docker_verified':False,'live_acceptance':False}
            result['passed']=all(result[k] for k in ('additional_absent_first_request','additional_in_next_request','initial_history_in_next_request',
                'implementation_changed_after_delivery','gateway_additional_input_reached')) and result['native_session_count']==1 and not result['evidence_issues']
            return result
        finally:
            release.set()
            for process in (client,native):
                if process is not None and process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=5)
                    except subprocess.TimeoutExpired: process.kill();process.wait(timeout=5)
            for server in (proxy,upstream): server.shutdown();server.server_close()
            native_log.close();client_error.close();output.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--opencode',required=True)
    parser.add_argument('--gateway-barrier',action='store_true',help='Use the actual gateway barrier; fake provider ends normally')
    args=parser.parse_args();result=probe(args.opencode,gateway_barrier=args.gateway_barrier);print(json.dumps(result,indent=2))
    raise SystemExit(0 if result['passed'] else 1)
