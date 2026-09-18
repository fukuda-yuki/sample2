import tempfile
from pathlib import Path
import unittest

from research.analyze import classify, numbered_lines, provider_response, reread_kind, shell_source_ranges


class AnalysisContracts(unittest.TestCase):
    def test_provider_totals_include_breakdowns_and_unknown_cache_write(self):
        data = 'data: {"model":"m","usage":{"prompt_tokens":100,"completion_tokens":30,"prompt_tokens_details":{"cached_tokens":80},"completion_tokens_details":{"reasoning_tokens":20}},"choices":[]}\n\ndata: [DONE]\n'
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'response.sse'; p.write_text(data, encoding='utf-8')
            u, calls, models, errors, done = provider_response(p)
        self.assertEqual((u['input_tokens'], u['output_tokens']), (100, 30))
        self.assertIsNone(u['cache_write_tokens'])
        self.assertEqual(u['cache_read_tokens'], 80)
        self.assertEqual(u['reasoning_tokens'], 20)
        self.assertTrue(done)
        self.assertEqual(errors, [])

    def test_truncated_stream_preserves_reported_usage_but_not_completion(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'r'; p.write_text('data: {"usage":{"prompt_tokens":5,"completion_tokens":2}}\ndata: {', encoding='utf-8')
            u, _, _, errors, done=provider_response(p)
        self.assertEqual(u['input_tokens'], 5)
        self.assertFalse(done)
        self.assertTrue(errors)

    def test_read_ranges_and_partial_overlap(self):
        lines=numbered_lines('<content>\n2: b\n3: c\n\n(Output capped)\n</content>')
        self.assertEqual(lines,{2:'b',3:'c'})
        self.assertEqual(reread_kind(lines,{1:'a',2:'b'},0,0),'partial_overlap')
        self.assertEqual(reread_kind(lines,{2:'b',3:'c'},0,0),'unchanged_range_reacquisition')
        self.assertEqual(reread_kind(lines,{2:'b',3:'c'},1,0),'after_observed_edit')
        self.assertEqual(reread_kind(lines,{2:'changed',3:'c'},0,0),'content_changed_edit_unobserved')
        self.assertEqual(reread_kind({}, {},0,0),'indeterminate')

    def test_compound_shell_loop_is_read_even_when_path_precedes_cat(self):
        cmd='cd /input/legacy-source/App; for f in Models/A.cs Models/B.cs; do cat "$f"; done; dotnet build'
        labels,_=classify('bash',{'command':cmd},'',set())
        self.assertIn('source_read', labels)
        self.assertIn('build', labels)

    def test_count_only_source_processing_does_not_claim_content_delivery(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'A.cs').write_text('line one with content\nline two with content\nline three with content\n')
            self.assertEqual(shell_source_ranges('grep -c x /input/legacy-source/A.cs','3\n',root,{}),[])
            rows=shell_source_ranges('cat /input/legacy-source/A.cs','line one with content\nline two with content\nline three with content\n',root,{})
        self.assertEqual(len(rows),1)
        self.assertEqual(set(rows[0][1]),{1,2,3})

    def test_edit_and_repeated_write_are_revision_not_proof_of_failure(self):
        self.assertNotIn('revision', classify('write',{'filePath':'/workspace/A.cs'},'',set())[0])
        self.assertIn('revision', classify('write',{'filePath':'/workspace/A.cs'},'',{'/workspace/A.cs'})[0])
        self.assertIn('revision', classify('edit',{'filePath':'/workspace/A.cs'},'',set())[0])


if __name__=='__main__':
    unittest.main()
