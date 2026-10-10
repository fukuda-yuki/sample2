"""Bind a reviewed public analysis ZIP to this exact finished cohort.

Read only, no extraction or execution. Review receipts must be issued after
actual content/privacy/rights review, never generated from this validator.
"""
import hashlib,json,stat,zipfile
from download_verified_public_pairs import sha,safe_relative

def verify_analysis(package, review_path, expected_review_sha256, catalog, catalog_sha256):
    if sha(review_path)!=expected_review_sha256:
        raise ValueError('Independent actual public-review receipt identity mismatch')
    review=json.loads(review_path.read_bytes())
    if (review.get('kind')!='actual_exact_all200_analysis_public_copy_review_v1'
        or review.get('publication_approved') is not True
        or review.get('human_review')!='not_run'
        or review.get('original_bundle_sha256')!=catalog['bundle_sha256']
        or review.get('completion_receipt_sha256')!=catalog['completion_receipt_sha256']
        or review.get('catalog_sha256')!=catalog_sha256
        or review.get('analysis_zip_sha256')!=sha(package)
        or any(review.get(k) is not True for k in (
            'all_public_contents_actually_reviewed','known_provider_credential_memory_only_scan_passed',
            'private_ownership_and_oracle_excluded','licenses_and_exclusion_scope_actually_reviewed'))
        or review.get('credential_values_logged') is not False):
        raise ValueError('Actual reviewed ZIP/cohort/public boundary receipt required')
    with zipfile.ZipFile(package) as z:
        entries=z.infolist(); seen=set();folded=set()
        for e in entries:
            name=safe_relative(e.filename).as_posix()
            if e.is_dir() or stat.S_ISLNK(e.external_attr>>16) or name in seen or name.casefold() in folded:
                raise ValueError('Unsafe, directory, symlink or duplicate analysis member')
            seen.add(name);folded.add(name.casefold())
        manifest_bytes=z.read('MANIFEST.json')
        manifest_sha=hashlib.sha256(manifest_bytes).hexdigest()
        if manifest_sha!=review['analysis_manifest_sha256']:
            raise ValueError('Reviewed analysis manifest changed')
        m=json.loads(manifest_bytes);inv=m['files']
        if (m.get('kind')!='source_info_v5_final_analysis_public_package_v1'
            or (m.get('pairs'),m.get('runs'))!=(100,200)
            or m.get('original_bundle_sha256')!=catalog['bundle_sha256']
            or m.get('completion_receipt_sha256')!=catalog['completion_receipt_sha256']
            or m.get('catalog_sha256')!=catalog_sha256
            or seen!=set(inv)|{'MANIFEST.json'} or review['reviewed_inventory']!=inv):
            raise ValueError('Exact reviewed inventory/current cohort binding required')
        for name,item in inv.items():
            safe_relative(name);entry=z.getinfo(name);h=hashlib.sha256();size=0
            if entry.file_size!=item['bytes']:raise ValueError('Analysis member size mismatch')
            with z.open(entry) as stream:
                for b in iter(lambda:stream.read(1024*1024),b''):
                    size+=len(b);h.update(b)
            if size!=item['bytes'] or h.hexdigest()!=item['sha256']:
                raise ValueError('Analysis member bytes/SHA256 mismatch')
        for required in ('data/public-dataset.json','data/public-check-audit.json',
                         'data/all-100-public-pairs-catalog.json','report/research-report-ja.md',
                         'README-ja.md','environment.json'):
            if required not in inv:raise ValueError('Missing required public deliverable')
        if hashlib.sha256(z.read('data/all-100-public-pairs-catalog.json')).hexdigest()!=catalog_sha256:
            raise ValueError('Nested all100 public catalog differs')
        data=json.loads(z.read('data/public-dataset.json'));identity=data['cohort_identity']
        if (data.get('kind')!='public_verified_all200_reanalysis_dataset_v1'
            or identity.get('bundle_sha256')!=catalog['bundle_sha256']
            or identity.get('actual_completion_sha256')!=catalog['completion_receipt_sha256']
            or identity.get('public_check_audit_sha256')!=inv['data/public-check-audit.json']['sha256']):
            raise ValueError('Nested dataset belongs to a different cohort/completion/audit')
        rows=data['runs'];assignments=data['original_assignments']
        expected={(p['pair'],rid,uid) for p in catalog['pair_releases'] for rid,uid in p['original_run_instances'].items()}
        if (len(expected)!=200 or len(rows)!=200 or len(assignments)!=200
            or {(r['pair'],r['run_id'],r['run_instance_id']) for r in rows}!=expected
            or {(r['pair'],r['run_id'],r['run_instance_id']) for r in assignments}!=expected):
            raise ValueError('Exact original200 dataset/registry identities required')
        audit=json.loads(z.read('data/public-check-audit.json'))['runs']
        if len(audit)!=200 or {(r['run_id'],r['run_instance_id']) for r in audit}!={(r[1],r[2]) for r in expected}:
            raise ValueError('Exact original200 audit identities required')
    return {'analysis_public_review_sha256':expected_review_sha256,
            'analysis_manifest_sha256':manifest_sha,
            'analysis_all_member_bytes_and_cohort_verified':True}
