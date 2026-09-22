"""Freeze and execute exactly four technical pilot slots using the ordinary run CLI."""
import argparse
from collections import Counter
import json
from pathlib import Path
import random
import secrets
import subprocess
import sys

from outer.harness import aggregate, machine, preserve, profiles, run, runtime, util
from outer.harness.security import child_environment
from research.catalog_connection_probe import ARMS, RUNTIME, common_body
from research import catalog_environment
from research.catalog_identity import compare_initial

REPO = Path(__file__).resolve().parents[1]
PINNED = ('research/catalog_pilot.py','research/catalog_connection_probe.py','research/catalog_return_contract.py',
          'research/catalog_environment.py',
          'docs/ms1-catalog-return-two-condition-spec.md')


def freeze(probe, target, batch, browser_environment):
    probe, target = Path(probe).resolve(), Path(target).resolve()
    result = util.read_json(probe/'connection-result.json')
    if not result['verified'] or result['model_called']:
        raise ValueError('No-model connection gate is not complete')
    preset = profiles.read(REPO,'runtimes',RUNTIME)
    lock_path = profiles.runtime_root(REPO,'MS1-001',preset)/'lock.json'
    lock = util.read_json(lock_path)
    if result['runtime_lock_sha256'] != util.sha256_file(lock_path) or runtime.controller_files(REPO) != lock['controller_files']:
        raise ValueError('Runtime changed after connection probe')
    browser = catalog_environment.capture(browser_environment, REPO)
    seed = secrets.randbits(64)
    pairs = [list(ARMS), list(reversed(ARMS))]
    random.Random(seed).shuffle(pairs)
    counts, slots = Counter(), []
    for block, pair in enumerate(pairs,1):
        for position, arm in enumerate(pair,1):
            counts[arm] += 1
            slots.append({'slot':len(slots)+1,'block':block,'position':position,'condition':arm,
                'attempt':counts[arm], 'run_id':run.run_id_for('MS1-001',arm,counts[arm])})
    plan = {'schema_version':1,'cohort':'catalog-technical-pilot-20260920','frozen_at':run.now(),
        'base_commit':runtime.command(['git','rev-parse','HEAD'],cwd=REPO).stdout.strip(),
        'task':'MS1-001','runtime':RUNTIME,'runs_dir':str(Path(batch).resolve()),
        'slots':slots,'maximum_runs':4,'maximum_supplements':0,
        'randomization_seed':seed,'randomization':'random.Random(seed).shuffle([expanded-compact, compact-expanded])',
        'budget':{'run_seconds':1800,'provider_seconds':600,'concurrency':1},
        'model':'deepseek-v4.1-flash','agent':'OpenCode 1.17.11','fallback':False,
        'condition_fingerprints':machine.expected_conditions(REPO,'MS1-001',RUNTIME,ARMS),
        'images':lock['images'],'evaluator_sha256':lock['evaluator_sha256'],
        'browser_environment':browser,
        'probe':str(probe),'probe_result_sha256':util.sha256_file(probe/'connection-result.json'),
        'code_hashes':{p:util.sha256_file(REPO/p) for p in PINNED},
        'primary_measure':'provider input_tokens + output_tokens across all attempts; incomplete totals null with known sums separate',
        'quality':'public 29 requirements with ordinary browser evaluation through PR 12; retain known failure and incomplete coverage separately',
        'stop_rules':['authentication/quota failure','model/policy mismatch','initial input mismatch','source/file integrity mismatch',
                      'unconfirmed resource cleanup','technical environment failure; diagnose before any further model dispatch'],
        'product_failure_policy':'retain and continue; never replace or regenerate a failed slot',
        'evaluation_recovery':'reuse the same frozen artifact only; retain original evaluation',
        'inference_limit':'connection and behavior observation only; no efficacy or noninferiority conclusion',
        'next_stage':'separately freeze repetitions, primary comparison, quality rule and stopping rules after technical pilot review',
        'excluded':['historical 24 artifact reevaluation','historical ZIP recreation','bulk historical token audit','exploration reruns']}
    util.write_new_json(target,plan)
    print(json.dumps({'plan':str(target),'sha256':util.sha256_file(target),'slots':slots}),flush=True)


def check_frozen(plan):
    if machine.expected_conditions(REPO,'MS1-001',RUNTIME,ARMS) != plan['condition_fingerprints']:
        raise ValueError('Frozen profile/runtime changed')
    for name, sha in plan['code_hashes'].items():
        if util.sha256_file(REPO/name) != sha:
            raise ValueError('Frozen code changed: '+name)
    lock=util.read_json(profiles.runtime_root(REPO,'MS1-001',profiles.read(REPO,'runtimes',RUNTIME))/'lock.json')
    if runtime.controller_files(REPO) != lock['controller_files']:
        raise ValueError('Frozen controller changed')
    if util.sha256_file(Path(plan['probe'])/'connection-result.json') != plan['probe_result_sha256']:
        raise ValueError('Connection evidence changed')
    catalog_environment.validate(plan['browser_environment'], REPO)


def assess(root, plan, row):
    manifest=util.read_json(root/'manifest.json')
    events=util.read_lines(root/'usage/raw/events.jsonl')
    stops=[]
    if any(e.get('http_status') in (401,402,403,429) for e in events): stops.append('authentication_or_quota')
    if any(e.get('policy_error') or e.get('response_model_id') != plan['model'] for e in events): stops.append('model_or_provider_failure')
    if not manifest.get('stop_confirmed') or not (manifest.get('network_cleanup') or {}).get('confirmed'): stops.append('runtime_cleanup')
    if row.get('operation_status')=='cleanup_failed': stops.append('browser_cleanup')
    for relative in ('usage/raw/first-request-contract.json','state/catalog-access.json'):
        if not (root/relative).exists() or not util.read_json(root/relative)['verified']: stops.append(relative)
    if not stops:
        baseline=Path(plan['probe'])/run.run_id_for('MS1-001',manifest['intervention_id'],1)
        if not (compare_initial(root, baseline, plan) or {}).get('matches'): stops.append('initial_request_differs_from_probe')
        if util.read_json(root/'state/catalog-access.json') != util.read_json(baseline/'state/catalog-access.json'):
            stops.append('worker_files_or_retrieval_differs')
    profiles.validate_run(root)
    if manifest.get('end_reason') in ('environment_failure','stop_unconfirmed','provider_failure','operator_stop'):
        stops.append(manifest['end_reason'])
    return stops


def execute(target):
    plan=util.read_json(target)
    if len(plan['slots'])!=4 or plan['maximum_supplements']!=0: raise ValueError('Exactly four slots required')
    check_frozen(plan)
    # Validate presence/format using the already-authorized Windows user credential; never print it.
    runtime._gateway_credential()
    batch=Path(plan['runs_dir'])
    batch.mkdir(parents=True,exist_ok=False)
    (batch/'cli-logs').mkdir()
    util.write_new_json(batch/'plan.json',plan)
    records=[]
    for case in plan['slots']:
        check_frozen(plan)
        root=batch/case['run_id']
        if root.exists(): raise ValueError('Existing or uncertain Run must not be replayed')
        args=[sys.executable,'-m','outer.harness.cli','--runs-dir',str(batch),'run','--task','MS1-001',
              '--intervention',case['condition'],'--runtime',RUNTIME,'--attempt',str(case['attempt'])]
        util.append_line(batch/'journal.jsonl',{'kind':'dispatch','at':run.now(),'case':case,'command':args})
        print('DISPATCH '+case['run_id'],flush=True)
        with (batch/'cli-logs'/(case['run_id']+'.log')).open('xb') as log:
            process=subprocess.run(args,cwd=REPO,env=child_environment(plan['browser_environment']['environment']),
                                   stdout=log,stderr=subprocess.STDOUT)
        row=aggregate.row_for(batch,case['run_id'])
        stops=assess(root,plan,row)
        reference=util.read_json(root/'archive-reference.json')
        preserve.verify(batch/'_archive',reference['package_id'],reference['sha256'])
        record={'case':case,'row':row,'cli_exit_code':process.returncode,'stops':stops,'at':run.now()}
        records.append(record)
        util.append_line(batch/'journal.jsonl',{'kind':'result',**record})
        util.write_json_atomic(batch/'progress.json',{'records':records,'dispatched':len(records),'halted':bool(stops)})
        print('RESULT '+case['run_id']+' '+json.dumps({'stops':stops,'quality':row['quality'],
              'scoring':row['scoring']['state'],'usage':row['usage']}),flush=True)
        if stops: break
        if row['scoring']['state'] in ('evaluator_fault','rejected_mismatch','not_attempted'):
            # Leave originals available for an offline recovery before another dispatch.
            break
    util.write_new_json(batch/'execution-result.json',{'records':records,'assigned':4,
        'dispatched':len(records),'unstarted':4-len(records),'new_model_execution_finished':True})


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='command',required=True)
    f=sub.add_parser('freeze'); f.add_argument('--probe',required=True); f.add_argument('--out',required=True); f.add_argument('--batch',required=True)
    f.add_argument('--browser-environment',required=True,help='Saved successful probe of the existing Node/Playwright/browser environment')
    e=sub.add_parser('execute'); e.add_argument('--plan',required=True)
    args=p.parse_args()
    if args.command=='freeze': freeze(args.probe,args.out,args.batch,args.browser_environment)
    else: execute(args.plan)
