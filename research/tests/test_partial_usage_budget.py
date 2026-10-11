"""Synthetic component-wise accounting through both acquisition and origin paths."""
from pathlib import Path
import tempfile
import unittest

from outer.harness import util
from research import acquisition_pipeline as pipeline, live_pilot, resource_origin


class PartialUsageBudgetTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)

    def attempt(self,name,usage):
        batch=self.root/name;root=batch/'run'
        util.write_new_json(root/'manifest.json',dict(run_instance_id=name,stop_confirmed=True,
            network_cleanup={'confirmed':True},started_at='2026-10-01T00:00:00+00:00',
            ended_at='2026-10-01T00:00:02+00:00',duration_seconds=2))
        util.append_line(root/'usage/raw/started.jsonl',dict(request_id='request'))
        util.append_line(root/'usage/raw/events.jsonl',dict(request_id='request',status='transport_error',usage=usage))
        return batch

    def origin(self,*batches):
        path=self.root/('origin-'+str(len(list(self.root.glob('origin-*.json'))))+'.json')
        util.write_new_json(path,dict(kind='technical_acceptance_resources_v1',
            started_at='2026-10-01T00:00:00+00:00',runs=[dict(
                manifest=live_pilot.reference(batch/'run/manifest.json'),
                raw_usage=util.tree_hashes(batch/'run/usage/raw')) for batch in batches]))
        return resource_origin.read(live_pilot.reference(path))[1]

    def budget(self,usage,cap):
        return pipeline.Budget(dict(usage=usage,root=str(self.root),started_at='2026-10-01T00:00:00+00:00',
            bounds=dict(observed_tokens=cap,request_count=100,accumulated_run_seconds=100,wall_seconds=10**10)))

    def test_known_components_survive_in_both_paths_and_unknown_totals_stay_null(self):
        cases=[(100,None,100),(None,100,100),(None,None,0),(100,20,120),(0,None,0),(0,0,0)]
        for index,(input_tokens,output_tokens,expected) in enumerate(cases):
            with self.subTest(input_tokens=input_tokens,output_tokens=output_tokens):
                batch=self.attempt(str(index),dict(input_tokens=input_tokens,output_tokens=output_tokens,
                    cached_input_tokens=999,reasoning_tokens=999,total_tokens=9999))
                direct=pipeline.usage_for(batch);origin=self.origin(batch)
                self.assertEqual(direct,origin)
                self.assertEqual(direct['observed_tokens'],expected)
                missing=[key for key,value in [('input_tokens',input_tokens),('output_tokens',output_tokens)] if value is None]
                self.assertEqual(len(direct['unknown_usage_requests']),int(bool(missing)))
                if missing:
                    row=direct['unknown_usage_requests'][0]
                    self.assertIsNone(row['observed_tokens'])
                    self.assertEqual(row['input_tokens'],input_tokens)
                    self.assertEqual(row['output_tokens'],output_tokens)
                    self.assertEqual(row['observed_tokens_lower_bound'],expected)
                    self.assertEqual(row['missing_usage_fields'],missing)

    def test_partial_origin_reaches_cap_before_any_new_attempt(self):
        for index,usage in enumerate((dict(input_tokens=100,output_tokens=None),
                dict(input_tokens=None,output_tokens=100),dict(input_tokens=30,output_tokens=20))):
            batch=self.attempt(str(index),usage)
            for value in (pipeline.usage_for(batch),self.origin(batch)):
                with self.subTest(usage=usage),self.assertRaisesRegex(RuntimeError,'observed_tokens'):
                    self.budget(value,50).check(None,{})

    def test_missing_or_invalid_components_never_invent_zero_or_cancel_known_tokens(self):
        cases=[(None,None,None,0),({},None,None,0),
            (dict(input_tokens=100,output_tokens=-1),100,None,100),
            (dict(input_tokens=100,output_tokens=True),100,None,100),
            (dict(input_tokens='100',output_tokens=7),None,7,7),
            (dict(output_tokens=7),None,7,7),
            (dict(input_tokens=100,output_tokens=1.5),100,None,100)]
        for index,(usage,expected_input,expected_output,expected_total) in enumerate(cases):
            batch=self.attempt(str(index),usage);result=pipeline.usage_for(batch)
            self.assertEqual(result['observed_tokens'],expected_total)
            row=result['unknown_usage_requests'][0]
            self.assertIsNone(row['observed_tokens'])
            self.assertEqual(row['input_tokens'],expected_input)
            self.assertEqual(row['output_tokens'],expected_output)
            self.assertEqual(result,self.origin(batch))

    def test_duplicate_request_journals_are_rejected_by_both_paths(self):
        for name in ('started','events'):
            batch=self.attempt(name,dict(input_tokens=100,output_tokens=None))
            util.append_line(batch/('run/usage/raw/'+name+'.jsonl'),dict(request_id='request',
                usage=dict(input_tokens=100,output_tokens=None)))
            for read in (lambda:pipeline.usage_for(batch),lambda:self.origin(batch)):
                with self.subTest(journal=name),self.assertRaisesRegex(ValueError,'Duplicate usage request'):read()

    def test_origin_and_fresh_uuid_attempts_share_cap_without_recounting_finished_attempts(self):
        origin=self.origin(self.attempt('acceptance',dict(input_tokens=100,output_tokens=None)))
        first=pipeline.usage_for(self.attempt('failed-attempt',dict(input_tokens=None,output_tokens=40)))
        second=pipeline.usage_for(self.attempt('fresh-uuid',dict(input_tokens=10,output_tokens=5)))
        budget=self.budget(origin,155)
        self.assertTrue(budget.total['observed_tokens_are_lower_bound'])
        budget.check('first',first);budget.finish('first',first);budget.finish('first',first)
        self.assertEqual(budget.total['observed_tokens'],140)
        with self.assertRaisesRegex(RuntimeError,'observed_tokens'):budget.check('second',second)
        budget.finish('second',second)
        self.assertEqual(budget.total['observed_tokens'],155)
        self.assertEqual(budget.total['requests'],3)
        self.assertEqual(len(budget.total['unknown_usage_requests']),2)
        with self.assertRaisesRegex(RuntimeError,'observed_tokens'):budget.check(None,{})
        restored=self.budget(origin,155)
        restored.finish('first',first);restored.finish('second',second)
        self.assertEqual(restored.total,budget.total)
        with self.assertRaisesRegex(RuntimeError,'observed_tokens'):restored.check(None,{})
