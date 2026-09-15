# sample2

既存システムのモダナイズを題材に、**Context Engineering**（特にモデルが実際に受け取る Input コンテキスト）の効果を、品質と Run 全体の input/output token の両面から追う研究のための作業リポジトリ。

`sample1` は旧実験の保存・参照元として残し、旧実験の前提（条件名 `normal` / `anti`、AP-001、旧要件ID、固定分母 57、旧実行許可など）は本リポジトリへ持ち込まない。

## 作業の正本

- 計画と判断: [docs/plan.md](docs/plan.md)、[docs/decision-log.md](docs/decision-log.md)
- 個別 Issue: [fukuda-yuki/sample2 Issues](https://github.com/fukuda-yuki/sample2/issues)

| Issue | 内容 | 成果物 |
| --- | --- | --- |
| [#1](https://github.com/fukuda-yuki/sample2/issues/1) | 全体計画 | [docs/plan.md](docs/plan.md) |
| [#2](https://github.com/fukuda-yuki/sample2/issues/2) | sample1 再利用資産の棚卸し | [docs/sample1-inventory.md](docs/sample1-inventory.md) |
| [#3](https://github.com/fukuda-yuki/sample2/issues/3) | 題材・移行課題の選定 | [docs/topic-selection.md](docs/topic-selection.md) |
| [#4](https://github.com/fukuda-yuki/sample2/issues/4) | 内側: 品質評価仕様と評価器 | [docs/quality-spec.md](docs/quality-spec.md), [docs/evaluator.md](docs/evaluator.md), [inner/](inner/) |
| [#5](https://github.com/fukuda-yuki/sample2/issues/5) | 外側: 実験実行基盤 | [docs/outer-harness.md](docs/outer-harness.md), [outer/](outer/) |

## リポジトリ構成

| パス | 区分 | 責務 |
| --- | --- | --- |
| `docs/` | 研究管理 | 計画・調査・選定・仕様・判断履歴 |
| `inner/` | 内側 | 品質評価仕様、評価器の実装、校正用 fixture、評価結果 |
| `outer/` | 外側 | 開始状態の用意、実行・停止・回収、固定、採点呼び出し、記録・再集計 |
| `runs/` | 実装作業領域 | 実装エージェントの作業場所と固定成果物。**追跡しない**（`.gitignore`） |

`docs/`・`inner/`・`outer/` は研究管理側であり、実装役へは当該条件で許された範囲だけを渡す。非公開評価資材・秘密情報・旧 Run 実体は公開 Git へ入れない。

## 文書と事実の区別

本リポジトリでは、**「文書がある」「コードがある」「非モデルで検証済み」「実モデル・実環境で検証済み」を区別して記録する**。スクリプトやテストの存在を、実験の成立根拠として扱わない。未確認・未実行・欠測は隠さない。
