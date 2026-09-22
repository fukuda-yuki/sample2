"""Comparison-only handling of OpenCode 1.17.11's automatic environment date.

Never changes a request, source packet, clock, agent or saved evidence. Hashes of
raw files and canonical comparison objects have explicitly different names.
"""
from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path
import re

from research.catalog_allocation_review import read, sha256

RULE = 'opencode-1.17.11-system-environment-date-v1'
LEGACY_RULE = 'catalog-packet-only-v1'
MARKER = '<OPENCODE_AUTOMATIC_DATE>'
ENVIRONMENT = re.compile(
    r'(?m)^Here is some useful information about the environment you are running in:\n'
    r'<env>\n'
    r'  Working directory: /[^\r\n<>]*\n'
    r'  Workspace root folder: /[^\r\n<>]*\n'
    r'  Is directory a git repo: (?:yes|no)\n'
    r'  Platform: linux\n'
    r"  Today's date: (?P<date>(?:Sun|Mon|Tue|Wed|Thu|Fri|Sat) "
    r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) '
    r'(?:0[1-9]|[12][0-9]|3[01]) [0-9]{4})\n'
    r'</env>(?=\n|$)')
MONTHS = 'Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split()
WEEKDAYS = 'Mon Tue Wed Thu Fri Sat Sun'.split()


def object_hash(value):
    """SHA-256 of sorted, compact UTF-8 JSON, not of an original request file."""
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                     allow_nan=False).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def normalize_date(body):
    messages = body.get('messages')
    if (not isinstance(messages, list) or not messages or
            not all(isinstance(m, dict) for m in messages) or
            messages[0].get('role') != 'system' or
            sum(m.get('role') == 'system' for m in messages) != 1 or
            not isinstance(messages[0].get('content'), str)):
        raise ValueError('Expected exactly one leading string system message')
    content = messages[0]['content']
    if (content.count('<env>') != 1 or content.count('</env>') != 1 or
            content.count("Today's date:") != 1 or MARKER in content):
        raise ValueError('Missing, duplicate or already normalized system environment/date')
    matches = list(ENVIRONMENT.finditer(content))
    if len(matches) != 1:
        raise ValueError('Unexpected system environment structure or date format')
    match = matches[0]
    original = match['date']
    weekday, month, day, year = original.split()
    value = date(int(year), MONTHS.index(month) + 1, int(day))
    if WEEKDAYS[value.weekday()] != weekday:
        raise ValueError('System date weekday does not match its calendar date')
    result = deepcopy(body)
    start, end = match.span('date')
    result['messages'][0]['content'] = content[:start] + MARKER + content[end:]
    return result, {'text': original, 'iso_date': value.isoformat(),
                    'message_index': 0, 'role': 'system', 'field': "<env>/Today's date"}


def request(root):
    root = Path(root)
    first = json.loads((root / 'usage/raw/started.jsonl').read_text(encoding='utf-8').splitlines()[0])
    name = first['request_file']
    if Path(name).name != name or '/' in name or '\\' in name:
        raise ValueError('Initial request must be a local raw file')
    path = root / 'usage/raw' / name
    if sha256(path) != first['request_sha256']:
        raise ValueError('Original initial request hash mismatch')
    return read(path), {'path_within_run': 'usage/raw/' + name,
                        'original_file_sha256': sha256(path)}


def remove_packet(body, root):
    """Retain the existing packet-only comparison transformation exactly."""
    result = deepcopy(body)
    if read(Path(root) / 'condition.json')['intervention']['append_source_packet']:
        packet = (Path(root) / 'inputs/catalog-derived/raw-first.txt').read_bytes().decode('utf-8')
        for message in result['messages']:
            if isinstance(message.get('content'), str):
                message['content'] = message['content'].replace(packet, '')
            elif isinstance(message.get('content'), list):
                for part in message['content']:
                    if 'text' in part:
                        part['text'] = part['text'].replace(packet, '')
    return result


def compare_initial(actual_root, baseline_root, plan):
    revised = bool(plan.get('date_revision'))
    if revised and plan['date_revision'].get('rule') != RULE:
        raise ValueError('Unknown input identity revision')
    if revised:
        starts = Path(actual_root) / 'usage/raw/started.jsonl'
        if not starts.exists() or not starts.read_bytes().strip():
            # An absent request remains unobserved, never a normalized match.
            # Do not turn an otherwise recorded failed Run into an exception.
            return None
    actual, actual_file = request(actual_root)
    baseline, baseline_file = request(baseline_root)
    left, right = remove_packet(actual, actual_root), remove_packet(baseline, baseline_root)
    result = {'rule': RULE if revised else LEGACY_RULE,
              'hash_encoding': 'sorted compact UTF-8 JSON for comparison objects only',
              'actual_request': actual_file, 'baseline_request': baseline_file,
              'raw_common_equal': left == right,
              'actual_common_object_sha256': object_hash(left),
              'baseline_common_object_sha256': object_hash(right)}
    if not revised:
        return {**result, 'matches': left == right}
    # Changes in the source packet or access receipt cannot be hidden by the
    # inherited intervention removal, even if request + packet are edited together.
    packet = Path('inputs/catalog-derived/raw-first.txt')
    result['source_packet_equal'] = (Path(actual_root) / packet).read_bytes() == (Path(baseline_root) / packet).read_bytes()
    result['access_equal'] = read(Path(actual_root) / 'state/catalog-access.json') == read(Path(baseline_root) / 'state/catalog-access.json')
    try:
        normalized_actual, actual_date = normalize_date(left)
        normalized_baseline, baseline_date = normalize_date(right)
        result.update(actual_date=actual_date, baseline_date=baseline_date,
                      date_text_equal=actual_date['text'] == baseline_date['text'],
                      actual_normalized_object_sha256=object_hash(normalized_actual),
                      baseline_normalized_object_sha256=object_hash(normalized_baseline),
                      normalized_equal=normalized_actual == normalized_baseline,
                      structure_valid=True)
    except (ValueError, KeyError, TypeError) as exc:
        result.update(structure_valid=False, normalized_equal=False, validation_error=str(exc))
    result['matches'] = bool(result['normalized_equal'] and result['source_packet_equal'] and result['access_equal'])
    return result
