"""Finite production-controller/actual-worker mock recording acceptance.

Uses the prepared NEW namespace. Credential bootstrap is a fixed canary; no
Windows API credential is read. Each injected Run is a distinct technical slot.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from outer.harness import live_usage, machine, profiles, run, runtime, util
from research import pair_execution
from outer.harness.security import child_environment

REPO=Path(__file__).resolve().parents[2]
CANARY='synthetic-repair-only-canary'
CASES=('actual-explore','actual-preload','partial-usage','partial-no-usage',
       'done-only','after-send-before-ack','controller-loss75','write-failure')

GATEWAY=r'''
import json,sys,threading,time,uuid
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
sys.path.insert(0,'/app')
from gateway import Gateway
mode,rid,instance=sys.argv[1:]
model='deepseek-v4.1-flash'
class Upstream(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_POST(self):
        request=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.server.calls+=1
        if mode=='after-send-before-ack':
            time.sleep(2); self.connection.close(); return
        self.send_response(200); self.send_header('Content-Type','text/event-stream'); self.end_headers()
        if mode=='done-only': self.wfile.write(b'data: [DONE]\n\n'); return
        item={'id':'mock-'+uuid.uuid4().hex,'model':model,'object':'chat.completion.chunk','created':1,
              'choices':[{'index':0,'delta':{'role':'assistant','content':'synthetic complete'},'finish_reason':None}]}
        if mode=='controller-loss75':
            assert any(t.get('function',{}).get('name')=='bash' for t in request.get('tools',[]))
            command=('touch /workspace/responses-ready; sleep 20' if self.server.calls==75
                     else 'printf synthetic-recording-fixture-'+str(self.server.calls))
            item['choices'][0]['delta']={'role':'assistant','tool_calls':[{'index':0,
                'id':'fixture-tool-'+str(self.server.calls),'type':'function',
                'function':{'name':'bash','arguments':json.dumps({'command':command,
                    'description':'Deterministic harmless recording fixture','timeout':30000})}}]}
        self.wfile.write(('data: '+json.dumps(item)+'\n\n').encode()); self.wfile.flush()
        item['choices']=[{'index':0,'delta':{},'finish_reason':'tool_calls' if mode=='controller-loss75' else 'stop'}]
        if mode!='partial-no-usage' and not (mode=='controller-loss75' and self.server.calls==75):
            item['usage']={'prompt_tokens':20,'completion_tokens':5,'total_tokens':25}
        self.wfile.write(('data: '+json.dumps(item)+'\n\n').encode()); self.wfile.flush()
        if mode not in ('partial-usage','partial-no-usage'): self.wfile.write(b'data: [DONE]\n\n')
server=ThreadingHTTPServer(('127.0.0.1',0),Upstream)
server.calls=0
threading.Thread(target=server.serve_forever,daemon=True).start()
gateway=Gateway(('0.0.0.0',8080),'/records',rid,model,sys.stdin.readline().strip(),
    session_id=instance,upstream_host='127.0.0.1',upstream_port=server.server_port,tls=False,
    expected_prompt='/contract/prompt.txt')
if mode=='write-failure':
    original=gateway.record
    def record(file,obj):
        if file=='started.jsonl': raise OSError('synthetic write failure before send')
        return original(file,obj)
    gateway.record=record
gateway.serve_with_signals()
'''

WORKER=r'''
import json,sys,time,urllib.request
from pathlib import Path
mode=sys.argv[1]
body={'model':'deepseek-v4.1-flash','stream':True,'messages':[{'role':'user','content':Path('/inputs/prompt.txt').read_text()}]}
for i in range(75 if mode=='controller-loss75' else 1):
    request=urllib.request.Request('http://gateway:8080/v1/chat/completions',data=json.dumps(body).encode(),
        headers={'Content-Type':'application/json'})
    try: urllib.request.urlopen(request,timeout=10).read()
    except Exception: pass
    print(json.dumps({'type':'step_finish','sessionID':'synthetic-native','index':i}),flush=True)
if mode=='controller-loss75':
    Path('/workspace/responses-ready').write_text('75')
    while True: time.sleep(.1)
'''


def child(root,case,repo,paired=False,synthetic_worker=False):
    root,repo=Path(root),Path(repo)
    old_docker=runtime.docker
    resolver=profiles.resolve
    def resolve(*args,**kwargs):
        c=resolver(*args,**kwargs)
        c['budget']['value']=120; c['runtime']['timeout_seconds']=120
        return c
    def docker(*args,**kwargs):
        args=list(args)
        if args and args[0]=='create' and '--name' in args:
            name=args[args.index('--name')+1]
            lock=util.read_json(repo/'artifacts/runtime/music-store-continuity-v1/lock.json')
            if name.startswith('s2-gateway-'):
                at=args.index(lock['images']['gateway'])
                instance=args[args.index('--session-id')+1]
                rid=args[args.index('--run-id')+1]
                args=args[:at]+['--entrypoint','python3',*runtime.mount(root/'fixtures','/fixtures',True),
                    lock['images']['gateway'],'/fixtures/gateway.py',case,rid,instance]
            elif name.startswith('s2-worker-') and synthetic_worker and not case.startswith('actual-'):
                at=args.index(lock['images']['worker'])
                args=args[:at]+[*runtime.mount(root/'fixtures','/fixtures',True),lock['images']['worker'],
                    'python3','/fixtures/worker.py',case]
        return old_docker(*args,**kwargs)
    with patch.object(profiles,'resolve',resolve),patch.object(runtime,'docker',docker),\
         patch.object(runtime,'_gateway_credential',return_value=CANARY):
        if paired:
            plan={'plan_sha256':util.sha256_file(root/'plan.json'),'cohort':'technical-mock-pair',
                  'runtime':'deepseek-migration-v1'}
            cases=[{'run_id':'MS1-CONT-A-'+arm+'-001','task':'MS1-CONT-A','condition':arm,
                    'attempt':1,'pair':1,'slot':i} for i,arm in enumerate(('explore','preload'),1)]
            def postprocess(repo,batch,rid,archive):
                peers=[util.read_json(batch/c['run_id']/'manifest.json') for c in cases]
                assert all(m['stop_confirmed'] for m in peers)
                assert all((batch/c['run_id']/'implementation-receipt.json').is_file() for c in cases)
                util.append_line(root/'heavy-boundary.jsonl',{'run_id':rid,'at':run.now(),'both_stopped':True})
                return {'run_id':rid,'verdict':None,'technical_boundary_only':True}
            result=pair_execution.execute_pair(plan,cases,root,repo=repo,concurrency=2,postprocess=postprocess)
            util.write_new_json(root/'pair-result.json',result)
            return
        intervention='preload' if case=='actual-preload' else 'explore'
        manifest=profiles.create(repo,root,'MS1-CONT-A',intervention,1,'deepseek-migration-v1')
        runtime.start(repo,root,manifest['run_id'])


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--repo',type=Path,default=REPO)
    p.add_argument('--out',type=Path)
    p.add_argument('--child',type=Path)
    p.add_argument('--case',choices=CASES)
    p.add_argument('--pair',action='store_true')
    p.add_argument('--synthetic-worker',action='store_true',help='Diagnostic fallback only; not ordinary-worker acceptance')
    p.add_argument('--cases',nargs='+',choices=CASES,default=CASES)
    a=p.parse_args()
    if a.child: child(a.child,a.case,a.repo,a.pair,a.synthetic_worker); return 0
    repo=a.repo.resolve()
    batch=a.out or repo/'runs'/('_recording-repair-mock-'+uuid.uuid4().hex[:12])
    batch.mkdir(parents=True,exist_ok=False)
    util.write_new_json(batch/'plan.json',{'cohort':'technical-recording-mock','real_model_calls':0,
        'cases':a.cases,'paired_actual_worker_check':a.pair,'ordinary_worker':not a.synthetic_worker,
        'controller_files':runtime.controller_files(repo),
        'limits':{'runs':len(a.cases)+(2 if a.pair else 0),'run_seconds':120,'fixed_no_retries':True},
        'expected':{'actual-*':'complete usage, exact serialized prompt, identical runtime and access',
            'partial-usage':'observed 25, total null','partial-no-usage':'observed null, total null',
            'done-only':'usage incomplete','after-send-before-ack':'observed send, no ack, usage missing',
            'controller-loss75':'observed activity after absent-controller stop, 75 saved responses',
            'write-failure':'no observed send, missing usage; retained failed write original'}})
    results=[]
    for case in a.cases:
        root=batch/case; fixtures=root/'fixtures'; fixtures.mkdir(parents=True)
        (fixtures/'gateway.py').write_text(GATEWAY,encoding='utf-8')
        (fixtures/'worker.py').write_text(WORKER,encoding='utf-8')
        rid='MS1-CONT-A-'+('preload' if case=='actual-preload' else 'explore')+'-001'
        run_root=root/rid
        with (root/'controller.log').open('xb') as output:
            process=subprocess.Popen([sys.executable,__file__,'--repo',str(repo),'--child',str(root),'--case',case,
                *(['--synthetic-worker'] if a.synthetic_worker else [])],
                cwd=repo,env=child_environment(),stdout=output,stderr=subprocess.STDOUT)
            try:
                if case=='controller-loss75':
                    deadline=time.monotonic()+90
                    while not (run_root/'workspace/responses-ready').exists():
                        if process.poll() is not None or time.monotonic()>deadline:
                            raise RuntimeError('75-response fixture did not reach crash boundary')
                        time.sleep(.2)
                    process.kill(); process.wait(timeout=10)
                    runtime.request_stop(run_root)
                else:
                    code=process.wait(timeout=150)
                    if code: raise RuntimeError('Mock controller failed; see '+str(root/'controller.log'))
            finally:
                if process.poll() is None:
                    process.kill(); process.wait(timeout=10)
                if (run_root/'runtime.json').exists(): runtime.stop_owned(run_root)
        live_usage.update_manifest_evidence(run_root)
        normalized=live_usage.collect(run_root)
        manifest=util.read_json(run_root/'manifest.json')
        evidence=manifest['execution_evidence']
        passed=manifest.get('stop_confirmed') and (manifest.get('network_cleanup') or {}).get('confirmed')
        if case.startswith('actual-'): passed=passed and normalized['usage_complete'] and normalized['input_reached']
        else: passed=passed and not normalized['usage_complete']
        if case=='partial-usage': passed=passed and normalized['observed_tokens']==25 and normalized['total_tokens'] is None
        if case in ('partial-no-usage','done-only','after-send-before-ack','write-failure'):
            passed=passed and normalized['total_tokens'] is None
        if case=='after-send-before-ack': passed=passed and evidence['send_evidence']=='observed_send' and not evidence['provider_acknowledged']
        if case=='controller-loss75':
            passed=passed and manifest['model_called'] is True and evidence['saved_response_count']==75
        safe=all(CANARY.encode() not in f.read_bytes() for f in (run_root/'usage').rglob('*') if f.is_file())
        config=util.read_json(run_root/'state/opencode.json')
        starts=util.read_lines(run_root/'usage/raw/started.jsonl')
        first=util.read_json(run_root/'usage/raw'/starts[0]['request_file']) if starts else {}
        result={'case':case,'passed':bool(passed and safe),'real_model_calls':0,
            'ordinary_opencode_worker':not a.synthetic_worker,
            'run_id':rid,'run_instance_id':manifest['run_instance_id'],'root':str(run_root),
            'model_called':manifest['model_called'],'execution_evidence':evidence,
            'usage_complete':normalized['usage_complete'],'observed_tokens':normalized['observed_tokens'],
            'total_tokens':normalized['total_tokens'],'input_reached':normalized['input_reached'],
            'first_request_contract':util.read_json(run_root/'usage/raw/first-request-contract.json')
                if (run_root/'usage/raw/first-request-contract.json').exists() else None,
            'model':first.get('model'),'tools':[t.get('function',{}).get('name') for t in first.get('tools',[])],
            'compaction':config['compaction'],'permission':config['permission'],
            'condition_sha256':manifest['condition_sha256'],'credential_records_redacted':safe,
            'isolation':util.read_json(run_root/'evidence/isolation.json')}
        util.write_new_json(root/'result.json',result); results.append(result)
        util.write_json_atomic(batch/'progress.json',{'results':results,'complete':False})
        print(json.dumps({'case':case,'passed':result['passed'],'root':str(run_root)}),flush=True)
        if not result['passed']: raise RuntimeError('Finite mock case failed; no replacement: '+str(root))
    if a.pair:
        root=batch/'actual-worker-pair'; fixtures=root/'fixtures'; fixtures.mkdir(parents=True)
        (fixtures/'gateway.py').write_text(GATEWAY,encoding='utf-8')
        util.write_new_json(root/'plan.json',{'purpose':'technical paired worker overlap and barrier','real_model_calls':0})
        with (root/'controller.log').open('xb') as output:
            code=subprocess.run([sys.executable,__file__,'--repo',str(repo),'--child',str(root),
                '--case','actual-explore','--pair'],cwd=repo,env=child_environment(),
                stdout=output,stderr=subprocess.STDOUT,timeout=180).returncode
        if code: raise RuntimeError('Actual-worker pair failed; retained '+str(root))
        manifests=[util.read_json(root/('MS1-CONT-A-'+arm+'-001')/'manifest.json') for arm in ('explore','preload')]
        from datetime import datetime
        begin=max(datetime.fromisoformat(m['started_at']) for m in manifests)
        end=min(datetime.fromisoformat(m['ended_at']) for m in manifests)
        overlap=max(0,(end-begin).total_seconds())
        decision=util.read_json(root/'pair-result.json')
        passed=overlap>0 and len(pair_execution.state(root/'_control/pair-journal.jsonl')['results'])==2
        passed=passed and decision['reason']=='pair_publication_restore_cleanup_required'
        result={'case':'actual-worker-pair','passed':passed,'overlap_seconds':overlap,
            'real_model_calls':0,'run_instances':[m['run_instance_id'] for m in manifests],
            'postprocess_boundary':util.read_lines(root/'heavy-boundary.jsonl'),'decision':decision}
        util.write_new_json(root/'result.json',result); results.append(result)
        if not passed: raise RuntimeError('Actual-worker pair boundary failed; no replacement')
    util.write_new_json(batch/'result.json',{'passed':all(r['passed'] for r in results),'results':results,
        'real_model_calls':0,'directory':str(batch)})
    print(str(batch)); return 0


if __name__=='__main__': sys.exit(main())
