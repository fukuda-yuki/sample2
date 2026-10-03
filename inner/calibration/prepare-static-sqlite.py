"""Prepare one new static-database submission fixture; never reuse a model Run."""
import argparse
import json
from pathlib import Path
import shutil
import sys


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,default=Path(__file__).resolve().parents[2])
    parser.add_argument('--task-assets',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args(); repo=args.repo.resolve(); out=args.out.resolve()
    sys.path.insert(0,str(repo))
    from research import migration_tasks
    from outer.harness import util
    out.mkdir(parents=True,exist_ok=False)
    project=out/'independent-fixture/MusicStore.Continuity'
    shutil.copytree(repo/'inner/tasks/music-store-continuity/reference/MusicStore.Continuity',project,
                    ignore=shutil.ignore_patterns('bin','obj','.git'))
    (project/'Data').mkdir(exist_ok=True)
    source=migration_tasks.pricing_source(migration_tasks.variant(repo,'A')['pricing_rate'],namespace='MusicStore.Minimal')
    (project/'SourcePricingPolicy.cs').write_bytes(source.encode('utf-8'))
    (project/'Data/catalog.json').write_bytes((json.dumps(migration_tasks.raw_catalog(repo,'A'),indent=2)+'\n').encode('utf-8'))
    migration_tasks.create_initial_database(repo,'A',project/'Data/initial-store.sqlite')
    csproj=project/'MusicStore.Continuity.csproj'
    text=csproj.read_text(encoding='utf-8').replace(" Condition=\"Exists('Data\\initial-store.sqlite')\"",'')
    assert 'Condition=' not in text and '<Content Include="Data\\initial-store.sqlite"' in text
    csproj.write_bytes(text.replace('\r\n','\n').encode('utf-8'))
    shutil.copytree(args.task_assets.resolve()/'MS1-CONT-A/evaluation',out/'assets/A')
    failures=migration_tasks.compare_existing(project/'Data/initial-store.sqlite',
                                               util.read_json(out/'assets/A/migration-oracle.json'))
    assert not failures,failures
    cases=[{'name':'allowed-static-sqlite-content-A','variant':'A','artifact_path':str(project.parent),
            'expected':{'verdict':'pass','scoring_state':'scored','operation_status':'complete',
                        'quality':100.0,'critical_failed':[],'failed_requirements':[],'aggregate_verdict':'pass'}}]
    util.write_new_json(out/'cases.json',cases)
    util.write_new_json(out/'preparation.json',{'scope':'New independent developer fixture; no model output reuse or reconstruction',
        'model_calls':0,'human_review':'not_run','collection_policy':'workspace-static-db-v2',
        'source_template_files':util.tree_hashes(repo/'inner/tasks/music-store-continuity/reference/MusicStore.Continuity'),
        'fixture_files':util.tree_hashes(project.parent), 'private_assets':util.tree_hashes(out/'assets/A'),
        'database_asset':'MusicStore.Continuity/Data/initial-store.sqlite',
        'oracle_row_mismatches':failures,'positive_case_count':1,
        'additional_declared_controls':[
            'Independent fresh collection, then static database byte alteration: ordinary score rejects artifact hash before evaluator launch.',
            'Composition using copied new fixture HTTP baseline with mismatched spec identity: SDK refuses baseline; no observed pass adopted.'],
        'historical_boundary':'Old frozen technical targets, failure receipts, raw inputs and evaluator indices remain untouched.'})
    print(out/'cases.json')


if __name__=='__main__':main()
