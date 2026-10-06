"""Real finite Windows pipe/owner lifecycle; no model or campaign mutation."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from research import proof_session as proof


@unittest.skipUnless(os.name=='nt','Windows authenticated local pipe')
class ProofServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.repo=Path(proof.__file__).resolve().parents[1]

    def own(self,command):
        process=subprocess.Popen(command,cwd=self.repo,stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
        def cleanup():
            if process.poll() is None:process.terminate()
            process.wait(timeout=10)
        self.addCleanup(cleanup)
        return process

    def start(self,owner=None,seconds=30):
        reference=self.root/'private-reference.json'
        process=self.own([sys.executable,'-B','-X','utf8','-m','research.proof_session','serve',str(reference),
            '--owner-pid',str(owner or os.getpid()),'--seconds',str(seconds)])
        end=time.monotonic()+10
        while not reference.exists() and time.monotonic()<end:
            self.assertIsNone(process.poll())
            time.sleep(.05)
        return process,proof.Client(reference)

    def test_explicit_stop_releases_and_stale_reference_rejects(self):
        process,client=self.start()
        self.assertEqual(client.check()['entries'],0)
        self.assertEqual(client.request(dict(action='stop')),'closed')
        self.assertEqual(process.wait(timeout=10),0)
        with self.assertRaises(proof.ProofInvalid):client.check()

    def test_owner_loss_exits_without_client_request(self):
        owner=self.own([sys.executable,'-B','-c','import time; time.sleep(30)'])
        process,client=self.start(owner.pid)
        owner.terminate();owner.wait(timeout=10)
        self.assertEqual(process.wait(timeout=10),2)
        with self.assertRaises(proof.ProofInvalid):client.check()

    def test_finite_expiry_exits_without_client_request(self):
        process,client=self.start(seconds=3)
        self.assertEqual(process.wait(timeout=10),2)
        with self.assertRaises(proof.ProofInvalid):client.check()

    def test_unknown_proof_fails_closed_and_exits(self):
        process,client=self.start()
        with self.assertRaises(proof.ProofInvalid):client.use('unknown',{},lambda:True)
        self.assertEqual(process.wait(timeout=10),2)

    def test_incomplete_inventory_or_modified_reference_rejected(self):
        process,client=self.start()
        record=json.loads(client.bytes)
        record['source_inventory']={}
        foreign=self.root/'foreign-reference.json'
        foreign.write_text(json.dumps(record))
        with self.assertRaises(proof.ProofInvalid):proof.Client(foreign)
        client.path.write_bytes(client.bytes+b'\n')
        with self.assertRaises(proof.ProofInvalid):client.check()


if __name__=='__main__':unittest.main()
