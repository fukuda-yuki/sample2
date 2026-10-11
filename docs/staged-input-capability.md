# 固定 OpenCode の継続能力と未確定契約

この変更は単一条件の割付に既存Run部品を使えるようにする。新しい科学条件、
取得計画、要求分割、件数、予算値、実行承認は作成していない。
段階入力のproduction dispatchは未実装であり、取得開始可能・live受入済みとはしない。
Musicの大小文字別名とEducationのmarkerに関する限定裁定の変更は
[限定評価器修正](limited-evaluator-review.md)に分離する。
原判定は変更していない。

## 確認した能力

固定リリース OpenCode `1.17.11` の実バイナリを使ったループバックの合成試験。
取得済みRun、実モデル、provider credential、外部providerは使用しない。
試験は一時ディレクトリに合成workspaceと隔離されたconfig/stateを作り、終了後に削除する。
実験workerへの新しいbinaryの導入や既存runtime lockの変更はしていない。

```text
python outer/verify/probe-staged-session.py --opencode /absolute/path/to/opencode-1.17.11
```

- バイナリのversionと`run --help`で`--session` / `--pure`を確認する。
- 初回はstdinで合成要求を渡す。合成HTTP応答で`write` toolを動かし、実装ファイルの変更と完了eventを確認する。
- 初回CLIの終了後、同じworkspace・stateで`run --session <明示的なnative ID>`へ追加文をstdinで渡す。
- 同じnative session、workspaceの変更、初回要求の履歴保持を確認する。追加文は初回worker可読ファイルへ置かず、初回HTTP要求にないことを検査する。
- 初回呼出しからの1つのdeadlineを使う。追加呼出しで予算をリセットしない。

合成試験の実測は、初回2要求、追加文を含む最初の要求が0始まりindex 2、合計3要求、
native session 1つ。実装ファイルの変更と完了eventを観測した。これはモデル性能や
実研究Runの結果ではなく、固定CLIの終了後継続に関する能力確認だけである。
試験に用いたバイナリのSHA256は
`0254a429cd0e6cf0ba53fc01672cf98e4a8dc728f7fa94be88f1e4b3645e6ded`。

## tool完了境界の阻害

[固定版 run.ts](https://github.com/anomalyco/opencode/blob/v1.17.11/packages/opencode/src/cli/cmd/run.ts) は
`Bun.stdin.text()`を開始時に一度読み、通常の非attachモードでは
`Server.Default().app.fetch`へ接続するプロセス内SDKを使う。CLIに`--port`が表示されることは、
現在の非対話`run`が外部待受を持つ証明にはならない。完了toolはJSON eventへ出るが、
その出力によってsessionの次のmodel requestが停止するわけではない。

[固定版 prompt.ts](https://github.com/anomalyco/opencode/blob/v1.17.11/packages/opencode/src/session/prompt.ts) では
user messageの追加とsession loopが実装されている。これは既存単発プロセスへ外部から
安全に注入できる証明にはならない。同じDBに対して二つの通常`run`を同時起動すると、
共有された単一実行loop・注入位置・tool処理との直列化を保証できないので採用しない。

検討可能な代替は固定版の常駐サーバーと明示sessionへの送信、または停止・継続を定義した
別の境界である。前者は実行形態と制御経路を変え、後者は停止方法・投入時点を変える。
tool集合・permission・model・compaction・source/DB可視性を維持できても比較への影響は残る。
終了後継続を最初の実装変更tool完了という境界へ置き換えてよいとは判断していない。
版更新、tool変更、常駐サーバー化、kill/restartをproductionへ採用していない。

## 実装前に固定する契約

研究管理側から追加文1回と境界の候補を受領した。境界は、最初の実装file変更を含むtool終了後、
次のmodel request前である。tool名や成功buildだけでなく対象fileのhash差分を確認し、
失敗したtoolの変更も扱う。実装対象外file、並行tool/子process終了、symlink、snapshot時点と
未到達・追加前失敗・早期終了時の規則は実行計画とtransportに結合する必要がある。
通常終了後の追加送信はこの境界の代用にならない。安全な停止を検証できなければ未採用とする。
成功buildや採点成功を投入条件にせず、既存exploreとの運用比較として扱う。
計画と承認は既存campaign入口のhashに結合し、この文書を承認receiptへ転用しない。

transport決定後のproducer実装には次の証拠が必要である。

| 事実 | 必要な結合・保全 |
| --- | --- |
| 投入予定 | task/condition、Run UUID、初回・追加promptのhash、要求分割と境界の版。後続本文はcontroller専用でworker mountの外 |
| 境界の観測 | native session ID、tool/call/message ID、完了event、対象実装fileの変更。単なるbuild合格を代用しない |
| 実投入 | 同じRun UUID/workspace/native sessionへの送信intent、native message IDまたは確認receipt、単一writer。競合・重複・途中停止のunknownを維持し、自動再送しない |
| 最初のrequest | gateway request ID/hashと追加文のuser-role中の位置・一意性、送信前検証と観測sendの区別。初回向け入力証明だけで追加到達をpassにしない |
| 終端と資源 | 初回から通算の時刻/usage。未到達・早期終了・追加前失敗を残し、段階間で回収/採点しない。停止確認後だけ最終回収/採点 |

既存pipelineの再試行条件は `pipeline-acquisition.json.acquired == false` の割付枠である。
`acquired == true` の未採用枠は取得から除外し、保存物の評価回復へ送る。
新campaignでは旧評価除外によるモデル再取得を許さない。未知sendと資源未回収は停止する。
既存の有限 `max_pair_attempts` に従うfresh UUID技術再試行を維持したため、
候補の「既知の送信前準備失敗のみ1回、送信後再取得0」はまだ実装・採用していない。
この差を含め、件数・通算予算・retryとtransportの固定、および当該計画への実行承認が必要である。

gateway/live_usageの段階別証明、実transportの重複・停止競合テストとDocker受入は未実装・未実施。
単一条件のfixtureは旧2条件の再開互換、1条件の予約・回復・重複防止、全試行資源を検証するが、
段階入力のlive受入を代用しない。公開内容はコード・合成fixture・能力確認に限定する。
