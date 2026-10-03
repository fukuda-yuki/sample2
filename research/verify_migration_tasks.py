"""Independent HTTP/SQLite compatibility workflow; no models, no Docker.

Execute one A reference, one B reference and one A-fixed-on-B negative control.
Expected quantities and amounts are taken from manually derived assertions,
not the implementation, and independently recomputed with Decimal.
"""
import argparse
import http.cookiejar
import http.client
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import closing
from pathlib import Path

from . import migration_tasks as tasks


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Session:
    def __init__(self, base):
        self.base = base
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()), NoRedirect())
        self.transcript = []

    def request(self, path, fields=None):
        data = None if fields is None else urllib.parse.urlencode(fields).encode()
        req = urllib.request.Request(self.base + path, data=data)
        try:
            response = self.opener.open(req, timeout=10)
        except urllib.error.HTTPError as error:
            response = error
        result = {'path': path, 'status': response.code,
                  'location': response.headers.get('Location'),
                  'body': response.read().decode('utf-8')}
        self.transcript.append(result)
        return result


def fields(**changes):
    value = dict(FirstName='Ada', LastName='Lovelace', Address='1 Analytical Way',
                 City='London', State='LDN', PostalCode='10001', Country='UK',
                 Phone='555-0100', Email='ada@example.invalid', PromoCode='fReE')
    value.update(changes)
    return value


def scalar(database, sql, params=()):
    with closing(sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True)) as connection:
        return connection.execute(sql, params).fetchone()[0]


def money_in(body):
    match = re.search(r'id=[\"\']cart-total[\"\'][^>]*>\s*([0-9.]+)', body)
    return match.group(1) if match else None


def rows_in(body):
    result = []
    for row in re.finditer(r'<tr\s+id=[\"\']row-(\d+)[\"\'][^>]*>(.*?)</tr>', body, re.S):
        album = re.search(r'/Store/Details/(\d+)', row.group(2))
        count = re.search(r'item-count-\d+[\"\'][^>]*>\s*(\d+)', row.group(2))
        if album and count:
            result.append({'id': int(row.group(1)), 'album': int(album.group(1)), 'quantity': int(count.group(1))})
    return result


def launch(published, database, output):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    base = f'http://127.0.0.1:{port}'
    allowed = {'PATH', 'PATHEXT', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'TEMP', 'TMP',
               'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'PROGRAMFILES', 'PROGRAMFILES(X86)',
               'PROGRAMW6432', 'DOTNET_ROOT', 'DOTNET_ROOT_X64'}
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    env.update(ConnectionStrings__MusicStoreEntities='Data Source=' + str(database.resolve()),
               DOTNET_CLI_TELEMETRY_OPTOUT='1', DOTNET_NOLOGO='1', ASPNETCORE_ENVIRONMENT='Production')
    log = output.open('wb')
    process = subprocess.Popen(['dotnet', str(published / 'MusicStore.Continuity.dll'), '--urls', base],
            cwd=published, env=env, stdout=log, stderr=subprocess.STDOUT)
    tasks.write_json(output.with_suffix('.process.json'), {'pid': process.pid, 'base_url': base,
            'published_root': str(published), 'database': str(database), 'credential_environment_passed': False})
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            log.close()
            raise RuntimeError('Reference startup failed; inspect ' + str(output))
        try:
            if urllib.request.urlopen(base, timeout=1).code == 200:
                return process, log, base
        except (urllib.error.URLError, TimeoutError, http.client.HTTPException):
            time.sleep(.2)
    process.kill()
    process.wait(timeout=20)
    log.close()
    raise TimeoutError('Reference startup timed out')


def stop(process, log):
    if process is not None and process.poll() is None:
        process.kill()
        process.wait(timeout=20)
    if log:
        log.close()


def order_evidence(database, order_id, workflow):
    with closing(sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True)) as connection:
        total = connection.execute('SELECT Total FROM Orders WHERE OrderId=?', (order_id,)).fetchone()[0]
        details = connection.execute('SELECT AlbumId,Quantity,UnitPrice FROM OrderDetails WHERE OrderId=? ORDER BY AlbumId', (order_id,)).fetchall()
    expected = [(int(i), q, workflow['unit_prices'][i]) for i, q in workflow['album_quantities'].items()]
    return {'order_id': order_id, 'total': total, 'details': details,
            'expected_total': workflow['total'], 'expected_details': expected,
            'matches': total == workflow['total'] and details == expected}


def execute_case(repo, name, published, destination, expected_pass=True):
    start = time.monotonic()
    destination.mkdir(parents=True, exist_ok=False)
    assets = repo / 'artifacts' / tasks.ASSET_NAMESPACE / ('MS1-CONT-' + name) / 'evaluation'
    oracle = tasks.read_json(assets / 'migration-oracle.json')
    database = destination / 'store.sqlite'
    shutil.copy2(assets / 'initial-store.sqlite', database)
    saved_input_hash = tasks.sha256(assets / 'initial-store.sqlite')
    checks = {}
    process = log = None
    sessions = []
    try:
        process, log, base = launch(published, database, destination / 'startup.log')
        checks['preserved_on_start'] = not tasks.compare_existing(database, oracle)
        session = Session(base)
        sessions.append(session)
        for album in (1, 1, 2):
            session.request('/ShoppingCart/AddToCart/' + str(album))
        cart = session.request('/ShoppingCart')
        expected = oracle['workflow']['checkout']
        checks['quantity_and_nonuniform_total'] = sorted((x['album'], x['quantity']) for x in rows_in(cart['body'])) == [(1, 2), (2, 1)] and money_in(cart['body']) == expected['total']
        before = tasks.snapshot_tables(database)
        invalid = session.request('/Checkout/AddressAndPayment', fields(PromoCode='WRONG'))
        checks['invalid_promo_no_mutation'] = invalid['status'] == 200 and tasks.snapshot_tables(database) == before
        invalid = session.request('/Checkout/AddressAndPayment', fields(Email=''))
        checks['missing_email_no_mutation'] = invalid['status'] == 200 and tasks.snapshot_tables(database) == before
        response = session.request('/Checkout/AddressAndPayment', fields())
        if response['status'] != 302:
            raise ValueError('Valid checkout did not redirect')
        order_id = int(response['location'].rsplit('/', 1)[1])
        complete = session.request(response['location'])
        checks['order_marker'] = complete['status'] == 200 and re.search(r'order-number[\"\'][^>]*>\s*' + str(order_id), complete['body']) is not None
        first_order = order_evidence(database, order_id, expected)
        checks['persisted_amount_quantity_and_unit_price'] = first_order['matches']
        checks['new_id_preserves_old_ids'] = order_id > 7001 and not tasks.compare_existing(database, oracle)
        checks['purchasing_cart_empty'] = not rows_in(session.request('/ShoppingCart')['body'])
        other = Session(base)
        sessions.append(other)
        checks['other_session_cannot_complete'] = other.request(response['location'])['status'] in (403, 404)
        for _ in range(2):
            other.request('/ShoppingCart/AddToCart/1')
        old_cart = other.request('/ShoppingCart')
        record = rows_in(old_cart['body'])[0]['id']
        session.request('/ShoppingCart/RemoveFromCart', {'id': record})
        checks['foreign_cart_removal_no_mutation'] = old_cart['body'] == other.request('/ShoppingCart')['body']
        removed = other.request('/ShoppingCart/RemoveFromCart', {'id': record})
        value = json.loads(removed['body'])
        checks['remove_two_to_one'] = value.get('itemCount', value.get('ItemCount')) == 1
        removed = other.request('/ShoppingCart/RemoveFromCart', {'id': record})
        value = json.loads(removed['body'])
        checks['remove_one_to_zero'] = value.get('itemCount', value.get('ItemCount')) == 0 and not rows_in(other.request('/ShoppingCart')['body'])
        stop(process, log)
        process = log = None
        stopped_hash = tasks.sha256(database)
        checks['preserved_before_restart'] = not tasks.compare_existing(database, oracle)
        process, log, base = launch(published, database, destination / 'restart.log')
        checks['preserved_after_restart'] = not tasks.compare_existing(database, oracle)
        checks['completed_new_order_after_restart'] = order_evidence(database, order_id, expected)['matches']
        restarted = Session(base)
        sessions.append(restarted)
        restarted.request('/ShoppingCart/AddToCart/3')
        response = restarted.request('/Checkout/AddressAndPayment', fields())
        restarted_order_id = int(response['location'].rsplit('/', 1)[1])
        restart_order = order_evidence(database, restarted_order_id, oracle['workflow']['restart'])
        checks['restart_new_checkout_amount'] = restart_order['matches'] and restarted_order_id != order_id
        checks['all_existing_rows_after_all_operations'] = not tasks.compare_existing(database, oracle)
        evidence = {'first_order': first_order, 'restart_order': restart_order,
                    'database_sha256_before_restart': stopped_hash}
        stop(process, log)
        process = log = None
        fresh_database = destination / 'newpath-import.sqlite'
        process, log, base = launch(published, fresh_database, destination / 'newpath-import.log')
        checks['reference_newpath_import_all_existing_rows'] = fresh_database.exists() and not tasks.compare_existing(fresh_database, oracle)
    finally:
        stop(process, log)
        for index, session in enumerate(sessions):
            tasks.write_json(destination / f'http-{index}.json', session.transcript)
    passed = all(checks.values())
    result = {'schema_version': 1, 'variant': name, 'model_dispatches': 0,
              'human_review': 'not_run', 'checks': checks, 'product_pass': passed,
              'expected_product_pass': expected_pass, 'control_expectation_met': passed == expected_pass,
              'evidence': evidence, 'elapsed_seconds': round(time.monotonic() - start, 3),
              'preserved_source_input_sha256': saved_input_hash,
              'published_reference_files': tasks.hashes(published),
              'raw_files': tasks.hashes(destination)}
    tasks.write_json(destination / 'receipt.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--published-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    repo = args.repo.resolve()
    output = args.out.resolve()
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    cases = [('reference-A', 'A', 'published-A', True), ('reference-B', 'B', 'published-B', True),
             ('fixed-A-on-B', 'B', 'published-fixed', False)]
    results = [execute_case(repo, name, (args.published_root / published).resolve(), output / label, accepted)
               for label, name, published, accepted in cases]
    receipt = {'cases': results, 'finite_case_count': len(cases), 'model_dispatches': 0,
               'human_review': 'not_run', 'all_control_expectations_met': all(r['control_expectation_met'] for r in results),
               'semantic_necessity': tasks.semantic_necessity(repo),
               'executing_code_files': {path: tasks.sha256(repo / path) for path in
                       ['research/migration_tasks.py', 'research/verify_migration_tasks.py']},
               'reference_template_files': tasks.hashes(repo / 'inner/tasks/music-store-continuity/reference'),
               'claim_limit': 'One publicly available family with synthetic installations; legacy application not executed; no held-out independent source application. Reference fresh-path import is checked; ordinary generated-product scorer startup uses a prepopulated database.'}
    tasks.write_json(output / 'summary.json', receipt)
    print(json.dumps({'out': str(output), 'all_control_expectations_met': receipt['all_control_expectations_met'],
                     'product_pass': [r['product_pass'] for r in results]}))
    return 0 if receipt['all_control_expectations_met'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
