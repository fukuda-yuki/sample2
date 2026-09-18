"""Render this batch's Japanese report from the final, separately checked tables.

Post-acquisition reporting only; no model, evaluator, or Docker operations.
"""
from pathlib import Path
from datetime import datetime, timedelta, timezone
from research.analyze import read_json

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'artifacts/exploration/20260919'


def table(headers, rows):
    def fmt(v):
        if v is None: return 'null'
        if isinstance(v, bool): return str(v)
        if isinstance(v, int): return f'{v:,}'
        if isinstance(v, float): return f'{v:,.1f}'
        return str(v).replace('|', '\\|').replace('\n', ' ')
    line = lambda row: '| ' + ' | '.join(map(fmt, row)) + ' |'
    return '\n'.join([line(headers), line(['---'] * len(headers))] + [line(r) for r in rows])


def main():
    old = read_json(BASE/'pilot-v1.0.1/analysis.json')
    new = read_json(BASE/'new-resumed-v1/analysis.json')
    summary = read_json(BASE/'display-resumed-v2/summary.json')
    ledger = read_json(BASE/'ledger-resumed-v1/execution-ledger.json')
    checks = read_json(BASE/'independent-check-resumed-v1.json')
    resume = read_json(ROOT/'runs/exploration-20260919-ms1/resume-v1/result.json')
    assert resume['complete'] and not ledger['schedule_issues']
    assert all(c['pass'] for c in checks)
    jst = lambda s: datetime.fromisoformat(s).astimezone(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M:%S JST')
    started = min(r['dispatch_at'] for r in ledger['ledger'])
    runs = old['runs'] + new['runs']
    primary = sorted([r for r in new['runs'] if r['cohort'] == 'primary18'], key=lambda r:r['slot'])
    supplement = [r for r in new['runs'] if r['cohort'] == 'supplement']
    assert len(primary) == 18 and len(supplement) == 1
    calls = old['calls'] + new['calls']
    actions = old['actions'] + new['actions']
    input_context = table(['条件','観測された初回input','初回user文字量','初期投入保持calls / 観測calls'], [
        [arm, ', '.join(str(v) for v in sorted({r['first_input'] for r in runs if r['condition']==arm and r['calls']})),
         ', '.join(str(v) for v in sorted({c['user_chars'] for c in calls if c['condition']==arm and c['call_index']==1})),
         str(sum(r['initial_prompt_present_calls'] for r in runs if r['condition']==arm))+' / '+
         str(sum(r['calls'] for r in runs if r['condition']==arm))] for arm in ('explore','preload','explained')])
    context_losses = [(r['cohort']+'/'+r['run_id'],r['disappeared_message_count']) for r in runs if r['disappeared_message_count']]
    def values(rr):
        return table(['Run', 'calls', 'input', 'output', '合計', '平均input/call', '品質'], [
            [r['run_id'].replace('MS1-001-', ''), r['calls'], r['input_tokens'], r['output_tokens'],
             r['total_tokens'], r['mean_input'], str(r['quality']) + ' / ' + r['verdict']] for r in rr])
    groups = table(['集団', '条件', '試行/既知総量/合格', '平均', '中央値', '標本SD', '最小〜最大'], [
        [g['cohort'], g['condition'], f"{g['attempts']}/{g['total_tokens']['n']}/{g['quality_pass']}",
         g['total_tokens']['mean'], g['total_tokens']['median'], g['total_tokens']['sd'],
         f"{g['total_tokens']['min']:,}〜{g['total_tokens']['max']:,}" if g['total_tokens']['n'] else 'null']
        for g in summary['groups']])
    contrast = table(['ブロック', 'preload − explore', 'explained − explore', 'explained − preload', '全条件品質合格'], [
        [b, *[next(x['difference'] for x in summary['block_contrasts'] if x['block']==b and x['contrast']==c)
              for c in ('preload - explore','explained - explore','explained - preload')],
         next(x['all_quality_pass'] for x in summary['block_contrasts'] if x['block']==b)] for b in range(1,7)])
    mechanism = table(['集団/Run', '行動/calls', '取得', '探索', '修正', '未分類', '未変更再取得/編集後/部分重複/不明'], [
        [r['cohort']+'/'+r['run_id'].replace('MS1-001-',''), f"{r['actions']}/{r['calls']}",
         r['action_label_counts'].get('source_read',0), r['action_label_counts'].get('discovery',0),
         r['action_label_counts'].get('revision',0), r['action_label_counts'].get('other_unknown',0),
         '/'.join(str(r['read_kind_counts'].get(k,0)) for k in
                  ('unchanged_range_reacquisition','after_observed_edit','partial_overlap','indeterminate'))]
        for r in runs])
    chosen = table(['条件','選定Run','合計','合格集合の中央値','人の確認'], [
        [s['condition'],s['run_id'],s.get('total_tokens'),s.get('arm_median'),'Not run']
        for s in summary['human_review_selection']])
    text = f'''# MS1-001：既存6 Runの行動分析と18枠の探索実験

**初回18枠と補充1枠の処理を完了した。** 初回は17件がモデル実行・完全計測、1件がモデル起動前のDocker障害である。
その失敗を残し、全初回枠の終了後に同条件の補充1件を実行した。新規のモデル実行は合計18件、試行枠は19件で、上限24以内。
既存6 Run、初回18枠、補充は別集計し、補充で初回の欠測を置き換えていない。

**次の主仮説は「カタログ原文をファイルに保持し、モデルへ返す範囲を限定すると、品質を保ちながらRun総量を減らせるか」とする。**
大きな出力が後続入力に残る行動は複数条件・複数Runで繰り返された。ただし、短い出力への介入効果は今回測っていない。
条件の勝者、品質非劣性、他タスクへの一般化は確定しない。人の抜き取り確認と確認実験は未実施である。

## 1. 固定条件、Docker障害、再開

[固定プロトコル](ms1-exploration-20260919-protocol.md)と
[原計画](../research/protocols/ms1-001-exploration-20260919.json)は採取前に保存した。
MS1-001、公開29要件、評価1.2.0、deepseek-v4.1-flash、OpenCode 1.17.11、各Run1800秒、provider600秒、同時実行1。
既存CLIの通常の `run` 経路で、新しいセッション・作業領域・状態領域を毎回使用した。
ソース、要求文、preloadの20ソース、explainedの既存説明、compaction、モデル設定、依存関係、保存イメージ、評価器は固定した。

乱数seedは `2276221400835857104`。6通りの順列を1回ずつ使い、組の順序を採取前に無作為化した。

| 組 | 元の実行順 | 結果 |
|---|---|---|
| 1 | explore-001 → preload-001 → explained-001 | 2実装完了、explainedは起動前障害 |
| 2 | explained-002 → preload-002 → explore-002 | 3実装完了 |
| 3 | explore-003 → explained-003 → preload-003 | 3実装完了 |
| 4 | explained-004 → explore-004 → preload-004 | 3実装完了 |
| 5 | preload-005 → explained-005 → explore-005 | 3実装完了 |
| 6 | preload-006 → explore-006 → explained-006 | 3実装完了 |
| 補充 | explained-007（explained-001に対応） | 初回18枠の終了後に実施 |

最初の停止原因は `all predefined address pools have been fully subnetted`。
現行 `outer/harness/runtime.py` はRunコンテナーを止めるが、専用ネットワークを回収しないため蓄積していた。
障害時は32ネットワークを観測した。32という普遍的なDocker上限を発見したという意味ではない。
ユーザーの明示的な再試行・修復指示を受け、[再開改訂R1](ms1-exploration-20260919-retry-amendment.md)を別途固定した。
元計画、停止結果、障害Runは改変せず、未実行15枠を元の順番で継続した。中断を挟んだ改訂付きの探索として報告する。

保存パッケージ、所有者、停止、未使用の内部bridgeであることを確認して、当該バッチの専用ネットワークだけを回収した。
最初の2ネットワーク回収後は32から30になり、内部ネットワークの作成・削除をモデルなしで確認した。
以後の回収は各Runの保存完了後、測定区間の外で行った。停止コンテナー、原本、他タスクのネットワークは保持した。
モデル実行の途中でネットワークや入力条件を変更していない。検証機本体・評価器は変更していない。

原計画SHA-256：`7e4df4a319557b161368fe4fb1d68f5456229d2e6f5619e5ce37bbb58e0d318a`。
R1計画SHA-256：`a258e0d81304f1665d83b809e928410f6e9d7189f57e687d04910fdeefb9b011`。
各開始・終了・保存時刻、障害・補充対応は[実行台帳](../artifacts/exploration/20260919/ledger-resumed-v1/execution-ledger.csv)にある（UTC）。
初回dispatchから補充後の保存・回収終了までは {jst(started)}〜{jst(resume['ended_at'])}。この区間には中断・復旧作業を含む。
元の `batch-result.json` は中断時点を表し、最終状態は `resume-v1/result.json` である。
品質不合格を理由とする補充、有意差や望ましい結果を理由とする追加はない。

## 2. 全試行と記述比較

主指標は全モデル呼び出しのgateway原本のinput＋outputである。補助呼び出しも分母に含む。
cache readはinput、reasoningはoutputの内数なので再加算しない。OpenCode側の異なる欄定義とは混用しない。
欠測はnull、既知の部分和とは区別する。主指標は料金ではない。
今回の説明生成の追加LLM呼び出しはなく、説明文の過去の準備トークンは不明。準備から含む方法全体の効率は未評価である。

### 初回18枠

{values(primary)}

explained-001は観測callsが0でもinput/output/部分和はnullである。0点は空の成果物の1不合格・28blockedで、説明投入で生成した実装の品質ではない。
preload-001（93.1）とpreload-002（96.55）も全試行の比較に残した。失敗の早期終了を効率改善とは判定しない。

### 補充（別集計）

{values(supplement)}

### 既存6 Run（診断試行・復元コピーを除く）

{values(old['runs'])}

### 条件別分布

{groups}

初回の既知総量ではpreloadの平均が最小だが、同条件の実装6件中2件は品質不合格である。
explainedは同条件内で約2.32M〜7.67Mと幅が大きく、モデル起動前の欠測も1枠ある。
これらを無視して最少平均の条件を「有効」と選ばない。
分布は既知の総量に対する記述で、試行数と欠測を併記した。SD・四分位・範囲は効果の信頼区間ではない。
input/output別分布・Q1/Q3・成功Runだけの補助分析は[集計JSON](../artifacts/exploration/20260919/display-resumed-v2/summary.json)にある。
成功例だけの比較を主分析にしていない。各条件6回が統計的に十分であるとは主張しない。

全条件の総量を観測できたブロックは2〜6の5組。差の単位はtokens、負値は左の条件が少ないことを表す。
品質不合格を含む組2も残し、品質条件を併記した。組1の欠測を補充で埋めない。

{contrast}

![初回18枠の総量](../artifacts/exploration/20260919/display-resumed-v2/primary18-totals.png)
![呼び出し数と平均入力](../artifacts/exploration/20260919/display-resumed-v2/primary18-decomposition.png)

## 3. 入力が増えた場所と、呼び出しが増えた行動

入力合計はcalls×平均inputに分解できる。既存preload-001から002では38→54calls、平均66,496→75,857で、両方が増えた。
新規explore-002と005は71/72callsだが、平均87,046/56,352、総量6.24M/4.10Mである。
一方、新規preload-006は大きな原文と起動出力を保持していても37callsで終わった。
取得回数だけ、呼び出し数だけ、初期promptだけでは総量を説明できない。

全Runの入力成分はcalls.csvにsystem/user/assistant/toolの正規化JSON文字量、ツール定義文字量、保持・新規メッセージ文字量として保存した。
actions.csvは各出力の文字量、実際に後続入力へ含まれた回数と文字露出を持つ。これらはトークンの因果的な寄与ではない。
複数目的・複数ツールの要求を複合のまま残し、usageを行動ごとに按分していない。

{input_context}

system文字量の観測値は {sorted({c['system_chars'] for c in calls})}、ツール定義は {sorted({c['tool_schema_chars'] for c in calls})}。
preloadの20ソース、explainedの説明1ブロックは該当する全要求で残っていた。
直前の要求から消えたメッセージhashの件数は `{context_losses}`。文面のhash変化も含むため、この値を圧縮回数とは呼ばない。
初期投入を失う大きな文脈圧縮は観測されず、長いソースと会話履歴が残った。
一方、ツール出力自体の切詰めはある。53,025文字のCompleted/SampleData.cs取得例は50 KB上限で1〜360行までを表示し、
361行以降は別途取得する案内が付く。ファイル全体の投入とは扱わない。原本の全データと、モデルが実際に見た範囲を分けて照合した。

さらに、送信文字量が増え、直前のメッセージhashもすべて保持されているのに、providerのprompt_tokensが3,000超減る箇所が4件あった。
新規explore-002 call35（−16,196）、explore-004 call23（−11,891）、explained-004 call32（−14,843）、補充explained-007 call44（−31,063）である。
これらではcache欄とusage packetの形式も変わるが、報告model IDは固定値と一致する。内部の処理・算定理由は保存原本から分からない。
**原本との数値一致は、送信文字数からtoken数への一定の対応や、provider内部の挙動の不変を保証しない。**
この減少をエージェントの圧縮・入力削減へ帰属しない。3,000は事後の表示閾値で、仮説採否の基準ではない。
[原本の前後照合](../artifacts/exploration/20260919/provider-input-decreases.json)と根拠索引へ残した。

![既存6件の入力長](../artifacts/exploration/20260919/display-resumed-v2/existing6-input.png)
![新規初回の入力長](../artifacts/exploration/20260919/display-resumed-v2/primary18-input.png)
![新規初回の累計](../artifacts/exploration/20260919/display-resumed-v2/primary18-cumulative.png)

代表的な根拠は次のとおり。各call番号はRun内のgateway時刻順であり、同名の既存Runと新規Runを区別する。

| 集団・Run | 入力増加／反復の対応 |
|---|---|
| 既存explore-001/002 | 53,025文字の種データを54/49回保持。取得直後に+14,707/+18,896 |
| 既存preload-001/002 | 71/85行動、38/54calls。002ではcall33の51,295文字ログを21回保持し、次入力+18,667 |
| 既存explained-001 | 別内容の2種データを各40回保持、次入力+29,059。自作テストのGET/POST取り違えで確認が反復 |
| 既存explained-002 | 70行動/71calls、複数ツール要求0。51,112文字のシェル出力を67回保持 |
| 新規explore-002 | 2つの種データを各65回、51,455文字の起動ログを46回保持。プロセス終了操作にも反復・時間切れ |
| 新規explore-003 | 45callsだが平均82,001。初期のまとまった取得と後の再読込・起動ログが大きい |
| 新規explained-003 | 46calls、平均58,889。種データは残るが、5万文字級の確認出力がない |
| 新規explore-004 | 46calls、平均50,649。call5は原本をスクリプトで処理し、件数・先頭ID等538文字だけ返す。ただしその前に大原文を既に取得している |
| 新規preload-004 | 取得ラベル10件でも56calls、平均92,056。2種データを各53回、51,113文字の起動ログを29回保持 |
| 新規explained-005 | 89calls。種データを84回、起動出力を53回保持。生成した自作テストと修正が反復し、複数ツール要求も13件ある |
| 新規explore-005 | 71行動/72calls、複数ツール要求0。既存explainedで見た単独ツール型が別条件でも出現 |
| 新規preload-006 | 71行動/37calls。種データを34回、起動出力を15回保持。大きな出力があっても後続callsは少ない |
| 新規explore-006 | 95行動/45calls。種データを42回保持。SQLiteのdecimal Sum失敗をログで確認し修正。自作テストの文字列抽出と最終成果物の評価は区別する |
| 新規explained-006 | 89行動/36calls、複数ツール要求19件。種データは32回保持。自作テストの文字列不一致は後で解消、最終29要件合格 |
| 補充explained-007 | 106行動/50calls。種データ47回、起動出力29回、42,674文字の診断出力24回を保持。decimal Sumの修正・再検査が反復し、最終29要件合格。初回組の比較には入れない |

全Runの上位増分、その直前の行動、保持出力、未分類、品質の根拠位置は
[根拠索引](../artifacts/exploration/20260919/evidence-resumed-v2/evidence-index.json)にrequest ID・tool call ID・原本参照付きで保存した。
個別の意味の確認は[既存注記](../research/pilot-case-review.json)、[初回区間注記](../research/new-case-review.json)、
[再開後注記](../research/resumed-case-review.json)を参照。これらは事後注記で、固定分類を上書きしない。

### 行動と再取得

{mechanism}

取得・探索・修正ラベルは重複する。再取得は範囲単位であり、行動数とは一致しない。
未変更範囲の再取得もそれだけで浪費としない。編集後確認、部分重複、判定不能を分けて残した。
2つの同名SampleData原本は143行位置で異なり、先頭アルバムと登録順も異なる。単純な同名重複扱いは誤りになる。
シェル変数や加工出力の範囲復元には限界がある。新規explore-003のループ取得については、事後照合で後続readとの94行の部分重複と131行の未変更再取得を注記した。
自動表の確定再取得数は網羅的な回数ではない。未分類も失敗ではなく、スクリプト実行・ログ取得等の意味を個別注記した。
`FAIL=0`や依存ツールの例外も文字列検出に掛かるため、build/testエラー候補数をアプリ不具合数とは扱わない。

## 4. 品質との対応

新規preload-001はcall32のCS1501を修正してビルド成功したが、ViewComponentの `Content(html)` がHTMLを文字として返し、
Cart／ジャンルのリンクを壊した。保存評価R-010/C-011とエージェントによる実画面確認が対応する。自作の文字列検査は見逃していた。
同RunのR-029/C-030は `MvcMusicStore.sln` 名を根拠とし、参照先は新しいSdk.Web/net8.0である。
modern project除外がcsprojに限られるため偽不合格の具体的な疑いがある。公式93.1点は変更していない。
仮にその1項目を解消してもR-010が残り、このRunの品質合格にはならない。

新規preload-002はR-016/C-017で不合格。元のCart.csの `[Key] RecordId` は事前投入に含まれ、その後も入力に残ったが、
生成モデルでは属性もHasKeyもなく、実DBの主キーがCartIdになっていた。別商品追加で `UNIQUE constraint failed: Carts.CartId` が発生する。
これは情報の未到達ではなく、届いた制約が実装へ保持されなかった例である。自作テストのPASS56/FAIL0はこの違いを検出していない。
固定評価、アプリログ、DB/WALの派生コピーの読み取り専用照合を事例台帳へ記録した。原本は変更していない。

確認・修正の全てをアプリ不具合とは見なさない。例えばexplained-004の自作テストは再起動時にDBを削除するため、
そこでの旧注文消失だけから永続化不良とは言えない。explained-005もアプリ修正とテスト／セッション修正が混在する。
品質の対象は公開29要件であり、全機能・画面忠実度・注文詳細の全列を保証しない。

## 5. 次の主仮説と確認実験への条件

H1（事前投入と取得）、H2（大出力保持）、H3（まとめ方・反復）の支持例・反例・未確認を
[仮説台帳／設計案](ms1-exploration-20260919-hypotheses.md)に整理した。主仮説はH2の**カタログ原文の返却範囲**に絞る。
原本と同じ順序の全データを両条件のファイルへ保持し、同じ決定的抽出・共通の短い確認出力を用意した上で、原文の大出力の併記だけを変える案である。
原文側の対象範囲、出力上限、切詰め規則も採取前に固定し、片側だけ表示上限を拡張しない。
原文へアクセスする経路、投入時点、タスク、モデル、予算、ツール、評価条件は揃える。起動ログ抑制・プロセス制御・まとめ実行は同時に変えない。

予測は大入力の発生と後続保持が小さくなり、追加取得・修正で相殺されず総量が下がること。
全文再取得で差が消える、総量が下がらない、ID・順序・文字列・購入挙動を失う場合は支持しない。
短い機械処理結果を返す自然発生例は実装可能性の根拠であり、削減効果の実証ではない。
確認実験の必要数は、必要精度、意味のある最小削減幅、品質判定、資源、停止規則から別途決める。
provider報告値と送信原本の乖離の扱いも事前に定め、文字量・保持量を別指標として併記する。内部算定を確かめられない場合はprovider報告値に対する効果として解釈を限定する。
今回の最少値や探索での削減率を真の効果と仮定しない。独立した新しいRunで確認する。

## 6. 人の確認材料と研究正本

各条件の初回枠のうち完全計測・品質合格の総量中央値に最も近いRunを選び、同値は実行順が早いものとした。
補充と既存6は選定母集団へ混ぜない。

{chosen}

[人の確認手順](ms1-exploration-20260919-human-review.md)に起動方法、通常購入、無効checkoutの状態保持、
セッション分離、再起動後の注文保持と現行評価項目の対応を用意した。人の状態領域は自動確認と分離した。
自動の起動・画面確認は人の確認済みを意味しない。本実験前に不一致を解決する必要がある。
[研究正本の修正文案](ms1-exploration-research-protocol-proposal.md)も添付した。GitHubの正本へはまだ反映していない。
不可欠な要件追加が必要なら契約を改版し、新しいバッチとする。

## 7. 原本照合と再現

既存322＋新規{len(new['calls'])}＝**{len(calls)}呼び出し**、合計**{len(actions)}行動**を照合した。
独立したSSE再集計とハッシュ検査は**{sum(c['files_checked'] for c in checks):,}ファイル、不一致0**。
失敗explained-001のnative／request等の未生成による4監査指摘を残し、正常Runの結合漏れと混同しない。
重複ID、順序、欠測保持、複合行動、編集前後の範囲分類、補充制限、ネットワーク回収条件の19テストが通過した。
採取終了後、補充のSSEに `tool_calls: null` を確認したため解析v1.0.2で空のツール差分として読めるよう修正した。
usageや実際のツール呼び出しを捨てる変更ではなく、モデル再実行はない。採取時コードは別途バイト単位で保存した。
修正前に完了した初回18枠の全行と、既存6件の4集計表は再抽出後も一致した。元の初回区間1,023ファイルも再照合し不変だった。
採取後の分類注記・表示上の修正は[変更記録](../research/post-freeze-changes.md)へ分離し、固定入力・評価を変えていない。

| 成果物 | 保存先 |
|---|---|
| 既存／新規のcalls・actions・reads・runs | `artifacts/exploration/20260919/pilot-v1.0.1` / `new-resumed-v1` |
| 実行・補充台帳 | `artifacts/exploration/20260919/ledger-resumed-v1` |
| 分布・ブロック差・保持・図 | `artifacts/exploration/20260919/display-resumed-v2` |
| 全Run根拠索引 | `artifacts/exploration/20260919/evidence-resumed-v2` |
| 実行済みノート／HTML | [analysis.html](../artifacts/exploration/20260919/notebook-resumed-v3/analysis.html) |
| 独立検算／完了監査 | `independent-check-resumed-v1.json` / `completion-check-resumed-v1.json`（同日ディレクトリ） |
| 納品ハッシュ | `artifacts/exploration/20260919/delivery-manifest-resumed-v1.json` |
| 原本保存パッケージ | `runs/exploration-20260919-ms1/_archive`、各Runの `archive-reference.json` |
| 復旧記録・中断時の報告 | `artifacts/exploration/20260919/recovery-v1` / `runs/.../resume-v1` |

再現は未使用の出力ディレクトリへ行う。下記はモデルや評価器を呼ばない。

```powershell
python -m research.analyze --runs-dir runs/acceptance-64ad09cd85ca --cohort existing6 --out artifacts/reproduce/existing
python -m research.analyze --runs-dir runs/exploration-20260919-ms1 --cohort primary18 --plan research/protocols/ms1-001-exploration-20260919-resume-v1.json --out artifacts/reproduce/new
python -m research.ledger --batch runs/exploration-20260919-ms1 --plan research/protocols/ms1-001-exploration-20260919-resume-v1.json --out artifacts/reproduce/ledger
python -m research.validate --analysis artifacts/reproduce/existing/analysis.json --analysis artifacts/reproduce/new/analysis.json --out artifacts/reproduce/check.json
.\\artifacts\\exploration\\analysis-env\\Scripts\\python.exe -m research.summarize --analysis artifacts/reproduce/existing/analysis.json --analysis artifacts/reproduce/new/analysis.json --plan research/protocols/ms1-001-exploration-20260919-resume-v1.json --out artifacts/reproduce/display
.\\artifacts\\exploration\\analysis-env\\Scripts\\python.exe -m research.notebook --analysis artifacts/reproduce/existing/analysis.json --analysis artifacts/reproduce/new/analysis.json --summary artifacts/reproduce/display/summary.json --out artifacts/reproduce/notebook
```

解析用環境の固定リストは `analysis-environment.txt`。日本語報告の表は `python -m research.report` で今回の最終解析から再生成できる。
本納品はローカル保存であり、GitHubへの公開・確認実験・別タスク展開は実施していない。

## 参考

最終成果物とトレースの併用は[Anthropicの評価解説](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)、
順序設計は[NISTのブロック化](https://www.itl.nist.gov/div898/handbook/pri/section3/pri332.htm)を参照した。
確認の反復数は[Lakensの標本サイズ設計](https://lakens.github.io/statistical_inferences/08-samplesizejustification.html)を参考に別途正当化する。
'''
    target = ROOT/'docs/ms1-exploration-20260919-report.md'
    target.write_text(text, encoding='utf-8', newline='\n')
    print(target)


if __name__ == '__main__':
    main()
