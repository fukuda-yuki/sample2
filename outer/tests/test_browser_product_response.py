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
        request['evaluationVersion']=self.receipt['evaluationVersion']='1.7.0'
        util.write_json_atomic(self.root/'request.json',request)
        self.receipt['requestSha256']=util.sha256_file(self.root/'request.json')
        self.assertEqual([],browser_product.validated_checks(self.root,self.receipt,'run','artifact','spec'))

    def test_music_16_request_binding_retains_prior_versions_and_rejects_future_or_cross_version(self):
        event=util.read_json(self.root/'response.json')
        event.update(caseId='C-015-add-1',checkId='C-012',operation='cart-add',
                     url='http://127.0.0.1:1234/ShoppingCart/AddToCart/1')
        util.write_json_atomic(self.root/'response.json',event)
        self.receipt['productFailures']=[{key:event[key] for key in
            ('caseId','checkId','operation','method','url','status','clickConfirmed')} | {
                'evidence':{'path':'response.json','sha256':util.sha256_file(self.root/'response.json')}}]
        for version in ('1.4.0','1.5.0','1.6.0','1.7.0'):
            with self.subTest(version=version):
                self.receipt['evaluationVersion']=version
                request={key:self.receipt[key] for key in ('runInstanceId','artifactSha256','specSha256','evaluationVersion','baseUrl')}
                util.write_json_atomic(self.root/'request.json',request)
                self.receipt['requestSha256']=util.sha256_file(self.root/'request.json')
                expected=[] if version=='1.7.0' else ['C-012']
                self.assertEqual(expected,browser_product.validated_checks(self.root,self.receipt,'run','artifact','spec'))
        self.receipt['evaluationVersion']='1.6.0' # Request remains 1.7; changing a receipt cannot relabel it.
        self.assertEqual([],browser_product.validated_checks(self.root,self.receipt,'run','artifact','spec'))

    def test_cart_15_receipt_inherits_schema_three_without_starting_a_real_browser(self):
        collector=Path(__file__).resolve().parents[2]/'inner/browser/cart-review.cjs'
        script='''const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
(async()=>{const file=process.argv[1],root=process.argv[2],source=fs.readFileSync(file,'utf8');
const executable=path.join(root,'fixture-browser-bytes');fs.writeFileSync(executable,'finite fixture; never execute');
for(const version of ['1.3.0','1.4.0','1.5.0','1.6.0']){
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

    def test_music_16_currency_money_is_exact_bounded_and_preserves_legacy_interpretations(self):
        collector=Path(__file__).resolve().parents[2]/'inner/browser/cart-review.cjs'
        cases=[
            {'text':text,'kind':'known','minor':minor} for text,minor in [
                ('21.75','2175'),('$21.75','2175'),('$ 21.75','2175'),('21.75 $','2175'),
                ('-$21.75','-2175'),('$-21.75','-2175'),('-21.75$','-2175'),('+€21.75','2175'),
                ('  £00021.75  ','2175'),('¥0.00','0'),('-$0.00','0'),('- $ 21.75','-2175'),
                ('$ - 21.75','-2175'),('- 21.75','-2175'),
                ('792281625142643375935439503.35','79228162514264337593543950335')]]
        cases += [{'text':text,'kind':'unknown'} for text in
            ('21.75 or 30.00','USD21.75','1,234.56','(21.75)','$$21.75','-$-21.75','21.75-$',
             '$21.75€','792281625142643375935439503.36')]
        cases += [{'text':text,'kind':'invalid'} for text in ('21.7','21.750','21','$21.7','21.750$','',None)]
        script='''const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const file=process.argv[1],root=process.argv[2],cases=JSON.parse(process.argv[3]);
const source=fs.readFileSync(file,'utf8').split('(async () => {')[0];
function context(version){const request=path.join(root,'money-'+version+'.json');
 fs.writeFileSync(request,JSON.stringify({evaluationVersion:version,price:7.25,albumId:1,requireCartStatus:true,structuralPrecondition:true}));
 const fixtureRequire=name=>name==='playwright'?{chromium:{}}:name==='playwright/package.json'?{version:'fixture'}:name==='./product-response.cjs'?require(path.join(path.dirname(file),'product-response.cjs')):require(name);
 const c=vm.createContext({require:fixtureRequire,__filename:file,__dirname:path.dirname(file),process:{argv:['node',file,request,root],version:'fixture'},URL,Buffer,setTimeout});
 vm.runInContext(source,c);return c;
}
const current=context('1.6.0'),parse=vm.runInContext('(text)=>moneyObservation(text)',current);
for(const item of cases){const actual=parse(item.text);assert.equal(actual.kind,item.kind,item.text);if(item.minor!==undefined)assert.equal(actual.minor,item.minor,item.text);}
const state={totals:['$14.50'],cartStatus:['Cart (2)'],rows:[{id:'row-1',count:'2',album:'/Store/Details/1'}],possibleControls:[],rowMarkerObservation:{kind:'known'}};
for(const version of ['1.4.0','1.5.0','1.6.0']){const c=context(version),matches=vm.runInContext('(state)=>matches(state,2)',c),populated=vm.runInContext('(state)=>populated(state,2)',c);
 assert.equal(matches(state),version==='1.6.0');assert.equal(populated(state),version==='1.6.0');
 assert.equal(matches({...state,totals:[]}),false);assert.equal(matches({...state,totals:['$99.99']}),false);
 if(version==='1.6.0'){assert.equal(populated({...state,totals:['$99.99']}),true);assert.equal(populated({...state,totals:['14.50 or 20.00']}),false);assert.equal(populated({...state,totals:['14.5']}),false);}
}'''
        result=subprocess.run(['node','-e',script,str(collector),str(self.root),json.dumps(cases)],capture_output=True,text=True)
        self.assertEqual(0,result.returncode,result.stderr)

    def test_music_16_generic_marked_rows_are_observed_and_malformed_rows_never_establish_empty(self):
        collector=Path(__file__).resolve().parents[2]/'inner/browser/cart-review.cjs'
        script='''const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
(async()=>{const file=process.argv[1],root=process.argv[2],source=fs.readFileSync(file,'utf8').split('(async () => {')[0];
function row(tag,id,count,links=['http://127.0.0.1:1234/Store/Details/1'],counterCopies=1,visible=true){
 const counters=count===undefined?[]:Array.from({length:counterCopies},()=>({id:'item-count-'+id.slice(4),textContent:count}));
 const anchors=links.map(href=>({href}));
 return {tagName:tag,id,counters,outerHTML:'<'+tag.toLowerCase()+' id="'+id+'">'+counters.map(e=>'<span id="'+e.id+'">'+e.textContent+'</span>').join('')+anchors.map(e=>'<a href="'+e.href+'">Album</a>').join('')+'</'+tag.toLowerCase()+'>',
 getClientRects:()=>visible?[{}]:[],contains:e=>counters.includes(e),querySelector:q=>counters[0],querySelectorAll:q=>q==='a[href]'?anchors:counters};
}
function context(version){const request=path.join(root,'rows-'+version+'.json');fs.writeFileSync(request,JSON.stringify({evaluationVersion:version,price:7.25,albumId:1,requireCartStatus:true,structuralPrecondition:true}));
 const fixtureRequire=n=>n==='playwright'?{chromium:{}}:n==='playwright/package.json'?{version:'fixture'}:n==='./product-response.cjs'?require(path.join(path.dirname(file),'product-response.cjs')):require(n);
 const c=vm.createContext({require:fixtureRequire,__filename:file,__dirname:path.dirname(file),process:{argv:['node',file,request,root],version:'fixture'},URL,Buffer,setTimeout,getComputedStyle:()=>({visibility:'visible'}),location:{href:'http://127.0.0.1:1234/ShoppingCart'}});vm.runInContext(source,c);return c;
}
async function observe(c,rows,total,status,orphans=[]){const marker=text=>({textContent:text,outerHTML:'<span>'+text+'</span>',getClientRects:()=>[{}]});
 c.document={documentElement:{outerHTML:'synthetic DOM'},querySelectorAll:q=>q==='tr[id^="row-"]'?rows.filter(r=>r.tagName==='TR'):q==='[id^="row-"]'?rows:q==='[id^="item-count-"]'?orphans:q==='[id="cart-total"]'?[marker(total)]:q==='[id="cart-status"]'?[marker(status)]:[]};
 return vm.runInContext('observe',c)({evaluate:async(fn,arg)=>fn(arg)});
}
const c=context('1.6.0'),match=vm.runInContext('(s,n)=>matches(s,n)',c),populate=vm.runInContext('(s,n)=>populated(s,n)',c);
let state=await observe(c,[row('DIV','row-1','2')],'14.50','Cart (2)');
assert.equal(state.rows.length,1,'valid div marked row must not disappear');assert.equal(state.rowMarkerObservation.kind,'known');assert.equal(match(state,2),true);assert.equal(populate(state,2),true);
assert(state.visibleCartHtml.includes('<div id="row-1">'));
state=await observe(c,[row('DIV','row-1','1')],'7.25','Cart (1)');assert.equal(match(state,1),true);
state=await observe(c,[row('DIV','row-01','02',['http://127.0.0.1:1234/Store/Details/01/','http://127.0.0.1:1234/Store/Details/1'])],'14.50','Cart (2)');assert.equal(match(state,2),true,'same decoded ID links/counter aliases remain unambiguous');
for(const id of ['row-0','row-000']){state=await observe(c,[row('DIV',id,'2')],'14.50','Cart (2)');assert.equal(populate(state,2),false,'zero is decoded but cannot establish a positive owned removal identity');assert.equal(match(state,2),false);}
for(const rows of [[row('DIV','row-bad','1')],[row('DIV','row-1',undefined)],[row('DIV','row-1','not-an-int')],
 [row('DIV','row-1','1',[],1)],[row('DIV','row-1','1',undefined,2)],
 [row('DIV','row-1','1',['http://127.0.0.1:1234/Store/Details/1','http://127.0.0.1:1234/Store/Details/2'])],
 [row('DIV','row-1','1'),row('DIV','row-1','1')]]){
 state=await observe(c,rows,'0.00','Cart (0)');assert(state.rows.length>0);assert.equal(state.rowMarkerObservation.kind,'unknown');assert.equal(match(state,0),false);assert.equal(populate(state,1),false);
}
const orphan={id:'item-count-1',textContent:'1',outerHTML:'<span id="item-count-1">1</span>',getClientRects:()=>[{}]};
state=await observe(c,[],'0.00','Cart (0)',[orphan]);assert.equal(state.rowMarkerObservation.kind,'unknown');assert.equal(match(state,0),false);assert(state.visibleCartHtml.includes(orphan.outerHTML));
state=await observe(c,[row('DIV','row-1','1',undefined,1,false)],'0.00','Cart (0)');assert.equal(state.rows.length,0);assert.equal(match(state,0),true);
for(const version of ['1.4.0','1.5.0']){const old=context(version),oldMatch=vm.runInContext('(s,n)=>matches(s,n)',old);
 const div=await observe(old,[row('DIV','row-1','1')],'0.00','Cart (0)');assert.equal(div.rows.length,0);assert.equal(oldMatch(div,0),true);assert.equal(div.rowMarkerObservation,undefined);
 const table=await observe(old,[row('TR','row-1','1')],'7.25','Cart (1)');assert.equal(oldMatch(table,1),true);
}
})().catch(e=>{console.error(e);process.exitCode=1});'''
        result=subprocess.run(['node','-e',script,str(collector),str(self.root)],capture_output=True,text=True)
        self.assertEqual(0,result.returncode,result.stderr)

    def test_music_16_projection_preserves_table_markers_and_dom_identity(self):
        collector=Path(__file__).resolve().parents[2]/'inner/browser/cart-review.cjs'
        script='''const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
(async()=>{const file=process.argv[1],root=process.argv[2],source=fs.readFileSync(file,'utf8').split('(async () => {')[0];
function node(tag,id,text,children=[]){return {tagName:tag,id,textContent:text,children,
 outerHTML:'<'+tag.toLowerCase()+' id="'+id+'">'+text+children.map(e=>e.outerHTML).join('')+'</'+tag.toLowerCase()+'>',
 getClientRects:()=>[{}],contains(e){return children.some(child=>child===e||child.contains(e));},
 querySelectorAll(q){const all=children.flatMap(e=>[e,...e.querySelectorAll('*')]);return q==='*'?all:q==='a[href]'?all.filter(e=>e.href):all.filter(e=>e.id.startsWith('item-count-'));},querySelector(){return null;}};}
function context(version){const request=path.join(root,'projection-'+version+'.json');fs.writeFileSync(request,JSON.stringify({evaluationVersion:version}));
 const fixtureRequire=n=>n==='playwright'?{chromium:{}}:n==='playwright/package.json'?{version:'fixture'}:n==='./product-response.cjs'?require(path.join(path.dirname(file),'product-response.cjs')):require(n);
 const c=vm.createContext({require:fixtureRequire,__filename:file,__dirname:path.dirname(file),process:{argv:['node',file,request,root],version:'fixture'},URL,Buffer,setTimeout,getComputedStyle:()=>({visibility:'visible'}),location:{href:'http://127.0.0.1:1234/ShoppingCart'}});vm.runInContext(source,c);return c;}
async function observed(c,{rows=[],totals=[],status=[],orphans=[]}){c.document={documentElement:{outerHTML:'finite native DOM'},querySelectorAll:q=>q==='[id^="row-"]'?rows:q==='tr[id^="row-"]'?rows.filter(e=>e.tagName==='TR'):q==='[id="cart-total"]'?totals:q==='[id="cart-status"]'?status:q==='[id^="item-count-"]'?orphans:[]};return vm.runInContext('observe',c)({evaluate:async(fn,arg)=>fn(arg)});}
const c=context('1.6.0');
const save=(name,state)=>fs.writeFileSync(path.join(root,'finite-'+name+'.json'),JSON.stringify({page:state}));
const wrappers={TD:['<table><tbody><tr>','</tr></tbody></table>'],TH:['<table><tbody><tr>','</tr></tbody></table>'],TR:['<table><tbody>','</tbody></table>'],TBODY:['<table>','</table>'],THEAD:['<table>','</table>'],TFOOT:['<table>','</table>'],CAPTION:['<table>','</table>'],COLGROUP:['<table>','</table>'],COL:['<table><colgroup>','</colgroup></table>'],DIV:['','']};
for(const [tag,[prefix,suffix]] of Object.entries(wrappers)){
 const total=node(tag,'cart-total','$14.50'),status=node(tag,'cart-status','Cart (2)'),orphan=node(tag,'item-count-999','1');
 const state=await observed(c,{totals:[total],status:[status],orphans:[orphan]});
 assert.equal(state.visibleCartHtml,'<section>'+[total,status,orphan].map(e=>prefix+e.outerHTML+suffix).join('')+'</section>',tag+' markers require valid table ancestry');
 assert.equal(state.totals[0],'$14.50');assert.equal(state.cartStatus[0],'Cart (2)');assert.equal(state.rowMarkerObservation.kind,'unknown');
}
const total=node('TD','cart-total','14.50'),duplicate=node('TD','cart-total','7.25');
let state=await observed(c,{totals:[total,duplicate]});assert.equal((state.visibleCartHtml.match(/id="cart-total"/g)||[]).length,2,'genuine duplicate IDs must remain');assert.equal(state.totals.length,2);save('duplicate-totals',state);
state=await observed(c,{});assert.equal(state.visibleCartHtml,'<section></section>');assert.equal(state.totals.length,0,'no monetary marker can be synthesized');save('missing-total',state);
state=await observed(c,{totals:[node('TD','cart-total','')]});assert.equal(state.totals[0],'');save('empty-total',state);
const contained=node('TD','cart-total','14.50'),row=node('TR','row-bad','',[contained]);
state=await observed(c,{rows:[row],totals:[contained]});assert.equal((state.visibleCartHtml.match(/id="cart-total"/g)||[]).length,1,'a native node inside a projected row must appear once');assert(state.visibleCartHtml.includes('id="row-bad"'));assert.equal(state.rowMarkerObservation.kind,'unknown');save('malformed-contained-row',state);
const anchor=node('A','','Album');anchor.href='http://127.0.0.1:1234/Store/Details/1';anchor.outerHTML='<a href="/Store/Details/1">Album</a>';
const validRow=node('DIV','row-1','',[node('SPAN','item-count-1','2'),anchor]);
for(const tag of ['TD','DIV']){state=await observed(c,{rows:[validRow],totals:[node(tag,'cart-total','$14.50')],status:[node('DIV','cart-status','Cart (2)')]});assert.equal(state.rowMarkerObservation.kind,'known');assert.equal(state.rows[0].count,'2');save('currency-'+tag.toLowerCase(),state);}
const nested=node('DIV','row-duplicate','',[node('DIV','row-duplicate','')]);
state=await observed(c,{rows:[nested,nested.children[0]]});assert.equal((state.visibleCartHtml.match(/id="row-duplicate"/g)||[]).length,2,'containment removes repeated projection, never actual duplicate markers');
for(const version of ['1.4.0','1.5.0']){const old=context(version);state=await observed(old,{totals:[total],status:[node('TD','cart-status','Cart (2)')]});assert.equal(state.visibleCartHtml,'<table><tr>'+total.outerHTML+'</tr></table><td id="cart-status">Cart (2)</td>','historical byte behavior');}
})().catch(e=>{console.error(e);process.exitCode=1});'''
        result=subprocess.run(['node','-e',script,str(collector),str(self.root)],capture_output=True,text=True)
        self.assertEqual(0,result.returncode,result.stderr)

    def test_music_16_click_locator_follows_generic_marker_and_unsupported_rows_remain_partial(self):
        collector=Path(__file__).resolve().parents[2]/'inner/browser/cart-review.cjs'
        script='''const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
(async()=>{const file=process.argv[1],root=process.argv[2],source=fs.readFileSync(file,'utf8');
for(const [version,malformed] of [['1.4.0',false],['1.5.0',false],['1.6.0',false],['1.6.0',true],['1.6.0','zero'],['1.6.0','zero-alias']]){
 const out=path.join(root,'flow-'+version+'-'+malformed);fs.mkdirSync(out);const request=path.join(out,'request.json');
 fs.writeFileSync(request,JSON.stringify({evaluationVersion:version,price:7.25,albumId:1,requireCartStatus:true,structuralPrecondition:true,baseUrl:'http://127.0.0.1:1234',runInstanceId:'fixture',artifactSha256:'fixture',specSha256:'fixture'}));
 const executable=path.join(out,'fixture-browser');fs.writeFileSync(executable,'finite VM placeholder: no actual browser');
 const fixtureProcess={argv:['node',file,request,out],version:'fixture',env:{},exitCode:0};let clock=0,clicks=0;let c;
 const visible={getClientRects:()=>[{}]};
 const browser={version:()=> 'finite-vm',close:async()=>{},newContext:async()=>{let quantity=0;
   function document(){const id=malformed===true?'row-bad':malformed==='zero'?'row-0':malformed==='zero-alias'?'row-000':'row-1';const count={...visible,id:'item-count-'+id.slice(4),textContent:String(quantity)};
     const row={...visible,tagName:version==='1.6.0'?'DIV':'TR',id,outerHTML:'<div id="'+id+'"><span id="'+count.id+'">'+quantity+'</span><a href="/Store/Details/1">Album</a></div>',
       contains:e=>e===count,querySelector:()=>count,querySelectorAll:q=>q==='a[href]'?[{href:'http://127.0.0.1:1234/Store/Details/1'}]:[count]};
     const rows=quantity>0||malformed===true?[row]:[];const marker=text=>({...visible,textContent:text,outerHTML:'<span>'+text+'</span>'});
     return {documentElement:{outerHTML:'finite synthetic DOM'},querySelectorAll:q=>q==='[id^="row-"]'?rows:q==='tr[id^="row-"]'?rows.filter(r=>r.tagName==='TR'):q==='[id^="item-count-"]'?rows.length?[count]:[]:q==='[id="cart-total"]'?[marker((quantity*7.25).toFixed(2))]:q==='[id="cart-status"]'?[marker('Cart ('+quantity+')')]:[]};
   }
   const control={count:async()=>1,isEnabled:async()=>true,click:async()=>{quantity--;clicks++;},or:()=>control};
   const page={setDefaultTimeout:()=>{},setDefaultNavigationTimeout:()=>{},on:()=>{},goto:async url=>{if(url.includes('AddToCart'))quantity++;},
     evaluate:async(fn,arg)=>{c.document=document();return fn(arg);},screenshot:async args=>fs.writeFileSync(args.path,'finite VM placeholder: not real PNG'),
     locator:selector=>{assert.equal(selector,version==='1.6.0'?'[id="row-1"]:visible':'tr[id="row-1"]');return {locator:()=>control,getByRole:()=>control};}};
   return {newPage:async()=>page,close:async()=>{},tracing:{start:async()=>{},stop:async args=>fs.writeFileSync(args.path,'finite VM placeholder: not real trace')}};
 }};
 const fixtureRequire=n=>n==='playwright'?{chromium:{executablePath:()=>executable,launch:async()=>browser}}:n==='playwright/package.json'?{version:'fixture'}:n==='./product-response.cjs'?require(path.join(path.dirname(file),'product-response.cjs')):require(n);
 c=vm.createContext({require:fixtureRequire,__filename:file,__dirname:path.dirname(file),process:fixtureProcess,URL,Buffer,setTimeout,getComputedStyle:()=>({visibility:'visible'}),location:{href:'http://127.0.0.1:1234/ShoppingCart'},performance:{now:()=>clock+=1000}});
 await vm.runInContext(source,c);const receipt=JSON.parse(fs.readFileSync(path.join(out,'receipt.json'))),result=JSON.parse(fs.readFileSync(path.join(out,'collector-result.json')));
 assert.equal(receipt.faults.length,0);assert.equal(receipt.productFailures.length,0);assert.equal(receipt.removals.length,2);
 if(malformed){assert.equal(clicks,0);assert.equal(result.status,'partial');for(const r of receipt.removals){assert.equal(r.action,'not-run-precondition');assert.equal(r.reason,malformed===true?'cart_row_markers_unsupported':'positive_owned_row_id_not_established');}}
 else{assert.equal(clicks,2);assert.equal(result.status,'observed');for(const r of receipt.removals){assert.equal(r.action,'click-remove');assert.equal(r.completion,'expected_state_stable');}}
}
})().catch(e=>{console.error(e);process.exitCode=1});'''
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
