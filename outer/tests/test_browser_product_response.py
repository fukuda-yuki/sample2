"""Finite response evidence does not turn unrelated observer faults into product facts."""
import copy
import json
import io
import urllib.error
import subprocess
import shutil
import tempfile
import unittest
from pathlib import Path
try:
    from . import support
except ImportError:
    import support
from harness import browser_product, education_browser as school, browser_cart, util


class ProductResponseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.receipt = {'schemaVersion': 1, 'actor': 'agent', 'runInstanceId': 'run',
            'artifactSha256': 'artifact', 'specSha256': 'spec', 'baseUrl': 'http://127.0.0.1:1234',
            'productFailures': [], 'faults': ['independent screenshot failure']}
        event = {'caseId': 'create-form', 'checkId': 'E-012', 'operation': 'school-create-form',
            'method': 'GET', 'url': 'http://127.0.0.1:1234/Student/Create', 'status': 500,
            'clickConfirmed': False, 'resourceType': 'document', 'requestPayload': None, 'responseBody': 'missing Create view'}
        self.receipt['evaluationVersion'] = 'education-1.1.0'
        util.write_new_json(self.root/'request.json', {k: self.receipt[k] for k in
            ('runInstanceId', 'artifactSha256', 'specSha256', 'baseUrl', 'evaluationVersion')})
        self.receipt['requestSha256'] = util.sha256_file(self.root/'request.json')
        util.write_new_json(self.root/'response.json', event)
        self.receipt['productFailures'] = [{k: event[k] for k in
            ('caseId', 'checkId', 'operation', 'method', 'url', 'status', 'clickConfirmed')} | {
                'evidence': {'path': 'response.json', 'sha256': util.sha256_file(self.root/'response.json')}}]

    def test_bound_product_failure_survives_separate_observer_fault_without_complete_coverage(self):
        self.assertEqual(['E-012'], browser_product.validated_checks(self.root, self.receipt, 'run', 'artifact', 'spec'))
        self.assertFalse(school.coverage_complete({'researchStatus': 'incomplete', 'browserReviewCoverage': 'evaluator_fault'}))

    def test_fake_foreign_route_method_hash_and_identity_are_not_product_evidence(self):
        for key, value in [('url', 'http://localhost:9999/Student/Create'), ('method', 'POST'),
                           ('operation', 'unrecognised'), ('status', 200), ('checkId', 'C-015')]:
            with self.subTest(key=key):
                receipt = copy.deepcopy(self.receipt); receipt['productFailures'][0][key] = value
                self.assertEqual([], browser_product.validated_checks(self.root, receipt, 'run', 'artifact', 'spec'))
        self.assertEqual([], browser_product.validated_checks(self.root, self.receipt, 'wrong-run', 'artifact', 'spec'))
        (self.root/'response.json').write_text('changed')
        self.assertEqual([], browser_product.validated_checks(self.root, self.receipt, 'run', 'artifact', 'spec'))

    def test_later_damaged_evidence_and_body_read_fault_cannot_erase_prior_failure(self):
        evidence = util.read_json(self.root/'response.json')
        evidence.pop('responseBody'); evidence['bodyReadError'] = 'observer stream closed'
        util.write_json_atomic(self.root/'response.json', evidence)
        self.receipt['productFailures'][0]['evidence']['sha256'] = util.sha256_file(self.root/'response.json')
        self.receipt['productFailures'].append({'evidence': {'path': 'missing'}})
        self.assertEqual(['E-012'], browser_product.validated_checks(self.root, self.receipt, 'run', 'artifact', 'spec'))

    def test_stored_school_partial_product_failure_is_bound_and_cannot_import_unobserved_failure(self):
        result = self.root/'assessment'; result.mkdir()
        review = result/'browser-school'; review.mkdir()
        for name in ('request.json', 'response.json'): shutil.copyfile(self.root/name, review/name)
        self.receipt['action'] = 'product-http-failed'
        util.write_new_json(review/'receipt.json', self.receipt)
        baseline=result/'http-only'; baseline.mkdir()
        util.write_new_json(baseline/'evaluation.json', {'artifactSha256':'artifact','specSha256':'spec',
            'requirements':[{'id':'EDU-R-005','judgement':'pass'}], 'criticalFailed':[]})
        (baseline/'results.jsonl').write_text('immutable HTTP baseline')
        output={'evaluationVersion':'education-1.1.0','reviewRunInstanceId':'run','artifactSha256':'artifact',
            'specSha256':'spec','researchStatus':'incomplete','browserReviewCoverage':'evaluator_fault',
            'browserReviewEvidenceSha256':util.sha256_file(review/'receipt.json'),
            'baselineEvaluationSha256':util.sha256_file(baseline/'evaluation.json'),
            'baselineResultsSha256':util.sha256_file(baseline/'results.jsonl'),
            'requirements':[{'id':'EDU-R-012','judgement':'fail'},{'id':'EDU-R-005','judgement':'fail'}],
            'criticalFailed':['EDU-R-005']}
        util.write_new_json(result/'evaluation.json',output)
        failure=school.stored_failure(result,'run','artifact','spec',util.sha256_file(result/'evaluation.json'))
        self.assertEqual({'verdict':'fail','requirements':['EDU-R-012'],'source':'composed-product-http'},failure)
        (review/'response.json').write_text('tampered')
        self.assertIsNone(school.stored_failure(result,'run','artifact','spec',util.sha256_file(result/'evaluation.json')))

    def test_response_recorder_separates_status_fact_from_body_failure_and_click_attempt(self):
        helper = Path(__file__).resolve().parents[2]/'inner/browser/product-response.cjs'
        script = '''const { recorder } = require(process.argv[1]);
const assert = require('node:assert/strict'), {EventEmitter}=require('node:events');
(async()=>{const page=new EventEmitter(), saved={}, receipt={faults:[],productFailures:[]};
const r=recorder(page,{baseUrl:'http://127.0.0.1:1234'},receipt,(n,v)=>{saved[n]=v},n=>({path:n,sha256:'test-only'}),()=> 'sha');
const op={caseId:'remove',checkId:'C-015',operation:'cart-remove',method:'POST',path:'/ShoppingCart/RemoveFromCart',clickConfirmed:false};
r.set(op);
const request={method:()=> 'POST',url:()=> 'http://127.0.0.1:1234/ShoppingCart/RemoveFromCart',resourceType:()=> 'xhr',postData:()=> 'id=1'};
page.emit('request',request); page.emit('response',{request:()=>request,url:request.url,status:()=>500,body:async()=>{throw Error('stream closed')}});
r.confirm('remove'); await r.flush(); await r.flush();
assert.equal(receipt.productFailures.length,1); assert.equal(receipt.productFailures[0].clickConfirmed,true);
assert.equal(receipt.faults.length,1); assert(Object.values(saved)[0].bodyReadError);
// Uncompleted interaction cannot invent a confirmed click.
r.set({...op,caseId:'attempt',clickConfirmed:false});
const req2={...request}; page.emit('request',req2);page.emit('response',{request:()=>req2,url:request.url,status:()=>500,body:async()=>Buffer.from('500')});
await r.flush(); assert.equal(receipt.productFailures[1].clickConfirmed,false);
})().catch(e=>{console.error(e);process.exitCode=1});'''
        result = subprocess.run(['node', '-e', script, str(helper)], capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_js_classification_requires_response_to_exact_measured_operation(self):
        helper = Path(__file__).resolve().parents[2]/'inner/browser/product-response.cjs'
        script = '''const { productResponse } = require(process.argv[1]);
const assert = require('node:assert/strict');
const operation={caseId:'create-form',checkId:'E-012',operation:'school-create-form',method:'GET',path:'/Student/Create'};
const actual={method:'GET',url:'http://127.0.0.1:1234/Student/Create',status:500,resourceType:'document'};
assert(productResponse('http://127.0.0.1:1234',operation,actual));
for (const extra of [{status:200},{url:'http://other/Student/Create'},{url:'http://127.0.0.1:1234/favicon.ico'},{method:'POST'},{resourceType:'script'}])
  assert.equal(productResponse('http://127.0.0.1:1234',operation,{...actual,...extra}),null);
assert.equal(productResponse('http://127.0.0.1:1234',null,actual),null);'''
        result = subprocess.run(['node', '-e', script, str(helper)], capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_music_15_binds_owned_product_response_and_rejects_relabelled_request(self):
        event=util.read_json(self.root/'response.json')
        event.update(caseId='C-015-add-1',checkId='C-012',operation='cart-add',
                     url='http://127.0.0.1:1234/ShoppingCart/AddToCart/1')
        util.write_json_atomic(self.root/'response.json',event)
        self.receipt['evaluationVersion']='1.5.0'
        self.receipt['productFailures']=[{key:event[key] for key in
            ('caseId','checkId','operation','method','url','status','clickConfirmed')} | {
                'evidence':{'path':'response.json','sha256':util.sha256_file(self.root/'response.json')}}]
        request={key:self.receipt[key] for key in ('runInstanceId','artifactSha256','specSha256','evaluationVersion','baseUrl')}
        util.write_json_atomic(self.root/'request.json',request)
        self.receipt['requestSha256']=util.sha256_file(self.root/'request.json')
        self.assertEqual(['C-012'],browser_product.validated_checks(self.root,self.receipt,'run','artifact','spec'))
        self.receipt['evaluationVersion']='1.4.0'
        self.assertEqual([],browser_product.validated_checks(self.root,self.receipt,'run','artifact','spec'))
        request['evaluationVersion']=self.receipt['evaluationVersion']='1.6.0'
        util.write_json_atomic(self.root/'request.json',request)
        self.receipt['requestSha256']=util.sha256_file(self.root/'request.json')
        self.assertEqual([],browser_product.validated_checks(self.root,self.receipt,'run','artifact','spec'))

    def test_cart_15_receipt_inherits_schema_three_without_starting_a_real_browser(self):
        collector=Path(__file__).resolve().parents[2]/'inner/browser/cart-review.cjs'
        script='''const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
(async()=>{const file=process.argv[1],root=process.argv[2],source=fs.readFileSync(file,'utf8');
const executable=path.join(root,'fixture-browser-bytes');fs.writeFileSync(executable,'finite fixture; never execute');
for(const version of ['1.3.0','1.4.0','1.5.0']){
 const directory=path.join(root,'receipt-'+version);fs.mkdirSync(directory);
 const input=path.join(directory,'request.json');fs.writeFileSync(input,JSON.stringify({evaluationVersion:version,runInstanceId:'fixture',artifactSha256:'artifact',specSha256:'spec',baseUrl:'http://127.0.0.1:1234'}));
 const fixtureProcess={argv:['node',file,input,directory],version:'fixture-node',env:{},exitCode:0};
 const fixtureRequire=name=>name==='playwright'?{chromium:{executablePath:()=>executable,launch:async()=>{throw Error('finite observer fixture: browser never started')}}}:name==='playwright/package.json'?{version:'fixture-playwright'}:name==='./product-response.cjs'?require(path.join(path.dirname(file),'product-response.cjs')):require(name);
 await vm.runInNewContext(source,{require:fixtureRequire,__filename:file,__dirname:path.dirname(file),process:fixtureProcess,Buffer,URL,performance,setTimeout});
 const receipt=JSON.parse(fs.readFileSync(path.join(directory,'receipt.json'),'utf8'));
 assert.equal(receipt.schemaVersion,version==='1.3.0'?2:3);
 assert.equal(receipt.conditions.collectorVersion,version==='1.3.0'?'1.2.1':version);
 assert.equal(receipt.faults.length,1);assert.equal(fixtureProcess.exitCode,2);
 if(version!=='1.3.0'){assert.equal(receipt.evaluationVersion,version);assert(receipt.requestSha256);assert.deepEqual(receipt.productFailures,[]);}
}
})().catch(error=>{console.error(error);process.exitCode=1});'''
        result=subprocess.run(['node','-e',script,str(collector),str(self.root)],capture_output=True,text=True)
        self.assertEqual(0,result.returncode,result.stderr)


class DateRepresentationTests(unittest.TestCase):
    def test_date_semantics_only_for_new_contract_and_date_columns(self):
        self.assertTrue(school._equal('2020-01-02', '2020-01-02 00:00:00',
                                     table='Students', column='EnrollmentDate', version='education-1.1.0'))
        self.assertTrue(school._equal('2020-01-02', '2020-01-02T00:00:00',
                                     table='Students', column='EnrollmentDate', version='education-1.1.0'))
        for zeroes in (1, 3, 7, 8):
            self.assertTrue(school._equal('2020-01-02', '2020-01-02T00:00:00.'+'0'*zeroes,
                table='Departments', column='StartDate', version='education-1.1.0'))
            self.assertFalse(school._equal('2020-01-02', '2020-01-02T00:00:00.'+'0'*zeroes+'1',
                table='Departments', column='StartDate', version='education-1.1.0'))
        for actual in ('2020-01-02 01:00:00', '2020-01-02T00:00:00Z', '2020-01-03', '2020-02-31'):
            self.assertFalse(school._equal('2020-01-02', actual,
                table='Students', column='EnrollmentDate', version='education-1.1.0'))
        self.assertFalse(school._equal('2020-01-02', '2020-01-02 00:00:00',
                                      table='Students', column='LastName', version='education-1.1.0'))
        self.assertFalse(school._equal('2020-01-02', '2020-01-02 00:00:00'))


class ReadinessDiagnosticTests(unittest.TestCase):
    def test_observed_500_is_separate_from_transport_error_and_not_workflow_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            events = iter([OSError('connection not observed'),
                urllib.error.HTTPError('http://127.0.0.1:1234/',500,'Internal error',{},io.BytesIO(b'owned server 500'))])
            ticks = [0]
            def opener(*args,**kwargs): raise next(events)
            def sleep(amount): ticks[0] += amount
            output = Path(directory)/'readiness.json'
            self.assertFalse(browser_product.wait_ready('http://127.0.0.1:1234',output,seconds=.5,
                opener=opener,clock=lambda:ticks[0],sleep=sleep))
            observed=util.read_json(output)
            self.assertEqual(['transport_unobserved','observed_product_http_failure'],
                [r['classification'] for r in observed['observations']])
            self.assertNotIn('productFailures',observed)
            self.assertIn('no browser workflow',observed['qualityInference'])

    def test_foreign_redirect_target_cannot_become_ready_or_owned_500(self):
        class Foreign(io.BytesIO):
            status=500
            def geturl(self): return 'http://other.example/'
        with tempfile.TemporaryDirectory() as directory:
            ticks=[0]
            def sleep(amount): ticks[0] += amount
            output=Path(directory)/'readiness.json'
            self.assertFalse(browser_product.wait_ready('http://127.0.0.1:1234',output,seconds=.25,
                opener=lambda *a,**k:Foreign(b'foreign'),clock=lambda:ticks[0],sleep=sleep))
            self.assertEqual('transport_unobserved',util.read_json(output)['observations'][0]['classification'])


class ExistingAttemptPreservationTests(unittest.TestCase):
    def test_refuse_existing_output_before_creating_or_updating_lease_files(self):
        for module in (school,browser_cart):
            with self.subTest(module=module.__name__), tempfile.TemporaryDirectory() as directory:
                root=Path(directory)
                (root/'evaluation.json').write_text('original partial or fault result, immutable')
                before=util.tree_hashes(root)
                with self.assertRaises(FileExistsError):
                    module.complete_evaluation(root,{},root,root,root,root,root,'new-attempt',2)
                self.assertEqual(before,util.tree_hashes(root))


if __name__ == '__main__': unittest.main()
