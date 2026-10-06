"""Verify finite owned-operation HTTP failures separately from browser coverage."""
import re
import hashlib
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit
from . import util


def wait_ready(base_url, output, *, seconds=60, opener=None, clock=time.monotonic, sleep=time.sleep):
    """A readiness response is a diagnostic prerequisite, never workflow coverage.

    Redirects are not followed to unowned hosts. Transport failure is not proof
    that application code returned HTTP 500. Each invocation writes a fresh file.
    """
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl): return None
    if opener is None: opener = urllib.request.build_opener(NoRedirect()).open
    base = urlsplit(base_url)
    if base.scheme != 'http' or base.hostname not in ('127.0.0.1', '::1') or not base.port:
        raise ValueError('Readiness target must be an owned loopback endpoint')
    observations = []; deadline = clock()+seconds; ready = False
    try:
        while clock() < deadline:
            observation = {'method':'GET', 'url':base_url+'/', 'status':None, 'classification':'transport_unobserved'}
            response = None
            try:
                try: response = opener(base_url+'/', timeout=2)
                except urllib.error.HTTPError as error: response = error
                target = urlsplit(response.geturl())
                if (target.scheme,target.netloc) != (base.scheme,base.netloc):
                    raise ValueError('Readiness response is not from the owned origin')
                observation['status'] = response.status
                observation['classification'] = 'observed_product_http_failure' if 500 <= response.status <= 599 else 'observed_http_response'
                try:
                    body = response.read(4096); observation['bodyPrefixSha256'] = hashlib.sha256(body).hexdigest()
                    observation['bodyPrefixBytes'] = len(body)
                except (OSError, TimeoutError) as error: observation['bodyReadError'] = str(error)
                ready = response.status == 200
            except (OSError, TimeoutError, ValueError) as error:
                observation['observerError'] = str(error)
            finally:
                if response is not None:
                    try: response.close()
                    except OSError as error: observation['closeError'] = str(error)
            observations.append(observation)
            if ready: break
            sleep(.25)
    finally:
        util.write_new_json(output, {'ready':ready,'observations':observations,
            'qualityInference':'none; readiness prerequisite only; no browser workflow was measured'})
    return ready


def _allowed(item, evidence, base_url):
    base, target = urlsplit(base_url), urlsplit(item['url'])
    if (base.scheme != 'http' or base.hostname not in ('127.0.0.1', '::1') or not base.port
            or (target.scheme, target.netloc) != (base.scheme, base.netloc)
            or target.query or target.fragment or base.username or base.password): return False
    operation, check = item['operation'], item['checkId']
    routes = {
        'school-create-form': ('GET', r'/Student/Create', ('E-012',), False),
        'school-create-submit': ('POST', r'/Student/Create', ('E-012',), True),
        'school-edit-form': ('GET', r'/Student/Edit/[1-9][0-9]*', ('E-012',), False),
        'school-edit-submit': ('POST', r'/Student/Edit/[1-9][0-9]*', ('E-012',), True),
        'cart-add': ('GET', r'/ShoppingCart/AddToCart/[1-9][0-9]*', ('C-012',), False),
        'cart-remove': ('POST', r'/ShoppingCart/RemoveFromCart', ('C-015', 'C-016'), True),
    }
    if operation not in routes: return False
    method, route, checks, clicked = routes[operation]
    return (item['method'] == method and re.fullmatch(route, target.path) is not None
            and check in checks and item.get('clickConfirmed') is clicked
            and type(item['status']) is int and 500 <= item['status'] <= 599
            and evidence.get('resourceType') in ('document', 'xhr', 'fetch')
            and (not clicked or isinstance(evidence.get('requestPayload'), str)
                 and bool(evidence['requestPayload'])))


def validated_checks(review, receipt, instance, artifact_hash, spec_hash):
    """A partial receipt can prove a failure; it cannot prove complete coverage."""
    found = []
    try:
        review = Path(review)
        if (receipt.get('actor') != 'agent' or receipt.get('runInstanceId') != instance
                or receipt.get('artifactSha256') != artifact_hash or receipt.get('specSha256') != spec_hash): return []
        request_path = review/'request.json'
        if receipt.get('requestSha256') != util.sha256_file(request_path): return []
        request = util.read_json(request_path)
        if any(request.get(k) != receipt.get(k) for k in
               ('runInstanceId', 'artifactSha256', 'specSha256', 'baseUrl', 'evaluationVersion')): return []
        if request.get('evaluationVersion') not in ('education-1.1.0', '1.4.0', '1.5.0'): return []
        for item in receipt.get('productFailures', []):
            try:
                ref = item['evidence']; path = (review/ref['path']).resolve()
                if not path.is_relative_to(review.resolve()) or util.sha256_file(path) != ref['sha256']: continue
                evidence = util.read_json(path)
                keys = ('caseId', 'checkId', 'operation', 'method', 'url', 'status', 'clickConfirmed')
                if any(evidence.get(k) != item.get(k) for k in keys): continue
                if not isinstance(item['caseId'], str) or not item['caseId']: continue
                if _allowed(item, evidence, receipt['baseUrl']): found.append(item['checkId'])
            except (OSError, ValueError, KeyError, TypeError):
                continue
    except (OSError, ValueError, KeyError, TypeError):
        return []
    return sorted(set(found))
