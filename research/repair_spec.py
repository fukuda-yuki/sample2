"""Explicit new measurement ledger; never overwrite an old frozen ledger.

Public task/source contracts retain their original identities. Only the new
measurement version, disclosed interpretation and stale descriptive text change.
"""
import argparse
import copy
import json
from pathlib import Path

from outer.harness import util
from .saved_reassessment import requirement_inventory


def revised(original):
    result = copy.deepcopy(original)
    old = result['specVersion']
    if old == 'education-1.0.0':
        result['specVersion'] = 'education-1.1.0'
        changes = [
            'SQLite Students.EnrollmentDate and Departments.StartDate compare calendar values: '
            'YYYY-MM-DD or exactly midnight YYYY-MM-DD HH:mm:ss / YYYY-MM-DDTHH:mm:ss '
            'with optional zero-only fractional seconds; '
            'invalid dates, other times, offsets, timezones and arbitrary coercions are rejected.',
            'Visible date markers must remain exactly YYYY-MM-DD; DB equivalence does not relax UI.',
            'Create identity is the unique database post-minus-pre ID, never a matching name.',
            'Owned operation HTTP500 is a finite product failure; downstream unobserved operations '
            'and independent observer failures remain partial coverage with no complete quality.'
        ]
    elif old == '1.3.0':
        result['specVersion'] = '1.4.0'
        by_id = {r['id']: r for r in result['requirements']}
        by_id['R-013']['basisDetail'] = ('ShoppingCart total is the sum of quantity times source-defined '
            'effective unit price, rounded per unit to cents. Variant prices are frozen independently '
            'in catalog.json/migration-oracle.json; no universal 8.99 assumption applies.')
        texts = {'C-014': 'Three copies of album 1 display 3 * its independently frozen effective unit price.',
            'C-015': 'Ordinary removal from quantity 2 leaves one line of quantity 1 and total equal '
                'to that album\'s independently frozen effective unit price; visible Cart (N) updates.',
            'C-017': 'Two copies of album 1 and one copy of album 2 produce two lines, quantity 3, '
                'and total 2 * effectivePrice(1) + effectivePrice(2).'}
        for req in result['requirements']:
            for check in req['checks']:
                if check['id'] in texts: check['observation'] = texts[check['id']]
        result['knownLimits'] = [x for x in result.get('knownLimits', [])
            if not (x.startswith('C-006（') or x.startswith('注文合計（Order.Total）'))]
        result['knownLimits'].append('C-031 uses read-only SQLite to observe specified original rows '
            'and checkout quantities/unit prices/Order.Total at declared restart stages; '
            'this is finite coverage, not all database operations or universal persistence.')
        changes = ['Legacy names in data folders/comments are mentions, not actual dependencies. '
            'Actual project/assembly/launch evidence is required; unreadable/unresolved scans stay unknown.',
            'Source-derived effective prices replace stale fixed-price descriptions; check IDs, '
            'severities, original requirement inventory and frozen source/oracle assets are unchanged.',
            'Owned operation HTTP500 preserves a finite product failure independently of observer faults; '
            'unperformed removals remain unknown and cannot yield complete quality.']
    else:
        raise ValueError('Only the original frozen Education1.0/Music1.3 ledgers are supported')
    result['measurementRevision'] = {'sourceSpecVersion': old,
        'scope': 'new evaluation of same saved artifact, not historical labels or new acquisition',
        'changes': changes, 'humanReview': 'not_run'}
    if requirement_inventory(original) != requirement_inventory(result):
        raise AssertionError('Requirement inventory changed')
    return result


def write(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination: raise ValueError('Old ledger cannot be overwritten')
    original = util.read_json(source)
    util.write_new_json(destination, revised(original))
    return util.sha256_file(destination)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source'); parser.add_argument('destination')
    args = parser.parse_args()
    print(write(args.source, args.destination))
