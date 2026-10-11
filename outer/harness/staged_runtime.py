"""Owned Docker adapter for fixed OpenCode server + gateway response boundary.

The runner is selected only by an explicit staged condition/contract. Requests
use docker-exec stdin: later text never enters argv, environment or worker files.
No retry is performed after any initial or additional dispatch intent.
"""
import json
from pathlib import Path
import subprocess
import time

from . import live_usage, staged_input, util
from .security import child_environment

PORT = 40961
API = """import json,sys,urllib.request
v=json.load(sys.stdin)
r=urllib.request.Request(v['url'], data=json.dumps(v['body']).encode() if v['body'] is not None else None,
 headers={'Content-Type':'application/json','x-opencode-directory':'/workspace'})
with urllib.request.urlopen(r,timeout=v['timeout']) as x: sys.stdout.buffer.write(x.read())
"""
CHILDREN = """import json,os,pathlib
rows=[]
for p in pathlib.Path('/proc').glob('[0-9]*/stat'):
 try:
  s=p.read_text();tail=s[s.rfind(')')+2:].split();rows.append((int(p.parent.name),int(tail[1]),tail[0]))
 except (OSError,ValueError): pass
parents={1};found=set()
while True:
 new={pid for pid,ppid,state in rows if ppid in parents and pid!=os.getpid() and state!='Z'}-found
 if not new:break
 found|=new;parents|=new
print(json.dumps(sorted(found)))
"""


class DockerTransport:
    def __init__(self, root, state, controller, runtime, model):
        self.root, self.state, self.controller, self.runtime = Path(root), state, controller, runtime
        self.model = model

    def owned(self, role):
        item = self.runtime._owned_container(self.state, role)
        if not item or not item['State']['Running']:
            raise RuntimeError('Owned staged '+role+' is not running')
        if role == 'worker':
            mounts = [m for m in item.get('Mounts', []) if m.get('Destination') == '/workspace']
            if len(mounts) != 1 or Path(mounts[0]['Source']).resolve() != (self.root/'workspace').resolve():
                raise ValueError('Staged workspace ownership mismatch')

    def api(self, role, path, body=None):
        if (self.root/'stop-request.json').exists() or (self.controller.root/'stop-request.json').exists():
            raise RuntimeError('Staged transport stopped')
        self.owned(role)
        timeout = min(10., self.controller.remaining())
        if timeout <= 0: raise TimeoutError('Original Run budget exhausted')
        port = PORT if role == 'worker' else 8080
        payload = {'url':f'http://127.0.0.1:{port}'+path,'body':body,'timeout':timeout}
        result = subprocess.run(['docker','exec','-i',self.state[role],'python3','-c',API],
            input=json.dumps(payload),text=True,capture_output=True,env=child_environment(),timeout=timeout+.5)
        if result.returncode: raise RuntimeError('Owned staged API call failed')
        return json.loads(result.stdout)

    def barrier(self):
        return self.api('gateway','/control/staged-barrier',{'action':'inspect',
            'run_id':self.state['run_id'],'run_instance_id':self.state['run_instance_id']})

    def release(self, barrier_id, native_message_id=None):
        return self.api('gateway','/control/staged-barrier',{'action':'release','barrier_id':barrier_id,
            'run_id':self.state['run_id'],'run_instance_id':self.state['run_instance_id'],
            'native_message_id':native_message_id})

    def children(self):
        self.owned('worker')
        result = self.runtime.docker('exec',self.state['worker'],'python3','-c',CHILDREN,
            timeout=max(.1,min(5.,self.controller.remaining())))
        return json.loads(result.stdout)

    def send(self, payload, remaining):
        self.api('gateway','/control/staged-input',{k:payload[k] for k in
            ('run_id','run_instance_id','delivery_id','contract_sha256','additional_sha256','native_session_id','barrier_id')})
        response = self.api('worker','/session/'+payload['native_session_id']+'/message',
            {'noReply':True,'model':{'providerID':'sample2','modelID':self.model},
             'parts':[{'type':'text','text':payload['text']}]})
        session = self.api('worker','/session/'+payload['native_session_id'])
        if session.get('directory') != '/workspace' or response['info'].get('role') != 'user':
            raise ValueError('Native acknowledgement/workspace mismatch')
        return {'run_instance_id':self.state['run_instance_id'],'workspace':str((self.root/'workspace').resolve()),
            'delivery_id':payload['delivery_id'],'native_session_id':response['info']['sessionID'],
            'native_message_id':response['info']['id']}


def observe_boundary(controller, transport, barrier, events, before):
    """One whole model response's tools must terminate before considering mutation."""
    contract = controller.contract
    sessions = {e['sessionID'] for e in events if 'sessionID' in e}
    session = next(e['native_session_id'] for e in controller.events() if e['kind']=='native_session')
    if sessions != {session}: raise ValueError('Native session changed at boundary')
    parts = [e['part'] for e in events if e.get('type')=='tool_use'
        and e.get('part',{}).get('callID') in barrier['tool_call_ids']
        and e['part'].get('state',{}).get('status') in ('completed','error')]
    ids = [p['callID'] for p in parts]
    if len(ids) != len(set(ids)): raise ValueError('Duplicate native terminal tool event')
    if set(ids) != set(barrier['tool_call_ids']) or transport.children(): return before, False
    after = staged_input.snapshot(contract['workspace'],contract['boundary_contract']['snapshot_policy'])
    changed = before['sha256'] != after['sha256']
    if changed and len(parts) != 1:
        # Simultaneous tools cannot be individually attributed by a global file
        # diff. Retain this ambiguity instead of moving to a later boundary.
        controller.unknown_boundary('parallel_mutation')
        raise ValueError('First mutation attribution ambiguous across parallel tools')
    if changed:
        controller.boundary(parts[0],before,after,{**barrier,'native_session_id':session,
            'next_request_blocked':True,'active_tools':[],'children_exited':True,
            'completed_tool_call_ids':ids})
        controller.dispatch(transport.send)
        acks=[e for e in controller.events() if e['kind']=='acknowledged']
        if len(acks)!=1: raise RuntimeError('Additional delivery uncertain; retain and stop without resend')
        transport.release(barrier['barrier_id'],acks[0]['native_message_id'])
    else:
        controller.unchanged_boundary(before,after,barrier)
        transport.release(barrier['barrier_id'])
    return after, changed


def execute(root, state, controller, condition, runtime, *, transport=None):
    """Called inside the existing Run owner; collection/scoring remain outside."""
    root=Path(root); transport=transport or DockerTransport(root,state,controller,runtime,condition['runtime']['model_id'])
    while True:
        if (root/'stop-request.json').exists(): return None,'operator_stop'
        if not controller.remaining(): return None,'timeout'
        try: transport.api('worker','/global/health');break
        except (OSError,RuntimeError,ValueError): time.sleep(.1)
    session=transport.api('worker','/session',{'title':state['run_id'],'permission':[
        {'permission':p,'pattern':'*','action':'deny'} for p in ('question','plan_enter','plan_exit')]})['id']
    controller.bind_session(session);controller.audit_mounts()
    before=staged_input.snapshot(controller.contract['workspace'],controller.contract['boundary_contract']['snapshot_policy'])
    util.write_new_json(controller.root/'initial-snapshot.json',before)
    transport.owned('worker')
    command=['docker','exec','-i',state['worker'],'opencode','run','--attach',f'http://127.0.0.1:{PORT}',
        '--dir','/workspace','--session',session,'--pure','--format','json',
        '--model','sample2/'+condition['runtime']['model_id']]
    with (root/'evidence/agent.jsonl').open('xb') as output, (root/'inputs/prompt.txt').open('rb') as prompt:
        client=subprocess.Popen(command,stdin=prompt,stdout=output,stderr=subprocess.STDOUT,env=child_environment())
        try:
            delivered=False;handled=set()
            while client.poll() is None:
                if (root/'stop-request.json').exists():
                    controller.stop('operator_stop');return None,'operator_stop'
                if not controller.remaining(): return None,'timeout'
                if (root/'usage/raw/failure.jsonl').exists(): return None,'provider_failure'
                if not delivered:
                    barrier=transport.barrier()
                    if barrier and barrier['barrier_id'] not in handled:
                        events,errors=live_usage.journal(root/'evidence/agent.jsonl')
                        # A writer may currently be halfway through the last line.
                        if not errors:
                            prior=before
                            before,delivered=observe_boundary(controller,transport,barrier,events,before)
                            if delivered or before is not prior: handled.add(barrier['barrier_id'])
                time.sleep(.05)
            return client.returncode,'completed' if client.returncode==0 else 'agent_error'
        finally:
            # Terminate only this owned docker-exec client. The existing runtime
            # shutdown fences/stops both owned containers, including descendants.
            if client.poll() is None:
                client.terminate()
                try:client.wait(timeout=3)
                except subprocess.TimeoutExpired:client.kill();client.wait(timeout=3)
