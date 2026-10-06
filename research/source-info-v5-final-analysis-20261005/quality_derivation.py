"""Derive separate binary endpoints from an explicitly audited check table.

This does not audit raw evidence, run an evaluator, or convert verdict text.
The exporter must first verify original seq1 identities and evidence bindings,
then retain its check decisions, references, uncertainties and public omissions.
"""
from collections import Counter

RULE_VERSION = 'evidence_linked_required_check_tristate_v2'
FROZEN_SEVERITIES = {'critical', 'major', 'minor', 'normal'}
STATES = {'pass', 'product_failure', 'unobserved', 'observer_fault',
          'identity_invalid', 'unsupported', 'ambiguous'}


def derive(required_checks, audit):
    expected = {(c['requirement_id'], c['check_id']): c for c in required_checks}
    if not expected or len(expected) != len(required_checks):
        raise ValueError('The exact nonempty frozen required-check ledger is needed')
    actual = {(c['requirement_id'], c['check_id']): c for c in audit['checks']}
    if len(actual) != len(audit['checks']) or set(actual) != set(expected):
        raise ValueError('Every frozen required check must appear exactly once')
    if type(audit.get('original_sequence')) is not int or audit['original_sequence'] != 1:
        raise ValueError('Only the original first evaluation is allowed')
    if not audit.get('original_evidence_references'):
        raise ValueError('Original evaluation references must remain even when unknown')
    for key, check in actual.items():
        if check['severity'] != expected[key]['severity']:
            raise ValueError('Severity must come from the frozen ledger')
        if check['severity'] not in FROZEN_SEVERITIES:
            raise ValueError('Unexpected frozen severity needs explicit rule review')
        state = check['derived_state']
        if state not in STATES or not check.get('reason') or not check.get('evidence_references'):
            raise ValueError('Every audit state requires an explicit reason and references')
        if state in {'pass', 'product_failure'}:
            if audit.get('original_identity_verified') is not True or check.get('identity_verified') is not True:
                raise ValueError('Invalid/mismatched identity cannot support a known endpoint')
            if check.get('evidence_valid') is not True:
                raise ValueError('Known endpoint requires valid check-specific evidence')
        if state == 'pass' and (check.get('original_judgement') != 'pass'
                                or check.get('observation_complete') is not True):
            raise ValueError('Pass requires an actual complete passed check observation')
        if state == 'product_failure' and (check.get('original_judgement') != 'fail'
                                          or check.get('product_violation_confirmed') is not True):
            raise ValueError('A failed/blocked raw judgement alone is not confirmed product violation')
    checks = list(actual.values())
    failed = [c for c in checks if c['derived_state'] == 'product_failure']
    critical = [c for c in checks if c['severity'] == 'critical']
    if not critical:
        raise ValueError('Frozen tasks require at least one critical check')
    critical_failed = [c for c in failed if c['severity'] == 'critical']
    full_pass = 0 if failed else 1 if all(c['derived_state'] == 'pass' for c in checks) else None
    critical_failure = 1 if critical_failed else 0 if all(c['derived_state'] == 'pass' for c in critical) else None
    def ids(items):
        return sorted(f"{c['requirement_id']}/{c['check_id']}" for c in items)
    return {'rule_version': RULE_VERSION, 'full_pass': full_pass,
            'critical_failure': critical_failure,
            'confirmed_product_failure_checks': ids(failed),
            'confirmed_critical_failure_checks': ids(critical_failed),
            'unknown_required_checks': ids([c for c in checks if c['derived_state'] not in {'pass', 'product_failure'}]),
            'derived_check_state_counts': dict(sorted(Counter(c['derived_state'] for c in checks).items())),
            'raw_numeric_quality_imputed': False,
            'declared_public_check_evidence_complete': all(c.get('public_evidence_complete') is True for c in checks),
            'declared_public_chain_and_rule_complete': all(audit.get(k) is True for k in
                ('original_identity_chain_public', 'frozen_ledger_public', 'derivation_rule_public')),
            'public_independent_quality_audit_performed': False,
            'recalculation_of_this_derivation_is_raw_evidence_reaudit': False}
