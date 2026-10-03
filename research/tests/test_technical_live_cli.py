"""No-model admission and normal scoring share the validated browser pin."""
from contextlib import contextmanager
import importlib.util
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from outer.harness import util

REPO=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('technical_live_cli',REPO/'outer/verify/technical-pair-live.py')
cli=importlib.util.module_from_spec(spec); spec.loader.exec_module(cli)


class TechnicalLiveCliTests(unittest.TestCase):
    def test_invalid_browser_dependency_pin_rejects_before_cohort_allocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo=Path(tmp); output=repo/'new-technical-cohort'
            protocol=repo/'research/protocols/technical-pair-live-20261003.json'
            protocol.parent.mkdir(parents=True)
            shutil.copyfile(REPO/'research/protocols/technical-pair-live-20261003.json',protocol)
            mock=repo/'mock.json'; util.write_new_json(mock,{'passed':True,'real_model_calls':0,
                'results':[{'case':'actual-'+arm,'ordinary_opencode_worker':True} for arm in ('explore','preload')]})
            browser=repo/'browser.json'; util.write_new_json(browser,{'verified':True,
                'environment':{'unexpected_dependency_setting':'fixture'}})
            argv=['technical-pair-live.py','--mode','prepare','--repo',str(repo),'--out',str(output),
                  '--mock-receipt',str(mock),'--browser-probe',str(browser)]
            with patch.object(sys,'argv',argv), patch.object(cli.machine,'expected_conditions') as conditions, \
                 self.assertRaisesRegex(ValueError,'verified existing browser'):
                cli.main()
            self.assertFalse(output.exists()); conditions.assert_not_called()

    def test_normal_postprocessing_receives_activation_and_failure_restores_scope(self):
        events=[]; pin={'fixture':'exact pinned environment'}
        @contextmanager
        def activate(record,repo):
            self.assertEqual(record,pin); events.append('enter')
            try: yield
            finally: events.append('exit')
        def scoring(*args):
            self.assertEqual(events,['enter']); events.append('normal_postprocess')
            raise RuntimeError('ordinary scoring fault')
        with patch.object(cli.catalog_environment,'activated',activate), \
             patch.object(cli.machine,'postprocess',side_effect=scoring), self.assertRaises(RuntimeError):
            cli.pinned_postprocess(pin)(REPO,REPO/'runs','fixture',REPO/'archive')
        self.assertEqual(events,['enter','normal_postprocess','exit'])


if __name__ == '__main__': unittest.main()
