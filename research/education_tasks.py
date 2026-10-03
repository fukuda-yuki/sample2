"""Independent Contoso enrollment migration assets, reference and source/data oracle.

No model dispatch. Exact public upstream bytes are separately pinned and verified;
controlled grade enums and synthetic existing business records are explicit.
"""
import argparse
import copy
import hashlib
import json
import re
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

from . import migration_tasks as common

FAMILY = 'contoso-enrollment'
SOURCE_COMMIT = '5c4e4ec11395172f82606f95ec520f0a93508541'
ASSET_NAMESPACE = 'education-assets-v2'
KEYS = {'Students': 'ID', 'Departments': 'DepartmentID', 'Courses': 'CourseID', 'Enrollments': 'EnrollmentID'}
TARGET_SCHEMA = '''
PRAGMA foreign_keys=ON;
CREATE TABLE Students(ID INTEGER PRIMARY KEY AUTOINCREMENT,LastName TEXT NOT NULL,FirstMidName TEXT NOT NULL,EnrollmentDate TEXT NOT NULL);
CREATE TABLE Departments(DepartmentID INTEGER PRIMARY KEY,Name TEXT NOT NULL,Budget TEXT NOT NULL,StartDate TEXT NOT NULL);
CREATE TABLE Courses(CourseID INTEGER PRIMARY KEY,Title TEXT NOT NULL,Credits INTEGER NOT NULL,DepartmentID INTEGER NOT NULL REFERENCES Departments(DepartmentID));
CREATE TABLE Enrollments(EnrollmentID INTEGER PRIMARY KEY,CourseID INTEGER NOT NULL REFERENCES Courses(CourseID),StudentID INTEGER NOT NULL REFERENCES Students(ID),Grade INTEGER);
'''
LEGACY_SCHEMA = TARGET_SCHEMA.replace('Students(', 'Person(').replace('FirstMidName TEXT', 'FirstName TEXT').replace('EnrollmentDate TEXT NOT NULL);', "EnrollmentDate TEXT NOT NULL,Discriminator TEXT NOT NULL);")
LEGACY_SCHEMA = LEGACY_SCHEMA.replace('Departments(', 'Department(').replace('Courses(', 'Course(').replace('Enrollments(', 'Enrollment(').replace('REFERENCES Departments(', 'REFERENCES Department(').replace('REFERENCES Courses(', 'REFERENCES Course(').replace('REFERENCES Students(', 'REFERENCES Person(')


def definition(repo, name):
    return common.read_json(Path(repo) / 'research/tasks' / FAMILY / 'variants.json')['variants'][name]


def expected_tables(repo, name):
    credits = definition(repo, name)['course_credits']
    return {
        'Students': {'key': 'ID', 'rows': [
            {'ID': 101, 'LastName': 'Hopper', 'FirstMidName': 'Grace', 'EnrollmentDate': '2010-09-01'},
            {'ID': 202, 'LastName': 'Turing', 'FirstMidName': 'Alan', 'EnrollmentDate': '2015-02-03'}]},
        'Departments': {'key': 'DepartmentID', 'rows': [
            {'DepartmentID': 10, 'Name': 'Computing', 'Budget': '123456.78', 'StartDate': '1990-01-01'},
            {'DepartmentID': 20, 'Name': 'Mathematics', 'Budget': '98765.43', 'StartDate': '1992-02-02'}]},
        'Courses': {'key': 'CourseID', 'rows': [
            {'CourseID': 1045, 'Title': 'Algorithms', 'Credits': credits['1045'], 'DepartmentID': 10},
            {'CourseID': 2021, 'Title': 'Calculus', 'Credits': credits['2021'], 'DepartmentID': 20},
            {'CourseID': 4041, 'Title': 'Logic', 'Credits': credits['4041'], 'DepartmentID': 20}]},
        'Enrollments': {'key': 'EnrollmentID', 'rows': [
            {'EnrollmentID': 9001, 'CourseID': 1045, 'StudentID': 101, 'Grade': 0},
            {'EnrollmentID': 9002, 'CourseID': 2021, 'StudentID': 101, 'Grade': 1},
            {'EnrollmentID': 9003, 'CourseID': 4041, 'StudentID': 101, 'Grade': None},
            {'EnrollmentID': 9010, 'CourseID': 2021, 'StudentID': 202, 'Grade': 3}]}}


def database(repo, name, path, legacy=False):
    path = Path(path)
    if path.exists():
        raise FileExistsError(path)
    tables = expected_tables(repo, name)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript(LEGACY_SCHEMA if legacy else TARGET_SCHEMA)
        aliases = {'Students': 'Person', 'Departments': 'Department', 'Courses': 'Course', 'Enrollments': 'Enrollment'}
        for table in ('Departments', 'Students', 'Courses', 'Enrollments'):
            for row in tables[table]['rows']:
                value = dict(row)
                if legacy and table == 'Students':
                    value['FirstName'] = value.pop('FirstMidName')
                    value['Discriminator'] = 'Student'
                common.insert(connection, aliases[table] if legacy else table, value)
        if connection.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('School snapshot has broken relationships')


def rows(database_path, legacy=False):
    aliases = {'Students': 'Person', 'Departments': 'Department', 'Courses': 'Course', 'Enrollments': 'Enrollment'}
    with closing(sqlite3.connect(Path(database_path).resolve().as_uri() + '?mode=ro', uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        return {key: {'key': primary, 'rows': [dict(r) for r in connection.execute(
                    'SELECT * FROM "' + (aliases[key] if legacy else key) + '" ORDER BY "' + primary + '"')]}
                for key, primary in KEYS.items()}


def compare_rows(database_path, expected):
    actual = rows(database_path)
    issues = []
    for table, spec in expected.items():
        lookup = {r[spec['key']]: r for r in actual[table]['rows']}
        for row in spec['rows']:
            got = lookup.get(row[spec['key']])
            if got is None or any(got.get(column) != value for column, value in row.items()):
                issues.append({'table': table, 'id': row[spec['key']], 'expected': row, 'observed': got})
    return issues


def parse_grade_enum(path):
    source = Path(path).read_text(encoding='utf-8-sig')
    block = re.search(r'enum\s+Grade\s*\{([^}]+)\}', source, re.S).group(1)
    values = [x.strip() for x in block.split(',') if x.strip()]
    if any(not re.fullmatch('[A-Z]', x) for x in values):
        raise ValueError('Unexpected grade declaration; do not silently infer enum values')
    return {str(i): value for i, value in enumerate(values)}


def source_root(repo, explicit=None):
    root = Path(explicit) if explicit else Path(repo) / 'artifacts/education-upstream-v1/source'
    if not root.is_dir():
        raise FileNotFoundError('Prepare the pinned 21-file upstream snapshot; pass --source-root for a read-only copy. No network fetch is performed here.')
    pin = common.read_json(Path(repo) / 'research/tasks' / FAMILY / 'source-pin.json')
    for relative, expected in pin['sha256'].items():
        if common.sha256(root / relative) != expected:
            raise ValueError('Pinned upstream bytes changed: ' + relative)
    return root


def prepare_assets(repo, name, upstream=None):
    repo = Path(repo).resolve()
    variant = definition(repo, name)
    root = repo / 'artifacts' / ASSET_NAMESPACE / variant['task_id']
    public = repo / 'research/tasks' / FAMILY / 'public-request.txt'
    definitions = repo / 'research/tasks' / FAMILY / 'variants.json'
    receipt = root / 'preparation.json'
    if receipt.exists():
        saved = common.read_json(receipt)
        if saved['files'] != {k: v for k, v in common.hashes(root).items() if k != 'preparation.json'}:
            raise ValueError('Prepared education assets changed')
        if saved['public_request_sha256'] != common.sha256(public) or saved['definition_sha256'] != common.sha256(definitions):
            raise ValueError('Education contract changed; choose a new namespace')
        if saved['source_pin_sha256'] != common.sha256(repo / 'research/tasks' / FAMILY / 'source-pin.json'):
            raise ValueError('Pinned source manifest changed; choose a new namespace')
        return root
    if root.exists():
        raise FileExistsError('Retain incomplete preparation')
    original = source_root(repo, upstream)
    root.mkdir(parents=True)
    source = root / 'inputs/legacy-source'
    shutil.copytree(original, source)
    grade_file = source / 'src/ContosoUniversity/Models/Enrollment.cs'
    text = grade_file.read_text(encoding='utf-8-sig')
    anchor = 'A, B, C, D, F'
    if text.count(anchor) != 1:
        raise ValueError('Pinned source grade anchor changed')
    replacement = ', '.join(variant['grade_enum'])
    grade_file.write_text('// Research installation overlay: controlled grade ordinal semantics.\n' + text.replace(anchor, replacement), encoding='utf-8', newline='\n')
    business = root / 'inputs/existing-business'
    business.mkdir()
    database(repo, name, business / 'legacy-school.sqlite', legacy=True)
    raw = rows(business / 'legacy-school.sqlite', legacy=True)
    operational = source / 'OperationalData'
    operational.mkdir()
    common.write_json(operational / 'existing-data.json', raw)
    (source / 'INSTALLATION-NOTE.txt').write_text('Scoped real Contoso University source at pinned commit plus synthetic old business export. This installation changes the Grade enum order; old Grade integers must retain their source-defined meanings. Raw Person.FirstName maps to target Students.FirstMidName. The target table names are explicitly fixed by the public migration request.\n', encoding='utf-8')
    evaluation = root / 'evaluation'
    evaluation.mkdir()
    database(repo, name, evaluation / 'initial-store.sqlite')
    grade_map = parse_grade_enum(grade_file)
    observed = {str(r['EnrollmentID']): ('No grade' if r['Grade'] is None else grade_map[str(r['Grade'])])
                for r in raw['Enrollments']['rows']}
    if observed != variant['manual_grade_expectations']:
        raise ValueError('Manual grade expectations disagree with independent source/raw-data interpretation')
    if rows(evaluation / 'initial-store.sqlite') != expected_tables(repo, name):
        raise ValueError('Target schema/data conversion oracle disagrees')
    oracle = {'schema_version': 1, 'task_id': variant['task_id'], 'family_id': FAMILY, 'variant': name,
        'tables': expected_tables(repo, name), 'grade_map': grade_map, 'human_review': 'not_run',
        'workflow': {'search': {'query': 'Hop', 'student_ids': [101]}, 'grades': observed,
            'create': {'fields': {'LastName': 'Researcher', 'FirstMidName': 'Casey', 'EnrollmentDate': '2026-01-02'}, 'id_floor': 202},
            'edit': {'fields': {'LastName': 'Review', 'FirstMidName': 'Morgan', 'EnrollmentDate': '2026-02-03'}},
            'courses': {str(r['CourseID']): {'title': r['Title'], 'credits': r['Credits'], 'department_id': r['DepartmentID']} for r in expected_tables(repo, name)['Courses']['rows']}},
        'authority': [
            {'scope': 'raw rows, IDs and relations', 'kind': 'synthetic preserved old business snapshot', 'source': 'existing-business/legacy-school.sqlite'},
            {'scope': 'grade meanings and nullable No grade', 'kind': 'old source enum and DisplayFormat', 'source': 'src/ContosoUniversity/Models/Enrollment.cs'},
            {'scope': 'FirstName column and computed full name', 'kind': 'old source', 'source': 'src/ContosoUniversity/Models/Person.cs'},
            {'scope': 'create/edit/search/course details', 'kind': 'old source feature handlers plus declared public observation interface', 'source': 'src/ContosoUniversity/Features/'},
            {'scope': 'displayed grade assertions', 'kind': 'manual expectations checked by independent Python source parser', 'source': 'research/tasks/contoso-enrollment/variants.json'}],
        'limitations': ['Old Framework app not_run; compatibility reference is executed.', 'Synthetic business installation, publicly known upstream; contamination not eliminated.', 'Human confirmation not_run.', 'Reference/evaluator calibration exposes this prospectively reserved family; it is not completely secret.']}
    common.write_json(evaluation / 'migration-oracle.json', oracle)
    common.write_json(evaluation / 'catalog.json', {'family_id': FAMILY, 'task_id': variant['task_id'], 'expected_grades': observed})
    common.write_json(receipt, {'schema_version': 1, 'task_id': variant['task_id'], 'family_id': FAMILY,
        'source_commit': SOURCE_COMMIT, 'source_pin_sha256': common.sha256(repo / 'research/tasks' / FAMILY / 'source-pin.json'),
        'public_request_sha256': common.sha256(public), 'definition_sha256': common.sha256(definitions),
        'original_source_files': common.hashes(original), 'files': common.hashes(root),
        'human_review': 'not_run', 'model_dispatches': 0})
    return root


def grade_policy(names):
    entries = ','.join('"' + x + '"' for x in names)
    return 'public static class GradePolicy { private static readonly string[] Labels = {' + entries + '}; public static string Display(int? code) => code.HasValue ? Labels[code.Value] : "No grade"; }\n'


def reference(repo, name, destination, fixed_variant=None):
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(destination)
    project = destination / 'Education.Continuity'
    shutil.copytree(Path(repo) / 'inner/tasks' / FAMILY / 'reference/Education.Continuity', project, ignore=shutil.ignore_patterns('bin', 'obj'))
    (project / 'GradePolicy.cs').write_text(grade_policy(definition(repo, fixed_variant or name)['grade_enum']), encoding='utf-8')
    (project / 'Data').mkdir(exist_ok=True)
    database(repo, name, project / 'Data/legacy-school.sqlite', legacy=True)
    return project


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('prepare')
    p.add_argument('--source-root', type=Path)
    r = commands.add_parser('reference')
    r.add_argument('--variant', choices=['C', 'D'], required=True)
    r.add_argument('--out', type=Path, required=True)
    r.add_argument('--fixed-variant', choices=['C', 'D'])
    args = parser.parse_args()
    if args.command == 'prepare':
        for name in ('C', 'D'):
            print(prepare_assets(args.repo, name, args.source_root))
    else:
        print(reference(args.repo, args.variant, args.out, args.fixed_variant))


if __name__ == '__main__':
    main()
