import copy
from pathlib import Path
import tempfile
import unittest

from outer.harness import util
from research import repair_spec
from research.saved_reassessment import requirement_inventory


class RepairSpecTests(unittest.TestCase):
    def test_education_field_specific_date_and_ui_contract_preserves_inventory(self):
        original = {'specVersion': 'education-1.0.0', 'taskId': 'EDU',
            'requirements': [{'id': 'R-001', 'severity': 'critical', 'checks': [{'id': 'E-001'}]}]}
        before = copy.deepcopy(original); result = repair_spec.revised(original)
        self.assertEqual(original, before)
        self.assertEqual(result['specVersion'], 'education-1.1.0')
        self.assertEqual(requirement_inventory(original), requirement_inventory(result))
        text = ' '.join(result['measurementRevision']['changes'])
        self.assertIn('Departments.StartDate', text); self.assertIn('Visible date markers', text)

    def test_music_price_text_changes_without_oracle_or_requirements_drift(self):
        original = {'specVersion': '1.3.0', 'taskId': 'MS', 'requirements': [
            {'id': 'R-013', 'severity': 'critical', 'basisDetail': '8.99 always',
             'checks': [{'id': 'C-014', 'observation': '26.97'}]},
            {'id': 'R-014', 'severity': 'major', 'checks': [{'id': 'C-015', 'observation': '8.99'}]},
            {'id': 'R-016', 'severity': 'major', 'checks': [{'id': 'C-017', 'observation': '26.97'}]}],
            'migrationContract': {'oracleSha256': 'fixed'}, 'knownLimits': [
                '注文合計（Order.Total）は HTTP で観測できないため評価対象外である。',
                'C-006（再起動）は他DB非観測', 'Only finite coverage.']}
        result = repair_spec.revised(original)
        self.assertEqual(result['specVersion'], '1.4.0')
        self.assertEqual(result['migrationContract'], original['migrationContract'])
        self.assertEqual(requirement_inventory(original), requirement_inventory(result))
        self.assertNotIn('26.97', str(result)); self.assertIn('Only finite coverage.', result['knownLimits'])
        self.assertTrue(any('Order.Total' in text and 'read-only SQLite' in text for text in result['knownLimits']))

    def test_old_file_and_prior_revision_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'old.json'; dest = Path(directory)/'new.json'
            util.write_new_json(source, {'specVersion': 'education-1.0.0', 'requirements': []})
            before = source.read_bytes()
            with self.assertRaises(ValueError): repair_spec.write(source, source)
            repair_spec.write(source, dest)
            with self.assertRaises(FileExistsError): repair_spec.write(source, dest)
            self.assertEqual(before, source.read_bytes())
        with self.assertRaises(ValueError): repair_spec.revised({'specVersion': '9.0.0'})

    def test_music_removal_revision_keeps_prior_contract_and_declares_missing_preconditions(self):
        original = {'specVersion': '1.4.0', 'taskId': 'MS', 'requirements': [
            {'id': 'R-014', 'severity': 'major', 'weight': 1,
             'checks': [{'id': 'C-015', 'observation': 'Quantity 2 removal'}]},
            {'id': 'R-015', 'severity': 'major', 'weight': 1,
             'checks': [{'id': 'C-016', 'observation': 'Quantity 1 removal'}]}],
            'migrationContract': {'oracleSha256': 'fixed'},
            'measurementRevision': {'sourceSpecVersion': '1.3.0', 'changes': ['Earlier finite repairs']}}
        before = copy.deepcopy(original)
        result = repair_spec.revised(original)
        self.assertEqual(original, before)
        self.assertEqual(result['specVersion'], '1.5.0')
        self.assertEqual(requirement_inventory(result), requirement_inventory(original))
        self.assertEqual(result['migrationContract'], original['migrationContract'])
        self.assertEqual(result['priorMeasurementRevision'], original['measurementRevision'])
        text = ' '.join(result['measurementRevision']['changes'])
        self.assertIn('positive record ID', text)
        self.assertIn('blocked', text)
        self.assertIn('C-016', text)

    def test_music_attribution_revision_preserves_oracle_and_discloses_observation_gaps(self):
        original = {'specVersion': '1.5.0', 'taskId': 'MS', 'requirements': [
            {'id': 'R-013', 'severity': 'critical', 'checks': [{'id': 'C-014'}]},
            {'id': 'R-031', 'severity': 'critical', 'checks': [{'id': 'C-031'}]}],
            'migrationContract': {'oracleSha256': 'fixed'},
            'measurementRevision': {'sourceSpecVersion': '1.4.0', 'changes': ['Removal preconditions']},
            'priorMeasurementRevision': {'sourceSpecVersion': '1.3.0', 'changes': ['Earlier repairs']}}
        before = copy.deepcopy(original)
        result = repair_spec.revised(original)
        self.assertEqual(original, before)
        self.assertEqual(result['specVersion'], '1.6.0')
        self.assertEqual(requirement_inventory(result), requirement_inventory(original))
        self.assertEqual(result['migrationContract'], original['migrationContract'])
        self.assertEqual(result['measurementRevisionHistory'], [
            original['priorMeasurementRevision'], original['measurementRevision']])
        text = ' '.join(result['measurementRevision']['changes'])
        self.assertIn('C-014', text)
        self.assertIn('currency', text)
        self.assertIn('independent', text)
        self.assertIn('unknown', text)
        self.assertIn('quality', text)


if __name__ == '__main__': unittest.main()
