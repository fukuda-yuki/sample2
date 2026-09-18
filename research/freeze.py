"""Freeze the approved schedule and pilot evidence before new acquisition."""
from collections import Counter
from datetime import datetime, timezone
import itertools
import json
from pathlib import Path
import random
import secrets
import subprocess

from outer.harness import machine, runtime
from research.analyze import read_json, sha, write_json


def main():
    repo=Path(__file__).resolve().parents[1]
    pilot=repo/'artifacts/exploration/20260919/pilot-v1'
    audit=read_json(pilot/'audit.json')
    if audit['issues'] or (audit['run_count'],audit['call_count'],audit['action_count'])!=(6,322,532):
        raise ValueError('Pilot gate not passed')
    target=repo/'research/protocols/ms1-001-exploration-20260919.json'
    if target.exists():
        raise ValueError('Plan already frozen')
    lock=read_json(repo/'artifacts/runtime/MS1-001/lock.json')
    if runtime.controller_files(repo)!=lock['controller_files']:
        raise ValueError('Controller differs from retained runtime')
    for digest in lock['images'].values():
        if runtime.image_id(digest)!=digest:
            raise ValueError('Image mismatch')
    arms=('explore','preload','explained')
    permutations=list(itertools.permutations(arms))
    seed=secrets.randbits(64)
    random.Random(seed).shuffle(permutations)
    slots=[]; count=Counter()
    for b,order in enumerate(permutations,1):
        for position,arm in enumerate(order,1):
            count[arm]+=1
            slots.append({'slot':len(slots)+1,'block':b,'position':position,'condition':arm,
                'attempt':count[arm], 'run_id':f'MS1-001-{arm}-{count[arm]:03d}','cohort':'primary18'})
    plan={'protocol_version':'1.0.0','frozen_at':datetime.now(timezone.utc).isoformat(),
          'base_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip(),
          'randomization_seed':seed,'randomization':'Python random.Random(seed).shuffle(all six itertools.permutations)',
          'runs_dir':'runs/exploration-20260919-ms1','slots':slots,'maximum_supplements':6,
          'condition_fingerprints':machine.expected_conditions(repo,'MS1-001','deepseek',arms),
          'images':lock['images'],'evaluator_sha256':lock['evaluator_sha256'],
          'research_code_hashes':{str(p.relative_to(repo)).replace('\\','/'):sha(p) for p in
              [repo/'research/analyze.py',repo/'research/acquire.py',repo/'research/freeze.py']},
          'protocol_sha256':sha(repo/'docs/ms1-exploration-20260919-protocol.md'),
          'pilot':{'root':'runs/acceptance-64ad09cd85ca','analysis':'artifacts/exploration/20260919/pilot-v1',
                   'audit_sha256':sha(pilot/'audit.json'),'analysis_sha256':sha(pilot/'analysis.json'),
                   'source_hashes_sha256':sha(pilot/'source-hashes.json')},
          'hypotheses':['H1 initial delivery versus reacquisition','H2 large tool-output retention','H3 action grouping and repetition'],
          'primary_metric':'sum of provider input_tokens + output_tokens over every model call',
          'data_policy':'historical, primary and supplement cohorts remain separate; originals immutable; missing is null',
          'human_review':'after exploration, before confirmation; per-arm complete passing Run nearest median total tokens'}
    target.parent.mkdir(parents=True,exist_ok=True)
    write_json(target,plan)
    print(json.dumps({'plan':str(target),'sha256':sha(target),'blocks':permutations,'seed':seed},ensure_ascii=True))


if __name__=='__main__':
    main()
