# 実験一覧と読み方

この一覧は、取得実験、保存生成物の再評価、分析追補を区別する入口です。branchやworktreeを切り替えず、各行の報告書から必要なデータ・コード・再現手順へ進めます。

| 実験・派生物 | 種類・関係 | 報告書 | データ・コード・再現手順 |
| --- | --- | --- | --- |
| `source-information-two-families-20261003-v5-100p2` | 原100ペア・200割付。固定済み要求・評価器による原結果を保持 | [原報告書](../research/source-info-v5-final-analysis-20261005/REPORT-ja.md) | [専用Release](https://github.com/fukuda-yuki/sample2/releases/tag/source-info-v5-100p2-f39b38adc6bb-final)の`analysis.zip`、[再計算と必要データ](../research/source-info-v5-final-analysis-20261005/README.md) |
| 同実験の分析追補v2 | 原100ペアの再分析。新規取得・再採点を増やさない | [追補v2](../research/source-info-v5-analysis-v2-20261006/REPORT-ADDENDUM-v2-ja.md) | 同Releaseの`analysis-v2-iterative-20261006.zip`、[データ・コード・再計算](../research/source-info-v5-analysis-v2-20261006/README-ja.md) |
| 評価器修正後の保存生成物再評価 | 修正版の新`assessment_id`と`evaluation_version`で原`run_instance_id`・`artifact_sha256`へ結合する別評価。実取得件数に加算しない | 実行済みの評価receiptと報告書が揃ってから、この行へ固定linkを追加する | 原採点・原Releaseのbytesを維持。新評価の結果・比較表・コードを別パッケージに置く |
| 次の取得campaign | 新campaign UUID、新Run UUID、新保存先、新固定条件による取得。今回のアダプター試験は取得実験ではない | 未取得 | [ID・保存・配布の契約と開始前の統合ゲート](experiment-identity.md) |

Release内のMANIFESTだけを自己証明として信頼せず、Release本文の固定SHA256と取得ファイルを照合してください。元報告書と追補は、その時点での結論です。評価器修正後の結果を原評価器による結果へ置き換えません。

## 比較できること・そのまま比較できないこと

| 比較 | 必要な対応 | 比較上の制限・理由 |
| --- | --- | --- |
| 原評価と修正版再評価 | 同じsource Run UUID・同じ保存生成物SHA、旧・新評価版、checkごとの仕様とoracleの対応 | 品質判定の差を評価変更に関連付けられる。観測しなかった過去のUI操作や要求payloadを復元したとは言えない |
| 原取得と新campaign | 別campaign・別Run UUID、要求・モデル識別・介入・資産・評価器・取得運用の対応表 | 新モデル、要求、評価器、取得方式が異なれば単純な介入差にまとめない。共通要求を同じ評価版で比較する範囲を明示する |
| 分析v1と追補v2 | 同じ原dataset SHAと派生コード・結果の版 | 新しい独立Runが増えたとは扱わない。再計算一致と品質証拠の独立再監査を区別する |

新規結果を追加する際も、入口はこの一覧→報告書→必要なデータとコード→再現手順の順に保ちます。private oracle、生ログ、APIキー、非公開評価資材を公開パッケージへ自動収集しません。
