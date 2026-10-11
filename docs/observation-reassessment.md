# 同一specの観測revisionと共通bundle

`observation-20261011-v1` は、既存の要求・spec bytes・spec versionを保った
観測実装の明示revisionである。新しい課題や要求版ではない。Musicの`1.6.0`、
Educationの`education-1.1.0`を変更せず、新DLL、build receipt、image、browser、
対象Runと旧評価hashをprivate入力で固定する。通常のschema-2 RunへDLLを
差し替える禁止規則と、旧技術復旧adapterの適用範囲は変更しない。

この入口はモデル取得・実データ再評価の実施済み証明や承認を作らない。
公開リポジトリへ実plan、bundle、prompt、Run、復元receiptを追加しない。
実bundleの受入は別工程で行う。人工fixtureの通過で代用しない。

## 1. 2系列の共通revisionファイル

private JSONは次の形とする。`path`は絶対path、`sha256`は実測64桁hex。
下記の説明用placeholderは実行入力ではない。

```json
{
  "kind": "same_spec_observation_revision_v1",
  "revision_id": "observation-20261011-v1",
  "families": {
    "music": {
      "bundle": "/private/accepted/music",
      "build_receipt": {"path": "/private/accepted/music/build-receipt.json", "sha256": "MEASURED"},
      "evaluator_sha256": "MEASURED_MUSIC_DLL",
      "images": {"worker": "sha256:MEASURED", "evaluator": "sha256:MEASURED", "gateway": "sha256:MEASURED"},
      "spec_sha256_by_task": {"MS1-CONT-A": "FROZEN_SPEC_A", "MS1-CONT-B": "FROZEN_SPEC_B"}
    },
    "education": {
      "bundle": "/private/accepted/education",
      "build_receipt": {"path": "/private/accepted/education/build-receipt.json", "sha256": "MEASURED"},
      "evaluator_sha256": "MEASURED_EDUCATION_DLL",
      "images": {"worker": "sha256:MEASURED", "evaluator": "sha256:MEASURED", "gateway": "sha256:MEASURED"},
      "spec_sha256_by_task": {"CU1-ENR-C": "FROZEN_SPEC_C", "CU1-ENR-D": "FROZEN_SPEC_D"}
    }
  }
}
```

build receiptは既存のaccepted-bundle形式を使う。

- `evaluation_version`、`sdk: "8.0.425"`、実際の`source_commit`、
  `source_worktree_clean_at_start: true`、実行した`commands`を保存する。
- `observation_revision: "observation-20261011-v1"`を明示する。
- `source_files`（または`sources`）の`path`/`sha256`はrepo相対pathで、
  当該projectの全`.cs`/`.csproj`を含める。`global_json_sha256`も必須。
  現在ファイルとそのcommitのGit blobの双方へ照合する。
- `deployable_files`（または`bundle_files`）は配布物全件の
  `path`/`sha256`/`bytes`。receipt自身は除く。依存DLLも省略しない。

既知の旧DLL SHAをrevisionへ付け替えること、別specを同じ版と称すること、
bundleやreceiptを固定後に交換することは拒否する。同系列の2task・両条件は
この同じ1つのbuildを使う。新DLLのSHAをpublicコードへ埋め込まない代わりに、
revisionファイル自体のhashを各runtime lockと各再評価planへ結ぶ。

## 2. 受入・本取得用の新runtime

新規profileは`deepseek-music-observation-v1`と
`deepseek-education-observation-v1`。モデル・CLI・SDK・予算・入力アクセスは
旧repaired profileと同じで、保存名前空間だけを分離する。

`research.repaired_runtime`の既存引数に
`--observation-revision /private/revision.json`を追加する。
`--runtime-id`には上記新profile、`--accepted-bundle`とreceipt引数には
revisionに固定した実物を渡す。`--prior-lock`は実際に準備されたimageの
lockでなければならない。既存imageがない／gateway sourceが古い場合は、
別のclean build checkoutで通常のimage準備を行い、その実測lockを使用する。
既存namespaceの上書きや、作っていないimageのlock捏造はしない。

旧namespace・旧lock・旧DLL pinは維持する。新lockはbundle全量、receipt、
現在controller、両taskのspec/input、revision hash、immutable imageを照合し、
SDK/CLIをnetwork-noneで実測する。image内の旧scorerは使わず、固定した
`/assets/evaluator`のDLLを通常採点経路で使う。
受入と本取得のcampaign planはこの同じ新lockを参照する。

## 3. 旧passを含む固定選択の別出力再評価

private selection planは次の4フィールドを持つ。

```json
{
  "kind": "selected_observation_reassessment_v1",
  "revision": {"path": "/private/revision.json", "sha256": "MEASURED"},
  "browser_pin": {"path": "/private/browser-pin.json", "sha256": "MEASURED"},
  "selected_runs": [
    {
      "source": "/private/original/run",
      "run_id": "ORIGINAL_RUN_ID",
      "run_instance_id": "ORIGINAL_32_HEX_UUID",
      "manifest_sha256": "ORIGINAL_MANIFEST_HASH",
      "condition_sha256": "ORIGINAL_CONDITION_HASH",
      "artifact_sha256": "ORIGINAL_ARTIFACT_HASH",
      "evaluation": {"path": "/private/original/run/evaluations/001/evaluation.json", "sha256": "ORIGINAL_EVALUATION_HASH"},
      "evaluation_id": "ORIGINAL_EVALUATION_ID"
    }
  ]
}
```

既存の3固定JSON等から選択台帳を生成する作業は研究管理側で行う。
このコードは対象数や対象者を推測せず、渡された全件を固定する。
今回のselected200は全200行を列挙する。品質、旧pass/fail、recoverable判定で
絞らない。UUID重複、対象外source、旧indexと一致しない評価hashは拒否する。
同じ`evaluationId`は許容し、元UUID・旧評価hash・新`assessment_id`で区別する。

```bash
python -m research.observation_revision /private/selected.json /private/new-assessments --repo /checkout
python -m research.saved_reassessment execute /private/new-assessments/RUN_UUID --repo /checkout
python -m research.saved_reassessment revalidate /private/new-assessments/RUN_UUID /private/validation/ASSESSMENT_ID.json --repo /checkout
```

最初のコマンドは全対象を検証・複写して`selection.json`を作るだけで、採点しない。
既存出力へ再prepareしない。個別prepareには既存CLIの
`--observation-plan /private/selected.json`を使用できる。
executeは同じplan/build/spec/sourceを再照合し、evaluator imageとSDKを実測し、
固定browser環境で既存の隔離HTTP→browser採点を使う。評価は直列に呼ぶ。
1800秒を超える評価timeoutは拒否する。中断済みoutput/probeを上書きしない。

revalidateは新しい検証receiptだけを書く。原Runのmanifest・snapshot・index・
原評価・DBを更新しない。観測不足やfaultのqualityはnullを保ち、旧passから
新passを補完しない。結果の採用は既存のidentity・browser coverage・cleanup等の
検査を通った場合に限る。再評価の使用量を新しいモデルRunの使用量へ加算しない。

## 4. 派生復元物の追加証明

原本sourceには通常の`profiles.validate_run`を使う。復元sourceも同じ検証を
通した上で、selection行の任意の`restoration` path/hash参照を追加する。
復元receiptは`restored_to`、選択台帳と一致する`original_manifest_sha256`、
preserve archiveの絶対path `archive`、全復元fileの`files`を持つ。

`files`は復元root相対pathから、
`{"reference": {"package_id": "...", "sha256": "..."}, "member": "保存member名", "original_sha256": "..."}`
への対応表である。複数の既存保存packageのmemberを明示できる。
package本体・index・参照package、保存member、復元bytes/size、原manifest hashを
別々に確認し、未記載の追加fileも拒否する。

不足member、差分、原manifestとの不一致はholdとなる。復元都合のmanifest再生成、
spec/version変更、hash検査の省略、無証明のZIP展開を原本扱いする機能はない。
