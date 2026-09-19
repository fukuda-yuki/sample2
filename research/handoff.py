"""Create and verify a local, relocatable evidence handoff. Never uploads data."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

from outer.harness import preserve, runtime
from research.correction_inventory import write_new
from research.validate import read, digest, safe_path

BASE = Path('artifacts/corrections/ms1-20260919-v1')


def copy_tree(source, destination, *, code=False):
    shutil.copytree(preserve.native_path(source), preserve.native_path(destination),
        ignore=shutil.ignore_patterns('bin','obj','__pycache__') if code else None)


def create(repo, destination, probes, calibration):
    repo, destination = Path(repo).resolve(), Path(destination).resolve()
    if destination.exists(): raise ValueError('Handoff destination already exists; retain it')
    destination.mkdir(parents=True)
    inv=read(repo/BASE/'baseline/inventory.json')
    for name in ('outer','research','inner','docs'):
        copy_tree(repo/name,destination/name,code=True)
    for name in ('README.md','.dockerignore','.gitattributes','.gitignore'):
        shutil.copy2(repo/name,destination/name)
    for batch in sorted({str(Path(r['root']).parent) for r in inv['runs']}):
        src=repo/batch; dst=destination/batch
        dst.mkdir(parents=True)
        # Direct expected attempts only: restored/diagnostic copies are not Runs.
        for r in inv['runs']:
            if str(Path(r['root']).parent)==batch: copy_tree(repo/r['root'],destination/r['root'])
        copy_tree(src/'_archive',dst/'_archive')
        for p in src.iterdir():
            if p.is_file(): shutil.copy2(p,dst/p.name)
        if (src/'resume-v1').exists(): copy_tree(src/'resume-v1',dst/'resume-v1')
        if (src/'cli-logs').exists(): copy_tree(src/'cli-logs',dst/'cli-logs')
    copy_tree(repo/'artifacts/exploration/20260919', destination/'artifacts/exploration/20260919')
    copy_tree(repo/BASE,destination/BASE)
    copy_tree(repo/'inner/evaluator/LegacyScan.Tests/bin/Release/net8.0',destination/'tools/LegacyScan.Tests')
    evidence=destination/'verification-evidence';evidence.mkdir()
    # Complete calibration results; compact Docker diagnostics omit duplicated
    # legacy inputs but keep manifests, raw mock exchanges and cleanup receipts.
    copy_tree(calibration,evidence/'calibration')
    for probe in map(Path,probes):
        pd=evidence/'container-probes'/probe.name;pd.mkdir(parents=True)
        for p in probe.iterdir():
            if p.is_file(): shutil.copy2(p,pd/p.name)
            elif p.is_dir():
                case=pd/p.name;case.mkdir()
                for f in p.iterdir():
                    if f.is_file():shutil.copy2(f,case/f.name)
                for run_root in p.glob('MS1-001-*'):
                    target=case/run_root.name;target.mkdir()
                    for name in ('manifest.json','runtime.json','evidence','usage','snapshot.json','archive-reference.json'):
                        f=run_root/name
                        if f.is_dir():copy_tree(f,target/name)
                        elif f.is_file():shutil.copy2(f,target/name)
    images=sorted({read(repo/r['root']/'condition.json')['runtime_lock']['images']['evaluator'] for r in inv['runs']})
    image_dir=destination/'images';image_dir.mkdir()
    saved=[]
    for image_id in images:
        p=image_dir/(image_id.replace(':','-')+'.tar')
        runtime.docker('image','save','--output',str(p),image_id,timeout=600)
        saved.append({'image_id':image_id,'path':p.relative_to(destination).as_posix(),'sha256':digest(p)})
    write_new(destination/'images/index.json',saved)
    (destination/'README-ja.md').write_text('''# MS1 修正・再監査の受渡し

既存6 Run、初回18枠、補充1枠の原本と旧評価を保持しています。
訂正評価は artifacts/corrections/ms1-20260919-v1 に別保存しています。
新しいモデル実行、人の主要シナリオ確認、確認実験は含みません。

1. ZIPを新しいディレクトリへ展開し、このREADMEのある場所へ移動します。
2. Python 3.12以降で次を実行します（出力先は展開先の外にある新規パス）。

```powershell
python -B -m research.handoff verify --root . --out ../ms1-verification
```

全ファイルのハッシュ、独立した呼び出し一覧、1,277呼び出し、原本・保存パッケージを検証します。
この検算はPython標準ライブラリのみを使用し、DockerもAPIキーも不要です。

訂正評価の再現にはDockerのLinuxコンテナーが必要です。
images/index.jsonにあるイメージを `docker load -i <path>` で読み込んでから実行します。
同じSDK・依存キャッシュを使用し、評価コンテナーのネットワークはnoneです。

```powershell
python -B -m research.rejudge --root . --inventory artifacts/corrections/ms1-20260919-v1/baseline/inventory.json --bundle artifacts/corrections/ms1-20260919-v1/corrected-runtime/evaluator --runtime-lock artifacts/corrections/ms1-20260919-v1/corrected-runtime/lock.json --scan-tool tools/LegacyScan.Tests/LegacyScan.Tests.dll --scan-in-docker --out ../ms1-rejudgement
```

この手順は24生成物の旧新R-029を比較し、判定が変わる生成物だけを全29要件で再評価します。
SDK、.NETランタイム、依存パッケージのキャッシュは同梱イメージを使います。ホストの.NETやインターネットでのrestoreは不要です。
元のRunや評価結果、APIのusageは上書きしません。旧評価器を使う通常rescoreの制約も保持しています。
Pythonによる監査と、実評価器による訂正評価の再現は別の確認です。
原本に残る絶対パスは採取時の記録です。検算・再判定には指定したroot内の対応物を使います。
`-B` は展開先にPythonキャッシュを生成しない指定です。検算前に展開先へファイルを追加しないでください。
verification-evidence/container-probes は合成providerを使った本体検証で、研究Runに含めません。
人の確認手順は docs/ms1-exploration-20260919-human-review.md を参照してください。
''',encoding='utf-8')
    print('Hashing handoff files',flush=True)
    files={p.relative_to(destination).as_posix():digest(p) for p in destination.rglob('*') if p.is_file()}
    manifest={'created_at':datetime.now(timezone.utc).isoformat(),'source_commit':runtime.command(['git','rev-parse','HEAD'],cwd=repo).stdout.strip(),
        'files':files,'file_count':len(files),'external_upload':False,'evaluator_images':saved}
    write_new(destination/'handoff-manifest.json',manifest)
    archive=destination.with_suffix('.zip')
    if archive.exists():raise ValueError('Archive already exists')
    print('Writing ZIP64 archive',flush=True)
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=1,allowZip64=True) as z:
        for p in destination.rglob('*'):
            if p.is_file():z.write(p,p.relative_to(destination).as_posix())
    receipt={'archive':str(archive),'archive_sha256':digest(archive),'bytes':archive.stat().st_size,
        'manifest_sha256':digest(destination/'handoff-manifest.json'),'files':len(files)}
    write_new(destination.with_suffix('.receipt.json'),receipt)
    print(json.dumps(receipt),flush=True)


def verify(root, out):
    root,out=Path(root).resolve(),Path(out).resolve()
    if out.exists() or out.is_relative_to(root): raise ValueError('Verification requires a new output directory outside the handoff')
    out.mkdir(parents=True)
    manifest=read(root/'handoff-manifest.json')
    failures=[]
    for name,expected in manifest['files'].items():
        p=safe_path(root,name)
        if not p.is_file() or digest(p)!=expected:failures.append(name)
    actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    extras=actual-set(manifest['files'])-{'handoff-manifest.json'}
    write_new(out/'files.json',{'pass':not failures and not extras,'failures':failures,'extra_files':sorted(extras),'files':len(manifest['files'])})
    if failures or extras:raise RuntimeError('Handoff file verification failed; use python -B and an unchanged extraction')
    def execute(module,args,log):
        r=subprocess.run([sys.executable,'-B','-m',module,*map(str,args)],cwd=root,capture_output=True,text=True,encoding='utf-8')
        (out/log).write_text(r.stdout+'\n'+r.stderr,encoding='utf-8')
        if r.returncode:raise RuntimeError(module+' failed; see '+str(out/log))
    inv=root/BASE/'baseline/inventory.json'
    execute('research.validate',['--root',root,'--inventory',inv,'--analysis',root/BASE/'analysis-pilot/analysis.json','--group','pilot',
        '--analysis',root/BASE/'analysis-new/analysis.json','--group','new','--out',out/'independent.json'],'independent.log')
    execute('research.completion',['--root',root,'--inventory',inv,'--independent-audit',out/'independent.json',
        '--original-hashes',root/BASE/'baseline/originals-all-hashes.json','--acquisition-code',root/BASE/'baseline/acquisition-code',
        '--out',out/'completion.json'],'completion.log')
    result={'pass':True,'root':str(root),'file_verification':read(out/'files.json'),
        'calls':read(out/'independent.json')['calls_checked'],'original_files':read(out/'completion.json')['original_files_rechecked']}
    write_new(out/'result.json',result)
    print(json.dumps(result),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='command',required=True)
    c=sub.add_parser('create');c.add_argument('--repo',type=Path,default=Path.cwd());c.add_argument('--out',type=Path,required=True)
    c.add_argument('--probe',type=Path,required=True,action='append');c.add_argument('--calibration',type=Path,required=True)
    v=sub.add_parser('verify');v.add_argument('--root',type=Path,required=True);v.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    if a.command=='create':create(a.repo,a.out,a.probe,a.calibration)
    else:verify(a.root,a.out)


if __name__=='__main__':
    main()
