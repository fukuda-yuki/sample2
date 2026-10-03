"""Finite, no-model migration apparatus; synthetic installation, independent oracle.

Never reads old Runs and never dispatches a model. Output directories are new.
The pricing assertions are manually specified in variants.json, independently
recomputed with Python Decimal, then exercised against compiled .NET code.
"""
import argparse
import copy
import hashlib
import json
import shutil
import sqlite3
import subprocess
from contextlib import closing
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

SOURCE_COMMIT = '2967afb9d69488641df0d154e2ad5827a7820e71'
FAMILY = 'music-store-continuity'
ASSET_NAMESPACE = 'migration-assets-v2'
TABLE_KEYS = {'Genres': 'GenreId', 'Artists': 'ArtistId', 'Albums': 'AlbumId',
              'Customers': 'CustomerId', 'Carts': 'RecordId',
              'Orders': 'OrderId', 'OrderDetails': 'OrderDetailId'}
SCHEMA = '''
PRAGMA foreign_keys=ON;
CREATE TABLE Genres(GenreId INTEGER PRIMARY KEY AUTOINCREMENT, Name TEXT NOT NULL, Description TEXT NOT NULL);
CREATE TABLE Artists(ArtistId INTEGER PRIMARY KEY AUTOINCREMENT, Name TEXT NOT NULL);
CREATE TABLE Albums(AlbumId INTEGER PRIMARY KEY AUTOINCREMENT,Title TEXT NOT NULL,GenreId INTEGER NOT NULL REFERENCES Genres(GenreId),ArtistId INTEGER NOT NULL REFERENCES Artists(ArtistId),Price TEXT NOT NULL,AlbumArtUrl TEXT);
CREATE TABLE Customers(CustomerId INTEGER PRIMARY KEY,Username TEXT UNIQUE NOT NULL,Email TEXT,DisplayName TEXT);
CREATE TABLE Carts(RecordId INTEGER PRIMARY KEY AUTOINCREMENT,AlbumId INTEGER NOT NULL REFERENCES Albums(AlbumId),CartId TEXT NOT NULL,Count INTEGER NOT NULL,DateCreated TEXT NOT NULL);
CREATE TABLE Orders(OrderId INTEGER PRIMARY KEY AUTOINCREMENT,OrderDate TEXT,Username TEXT,FirstName TEXT,LastName TEXT,Address TEXT,City TEXT,State TEXT,PostalCode TEXT,Country TEXT,Phone TEXT,Email TEXT,Total TEXT,CustomerId INTEGER REFERENCES Customers(CustomerId));
CREATE TABLE OrderDetails(OrderDetailId INTEGER PRIMARY KEY AUTOINCREMENT,OrderId INTEGER NOT NULL REFERENCES Orders(OrderId),AlbumId INTEGER NOT NULL REFERENCES Albums(AlbumId),Quantity INTEGER NOT NULL,UnitPrice TEXT NOT NULL);
'''


def asset_dir(repo):
    return Path(repo) / 'research/tasks' / FAMILY


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def hashes(root):
    root = Path(root)
    return {p.relative_to(root).as_posix(): sha256(p)
            for p in sorted(root.rglob('*')) if p.is_file()}


def variant(repo, name):
    return read_json(asset_dir(repo) / 'variants.json')['variants'][name]


def current_price(raw, rate):
    # ROUND_HALF_UP is decimal midpoint away from zero for positive catalog prices.
    return (Decimal(str(raw)) * Decimal(rate)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def money(value):
    return format(Decimal(value), '.2f')


def raw_catalog(repo, name):
    data = copy.deepcopy(read_json(Path(repo) / 'inner/spec/catalog.json'))
    overrides = variant(repo, name)['raw_prices']
    for album in data['albums']:
        if str(album['albumId']) in overrides:
            album['price'] = float(overrides[str(album['albumId'])])
    return data


def expected_catalog(repo, name):
    data = raw_catalog(repo, name)
    rate = variant(repo, name)['pricing_rate']
    for album in data['albums']:
        album['price'] = float(current_price(album['price'], rate))
    return data


def independently_check_arithmetic(repo, name):
    definition = variant(repo, name)
    workflows = {'checkout': {1: 2, 2: 1}, 'second': {2: 1}, 'restart': {3: 1}}
    receipts = {}
    for operation, quantities in workflows.items():
        expected = definition['independently_derived_workflows'][operation]
        prices = {str(i): money(current_price(definition['raw_prices'][str(i)],
                                           definition['pricing_rate'])) for i in quantities}
        total = money(sum(Decimal(prices[str(i)]) * q for i, q in quantities.items()))
        if prices != expected['unit_prices'] or total != expected['total']:
            raise ValueError('Manually specified arithmetic and independent Decimal disagree')
        receipts[operation] = {'album_quantities': {str(k): v for k, v in quantities.items()},
                               'unit_prices': prices, 'total': total}
    historical = sum(Decimal(x['UnitPrice']) * x['Quantity'] for x in definition['historical_details'])
    if money(historical) != definition['historical_order']['Total']:
        raise ValueError('Historical header total conflicts with its immutable details')
    return receipts


def insert(connection, table, row):
    names = list(row)
    sql = 'INSERT INTO "' + table + '" (' + ','.join('"' + n + '"' for n in names) + ') VALUES (' + ','.join('?' for _ in names) + ')'
    connection.execute(sql, [row[n] for n in names])


def create_initial_database(repo, name, destination):
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(destination)
    definition = variant(repo, name)
    catalog = raw_catalog(repo, name)
    with closing(sqlite3.connect(destination)) as connection, connection:
        connection.executescript(SCHEMA)
        genre_ids = {g: i + 1 for i, g in enumerate(catalog['genres'])}
        artist_ids = {a: i + 1 for i, a in enumerate(catalog['artists'])}
        for g, i in genre_ids.items():
            insert(connection, 'Genres', {'GenreId': i, 'Name': g, 'Description': g})
        for a, i in artist_ids.items():
            insert(connection, 'Artists', {'ArtistId': i, 'Name': a})
        for a in catalog['albums']:
            insert(connection, 'Albums', {'AlbumId': a['albumId'], 'Title': a['title'],
                    'GenreId': genre_ids[a['genre']], 'ArtistId': artist_ids[a['artist']],
                    'Price': money(str(a['price'])), 'AlbumArtUrl': a['albumArtUrl']})
        insert(connection, 'Customers', {'CustomerId': 301, 'Username': 'archival-ada',
                'Email': 'ada@example.invalid', 'DisplayName': 'Ada Archived'})
        insert(connection, 'Carts', {'RecordId': 5001, 'AlbumId': 41, 'CartId': 'retained-cart',
                'Count': 3, 'DateCreated': '2020-01-02T03:04:05Z'})
        old = definition['historical_order']
        insert(connection, 'Orders', {'OrderId': old['OrderId'], 'OrderDate': '2020-02-03T04:05:06Z',
                'Username': old['Username'], 'FirstName': 'Ada', 'LastName': 'Archived',
                'Address': '10 Historical Lane', 'City': 'London', 'State': 'LDN', 'PostalCode': '10001',
                'Country': 'UK', 'Phone': '555-0301', 'Email': 'ada@example.invalid',
                'Total': old['Total'], 'CustomerId': old['CustomerId']})
        for detail in definition['historical_details']:
            insert(connection, 'OrderDetails', detail)
        if connection.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('Initial business snapshot has broken relationships')


def snapshot_tables(database):
    with closing(sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        return {table: {'key': key, 'rows': [dict(r) for r in connection.execute(
                'SELECT * FROM "' + table + '" ORDER BY "' + key + '"')]}
                for table, key in TABLE_KEYS.items()}


def pricing_source(rate, namespace='MvcMusicStore.Models'):
    return f'''using System;
namespace {namespace}
{{
    public static class SourcePricingPolicy
    {{
        // This installation's operational rule. Never rewrite historical orders.
        public static decimal CurrentUnitPrice(decimal storedPrice, int albumId = 0)
        {{
            return decimal.Round(storedPrice * {rate}m, 2, MidpointRounding.AwayFromZero);
        }}
    }}
}}
'''


def find_original_source(repo):
    repo = Path(repo).resolve()
    local = repo / 'artifacts/sources' / SOURCE_COMMIT
    if local.is_dir():
        return local
    # Shared git directory gives a read-only fallback to the original checkout.
    common = subprocess.check_output(['git', 'rev-parse', '--git-common-dir'], cwd=repo,
                                    text=True).strip()
    common = (repo / common).resolve()
    fallback = common.parent / 'artifacts/sources' / SOURCE_COMMIT
    if not fallback.is_dir():
        raise FileNotFoundError('Prepare the pinned upstream source; no network fetch is performed here')
    return fallback


def prepare_assets(repo, name, original_source=None):
    repo = Path(repo).resolve()
    definition = variant(repo, name)
    root = repo / 'artifacts' / ASSET_NAMESPACE / definition['task_id']
    receipt = root / 'preparation.json'
    if receipt.exists():
        saved = read_json(receipt)
        if saved['files'] != {k: v for k, v in hashes(root).items() if k != 'preparation.json'}:
            raise ValueError('Prepared migration assets changed')
        if saved['definition_sha256'] != sha256(asset_dir(repo) / 'variants.json'):
            raise ValueError('Prepared migration definition changed; choose a new namespace')
        if saved['public_request_sha256'] != sha256(asset_dir(repo) / 'public-request.txt'):
            raise ValueError('Prepared public request changed; choose a new namespace')
        return root
    if root.exists():
        raise FileExistsError('Retain incomplete preparation and use a fresh output location')
    root.mkdir(parents=True)
    source = Path(original_source) if original_source else find_original_source(repo)
    copied = root / 'inputs/legacy-source'
    shutil.copytree(source, copied, ignore=shutil.ignore_patterns('.git', 'bin', 'obj'))
    models = copied / 'MvcMusicStore-Completed/MvcMusicStore/Models'
    # The controlled variants are explicit researcher overlays to one real family.
    (models / 'SourcePricingPolicy.cs').write_text(pricing_source(definition['pricing_rate']), encoding='utf-8')
    cart = models / 'ShoppingCart.cs'
    text = cart.read_text(encoding='utf-8-sig')
    old = '''decimal? total = (from cartItems in storeDB.Carts
                              where cartItems.CartId == ShoppingCartId
                              select (int?)cartItems.Count * cartItems.Album.Price).Sum();'''
    new = '''decimal? total = storeDB.Carts.Where(c => c.CartId == ShoppingCartId).ToList()
                .Sum(c => (decimal?)(c.Count * SourcePricingPolicy.CurrentUnitPrice(c.Album.Price)));'''
    if old not in text or text.count('item.Album.Price') != 2:
        raise ValueError('Pinned upstream pricing anchors changed')
    text = text.replace(old, new).replace('item.Album.Price', 'SourcePricingPolicy.CurrentUnitPrice(item.Album.Price)')
    cart.write_text(text, encoding='utf-8', newline='\n')
    project_file = models.parent / 'MvcMusicStore.csproj'
    project_text = project_file.read_text(encoding='utf-8-sig')
    anchor = '<Compile Include="Models\\ShoppingCart.cs" />'
    if project_text.count(anchor) != 1:
        raise ValueError('Pinned upstream project anchor changed')
    project_file.write_text(project_text.replace(anchor, anchor + '\n    <Compile Include="Models\\SourcePricingPolicy.cs" />'), encoding='utf-8', newline='\n')
    for relative, before, after in [
        ('Views/Store/Details.cshtml', 'Model.Price)', 'MvcMusicStore.Models.SourcePricingPolicy.CurrentUnitPrice(Model.Price))'),
        ('Views/ShoppingCart/Index.cshtml', '@item.Album.Price', '@MvcMusicStore.Models.SourcePricingPolicy.CurrentUnitPrice(item.Album.Price)')]:
        view = models.parent / relative
        content = view.read_text(encoding='utf-8-sig')
        if content.count(before) != 1:
            raise ValueError('Pinned upstream view pricing anchor changed')
        view.write_text(content.replace(before, after), encoding='utf-8', newline='\n')
    (copied / 'INSTALLATION-NOTE.txt').write_text(
        'This controlled installation adds Models/SourcePricingPolicy.cs and existing-business/initial-store.sqlite. '
        'Prices in Albums are stored catalog values; current display/cart/checkout uses SourcePricingPolicy. '
        'Historical Orders/OrderDetails are immutable. These synthetic operational assets are a researcher overlay '
        'to the pinned public tutorial, not a separate independent application.\n', encoding='utf-8')
    business = root / 'inputs/existing-business'
    business.mkdir()
    create_initial_database(repo, name, business / 'initial-store.sqlite')
    operational = copied / 'OperationalData'
    operational.mkdir()
    # Readable source data are permitted in both arms. This is the raw snapshot,
    # not an expectation: it contains no computed current-unit or workflow values.
    write_json(operational / 'existing-data.json', snapshot_tables(business / 'initial-store.sqlite'))
    evaluation = root / 'evaluation'
    evaluation.mkdir()
    shutil.copy2(business / 'initial-store.sqlite', evaluation / 'initial-store.sqlite')
    write_json(evaluation / 'catalog.json', expected_catalog(repo, name))
    workflows = independently_check_arithmetic(repo, name)
    oracle = {'schema_version': 1, 'task_id': definition['task_id'], 'family_id': FAMILY,
        'variant': name, 'human_review': 'not_run',
        'tables': snapshot_tables(evaluation / 'initial-store.sqlite'),
        'workflow': workflows, 'pricing': {'rate': definition['pricing_rate'], 'rounding': 'away_from_zero_cents'},
        'authority': [
            {'scope': 'existing rows', 'kind': 'preserved_input_snapshot', 'source': 'inputs/existing-business/initial-store.sqlite'},
            {'scope': 'current pricing', 'kind': 'source_rule', 'source': 'Models/SourcePricingPolicy.cs'},
            {'scope': 'workflow arithmetic', 'kind': 'manual_assertions_and_independent_decimal', 'source': 'research/tasks/music-store-continuity/variants.json'},
            {'scope': 'HTTP/SQLite operations', 'kind': 'public_contract', 'source': 'research/tasks/music-store-continuity/public-request.txt'}],
        'limitations': ['Legacy ASP.NET/SQL Server application not executed; compiled .NET compatibility reference is executed instead.',
                        'One family and two synthetic semantic variants; no independent held-out application.',
                        'Human oracle/workflow confirmation is not_run.']}
    write_json(evaluation / 'migration-oracle.json', oracle)
    write_json(receipt, {'schema_version': 1, 'task_id': definition['task_id'], 'family_id': FAMILY,
        'variant': name, 'base_source_commit': SOURCE_COMMIT,
        'source_tree_sha256': hashes(source), 'definition_sha256': sha256(asset_dir(repo) / 'variants.json'),
        'public_request_sha256': sha256(asset_dir(repo) / 'public-request.txt'),
        'model_dispatches': 0, 'human_review': 'not_run', 'files': hashes(root)})
    return root


def materialize_reference(repo, name, destination, fixed_variant=None, quote_style='double'):
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(destination)
    template = Path(repo) / 'inner/tasks' / FAMILY / 'reference/MusicStore.Continuity'
    shutil.copytree(template, destination / 'MusicStore.Continuity', ignore=shutil.ignore_patterns('bin', 'obj'))
    project = destination / 'MusicStore.Continuity'
    (project / 'Data').mkdir(exist_ok=True)
    rule_variant = fixed_variant or name
    (project / 'SourcePricingPolicy.cs').write_text(pricing_source(variant(repo, rule_variant)['pricing_rate'],
                                              namespace='MusicStore.Minimal'), encoding='utf-8')
    # Fixed control uses A's effective values even with B's existing database.
    if fixed_variant:
        values = {int(a['albumId']): a['price'] for a in expected_catalog(repo, fixed_variant)['albums']}
        replacements = ', '.join(f'[{k}] = {money(str(v))}m' for k, v in values.items())
        text = '''namespace MusicStore.Minimal;
public static class SourcePricingPolicy {
    private static readonly Dictionary<int,decimal> Fixed = new() { ''' + replacements + ''' };
    public static decimal CurrentUnitPrice(decimal storedPrice, int albumId) => Fixed[albumId];
}
'''
        (project / 'SourcePricingPolicy.cs').write_text(text, encoding='utf-8')
    write_json(project / 'Data/catalog.json', raw_catalog(repo, name))
    create_initial_database(repo, name, project / 'Data/initial-store.sqlite')
    if quote_style == 'single':
        # An equivalent markup form for calibration; no source-specific values change.
        pages = project / 'Pages.cs'
        pages.write_text(pages.read_text(encoding='utf-8').replace('\\"', "'"), encoding='utf-8')
    return project


def compare_existing(database, oracle):
    """Read-only independent row checker. Extra rows are permitted, old rows are exact."""
    issues = []
    current = snapshot_tables(database)
    for table, expected in oracle['tables'].items():
        key = expected['key']
        observed = {r[key]: r for r in current[table]['rows']}
        for row in expected['rows']:
            actual = observed.get(row[key])
            matches = actual is not None
            for column, value in row.items():
                got = actual.get(column) if actual else None
                if column in ('Price', 'Total', 'UnitPrice') and value is not None and got is not None:
                    matches = matches and Decimal(str(got)) == Decimal(str(value))
                else:
                    matches = matches and got == value
            if not matches:
                issues.append({'table': table, 'id': row[key], 'expected': row,
                               'observed': actual})
    return issues


def semantic_necessity(repo):
    a = independently_check_arithmetic(repo, 'A')
    b = independently_check_arithmetic(repo, 'B')
    return {'same_public_request': True, 'public_request_sha256': sha256(asset_dir(repo) / 'public-request.txt'),
        'family_count': 1, 'variant_count': 2, 'A': a, 'B': b,
        'A_fixed_answer_passes_A': a == a, 'A_fixed_answer_passes_B': a == b,
        'information_dependence': a != b, 'human_review': 'not_run', 'model_read_source_proven': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    commands = parser.add_subparsers(dest='command', required=True)
    prepare = commands.add_parser('prepare')
    prepare.add_argument('--source', type=Path)
    reference = commands.add_parser('reference')
    reference.add_argument('--variant', choices=['A', 'B'], required=True)
    reference.add_argument('--out', type=Path, required=True)
    reference.add_argument('--fixed-variant', choices=['A', 'B'])
    reference.add_argument('--quote-style', choices=['double', 'single'], default='double')
    check = commands.add_parser('necessity')
    check.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'prepare':
        for name in ('A', 'B'):
            print(prepare_assets(args.repo, name, args.source))
    elif args.command == 'reference':
        print(materialize_reference(args.repo, args.variant, args.out, args.fixed_variant, args.quote_style))
    else:
        if args.out.exists():
            raise FileExistsError(args.out)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        write_json(args.out, semantic_necessity(args.repo))
        print(args.out)


if __name__ == '__main__':
    main()
