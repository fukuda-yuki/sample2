"""Non-model verification of the outer harness.

It builds the real evaluator and runs the real end-to-end path against the
calibration fixtures, then records what was observed. It never calls a model.

Usage: python outer/verify/verify.py --repo <repo root>
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import aggregate, evaluate, preserve, run as run_mod, util  # noqa: E402

TASK_ID = 'MS1-001'
CONDITION_ID = 'C01'
RUN_ID = 'MS1-001-C01-001'

# Recorded in inner/calibration/README.md section 2 for the same bytes.
REFERENCE_HASH = '9a6de335c982a35a6fa76737872c698ade9d32a1b03cc1636ebb90d8d9259e73'
REFERENCE_SHORT = '9a6de335c982'
EXPECTED_TOKENS = 7420

BROKEN_PROJECT = ('<Project Sdk="Microsoft.NET.Sdk.Web">\n'
                  '  <PropertyGroup>\n'
                  '    <TargetFramework>net8.0</TargetFramework>\n'
                  '  </PropertyGroup>\n'
                  '</Project>\n')


class Report:
    def __init__(self, repo):
        self.repo = str(repo)
        self.cases = []
        self.commands = []
        self.artifacts = {}
        self.started_at = datetime.now(timezone.utc).isoformat()

    def command(self, text):
        self.commands.append(text)

    def artifact(self, key, value):
        """A measured value recorded so a reader can recheck it independently."""
        self.artifacts[key] = value

    def case(self, case_id, kind, what, expected, observed):
        matched = expected == observed
        self.cases.append({'id': case_id, 'kind': kind, 'what': what,
                           'expected': expected, 'observed': observed,
                           'matched': matched})
        print('{} {} {}'.format(case_id, 'OK    ' if matched else 'MISMATCH', what))
        if not matched:
            print('  expected: ' + json.dumps(expected, ensure_ascii=False, sort_keys=True))
            print('  observed: ' + json.dumps(observed, ensure_ascii=False, sort_keys=True))
        return matched

    def matched(self):
        return all(case['matched'] for case in self.cases)

    def summary(self):
        return {
            'schema_version': 1,
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'started_at': self.started_at,
            'repo': self.repo,
            'note': ('外側の実験実行基盤の非モデル検証の生記録。モデルは一切呼び出していない。'
                     '期待は実行前に宣言し、観測値と完全一致で突き合わせる。'),
            'environment': {
                'platform': sys.platform,
                'python': sys.version.split()[0],
                'dotnet': dotnet_version(self.repo),
            },
            'commands': self.commands,
            'artifacts': self.artifacts,
            'case_count': len(self.cases),
            'mismatched': [case['id'] for case in self.cases if not case['matched']],
            'cases': self.cases,
        }


def dotnet_version(repo):
    try:
        completed = subprocess.run(['dotnet', '--version'], cwd=repo,
                                   capture_output=True, text=True, encoding='utf-8',
                                   errors='replace')
        return completed.stdout.strip()
    except OSError as error:
        return 'unavailable: ' + str(error)


def run_step(report, command, cwd, **kwargs):
    report.command(' '.join(str(part) for part in command))
    return subprocess.run([str(part) for part in command], cwd=str(cwd),
                          capture_output=True, text=True, encoding='utf-8',
                          errors='replace', **kwargs)


def build_evaluator(repo, report):
    project = repo / 'inner' / 'evaluator' / 'MusicStore.Evaluator' / 'MusicStore.Evaluator.csproj'
    completed = run_step(report, ['dotnet', 'build', project, '-c', 'Release', '--nologo', '-v', 'q'],
                         repo)
    report.case('V-0', 'measured', '評価器をビルドする',
                {'exit_code': 0}, {'exit_code': completed.returncode})
    return completed.returncode == 0


def run_unit_tests(repo, report):
    tests = repo / 'outer' / 'tests'
    completed = run_step(report, [sys.executable, '-m', 'unittest', 'discover',
                                  '-p', 'test_*.py', '-v'], tests)
    output = completed.stderr or ''
    ran = re.search(r'Ran (\d+) tests', output)
    count = int(ran.group(1)) if ran else None
    failed = len(re.findall(r'^(FAIL|ERROR):', output, flags=re.MULTILINE))
    report.case('V-1', 'measured', '外側のテストを実行する',
                {'failed': 0, 'ran_at_least_70': True},
                {'failed': failed, 'ran_at_least_70': bool(count and count >= 70)})
    # The five mismatch rules are checked with a stand-in evaluator, not the real
    # one. Record that the named test exists and ran green rather than claiming
    # the real evaluator was used.
    named = 'test_mismatches_are_rejected_and_kept_as_evidence'
    report.case('V-1b', 'scripted',
                '取り違えの 5 検査は outer/tests の代替評価器で確認する（実評価器ではない）',
                {'test_present_and_green': True},
                {'test_present_and_green': bool(
                    re.search(re.escape(named) + r'.*\.\.\. ok', output))})
    return count, failed, output


def make_stand_in(scratch):
    """A stand-in for the legacy source. The harness never reads its content."""
    source = scratch / 'legacy-source'
    source.mkdir(parents=True, exist_ok=True)
    (source / 'README.md').write_bytes(
        ('# 非モデル検証用の入力の代役\n\n'
         '実モデル実行では、ここに旧実装 `chack411/MVC-Music-Store`（`net48` ブランチ、\n'
         'コミット `2967afb9d69488641df0d154e2ad5827a7820e71`）の作業ツリーを置く。\n'
         '本ファイルは `outer/verify/verify.py` が実行時に作る代役であり、\n'
         '成果物の採点には使われない。\n').encode('utf-8'))
    return source


def make_broken_project(scratch):
    """An artifact that cannot be published, to reach the evaluator's fault path."""
    project = scratch / 'broken-web'
    project.mkdir(parents=True, exist_ok=True)
    (project / 'Broken.Web.csproj').write_bytes(BROKEN_PROJECT.encode('utf-8'))
    (project / 'Program.cs').write_bytes(b'this is not C#\n')
    return project


def create_start_collect(repo, runs, attempt, source, seed, scenario='ok'):
    manifest = run_mod.create_run(repo, runs, TASK_ID, CONDITION_ID, attempt,
                                  {'legacy-source': source})
    run_mod.start_run(repo, runs, manifest['run_id'], 'dummy', synthetic=True,
                      scenario=scenario, seed=seed)
    manifest, snapshot = run_mod.collect_run(runs, manifest['run_id'])
    return manifest, snapshot


def score(repo, runs, run_id, **kwargs):
    return evaluate.score_run(repo, runs, run_id, **kwargs)


def input_policy_path(repo, runs, scratch, report):
    before = sorted(path.name for path in Path(runs).iterdir())
    attempts = []
    cases = (
        ('inner', {'legacy-source': repo / 'inner'}),
        ('docs', {'legacy-source': repo / 'docs'}),
        ('allowlist', {'legacy-source': scratch / 'legacy-source',
                       'extra': scratch / 'legacy-source'}),
    )
    for _, inputs in cases:
        try:
            run_mod.create_run(repo, runs, TASK_ID, CONDITION_ID, 90, inputs)
            attempts.append('accepted')
        except ValueError:
            attempts.append('refused')
    after = sorted(path.name for path in Path(runs).iterdir())
    report.case('V-9', 'measured', '非公開領域と許可リスト外を入力にできない',
                {'attempts': ['refused', 'refused', 'refused'],
                 'runs_unchanged': True},
                {'attempts': attempts, 'runs_unchanged': before == after})


def positive_path(repo, runs, source, reference, report):
    manifest, snapshot = create_start_collect(repo, runs, 1, source, reference)
    record = score(repo, runs, manifest['run_id'])
    usage = run_mod.read_usage(run_mod.run_dir_for(runs, manifest['run_id']))
    report.case('V-2', 'measured', '正例を実行し、実評価器で採点する',
                {'end_reason': 'completed', 'stop_confirmed': True,
                 'stop_method': 'process_exit', 'model_called': False,
                 'artifact_state': 'fixed', 'artifact_sha256': REFERENCE_HASH,
                 'artifact_sha256_collected': REFERENCE_HASH,
                 'normalized_files': 0, 'usage_state': 'complete',
                 'total_tokens': EXPECTED_TOKENS, 'scoring_state': 'scored',
                 'adopted': True, 'verdict': 'pass', 'quality': 100.0,
                 'mismatches': [], 'evaluation_id': 'MS1-001-9a6de335c982-1.0.0-001',
                 'artifact_sha256_reported': REFERENCE_HASH},
                {'end_reason': manifest['end_reason'],
                 'stop_confirmed': manifest['stop_confirmed'],
                 'stop_method': manifest['stop_method'],
                 'model_called': manifest['model_called'],
                 'artifact_state': snapshot['artifact_state'],
                 'artifact_sha256': snapshot['artifact_sha256'],
                 'artifact_sha256_collected': snapshot['artifact_sha256_collected'],
                 'normalized_files': len(snapshot['normalized']),
                 'usage_state': usage.get('state'),
                 'total_tokens': usage.get('total_tokens'),
                 'scoring_state': record['scoring_state'],
                 'adopted': record['adopted'],
                 'verdict': record['verdict'],
                 'quality': record['quality'],
                 'mismatches': record['mismatches'],
                 'evaluation_id': record['evaluation_id'],
                 'artifact_sha256_reported': record['artifact_sha256_reported']})
    return manifest, record


def line_ending_path(repo, runs, source, reference, report):
    manifest, snapshot = create_start_collect(repo, runs, 2, source, reference, scenario='crlf')
    record = score(repo, runs, manifest['run_id'])
    kinds = sorted({kind for entry in snapshot['normalized'] for kind in entry['changed']})
    report.case('V-3', 'measured',
                'CRLF と BOM の作業ツリーでも同じ成果物ハッシュと同じ評価 ID になる',
                {'artifact_hash_changed_by_collection': True,
                 'normalized_kinds': ['bom_removed', 'crlf_to_lf'],
                 'artifact_sha256': REFERENCE_HASH,
                 'evaluation_id': 'MS1-001-9a6de335c982-1.0.0-001'},
                {'artifact_hash_changed_by_collection': snapshot['artifact_hash_changed_by_collection'],
                 'normalized_kinds': kinds,
                 'artifact_sha256': snapshot['artifact_sha256'],
                 'evaluation_id': record['evaluation_id']})
    return manifest


def duplicate_path(runs, run_id, report):
    evaluations = run_mod.run_dir_for(runs, run_id) / 'evaluations'
    before = sorted(p.name for p in evaluations.iterdir() if p.is_dir())
    index_before = (evaluations / 'index.jsonl').read_bytes()
    raised = None
    try:
        score(Path(report.repo), runs, run_id, sequence=1)
    except FileExistsError as error:
        raised = type(error).__name__
    after = sorted(p.name for p in evaluations.iterdir() if p.is_dir())
    report.case('V-4', 'measured',
                '同じ成果物・同じ評価版・同じ連番の再実行を重複として拒否する',
                {'raised': 'FileExistsError', 'directories_before': 1,
                 'directories_after': 1, 'index_unchanged': True},
                {'raised': raised, 'directories_before': len(before),
                 'directories_after': len(after),
                 'index_unchanged': index_before == (evaluations / 'index.jsonl').read_bytes()})


def rescore_path(repo, runs, run_id, first, report):
    second = score(repo, runs, run_id)
    entries = evaluate.read_index(run_mod.run_dir_for(runs, run_id))
    report.case('V-5', 'measured',
                '連番を進めた再採点で判定・品質・成果物ハッシュが一致し、差が連番だけになる',
                {'verdict': first['verdict'], 'quality': first['quality'],
                 'artifact_sha256_outer': first['artifact_sha256_outer'],
                 'prefix_equal': True, 'sequence_delta': 1, 'index_lines': 2},
                {'verdict': second['verdict'], 'quality': second['quality'],
                 'artifact_sha256_outer': second['artifact_sha256_outer'],
                 'prefix_equal': (first['evaluation_id'].rsplit('-', 1)[0]
                                  == second['evaluation_id'].rsplit('-', 1)[0]),
                 'sequence_delta': second['sequence'] - first['sequence'],
                 'index_lines': len(entries)})
    return second


def fault_path(repo, runs, source, broken, report):
    manifest, _ = create_start_collect(repo, runs, 3, source, broken)
    record = score(repo, runs, manifest['run_id'])
    manifest = run_mod.load_manifest(runs, manifest['run_id'])
    row = aggregate.row_for(runs, manifest['run_id'])
    report.case('V-6', 'measured',
                '実評価器の障害を実行の失敗として扱わない',
                {'scoring_state': 'evaluator_fault', 'evaluator_exit_code': 2,
                 'quality': None, 'adopted': False, 'end_reason': 'completed',
                 'stop_confirmed': True, 'row_quality': None, 'row_verdict': None,
                 'row_issue_kinds': ['evaluator_fault', 'synthetic']},
                {'scoring_state': record['scoring_state'],
                 'evaluator_exit_code': record['evaluator_exit_code'],
                 'quality': record['quality'], 'adopted': record['adopted'],
                 'end_reason': manifest['end_reason'],
                 'stop_confirmed': manifest['stop_confirmed'],
                 'row_quality': row['quality'], 'row_verdict': row['verdict'],
                 'row_issue_kinds': [issue['kind'] for issue in row['issues']]})
    return manifest


def aggregate_path(runs, report):
    table = aggregate.build(runs)
    rows = {row['run_id']: row for row in table['runs']}
    report.case('V-7', 'measured', '保存済み資材だけから集計し、失敗した Run も残す',
                {'run_count': 3, 'scored_rows': 2, 'fault_rows': 1,
                 'unscored_quality_is_null': True, 'unscored_verdict_is_null': True,
                 'synthetic_rows': 3},
                {'run_count': table['run_count'],
                 'scored_rows': sum(1 for r in rows.values()
                                    if r['scoring']['state'] == 'scored'),
                 'fault_rows': sum(1 for r in rows.values()
                                   if r['scoring']['state'] == 'evaluator_fault'),
                 'unscored_quality_is_null': all(r['quality'] is None for r in rows.values()
                                                 if r['scoring']['state'] != 'scored'),
                 'unscored_verdict_is_null': all(r['verdict'] is None for r in rows.values()
                                                 if r['scoring']['state'] != 'scored'),
                 'synthetic_rows': sum(1 for r in rows.values() if r['synthetic'])})
    return table, rows


def preservation_path(runs, run_id, original_row, archive, restored, report):
    packed = preserve.pack_run(archive, run_mod.run_dir_for(runs, run_id))
    report.command('harness.cli preserve --run {} --archive {}'.format(run_id, archive))
    verified = preserve.verify(archive, packed['package_id'], packed['sha256'])
    preserve.restore(archive, packed, restored / run_id)
    table = aggregate.build(restored)
    rows = {row['run_id']: row for row in table['runs']}
    row = rows.get(run_id, {})
    report.case('V-8', 'measured',
                '保存したパッケージを検証・復元し、復元した資材で再集計できる',
                {'package_id': 'run-' + run_id, 'package_files': len(verified['files']),
                 'restored_runs': 1, 'quality': original_row['quality'],
                 'verdict': original_row['verdict'],
                 'artifact_sha256': original_row['artifact']['artifact_sha256'],
                 'usage_total_tokens': original_row['usage']['total_tokens']},
                {'package_id': packed['package_id'], 'package_files': len(verified['files']),
                 'restored_runs': table['run_count'], 'quality': row.get('quality'),
                 'verdict': row.get('verdict'),
                 'artifact_sha256': (row.get('artifact') or {}).get('artifact_sha256'),
                 'usage_total_tokens': (row.get('usage') or {}).get('total_tokens')})


def app_process_path(runs, run_id, report):
    """The evidence must name the app process, so a leftover can be identified."""
    run_dir = run_mod.run_dir_for(runs, run_id)
    evaluation_id = evaluate.read_index(run_dir)[0]['evaluation_id']
    evaluation = run_dir / 'evaluations' / evaluation_id
    header = (evaluation / 'evidence' / 'app-process.log').read_text(
        encoding='utf-8').splitlines()[0]
    pids = util.read_json(evaluation / 'evaluator-manifest.json')['appProcessIds']
    report.case('V-10', 'measured',
                '証跡がアプリのプロセス ID とポートを残す',
                {'header_matches': True, 'app_process_ids': 2, 'first_pid_in_header': True},
                {'header_matches': bool(re.match(
                    r'^===== app process \(pid \d+, url http://127\.0\.0\.1:\d+, started .+\) =====$',
                    header)),
                 'app_process_ids': len(pids),
                 'first_pid_in_header': 'pid {}'.format(pids[0]) in header})
    return evaluation_id


def evaluator_build_path(repo, runs, run_id, record, rows, report):
    """Which build scored must be measured by the outer, not taken on trust.

    `evaluation_version` names the meaning of the judgement; this is the
    identity of the artifact that produced it.
    """
    measured = util.sha256_file(evaluate.evaluator_file(repo))
    run_dir = run_mod.run_dir_for(runs, run_id)
    index_rows = evaluate.read_index(run_dir)
    scoring = rows[run_id]['scoring']
    report.artifact('evaluator_dll', evaluate.DEFAULT_EVALUATOR_DLL)
    report.artifact('evaluator_sha256', measured)
    report.case('V-11', 'measured',
                '採点した評価器ビルドを外側が測って記録する',
                {'record_matches_file': True, 'reported_matches_file': True,
                 'every_index_row_matches_file': True, 'index_row_count': 2,
                 'aggregate_matches_file': True,
                 'version_is_not_the_build': True},
                {'record_matches_file': record['evaluator_sha256'] == measured,
                 'reported_matches_file': record['evaluator_sha256_reported'] == measured,
                 'every_index_row_matches_file': all(
                     row['evaluator_sha256'] == measured for row in index_rows),
                 'index_row_count': len(index_rows),
                 'aggregate_matches_file': scoring['evaluator_sha256'] == measured,
                 'version_is_not_the_build': record['evaluation_version'] == '1.0.0'
                 and record['evaluation_version'] != measured})


def leaked_app_processes(report, before):
    report.case('V-12', 'measured',
                '検証の前後で成果物のアプリのプロセスが増えていない',
                {'leaked': []}, {'leaked': sorted(_app_processes() - before)})


def _app_processes():
    """PIDs of `dotnet <something>MusicStore.Web.dll` on this machine."""
    script = ("Get-CimInstance Win32_Process -Filter \"Name='dotnet.exe'\" | "
              "Where-Object { $_.CommandLine -like '*MusicStore.Web.dll*' } | "
              "ForEach-Object { $_.ProcessId }")
    completed = subprocess.run(['powershell', '-NoProfile', '-Command', script],
                               capture_output=True, text=True, encoding='utf-8',
                               errors='replace')
    if completed.returncode != 0:
        raise RuntimeError('プロセスを列挙できませんでした: ' + completed.stderr.strip())
    return {int(line) for line in completed.stdout.split() if line.strip().isdigit()}


def main(argv=None):
    parser = argparse.ArgumentParser(description='外側の実験実行基盤の非モデル検証。モデルを呼ばない。')
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    runs = repo / 'runs' / '_verify'
    scratch = repo / 'outer' / 'verify' / '.scratch'
    if runs.exists():
        shutil.rmtree(runs)
    if scratch.exists():
        shutil.rmtree(scratch)
    runs.mkdir(parents=True)
    reference = repo / 'inner' / 'fixtures' / 'reference'
    source = make_stand_in(scratch)
    broken = make_broken_project(scratch)
    report = Report(repo)
    app_processes_before = _app_processes()

    if not build_evaluator(repo, report):
        print('評価器をビルドできませんでした。')
        return 1
    run_unit_tests(repo, report)
    _, first = positive_path(repo, runs, source, reference, report)
    line_ending_path(repo, runs, source, reference, report)
    duplicate_path(runs, RUN_ID, report)
    rescore_path(repo, runs, RUN_ID, first, report)
    fault_path(repo, runs, source, broken, report)
    _, rows = aggregate_path(runs, report)
    preservation_path(runs, RUN_ID, rows[RUN_ID],
                      scratch / 'archive', scratch / 'restored', report)
    input_policy_path(repo, runs, scratch, report)
    app_process_path(runs, RUN_ID, report)
    evaluator_build_path(repo, runs, RUN_ID, first, rows, report)
    leaked_app_processes(report, app_processes_before)

    summary = report.summary()
    out = args.out or (repo / 'outer' / 'verify' / 'verification-summary.json')
    util.write_json_atomic(out, summary)
    print('')
    print('cases: {}  mismatched: {}'.format(summary['case_count'],
                                             len(summary['mismatched'])))
    print('summary: ' + str(out))
    if scratch.exists():
        shutil.rmtree(scratch)
    return 0 if report.matched() else 1


if __name__ == '__main__':
    sys.exit(main())
