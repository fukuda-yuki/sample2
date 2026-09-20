"""Windows operator entry point for live and legacy modernization experiments."""
import argparse
import json
import sys
from pathlib import Path

from . import aggregate
from . import evaluate
from . import preserve
from . import run as run_mod
from . import runner
from . import util
from . import profiles, runtime

REPO = Path(__file__).resolve().parents[2]


def default_runs_dir(repo):
    return Path(repo) / 'runs'


def parse_inputs(values):
    result = {}
    for item in values or []:
        if '=' not in item:
            raise SystemExit('--input は name=path の形式で与えてください: ' + item)
        name, _, path = item.partition('=')
        result[name.strip()] = path.strip()
    return result


def build_parser():
    parser = argparse.ArgumentParser(prog='harness.cli', description='モダナイズ検証機: 課題と介入を選択して実行・評価する。')
    parser.add_argument('--repo', type=Path, default=REPO)
    parser.add_argument('--runs-dir', type=Path)
    sub = parser.add_subparsers(dest='command', required=True)

    create = sub.add_parser('create', help='Run を排他で作る')
    create.add_argument('--task', required=True)
    create.add_argument('--condition')
    create.add_argument('--intervention')
    create.add_argument('--runtime', default='deepseek')
    create.add_argument('--attempt', type=int, default=1)
    create.add_argument('--input', action='append', default=[], metavar='NAME=PATH')

    start = sub.add_parser('start', help='実行器を走らせ、停止を確認する')
    start.add_argument('--run', required=True)
    start.add_argument('--runner', choices=[*runner.RUNNERS, 'opencode'])
    start.add_argument('--scenario')
    start.add_argument('--seed', type=Path)
    start.add_argument('--synthetic', action='store_true')
    start.add_argument('--timeout', type=float)
    start.add_argument('--note')

    stop = sub.add_parser('stop', help='実行停止を要求し、所有コンテナの停止を確認する')
    stop.add_argument('--run', required=True)
    stop.add_argument('--method', choices=list(run_mod.STOP_METHODS))
    stop.add_argument('--evidence')
    stop.add_argument('--end-reason', choices=list(run_mod.END_REASONS))

    collect = sub.add_parser('collect', help='成果物を固定し、使用量を正規化する')
    collect.add_argument('--run', required=True)

    for name, help_text in (('score', '内側の評価器を呼ぶ'), ('rescore', '新しい連番で採点し直す')):
        score = sub.add_parser(name, help=help_text)
        score.add_argument('--run', required=True)
        score.add_argument('--evaluator', type=Path)
        score.add_argument('--evaluation-version')
        score.add_argument('--sequence', type=int)

    agg = sub.add_parser('aggregate', help='保存済み資材だけから集計する')
    agg.add_argument('--out', type=Path)
    comparison = sub.add_parser('compare', help='課題・介入・固定環境ごとに保存済みRunを比較する')
    comparison.add_argument('--out', type=Path)

    pack = sub.add_parser('preserve', help='Run を append-only のパッケージとして保存する')
    pack.add_argument('--run', required=True)
    pack.add_argument('--archive', type=Path, required=True)
    pack.add_argument('--include', action='append', default=[],
                      choices=['workspace', 'evidence'])

    restore = sub.add_parser('restore', help='保存したパッケージを復元する')
    restore.add_argument('--archive', type=Path, required=True)
    restore.add_argument('--package', required=True)
    restore.add_argument('--destination', type=Path, required=True)
    restore.add_argument('--sha256')

    verify = sub.add_parser('verify-package', help='保存したパッケージを検証する')
    verify.add_argument('--archive', type=Path, required=True)
    verify.add_argument('--package', required=True)
    verify.add_argument('--sha256')

    cleanup = sub.add_parser('cleanup-browser', help='所有する残存資源だけを回収する。モデル・評価・ブラウザーを再実行しない')
    cleanup.add_argument('--directory', type=Path, required=True)
    sub.add_parser('build-evaluator', help='内側の評価器をビルドする（採点ではない）')
    view = sub.add_parser('profiles', help='課題・介入・実行環境の一覧または合成設定を表示する')
    view.add_argument('--task')
    view.add_argument('--intervention', default='explore')
    view.add_argument('--runtime', default='deepseek')
    prep = sub.add_parser('prepare', help='ソースと隔離実行イメージを用意する。モデルは呼ばない')
    prep.add_argument('--rebuild', action='store_true')
    prep.add_argument('--task', default='MS1-001')
    status = sub.add_parser('status', help='Runの状態と観測済み呼び出し数')
    status.add_argument('--run', required=True)
    one = sub.add_parser('run', help='実モデルで実行し、停止・回収・採点・保全する')
    one.add_argument('--task', required=True)
    one.add_argument('--intervention', required=True)
    one.add_argument('--runtime', default='deepseek')
    one.add_argument('--attempt', type=int, default=1)
    one.add_argument('--archive', type=Path)
    accept = sub.add_parser('acceptance', help='同じ環境で3介入各2Runの最終受入を実行する')
    accept.add_argument('--task', default='MS1-001')
    accept.add_argument('--runtime', default='deepseek')
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    repo = Path(args.repo).resolve()
    runs_dir = Path(args.runs_dir).resolve() if args.runs_dir else default_runs_dir(repo)
    result = None
    if args.command == 'create':
        if args.intervention:
            if args.condition or args.input:
                parser.error('--intervention は旧 --condition / --input と併用できません')
            result = profiles.create(repo, runs_dir, args.task, args.intervention, args.attempt, args.runtime)
        else:
            if not args.condition:
                parser.error('--intervention または --condition が必要です')
            result = run_mod.create_run(repo, runs_dir, args.task, args.condition,
                                        args.attempt, parse_inputs(args.input))
    elif args.command == 'start':
        live = run_mod.load_manifest(runs_dir, args.run).get('schema_version') == 2
        args.runner = args.runner or ('opencode' if live else 'dummy')
        if live and args.runner != 'opencode':
            parser.error('新形式のRunにはopencode実行器を使ってください')
        if args.runner == 'opencode':
            if args.synthetic or args.timeout is not None or args.scenario or args.seed or args.note:
                parser.error('実モデルの条件変更はRun作成前に実行環境プリセットへ記録してください')
            result = runtime.start(repo, runs_dir, args.run)
        elif args.runner not in runner.RUNNERS:
            parser.error('--runner は ' + ' / '.join(runner.RUNNERS) + ' のいずれかです')
        else:
            result = run_mod.start_run(repo, runs_dir, args.run, args.runner,
                                   synthetic=args.synthetic, scenario=args.scenario,
                                   seed=args.seed, timeout=args.timeout, note=args.note)
    elif args.command == 'stop':
        if run_mod.load_manifest(runs_dir, args.run).get('schema_version') == 2:
            result = runtime.request_stop(run_mod.run_dir_for(runs_dir, args.run))
        elif not args.method:
            parser.error('manual Runでは --method が必要です')
        else:
            result = run_mod.stop_run(runs_dir, args.run, args.method,
                                  evidence_text=args.evidence, end_reason=args.end_reason)
    elif args.command == 'collect':
        manifest, snapshot = run_mod.collect_run(runs_dir, args.run)
        result = {'run_id': manifest['run_id'], 'submission_fixed': manifest['submission_fixed'],
                  'artifact_state': snapshot['artifact_state'],
                  'artifact_sha256': snapshot['artifact_sha256'],
                  'artifact_sha256_collected': snapshot['artifact_sha256_collected'],
                  'normalized_files': len(snapshot['normalized'])}
    elif args.command in ('score', 'rescore'):
        result = evaluate.score_run(repo, runs_dir, args.run, evaluator=args.evaluator,
                                    evaluation_version=args.evaluation_version,
                                    sequence=args.sequence)
    elif args.command == 'aggregate':
        table = aggregate.build(runs_dir)
        out = Path(args.out) if args.out else runs_dir / 'aggregate.json'
        util.write_json_atomic(out, table)
        result = {'runs': table['run_count'], 'out': str(out)}
    elif args.command == 'compare':
        result = aggregate.compare(runs_dir)
        if args.out:
            util.write_json_atomic(args.out, result)
    elif args.command == 'preserve':
        manifest = run_mod.load_manifest(runs_dir, args.run)
        result = preserve.pack_run(args.archive, run_mod.run_dir_for(runs_dir, args.run),
                                   include=args.include)
    elif args.command == 'restore':
        result = preserve.restore(args.archive,
                                  {'package_id': args.package, 'sha256': args.sha256},
                                  args.destination)
    elif args.command == 'verify-package':
        result = preserve.verify(args.archive, args.package, args.sha256)
        result = {'package_id': args.package, 'file_count': len(result['files'])}
    elif args.command == 'cleanup-browser':
        from .browser_cleanup import cleanup
        result = cleanup(args.directory.resolve())
    elif args.command == 'build-evaluator':
        code = evaluate.publish_evaluator(repo)
        result = {'exit_code': code}
    elif args.command == 'profiles':
        result = (profiles.resolve(repo, args.task, args.intervention, args.runtime)
                  if args.task else profiles.inventory(repo))
    elif args.command == 'prepare':
        result = runtime.prepare(repo, task_id=args.task, rebuild=args.rebuild)
    elif args.command == 'status':
        root = run_mod.run_dir_for(runs_dir, args.run)
        result = aggregate.row_for(runs_dir, args.run)
        result['requests_started'] = len(util.read_lines(root / 'usage/raw/started.jsonl'))
        result['requests_ended'] = len(util.read_lines(root / 'usage/raw/events.jsonl'))
        result['model_called'] = bool(result.get('model_called') or result['requests_started'])
    elif args.command == 'run':
        from .machine import execute
        result = execute(repo, runs_dir, args.task, args.intervention, args.attempt,
                         args.runtime, args.archive or runs_dir / '_archive')
    elif args.command == 'acceptance':
        from .machine import acceptance
        result = acceptance(repo, runs_dir, args.task, args.runtime)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    if args.command == 'cleanup-browser' and not result.get('confirmed'):
        return 1
    if args.command in ('score', 'rescore', 'run') and result.get('operation_status') == 'cleanup_failed':
        return 1
    if args.command in ('start', 'stop', 'run') and result.get('network_cleanup') is not None:
        if not result['network_cleanup'].get('confirmed'):
            return 1
    if args.command == 'acceptance' and not result.get('complete'):
        return 1
    if args.command == 'start' and result.get('end_reason') != 'completed':
        return 1
    if args.command == 'stop' and not result.get('stop_confirmed'):
        return 1
    if args.command == 'run' and (result['execution']['state'] != 'completed'
            or result['scoring']['state'] != 'scored' or not result['usage'].get('usage_complete')):
        return 1
    if args.command in ('score', 'rescore') and result.get('scoring_state') != 'scored':
        return 1
    if args.command == 'build-evaluator':
        return result['exit_code']
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        sys.exit(main())
    except Exception as exc:
        print(json.dumps({'error':type(exc).__name__, 'message':str(exc)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
