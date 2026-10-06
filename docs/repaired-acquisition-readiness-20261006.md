# 修正評価器を使う新しい取得の準備

この変更は取得基盤の準備である。新しい100ペアの開始許可と、実モデルによる
パイロットの終了証拠は、保存した計画と証跡で別途確認する。

## 固定する条件

- モデルはOpenCode Goの`deepseek-v4.1-flash`、Use balance OFF、paid fallbackなし。
- Run上限1800秒、provider上限600秒。ペア内2 Run、Run内部1、ペア間は逐次。
- タスクのcanonical IDと公開要求・入力方式を維持する。新しいtask revisionは
  `evaluators-20261006`。Musicは1.6.0、Educationはeducation-1.1.0。
- 受入済みDLLの原本とbuild receiptを保全し、別runtime namespaceへコピーする。
  旧imageのSDK・OpenCode・gatewayを検証して再利用し、採点時はマウントした
  受入済みDLLを実行する。過去のbuild時点のclean/commit情報と、現在のcleanな
  controllerへの適用確認は別の事実として記録する。
- User環境変数のキーは既存のgateway専用bootstrapだけが読む。worker、評価器、
  監視プロセスへキー、研究者のAGENTS.md、研究Skill、共通設定を渡さない。

## 有限パイロット

`research.live_pilot`はMusic AとEducation Cの各explore/preloadを実行する。
固定済み2ペア・4 Run UUID、最大4 dispatch、Run再送・replacementなし。
個別上限の合計は7200 Run秒、全体9000秒、観測request上限600、観測input+output
token上限30,000,000、空きディスク下限8 GiBとする。request/tokenの値は観測後の
停止閾値であり、provider側のhard quotaを保証しない。

各ペアに独立journalを用意し、双方の停止後にHTTP・browser採点、usage、archiveを
直列処理する。別プロセスのobserverは事前にscopeを確認し、STOP時は正確な所有
gatewayをfenceする。完了には実model request/response、native session、停止、
network cleanup、usage、evaluator、observer ACKと資源証跡の照合が必要である。
生成物の正しい不合格・部分評価は技術基盤の障害と区別する。元200 Runの再送はしない。
このパイロットのpublic gateはpendingのまま記録し、成功gateを作らない。
起動は`research.live_pilot_launcher execute`で独立した子controllerを所有する。
異常終了または9000秒の観測閾値では、固定UUIDとphaseにSTOPを記録して所有Runを
停止する。停止用の子プロセスも有限時間で回収し、未確認状態を成功に変換しない。
launcherやホスト自体の喪失、controllerのobserver孫プロセスの未確認状態は制限として
残し、失敗時のbound observer ACK・unknown・manual resolutionを区別して記録する。

## 次の100ペア

`research.acquisition_readiness`は新しいkind `source_info_repaired_v6_main`を扱う。
旧v5 protocolのbyte pin `d055265291721575a301fc7e44640ad2888730a0fb8427936bd239fc7ef12a25`
と既存の固定シード割付関数を使用し、4タスク各25ペア、先行arm全体50/50、
variant内13/12または12/13、無作為順序、4ペアのsession groupingを維持する。
行政上のattemptは6001–6100、Run UUID・cohort・保存rootは新しく固定する。

新mainの有限監視上限は200 Run、360000 Run秒、全体450000秒、観測request30000、
観測input+output token1,500,000,000、空きディスク8 GiBである。これらは停止用の
上限であり、成果の目標や改善判定ではない。再起動したcontrollerも以前の全dispatch
と停止済みusageを再登録し、最初のdurable開始時刻から全体上限を確認する。

`check`と`create`はモデルを呼ばない。取得には、新main計画のSHAと
`new_100_pairs_200_runs` scopeを持つ明示的user approvalが必要である。
`execute-pair`は指定した1ペアだけを実行し、次のペアへ自動進行しない。
実起動ではbounded launcherへ`--pair`を渡し、その子として`execute-pair`を呼ぶ。
各起動の観測wall上限9000秒と、main開始時点からの残りwall上限の小さい方を使う。
前ペアの実publication・独立restore・所有scratch cleanup gateを照合してから
次ペアを許可する。未知の送信、未確認停止、未確認採点、既存intentを再送しない。
公開候補の作成・exact review・公開・匿名復元・独立抽出・所有scratch cleanupは
`research.acquisition_sharing`を使用する。新kind専用の公開tagと改訂済み公開要求・
spec・READMEを使用し、注入した模擬transferをmainの実公開gateへ採用しない。

旧protocol・既存Run・旧評価を上書きしない。新mainの科学的主張は既存の研究目的、
要求品質とRun全体input/output tokenに従う。技術パイロットや評価器の合格だけで
人間による品質保証・一般化・provider内部モデルの同一性を主張しない。
