# 正例フィクスチャ（reference）

評価器の**校正用**の成果物である。評価器が「正しく移行された成果物」を落とさないことを確かめるために使う。

**この実装を「正解の定義」として扱わない。** 正解の定義は `inner/spec/requirements.json`（要件台帳）と `docs/quality-spec.md`（品質評価仕様）であり、本フィクスチャは評価器と同じ作業者が書いた入力にすぎない。§「限界」を参照。

## 何であるか

旧実装 `chack411/MVC-Music-Store`（`net48` ブランチ、コミット `2967afb9d69488641df0d154e2ad5827a7820e71`）の、`StoreManager` と `Account` を除いた範囲の ASP.NET Core MVC 実装である。.NET 8 / EF Core 8（Sqlite）/ コントローラと Razor ビューという構成をとる。

- 起動: `dotnet run --project inner/fixtures/reference/MusicStore.Web`
- 接続文字列: 環境変数 `ConnectionStrings__MusicStoreEntities`（例: `Data Source=<path>`）。未設定なら作業ディレクトリの `store.sqlite` を使う。
- 初期データ: `Data/catalog.json` を、`Genres` が空のときだけ投入する。

## 校正の記録

| 実行 | 成果物ハッシュ | 評価版 | 連番 | 判定 | 品質 |
| --- | --- | --- | --- | --- | --- |
| `runs/cal-ref-001` | `b62edb6d0c05` | 1.0.0 | 1 | `pass` | 100.00 |
| `runs/cal-ref-002` | `b62edb6d0c05` | 1.0.0 | 2 | `pass` | 100.00 |

同じ成果物に対して 2 回実行し、判定と品質が一致することを確認した（`runs/` は追跡しない）。詳細は `inner/calibration/README.md`。

## 校正で見つかった誤り

最初の実行は `pass 28 / fail 1`（品質 96.55）で `R-016`（異なるアルバムの追加で明細が増える）が不合格だった。原因は評価器ではなく本フィクスチャ側で、`Carts` の主キーが EF Core の `<型名>Id` 規約により `CartId` に選ばれ、1 かご 1 行しか持てなくなっていた（`SQLite Error 19: UNIQUE constraint failed: Carts.CartId`）。`RecordId` を主キーに明示して修正した。**この誤りは、評価器が実際に成果物を動かして観測したことで初めて検出できた。**

## 限界

1. 正例を評価器と同じ作業者が書いている。正例が通ったことは評価器の妥当性の根拠にならない。妥当性の根拠は、要件と期待値を旧実装のコードと HTTP 契約から独立に導出して根拠を要件ごとに記録したこと、構造の異なる「妥当な別実装」で不当に落ちないこと、重要な負例を実際に落とすことの 3 点である（`docs/quality-spec.md` §7）。
2. 本フィクスチャは旧実装の HTML マークアップを再現していない。評価対象は HTTP 契約（URL・ステータスコード・表示される値と識別子）であり、マークアップ一致は §2.1 の評価対象外である。
3. 旧実装の実行時比較は行っていない。`legacy` を根拠とする期待値はコード読解に基づく。
