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


def validate_authorization(repo, root, manifest, controller, condition):
    """Direct Run entrypoints cannot bypass the exact approved campaign plan.

    This is the existing local receipt trust boundary, not a new authentication
    mechanism. A partition alone is an implementation choice, never permission
    to dispatch a provider request.
    """
    from research import campaign_initialization, live_pilot, pair_execution
    acquisition = manifest.get('acquisition') or {}
    if not acquisition.get('epoch') or not acquisition.get('campaign_config'):
        raise ValueError('Staged activation requires the approved campaign acquisition binding')
    epoch = campaign_initialization.verify_epoch(live_pilot.checked(acquisition['epoch']), Path(repo))
    if acquisition['campaign_config'] != epoch['campaign_config'] or epoch.get('cases_per_assignment') != 1:
        raise ValueError('Staged campaign configuration differs from approved epoch')
    binding = manifest.get('assignment') or {}
    matches = [c for a in epoch['assignments'] for c in a['cases']
               if c['run_id'] == manifest['run_id'] and c['run_instance_id'] == manifest['run_instance_id']]
    if (len(matches) != 1 or any(binding.get(k) != v for k,v in matches[0].items())
            or Path(root).resolve() != Path(epoch['batch']).resolve()/('pair-'+str(matches[0]['pair']))/manifest['run_id']
            or condition['runtime']['id'] != epoch['runtime_by_task'][manifest['task_id']]
            or condition['runtime']['model_id'] != epoch['settings']['model_id']):
        raise ValueError('Staged Run is not the approved epoch assignment')
    dispatch=pair_execution.state(Path(root).parent/'_control/pair-journal.jsonl')['dispatch'].get(manifest['run_id'])
    config=util.read_json(live_pilot.checked(epoch['campaign_config']))
    if (not dispatch or any(dispatch.get(k)!=manifest[k] for k in ('run_id','run_instance_id'))
            or dispatch.get('input_sha256')!=manifest.get('prompt_sha256')
            or dispatch.get('condition_sha256')!=manifest.get('condition_sha256')
            or (Path(config['root'])/'STOP').exists()):
        raise ValueError('Staged activation requires an admitted dispatch and an open campaign')
    partition_plan = util.read_json(live_pilot.checked(epoch['staged_inputs'][manifest['task_id']]))
    initial, additional, partition = staged_input.request_partition(condition['migration_request'],partition_plan)
    from . import profiles
    prompt, _ = profiles.prepare_prompt({**condition,'migration_request':initial},Path(root)/'inputs/legacy-source')
    partition = {**partition,'request_initial_sha256':partition['initial_sha256'],
                 'initial_sha256':util.sha256_bytes(prompt.encode())}
    if (controller.contract['partition'] != partition
            or controller.contract['additional_sha256'] != util.sha256_bytes(additional.encode())
            or controller.contract['boundary_contract'] != partition_plan['boundary_contract']):
        raise ValueError('Staged transport/partition differs from the approved plan')


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

    def release(self, barrier_id, native_message_id=None, capture_complete=False):
        return self.api('gateway','/control/staged-barrier',{'action':'release','barrier_id':barrier_id,
            'run_id':self.state['run_id'],'run_instance_id':self.state['run_instance_id'],
            'native_message_id':native_message_id,'capture_complete':capture_complete})

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


def observe_boundary(controller, transport, barrier, events, before, *, after_delivery=False):
    """One whole model response's tools must terminate before considering mutation."""
    contract = controller.contract
    sessions = {e['sessionID'] for e in events if 'sessionID' in e}
    session = next(e['native_session_id'] for e in controller.events() if e['kind']=='native_session')
    if not sessions:return before,False
    if sessions != {session}: raise ValueError('Native session changed at boundary')
    parts = [e['part'] for e in events if e.get('type')=='tool_use'
        and e.get('part',{}).get('callID') in barrier['tool_call_ids']
        and e['part'].get('state',{}).get('status') in ('completed','error')]
    ids = [p['callID'] for p in parts]
    if len(ids) != len(set(ids)): raise ValueError('Duplicate native terminal tool event')
    if set(ids) != set(barrier['tool_call_ids']): return before, False
    if transport.children():
        # A completed tool with a surviving child has no attributable stable
        # terminal snapshot. Waiting for it would silently move the boundary.
        controller.unknown_boundary('live_children_at_tool_terminal',phase='after_additional' if after_delivery else 'before_additional')
        raise ValueError('Native child lifetime ambiguous at terminal tool boundary')
    after = staged_input.snapshot(contract['workspace'],contract['boundary_contract']['snapshot_policy'])
    changed = before['sha256'] != after['sha256']
    if changed and len(parts) != 1:
        # Simultaneous tools cannot be individually attributed by a global file
        # diff. Retain this ambiguity instead of moving to a later boundary.
        controller.unknown_boundary('parallel_mutation',phase='after_additional' if after_delivery else 'before_additional')
        raise ValueError('First mutation attribution ambiguous across parallel tools')
    if changed:
        if after_delivery:
            if barrier.get('phase')!='after_additional' or not barrier.get('first_additional_request_id'):
                raise ValueError('Post-input checkpoint lacks observed request binding')
            controller.checkpoint('after-additional',{'fence':barrier,'native_session_id':session,
                'tool_call_id':parts[0]['callID'],'message_id':parts[0]['messageID'],
                'before':before,'after':after,'tool_status':parts[0]['state']['status']})
            ack=next(e for e in controller.events() if e['kind']=='acknowledged')
            transport.release(barrier['barrier_id'],ack['native_message_id'],capture_complete=True)
            return after,True
        controller.boundary(parts[0],before,after,{**barrier,'native_session_id':session,
            'next_request_blocked':True,'active_tools':[],'children_exited':True,
            'completed_tool_call_ids':ids})
        controller.checkpoint('before-additional',{'fence':barrier,'native_session_id':session,
            'tool_call_id':parts[0]['callID'],'message_id':parts[0]['messageID'],'before':before,'after':after})
        controller.dispatch(transport.send)
        acks=[e for e in controller.events() if e['kind']=='acknowledged']
        if len(acks)!=1: raise RuntimeError('Additional delivery uncertain; retain and stop without resend')
        transport.release(barrier['barrier_id'],acks[0]['native_message_id'])
    else:
        controller.unchanged_boundary(before,after,barrier)
        ack=next((e for e in controller.events() if e['kind']=='acknowledged'),None)
        if after_delivery:transport.release(barrier['barrier_id'],ack['native_message_id'])
        else:transport.release(barrier['barrier_id'])
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
    controller.checkpoint('initial',{'native_session_id':session,'implementation':before})
    transport.owned('worker')
    command=['docker','exec','-i',state['worker'],'opencode','run','--attach',f'http://127.0.0.1:{PORT}',
        '--dir','/workspace','--session',session,'--pure','--format','json',
        '--model','sample2/'+condition['runtime']['model_id']]
    with (root/'evidence/agent.jsonl').open('xb') as output, (root/'inputs/prompt.txt').open('rb') as prompt:
        client=subprocess.Popen(command,stdin=prompt,stdout=output,stderr=subprocess.STDOUT,env=child_environment())
        try:
            delivered=False;captured=False;handled=set()
            while client.poll() is None:
                if (root/'stop-request.json').exists():
                    controller.stop('operator_stop');return None,'operator_stop'
                if not controller.remaining(): return None,'timeout'
                if (root/'usage/raw/failure.jsonl').exists(): return None,'provider_failure'
                if not captured:
                    barrier=transport.barrier()
                    if barrier and barrier['barrier_id'] not in handled:
                        events,errors=live_usage.journal(root/'evidence/agent.jsonl')
                        # A writer may currently be halfway through the last line.
                        if not errors:
                            prior=before
                            before,reached=observe_boundary(controller,transport,barrier,events,before,after_delivery=delivered)
                            if delivered:captured=reached
                            else:delivered=reached
                            if reached or before is not prior: handled.add(barrier['barrier_id'])
                time.sleep(.05)
            return client.returncode,'completed' if client.returncode==0 else 'agent_error'
        finally:
            # Terminate only this owned docker-exec client. The existing runtime
            # shutdown fences/stops both owned containers, including descendants.
            if client.poll() is None:
                client.terminate()
                try:client.wait(timeout=3)
                except subprocess.TimeoutExpired:client.kill();client.wait(timeout=3)
