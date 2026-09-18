import unittest
from research.ledger import validate_schedule


class ScheduleContracts(unittest.TestCase):
    def setUp(self):
        self.slots=[{'run_id':str(i),'slot':i+1,'cohort':'primary18','condition':'explore'} for i in range(18)]
        self.plan={'slots':self.slots,'maximum_supplements':6}

    def events(self):
        result=[]
        for s in self.slots:
            result.extend([{'kind':'dispatch','case':s},
                           {'kind':'result','case':s,'disposition':'technical' if s['slot']==2 else 'observed'}])
        return result

    def test_only_technical_failure_can_receive_one_late_supplement(self):
        events=self.events()
        case={'cohort':'supplement','condition':'explore','run_id':'extra','replacement_for':'1'}
        events.append({'kind':'dispatch','case':case})
        self.assertEqual(validate_schedule(events,self.plan),[])
        case['replacement_for']='0'
        self.assertIn('supplement_for_ineligible_run:extra',validate_schedule(events,self.plan))

    def test_early_and_duplicate_dispatch_are_detected(self):
        events=[{'kind':'dispatch','case':self.slots[0]}, {'kind':'dispatch','case':self.slots[0]}]
        issues=validate_schedule(events,self.plan)
        self.assertIn('overlapping_dispatch:0',issues)
        self.assertIn('replayed_dispatch:0',issues)

    def test_changed_order_is_not_silently_accepted(self):
        events=self.events()
        events[0],events[2]=events[2],events[0]
        self.assertIn('initial_order_or_identity_changed',validate_schedule(events,self.plan))


if __name__=='__main__':
    unittest.main()
