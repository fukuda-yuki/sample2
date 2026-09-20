"""Normal research evaluation's real-browser phase, also reused for saved corrections.

The inner evaluator owns judgements. This module starts only the published app
in its original sandbox image, collects clicks, and asks it to compose results.
No model, Run mutation, direct removal POST, or application repair occurs here.
"""
import json
import os
from pathlib import Path
import subprocess
import time
import uuid
import urllib.request

from . import runtime, util, browser_cleanup, ownership
from .security import child_environment

OBSERVED = 'agent_observed_C-015_C-016'


def required(version):
    return version == '1.2.0'


def coverage_complete(output):
    return (output.get('browserCartCoverage') in (OBSERVED, 'agent_assessed_C-015_C-016')
            and bool(output.get('browserCartEvidenceSha256'))
            and bool(output.get('reviewRunInstanceId'))
            and output.get('researchStatus') == 'complete')


def execution_identity(directory):
    """Keep different collectors/browser conditions out of the same comparison group."""
    conditions = util.read_json(Path(directory)/'browser-cart/receipt.json').get('conditions')
    if not conditions: return {'conditions_sha256': None, 'provenance': 'historical independent receipt'}
    return {'conditions_sha256': util.sha256_bytes(json.dumps(conditions, sort_keys=True).encode('utf-8')),
            'collector_sha256': conditions.get('collectorSha256'), 'browser_version': conditions.get('browserVersion'),
            'playwright_version': conditions.get('playwrightVersion')}


def stored_coverage_complete(directory, instance, artifact_hash, spec_hash, *, allow_partial=False):
    """Read-only aggregate gate: an index's pass cannot stand in for evidence."""
    try:
        directory = Path(directory)
        output = util.read_json(directory/'evaluation.json')
        review = directory/'browser-cart'
        receipt_path = review/'receipt.json'
        if ((not allow_partial and not coverage_complete(output)) or output.get('reviewRunInstanceId') != instance
                or output.get('artifactSha256') != artifact_hash or output.get('specSha256') != spec_hash
                or util.sha256_file(receipt_path) != output['browserCartEvidenceSha256']): return False
        receipt = util.read_json(receipt_path)
        if (receipt.get('runInstanceId') != instance or receipt.get('artifactSha256') != artifact_hash
                or receipt.get('specSha256') != spec_hash or receipt.get('actor') != 'agent'
                or (not allow_partial and sorted(r['checkId'] for r in receipt['removals']) != ['C-015', 'C-016'])): return False
        for removal in receipt['removals']:
            kinds = ['before', 'after', 'beforeScreenshot', 'afterScreenshot']
            kinds += [k for k in ('setupBefore', 'setupScreenshot') if removal.get(k)]
            for kind in kinds:
                ref = removal[kind]
                path = (review/ref['path']).resolve()
                if not path.is_relative_to(review.resolve()) or util.sha256_file(path) != ref['sha256']: return False
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False


def stored_failure(directory, instance, artifact_hash, spec_hash, evaluation_hash, *, baseline_directory=None):
    """Retain bound failures separately from incomplete browser coverage.

    A damaged browser receipt invalidates its own claims, but not independently
    bound HTTP failures. Never returns a pass or an incomplete numeric score.
    """
    try:
        directory = Path(directory)
        path = directory/'evaluation.json'
        if not evaluation_hash or util.sha256_file(path) != evaluation_hash:
            return None
        output = util.read_json(path)
        if (output.get('reviewRunInstanceId') != instance or output.get('artifactSha256') != artifact_hash
                or output.get('specSha256') != spec_hash):
            return None
        baseline = Path(baseline_directory) if baseline_directory else directory/'http-only'
        if (util.sha256_file(baseline/'evaluation.json') != output.get('baselineEvaluationSha256')
                or util.sha256_file(baseline/'results.jsonl') != output.get('baselineResultsSha256')):
            return None
        http = util.read_json(baseline/'evaluation.json')
        if http.get('artifactSha256') != artifact_hash or http.get('specSha256') != spec_hash:
            return None
        observed = stored_coverage_complete(directory, instance, artifact_hash, spec_hash, allow_partial=True)
        source = output if observed else http
        failed = [r['id'] for r in source.get('requirements', []) if r['judgement'] == 'fail']
        if failed:
            return {'verdict': 'fail_critical' if source.get('criticalFailed') else 'fail',
                    'requirements': failed, 'source': 'composed' if observed else 'http-only'}
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def compose_evaluation(condition, frozen, baseline, assets, out, instance, sequence, *, defer_cleanup=False):
    if defer_cleanup:
        return _compose_evaluation(condition, frozen, baseline, assets, out, instance, sequence)
    with ownership.lease(out):
        try:
            code = _compose_evaluation(condition, frozen, baseline, assets, out, instance, sequence)
        finally:
            cleanup = browser_cleanup.cleanup(out, locked=True)
        # Preserve an existing evaluator failure when cleanup also fails.
        return code if cleanup['confirmed'] or code != 0 else 3


def _compose_evaluation(condition, frozen, baseline, assets, out, instance, sequence):
    """Judge preserved real observations with the same composer as score_run."""
    frozen, baseline, assets, out = map(Path, (frozen, baseline, assets, out))
    work = out/'composition-work'; work.mkdir()
    image = condition['runtime_lock']['images']['evaluator']
    version = condition['evaluation']['evaluation_version']
    name, command = runtime.scoring_command(condition, frozen, out, work, assets, version, sequence)
    owner = browser_cleanup.register(out, instance, 'container', name)
    image_at = command.index(image)
    command[image_at:image_at] = ['--label', 'sample2.browser-review=' + owner, *runtime.mount(baseline, '/baseline', True)]
    command += ['--browser-cart-baseline', '/baseline', '--browser-cart-evidence', '/result/browser-cart/receipt.json',
                '--review-run-instance-id', instance]
    evaluator_hash = util.sha256_file(assets/'evaluator'/condition['evaluation']['assembly'])
    util.write_new_json(out/'composition-intent.json', {'command': command, 'evaluator_sha256': evaluator_hash,
                        'model_called': False, 'observation_scope': ['C-015', 'C-016']})
    process = runtime.command(command, timeout=120, check=False)
    (out/'composition-stdout.log').write_text(process.stdout, encoding='utf-8')
    (out/'composition-stderr.log').write_text(process.stderr, encoding='utf-8')
    if not (out/'evaluation.json').is_file(): raise RuntimeError('Browser composition produced no evaluation')
    output = util.read_json(out/'evaluation.json')
    from .evaluate import check_mismatches
    mismatches = check_mismatches(output, condition, version, frozen, util.artifact_hash(frozen),
                                  assets/'requirements.json', util.sha256_file(assets/'requirements.json'))
    if output.get('reviewRunInstanceId') != instance: mismatches.append({'check': 'browser_run_instance'})
    if (output.get('browserCartEvidenceSha256') and
            output['browserCartEvidenceSha256'] != util.sha256_file(out/'browser-cart/receipt.json')):
        mismatches.append({'check': 'browser_receipt'})
    reported = util.read_json(out/'evaluator-manifest.json') if (out/'evaluator-manifest.json').exists() else {}
    if reported.get('evaluatorSha256') != evaluator_hash: mismatches.append({'check': 'evaluator_build'})
    if mismatches:
        util.write_new_json(out/'mismatches.json', mismatches)
        return 2
    return process.returncode


def complete_evaluation(repo, condition, frozen, baseline, published, assets, out,
                        instance, sequence):
    Path(out).mkdir(parents=True, exist_ok=True)
    with ownership.lease(out):
        return _complete_evaluation(repo, condition, frozen, baseline, published, assets, out, instance, sequence)


def _complete_evaluation(repo, condition, frozen, baseline, published, assets, out,
                         instance, sequence):
    """Append a browser composition beside HTTP evidence; return evaluator exit code.

    This is the same entry point used by score_run and saved-corpus correction.
    Inputs are immutable; every invocation requires a new output directory.
    """
    repo, frozen, baseline, published, assets, out = map(Path, (repo, frozen, baseline, published, assets, out))
    out.mkdir(parents=True, exist_ok=True)
    if (out/'evaluation.json').exists() or (out/'browser-cart').exists():
        raise FileExistsError('Browser completion already attempted: ' + str(out))
    review = out/'browser-cart'; review.mkdir()
    state = out/'browser-state'; state.mkdir()
    name = 's2-browser-' + uuid.uuid4().hex
    network = name + '-net'
    container_created = baseline_bound = False
    code = 2
    image = condition['runtime_lock']['images']['evaluator']
    version = condition['evaluation']['evaluation_version']
    original = util.read_json(baseline/'evaluation.json')
    artifact_hash, spec_hash = util.artifact_hash(frozen), util.sha256_file(assets/'requirements.json')
    intent = {'run_instance_id': instance, 'artifact_sha256': artifact_hash, 'spec_sha256': spec_hash,
              'baseline_evaluation_id': original.get('evaluationId'),
              'baseline_evaluation_sha256': util.sha256_file(baseline/'evaluation.json'),
              'baseline_results_sha256': util.sha256_file(baseline/'results.jsonl'),
              'evaluator_sha256': util.sha256_file(assets/'evaluator'/condition['evaluation']['assembly']),
              'runtime_image': image, 'model_called': False, 'scope': ['C-015', 'C-016'],
              'actor': 'agent', 'human_review': 'not_run'}
    try:
        if (not instance or original.get('artifactSha256') != artifact_hash
                or original.get('specSha256') != spec_hash or original.get('evaluationVersion') != version
                or condition['evaluation']['spec_sha256'] != spec_hash):
            raise ValueError('Browser target/baseline identity mismatch')
        baseline_bound = True
        util.reject_links(published)
        configs = list(published.glob('*.runtimeconfig.json'))
        if len(configs) != 1:
            raise ValueError('Published application is missing or ambiguous')
        assembly = configs[0].name.removesuffix('.runtimeconfig.json') + '.dll'
        if not (published/assembly).is_file(): raise FileNotFoundError(assembly)
        published_hashes = util.tree_hashes(published)
        intent['published_files'] = published_hashes
        # Docker internal networks suppress published ports on this host. A
        # dedicated bridge without outbound masquerading retains loopback access.
        owner = browser_cleanup.register(out, instance, 'network', network)
        runtime.docker('network', 'create', '--opt', 'com.docker.network.bridge.enable_ip_masquerade=false',
                       '--label', 'sample2.browser-review=' + owner, network)
        browser_cleanup.register(out, instance, 'container', name)
        command = ['docker', 'run', '-d', '--name', name, '--label', 'sample2.browser-review=' + owner,
                   '--network', network, '--publish', '127.0.0.1::8080', *runtime.sandbox_args(),
                   *runtime.mount(published, '/app', True), *runtime.mount(state, '/data'),
                   '--workdir', '/app', '--env', 'ASPNETCORE_ENVIRONMENT=Production',
                   '--env', 'ConnectionStrings__MusicStoreEntities=Data Source=/data/store.sqlite',
                   image, 'dotnet', assembly, '--urls', 'http://0.0.0.0:8080']
        intent['launch_command'] = command
        # A failed docker run may still have created the named container.
        container_created = True
        runtime.command(command)
        port = runtime.docker('port', name, '8080/tcp').stdout.strip().split(':')[-1]
        base_url = 'http://127.0.0.1:' + str(int(port))
        intent['base_url'] = base_url
        deadline = time.monotonic() + 60
        ready = False
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(base_url + '/', timeout=2) as response:
                    ready = response.status == 200
                if ready: break
            except (OSError, TimeoutError): pass
            time.sleep(.25)
        if not ready: raise RuntimeError('Browser application did not become ready within 60 seconds')
        catalog = util.read_json(assets/'catalog.json')
        album = next(a for a in catalog['albums'] if a['albumId'] == 1)
        request = {'runInstanceId': instance, 'artifactSha256': artifact_hash, 'specSha256': spec_hash,
                   'baseUrl': base_url, 'albumId': album['albumId'], 'price': album['price']}
        util.write_new_json(review/'request.json', request)
        collector = repo/'inner/browser/cart-review.cjs'
        environment = child_environment({k: os.environ[k] for k in
            ('NODE_PATH', 'PLAYWRIGHT_BROWSERS_PATH', 'SAMPLE2_BROWSER_EXECUTABLE') if k in os.environ})
        browser_command = [os.environ.get('SAMPLE2_NODE', 'node'), str(collector.resolve()),
                           str((review/'request.json').resolve()), str(review.resolve())]
        intent['collector_command'] = browser_command
        intent['collector_sha256'] = util.sha256_file(collector)
        with (review/'stdout.log').open('xb') as stdout, (review/'stderr.log').open('xb') as stderr:
            # Same process-group cleanup used by the ordinary evaluator; no orphaned browser on timeout.
            from .evaluate import run_evaluator
            exit_code, timed_out = run_evaluator(browser_command, repo, environment, stdout, stderr, 150)
        if exit_code != 0 or timed_out or not (review/'receipt.json').is_file():
            raise RuntimeError('Browser collection incomplete; inspect browser-cart logs and collector-result.json')
        if util.tree_hashes(published) != published_hashes or util.artifact_hash(frozen) != artifact_hash:
            raise ValueError('Application or frozen artifact changed during browser observation')
        code = compose_evaluation(condition, frozen, baseline, assets, out, instance, sequence, defer_cleanup=True)
    except Exception as exc:
        util.write_new_json(out/'browser-fault.json', {'type': type(exc).__name__, 'message': str(exc), 'scoring_state': 'evaluator_fault'})
        # The composer retains verified HTTP failures even when the browser is
        # unavailable. It never promotes an HTTP-only pass to research acceptance.
        if not (out/'evaluation.json').exists():
            try:
                code = compose_evaluation(condition, frozen, baseline, assets, out, instance, sequence, defer_cleanup=True)
            except Exception as composition_error:
                fault = {**original, 'verdict': 'error', 'quality': None, 'researchStatus': 'incomplete',
                         'browserCartCoverage': 'evaluator_fault', 'browserCartEvidenceSha256': None,
                         'reviewRunInstanceId': instance, 'evaluatorFaults': [str(exc), str(composition_error)],
                         'baselineEvaluationSha256': intent['baseline_evaluation_sha256'],
                         'baselineResultsSha256': intent['baseline_results_sha256'],
                         'observationScope': 'Browser phase incomplete; saved HTTP failures remain in baseline'}
                if baseline_bound and original.get('verdict') in ('fail', 'fail_critical'):
                    fault['verdict'] = original['verdict']
                if not (out/'evaluation.json').exists(): util.write_new_json(out/'evaluation.json', fault)
        code = 2
    finally:
        util.write_new_json(out/'browser-intent.json', intent)
        try:
            if container_created:
                logs = runtime.docker('logs', name, check=False, timeout=30)
                (out/'browser-server.log').write_text(logs.stdout + logs.stderr, encoding='utf-8')
        except Exception as exc:
            intent['log_collection_error'] = str(exc)
        # Quality is already saved. A failed cleanup changes operational exit,
        # never product quality; retries use only this owned-resource manifest.
        if (out/'browser-resources.json').exists():
            cleanup = browser_cleanup.cleanup(out, locked=True)
        else:
            cleanup = {'confirmed': True, 'status': 'no_resources_created'}
        util.write_new_json(out/'browser-cleanup.json', cleanup)
    return code if cleanup['confirmed'] or code != 0 else 3
