"""Finite independent source/data, HTTP and restart oracle; no model dispatch."""
import argparse
import http.client
import os
import re
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import education_tasks as tasks
from . import migration_tasks as common
from .verify_migration_tasks import Session, stop


def launch(published, database, log_path):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    base = f'http://127.0.0.1:{port}'
    allowed = {'PATH', 'PATHEXT', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'TEMP', 'TMP',
               'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'PROGRAMFILES', 'PROGRAMFILES(X86)',
               'PROGRAMW6432', 'DOTNET_ROOT', 'DOTNET_ROOT_X64'}
    env = {k: v for k, v in os.environ.items() if k.upper() in allowed}
    env.update(ConnectionStrings__SchoolContext='Data Source=' + str(database.resolve()),
               DOTNET_CLI_TELEMETRY_OPTOUT='1', DOTNET_NOLOGO='1', ASPNETCORE_ENVIRONMENT='Production')
    log = log_path.open('wb')
    process = subprocess.Popen(['dotnet', str(published / 'Education.Continuity.dll'), '--urls', base],
                               cwd=published, env=env, stdout=log, stderr=subprocess.STDOUT)
    common.write_json(log_path.with_suffix('.owner.json'), {'pid': process.pid, 'base_url': base,
        'published_root': str(published), 'database': str(database), 'credential_environment_passed': False})
    deadline = time.monotonic() + 30
    try:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError('Reference startup failed; inspect ' + str(log_path))
            try:
                if urllib.request.urlopen(base, timeout=1).code == 200:
                    return process, log, base
            except (urllib.error.URLError, TimeoutError, http.client.HTTPException):
                time.sleep(.2)
        raise TimeoutError('Reference startup timed out')
    except BaseException:
        stop(process, log)
        raise


def marker(body, name):
    match = re.search(r'id=["\']' + re.escape(name) + r'["\'][^>]*>\s*([^<]*)', body)
    return match.group(1).strip() if match else None


def invalid_fields(valid):
    result = []
    for name in valid:
        fields = dict(valid)
        del fields[name]
        result.append(('missing-' + name, fields))
    for name in ('LastName', 'FirstMidName'):
        for label, value in [('blank', '  '), ('too-long', 'x' * 51)]:
            result.append((label + '-' + name, {**valid, name: value}))
    for value in ('2026-02-30', 'not-a-date'):
        result.append(('invalid-date-' + value, {**valid, 'EnrollmentDate': value}))
    return result


def run_case(repo, name, published, output, expected_negative=False):
    started = time.monotonic()
    output.mkdir(parents=True, exist_ok=False)
    asset = tasks.prepare_assets(repo, name)
    oracle = common.read_json(asset / 'evaluation/migration-oracle.json')
    definition = tasks.definition(repo, name)
    database = output / 'fresh-school.sqlite'
    checks = []
    def check(label, passed, observed=None, expected=None):
        checks.append({'check': label, 'passed': bool(passed), 'observed': observed, 'expected': expected})
    process = log = None
    transcripts = []
    try:
        raw_hash = common.sha256(published / 'Data/legacy-school.sqlite')
        check('original-raw-input', raw_hash == common.sha256(asset / 'inputs/existing-business/legacy-school.sqlite'), raw_hash)
        source_enum = tasks.parse_grade_enum(asset / 'inputs/legacy-source/src/ContosoUniversity/Models/Enrollment.cs')
        raw_rows = tasks.rows(asset / 'inputs/existing-business/legacy-school.sqlite', legacy=True)
        decoded = {str(row['EnrollmentID']): 'No grade' if row['Grade'] is None else source_enum[str(row['Grade'])]
                   for row in raw_rows['Enrollments']['rows']}
        check('independent-source-enum-data', decoded == definition['manual_grade_expectations'], decoded,
              definition['manual_grade_expectations'])
        check('target-path-initially-absent', not database.exists())
        process, log, base = launch(published, database, output / 'first-start.log')
        session = Session(base)
        check('fresh-import-full-schema-rows', not tasks.compare_rows(database, oracle['tables']),
              tasks.compare_rows(database, oracle['tables']))
        observed_initial = tasks.rows(database)
        check('fresh-import-no-duplicate-rows', all(len(observed_initial[t]['rows']) == len(oracle['tables'][t]['rows']) for t in oracle['tables']), observed_initial)
        home = session.request('/')
        check('home-links', home['status'] == 200 and all(href in home['body'] for href in ('href=\'/Student\'', 'href=\'/Course\'')))
        listed = session.request('/Student')
        check('student-list-and-links', listed['status'] == 200 and set(re.findall(r'id=["\']student-(\d+)', listed['body'])) == {'101', '202'} and all('/Student/Edit/' + str(i) in listed['body'] for i in (101, 202)))
        search = session.request('/Student?SearchString=Hop')
        check('search-original-names', set(re.findall(r'id=["\']student-(\d+)', search['body'])) == {'101'})
        for student in oracle['tables']['Students']['rows']:
            response = session.request('/Student/Details/' + str(student['ID']))
            check('student-details-' + str(student['ID']), response['status'] == 200 and
                marker(response['body'], 'student-full-name') == student['LastName'] + ', ' + student['FirstMidName'] and
                marker(response['body'], 'student-enrollment-date') == student['EnrollmentDate'])
            for row in raw_rows['Enrollments']['rows']:
                if row['StudentID'] != student['ID']:
                    continue
                grade = marker(response['body'], 'grade-' + str(row['EnrollmentID']))
                check('source-defined-grade-' + str(row['EnrollmentID']), grade == decoded[str(row['EnrollmentID'])],
                      grade, decoded[str(row['EnrollmentID'])])
                check('enrollment-course-join-' + str(row['EnrollmentID']),
                      '/Course/Details/' + str(row['CourseID']) in response['body'])
        course_list = session.request('/Course')
        check('course-list', course_list['status'] == 200 and set(re.findall(r'id=["\']course-(\d+)', course_list['body'])) == {'1045', '2021', '4041'})
        departments = {r['DepartmentID']: r['Name'] for r in oracle['tables']['Departments']['rows']}
        for course in oracle['tables']['Courses']['rows']:
            response = session.request('/Course/Details/' + str(course['CourseID']))
            check('course-details-' + str(course['CourseID']), response['status'] == 200 and course['Title'] in response['body'] and marker(response['body'], 'course-credits') == str(course['Credits']) and marker(response['body'], 'department-name') == departments[course['DepartmentID']])
        for path in ('/Student/Details/9999', '/Student/Edit/9999', '/Course/Details/9999'):
            check('unknown-' + path, session.request(path)['status'] == 404)
        check('unknown-edit-post', session.request('/Student/Edit/9999', oracle['workflow']['edit']['fields'])['status'] == 404)
        create = oracle['workflow']['create']['fields']
        response = session.request('/Student/Create', create)
        id_match = re.fullmatch(r'/Student/Details/(\d+)', response['location'] or '')
        student_id = int(id_match.group(1)) if id_match else -1
        check('valid-create-new-id', response['status'] == 302 and student_id > 202, student_id, '>202')
        actual = tasks.rows(database)['Students']['rows']
        new_student = next((r for r in actual if r['ID'] == student_id), None)
        check('valid-create-persist-fields', new_student == {'ID': student_id, **create}, new_student)
        baseline = tasks.rows(database)
        for label, fields in invalid_fields(create):
            response = session.request('/Student/Create', fields)
            check('invalid-create-' + label, response['status'] == 200 and tasks.rows(database) == baseline)
        edit = oracle['workflow']['edit']['fields']
        response = session.request('/Student/Edit/' + str(student_id), edit)
        check('valid-edit-redirect', response['status'] == 302 and response['location'] == '/Student/Details/' + str(student_id))
        new_student = next((r for r in tasks.rows(database)['Students']['rows'] if r['ID'] == student_id), None)
        check('valid-edit-persist-fields', new_student == {'ID': student_id, **edit}, new_student)
        baseline = tasks.rows(database)
        for label, fields in invalid_fields(edit):
            response = session.request('/Student/Edit/' + str(student_id), fields)
            check('invalid-edit-' + label, response['status'] == 200 and tasks.rows(database) == baseline)
        check('old-rows-relations-still-preserved', not tasks.compare_rows(database, oracle['tables']))
        check('only-one-new-student', len(baseline['Students']['rows']) == 3 and all(baseline[t] == observed_initial[t] for t in ('Departments', 'Courses', 'Enrollments')))
        transcripts.extend(session.transcript)
        stop(process, log)
        process = log = None
        process, log, base = launch(published, database, output / 'restart.log')
        check('restart-full-db-continuity', tasks.rows(database) == baseline)
        restarted = Session(base)
        response = restarted.request('/Student/Details/' + str(student_id))
        check('restart-new-student-visible', response['status'] == 200 and marker(response['body'], 'student-full-name') == 'Review, Morgan')
        transcripts.extend(restarted.transcript)
    finally:
        stop(process, log)
    failed = [item['check'] for item in checks if not item['passed']]
    expected_failures = ['source-defined-grade-9001', 'source-defined-grade-9002', 'source-defined-grade-9010']
    accepted = set(failed) == set(expected_failures) if expected_negative else not failed
    common.write_json(output / 'transcript.json', transcripts)
    result = {'variant': name, 'expected_negative': expected_negative, 'accepted': accepted,
              'failed_checks': failed, 'checks': checks, 'elapsed_seconds': round(time.monotonic() - started, 3),
              'model_dispatches': 0, 'human_review': 'not_run',
              'asset_preparation_sha256': common.sha256(asset / 'preparation.json'),
              'asset_files': common.hashes(asset), 'published_files': common.hashes(published)}
    common.write_json(output / 'receipt.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--published-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.published_root = args.published_root.resolve()
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=False)
    cases = [run_case(args.repo, name, args.published_root / published, args.out / label, negative)
             for name, published, label, negative in [('C', 'published-C', 'reference-C', False),
                 ('D', 'published-D', 'reference-D', False), ('D', 'published-fixed', 'fixed-C-on-D', True)]]
    paths = ['research/education_tasks.py', 'research/verify_education_tasks.py', 'research/migration_tasks.py',
             'research/verify_migration_tasks.py']
    paths += [str(p.relative_to(args.repo)).replace('\\', '/') for root in
              ('research/tasks/contoso-enrollment', 'inner/tasks/contoso-enrollment/reference')
              for p in (args.repo / root).rglob('*') if p.is_file()]
    summary = {'schema_version': 1, 'family_id': tasks.FAMILY, 'accepted': all(r['accepted'] for r in cases),
               'cases': cases, 'model_dispatches': 0, 'human_review': 'not_run',
               'code_and_contract_files': {path: common.sha256(args.repo / path) for path in paths}}
    common.write_json(args.out / 'summary.json', summary)
    print(__import__('json').dumps({'accepted': summary['accepted'], 'cases': [
        {'variant': r['variant'], 'negative': r['expected_negative'], 'accepted': r['accepted'],
         'checks': len(r['checks']), 'failed': r['failed_checks']} for r in cases]}))
    return 0 if summary['accepted'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
