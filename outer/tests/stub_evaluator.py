"""A stand-in evaluator for tests. It is not the real evaluator.

It produces the same hand-over shape so the outer harness's own rules
(duplicate refusal, mismatch rejection, fault classification, timeout and
process-tree teardown) can be tested without running the real evaluator.
The mode comes from HARNESS_STUB_MODE. Modes: ok, fault, no-output, sleep,
blocked, fail-critical, mismatch-{task,spec,artifact,version,path}, work-marker
(leaves a file in the work directory, like a scoring run's database),
manifest-mismatch (claims a different evaluator build than the one invoked).
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness import util  # noqa: E402


def write_json(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def write_manifest(out, version, artifact_hash, evaluator_sha256=None):
    """The evaluator's own statement about which build it is.

    The real evaluator hashes `Assembly.Location`. This stand-in hashes itself,
    so a test can tell "the outer recorded what it invoked" apart from "the
    outer copied what the evaluator claimed".
    """
    write_json(out / 'evaluator-manifest.json',
               {'evaluatorVersion': 'stub',
                'evaluationVersion': version,
                'evaluatorSha256': evaluator_sha256 or util.sha256_file(__file__),
                'artifactSha256': artifact_hash,
                'appProcessId': None,
                'appProcessIds': []})


def main():
    mode = os.environ.get('HARNESS_STUB_MODE', 'ok')
    argv = sys.argv[1:]
    options = {}
    index = 0
    while index < len(argv):
        if argv[index].startswith('--'):
            options[argv[index][2:]] = argv[index + 1]
            index += 2
        else:
            index += 1
    out = Path(options['out'])
    artifact = Path(options['artifact'])
    # The same rule the real evaluator enforces: a scoring run starts from an
    # empty work directory, so a reused one is a contract violation, not a score.
    work = Path(options['work'])
    if work.exists() and any(work.iterdir()):
        sys.stderr.write('stub: work directory is not empty\n')
        return 2
    if mode == 'no-output':
        sys.stderr.write('stub: produced nothing\n')
        return 1
    if mode == 'sleep':
        # Stands in for the app under test: a child that outlives this process
        # unless the whole tree is taken down. It never writes evaluation.json.
        grandchild = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])
        Path(os.environ['HARNESS_STUB_MARKER']).write_text(str(grandchild.pid), encoding='utf-8')
        sys.stderr.write('stub: sleeping\n')
        sys.stderr.flush()
        time.sleep(120)
        return 0
    artifact_hash = util.artifact_hash(artifact) if artifact.is_dir() else ''
    sequence = int(options.get('sequence', '1'))
    version = options.get('evaluation-version', '1.0.0')
    # A stand-in that claims to be a different build, to check that the outer
    # records what it invoked rather than what it was told.
    claimed_build = 'f' * 64 if mode == 'manifest-mismatch' else None
    ledger = util.read_json(options['spec'])
    task = ledger.get('taskId', 'MS1-001')
    spec_hash = util.sha256_file(options['spec'])
    reported_path = str(artifact.resolve())
    if mode == 'fault':
        output = {'evaluationId': '{}-{}-{}-{:03d}'.format(task, (artifact_hash or '000000000000')[:12], version, sequence),
                  'taskId': task, 'taskTitle': 'stub', 'evaluationVersion': version,
                  'specVersion': 'stub', 'specSha256': spec_hash,
                  'artifactPath': reported_path, 'artifactSha256': artifact_hash,
                  'sourceRepository': 'stub', 'sourceCommit': 'stub',
                  'verdict': 'error', 'quality': None,
                  'evaluatorFaults': ['stub fault'],
                  'requirementCount': 29, 'passedCount': 0, 'failedCount': 0,
                  'blockedCount': 0, 'errorCount': 0}
        write_json(out / 'evaluation.json', output)
        (out / 'results.jsonl').write_text('', encoding='utf-8')
        write_manifest(out, version, artifact_hash, claimed_build)
        sys.stderr.write('stub: evaluator fault\n')
        return 2
    if mode == 'mismatch-task':
        task = 'WRONG-TASK'
    if mode == 'mismatch-spec':
        spec_hash = '0' * 64
    if mode == 'mismatch-artifact':
        artifact_hash = 'f' * 64
    if mode == 'mismatch-version':
        version = '9.9.9'
    if mode == 'mismatch-path':
        reported_path = str(artifact.parent / 'somewhere-else')
    verdict, quality, blocked, failed = 'pass', 100.0, 0, 0
    if mode == 'blocked':
        verdict, quality, blocked = 'blocked', 90.0, 2
    if mode == 'fail-critical':
        verdict, quality, failed = 'fail_critical', 31.03, 20
    output = {'evaluationId': '{}-{}-{}-{:03d}'.format(task, (artifact_hash or '000000000000')[:12], version, sequence),
              'taskId': task, 'taskTitle': 'stub', 'evaluationVersion': version,
              'specVersion': 'stub', 'specSha256': spec_hash,
              'artifactPath': reported_path, 'artifactSha256': artifact_hash,
              'sourceRepository': 'stub', 'sourceCommit': 'stub',
              'verdict': verdict, 'quality': quality, 'evaluatorFaults': [],
              'requirementCount': 29, 'passedCount': 29 - blocked - failed,
              'failedCount': failed, 'blockedCount': blocked, 'errorCount': 0}
    write_json(out / 'evaluation.json', output)
    (out / 'results.jsonl').write_text('', encoding='utf-8')
    write_manifest(out, version, artifact_hash, claimed_build)
    if mode == 'work-marker':
        # Leaves something behind, like a scoring run's SQLite file would.
        (work / 'store.sqlite').write_text('leftover\n', encoding='utf-8')
    return 0


if __name__ == '__main__':
    sys.exit(main())
