import unittest
from research.summarize import distribution, summarize


def run(arm, attempt, total, verdict='pass', cohort='primary18', block=1):
    return {'cohort':cohort,'condition':arm,'run_id':f'MS1-001-{arm}-{attempt:03d}',
        'run_instance_id':arm+str(attempt)+cohort,'root':'local', 'block':block,
        'quality':100 if verdict=='pass' else 0,'verdict':verdict,
        'execution':{'state':'completed'},'usage_complete':total is not None,
        'total_tokens':total,'input_tokens':total,'output_tokens':0 if total is not None else None,
        'calls':2,'actions':2,'mean_input':total/2 if total is not None else None,
        'started_at':str(attempt),'build_error_actions':0,'test_failure_actions':0,
        'action_label_counts':{},'initial_prompt_present_calls':2}


class SummaryContracts(unittest.TestCase):
    def test_saved_http_only_pass_is_not_research_quality(self):
        row = run('explore', 1, 123)
        row['scoring'] = {'evaluation_version': '1.2.0', 'browser_cart_coverage': 'not_run_http_only'}
        value = summarize({'runs': [row], 'calls': [], 'actions': []})
        self.assertEqual(0, value['groups'][0]['quality_pass'])
        self.assertEqual(1, value['groups'][0]['quality_missing'])
        self.assertEqual(123, value['groups'][0]['total_tokens']['mean'])
        self.assertEqual('pass', row['verdict'])  # original analysis not overwritten

    def test_http_only_cannot_claim_complete_and_a_verified_result_can_pass(self):
        row = run('explore', 1, 123)
        row['scoring'] = {'evaluation_version': '1.2.0', 'research_status': 'complete',
                          'browser_cart_coverage': 'not_run_http_only'}
        data = {'runs': [row], 'calls': [], 'actions': []}
        self.assertEqual(0, summarize(data)['groups'][0]['quality_pass'])
        row['scoring']['browser_cart_coverage'] = 'agent_observed_C-015_C-016'
        self.assertEqual(1, summarize(data)['groups'][0]['quality_pass'])

    def test_unknown_values_do_not_become_zero(self):
        self.assertEqual(distribution([None,None])['n'],0)
        self.assertIsNone(distribution([None])['mean'])
        self.assertEqual(distribution([0,None,4])['mean'],2)
        self.assertIsNone(distribution([4])['sd'])

    def test_failed_quality_stays_in_primary_and_supplement_is_separate(self):
        rows=[run('explore',1,10,'fail'),run('preload',1,20),run('explained',1,None),
              run('explore',7,30,cohort='supplement')]
        result=summarize({'runs':rows,'calls':[],'actions':[]})
        primary=next(g for g in result['groups'] if g['cohort']=='primary18' and g['condition']=='explore')
        self.assertEqual(primary['total_tokens']['mean'],10)
        self.assertEqual(primary['quality_pass'],0)
        self.assertEqual(primary['success_only_total']['n'],0)
        self.assertTrue(all(b['difference'] is None for b in result['block_contrasts']))

    def test_human_selection_uses_median_and_earlier_tie(self):
        rows=[run('explore',1,10),run('explore',2,30),run('explore',3,1,'fail')]
        result=summarize({'runs':rows,'calls':[],'actions':[]})
        pick=result['human_review_selection'][0]
        self.assertEqual(pick['arm_median'],20)
        self.assertEqual(pick['run_id'],'MS1-001-explore-001')
        self.assertEqual(result['human_review_selection'][1]['human_review'],'no_eligible_pass_inspect_failures')

    def test_unstarted_slot_remains_in_denominator(self):
        result=summarize({'runs':[],'calls':[],'actions':[]},{'slots':[{'run_id':'x','slot':1,'condition':'explore'}]})
        self.assertEqual(result['slots'][0]['status'],'not_started')
        self.assertIsNone(result['slots'][0]['total_tokens'])


if __name__=='__main__':
    unittest.main()
