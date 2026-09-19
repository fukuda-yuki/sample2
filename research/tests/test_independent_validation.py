import copy
import json
from pathlib import Path
import tempfile
import unittest

from research.validate import validate, digest, TOKEN_KEYS


class IndependentAuditTests(unittest.TestCase):
    def write(self, name, data):
        p = self.root/name; p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text(json.dumps(data),encoding='utf-8'); return p

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); run = self.root/'run'
        self.write('run/manifest.json',{'run_id':'run','run_instance_id':'instance'})
        self.write('run/condition.json',{'runtime':{'model_id':'model'}})
        events, calls = [], []
        for i, (ip,op) in enumerate([(100,10),(200,20)]):
            rid = 'req'+str(i)
            req = self.write('run/usage/raw/'+rid+'.request.json',{'model':'model'})
            res = run/'usage/raw'/(rid+'.response.sse')
            res.write_text('data: '+json.dumps({'model':'model','usage':{'prompt_tokens':ip,'completion_tokens':op}})+'\ndata: [DONE]\n',encoding='utf-8')
            usage = {k:None for k in TOKEN_KEYS}; usage.update(input_tokens=ip,output_tokens=op)
            e = {'run_id':'run','session_id':'instance','request_id':rid,'event_id':rid,'model_id':'model',
                'request_file':req.name,'response_file':res.name,'request_sha256':digest(req),'response_sha256':digest(res),
                'status':'completed','usage':usage}
            events.append(e)
            calls.append({'run_id':'run','run_instance_id':'instance','cohort':'pilot','request_id':rid,**usage,
                'request_ref':'usage/raw/'+req.name,'response_ref':'usage/raw/'+res.name})
        for name in ('usage/raw/started.jsonl','usage/raw/events.jsonl','usage/events.jsonl'):
            p=run/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(''.join(json.dumps(e)+'\n' for e in events),encoding='utf-8')
        self.write('run/usage/normalized.json',{'usage_complete':True,'observed_request_count':2,'observed_tokens':330,
            'input_tokens':300,'output_tokens':30,'cache_read_tokens':None,'cache_write_tokens':None,'reasoning_tokens':None})
        self.data = {'runs':[{'run_id':'run','run_instance_id':'instance','cohort':'pilot','calls':2,'audit_issues':[],
            'usage_complete':True,'input_tokens':300,'output_tokens':30,'total_tokens':330,
            'observed_input_tokens':300,'observed_output_tokens':30}], 'calls':calls}
        self.source=self.write('analysis.json',self.data)
        self.inventory={'groups':{'g':{'source_hashes':'receipts.json'}},'runs':[{'group':'g','cohort':'pilot',
            'run_id':'run','run_instance_id':'instance','root':'run','manifest_sha256':digest(run/'manifest.json')}]}
        self.refresh_receipts()

    def refresh_receipts(self):
        hashes={p.relative_to(self.root/'run').as_posix():digest(p) for p in (self.root/'run').rglob('*') if p.is_file()}
        p=self.write('receipts.json',{'run':hashes});self.inventory['groups']['g']['source_hashes_sha256']=digest(p)

    def audit(self):
        self.write('analysis.json',self.data)
        return validate(self.source,self.inventory,self.root,'g')

    def assert_bad(self, marker):
        result=self.audit();self.assertFalse(result['pass']);self.assertTrue(any(marker in e for e in result['failures']),result['failures'])

    def test_control(self): self.assertTrue(self.audit()['pass'])

    def test_omitted_call_and_adjusted_analysis_totals_cannot_pass(self):
        self.data['calls'].pop();r=self.data['runs'][0]
        r.update(calls=1,input_tokens=100,output_tokens=10,total_tokens=110,observed_input_tokens=100,observed_output_tokens=10)
        self.assert_bad('analysis_call_inventory')

    def test_whole_run_omission_cannot_pass(self):
        self.data={'runs':[],'calls':[]};self.assert_bad('analysis_run_inventory')

    def test_duplicate_call_cannot_pass(self):
        self.data['calls'].append(copy.deepcopy(self.data['calls'][0]));self.assert_bad('analysis_call_inventory')

    def test_foreign_run_call_cannot_pass(self):
        self.data['calls'][0]['run_instance_id']='other';self.assert_bad('foreign_analysis_call')

    def test_orphan_original_even_with_refreshed_hashes_cannot_pass(self):
        self.write('run/usage/raw/orphan.request.json',{});self.refresh_receipts();self.assert_bad('orphan_or_missing_original')

    def test_broken_sse_even_with_refreshed_hashes_cannot_pass(self):
        p=self.root/'run/usage/raw/req0.response.sse';p.write_text(p.read_text()+'data: {\n',encoding='utf-8')
        self.refresh_receipts();self.assert_bad('invalid_sse')

    def test_normalized_sum_mismatch_cannot_pass(self):
        p=self.root/'run/usage/normalized.json';n=json.loads(p.read_text());n['input_tokens']=301
        self.write('run/usage/normalized.json',n);self.refresh_receipts();self.assert_bad('normalized_sum:input_tokens')

    def test_unexpected_analysis_issue_fails_completion_gate(self):
        self.data['runs'][0]['audit_issues']=['unexplained_join_error'];self.assert_bad('analysis_audit')

    def test_missing_usage_is_not_zero(self):
        p=self.root/'run/usage/raw/req0.response.sse';p.write_text('data: {"choices":[]}\ndata: [DONE]\n',encoding='utf-8')
        self.refresh_receipts();self.assert_bad('unreported_usage')

    def test_root_relocation_does_not_need_analysis_absolute_paths(self):
        self.data['runs'][0]['root']='C:/unavailable/original';self.assertTrue(self.audit()['pass'])
