"""No-dispatch checks of migration packets in saved ordinary request originals."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from outer.harness import profiles, util

spec=importlib.util.spec_from_file_location('recording_probe',Path(__file__).with_name('probe-recording-repair.py'))
probe=importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class SavedPacketTests(unittest.TestCase):
    def fixture(self,root,method):
        source=root/'inputs/legacy-source'
        source.mkdir(parents=True)
        (source/'One.cs').write_bytes(b'one\r\n')
        (source/'Two.cs').write_text('two\n',encoding='utf-8')
        condition={'migration_request':'Modernize the existing application.',
            'runtime':{'input_mount':'/inputs'},'intervention':{'method':method},'context_files':['*.cs']}
        prompt,context=profiles.prepare_prompt(condition,source)
        util.write_json_atomic(root/'condition.json',condition)
        util.write_json_atomic(root/'context.json',context)
        (root/'inputs/prompt.txt').write_text(prompt,encoding='utf-8',newline='')
        raw=root/'usage/raw'; raw.mkdir(parents=True)
        request=raw/'first.request.json'
        util.write_json_atomic(request,{'messages':[{'role':'system','content':'Agent tools'},
            {'role':'user','content':[{'type':'text','text':prompt}]}]})
        util.append_line(raw/'started.jsonl',{'request_file':request.name,'request_sha256':util.sha256_file(request)})
        return request,prompt

    def test_production_preload_and_explore_packets(self):
        for method,count in (('preload',2),('explore',0)):
            with self.subTest(method=method),tempfile.TemporaryDirectory() as directory:
                root=Path(directory); self.fixture(root,method)
                proof=probe.serialized_source_packets(root)
                self.assertTrue(proof['verified'])
                self.assertEqual(count,proof['packet_count'])
                self.assertEqual(count,proof['expected_packet_count'])
                self.assertEqual(0,proof['gateway_catalog_source_packet_count'])

    def test_duplicate_serialized_prompt_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); request,prompt=self.fixture(root,'preload')
            util.write_json_atomic(request,{'messages':[{'role':'user','content':prompt+prompt}]})
            (root/'usage/raw/started.jsonl').write_text(json.dumps({'request_file':request.name,
                'request_sha256':util.sha256_file(request)})+'\n',encoding='utf-8')
            proof=probe.serialized_source_packets(root)
            self.assertEqual(4,proof['packet_count'])
            self.assertFalse(proof['verified'])

    def test_source_changed_after_freeze_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); self.fixture(root,'preload')
            (root/'inputs/legacy-source/One.cs').write_text('different\n',encoding='utf-8')
            self.assertFalse(probe.serialized_source_packets(root)['verified'])

    def test_changed_request_original_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); request,prompt=self.fixture(root,'preload')
            body=util.read_json(request); body['extra']='modified original'
            util.write_json_atomic(request,body)
            self.assertFalse(probe.serialized_source_packets(root)['verified'])


if __name__=='__main__': unittest.main()
