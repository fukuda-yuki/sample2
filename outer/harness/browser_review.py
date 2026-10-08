"""Dispatch mandatory browser contracts without changing historical cart meaning."""
from pathlib import Path
from collections import Counter
import re
from . import browser_cart, education_browser, util


def _for(version):
    return education_browser if education_browser.required(version) else browser_cart


def required(version):
    return _for(version).required(version)


def http_phase_eligible(condition, directory, *, exit_code, timed_out, cleanup_confirmed,
                        stopped, frozen, artifact_hash, spec, spec_hash, evaluator_hash):
    """Authorize only a next observation phase, never quality/adoption.

    Preserve historical mandatory-browser code-zero routing. The additional 1.6
    exit-two route requires a normal, bound HTTP result awaiting browser work.
    Known failures and HTTP unknown scope may coexist; neither is rewritten.
    Launchers and read-only reassessment validation share this exact boundary.
    """
    try:
        version=condition['evaluation']['evaluation_version'];directory=Path(directory)
        if (not required(version) or type(exit_code) is not int or timed_out is not False
                or cleanup_confirmed is not True or stopped is not False
                or not (directory/'evaluation.json').is_file()):return False
        # Music 1.6 normal HTTP exits two; zero must not bypass its binding gate.
        if exit_code==0:return version!='1.6.0'
        if version!='1.6.0' or exit_code!=2 or condition.get('schema_version')!=2:return False
        from . import evaluate
        config=condition['evaluation'];lock=condition['runtime_lock'];spec=Path(spec)
        if any(not isinstance(h,str) or not re.fullmatch('[0-9a-f]{64}',h)
               for h in (artifact_hash,spec_hash,evaluator_hash)):return False
        assembly=config['assembly']
        if Path(assembly).name!=assembly or not assembly.endswith('.dll'):return False
        bundle=spec.parent/'evaluator'
        if (config.get('evaluator_sha256')!=evaluator_hash or lock.get('evaluator_sha256')!=evaluator_hash
                or util.sha256_file(bundle/assembly)!=evaluator_hash
                or lock.get('evaluator_files')!=util.tree_hashes(bundle)
                or util.artifact_hash(frozen)!=artifact_hash or util.sha256_file(spec)!=spec_hash):return False
        ledger=util.read_json(spec);output=util.read_json(directory/'evaluation.json')
        manifest=util.read_json(directory/'evaluator-manifest.json')
        if (ledger.get('specVersion')!=version or ledger.get('taskId')!=condition.get('task_id')
                or output.get('specVersion')!=version
                or evaluate.check_mismatches(output,condition,version,frozen,artifact_hash,spec,spec_hash)
                or any(manifest.get(key)!=value for key,value in (
                    ('evaluationVersion',version),('evaluatorVersion',version),('evaluatorSha256',evaluator_hash),
                    ('artifactPath','/artifact'),('artifactSha256',artifact_hash),('specSha256',spec_hash)))):return False
        if (output.get('researchStatus')!='incomplete' or 'quality' not in output or output['quality'] is not None
                or type(output.get('evaluatorFaults')) is not list or output['evaluatorFaults']!=[]
                or type(output.get('uncheckedScope')) is not list
                or not all(isinstance(v,str) for v in output['uncheckedScope'])
                or output.get('browserCartCoverage')!='not_run_http_only'
                or type(output.get('browserCartCases')) is not dict or output['browserCartCases']!={}
                or any(key not in output or output[key] is not None for key in (
                    'browserCartEvidenceSha256','reviewRunInstanceId','baselineEvaluationSha256','baselineResultsSha256'))):return False
        # Explicit 1.6 ledger: no partial/duplicate output or guessed future contract.
        requirements=ledger['requirements'];expected={}
        if len(requirements)!=31 or {r['id'] for r in requirements}!={f'R-{n:03d}' for n in range(1,32)}:return False
        for row in requirements:
            for check in row['checks']:
                if check['id'] in expected:return False
                expected[check['id']]=row['id']
        if set(expected)!={f'C-{n:03d}' for n in range(1,34)}:return False
        for name in ('ledgerCheckIds','implementedCheckIds'):
            ids=manifest.get(name)
            if type(ids) is not list or len(ids)!=len(expected) or set(ids)!=set(expected):return False
        checks=util.read_lines(directory/'results.jsonl');observed={}
        if len(checks)!=len(expected):return False
        for check in checks:
            cid=check['checkId']
            if (cid in observed or expected.get(cid)!=check.get('requirementId')
                    or check.get('judgement') not in ('pass','fail','blocked')
                    or type(check.get('observationFaults')) is not list or check['observationFaults']!=[]
                    or type(check.get('unknownObservations')) is not list
                    or not all(isinstance(v,str) for v in check['unknownObservations'])):return False
            observed[cid]=check
        reported=output['requirements']
        if (type(reported) is not list or len(reported)!=len(requirements)
                or {r['id'] for r in reported}!={r['id'] for r in requirements}):return False
        counts=Counter();critical=[]
        for row in reported:
            own=[observed[c] for c,r in expected.items() if r==row['id']]
            status='fail' if any(c['judgement']=='fail' for c in own) else 'blocked' if any(c['judgement']=='blocked' for c in own) else 'pass'
            if (row.get('judgement')!=status or type(row.get('failedChecks')) is not list
                    or sorted(row['failedChecks'])!=sorted(c['checkId'] for c in own if c['judgement']!='pass')):return False
            severity=next(r.get('severity') for r in requirements if r['id']==row['id'])
            if row.get('severity')!=severity:return False
            if status=='fail' and severity=='critical':critical.append(row['id'])
            counts[status]+=1
        for key,value in (('requirementCount',31),('passedCount',counts['pass']),('failedCount',counts['fail']),
                          ('blockedCount',counts['blocked']),('errorCount',0)):
            if type(output.get(key)) is not int or output[key]!=value:return False
        if type(output.get('criticalFailed')) is not list or sorted(output['criticalFailed'])!=sorted(critical):return False
        verdict='fail_critical' if critical else 'fail' if counts['fail'] else 'blocked'
        return output.get('verdict')==verdict
    except (OSError,ValueError,KeyError,TypeError,AttributeError):return False


def coverage_complete(output):
    return _for(output.get('evaluationVersion')).coverage_complete(output)


def complete_evaluation(repo, condition, *args, **kwargs):
    return _for(condition['evaluation']['evaluation_version']).complete_evaluation(repo, condition, *args, **kwargs)


def _stored(directory):
    try:
        return _for(util.read_json(Path(directory)/'evaluation.json').get('evaluationVersion'))
    except (OSError, ValueError):
        return browser_cart


def execution_identity(directory):
    return _stored(directory).execution_identity(directory)


def stored_coverage_complete(directory, *args, **kwargs):
    return _stored(directory).stored_coverage_complete(directory, *args, **kwargs)


def stored_failure(directory, *args, **kwargs):
    return _stored(directory).stored_failure(directory, *args, **kwargs)
