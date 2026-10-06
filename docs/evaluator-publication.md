# 評価器修正の公開投影と再計算

`research/evaluator_publication.py` は保存assessmentの公開可能な最小投影と、
公開JSONだけからの報告値再計算を担当する。標準ライブラリだけを使い、provider・
評価器・browser・Docker・Gitを呼ばない。原100ペアの公開物を置き換えない。

入力は明示したassessment root、固定validation receipt SHA、事前計画である。
`normalize_assessment`は固定validation digestとassessment全体のbyte inventory、保存出力・baseline両hashを照合し、UUID、親Run UUID、
artifact/spec/DLL SHA、計画commitの宣言、台帳IDと判定ラベル、coarse確認だけを出力する。
DB、private oracle、要求入力値、観測本文、生ログ、画像、評価器binary、ホストpathは
出力しない。source campaign registry UUIDは未検証なのでnullを維持する。

既存7件は5種類の保存生成物へ結合した7つの評価実行である。後から実行した評価版は
新assessmentを追加し、既存行を書き換えない。validation IDは採用ゲートの別検証で
あり、評価実行や新取得を増やさない。非モデル運用の2campaign・4dummy Run・1assessment
は別の種類として記録し、研究サンプルへ加算しない。

`derive`は実公開行の要求・check inventory、版、来歴、coarse確認を検証する。
現行の両評価器と同じ等重みの要求品質をcompleteに限って再計算し、critical failureを
別に判定する。severityを数値weightへ変換しない。partial・faultはquality nullを
維持する。bound reported failureと未観測scope・cascade warningは別fieldに残し、
すべてのraw failを独立に確認した製品不良へ変換しない。criticalの報告failラベルと
未観測ラベルも別配列で再計算する。

`observation_scopes`はassessment IDに結合した別の公開sidecarである。checkの
`unknownObservations` / `observationFaults`とoutputの未観測・障害markerをcoarse
booleanへ投影する。private本文は出力しない。Failと未知・障害scopeが同時に存在しても
未知scopeを消さず、complete qualityへ昇格させない。旧7公開rowのbytesとSHAは維持する。
sealed packageには全assessmentのscope sidecarが必須である。

## Sealと公開後gate

`seal_package`はoperatorが固定した次のpolicyを要求する。

```text
package_id
expected_assessment_ids          # 実行済み全件の正確な集合
expected_assessment_versions     # assessment ID -> 正確な評価版
required_history_assessment_ids  # 保全する原7assessment、重複なし
required_history_row_sha256      # 原7公開行のcanonical JSON SHA
required_evaluation_versions     # 新分類revisionを含む必須版
required_phase                  # prepublication / final
```

新revisionの評価が未完了、operational receiptが未提供、IDの欠測・余分・衝突がある
場合はsealしない。prepublication版Aは公開gate未完了をそのまま示す。rootがAを実際に
公開・匿名取得・再計算した証跡をproduction journalへ結合してから、別のfinal版Bを
作る。BはAのpackage/verification SHAと4Runの実publication gate完了を要求する。
Aを上書きせず、自分自身のpackage digestを自己証明へ使う循環を作らない。

packageにはINDEX、report、最小data、derived results、reader、README、NOTICE、
相対pathのmanifestを含める。追加コードもoperatorの明示allowlistだけを使う。
公開review前にstaging全体を自動収集したり、private入力設定をZIPへ入れない。
NOTICEは原repoや第三者素材への包括的licenseを作るものではない。

## 読者の再計算

専用Releaseの正確なZIPを別フォルダーへ展開し、Release本文で固定したMANIFESTの
SHA256を使う。Windows CPython 3.14.4、標準ライブラリのみ。

```powershell
python -B -X utf8 <展開先>/code/evaluator_publication.py reproduce `
  --package <展開先> --expected-manifest-sha256 <Release本文のSHA256> `
  --out <未作成の別フォルダー>
```

readerは全manifestファイルのsize/SHAと完全inventory、ID、seal phaseを検証してから、
実公開行を再計算する。`results/summary.json`とのbyte一致、終了0、新出力のreceiptが
揃った場合のみ成功。改竄、未列挙ファイル、unsafe path、出力再利用、未知quality method、
partial品質の昇格を拒否する。packageと異なるworking directoryでも実行できる。

これは派生報告値の公開再計算であり、private oracleを使ったfull scoring replayや
品質意味の独立再監査、将来の無故障、本格100再取得の開始可を保証しない。
実公開・匿名downloadの操作と証跡はrootが担当し、ローカルstagingだけで成功を称しない。
