"""Command line for the outer harness.

There is no command that calls a model. `start --runner dummy` runs a scripted
runner; `start --runner manual` only opens a run for a human to execute.
"""
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
    parser = argparse.ArgumentParser(prog='harness.cli', description='外側の実験実行基盤。モデルを呼ばない。')
    parser.add_argument('--repo', type=Path, default=REPO)
    parser.add_argument('--runs-dir', type=Path)
    sub = parser.add_subparsers(dest='command', required=True)

    create = sub.add_parser('create', help='Run を排他で作る')
    create.add_argument('--task', required=True)
    create.add_argument('--condition', required=True)
    create.add_argument('--attempt', type=int, default=1)
    create.add_argument('--input', action='append', default=[], metavar='NAME=PATH')

    start = sub.add_parser('start', help='実行器を走らせ、停止を確認する')
    start.add_argument('--run', required=True)
    start.add_argument('--runner', default='dummy', choices=list(runner.RUNNERS))
    start.add_argument('--scenario')
    start.add_argument('--seed', type=Path)
    start.add_argument('--synthetic', action='store_true')
    start.add_argument('--timeout', type=float)
    start.add_argument('--note')

    stop = sub.add_parser('stop', help='人の実行の停止を確認する')
    stop.add_argument('--run', required=True)
    stop.add_argument('--method', required=True, choices=list(run_mod.STOP_METHODS))
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

    sub.add_parser('build-evaluator', help='内側の評価器をビルドする（採点ではない）')
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    repo = Path(args.repo).resolve()
    runs_dir = Path(args.runs_dir).resolve() if args.runs_dir else default_runs_dir(repo)
    result = None
    if args.command == 'create':
        result = run_mod.create_run(repo, runs_dir, args.task, args.condition,
                                    args.attempt, parse_inputs(args.input))
    elif args.command == 'start':
        if args.runner not in runner.RUNNERS:
            parser.error('--runner は ' + ' / '.join(runner.RUNNERS) + ' のいずれかです')
        result = run_mod.start_run(repo, runs_dir, args.run, args.runner,
                                   synthetic=args.synthetic, scenario=args.scenario,
                                   seed=args.seed, timeout=args.timeout, note=args.note)
    elif args.command == 'stop':
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
    elif args.command == 'build-evaluator':
        code = evaluate.publish_evaluator(repo)
        result = {'exit_code': code}
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == '__main__':
    sys.exit(main())
