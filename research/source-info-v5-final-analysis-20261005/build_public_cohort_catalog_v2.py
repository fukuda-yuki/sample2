"""Whitelist a unified catalogue of all100 actually verified pair Releases.

Read local final closure/gate/remote/restore receipts only; no network, provider,
evaluator, new release or data deletion. Originals remain private and unchanged.
"""
from pathlib import Path
import argparse
import hashlib
import json


def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--facts',type=Path,required=True)
    p.add_argument('--completion',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    facts=read(a.facts);complete=read(a.completion)
    if (complete.get('kind')!='actual_completed_original100_pairs_200_runs_all_gates_and_terminated_controller'
        or complete['data']['sha256']!=sha(a.facts) or complete['pairs']!=100
        or complete['actual_sent_runs']!=200 or complete['actual_controller_exit_code']!=0
        or complete['scoped_controller_observer_and_watch_absent'] is not True
        or complete['all100_real_publication_restore_extraction_cleanup_gates_verified'] is not True):
        raise ValueError('True verified full-cohort final completion is required')
    pairs=[]
    for number in range(1,101):
        members=[f for f in facts['rows'] if f['pair']==number]
        if len(members)!=2:raise ValueError('Exact original pair members required')
        gate=members[0]['verified_pair_gate']
        if gate!=members[1]['verified_pair_gate']:raise ValueError('Pair gate differs between arms')
        pubp=Path(gate['publication_receipt']);pub=read(pubp)
        roundp=Path(gate['roundtrip_receipt']);roundtrip=read(roundp)
        for rp in (pubp,roundp):
            if sha(rp)!=gate['evidence_files'][str(rp)]:raise ValueError('Verified gate evidence changed')
        if pub['remote_assets_verified'] is not True or roundtrip['hashes_match'] is not True:
            raise ValueError('Actual remote verification and whole-file restoration required')
        asset=pub['asset_manifest'];remote_path=pubp.with_name('actual-remote-readback.json')
        remote_ref=pub['actual_remote_readback']
        if (Path(remote_ref['path']).resolve()!=remote_path.resolve()
            or sha(remote_path)!=remote_ref['sha256']
            or gate['evidence_files'].get(str(remote_path))!=remote_ref['sha256']):
            raise ValueError('Actual remote readback not bound to verified publication/gate')
        remote=read(remote_path)
        expected={f['run_id']:f['run_instance_id'] for f in members}
        if (pub['pair']!=number or roundtrip['pair']!=number or gate['run_instances']!=expected
            or set(asset['selected_runs'])!=set(expected) or pub['plan_sha256']!=facts['bundle_reference']['sha256']
            or pub['package_sha256']!=asset['sha256'] or roundtrip['package_sha256']!=asset['sha256']):
            raise ValueError('Public package/current original pair identity mismatch')
        by_name={x['name']:x for x in remote['assets']}
        material=[]
        for part in asset['parts']:
            r=by_name[part['name']]
            if r['size']!=part['bytes'] or (r.get('digest') and r['digest']!='sha256:'+part['sha256']):
                raise ValueError('Actual remote part metadata differs from bound asset manifest')
            material.append({'name':part['name'],'bytes':part['bytes'],'sha256':part['sha256'],
                             'url':r['browser_download_url']})
        manifest_remote=by_name['pair.manifest.json']
        manifest_digest=manifest_remote.get('digest')
        supplementary=[]
        for name in ('pair.manifest.json','public-review.json','scan.json'):
            r=by_name[name];digest=r.get('digest')
            if (not digest or digest!='sha256:'+roundtrip['metadata_hashes'][name]
                or r['browser_download_url']!=pub['urls'][name]
                or r['browser_download_url']!=roundtrip['download_urls'][name]):
                raise ValueError('Remote metadata differs from actual anonymous roundtrip/publication')
            if name!='pair.manifest.json':
                supplementary.append({'name':name,'bytes':r['size'],'sha256':digest.removeprefix('sha256:'),
                                      'url':r['browser_download_url']})
        if roundtrip['metadata_hashes']['public-review.json']!=asset['review_sha256']:
            raise ValueError('Roundtrip review does not match approved public package')
        # Where GitHub does not expose its digest, bind the recorded exact local
        # manifest bytes from the original publication workspace.
        if not manifest_digest:
            raise ValueError('Manifest readback SHA256 must be explicitly available; handle actual old schema without guessing')
        if not manifest_digest.startswith('sha256:'):raise ValueError('Unexpected remote digest scheme')
        pairs.append({'pair':number,'task':members[0]['task'],'source_family':members[0]['source_family'],
            'original_run_instances':expected,'selected_runs_order':asset['selected_runs'],
            'original_assignment_position':{f['run_id']:f['position'] for f in members},
            'acquisition_phase':members[0]['acquisition_phase'],'release_url':remote['html_url'],
            'release_tag':remote['tag_name'],'release_source_commit':remote.get('tag_commit'),
            'pair_manifest':{'url':manifest_remote['browser_download_url'],'bytes':manifest_remote['size'],
                             'sha256':manifest_digest.removeprefix('sha256:')},
            'package_sha256':asset['sha256'],'package_bytes':asset['bytes'],'parts':material,
            'supplementary_metadata_assets':supplementary,
            'actual_remote_readback_sha256':remote_ref['sha256'],
            'public_file_count':len(asset['file_inventory']),'gate_publication_sha256':sha(pubp),
            'gate_roundtrip_sha256':sha(roundp),'publication_review_sha256':asset['review_sha256'],
            'preservation_gate_kind':gate.get('gate_kind','normal_pair_preservation_gate'),
            'gate_is_quality_acceptance':False,
            'retained_original_scoring':{f['run_id']:f['saved_terminal_row']['scoring']['state'] for f in members}})
    result={'kind':'current_original_source_info_v5_all100_pair_release_catalog_v1',
        'pairs':100,'runs':200,'bundle_sha256':facts['bundle_reference']['sha256'],
        'completion_receipt_sha256':sha(a.completion),'final_acquisition_source_commit':complete['HEAD'],
        'response_model':'deepseek-v4.1-flash','windows_runtime_only':True,
        'existing_result_release_used_as_current_data':False,'pair_releases':pairs,
        'limits':['Public packages are reviewed derivatives, not every byte of private original Runs.',
            'Per-pair MANIFEST and notices disclose omitted ownership/auth/private oracle/DB/runtime/binary/uncleared image material.',
            'All100 preservation/publication/restore/extraction/cleanup gates are separate from original quality acceptance.',
            'This catalogue unifies actual package identities; it does not authorize new sampling or re-evaluation.']}
    with a.out.open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2);f.write('\n')
    print(json.dumps({'pairs':100,'runs':200,'catalog_sha256':sha(a.out),'network_or_model_or_evaluator_called':False}))


if __name__=='__main__':main()
