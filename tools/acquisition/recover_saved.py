"""Serial, recorded repair of saved observations after the current driver exits."""
import argparse
import copy
import ctypes
import json
import shutil
from pathlib import Path
import subprocess
import sys
import time
import traceback
import uuid

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO))
from outer.harness import evaluate,util,run
from research import acquisition_pipeline as pipeline,campaign_reassessment,catalog_environment,live_pilot,pair_execution


def wait_owned_process(pid):
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_bool,ctypes.c_ulong]
    kernel.OpenProcess.restype=ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_ulong]
    kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    handle=kernel.OpenProcess(0x100000,False,pid)
    if not handle:
        if ctypes.get_last_error()!=87:raise OSError(ctypes.get_last_error(),'Cannot bind driver process')
        return
    try:
        while True:
            result=kernel.WaitForSingleObject(handle,1000)
            if result==0:return
            if result!=258:raise OSError('Driver wait failed')
    finally:kernel.CloseHandle(handle)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--wait-pid',type=int,required=True);args=parser.parse_args()
    config=util.read_json(args.config);root=Path(config['root']);session=uuid.uuid4().hex
    log=REPO.parent/'saved-evaluation-repair-events.jsonl'
    def event(kind,**values):
        row=dict(at=run.now(),kind=kind,session=session,**values)
        pair_execution.append(log,row);print(json.dumps(row),flush=True)
    event('waiting_for_driver',driver_pid=args.wait_pid,repo=str(REPO))
    wait_owned_process(args.wait_pid)
    event('driver_exited')
    with pair_execution.exclusive(root/'_owner'):
        events=[json.loads(l) for l in (root/'events.jsonl').read_text(encoding='utf-8').splitlines()]
        accepted=set(config['accepted_slots'])|{e['slot'] for e in events if e['kind']=='accepted'}
        attempts=[e for e in events if e['kind']=='reserved']
        for entry in attempts:
            slot=entry['slot']
            if slot not in (73,75,82,98) or slot in accepted:continue
            record=Path(entry['record']);batch=record.parent
            acquired=util.read_json(batch/'pipeline-acquisition.json')
            if not acquired['acquired']:continue
            attempt=util.read_json(record);plan=util.read_json(live_pilot.checked(attempt['epoch']))
            old_repo=live_pilot.checked(plan['launch_supervisor']).parent.parent
            browser=copy.deepcopy(util.read_json(live_pilot.checked(plan['browser_pin'])))
            browser['collector_hashes']['inner/browser/education-review.cjs']=util.sha256_file(REPO/'inner/browser/education-review.cjs')
            pin=batch/('recovery-browser-'+session+'.json');util.write_new_json(pin,browser)
            source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()
            intent=batch/('saved-evaluation-repair-'+session+'.json')
            util.write_new_json(intent,dict(at=run.now(),slot=slot,attempt=attempt['attempt'],model_calls=0,
                source_commit=source_commit,repo=str(REPO),browser=live_pilot.reference(pin),
                previous_browser=plan['browser_pin'],originals_preserved=True,
                changes=['fresh application-created browser database','details URL used for operation identity without rewriting captured markers'],
                native_scoring_work=(slot==75)))
            event('repair_started',slot=slot,intent=live_pilot.reference(intent))
            try:
                current=pair_execution.state(batch/'_control/pair-journal.jsonl')
                for binding in current['reserved'].values():
                    source=batch/binding['run_id'];live_pilot.validate_owned_terminal(source,binding)
                    condition=util.read_json(source/'condition.json')
                    observation=campaign_reassessment._observation(source,condition,binding['run_instance_id'])
                    if not observation.get('recoverable'):continue
                    sequence=max(evaluate.used_sequences(source),default=0)+1
                    with catalog_environment.activated(browser,REPO):
                        evaluate.score_run(REPO,batch,binding['run_id'],sequence=sequence,native_work=slot==75, recovery_source_repo=old_repo)
                    observation=campaign_reassessment._observation(source,condition,binding['run_instance_id'])
                    event('run_evaluated',slot=slot,run_id=binding['run_id'],sequence=sequence,observation=observation)
                    if observation.get('recoverable'):raise RuntimeError('Saved observation remains incomplete')
                # The original frozen archiver validates and archives the repaired receipts.
                with (batch/'saved-evaluation-repair-finalize.log').open('ab') as output:
                    result=subprocess.run([sys.executable,'-B','-X','utf8','-m','research.acquisition_pipeline',
                        'evaluate',str(record),'--repo',str(old_repo)],cwd=old_repo,stdout=output,stderr=subprocess.STDOUT,
                        creationflags=subprocess.CREATE_NO_WINDOW)
                if result.returncode:raise RuntimeError('Original pair finalization failed')
                outcome=util.read_json(batch/'pipeline-evaluation.json');assert outcome['accepted']
                pair_execution.append(root/'events.jsonl',dict(at=run.now(),kind='accepted',slot=slot,
                    quality=outcome['quality'],record=live_pilot.reference(batch/'pipeline-evaluation.json'),
                    repair=live_pilot.reference(intent)))
                accepted.add(slot);event('pair_recovered',slot=slot,accepted=len(accepted))
            except Exception as exc:
                event('repair_incomplete',slot=slot,error=str(exc),traceback=traceback.format_exc())
        pending,held=pipeline.pending_acquisition_slots(config,attempts,accepted)
        event('finished',accepted=sorted(accepted),pending=pending,held=sorted(held))
    if pending and shutil.disk_usage(root).free < config['bounds']['disk_free_min_bytes']:
        event('resume_deferred_disk_floor', free_bytes=shutil.disk_usage(root).free,
              required_bytes=config['bounds']['disk_free_min_bytes'])
        return
    if pending:
        repo=Path(config['repo']);w=REPO.parent
        launch=w/('pipeline-repair-resume-'+session+'.json')
        with (w/('pipeline-repair-resume-'+session+'.out.log')).open('ab') as out,(w/('pipeline-repair-resume-'+session+'.err.log')).open('ab') as err:
            child=subprocess.Popen([sys.executable,'-B','-X','utf8','-m','research.acquisition_pipeline','run',
                str(args.config),'--repo',str(repo)],cwd=repo,stdin=subprocess.DEVNULL,stdout=out,stderr=err,
                creationflags=subprocess.CREATE_NO_WINDOW|subprocess.DETACHED_PROCESS)
        util.write_new_json(launch,dict(at=run.now(),pid=child.pid,repo=str(repo),config=str(args.config)))
        event('remaining_acquisition_resumed',pid=child.pid,launch=str(launch))

if __name__=='__main__':main()
