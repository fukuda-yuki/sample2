"""Consolidate verified existing100 public pair packages and reviewed analysis.

Only downloaded, size/SHA-bound public derivatives are copied. Private originals,
ownership/auth/oracles, arbitrary download workspace files and restoration logs
are not included. No network/model/evaluator or acquisition operations.
"""
from pathlib import Path
import argparse,hashlib,json,zipfile
from download_verified_public_pairs import sha,native,safe_relative
from collection_analysis_binding import verify_analysis

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--catalog',type=Path,required=True);p.add_argument('--expected-catalog-sha256',required=True)
    p.add_argument('--downloads-root',type=Path,required=True);p.add_argument('--analysis-zip',type=Path,required=True)
    p.add_argument('--expected-analysis-zip-sha256',required=True)
    p.add_argument('--analysis-public-review',type=Path,required=True)
    p.add_argument('--expected-analysis-public-review-sha256',required=True)
    p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    if sha(a.catalog)!=a.expected_catalog_sha256 or sha(a.analysis_zip)!=a.expected_analysis_zip_sha256:
        raise ValueError('Catalog or approved analysis ZIP identity mismatch')
    catalog=json.loads(a.catalog.read_bytes())
    receipt=json.loads((a.downloads_root/'actual-download-restore-receipt.json').read_bytes())
    if (catalog.get('kind')!='current_original_source_info_v5_all100_pair_release_catalog_v1'
        or catalog.get('pairs')!=100 or catalog.get('runs')!=200
        or catalog.get('bundle_sha256')!='f39b38adc6bb46d6a12a6aefc4838155e0378c5d0dd7f5727aa68fbd4fc85334'
        or receipt['catalog_sha256']!=a.expected_catalog_sha256
        or len(receipt['pairs'])!=100 or {r['pair'] for r in receipt['pairs']}!=set(range(1,101))):
        raise ValueError('Exact actual verified all100 public download/restore required')
    analysis_binding=verify_analysis(a.analysis_zip,a.analysis_public_review,a.expected_analysis_public_review_sha256,catalog,a.expected_catalog_sha256)
    verified={r['pair']:r for r in receipt['pairs']};files=[]
    for item in catalog['pair_releases']:
        n=item['pair'];actual=verified[n]
        if (actual['package_sha256']!=item['package_sha256'] or actual['manifest_sha256']!=item['pair_manifest']['sha256']
            or actual['all_sha256_match'] is not True or actual['exact_restored_files']!=item['public_file_count']
            or any(actual[k] is not False for k in ('model_called','evaluator_called','contents_executed'))):
            raise ValueError('Pair actual receipt does not bind its public catalog')
        metadata=item['supplementary_metadata_assets']
        if (len(metadata)!=2 or {x['name'] for x in metadata}!={'public-review.json','scan.json'}
            or actual['supplementary_metadata_sha256']!={x['name']:x['sha256'] for x in metadata}):
            raise ValueError('Actual public review/scan download receipt mismatch')
        base=a.downloads_root/f'pair-{n:03d}'
        for asset in [item['pair_manifest']|{'name':'pair.manifest.json'},*item['parts'],*metadata]:
            rel=safe_relative(asset['name'])
            if len(rel.parts)!=1:raise ValueError('Pair asset must be flat')
            f=native(base/rel.name)
            if f.stat().st_size!=asset['bytes'] or sha(f)!=asset['sha256']:
                raise ValueError('Downloaded public asset changed before consolidation')
            files.append((f,f'pairs/pair-{n:03d}/{rel.name}',asset['sha256'],asset['bytes']))
    if len(catalog['pair_releases'])!=100 or len({x['pair'] for x in catalog['pair_releases']})!=100:
        raise ValueError('Public catalog pairs must appear exactly once')
    files += [(a.analysis_zip,'analysis.zip',a.expected_analysis_zip_sha256,a.analysis_zip.stat().st_size),
              (a.catalog,'all-100-public-pairs-catalog.json',a.expected_catalog_sha256,a.catalog.stat().st_size)]
    inventory={rel:{'bytes':size,'sha256':h} for f,rel,h,size in files}
    if len(inventory)!=len(files):raise ValueError('Duplicate public collection asset path')
    descriptor={'kind':'current_original100_public_collection_with_offline_analysis_v1',
        'pairs':100,'runs':200,'original_bundle_sha256':catalog['bundle_sha256'],
        'files':inventory,**analysis_binding,'public_derivatives_only':True,'private_originals_unchanged':True,
        'all100_real_public_download_restore_verified':True,
        'per_pair_exclusion_and_license_notices_retained_inside_exact_pair_archives':True,
        'model_called':False,'evaluator_called':False,'new_sampling':False,
        'quality_or_full_private_evaluator_replay_acceptance':False}
    readme='''今回の100ペア・200原割付の公開データ集約\n\nanalysis.zip: 全200解析表、全条件結果、研究レポート、コード、環境、offline再計算手順。\nall-100-public-pairs-catalog.json: 全100ペアの原UUID、実取得phase、公開Release、サイズ・SHA256。\npairs/pair-NNN/: 各公開Releaseから実匿名ダウンロードし、全SHA復元確認した元の公開pair ZIP/分割part、pair.manifest.json、public-review.json、scan.json。\nCOLLECTION-MANIFEST.json: この集約内の各元公開資産のサイズ・SHA256。\n\n各pair packageのMANIFEST・NOTICEに公開除外と権利範囲を記録。秘密・所有state・非公開oracle/DB/runtime・未清算素材を含むprivate原本は保持。統計再計算と品質原証拠監査、全評価器再実行は別。正常実行、品質合格、usage完全性を混同しない。故障、null、不完全coverage/usageも分析母集団から削除しない。\n\nmodel/evaluatorの新呼出しは行っていない。Windows用手順であり、Linux対応は今回の範囲外。\n'''
    a.out.mkdir(parents=True,exist_ok=False);package=a.out/'current-all100-public-data-collection.zip'
    with zipfile.ZipFile(package,'x',compression=zipfile.ZIP_STORED,allowZip64=True) as z:
        for f,rel,h,size in files:z.write(f,rel)
        z.writestr('COLLECTION-MANIFEST.json',json.dumps(descriptor,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
        z.writestr('README-ja.txt',readme)
    # Verify exact nested original bytes again rather than trusting ZIP creation.
    with zipfile.ZipFile(package) as z:
        if set(z.namelist())!=set(inventory)|{'COLLECTION-MANIFEST.json','README-ja.txt'}:raise ValueError('Collection membership mismatch')
        for rel,item in inventory.items():
            h=hashlib.sha256();size=0
            with z.open(rel) as f:
                for b in iter(lambda:f.read(1024*1024),b''):h.update(b);size+=len(b)
            if size!=item['bytes'] or h.hexdigest()!=item['sha256']:raise ValueError('Copied public bytes changed')
    final={'kind':'actual_local_consolidated_existing_public100_collection_v1','pairs':100,'runs':200,
        'package':{'name':package.name,'bytes':package.stat().st_size,'sha256':sha(package)},
        'public_catalog_sha256':a.expected_catalog_sha256,'analysis_zip_sha256':a.expected_analysis_zip_sha256,
        'all_nested_public_asset_bytes_verified':True,**analysis_binding,'assets':len(inventory),
        'new_sampling':False,'model_called':False,'evaluator_called':False,'remote_publication_verified':False}
    with (a.out/'actual-local-collection-receipt.json').open('x',encoding='utf8') as f:json.dump(final,f,indent=2);f.write('\n')
    print(json.dumps(final))
if __name__=='__main__':main()
