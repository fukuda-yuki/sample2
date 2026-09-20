"""Resume unstarted slots after an explicit, saved evaluation-environment repair.

Never regenerates an existing slot. The first saved artifact must already have
passed operational recovery using ordinary rescore before this command starts.
The original plan, driver, dispatch journal, inputs and model runtime stay fixed.
"""
import argparse
from pathlib import Path
import subprocess
import sys

from outer.harness import aggregate, preserve, util
from outer.harness.security import child_environment
from research.catalog_pilot import REPO, assess, check_frozen


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan',type=Path,required=True)
    p.add_argument('--amendment',type=Path,required=True)
    args=p.parse_args()
    plan=util.read_json(args.plan)
    amendment=util.read_json(args.amendment)
    if amendment['plan_sha256']!=util.sha256_file(args.plan): raise ValueError('Wrong original plan')
    if amendment['recovery_driver_sha256']!=util.sha256_file(__file__): raise ValueError('Recovery driver changed')
    env=amendment['evaluation_environment']
    if set(env)!={'NODE_PATH','SAMPLE2_BROWSER_EXECUTABLE'}: raise ValueError('Only existing browser environment may change')
    if util.sha256_file(env['SAMPLE2_BROWSER_EXECUTABLE'])!=amendment['browser_sha256']: raise ValueError('Browser changed')
    for name, expected in amendment['dependency_hashes'].items():
        if util.tree_hashes(Path(env['NODE_PATH'])/name)!=expected: raise ValueError('Browser dependency changed')
    batch=Path(plan['runs_dir'])
    ledger=batch/'recovery-journal.jsonl'
    # Exclusive marker prevents replay after a crash, including uncertain dispatch.
    util.write_new_json(batch/'recovery-dispatch.json',{'amendment':str(args.amendment.resolve()),
        'amendment_sha256':util.sha256_file(args.amendment)})
    dispatched={e['case']['run_id'] for e in util.read_lines(batch/'journal.jsonl') if e['kind']=='dispatch'}
    if dispatched!=set(amendment['existing_run_ids']): raise ValueError('Dispatch inventory changed')
    for rid in dispatched:
        root=batch/rid
        row=aggregate.row_for(batch,rid)
        if assess(root,plan,row) or row['scoring']['state']!='scored' or not row['usage']['usage_complete']:
            raise ValueError('Existing Run has not completed technical recovery')
        for relative, sha in amendment['recovered_inputs'][rid].items():
            if util.sha256_file(root/relative)!=sha: raise ValueError('Existing original changed')
    for case in plan['slots']:
        if case['run_id'] in dispatched: continue
        check_frozen(plan)
        root=batch/case['run_id']
        if root.exists(): raise ValueError('Uncertain Run cannot be replayed')
        command=[sys.executable,'-m','outer.harness.cli','--runs-dir',str(batch),'run','--task','MS1-001',
            '--intervention',case['condition'],'--runtime',plan['runtime'],'--attempt',str(case['attempt'])]
        util.append_line(ledger,{'kind':'dispatch','case':case,'command':command})
        print('DISPATCH '+case['run_id'],flush=True)
        with (batch/'cli-logs'/(case['run_id']+'.log')).open('xb') as log:
            process=subprocess.run(command,cwd=REPO,env=child_environment(env),stdout=log,stderr=subprocess.STDOUT)
        row=aggregate.row_for(batch,case['run_id'])
        stops=assess(root,plan,row)
        reference=util.read_json(root/'archive-reference.json')
        preserve.verify(batch/'_archive',reference['package_id'],reference['sha256'])
        util.append_line(ledger,{'kind':'result','case':case,'cli_exit_code':process.returncode,'row':row,'stops':stops})
        print('RESULT '+case['run_id']+' scoring='+row['scoring']['state']+' stops='+str(stops),flush=True)
        if stops or row['scoring']['state'] in ('evaluator_fault','rejected_mismatch','not_attempted'): break


if __name__=='__main__': main()
