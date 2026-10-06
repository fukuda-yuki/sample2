"""Audit coverage/construct limits and explicit misclassification sensitivity, without rescoring."""
import argparse
from common import *

def compute(d,audit_path):
    a=read(audit_path);registry={r['run_id']:r for r in d['runs']}
    if len(a['runs'])!=200 or {r['run_id'] for r in a['runs']}!=set(registry): raise ValueError('Audit cohort differs')
    groups={}
    for t in d['plan']['task_ids']:
        rr=[r for r in d['runs'] if r['task']==t];checks=[]
        for row in a['runs']:
            r=registry[row['run_id']]
            if r['task']!=t:continue
            if row['run_instance_id']!=r['run_instance_id'] or row['original_sequence']!=1 or row['original_identity_verified'] is not True:raise ValueError('Invalid first-evaluation identity')
            checks.extend(row['checks'])
        groups[t]={'assigned_runs':len(rr),'quality':quality(rr),
          'scoring':dict(sorted(Counter(r['scoring_state'] for r in rr).items())),
          'execution':dict(sorted(Counter(r['execution_state'] for r in rr).items())),
          'actual_evaluator_hashes':dict(sorted(Counter(r['evaluator_sha256'] for r in rr).items())),
          'check_observations':len(checks),'check_ids':len({c['check_id'] for c in checks}),
          'check_derived_states':dict(sorted(Counter(c['derived_state'] for c in checks).items())),
          'audit_dispositions':dict(sorted(Counter(c['audit_disposition'] for c in checks).items())),
          'independent_check_semantic_audits':sum(c['check_specific_semantic_audit_performed'] is True for c in checks),
          'product_violation_confirmed_checks':sum(c['product_violation_confirmed'] is True for c in checks),
          'quality_unknown_completed_runs':sum(r['full_pass'] is None and r['execution_state']=='completed' for r in rr)}
    q=quality(d['runs']);e,p=q['explore'],q['preload']
    return {'question':'Did the redesigned task/evaluation chain deliver an interpretable migration-quality comparison, and which uncertainty remains outside the reported missingness bounds?',
      'audit_input_sha256':sha(audit_path),'task_audit':groups,
      'fixed_evaluator_quality_difference_bounds':q['difference_bounds'],
      'measurement_stress':{'definition':'Hypothetically revoke rE/rP currently accepted automatic fullpass labels into unknown; confirmed violations preserved. No actual label changes.',
        'lower_bound_formula':'-0.50 - rP/100','upper_bound_formula':'+0.50 + rE/100',
        'max_revocable_E':e['pass'],'max_revocable_P':p['pass'],
        'all_automatic_pass_labels_untrusted_envelope':[-(e['pass']+e['unknown'])/100,(p['pass']+p['unknown'])/100],
        'not_a_falsepass_rate_estimate':True,'not_evidence_all_passes_wrong':True,
        'assumptions':'The two finite audited violations remain valid; no guaranteed independently semantically audited fullpass. Reported ±50pp bounds condition on validity of accepted automatic labels and declared finite contract.'},
      'claim_boundaries':{'cross_family_score_point_equivalence':False,'automated_pass_means_all_practical_migration_quality':False,
        'calibration_and_same_hash_means_exhaustive_validity':False,'noncompletion_means_product_failure':False},
      'decision':'Existing calibration/task controls establish finite information-dependence and apparatus feasibility. They do not establish complete or invariant quality measurement across all200 or old/new constructs. Prioritize finite dependency-aware measurement audit, preserve historical labels, and do not choose winning prompt from these bounds.'}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--data',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    execute('round3_measurement',__file__,a.data,a.out,lambda d:compute(d,Path(a.data)/'public-check-audit.json'))
