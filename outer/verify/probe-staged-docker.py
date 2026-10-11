"""Opt-in real Docker/native/gateway probe with a localhost canned provider.

No model credential is read. The two explicitly replaced seams are campaign
approval (this is an artificial Run) and the gateway stdin secret (synthetic).
Everything from runtime.start through owned DockerTransport, isolation, stop,
network cleanup and live_usage collection is the production implementation.
The fixture worker has Python/bash + the unchanged native binary; no .NET SDK.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from outer.harness import gateway,live_usage,preserve,profiles,runtime,staged_input,staged_runtime,util

BASE='python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258'
BINARY_SHA='0254a429cd0e6cf0ba53fc01672cf98e4a8dc728f7fa94be88f1e4b3645e6ded'
REPO=Path(__file__).resolve().parents[2]

def build(directory,binary,base):
    directory.mkdir();shutil.copy2(binary,directory/'opencode')
    docker_config=directory/'docker-config';docker_config.mkdir()
    environment={**os.environ,'DOCKER_CONFIG':str(docker_config)}
    shutil.copy2(REPO/'outer/harness/gateway.py',directory/'gateway.py')
    shutil.copy2(REPO/'outer/verify/staged-fake-provider.py',directory/'provider.py')
    (directory/'Dockerfile').write_text('''ARG BASE=python:3.12-slim-bookworm
FROM ${BASE} AS worker
COPY --chmod=0755 opencode /usr/local/bin/opencode
ENV HOME=/tmp/home XDG_CONFIG_HOME=/tmp/config XDG_DATA_HOME=/state XDG_CACHE_HOME=/tmp/cache OPENCODE_DISABLE_AUTOUPDATE=true OPENCODE_DISABLE_MODELS_FETCH=true OPENCODE_DISABLE_DEFAULT_PLUGINS=true
WORKDIR /workspace
USER 1000:1000
FROM ${BASE} AS gateway
COPY --chmod=0555 gateway.py provider.py /app/
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 1000:1000
ENTRYPOINT ["python3","/app/provider.py"]
''')
    images={};tags={};prefix='s2-staged-fixture-'+uuid.uuid4().hex
    for target in ('worker','gateway'):
        tag=prefix+':'+target
        with (directory/(target+'.log')).open('wb') as output:
            subprocess.run(['docker','build','--network','none','--target',target,'--build-arg','BASE='+base,
                '-t',tag,str(directory)],check=True,stdout=output,stderr=subprocess.STDOUT,timeout=180,env=environment)
        images[target]=runtime.image_id(tag)
        tags[target]=tag;util.write_json_atomic(directory/'image-tags.json',tags)
    return images


def case(directory,images,scenario):
    root=directory/('STAGED-'+scenario+'-staged-explore-001');root.mkdir()
    for name in ('inputs/legacy-source','workspace','state','usage/raw','evidence','profiles','evaluation-assets'):
        (root/name).mkdir(parents=True)
    initial='Synthetic initial requirement: implement stage one.\n'
    additional='Synthetic later requirement: implement stage two in the same file.\n'
    (root/'inputs/prompt.txt').write_text(initial)
    (root/'inputs/legacy-source/Original.cs').write_text('// synthetic original source')
    (root/'inputs/original.sqlite').write_bytes(b'synthetic original DB; never hidden')
    condition=profiles.resolve(REPO,'MS1-001','explore')
    condition['runtime']['prompt_transport']='stdin';condition['runtime']['timeout_seconds']=50
    condition['runtime']['provider_timeout_seconds']=40
    condition['budget']['value']=50;condition['intervention']['method']='staged-explore'
    condition['runtime_lock']={'controller_files':runtime.controller_files(REPO),'images':images,'opencode_version':'1.17.11'}
    util.write_new_json(root/'condition.json',condition)
    util.write_new_json(root/'context.json',{'method':'staged-explore','blocks':[]})
    manifest={'schema_version':2,'run_id':root.name,'run_instance_id':uuid.uuid4().hex,'task_id':'STAGED-'+scenario,
        'condition_id':'staged-explore','started_at':None,'stop_confirmed':False,
        'condition_sha256':util.sha256_file(root/'condition.json'),'context_sha256':util.sha256_file(root/'context.json'),
        'input_files':util.tree_hashes(root/'inputs'),'assets_sha256':{},'profile_files':{},
        'prompt_sha256':util.sha256_file(root/'inputs/prompt.txt')}
    util.write_new_json(root/'manifest.json',manifest)
    policy={'suffixes':['.cs'],'excluded_directories':['obj','bin']}
    _,_,partition=staged_input.split_sections([{'id':'a','text':initial},{'id':'b','text':additional}],['a'],['b'])
    controller=staged_input.create(root/'_controller/staged-input',run_id=root.name,
        run_instance_id=manifest['run_instance_id'],task=manifest['task_id'],condition='staged-explore',
        workspace=root/'workspace',worker_roots=[root/'inputs',root/'state'],initial_prompt=initial,additional_prompt=additional,
        budget_seconds=50,boundary_contract={'transport':'opencode-server-response-barrier-v1',
            'snapshot_policy':policy,'snapshot_policy_sha256':staged_input.digest(policy)},partition=partition)
    controller.bind_run(root)
    # The public runtime entrypoint must reject a partition without approval,
    # before allocating a network or reading any real provider credential.
    with patch.object(runtime,'docker',side_effect=AssertionError('Unapproved Docker activation')):
        try:runtime.start(REPO,directory,root.name)
        except ValueError as error:
            if 'approved campaign' not in str(error):raise
        else:raise AssertionError('Unapproved staged activation succeeded')
    with patch.object(staged_runtime,'validate_authorization'),patch.object(runtime,'_gateway_credential',return_value='synthetic-canary'):
        result=runtime.start(REPO,directory,root.name)
    usage=util.read_json(root/'usage/normalized.json');events=controller.events()
    requests=[util.read_json(root/'usage/raw'/e['request_file']) for e in live_usage.journal(root/'usage/raw/started.jsonl')[0]]
    checks={'stop_confirmed':result['stop_confirmed'],'network_cleaned':result['network_cleanup']['confirmed'],
        'real_isolation_probe':util.read_json(root/'evidence/isolation.json')['verified'],
        'one_native_session':len(usage.get('staged_input',{}).get('native_session_ids',[]))==1,
        'later_absent_first':bool(requests) and not gateway.check_additional_input(requests[0],additional)['locations'],
        'unauthorized_activation_refused':True}
    if scenario=='write':
        checkpoints=usage['staged_input']['checkpoints']
        for label in ('before-additional','after-additional'):
            preserve.restore(controller.root/'checkpoint-archive',checkpoints[label]['archive'],root/('restore-'+label))
        restore_before=(root/'restore-before-additional/workspace/Program.cs').read_text()
        restore_after=(root/'restore-after-additional/workspace/Program.cs').read_text()
        checks.update(additional_in_next=len(requests)==3 and gateway.check_additional_input(requests[1],additional)['verified'],
            later_file_change=(root/'workspace/Program.cs').is_file() and (root/'workspace/Program.cs').read_text()=='// synthetic stage 2\n',
            one_send=sum(e['kind']=='send_intent' for e in events)==1,
            complete_stage_evidence=usage['input_reached'] and not usage['inventory_issues'],all_usage=usage['observed_tokens']==36,
            checkpoint_before_restored=restore_before=='// synthetic stage 1\n',
            checkpoint_after_restored=restore_after=='// synthetic stage 2\n')
    else:
        post=scenario.startswith('post-')
        reason='parallel_mutation' if 'parallel' in scenario else 'live_children_at_tool_terminal'
        checkpoints=usage['staged_input']['checkpoints']
        checks.update(no_resend=sum(e['kind']=='send_intent' for e in events)==int(post),
            stopped_at_ambiguous_response=len(requests)==1+int(post),
            explicit_unknown=any(e['kind']=='boundary_unknown' and e['reason']==reason for e in events),
            retained_usage=usage['observed_tokens']==12*(1+int(post)),
            post_checkpoint_null=checkpoints['after-additional']['archive'] is None,
            final_not_used_for_post=checkpoints['final']['archive'] is not None)
        if post:checks['null_reason']=checkpoints['after-additional']['reason']=='boundary_unknown:'+reason
    state=util.read_json(root/'runtime.json')
    for role in ('worker','gateway'):
        item=runtime._owned_container(state,role)
        if item: runtime.docker('rm',state[role])
    return {'scenario':scenario,'checks':checks,'passed':all(checks.values()),'end_reason':result['end_reason'],
        'request_count':len(requests),'observed_tokens':usage['observed_tokens'],'inventory_issues':usage['inventory_issues']}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--opencode',required=True,type=Path)
    p.add_argument('--base-image',default=BASE);p.add_argument('--output',required=True,type=Path)
    p.add_argument('--scenario',choices=['write','parallel','child','post-parallel','post-child','all'],default='all')
    a=p.parse_args();binary=a.opencode.resolve(strict=True)
    if util.sha256_file(binary)!=BINARY_SHA:raise ValueError('Exact already-acquired binary required')
    # Keep synthetic artifacts in the explicitly chosen private output directory
    # for failed-case investigation; the caller may remove them after inspection.
    a.output.mkdir(parents=True,exist_ok=False)
    images=build(a.output/'build',binary,a.base_image)
    rows=[]
    try:
        with patch.dict(os.environ,{'DOCKER_CONFIG':str(a.output/'build/docker-config')}):
            for scenario in (('write','parallel','child','post-parallel','post-child') if a.scenario=='all' else (a.scenario,)):
                rows.append(case(a.output,images,scenario))
        result={'synthetic':True,'external_model_called':False,'images':images,'base_image':a.base_image,
            'binary_sha256':BINARY_SHA,'cases':rows,'passed':all(row['passed'] for row in rows),
            'production_dotnet_worker_tested':False,'live_acceptance':False}
        util.write_new_json(a.output/'result.json',result);print(json.dumps(result,indent=2))
        return 0 if result['passed'] else 1
    finally:
        for path in a.output.glob('*/runtime.json'):
            state=util.read_json(path)
            runtime.stop_owned(path.parent)
            runtime.cleanup_network(path.parent)
            for role in ('worker','gateway'):
                if runtime._owned_container(state,role): runtime.docker('rm',state[role])
        # Tags are unique to this invocation; image layers can be shared by a
        # concurrent fixture. Never force-remove a shared ID or use prune.
        for tag in util.read_json(a.output/'build/image-tags.json').values():
            runtime.docker('image','rm',tag,check=False)
if __name__=='__main__':raise SystemExit(main())
