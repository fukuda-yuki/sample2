# 校正用 fixture（`inner/fixtures`）

評価器の校正に使う成果物。**モデルは呼び出さない。** 校正の実行と記録は [`inner/calibration/`](../calibration/) にある。

| ディレクトリ | 種別 | 何を確認するか |
| --- | --- | --- |
| [`reference/`](reference/) | 正例 | 要件を満たす成果物を落とさない |
| [`alternative/`](alternative/) | 妥当な別実装 | 構造・表現の違いで不当に落とさない |
| [`negatives/`](negatives/) | 重要な負例（生成スクリプト） | 内容の取り違え・欠落・二重処理を実際に不合格にする |

**成果物ディレクトリの中に本ファイルのような研究用の文書を置かない。** 成果物ハッシュは成果物ディレクトリ配下の
全ファイルを対象にするため、研究メモを中に置くとハッシュが研究メモの編集で変わってしまう。
`reference/` `alternative/` の直下は成果物そのものだけにする。

**成果物のソースは `.gitattributes` により LF に固定する。** 成果物ハッシュはバイト列を見るため、
作業ツリーが CRLF のままだと記録したハッシュが新規 clone で再現しない。
負例を作る [`negatives/apply.ps1`](negatives/apply.ps1) の差分アンカーも LF で組んである。

**この 3 つを「正解の定義」として扱わない。** 正解の定義は
[`inner/spec/requirements.json`](../spec/requirements.json)（要件台帳）と
[`docs/quality-spec.md`](../../docs/quality-spec.md)（品質評価仕様）である。
校正の限界は [`inner/calibration/README.md`](../calibration/README.md) §5 に記録している。

## 1. 正例（`reference`）

旧実装 `chack411/MVC-Music-Store`（`net48` ブランチ、コミット `2967afb9d69488641df0d154e2ad5827a7820e71`）の、
`StoreManager` と `Account` を除いた範囲の ASP.NET Core MVC 実装である。
.NET 8 / EF Core 8（Sqlite）/ コントローラと Razor ビューという構成をとる。

- 起動: `dotnet run --project inner/fixtures/reference/MusicStore.Web`
- 接続文字列: 環境変数 `ConnectionStrings__MusicStoreEntities`（例: `Data Source=<path>`）。未設定なら作業ディレクトリの `store.sqlite` を使う。
- 初期データ: `Data/catalog.json` を、`Genres` が空のときだけ投入する。

### 1.1 正例の作成で見つかった誤り

最初の校正で `pass 28 / fail 1`（品質 96.55）となり `R-016`（異なるアルバムの追加で明細が増える）が不合格だった。
原因は評価器ではなく正例側で、`Carts` の主キーが EF Core の `<型名>Id` 規約により `CartId` に選ばれ、
1 かご 1 行しか持てなくなっていた（`SQLite Error 19: UNIQUE constraint failed: Carts.CartId`）。
`RecordId` を主キーに明示して修正した。
**この誤りは、評価器が実際に成果物を動かして観測したことで初めて検出できた。**

### 1.2 正例の限界

1. 正例を評価器と同じ作業者が書いている。正例が通ったことは評価器の妥当性の根拠にならない。
   妥当性の根拠は、要件と期待値を旧実装のコードと HTTP 契約から独立に導出して根拠を要件ごとに記録したこと、
   構造の異なる別実装で不当に落ちないこと、重要な負例を実際に落とすことの 3 点である（`docs/quality-spec.md` §7）。
2. 旧実装の HTML マークアップを再現していない。評価対象は HTTP 契約（URL・ステータスコード・表示される値と識別子）であり、
   マークアップ一致は `docs/quality-spec.md` §2.1 の評価対象外である。
3. 旧実装の実行時比較は行っていない。`legacy` を根拠とする期待値はコード読解に基づく。

## 2. 妥当な別実装（`alternative`）

正例と同じ要件を、**別の実装方式**で満たす成果物。最小 API（`Microsoft.AspNetCore.Builder` の `Map*`）、
EF Core を使わない素の `Microsoft.Data.Sqlite`、Razor ビューを使わない文字列組み立ての HTML で書いてある。

正例が MVC・EF Core・Razor ビューであるのに対し、こちらはそのいずれも使わない。
これにより、評価器が「正例と同じ書き方」を要求していないこと（構造・表現の違いで不当に落とさないこと）を確認する。

- 起動: `dotnet run --project inner/fixtures/alternative/MusicStore.Minimal`
- 接続文字列: 正例と同じく `ConnectionStrings__MusicStoreEntities` を読む。
- 初期データ: `Data/catalog.json`（`inner/spec/catalog.json` と同一の内容）を、`Genres` が空のときだけ投入する。

**別実装は 1 つだけである。** 構造・表現の違いのうち、この 1 つが示す範囲でしか
「不当に落とさない」ことを確認していない（`inner/calibration/README.md` §5）。

## 3. 負例（`negatives`）

負例は成果物そのものではなく「**正例 + 差分**」として表現する。差分は
[`apply.ps1`](negatives/apply.ps1) が正例のコピーに文字列置換で与える。

- 置換対象が見つからない場合、または一意でない場合はエラーで止める。
  正例が変わって差分が当たらなくなった状態を、静かに「何も壊れていない負例」として通さないため。
- 負例ごとに改変は 1 箇所だけにする。**複数の欠陥が同時に存在する場合の判定は確認していない。**

```powershell
.\inner\fixtures\negatives\apply.ps1 -Name remove-count-pre-decrement -Out .\runs\neg-001\artifact
```

| 負例 | 壊す内容 | 期待どおり落ちる要件 |
| --- | --- | --- |
| `remove-count-pre-decrement` | 削除応答の数量を減算前に読む | `R-014` |
| `no-quantity-multiply` | かご合計で数量を掛けない | `R-013` `R-016` |
| `duplicate-cart-lines` | 同じアルバムでも明細を増やす | `R-012` `R-013` `R-014` `R-015` `R-016` |
| `no-seed` | 初期カタログを投入しない | `R-002` `R-003` `R-004` `R-005` `R-006` `R-008` `R-010` `R-011` `R-012` `R-013` `R-014` `R-016` `R-017`（+ 未評価 `R-023` `R-024`） |
| `destructive-seed` | 起動のたびに DB を作り直す | `R-005` |
| `unknown-album-500` | 存在しないアルバムを 404 にしない | `R-009` |
| `legacy-wrapper` | 旧実装を起動する記述を残す | `R-029` |

期待どおりに落ちなかった負例（見逃し）と、負例で予期せず落ちた要件（誤検出）の記録は
[`inner/calibration/README.md`](../calibration/README.md) §4 にある。
