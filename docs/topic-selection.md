# 題材・移行課題の選定（第 1 課題）

対応 Issue: [#3](https://github.com/fukuda-yuki/sample2/issues/3)
状態: **採用確定（.NET 候補）／移行課題 `MS1-001` の範囲も確定**（[decision-log.md](decision-log.md) D-10）。§2 の移行範囲は、[quality-spec.md](quality-spec.md) の校正 13 ケースが期待と完全一致したことをもって確定した（[inner/calibration/README.md](../inner/calibration/README.md) §2）。ただし校正は部分検証である（同 §5）。**確定の根拠に使った 13 ケースは当時の件数であり、その後の改訂で 20 ケースになっている**（同 §2。確定そのものは巻き戻していない）。
関連: [docs/plan.md](plan.md) の D-4・D-6、[docs/decision-log.md](decision-log.md)、[docs/sample1-inventory.md](sample1-inventory.md)、[docs/quality-spec.md](quality-spec.md)

## 0. この文書の事実区分

| 区分 | 内容 |
| --- | --- |
| 確認した事実 | 各リポジトリを clone または GitHub API で参照し、ファイル一覧・主要ファイルの内容・ライセンス表示を確認した |
| 推測 | 実行可能性・評価準備の負担・研究適合性の見積り |
| 未確認 | **旧実装のビルド・起動・データ投入は、どの候補でも実施していない**。実行環境の構築成功を主張しない |

## 1. 3 候補の比較

参照した版: .NET 候補は clone した `net48` ブランチの HEAD `2967afb9d69488641df0d154e2ad5827a7820e71`（2025-12-11）。Java・COBOL 候補は GitHub API で `main` ブランチのルート・ツリーを参照（確認日 2026-09-15）。

| 観点 | Lv.1 .NET | Lv.2 Java | Lv.3 COBOL |
| --- | --- | --- | --- |
| リポジトリ | `chack411/MVC-Music-Store` `net48` | `yoshioterada/legacy-modernization-ws-java-260310` | `shinyay/legacy-modernization-ws-cobol-260630` |
| 確認した構成 | ASP.NET MVC 5.3 / .NET Framework 4.8 / EF 6.5.1 + SQL Server Compact 4.0 / Razor ビュー 21 件 / コントローラ 6 件 / モデル 10 件 | Struts 1.x / Hibernate 3.6 / MySQL 5.7 / Ant `build.xml` / JDK 1.5 / Tomcat 6.x–8.x | GnuCOBOL / Makefile / PostgreSQL マイグレーション 7 件 / `shared/copy` のコピーブック群 / `console` `subsystems` |
| ライセンス（確認した表示） | **`LICENSE` ファイルなし。** `readme.txt` に「コードは Ms-PL、チュートリアル文書は CC BY 3.0」と記載 | `LICENSE` あり（GitHub API は MIT と判定） | `LICENSE` あり（GitHub API は MIT と判定） |
| 既存テスト | **なし**（`test` を含むディレクトリ・テストプロジェクトを確認できず） | 確認したツリーにテストディレクトリなし | `tests/`（`console/tests/console-test.sh` 等）あり |
| 実行の前提 | Windows + IIS/IIS Express + SQL Server Compact。本環境に MSBuild と .NET Framework 4.8 参照アセンブリはあるが NuGet CLI がなく、ASP.NET MVC 5 の headless 起動は未確認 | JDK 1.5（Archive.org から取得する手順）+ MySQL 5.7 + Tomcat 6–8。dev container あり | GnuCOBOL + PostgreSQL + dev container あり |
| 移行の距離 | 中〜大（フレームワーク・ランタイム・ORM・DB の 4 つが同時に変わる） | 大（JDK 1.5 → 現行 LTS、Struts 1 → 現行、Hibernate 3.6 → 現行、Tomcat 世代、MySQL 5.7） | 大（COBOL → 任意の言語。業務規則の明文化が先に必要） |
| 研究との適合（推測） | 高。コントローラ・モデル・ビュー・`web.config`・`Global.asax.cs`・サンプルデータ定義・セッション/認証の複数情報源を横断しないと挙動を再現できない | 高。DAO・Action・設定 SQL を横断する | 高。コピーブック・JCL 相当・DB マイグレーションを横断する |
| 実行可能性（推測） | **中**。移行先（.NET 8/10）は本環境に SDK がある。旧実装の起動は未確認 | 低〜中。旧 JDK と MySQL 5.7 の用意が必要 | 低〜中。GnuCOBOL と PostgreSQL の用意が必要 |
| 観測可能性 | 高。HTTP の URL 契約が明確で、かご・注文の副作用も HTTP 経由で観測できる | 高。ただし Struts の画面遷移とセッション依存の確認が必要 | 中。バッチ/コンソール出力と DB 状態が主な観測点 |
| 正解の根拠 | 中。既存テストが 0 件。コード読解 + チュートリアル文書（CC BY 3.0）+ 独立に確認する要求で作る必要がある | 中。`config/mysql/02-seed-data.sql` と画面仕様が根拠候補 | 中〜高。`db/migration` と `tests/` が根拠候補 |
| 評価準備の負担（推測） | 中。HTTP の黒箱評価で足りる範囲に切れる | 中〜大。環境構築の比重が大きい | 大。業務規則の正解基準を新規に作る必要がある |

## 2. 第 1 課題の推奨案（確定）

ユーザー指示（D-4）に従い **Lv.1 .NET 候補** を第 1 課題の対象とする。

### 課題 `MS1-001`: MVC Music Store ストアフロントの ASP.NET Core 移行

| 項目 | 内容 |
| --- | --- |
| 元リポジトリ | `chack411/MVC-Music-Store`、ブランチ `net48`、コミット `2967afb9d69488641df0d154e2ad5827a7820e71` |
| 対象範囲（部分移行） | `HomeController`（トップ）、`StoreController`（ジャンル一覧・ジャンル別アルバム一覧・アルバム詳細・ジャンルメニュー）、`ShoppingCartController`（かご表示・追加・削除・件数サマリ）、`CheckoutController`（住所入力・注文確定・注文完了）と、それらが依存するモデル（`Album` `Genre` `Artist` `Cart` `Order` `OrderDetail`）とサンプルデータ |
| 対象外 | `StoreManagerController`（管理 CRUD・画像アップロード）、`AccountController`（登録・パスワード変更）、決済連携、CSS/JS の見た目、画像アセット、`Home` の「売れ筋」順位の一致 |
| 移行先 | .NET 8 (LTS) / ASP.NET Core MVC、EF Core + SQLite |
| 残してよい旧実装 | なし。旧アプリの呼び出し・プロキシ・ラッパー化は**認めない**（移行契約として明記） |
| 維持すべき外部挙動 | URL 契約、かごの数量と合計の意味、注文と注文明細の生成、注文確定後のかご空化、注文の帰属判定、初期カタログの内容 |
| 許容する変更 | 内部構造、ORM、DB 製品（SQL CE → SQLite）、HTML マークアップ、非同期化、DI |
| 認証 | **対象外**。旧実装の `[Authorize]` と ASP.NET Membership は移行しない。注文の帰属はセッションのカート識別子で判定する（詳細は [quality-spec.md](quality-spec.md)） |
| 評価対象 | 機能（ストア閲覧・かご・注文）と移行の実施（旧実装の呼び出しがないこと） |
| 評価対象外 | 性能、可用性、セキュリティ全般、保守性、画面の見た目、`Home` の売れ筋順位 |

### 評価の境界

- 観測は **HTTP のみ**（黒箱）。DB スキーマや内部 API を採点基準にしない。
- 起動と接続の契約: 成果物は `dotnet` で起動でき、SQLite の接続文字列を構成キー `ConnectionStrings:MusicStoreEntities` から読む。初期カタログは初回起動時に投入する。
- 存在しないジャンル・存在しないアルバムは **404 を返す**。旧実装は例外により 500 を返していたが、これは**旧実装の不具合とみなし、保持しない**（課題側の明示的な判断）。
- 初期カタログ投入は旧実装の `SampleData` に合わせる。ただし旧実装の `DropCreateDatabaseIfModelChanges`（モデル変更時に DB を破棄する）は**保持しない**。

## 3. 選定理由

1. **ユーザー指示（D-4）** が最優先。3 候補を同時に立ち上げない。
2. 移行先の SDK が本環境に既にあり（`dotnet` 8.0.425 / 10.0.300-preview）、**旧実装の起動可否に依存せずに評価器を作れる**（旧実装は挙動の参照元であり、評価の実行時依存ではない）。
3. 情報探索の意味が残る。URL 契約は `Global.asax.cs`、データ契約は `Models/*.cs`、初期状態は `SampleData.cs`、かごの識別は `ShoppingCart.cs` のセッション依存、表示項目は `Views/*.cshtml` に分散しており、**単一ファイルの読解では再現できない**。
4. 観測が HTTP に閉じるため、**画面の見た目を採点せずに**機能を判定できる。評価準備の負担が小さい。
5. 部分移行として切れる。管理画面と認証を外しても、かご・注文という業務の芯が残る。

## 4. 主なリスクと、その扱い

| リスク | 影響 | 扱い |
| --- | --- | --- |
| **既存テストが 0 件** | 「既存テストが保証する範囲」を根拠にできない | 正解の根拠を「コード読解 + 独立に確認する要求 + 旧実装の観測」で構成し、根拠の種別を要件ごとに記録する（[quality-spec.md](quality-spec.md)） |
| **旧実装のビルド・起動が未確認** | 旧新比較の「旧」側を実行で確認できていない | 第 1 課題の評価を **HTTP 契約に対する独立検査**で成立させ、旧実装の実行確認は後続の作業にする。未確認であることを記録に残す |
| **`LICENSE` ファイルがない** | 再配布条件が `readme.txt` の記載に依存する | 教材本体を `sample2` に取り込まない。参照コミットを記録し、必要な範囲だけを取得する手順にする。採用時点でライセンス表示の扱いを確認する |
| リポジトリに 10 MB の MDF と 5 MB の PDF がある | 複製するとリポジトリが重くなる | clone を成果物に含めない。参照コミットと取得手順のみを記録する |
| `SampleData` が `DropCreateDatabaseIfModelChanges` | 既存 DB を破棄する破壊的挙動 | 保持しないことを契約に明記し、**負例**として検査する |
| 初期カタログが 246 アルバム・全件 8.99 | 価格だけでは数量計算の誤りを検出できない | 数量を掛けた合計（複数明細・複数数量）を要件にする |
| トップページの「売れ筋」順位が非決定的 | 安定しない検査になる | 評価対象外にし、`GET /` はレイアウト合成（ジャンルメニュー・かご件数）だけを検査する |

## 5. 課題が評価不成立になった場合の見直し余地

- **縮小**: `Checkout` を外し、`Store` 閲覧とかご操作だけに縮める。研究に必要な情報探索（URL 契約・データ契約・初期状態）は残る。
- **拡大**: `StoreManagerController` を加える。ただし管理 CRUD と画像アップロードが入り、評価準備の負担が増える。
- **戻す条件**: 期待結果を確認できない、初期状態・観測が安定しない、重要な誤りを検出できない、または簡略化で研究に必要な依存関係が消える場合は、本 Issue に課題見直しを返す（[quality-spec.md](quality-spec.md) の見直し条件）。

## 6. 完了条件に対する状態

- [x] 3 候補の比較を、確認した事実・推測・未確認に分けた（§1、§0）
- [x] 最初の 1 課題の推奨案、選定理由、評価可能な品質の範囲、主なリスクを示した（§2〜§4）
- [x] 必要情報の探索・依存関係を残せているかと、評価準備の負担の両方を説明した（§3 の 3、§4）
- [x] ユーザー判断が記録されている（[decision-log.md](decision-log.md) の D-4・D-6。`.NET` 候補の採用は確定）
- [x] `MS1-001` の移行範囲（§2）を確定した。[quality-spec.md](quality-spec.md) の校正（正例・負例・別実装・評価側障害）13 ケースが期待と完全一致したため（[inner/calibration/README.md](../inner/calibration/README.md) §2、判断は [decision-log.md](decision-log.md) D-10）。ただし校正は部分検証であり（同 §5）、この確定は「評価器がこの範囲で使える」ことの確認であって「範囲が研究に十分」ことの証明ではない。**確定に使った件数は当時の 13 ケースであり、その後 20 ケースに増えている**（同 §2）。

## 7. 参照

- 教材: `chack411/MVC-Music-Store` `net48` @ `2967afb9d69488641df0d154e2ad5827a7820e71`（コードは `readme.txt` の記載により Ms-PL、チュートリアル文書は CC BY 3.0）
- Java 候補: `yoshioterada/legacy-modernization-ws-java-260310`（`LICENSE` あり）
- COBOL 候補: `shinyay/legacy-modernization-ws-cobol-260630`（`LICENSE` あり）
