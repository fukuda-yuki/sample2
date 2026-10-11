# 固定 OpenCode の追加入力経路と検証範囲

単一条件 `staged-explore` に、初回から通算の時間枠内で追加文を1回だけ渡す経路を追加する。
同じ Run UUID・workspace・native session を使い、元sourceとDBへのアクセスを保持する。
これは実装候補であり、Docker上の受入、実モデルでのlive受入、研究上の実行承認は未確認。
要求分割・対象file範囲・件数・予算・再試行回数を値入りの研究計画として作成していない。
[限定評価器修正](limited-evaluator-review.md)は別の変更で、既存保存物の原判定は変更しない。

## 固定版で確認できた経路

OpenCode `1.17.11` の実バイナリとループバックの人工providerで確認した。
バイナリのSHA256は
`0254a429cd0e6cf0ba53fc01672cf98e4a8dc728f7fa94be88f1e4b3645e6ded`。
試験は一時workspace・独立したconfig/stateを作り、終了後に削除する。
実モデル、provider credential、保存済み研究Runは使用しない。既存runtime lockや取得版は更新しない。

```text
python outer/verify/probe-staged-session.py --opencode /absolute/path/to/opencode-1.17.11 --observe-boundary
python outer/verify/probe-staged-server.py --opencode /absolute/path/to/opencode-1.17.11 --gateway-barrier
```

通常の `run` は [run.ts](https://github.com/anomalyco/opencode/blob/v1.17.11/packages/opencode/src/cli/cmd/run.ts)
でstdinを一度読み、非attach時にはprocess内のserverを使う。tool terminalのJSON出力には
次のrequestを停止するACK手順がない。初回CLIの終了後に `--session` で再開できることは確認したが、
それを最初の実装変更tool終了の境界には使わない。通常のCLIを2つ同時起動する方式も使わない。

候補経路は同じ固定版の `serve --pure --hostname 127.0.0.1` と `run --attach --session`。
[session prompt](https://github.com/anomalyco/opencode/blob/v1.17.11/packages/opencode/src/session/prompt.ts)
の `noReply: true` はuser messageの追加後に戻るため、別のmodel loopを起動せず、保留中の
同じsessionへ追加できる。gatewayはprovider SSEの `[DONE]` 行だけを一時保留し、先に届いた
固定版 `write` toolが終了することを実バイナリで確認した。その保留中にnative messageを追加し、
ACK後に元の応答末尾を開放すると、同じloopの次のrequestが追加文を含む。

実gatewayを使った人工試験では、native session 1つ、追加user message 1つ、request合計3件。
追加文は初回requestに存在せず、境界直後のrequestに初回履歴とともに存在した。
同じ実装fileが追加後にも変更され、usageは3件の合計36 synthetic tokens、段階証明の不一致は0。
これは有限のtool/API/証跡の能力試験であり、モデル性能や実研究Runの結果ではない。

## 実装契約

`profiles.create` は、hashで固定した元の最終要求を、明示したsection一覧へ過不足なく分割する。
sectionの重複・欠落・順序変更と元要求の変更を拒否する。共通wrapperは初回に残し、source preloadは行わない。
初回promptだけをworkerのinputsへ置き、追加本文は `_controller/staged-input` へ保存する。
controller領域はworkerにマウントせず、初回前にinputs/workspace/stateの本文漏洩を検査する。
追加文はowned containerへの `docker exec` のstdinからnative APIへ渡し、argv・環境変数・初回worker fileには置かない。
gatewayのみcontroller領域をread-onlyで参照し、本文を独立に照合する。

| 証跡 | 記録と制約 |
| --- | --- |
| 予定 | Run UUID、task/condition、初回・追加prompt hash、partition、明示transport/snapshot policy、元の予算、delivery ID |
| 境界 | gateway request ID/hashとtool call ID、native terminal message/session ID、file hash差分、全tool終了、子process不在、保留barrier ID |
| 投入 | hash連鎖のcontroller ledgerでintent、send-return、native ACKを分離。単一writer、ACK不明・停止・競合で自動再送しない |
| 最初のrequest | gatewayが追加文のuser-role中の一意性とrequest原本hashを照合。最初の観測requestと最初の送信requestは別項目。native ACKだけでprovider到達としない |
| 終端 | 初回からのwall/monotonic deadline、全request usage、未到達/早期終了/追加前失敗/unknown、停止確認、最終snapshotを保持 |

実装fileのscopeは実行計画のsuffix/excluded-directory一覧で固定する。symlinkを拒否し、build合格や
採点合格を条件にしない。toolが失敗していても実装fileが変われば候補となる。read-only toolでは
snapshotと保留解除を記録する。複数toolを含む応答で変更が起きた場合、最初の変更を個別toolへ
帰属できないためunknownとして停止し、都合のよい後続境界へ進めない。未完了tool・子processが
残る間は投入せず、元のdeadlineで停止する。追加文なしのrequestが投入境界を越える場合も拒否する。

`runtime` が既存containerの所有権・mount・Run UUIDを確認してnative APIを操作する。
既存のmodel ID、provider、tool権限、question deny、LSP/compaction設定、入力分離を維持する。
段階間に回収・採点を行わず、最終停止後に既存の回収・採点部品へ戻る。未到達でも初回入力と
usage/停止証拠が完備する終端は、追加到達をfalseのまま保持する。観測障害を到達成功へ変換しない。
私有archiveにはcontroller原本も含める。public公開allowlistは広げない。

## 明示計画と停止・再開

[新campaign入口](campaign-initialization.md)で `staged_inputs`（taskごとのpath/hash参照）と
`staged_retry` の両方を必須にする。partitionのkindは `staged_request_partition_v1`、transportは
`opencode-server-response-barrier-v1`。`known_pre_dispatch_retries` は明示した0または1、
`after_dispatch_retries` は0のみ。既知の準備失敗receiptとdispatch不存在・usage不存在が揃う場合だけ、
承認された準備retryを許す。送信後・不明・証跡不十分は新UUIDへの取り直しも保留する。
旧2条件の再開形式・retry規則は変更しない。停止・未知sendからの自動session継続は行わない。

この実行形態は通常の単発CLIと異なる。provider応答の保留時間、controllerのsnapshot時間と
待機時間も初回からの通算予算に含まれる。既存exploreとの比較は運用比較であり、時機だけの
純粋因果効果とは扱えない。この経路を採る明示実行計画と、その計画hashに対する実際の実行指示が必要。
本実装依頼を実取得の承認に読み替えない。

## 残る検証

通常テストはcontroller、gateway、SSE chunk分割、ACK消失、重複/外来ID/停止、失敗toolの変更、
並行toolのunknown、子process待機、予算非reset、未到達保持、producerの漏洩検査、単一条件と旧経路を検証する。
実バイナリ試験は有限の組込みwriteだけであり、任意のbash/並行toolや長時間tool、Windows Dockerの
process/mount/loopback、container UIDによるcontroller file読込みを受入済みとはしない。
Docker adapterは人工transport/command fixtureで検証した。実Docker・実モデル試験、課金API、
実保存物の再採点は実施していない。安全な継続のlive受入を済み扱いせず、PRはDraftを維持する。
