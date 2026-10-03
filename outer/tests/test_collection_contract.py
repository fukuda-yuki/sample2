"""Independent, no-model fixtures for versioned submission collection."""
import copy
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

try:
    from . import support
except ImportError:
    import support
from harness import preserve, profiles, run, util


class CollectionContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root/'workspace'
        self.workspace.mkdir()
        self.frozen = self.root/'frozen'
        (self.workspace/'Program.cs').write_text('static\n', encoding='utf-8', newline='')
        self.db = self.workspace/'Data/initial-store.sqlite'
        self.db.parent.mkdir()
        with closing(sqlite3.connect(self.db)) as db:
            db.execute('CREATE TABLE Facts(Id INTEGER PRIMARY KEY, Value TEXT)')
            db.execute("INSERT INTO Facts VALUES(7,'preserved')")
            db.commit()

    def test_static_databases_retained_byte_exact_and_sdk_identity_changes(self):
        for suffix in ('.sqlite3','.db'):
            self.db.with_suffix(suffix).write_bytes(self.db.read_bytes())
        before = util.tree_hashes(self.workspace)
        selected_hash = util.collection_hash(self.workspace, policy=util.STATIC_DB_COLLECTION_POLICY)
        result = util.collect(self.workspace,self.frozen,policy=util.STATIC_DB_COLLECTION_POLICY)
        self.assertEqual(before,util.tree_hashes(self.workspace))
        self.assertEqual(before,util.tree_hashes(self.frozen))
        self.assertEqual(3,len(result['database_assets']))
        self.assertEqual(selected_hash,util.artifact_hash(self.frozen))
        self.db = self.frozen/'Data/initial-store.sqlite'
        self.db.write_bytes(self.db.read_bytes()+b'changed')
        self.assertNotEqual(selected_hash,util.artifact_hash(self.frozen))

    def test_legacy_selection_and_frozen_hash_are_unchanged(self):
        result = util.collect(self.workspace,self.frozen)
        expected = util.sha256_bytes(('Program.cs '+util.sha256_bytes(b'static\n')+'\n').encode())
        self.assertEqual(expected,util.artifact_hash(self.frozen))
        self.assertEqual(expected,util.collection_hash(self.workspace))
        self.assertNotEqual(expected,util.artifact_hash(self.workspace))
        self.assertEqual(['Data/initial-store.sqlite'],result['excluded_files'])
        self.assertEqual({},result['database_assets'])

    def test_nonempty_database_sidecars_hold_before_freeze_without_mutation(self):
        for ending in ('-wal','-shm','-journal'):
            with self.subTest(ending=ending):
                sidecar = Path(str(self.db)+ending)
                sidecar.write_bytes(b'unresolved')
                before = util.tree_hashes(self.workspace)
                with self.assertRaisesRegex(ValueError,'held without checkpoint'):
                    util.collect(self.workspace,self.frozen,policy=util.STATIC_DB_COLLECTION_POLICY)
                self.assertFalse(self.frozen.exists())
                self.assertEqual(before,util.tree_hashes(self.workspace))
                sidecar.unlink()

    def test_empty_orphan_sidecars_and_generated_data_are_excluded_with_evidence(self):
        empty = Path(str(self.db)+'-wal'); empty.write_bytes(b'')
        orphan = self.workspace/'orphan.sqlite3-journal'; orphan.write_bytes(b'orphan')
        (self.workspace/'project.user').write_text('user',encoding='utf-8')
        generated = self.workspace/'bin/Release'
        generated.mkdir(parents=True)
        (generated/'live.db').write_bytes(b'live')
        (generated/'live.db-wal').write_bytes(b'active')
        result = util.collect(self.workspace,self.frozen,policy=util.STATIC_DB_COLLECTION_POLICY)
        self.assertEqual(1,len(result['database_assets']))
        self.assertFalse((self.frozen/'bin').exists())
        self.assertEqual({'Data/initial-store.sqlite-wal','orphan.sqlite3-journal','project.user'},
                         set(result['excluded_file_evidence']))
        self.assertEqual(util.sha256_file(orphan),result['excluded_file_evidence']['orphan.sqlite3-journal']['sha256'])

    def run_fixture(self,policy=util.STATIC_DB_COLLECTION_POLICY):
        repo,runs,legacy,seed = support.make_env(self.root/'run-fixture')
        condition = copy.deepcopy(run.load_condition(repo,support.TASK_ID))
        condition['collection_policy'] = policy
        manifest = run.create_run(repo,runs,support.TASK_ID,support.CONDITION_ID,1,
            {'legacy-source':legacy},resolved_condition=condition)
        root = runs/manifest['run_id']
        self.workspace.rename(root/'workspace')
        manifest.update(stop_confirmed=True,synthetic=True)
        run.save_manifest(runs,manifest['run_id'],manifest)
        return runs,root,manifest

    def test_run_snapshot_binds_policy_and_selected_identity(self):
        runs,root,manifest = self.run_fixture()
        fixed,snapshot = run.collect_run(runs,manifest['run_id'])
        self.assertTrue(fixed['submission_fixed'])
        self.assertEqual(util.STATIC_DB_COLLECTION_POLICY,fixed['collection_policy'])
        self.assertEqual(2,snapshot['collection_contract']['version'])
        self.assertIn('Data/initial-store.sqlite',snapshot['database_assets'])
        self.assertEqual(snapshot['artifact_sha256_collected'],snapshot['artifact_sha256'])
        self.assertEqual(util.artifact_hash(root/'frozen'),snapshot['artifact_sha256'])

    def test_policy_and_condition_tampering_cannot_change_collection(self):
        runs,root,manifest = self.run_fixture()
        manifest['collection_policy'] = util.LEGACY_COLLECTION_POLICY
        run.save_manifest(runs,manifest['run_id'],manifest)
        with self.assertRaisesRegex(ValueError,'assigned manifest'):
            run.collect_run(runs,manifest['run_id'])
        self.assertFalse((root/'frozen').exists())
        manifest['collection_policy'] = util.STATIC_DB_COLLECTION_POLICY
        run.save_manifest(runs,manifest['run_id'],manifest)
        condition = util.read_json(root/'condition.json'); condition['collection_policy']=util.LEGACY_COLLECTION_POLICY
        util.write_json_atomic(root/'condition.json',condition)
        with self.assertRaisesRegex(ValueError,'changed after assignment'):
            run.collect_run(runs,manifest['run_id'])
        self.assertFalse((root/'snapshot.json').exists())

    def test_database_survives_normal_preservation_roundtrip(self):
        result = util.collect(self.workspace,self.frozen,policy=util.STATIC_DB_COLLECTION_POLICY)
        snapshot = self.root/'snapshot.json'; util.write_new_json(snapshot,result)
        archive = self.root/'archive'
        reference = preserve.pack(archive,'static-db-fixture',{'frozen':self.frozen,'snapshot.json':snapshot})
        destination = self.root/'restored'
        preserve.restore(archive,reference,destination)
        self.assertEqual(util.tree_hashes(self.frozen),util.tree_hashes(destination/'frozen'))
        self.assertEqual(util.artifact_hash(self.frozen),util.artifact_hash(destination/'frozen'))

    def test_new_rule_is_same_public_prompt_in_both_arms_and_legacy_prompt_stays(self):
        condition = {'migration_request':'Modernize this installation.','context_files':['Program.cs'],
            'runtime':{'input_mount':'/inputs'},'intervention':{'method':'explore'}}
        old_prompt,_ = profiles.prepare_prompt(condition,self.workspace)
        self.assertNotIn('workspace-static-db-v2',old_prompt)
        condition['collection_policy']=util.STATIC_DB_COLLECTION_POLICY
        explore,ex = profiles.prepare_prompt(condition,self.workspace)
        condition['intervention']['method']='preload'
        preload,pr = profiles.prepare_prompt(condition,self.workspace)
        self.assertEqual(ex['common_sha256'],pr['common_sha256'])
        self.assertIn('workspace-static-db-v2',explore)
        self.assertIn('nonempty sidecar',preload)

    def test_unknown_policy_refused(self):
        with self.assertRaises(ValueError):
            util.collect(self.workspace,self.frozen,policy='unknown')
        self.assertFalse(self.frozen.exists())


if __name__=='__main__': unittest.main()
