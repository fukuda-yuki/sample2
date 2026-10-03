"""Ordinary Student Create/Edit/Save observation and evaluator-owned composition."""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import time
import urllib.request
import uuid
from decimal import Decimal, InvalidOperation

from . import browser_cleanup, ownership, runtime, util
from .security import child_environment

VERSION = 'education-1.0.0'
OBSERVED = 'agent_observed_StudentCreateEdit'
REFERENCES = ('before', 'created', 'edit', 'after', 'beforeScreenshot', 'afterScreenshot', 'database')


def required(version):
    return version == VERSION


def coverage_complete(output):
    return (output.get('browserReviewCoverage') == OBSERVED and output.get('researchStatus') == 'complete'
            and bool(output.get('browserReviewEvidenceSha256')) and bool(output.get('reviewRunInstanceId')))


def execution_identity(directory):
    try:
        conditions = util.read_json(Path(directory)/'browser-school/receipt.json')['conditions']
        return {'conditions_sha256': util.sha256_bytes(json.dumps(conditions, sort_keys=True).encode()),
                'collector_sha256': conditions['collectorSha256'], 'browser_version': conditions['browserVersion'],
                'playwright_version': conditions['playwrightVersion']}
    except (OSError, ValueError, KeyError):
        return {'conditions_sha256': None, 'provenance': 'school observation missing'}


def stored_coverage_complete(directory, instance, artifact_hash, spec_hash, *, allow_partial=False):
    try:
        directory = Path(directory); output = util.read_json(directory/'evaluation.json')
        review = directory/'browser-school'; path = review/'receipt.json'
        if ((not allow_partial and not coverage_complete(output)) or output.get('reviewRunInstanceId') != instance
                or output.get('artifactSha256') != artifact_hash or output.get('specSha256') != spec_hash
                or util.sha256_file(path) != output['browserReviewEvidenceSha256']): return False
        receipt = util.read_json(path)
        if (receipt.get('schemaVersion') != 1 or receipt.get('actor') != 'agent'
                or receipt.get('runInstanceId') != instance or receipt.get('artifactSha256') != artifact_hash
                or receipt.get('specSha256') != spec_hash): return False
        # A partial output may preserve a confirmed HTTP failure. It may claim
        # a browser failure only when the measured Save and its evidence exist.
        if receipt.get('action') != 'create-edit-save': return False
        for name in REFERENCES:
            ref = receipt.get(name)
            if not ref:
                return False
            target = (review/ref['path']).resolve()
            if not target.is_relative_to(review.resolve()) or util.sha256_file(target) != ref['sha256']: return False
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False


def stored_failure(directory, instance, artifact_hash, spec_hash, evaluation_hash, *, baseline_directory=None):
    try:
        directory = Path(directory); output_path = directory/'evaluation.json'
        if not evaluation_hash or util.sha256_file(output_path) != evaluation_hash: return None
        output = util.read_json(output_path)
        if (output.get('reviewRunInstanceId') != instance or output.get('artifactSha256') != artifact_hash
                or output.get('specSha256') != spec_hash): return None
        baseline = Path(baseline_directory) if baseline_directory else directory/'http-only'
        if (util.sha256_file(baseline/'evaluation.json') != output.get('baselineEvaluationSha256')
                or util.sha256_file(baseline/'results.jsonl') != output.get('baselineResultsSha256')): return None
        http = util.read_json(baseline/'evaluation.json')
        if http.get('artifactSha256') != artifact_hash or http.get('specSha256') != spec_hash: return None
        observed = stored_coverage_complete(directory, instance, artifact_hash, spec_hash, allow_partial=True)
        source = output if observed else http
        failed = [r['id'] for r in source.get('requirements', []) if r['judgement'] == 'fail']
        if failed:
            return {'verdict': 'fail_critical' if source.get('criticalFailed') else 'fail',
                    'requirements': failed, 'source': 'composed' if observed else 'http-only'}
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def _equal(expected, actual):
    if expected is None or actual is None: return expected is actual
    try: return Decimal(str(expected)) == Decimal(str(actual))
    except InvalidOperation: return str(expected) == str(actual)


def _database_observation(path, student_id, oracle):
    with sqlite3.connect(path.as_uri()+'?mode=ro', uri=True) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute('SELECT ID,LastName,FirstMidName,EnrollmentDate FROM Students WHERE ID=?',
                                 (student_id,)).fetchone()
        preserved = True
        for table in ('Students', 'Departments', 'Courses', 'Enrollments'):
            contract = oracle['tables'][table]
            for expected in contract['rows']:
                actual = connection.execute('SELECT * FROM "'+table+'" WHERE "'+contract['key']+'"=?',
                                            (expected[contract['key']],)).fetchone()
                preserved &= actual is not None and all(_equal(v, actual[k]) for k, v in expected.items())
        value = {'student': dict(row) if row else {}, 'original_rows_preserved': bool(preserved),
                 'read_only': True, 'scope': 'Independent host SQLite read after actual browser Save'}
    connection.close()
    return value


def _compose(condition, frozen, baseline, assets, out, instance, sequence):
    work = out/'composition-work'; work.mkdir()
    image = condition['runtime_lock']['images']['evaluator']
    name, command = runtime.scoring_command(condition, frozen, out, work, assets, VERSION, sequence)
    owner = browser_cleanup.register(out, instance, 'container', name)
    at = command.index(image)
    command[at:at] = ['--label', 'sample2.browser-review='+owner, *runtime.mount(baseline, '/baseline', True)]
    command += ['--browser-school-baseline', '/baseline', '--browser-school-evidence', '/result/browser-school/receipt.json',
                '--review-run-instance-id', instance]
    util.write_new_json(out/'composition-intent.json', {'command': command, 'model_called': False,
                         'scope': ['E-012'], 'evaluator_sha256': util.sha256_file(assets/'evaluator'/condition['evaluation']['assembly'])})
    process = runtime.command(command, timeout=120, check=False)
    (out/'composition-stdout.log').write_text(process.stdout, encoding='utf-8')
    (out/'composition-stderr.log').write_text(process.stderr, encoding='utf-8')
    from .evaluate import check_mismatches
    output = util.read_json(out/'evaluation.json')
    mismatches = check_mismatches(output, condition, VERSION, frozen, util.artifact_hash(frozen),
                                  assets/'requirements.json', util.sha256_file(assets/'requirements.json'))
    if output.get('reviewRunInstanceId') != instance: mismatches.append({'check': 'school_browser_run_instance'})
    if output.get('browserReviewEvidenceSha256') != util.sha256_file(out/'browser-school/receipt.json'):
        mismatches.append({'check': 'school_browser_receipt'})
    reported = util.read_json(out/'evaluator-manifest.json')
    if reported.get('evaluatorSha256') != util.sha256_file(assets/'evaluator'/condition['evaluation']['assembly']):
        mismatches.append({'check': 'school_composer_build'})
    if mismatches: util.write_new_json(out/'mismatches.json', mismatches); return 2
    return process.returncode


def complete_evaluation(repo, condition, frozen, baseline, published, assets, out, instance, sequence):
    repo, frozen, baseline, published, assets, out = map(Path, (repo, frozen, baseline, published, assets, out))
    with ownership.lease(out):
        original = util.read_json(baseline/'evaluation.json')
        artifact_hash, spec_hash = util.artifact_hash(frozen), util.sha256_file(assets/'requirements.json')
        intent = {'run_instance_id': instance, 'artifact_sha256': artifact_hash, 'spec_sha256': spec_hash,
                  'baseline_evaluation_sha256': util.sha256_file(baseline/'evaluation.json'),
                  'baseline_results_sha256': util.sha256_file(baseline/'results.jsonl'),
                  'scope': ['E-012'], 'actor': 'agent', 'human_review': 'not_run', 'model_called': False}
        code, bound, created = 2, False, False
        name = 's2-browser-'+uuid.uuid4().hex; network = name+'-net'
        try:
            if (not instance or original.get('artifactSha256') != artifact_hash or original.get('specSha256') != spec_hash
                    or original.get('evaluationVersion') != VERSION or condition['evaluation']['spec_sha256'] != spec_hash):
                raise ValueError('School browser target/baseline mismatch')
            bound = True
            review = out/'browser-school'; review.mkdir()
            state = out/'browser-state'; state.mkdir()
            shutil.copyfile(assets/'initial-store.sqlite', state/'school.sqlite')
            intent['initial_database_sha256'] = util.sha256_file(assets/'initial-store.sqlite')
            util.reject_links(published); configs = list(published.glob('*.runtimeconfig.json'))
            if len(configs) != 1: raise ValueError('Published school application missing or ambiguous')
            assembly = configs[0].name.removesuffix('.runtimeconfig.json')+'.dll'
            published_hashes = util.tree_hashes(published); intent['published_files'] = published_hashes
            owner = browser_cleanup.register(out, instance, 'network', network)
            runtime.docker('network', 'create', '--opt', 'com.docker.network.bridge.enable_ip_masquerade=false',
                           '--label', 'sample2.browser-review='+owner, network)
            browser_cleanup.register(out, instance, 'container', name)
            command = ['docker', 'run', '-d', '--name', name, '--label', 'sample2.browser-review='+owner,
                       '--network', network, '--publish', '127.0.0.1::8080', *runtime.sandbox_args(),
                       *runtime.mount(published, '/app', True), *runtime.mount(state, '/data'), '--workdir', '/app',
                       '--env', 'ASPNETCORE_ENVIRONMENT=Production', '--env', 'ConnectionStrings__SchoolContext=Data Source=/data/school.sqlite',
                       condition['runtime_lock']['images']['evaluator'], 'dotnet', assembly, '--urls', 'http://0.0.0.0:8080']
            intent['launch_command'] = command; created = True; runtime.command(command)
            port = int(runtime.docker('port', name, '8080/tcp').stdout.strip().split(':')[-1]); base_url = 'http://127.0.0.1:'+str(port)
            ready = False; deadline = time.monotonic()+60
            while time.monotonic() < deadline:
                try:
                    with urllib.request.urlopen(base_url+'/', timeout=2) as response: ready = response.status == 200
                    if ready: break
                except (OSError, TimeoutError): pass
                time.sleep(.25)
            if not ready: raise RuntimeError('School browser app readiness timed out')
            oracle = util.read_json(assets/'migration-oracle.json')
            request = {'runInstanceId': instance, 'artifactSha256': artifact_hash, 'specSha256': spec_hash,
                       'baseUrl': base_url, 'createFields': oracle['workflow']['create']['fields'],
                       'editFields': oracle['workflow']['edit']['fields']}
            util.write_new_json(review/'request.json', request)
            collector = repo/'inner/browser/education-review.cjs'
            command = [os.environ.get('SAMPLE2_NODE', 'node'), str(collector.resolve()),
                       str((review/'request.json').resolve()), str(review.resolve())]
            intent['collector_command'] = command; intent['collector_sha256'] = util.sha256_file(collector)
            environment = child_environment({k: os.environ[k] for k in
                ('NODE_PATH', 'PLAYWRIGHT_BROWSERS_PATH', 'SAMPLE2_BROWSER_EXECUTABLE') if k in os.environ})
            from .evaluate import run_evaluator
            with (review/'stdout.log').open('xb') as stdout, (review/'stderr.log').open('xb') as stderr:
                exit_code, timed_out = run_evaluator(command, repo, environment, stdout, stderr, 120)
            if exit_code != 0 or timed_out: raise RuntimeError('School browser collection incomplete')
            receipt = util.read_json(review/'collector-receipt.json')
            if receipt.get('studentId'):
                util.write_new_json(review/'database.json', _database_observation(state/'school.sqlite', int(receipt['studentId']), oracle))
                receipt['database'] = {'path': 'database.json', 'sha256': util.sha256_file(review/'database.json')}
            util.write_new_json(review/'receipt.json', receipt)
            if util.tree_hashes(published) != published_hashes or util.artifact_hash(frozen) != artifact_hash:
                raise ValueError('Published or frozen school artifact changed')
            code = _compose(condition, frozen, baseline, assets, out, instance, sequence)
        except Exception as exc:
            util.write_new_json(out/'browser-fault.json', {'type': type(exc).__name__, 'message': str(exc), 'scoring_state': 'evaluator_fault'})
            if not (out/'evaluation.json').exists():
                fallback = {**original, 'verdict': original['verdict'] if bound and original.get('verdict') in ('fail','fail_critical') else 'error',
                            'quality': None, 'researchStatus': 'incomplete', 'browserReviewCoverage': 'evaluator_fault',
                            'browserReviewEvidenceSha256': None, 'reviewRunInstanceId': instance, 'evaluatorFaults': [str(exc)],
                            'baselineEvaluationSha256': intent['baseline_evaluation_sha256'], 'baselineResultsSha256': intent['baseline_results_sha256']}
                util.write_new_json(out/'evaluation.json', fallback)
        finally:
            if created:
                try:
                    logs = runtime.docker('logs', name, check=False, timeout=30)
                    (out/'browser-server.log').write_text(logs.stdout+logs.stderr, encoding='utf-8')
                except Exception as exc: intent['log_collection_error'] = str(exc)
            util.write_new_json(out/'browser-intent.json', intent)
            cleanup = browser_cleanup.cleanup(out, locked=True) if (browser_cleanup._local_path(out)/'browser-resources.json').exists() else {'confirmed': True, 'status': 'no_resources_created'}
            util.write_new_json(out/'browser-cleanup.json', cleanup)
        return code if cleanup['confirmed'] or code != 0 else 3
