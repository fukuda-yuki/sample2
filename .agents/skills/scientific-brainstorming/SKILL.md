---
name: scientific-brainstorming
description: "分析・考察専用。取得済み結果を踏まえ、次段階の研究方向を複数案で比較・優先付けする。 Post-acquisition analysis only; never sampling, acquisition, Run monitoring/recovery, collection, sharing, or routine harness work."
---

# scientific-brainstorming — sample2分析専用

## 起動条件と優先する制約

取得済み結果の分析・考察、そこからの次段階の研究判断に限って使う。
サンプリング、Run実行・監視・停止・復旧・回収・共有、単純な抽出/集計の実行、
基盤修正だけでは起動しない。元資料の広い起動条件よりこの条件を優先する。

リポジトリ直下のAGENTS.mdと[分析・考察の手順](../research-analysis/SKILL.md)に
従い、[UPSTREAM.md](UPSTREAM.md)の該当する方法と必要な参考資料を読む。
この配置は元Skillを分析専用に適応したもの。元資料のscripts、外部API、生成図、
未導入Skillは今回の実行環境に含まれない。元資料の例から自動導入・自動実行しない。
新しい取得・再採点・凍結条件変更は、このSkillの使用から許可されない。

## この用途での使い方

既存推奨案への露出を記録し、初案、反対証拠、少数案、外部証拠の確認後の再発散、選択理由を保持する。委任された判断はCodexが行い、最終human判断という元資料の記述を工程ごとの承認要求に変えない。

既存データと取得条件を優先し、原本・測定手段・分析・解釈を区別する。
参考資料の出典・事例は独立確認なしに研究の根拠としない。
委任された範囲は自律的に進める。人間/他担当の独立生成が実際にないときは、
存在したように報告しない。既読の結果・推奨案を見ていないとも称さない。
必要な未提供情報だけを質問し、元資料の対話例や所要時間を毎回強制しない。

報告にこのSkill名、読んだ資料、適用した方法、証拠範囲と省略理由を残す。
導入元は`docs/research-skills/manifest.json`の固定commit、帰属はLICENSE.txtを参照する。
