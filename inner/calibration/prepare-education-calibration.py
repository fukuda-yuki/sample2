"""Freeze finite school product controls and their expectations before scoring."""
import argparse
import json
from pathlib import Path
import shutil


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--task-outputs', type=Path, required=True)
    parser.add_argument('--task-assets', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(); out = args.out.resolve(); out.mkdir(parents=True, exist_ok=False)
    for variant in ('C', 'D'):
        source = args.task_assets/f'CU1-ENR-{variant}'
        shutil.copytree(source/'evaluation', out/'assets'/variant)
        shutil.copyfile(source/'inputs/existing-business/legacy-school.sqlite', out/'assets'/variant/'legacy-school.sqlite')
        shutil.copytree(args.task_outputs/f'reference-{variant}', out/f'reference-{variant}',
                        ignore=shutil.ignore_patterns('bin', 'obj', '.git'))
    shutil.copytree(args.task_outputs/'fixed-C-on-D', out/'fixed-grade-D',
                    ignore=shutil.ignore_patterns('bin', 'obj', '.git'))
    for name in ('wrong-mapping-C', 'invalid-names-C', 'broken-save-C', 'unsupported-save-C'):
        shutil.copytree(out/'reference-C', out/name)

    def replace(case, filename, old, new):
        path = out/case/'Education.Continuity'/filename
        source = path.read_text(encoding='utf-8')
        if source.count(old) != 1: raise ValueError('Declared mutation anchor absent/ambiguous: '+str(path))
        path.write_bytes(source.replace(old, new).replace('\r\n', '\n').encode('utf-8'))
    replace('wrong-mapping-C', 'Store.cs', 'SELECT ID,LastName,FirstName,EnrollmentDate FROM old.Person',
            'SELECT ID,LastName,LastName,EnrollmentDate FROM old.Person')
    replace('invalid-names-C', 'Program.cs',
            'string.IsNullOrWhiteSpace(last) || string.IsNullOrWhiteSpace(first) || last.Length > 50 || first.Length > 50 || ', '')
    replace('broken-save-C', 'Pages.cs', "<button type='submit'>\" + (id.HasValue ? \"Save\" : \"Create\")",
            "<button type='\" + (id.HasValue ? \"button\" : \"submit\") + \"'>\" + (id.HasValue ? \"Save\" : \"Create\")")
    replace('unsupported-save-C', 'Pages.cs', 'id.HasValue ? "Save" : "Create"', 'id.HasValue ? "Persist" : "Create"')

    def case(name, variant, artifact, verdict, state='scored', operation='complete', fault=None):
        return {'name': name, 'variant': variant, 'artifact_path': str(out/artifact),
                'expected': {'verdict': verdict, 'scoring_state': state, 'operation_status': operation,
                             'aggregate_verdict': None if verdict == 'blocked' else verdict},
                **({'fault': fault} if fault else {})}
    cases = [case('allowed-school-C', 'C', 'reference-C', 'pass'),
             case('allowed-school-D', 'D', 'reference-D', 'pass'),
             case('critical-fixed-grade-D', 'D', 'fixed-grade-D', 'fail_critical'),
             case('critical-wrong-raw-mapping-C', 'C', 'wrong-mapping-C', 'fail_critical', 'evaluation_incomplete', 'evaluation_incomplete'),
             case('critical-invalid-names-C', 'C', 'invalid-names-C', 'fail_critical'),
             case('defect-browser-save-C', 'C', 'broken-save-C', 'fail'),
             case('unsupported-save-C', 'C', 'unsupported-save-C', 'blocked', 'evaluation_incomplete', 'evaluation_incomplete'),
             case('collector-fault-known-grade-failure-D', 'D', 'fixed-grade-D', 'fail_critical', 'evaluator_fault', 'evaluation_incomplete', 'collector_unavailable'),
             case('cleanup-fault-known-grade-failure-D', 'D', 'fixed-grade-D', 'fail_critical', 'scored', 'cleanup_failed', 'cleanup_receipt_failure')]
    (out/'cases.json').write_bytes((json.dumps(cases, indent=2)+'\n').encode('utf-8'))
    print(out/'cases.json')


if __name__ == '__main__': main()
