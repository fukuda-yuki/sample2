# 公開要求に基づく限定評価器修正

## Music R-014 / R-015

公開ledger [R-014/R-015](../inner/spec/requirements-cont-A-1.6.0.json) は、削除後の
JSON `ItemCount` がそれぞれ1/0で、明細と合計も対応することを要求する。
現在の1.6経路は大小文字を無視してメンバーを探す一方、その個数を1に限定していた。
研究管理側の限定裁定に合わせ、**異なる綴りの大小文字別名がすべて同じ正しい整数を持つ**
場合だけを受け入れる。追加の別名が正しい値と矛盾しないことを通常採点経路で検証する。

欠落、異なる値、null、文字列、小数、範囲外値、JSON非object、構文不正は受け入れない。
同一綴りのJSONキー重複が同じ正値を持つ場合は今回の裁定対象外でblockedとする。
矛盾・誤値が確認できればfailを保持する。保存済みの原判定は書き換えない。
HTTP500、誤ったalbum/数量、誤った合計、browserによる独立の不具合は別々に失敗する。
未観測応答はblocked、観測障害はerror、観測障害と確認済み失敗が共存すると失敗を保持する。
保留項目を分母から落とす集計や、人間確認済みへの変更は行わない。

`RemovalAliasTests` は一般公開要求から作った合成HTTP/cart観測を
`Checks.Registry` の C-015/C-016 に投入する50アサーション。
実appの新規取得や保存Runの再採点ではない。既存Music suiteと合わせ270アサーションが成功。
1.6以外の歴史的判定、ledger/spec/prompt/oracle、既存Runの評価結果を変更しない。
評価器の適用には別の新規build/hash固定が必要であり、既存runtime lockやDLLを置き換えていない。

## Education E-005 / E-006 / E-012

公開[要求](../research/tasks/contoso-enrollment/public-request.txt)と
[ledger](../inner/spec/requirements-cu-C-education-1.1.0.json)のmarkerを、
指定HTML idまたは指定名の独自属性から観測する。1つの対象要素の表示値が対応し、
値付き属性との矛盾がない有限範囲を扱う。ページ全体の文字列検索や属性値だけではpassにしない。
別対象を指す親属性、非表示・script内だけの必要値、名前・日付・FullName・gradeの誤値はfail。
gradeは元の `enrollment-ID` 行に属することを確認する。学生一覧行ID、course一覧ID、
履修行・course title/link、404、入力フォーム、DB判定は別に維持する。

属性だけのstudent-id、重複marker、複合領域の対応が曖昧な値はblocked。
HTTP経路の新しい属性対応は、CSS/script/inline styleが表示に影響し得る場合もblockedとする。
単なるTextContentをcomputed visibilityの証拠にしない。このHTTP経路には完全な描画検証がなく、
複雑な許容表現の網羅は未完である。旧id経路の観測範囲は保持する。

E-012は実ブラウザーがcomputed styleと描画領域を調べ、markerごとの状態をhash付きcaptureへ残す。
通常Create/Edit/Save・アプリ自身のdetails遷移・独立read-only DB・元row保持を維持し、
DB一致だけでUIの欠落を救済しない。未解決markerがあっても確認済みDB不一致やHTTP不具合はfail。
歴史的capture形式は従来経路で読めるが、新しい観測を後付けしたとは扱わない。

E-008/E-010の不正9入力・HTTP200の通常form・全domain table snapshot非変更のpredicateは変更しない。
markerの保留はこれらのcritical失敗を取り消さない。blockedがある場合は分母12を保持しqualityはnull。
条件別の識別上下限の新しい集計、全保存物の再採点、人間確認はこのPRの範囲外。

DiagnosticsChecksは実predicate、Check蓄積、hash付きCompose/Emitへ人工証拠を投入する。
既存のDB/観測障害回帰と合わせ96アサーションが成功した。
別途ローカル人工アプリの通常UIを実Chromiumで操作し、独自属性、CSS非表示、属性だけの値、
別対象、ID保留を確認する。fixtureのHTTP要求は新規モデル取得ではない。
実装revisionは `education-1.1.0-observation-2`。元spec、入力、runtime lock、保存DLLは変更しない。
