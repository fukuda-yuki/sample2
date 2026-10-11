"""Opt-in finite real-browser local fixtures; no model, Docker, or saved Run writes."""
import json
import os
import subprocess
import shutil
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs
from uuid import uuid4
try:
    from . import support
except ImportError:
    import support
from harness import browser_product, util
from harness.security import child_environment


@unittest.skipUnless(os.environ.get('SAMPLE2_LIVE_BROWSER_FIXTURES') == '1', 'Explicit pinned browser fixture environment required')
class LiveCollectorTests(unittest.TestCase):
    def collect(self, kind, mode):
        state = {'students': {}, 'carts': {}, 'requests': []}
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def send(self, status, body='', location=None, cookie=None):
                self.send_response(status)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                if location: self.send_header('Location', location)
                if cookie: self.send_header('Set-Cookie', 'fixture='+cookie+'; Path=/')
                self.end_headers(); self.wfile.write(body.encode('utf-8'))
            def form(self, action, label, fields):
                return '<html><body><form method="post" action="'+action+'">'+''.join(
                    '<input name="'+name+'" value="'+value+'">' for name, value in fields.items())+'<button type="submit">'+label+'</button></form></body></html>'
            def cart(self, count):
                row = '' if not count else ('<tr id="row-1"><td><a href="/Store/Details/1">Album</a></td><td>8.99</td><td id="item-count-1">'+str(count)+'</td><td><form action="/ShoppingCart/RemoveFromCart" method="post"><input type="hidden" name="id" value="1"><button type="submit">Remove</button></form></td></tr>')
                return '<html><body><table>'+row+'</table><div id="cart-total">'+format(count*8.99, '.2f')+'</div><div id="cart-status">Cart ('+str(count)+')</div></body></html>'
            def do_GET(self):
                state['requests'].append(('GET', self.path, None))
                if self.path == '/favicon.ico': self.send(500, 'unrelated icon failure'); return
                if self.path == '/Student/Create':
                    if mode == '500': self.send(500, 'missing Create view'); return
                    self.send(200, self.form('/Student/Create', 'Create', {'LastName':'', 'FirstMidName':'', 'EnrollmentDate':''})); return
                if self.path == '/Student/Edit/203':
                    self.send(200, self.form(self.path, 'Unsupported' if mode == 'unsupported' else 'Save', state['students'])); return
                if self.path == '/Student/Details/203':
                    fields=state['students']
                    markers={'student-id':'203','student-first-name':fields['FirstMidName'], 'student-last-name':fields['LastName'], 'student-enrollment-date':fields['EnrollmentDate'], 'student-full-name':fields['FirstMidName']+' '+fields['LastName']}
                    if mode.startswith('marker-'):
                        body=''.join('<span '+k+'="'+v+'"'+(' class="concealed"' if mode=='marker-hidden' and k=='student-first-name' else ' style="display:contents"' if mode=='marker-visible' else '')+'>'+
                            ('' if mode=='marker-id-only' and k=='student-id' or mode=='marker-value-only' and k=='student-first-name' else v)+'</span>' for k,v in markers.items())
                        if mode=='marker-foreign': body='<section student-id="999">'+body+'</section>'
                        if mode=='marker-hidden': body='<style>.concealed { display: none; }</style>'+body
                    else: body=''.join('<span id="'+k+'">'+v+'</span>' for k,v in markers.items())
                    self.send(200, '<html><body>'+body+'</body></html>'); return
                session = self.headers.get('Cookie', '').removeprefix('fixture=') or uuid4().hex
                count=state['carts'].get(session, 0)
                if self.path == '/ShoppingCart': self.send(200, self.cart(count), cookie=session); return
                if self.path == '/ShoppingCart/AddToCart/1':
                    if mode == '500': self.send(500, 'UNIQUE constraint failed: Carts.RecordId'); return
                    state['carts'][session]=count+1; self.send(302, location='/ShoppingCart'); return
                self.send(404, 'not found')
            def do_POST(self):
                payload=self.rfile.read(int(self.headers.get('Content-Length', '0'))).decode('utf-8')
                state['requests'].append(('POST', self.path, payload))
                if self.path in ('/Student/Create', '/Student/Edit/203'):
                    state['students']={k:v[0] for k,v in parse_qs(payload).items()}; self.send(302, location='/Student/Details/203'); return
                if self.path == '/ShoppingCart/RemoveFromCart':
                    session=self.headers.get('Cookie', '').removeprefix('fixture=')
                    state['carts'][session]=max(0,state['carts'].get(session,0)-1)
                    self.send(302, location='/ShoppingCart'); return
                self.send(404, 'not found')
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        try:
            repo=Path(__file__).resolve().parents[2]
            scratch=repo/'artifacts/browser-fixture-temporary'; scratch.mkdir(parents=True,exist_ok=True)
            with tempfile.TemporaryDirectory(dir=scratch) as directory:
                root=Path(directory)
                browser_temp=root/'browser-temp'; browser_temp.mkdir()
                request={'runInstanceId':'fixture-run','artifactSha256':'fixture-artifact','specSha256':'fixture-spec',
                    'baseUrl':'http://127.0.0.1:'+str(server.server_port), 'evaluationVersion':'education-1.1.0' if kind=='education' else '1.4.0',
                    'createFields':{'LastName':'Researcher','FirstMidName':'Casey','EnrollmentDate':'2026-01-02'},
                    'editFields':{'LastName':'Review','FirstMidName':'Morgan','EnrollmentDate':'2026-02-03'},
                    'albumId':1,'price':8.99,'requireCartStatus':True,'structuralPrecondition':True}
                util.write_new_json(root/'request.json',request)
                environment=child_environment({k:os.environ[k] for k in ('NODE_PATH','SAMPLE2_BROWSER_EXECUTABLE')}
                    | {'TEMP':str(browser_temp),'TMP':str(browser_temp)})
                result=subprocess.run(['node',str(repo/'inner/browser'/('education-review.cjs' if kind=='education' else 'cart-review.cjs')),
                    str(root/'request.json'),str(root)],env=environment,capture_output=True,text=True,timeout=45)
                receipt=util.read_json(root/('collector-receipt.json' if kind=='education' else 'receipt.json'))
                self.assertEqual(0,result.returncode,result.stderr+repr(receipt['faults']))
                self.assertEqual([],receipt['faults'])
                failures=browser_product.validated_checks(root,receipt,'fixture-run','fixture-artifact','fixture-spec')
                if kind=='education' and (root/'after.json').is_file(): state['after']=util.read_json(root/'after.json')['page']
                archive=repo/'artifacts/browser-repair-fixtures'/(kind+'-'+mode+'-'+uuid4().hex)
                shutil.copytree(root,archive,ignore=shutil.ignore_patterns('browser-temp'))
                util.write_new_json(archive/'fixture-result.json',{'kind':kind,'mode':mode,
                    'collectorExitCode':result.returncode,'validatedProductChecks':failures,'modelCalled':False,
                    'acquisitionRun':False,'fixtureRequests':state['requests']})
                return receipt,failures,state
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)

    def test_school_missing_view_500_is_observed_failure_with_incomplete_workflow(self):
        receipt,failures,_=self.collect('education','500')
        self.assertEqual(['E-012'],failures); self.assertEqual('product-http-failed',receipt['action'])
        self.assertNotIn('after',receipt)

    def test_school_normal_form_save_and_unrelated_500_icon(self):
        receipt,failures,state=self.collect('education','normal')
        self.assertEqual([],failures); self.assertEqual('create-edit-save',receipt['action'])
        self.assertEqual('Morgan',state['students']['FirstMidName'])
        self.assertEqual(2,len([r for r in state['requests'] if r[0]=='POST']))

    def test_school_unsupported_save_control_is_unknown_without_invented_product_fail(self):
        receipt,failures,_=self.collect('education','unsupported')
        self.assertEqual([],failures); self.assertEqual('ordinary_save_form_unsupported',receipt['reason'])
        self.assertNotEqual('create-edit-save',receipt['action'])

    def test_school_named_attributes_preserve_actual_ordinary_create_edit_save(self):
        receipt,failures,state=self.collect('education','marker-visible')
        self.assertEqual([],failures); self.assertEqual('create-edit-save',receipt['action'])
        self.assertEqual(2,len([r for r in state['requests'] if r[0]=='POST']))
        self.assertEqual('Morgan',state['after']['firstName'])
        self.assertTrue(all(r['status']=='observed' for r in state['after']['markerObservations'].values()))

    def test_school_css_hidden_attribute_only_and_foreign_fields_never_become_visible_values(self):
        for mode in ('marker-hidden','marker-value-only','marker-foreign'):
            with self.subTest(mode=mode):
                receipt,_,state=self.collect('education',mode)
                self.assertEqual('create-edit-save',receipt['action'])
                self.assertEqual('invalid',state['after']['markerObservations']['student-first-name']['status'])
                self.assertIsNone(state['after']['firstName'])

    def test_school_attribute_only_student_id_keeps_unresolved_display_and_route_identity(self):
        receipt,_,state=self.collect('education','marker-id-only')
        self.assertEqual('create-edit-save',receipt['action'])
        self.assertEqual('observed-details-url',receipt['studentIdentifierSource'])
        self.assertIsNone(state['after']['studentId'])
        self.assertEqual({'status':'unresolved','value':'203'},state['after']['markerObservations']['student-id'])

    def test_cart_add_500_preserves_add_failure_without_claiming_remove_coverage(self):
        receipt,failures,_=self.collect('cart','500')
        self.assertEqual(['C-012'],failures); self.assertEqual([],receipt['removals'])

    def test_cart_normal_visible_remove_two_independent_sessions(self):
        receipt,failures,_=self.collect('cart','normal')
        self.assertEqual([],failures); self.assertEqual(['click-remove','click-remove'],[r['action'] for r in receipt['removals']])


if __name__ == '__main__': unittest.main()
