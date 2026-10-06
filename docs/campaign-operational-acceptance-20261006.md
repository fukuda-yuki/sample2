# 非モデルの実運用 campaign 受入

この受入は既存 100 ペア / 200 Run の追加取得ではない。2 campaign の各 1 ペア、合計 4 dummy Run と 1 別保存 reassessment に限定する。モデル prompt は送らず、OpenCode 1.17.11 の実 session HTTP API と、保存済み byte inventory を読む実 subprocess を区別する。要求品質と token 効果の結論は得られない。

新しい `research/campaign_operational.py` は変更していない `pair_execution.execute_pair`、`ownership.lease`、`resource_supervisor.ProcessMonitor`、`runtime.fence_owned` / `stop_owned` / `cleanup_network` を使う。新 phase は非モデル fixture kind を明示し、呼出側と独立 observer が新 plan の実行 source hash を検証する。旧 v5 protocol、v1–v10 の取得 pin、原 Run、旧 Release を変更しない。

有限受入では各ペアを serial concurrency 1 に固定する。session と child の STOP 境界を一つずつ観測し、資源使用を抑えるための選択である。今後の同一ペア 2 並列取得を検証したことにはならない。旧 100 ペアの 2 並列実績とは別の証拠である。plan の `source_commit` は準備時の実 Git HEAD の宣言、各 module SHA は実行 bytes の primary pin とする。

120 秒は worker 所要時間の見積りであり、強制 worker wall-clock 上限ではない。個々の subprocess / Docker 操作には最大 120 秒の timeout を置く。親の 900 秒監督は最初の `runtime.json` 作成（最初の Docker 起動前）から全 4 Run の cleanup と 2 observer の shutdown ACK までの live resource phase に適用し、読取りだけの before/after 全体照合時間は別記録にする。期限時は固定 plan SHA / 4 UUID に結合した `emergency-stop` で campaign/observer STOP を記録し、親が controller を停止してから再度所有 runtime を回収する。進行中の setup と STOP の原子的切替をこの補助 CLI だけで保証しない。親が各 observer の正確な config/session/phase/generation と PID に結合して shutdown、ACK、終了を別確認する。ACK が得られず所有プロセスを終了した場合は ACK 不成立を記録し、受入完了としない。unknown/foreign resource を消さない。

各 Run に専用の UUID、root、workspace、state、内部 bridge network、worker と gateway がある。既存の pinned worker image で `opencode serve` を起動し、session create/read/abort、空 message と idle status を観測する。dummy artifact subprocess は同じ所有 worker 内で partial を書き、実 observer の worker/gateway stats sample が UUID に結合されるまで待つ。normal は明示 sentinel を解放して正常 exit と final artifact を確認する。middle STOP は解放せず、停止直前の child 生存と final 不在、停止後の final 不在を確認する。停止確認後だけ frozen へ回収する。

gateway は既存 production handler を使うが、credential は inert 定数、upstream は専用 network 内の `127.0.0.1:9` とする。host provider key は読む経路も worker/observer に渡す経路もない。モデル endpoint は ACK 後の admission 拒否テストだけであり、通常なら受付条件を満たす synthetic payload の 403 と gateway event/payload 記録 0 を照合する。負の local HTTP control/admission request はゼロモデル呼出とは別に記録する。

準備で原 200 Run tree と既存 7 assessment tree 全体の regular-file SHA inventory を取得し、終了後に同じ 8 tree の FULL after inventory と完全比較する。復旧計画では取得済み before proof を SHA・8 scope・200 manifest count・固定 UUID registry・コピーした metadata/input pin に結合して再利用し、実行直前の原 tree 再走査を重複させない。これは新しい current-before snapshot を取得したという主張ではない。worker は原 tree を共有マウントせず、固定したコピーだけを使う。after の欠損、不一致、未完了時は公開 projection と pair gate を採用しない。保存 source の campaign registry が確認できない場合は `caller_asserted_unverified` とし、架空の campaign UUID を与えない。新 reassessment は登録済み新 campaign の Run UUID と source artifact SHA を結合し、新 evaluation version と assessment UUID を持つ。取得増分は 0。

全 entry で kind、整数型を含む固定上限、4 つの lowercase 32-hex Run UUID、campaign/Run 名、case-insensitive collision、原本との path overlap を書込み前に検証する。raw path と ancestor の symlink/junction は resolve 前に検査する。停止経路は固定 plan SHA、安全な path scope、UUID と実資源の所有 label に限定し、before proof、コピー input、実行 source pin の破損を owned stop の拒否条件にしない。完全性の検証は prepare/execute と normalize/finish の採用 gate に分離する。

最初の公開 projection は `operational-prepublication.json`。4 Run の session/stop/cleanup/observer ACK を保持するが、production pair journal の公開 gate は pending と記す。公開用 builder は親担当の `research/evaluator_publication.py` であり、report → data → code → reproduction の相対パスだけを含む。私用 DB、raw log、oracle、host 絶対パスは公開しない。

親が実 Release の匿名 download と別フォルダ復元を検証した後、`finish-publication` は外部 proof SHA、package SHA、正確な campaign / 4 Run / assessment identity、publication・roundtrip・cleanup 各 receipt の SHA を照合し、既存 `pair_execution.record_pair_gate` にのみ追記する。再送や再採点はしない。最終 projection は phase A の検証 SHA と package SHA を含み、自己 digest の循環を避ける。ローカル復元を匿名 remote 公開と呼ばない。

再現 CLI:

```text
python -B -X utf8 -m research.campaign_operational prepare <exclusive-short-root> --repo <repair-repo> --original <immutable-v5-root> --protect <stage> ...
python -B -X utf8 -m research.campaign_operational execute <exclusive-short-root>/plan.json --repo <repair-repo>
python -B -X utf8 -m research.campaign_operational finish-publication <exclusive-short-root> <actual-external-proof.json> --receipt-sha256 <trusted-proof-SHA> --package-sha256 <trusted-phase-A-package-SHA>
python -B -X utf8 -m research.campaign_operational emergency-stop <exclusive-short-root> --repo <repair-repo> --plan-sha256 <trusted-plan-SHA>
python -B -X utf8 -m unittest research.tests.test_campaign_operational research.tests.test_experiment_identity
```

source pin が変わった plan、既存 root、既 dispatch UUID、foreign/stale STOP、lease collision、missing observer ACK、品質不明の partial、回収後の byte 変更、異なる package / campaign proof は拒否する。実 session lifecycle の成功は実 prompt/SDK generation や新 100 ペア dispatcher の対応を証明しない。実行結果と証跡は exclusive 受入 root に保存し、本書の計画記述と区別する。
