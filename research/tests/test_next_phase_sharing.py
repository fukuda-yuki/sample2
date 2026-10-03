from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from outer.harness import util
from research import next_phase_sharing as sharing


class SharingRecoveryTests(unittest.TestCase):
    def fixture(self, root):
        work = root / 'artifacts/continuity-sharing-v1/pair-001'
        work.mkdir(parents=True)
        bundle, review = root / 'bundle.json', root / 'review.json'
        util.write_new_json(bundle, {'fixed': True})
        util.write_new_json(review, {'publication_approved': True})
        evidence = work / 'roundtrip-bound-001.json'
        util.write_new_json(evidence, {'package_sha256': 'package', 'hashes_match': True,
            'extraction_sockets_blocked': True, 'workspace': str(work / 'roundtrip-001')})
        saved = work / 'finalization.json'
        util.write_new_json(saved, {'pair': 1, 'plan_sha256': util.sha256_file(bundle),
            'cohort': 'runs/continuity-v1', 'review_sha256': util.sha256_file(review),
            'run_instances': {'run': 'instance'}, 'attempt': 1,
            'original_inventory': {'run': {}}, 'package_sha256': 'package',
            'roundtrip_receipt': str(evidence),
            'evidence_files': {str(evidence): util.sha256_file(evidence)}})
        context = ({'cohort': 'runs/continuity-v1'}, root / 'runs/continuity-v1',
            {'gates': {}}, {}, [{'run_id': 'run', 'run_instance_id': 'instance'}])
        return work, bundle, review, saved, evidence, context

    def test_cleanup_completed_before_journal_write_resumes_without_transfer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            work, bundle, review, saved, evidence, context = self.fixture(root)
            cleanup = {'cleanup_completed': True, 'targets': [], 'original_runs_deleted': False}
            with patch.object(sharing, 'pair_context', return_value=context), patch.object(sharing.catalog_share, 'inventory', return_value={}), patch.object(sharing.catalog_delivery, 'cleanup', return_value=cleanup) as clean, patch.object(sharing.pair_execution, 'record_pair_gate', side_effect=[RuntimeError('crash after owned cleanup'), None]) as gate, patch.object(sharing.catalog_delivery, 'publish') as publish:
                with self.assertRaises(RuntimeError): sharing.finish(root, bundle, 1, work, review, saved)
                result = sharing.share(root, bundle, 1, work, review)
                self.assertEqual(result['status'], 'shared_downloaded_restored_extracted_cleaned')
                self.assertEqual(clean.call_count, 1)
                self.assertEqual(gate.call_count, 2)
                publish.assert_not_called()

    def test_changed_retained_receipt_cannot_complete_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            work, bundle, review, saved, evidence, context = self.fixture(root)
            evidence.write_text('{}', encoding='utf-8')
            with patch.object(sharing, 'pair_context', return_value=context), patch.object(sharing.pair_execution, 'record_pair_gate') as gate:
                with self.assertRaises(ValueError): sharing.finish(root, bundle, 1, work, review, saved)
                gate.assert_not_called()


if __name__ == '__main__': unittest.main()
