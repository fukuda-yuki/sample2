"""Finite offline campaign/assessment boundary tests; no provider or old Runs."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import warnings
import zipfile

from research import experiment_identity as identity
from outer.harness import util


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree(path):
    return {p.relative_to(path).as_posix(): digest(p)
            for p in path.rglob('*') if p.is_file()}


class ExperimentIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def campaign(self, name):
        return identity.create_campaign(self.root, name, plan_sha256='a' * 64,
                                        evaluation_version='fixture-2', evaluator_sha256='b' * 64)

    def test_two_campaigns_reassessment_stop_partial_fault_and_original_immutable(self):
        a, b = self.campaign('campaign-a'), self.campaign('campaign-b')
        self.assertNotEqual(a.campaign_uuid, b.campaign_uuid)
        self.assertNotEqual(a.root, b.root)
        self.assertNotEqual(a.public_workspace, b.public_workspace)
        ar, br = a.create_run('same-task-001'), b.create_run('same-task-001')
        self.assertNotEqual(ar['run_instance_id'], br['run_instance_id'])
        artifact = a.run_root(ar) / 'artifact.txt'
        artifact.write_text('original model-free fixture', encoding='utf8')
        (a.output_root(ar) / 'result.json').write_text('{"state":"partial"}', encoding='utf8')
        original = tree(a.root)
        al, bl = a.acquire_lease(), b.acquire_lease()
        self.assertNotEqual(al['generation'], bl['generation'])
        with self.assertRaises(ValueError): a.release_lease(bl)
        with self.assertRaises(FileExistsError): a.acquire_lease()
        a.request_stop(al, reason='fixture stop')
        self.assertTrue(a.stop_requested(al))
        self.assertFalse(b.stop_requested(bl))
        with self.assertRaises(ValueError): b.run_root(ar)
        a.release_lease(al)
        b.release_lease(bl)
        fresh = a.acquire_lease()
        self.assertFalse(a.stop_requested(fresh))
        with self.assertRaises(ValueError): a.request_stop(al, reason='stale generation')
        a.release_lease(fresh)
        # Acquisition control activity is expected; the source Run is unchanged.
        original_run = tree(a.run_root(ar))
        assessment = identity.create_reassessment(
            self.root, 'assessment-one', source=a, source_run=ar, artifact=artifact,
            artifact_sha256=digest(artifact), evaluation_version='fixture-3',
            evaluator_sha256='c' * 64)
        self.assertEqual(assessment['source_run_instance_id'], ar['run_instance_id'])
        self.assertNotEqual(assessment['assessment_id'], ar['run_instance_id'])
        self.assertEqual(assessment['kind'], 'saved_artifact_reassessment')
        assessment_root = self.root / 'assessments' / 'assessment-one'
        (assessment_root / 'result.json').write_text('{"state":"postprocess_fault"}', encoding='utf8')
        self.assertEqual(tree(a.run_root(ar)), original_run)
        for path, sha in original.items():
            self.assertEqual(digest(a.root / path), sha)
        with self.assertRaises(FileExistsError):
            identity.create_reassessment(self.root, 'assessment-one', source=a, source_run=ar,
                artifact=artifact, artifact_sha256=digest(artifact), evaluation_version='fixture-3',
                evaluator_sha256='c' * 64)
        with self.assertRaises(ValueError):
            identity.create_reassessment(self.root, 'bad-source', source=b, source_run=ar,
                artifact=artifact, artifact_sha256=digest(artifact), evaluation_version='fixture-3',
                evaluator_sha256='c' * 64)
        with self.assertRaises(ValueError):
            identity.create_reassessment(self.root, 'bad-hash', source=a, source_run=ar,
                artifact=artifact, artifact_sha256='d' * 64, evaluation_version='fixture-3',
                evaluator_sha256='c' * 64)

    def package(self, campaign):
        files = {
            'report/REPORT.md': b'Toy fixture sum=5; not research data.\n',
            'data/values.json': b'[2,3]\n',
            'code/recompute.py': b'import json\nfrom pathlib import Path\nprint(sum(json.loads((Path(__file__).resolve().parents[1]/"data/values.json").read_text())))\n',
            'REPRODUCE.md': b'Run python code/recompute.py; expect 5.\n',
        }
        return identity.build_package(campaign.public_workspace / 'fixture.zip',
                                      identity=campaign.metadata, files=files)

    def test_restore_relative_paths_recompute_and_cross_campaign_rejection(self):
        a, b = self.campaign('campaign-a'), self.campaign('campaign-b')
        package = self.package(a)
        dest = self.root / 'anonymous-download' / 'different-folder'
        manifest = identity.restore_package(package, dest, expected_campaign_uuid=a.campaign_uuid,
                                            expected_package_sha256=digest(package))
        self.assertEqual(manifest['identity']['campaign_uuid'], a.campaign_uuid)
        proc = subprocess.run([sys.executable, str(dest / 'code/recompute.py')],
                              cwd=self.root, capture_output=True, text=True, timeout=10)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), '5')
        with self.assertRaises(ValueError):
            identity.restore_package(package, self.root / 'wrong-campaign', expected_campaign_uuid=b.campaign_uuid)
        with self.assertRaises(FileExistsError):
            identity.restore_package(package, dest, expected_campaign_uuid=a.campaign_uuid)

    def test_reassessment_package_preserves_lineage_not_new_acquisition(self):
        a = self.campaign('campaign-a')
        run = a.create_run('fixture-001')
        artifact = a.run_root(run) / 'artifact.txt'
        artifact.write_bytes(b'unchanged')
        assessment = identity.create_reassessment(self.root, 'assessment-one', source=a,
            source_run=run, artifact=artifact, artifact_sha256=digest(artifact),
            evaluation_version='fixture-3', evaluator_sha256='c' * 64)
        source_hashes = tree(a.run_root(run))
        source_package = self.package(a)
        with zipfile.ZipFile(source_package) as z:
            files = {n: z.read(n) for n in z.namelist() if n != 'manifest.json'}
        package = identity.build_package(self.root / 'assessment-public' / 'fixture.zip',
            identity=assessment, files=files)
        manifest = identity.restore_package(package, self.root / 'restore-assessment',
            expected_campaign_uuid=a.campaign_uuid)
        self.assertEqual(manifest['identity']['kind'], 'saved_artifact_reassessment')
        self.assertEqual(manifest['identity']['source_artifact_sha256'], digest(artifact))
        self.assertEqual(tree(a.run_root(run)), source_hashes)

    def test_tamper_traversal_duplicate_unlisted_and_symlink_rejected_before_restore(self):
        a = self.campaign('campaign-a')
        package = self.package(a)
        with zipfile.ZipFile(package) as z:
            entries = {n: z.read(n) for n in z.namelist()}
        for kind in ('tamper', 'traversal', 'windows', 'duplicate', 'unlisted', 'symlink', 'prefix', 'case'):
            changed = dict(entries)
            if kind == 'tamper': changed['data/values.json'] = b'[9,9]'
            if kind == 'traversal': changed['../outside.txt'] = b'bad'
            if kind == 'windows': changed['C:/outside.txt'] = b'bad'
            if kind == 'unlisted': changed['extra.txt'] = b'bad'
            if kind == 'prefix': changed['data'] = b'bad'
            if kind == 'case': changed['DATA/values.json'] = b'bad'
            bad = self.root / (kind + '.zip')
            with zipfile.ZipFile(bad, 'w') as z:
                for name, content in changed.items(): z.writestr(name, content)
                if kind == 'duplicate':
                    with warnings.catch_warnings():
                        warnings.simplefilter('ignore', UserWarning)
                        z.writestr('data/values.json', b'[2,3]')
                if kind == 'symlink':
                    item = zipfile.ZipInfo('link')
                    item.create_system = 3
                    item.external_attr = 0o120777 << 16
                    z.writestr(item, b'../outside')
            dest = self.root / ('rejected-' + kind)
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                identity.restore_package(bad, dest, expected_campaign_uuid=a.campaign_uuid)
            self.assertFalse(dest.exists())

    def test_public_expected_digest_rejects_fully_rehashed_forgery(self):
        a = self.campaign('campaign-a')
        package = self.package(a)
        expected = digest(package)
        with zipfile.ZipFile(package) as z:
            files = {n: z.read(n) for n in z.namelist() if n != 'manifest.json'}
        files['data/values.json'] = b'[9,9]'
        forged = identity.build_package(self.root / 'forged.zip', identity=a.metadata, files=files)
        with self.assertRaises(ValueError):
            identity.restore_package(forged, self.root / 'rejected-forgery',
                expected_campaign_uuid=a.campaign_uuid, expected_package_sha256=expected)
        self.assertFalse((self.root / 'rejected-forgery').exists())

    def test_existing_frozen_run_import_hex_uuid_no_original_writes(self):
        source = self.root / 'old-run'
        source.mkdir()
        (source / 'frozen').mkdir()
        (source / 'frozen' / 'app.txt').write_bytes(b'original saved artifact')
        condition = {'schema_version': 2, 'evaluation': {'evaluation_version': 'education-1.0.0'}}
        (source / 'condition.json').write_text(json.dumps(condition), encoding='utf8')
        manifest = {'schema_version': 2, 'run_id': 'old-001', 'run_instance_id': '1234567890abcdef1234567890abcdef',
            'stop_confirmed': True, 'submission_fixed': True, 'condition_sha256': digest(source / 'condition.json')}
        (source / 'manifest.json').write_text(json.dumps(manifest), encoding='utf8')
        (source / 'snapshot.json').write_text(json.dumps({'run_id': 'old-001',
            'artifact_sha256': util.artifact_hash(source / 'frozen')}), encoding='utf8')
        old = tree(source)
        kwargs = dict(source_run_root=source, source_campaign_id='original100',
            source_campaign_uuid='12345678-90ab-cdef-1234-567890abcdef',
            evaluation_version='education-2.0.0', evaluator_sha256='a' * 64)
        result = identity.create_frozen_reassessment(self.root, 'saved-one', **kwargs)
        self.assertEqual(result['source_run_instance_id'], manifest['run_instance_id'])
        self.assertEqual(result['kind'], 'saved_artifact_reassessment')
        self.assertEqual(result['source_campaign_binding'], 'caller_asserted_unverified')
        self.assertEqual(tree(source), old)
        with self.assertRaises(ValueError):
            identity.create_frozen_reassessment(source, 'bad-location', **kwargs)
        with self.assertRaises(ValueError):
            identity.create_frozen_reassessment(self.root, 'same-version',
                **{**kwargs, 'evaluation_version': 'education-1.0.0'})
        (source / 'frozen' / 'app.txt').write_bytes(b'tampered')
        with self.assertRaises(ValueError):
            identity.create_frozen_reassessment(self.root, 'tampered-source', **kwargs)
        self.assertFalse((self.root / 'assessments' / 'tampered-source').exists())

    def test_identity_paths_reject_alias_and_existing_campaign(self):
        for name in ('../x', 'a/b', 'C:x', '.', 'CON', 'campaign.'):
            with self.subTest(name=name), self.assertRaises(ValueError): self.campaign(name)
        a = self.campaign('campaign-a')
        with self.assertRaises(FileExistsError): self.campaign('campaign-a')
        with self.assertRaises(ValueError): a.create_run('../x')
        bad = {**a.metadata, 'unreviewed_private_field': 'not eligible for public metadata'}
        with self.assertRaises(ValueError):
            identity.build_package(self.root / 'bad-identity.zip', identity=bad,
                files={'report/REPORT.md': b'x', 'REPRODUCE.md': b'x',
                       'data/x': b'x', 'code/x': b'x'})


if __name__ == '__main__': unittest.main()
