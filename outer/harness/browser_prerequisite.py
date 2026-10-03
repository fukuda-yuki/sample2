"""Record an evaluator-confirmed product prerequisite without inventing a fault."""
from pathlib import Path
import shutil

from . import util


def save_if_unpublished(condition, frozen, baseline, published, assets, out, instance,
                        *, version, requirement_id, build_check, coverage_field):
    """Only adapters with an explicit version/check contract may skip the browser.

    This copies a bound evaluator judgement. It does not diagnose publish errors,
    infer quality from a missing file, or turn observer failures into product fails.
    """
    from .evaluate import check_mismatches
    frozen, baseline, published, assets, out = map(Path, (frozen, baseline, published, assets, out))
    original = util.read_json(baseline/'evaluation.json')
    spec = assets/'requirements.json'
    if (not instance or condition['evaluation']['evaluation_version'] != version
            or original.get('evaluatorFaults')
            or check_mismatches(original, condition, version, frozen, util.artifact_hash(frozen),
                                spec, util.sha256_file(spec))):
        return False
    manifest = util.read_json(baseline/'evaluator-manifest.json')
    if manifest.get('evaluatorSha256') != util.sha256_file(assets/'evaluator'/condition['evaluation']['assembly']):
        return False
    requirements = [r for r in original.get('requirements', []) if r.get('id') == requirement_id]
    checks = [r for r in util.read_lines(baseline/'results.jsonl') if r.get('checkId') == build_check]
    if (len(requirements) != 1 or requirements[0].get('judgement') != 'fail'
            or len(checks) != 1 or checks[0].get('requirementId') != requirement_id
            or checks[0].get('judgement') != 'fail'):
        return False
    util.reject_links(published)
    configs = list(published.glob('*.runtimeconfig.json'))
    if len(configs) == 1 and (published/(configs[0].name.removesuffix('.runtimeconfig.json')+'.dll')).is_file():
        return False
    evaluation_hash, results_hash = util.sha256_file(baseline/'evaluation.json'), util.sha256_file(baseline/'results.jsonl')
    util.write_new_json(out/'browser-product-prerequisite.json', {
        'run_instance_id': instance, 'artifact_sha256': original['artifactSha256'],
        'spec_sha256': original['specSha256'], 'evaluation_version': version,
        'evaluator_sha256': manifest['evaluatorSha256'], 'baseline_evaluation_sha256': evaluation_hash,
        'baseline_results_sha256': results_hash, 'requirement_id': requirement_id, 'build_check': build_check,
        'status': 'not_run_product_prerequisite', 'published_application_established': False,
        'model_called': False, 'browser_observed': False,
        'scope': 'Bound evaluator build failure and no published entry application; remaining browser checks unobserved'})
    output = {**original, 'quality': None, 'researchStatus': 'incomplete',
              coverage_field: 'not_run_product_prerequisite', 'reviewRunInstanceId': instance,
              'baselineEvaluationSha256': evaluation_hash, 'baselineResultsSha256': results_hash,
              'evaluatorFaults': []}
    output['browserReviewEvidenceSha256' if coverage_field == 'browserReviewCoverage' else 'browserCartEvidenceSha256'] = None
    util.write_new_json(out/'evaluation.json', output)
    shutil.copyfile(baseline/'evaluator-manifest.json', out/'evaluator-manifest.json')
    return True
