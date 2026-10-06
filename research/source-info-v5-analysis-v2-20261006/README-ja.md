# 研究継続性・責任者判断の追補 v2

[REPORT-ADDENDUM-v2-ja.md](REPORT-ADDENDUM-v2-ja.md) が今回の結論・研究史・次の判断です。前回100組と今回100ペアを混ぜず、今回200 Runの保存結果から6つの問いを順に検討しました。品質維持とRun全体token削減は確定できません。新しいモデル実験・再採点は0です。

既存v1のreport/analysis.zip/全100pair collectionは同じ専用Releaseに残っています。本ZIPは追補の派生再計算用です。既存の大容量collectionを再取得する必要はありません。STOP原証拠監査や旧raw監査、独立品質意味監査、非公開評価器replayを再計算と同一視しません。

## Offline再計算

Windows・CPython 3.14.4で検証。標準ライブラリのみ、キー不要。6本のCLIとreaderはモデル・provider・評価器・Docker・ネットワークを呼びません。

1. `analysis-v2-iterative-20261006.zip` を新しいフォルダへ展開します。
2. 専用Release本文のMANIFEST SHA256を確認します。ZIP内部の値だけを無条件に信頼しません。
3. package rootから、新しい外部出力先へ実行します。

```powershell
python -B -X utf8 .\code\reproduce_iterative_v2.py --package . --out ..\v2-recalculated-new --manifest-sha256 '<専用Release本文のSHA256>'
```

全manifestファイルのsize/SHAを検証し、6結果のbyte一致を確認します。再現時刻を含むreceiptは一致対象ではありません。出力先が存在したり入力が変われば停止します。終了0と `actual-recalculation-receipt.json` を確認してください。

| 場所 | 内容 |
| --- | --- |
| `data/` | 原公開200 Run/4500check、別保存STOP起点whitelist |
| `prior/` | 旧公開CSV/結果/計画/report/manifest/設計レビューの最小7ファイル。旧raw未再監査 |
| `code/` | 6段階の実行sourceとcommon、再現reader |
| `results/01..06/` | 公開版結果。02のみ公開prior inventoryへ限定した別保存結果 |
| `history/01..06/` | 当時のplan/source/result/receipt。原02も保持 |
| `history/stage-history.json` | 実時刻から後に組み立てた6段階・6CLI・5移行の履歴。grid/チェック/再計算は回数に含まない |
| `history/*clarification*.json` | 原source/resultを変更しない表現・時系列の補足 |
| `provenance/` | 原R2と公開R2のcontent一致、レビューcopyのpath正規化対応 |
| `reviews/` | 有限AIレビューと独立数値チェック結果。human_reviewはnot_run |

R2は入力hash inventoryだけを最小既公開ファイルへ変更しました。数値と分析contentは原R2と同一です。readerは公開02のbyte一致と原02のcontent一致を別々に確認します。原02の公開日と本文成立時刻に関する表現には別clarificationがあります。

APIキー、認証原材、所有者台帳、生ログ、DB、private oracle/評価バイナリ、権利未確認画像を含めません。レビューcopyのoperator絶対pathは汎用markerへ置換し、元SHAと公開SHAを対応づけています。実行した6分析sourceは変更していません。

原取得bundle SHA256: `f39b38adc6bb46d6a12a6aefc4838155e0378c5d0dd7f5727aa68fbd4fc85334`。原dataset SHA256: `8a74ffc4bf90b38297a7668eabe91befa572215c9facdf20c814e617efa125f3`。

専用公開入口: https://github.com/fukuda-yuki/sample2/releases/tag/source-info-v5-100p2-f39b38adc6bb-final 。Release tagは原v1のcommitを保持し、v2追加commitは本文の固定linkで示します。
