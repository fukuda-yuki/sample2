"""Known wrong first-student grade followed by a bounded later HTTP timeout."""
import argparse
import json
from pathlib import Path
import shutil

p = argparse.ArgumentParser()
p.add_argument('--prepared-controls', type=Path, required=True)
p.add_argument('--out', type=Path, required=True)
args = p.parse_args(); out = args.out.resolve(); out.mkdir(parents=True, exist_ok=False)
shutil.copytree(args.prepared_controls/'assets', out/'assets')
target = out/'wrong-grade-later-observer-fault-D'
shutil.copytree(args.prepared_controls/'fixed-grade-D', target)
program = target/'Education.Continuity/Program.cs'
source = program.read_text(encoding='utf-8')
old = 'app.MapGet("/Student/Details/{id:long}", (long id) =>\n{'
assert source.count(old) == 1
source = source.replace(old, 'app.MapGet("/Student/Details/{id:long}", async (long id) =>\n{\n    if (id == 202) await Task.Delay(30000);')
program.write_bytes(source.replace('\r\n', '\n').encode('utf-8'))
case = {'name': 'known-grade-then-http-observer-fault-D', 'variant': 'D', 'artifact_path': str(target),
        'fault': 'known_grade_then_http_timeout',
        'expected': {'verdict': 'fail_critical', 'scoring_state': 'evaluator_fault',
                     'operation_status': 'evaluation_incomplete', 'aggregate_verdict': 'fail_critical',
                     'critical_failed': ['EDU-R-005'], 'failed_requirements': ['EDU-R-005']}}
(out/'cases.json').write_bytes((json.dumps([case], indent=2)+'\n').encode('utf-8'))
print(out/'cases.json')
