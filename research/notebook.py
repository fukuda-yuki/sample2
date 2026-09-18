"""Create an executed, inspectable companion to the frozen trace analysis.

Requires the separately recorded research Python environment. Run from repo root.
The notebook only reads analysis JSON; it never calls a model or an evaluator.
"""
import argparse
from pathlib import Path
import textwrap

import nbformat
from nbclient import NotebookClient
from nbconvert import HTMLExporter


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--analysis',action='append',required=True)
    p.add_argument('--summary',required=True)
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    repo=Path(__file__).resolve().parents[1]
    if args.out.exists():
        raise SystemExit('Refusing to overwrite notebook output')
    args.out.mkdir(parents=True)
    n=nbformat.v4.new_notebook()
    n.metadata.kernelspec={'display_name':'Python 3','language':'python','name':'python3'}
    md=nbformat.v4.new_markdown_cell
    code=lambda s:nbformat.v4.new_code_cell(textwrap.dedent(s).strip())
    n.cells=[
      md('# MS1-001 探索分析の再現ノート\n\n'
         'このノートは保存済み解析表を読み、全Runの値、入力増加、呼び出し数、情報保持を確認します。'
         '原本の再採取・モデル呼び出し・再採点はしません。結論と反例は日本語の最終報告を参照してください。'),
      md('## 方法と観測境界\n\n'
         '実験単位はRunです。既存6、新規18枠、補充は別集計します。providerのinput＋outputを主指標とし、'
         'cache/reasoningを再加算しません。nullは欠測です。行動ラベルは重複を許す観測用分類で、'
         '文字量×実際の保持回数はトークンの因果的寄与ではありません。'),
      code(f'''
        import json, sys
        from pathlib import Path
        ROOT = Path({str(repo)!r})
        sys.path.insert(0, str(ROOT))
        from research.summarize import summarize, distribution
        from IPython.display import display, Markdown, Image
        sources = {args.analysis!r}
        data = {{k: [] for k in ('runs','calls','actions','reads')}}
        for name in sources:
            value = json.loads((ROOT/name).read_text(encoding='utf-8-sig'))
            for key in data:
                data[key].extend(value[key])
        summary_path = ROOT / {args.summary!r}
        summary = json.loads(summary_path.read_text(encoding='utf-8-sig'))
        assert len(data['runs']) == len({{r['run_instance_id'] for r in data['runs']}})
        def table(headers, rows):
            def fmt(v):
                if v is None: return 'null'
                if isinstance(v,bool): return str(v)
                if isinstance(v,int): return format(v,',')
                if isinstance(v,float): return format(v,',.3f').rstrip('0').rstrip('.')
                return str(v)
            cells = lambda row: '| ' + ' | '.join(fmt(v) for v in row) + ' |'
            display(Markdown('\\n'.join([cells(headers),cells(['---']*len(headers))]+[cells(row) for row in rows])))
        print('Input files:', *sources, sep='\\n')
        print('Runs:',len(data['runs']), 'Calls:',len(data['calls']), 'Actions:',len(data['actions']))
        if summary['slots']:
            from collections import Counter
            states=Counter(s['status'] for s in summary['slots'])
            display(Markdown('**初回18枠の実行状態：** '+', '.join(str(k)+' = '+str(v) for k,v in states.items())))
            if states.get('not_started',0):
                display(Markdown('**18 Runの採取は完了していません。未実行枠を除外していません。** '
                    '停止理由・品質上の問題・次の判断は最終報告に記載します。'))
      '''),
      md('## 全試行とトークン\n\n成功例だけを選ばず、欠測と品質を併記します。'),
      code('''
        table(['cohort','Run','calls','input','output','total','quality','verdict'],
          [[r['cohort'],r['run_id'],r['calls'],r['input_tokens'],r['output_tokens'],
            r['total_tokens'],r['quality'],r['verdict']] for r in data['runs']])
        for r in data['runs']:
            c=[c for c in data['calls'] if c['run_instance_id']==r['run_instance_id']]
            if r['usage_complete']:
                assert r['input_tokens']==sum(x['input_tokens'] for x in c)
                assert r['output_tokens']==sum(x['output_tokens'] for x in c)
                assert r['total_tokens']==r['input_tokens']+r['output_tokens']
        print('Complete-usage totals reconcile with every call.')
      '''),
      md('## 条件別の分布\n\nSD・四分位・範囲は観測値のばらつきであり、効果の信頼区間ではありません。'),
      code('''
        table(['cohort','condition','attempts','passes','known totals','mean','median','SD','min','max'],
          [[g['cohort'],g['condition'],g['attempts'],g['quality_pass'],g['total_tokens']['n'],
            g['total_tokens']['mean'],g['total_tokens']['median'],g['total_tokens']['sd'],
            g['total_tokens']['min'],g['total_tokens']['max']] for g in summary['groups']])
      '''),
      md('## 入力増加と呼び出し数\n\n各Runを独立に表示し、途中の増分と最終入力長を確認します。'),
      code('''
        for figure in sorted(summary_path.parent.glob('*-input.png')):
            display(Markdown('### '+figure.stem))
            display(Image(filename=str(figure)))
        for figure in sorted(summary_path.parent.glob('*-cumulative.png')):
            display(Image(filename=str(figure)))
        for figure in sorted(summary_path.parent.glob('*-decomposition.png')):
            display(Image(filename=str(figure)))
        if (summary_path.parent/'primary18-totals.png').exists():
            display(Image(filename=str(summary_path.parent/'primary18-totals.png')))
      '''),
      md('## 行動と保持された出力\n\n10,000文字以上という表示上の区分は事後的な記述用です。'
         '仮説採否の事前閾値や「浪費」の判定に使いません。エラーらしい文字列も意味を個別確認します。'),
      code('''
        table(['cohort','Run','multi-tool requests','actions/call','source actions','large seed reads','unknown actions'],
          [[m['cohort'],m['run_id'],m['multi_tool_requests'],round(m['actions_per_call'],2) if m['actions_per_call'] else None,
            m['source_action_count'],m['large_seed_read_actions'],m['unknown_actions']] for m in summary['mechanisms']])
        table(['cohort','Run','call','tool','output chars','later requests','character exposure','evidence'],
          [[r['cohort'],r['run_id'],a['call_index'],a['tool'],a['output_chars'],a['subsequent_input_count'],
            a['subsequent_input_char_exposure'],a['native_ref']] for r in data['runs'] for a in r['top_retained_outputs'][:2]])
      '''),
      md('## 完全な初回ブロック内の差\n\n補充は後刻の別試行なので元のブロックへ入れません。欠測ブロックは差をnullにします。'),
      code('''
        table(['block','contrast','complete','difference','ratio','all quality pass'],
          [[b['block'],b['contrast'],b['complete_block'],b['difference'],b['ratio'],b['all_quality_pass']]
            for b in summary['block_contrasts']])
      '''),
      md('## 人による確認対象と未確認\n\n以下は対象選定であり、人が操作したという記録ではありません。'),
      code('''
        table(['condition','Run','tokens','arm median','human review'],
          [[s['condition'],s['run_id'],s.get('total_tokens'),s.get('arm_median'),s['human_review']]
            for s in summary['human_review_selection']])
      '''),
      md('## 再現\n\n原本からの再抽出は `python -m research.analyze --runs-dir <source> --cohort <cohort> --out <new-directory>`。'
         '次に `research.summarize` を実行します。コマンド・版・ハッシュ・実行結果は納品報告に記載します。'
         '入力長と行動の対応は観測上の説明であり、次の固定介入の効果は新しい確認実験で検証します。')]
    nbformat.validate(n)
    client=NotebookClient(n,timeout=180,kernel_name='python3',resources={'metadata':{'path':str(repo)}})
    client.execute()
    target=args.out/'analysis.ipynb'
    nbformat.write(n,target)
    exporter=HTMLExporter()
    exporter.exclude_input=True
    body,_=exporter.from_notebook_node(n)
    (args.out/'analysis.html').write_text(body,encoding='utf-8')
    print(target)


if __name__=='__main__':
    main()
