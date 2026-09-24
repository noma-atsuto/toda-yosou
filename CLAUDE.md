# 戸田ボートレース予想アプリ — Claude Code 向けメモ

## このプロジェクトは何か
- 戸田（競艇場番号 02）の予想を毎日自動で作り、結果と照合しながら学習し直す iPhone 向け Web アプリ。
- 持ち主はプログラミングに詳しくない。説明は日本語で、専門用語にはかっこ書きで簡単な説明をつける。
- 変更したら「何が変わったか」「どう確かめたか」を短く報告する。

## しくみ
```
GitHub Actions（.github/workflows/auto.yml）が定期実行
  └ python -m engine.pipeline run
       1. engine/data.py     … Boatrace Open API から戸田の分だけ取得 → store/YYYYMMDD.json
       2. engine/pipeline.py learn() … 新しい結果があれば学習し直す（4通りの設定を試し、直近45日で最良のもの）
       3. predict()          … 今日の予想 → predictions/YYYYMMDD.json（締切後は frozen=true で固定）
       4. build_site()       … 予想と結果を照合 → docs/data/*.json（アプリが読む）
  └ 変更をコミット → GitHub Pages が docs/ を公開
docs/ … 画面（index.html / app.js / style.css / sw.js）。ビルド不要の素のHTML/JS。
```
- モデル: engine/model.py。各艇のスコア = 特徴量 × 重み。プラケット・ルース模型で全着順の確率を出す。
  学習は 1〜3着の尤度を最大化（L2正則化・日数による重み減衰あり）。標準ライブラリのみ（numpy 不使用）。
- 設定値: engine/config.py（競艇場・学習日数・検証日数・成績に使う買い目）。

## 守ること
- **締切後の予想を書き換えない**（frozen の予想だけで成績を計算する＝公正な答え合わせ）。
- **結果（results）の情報を予想の特徴量に入れない**（未来の情報が混ざる「リーク」を防ぐ）。
- 特徴量を追加・変更したら model.py の FEATURES と DEFAULT_WEIGHTS を両方直す。
  FEATURES が変わると保存済みモデルは読み込まれず初期値に戻るので、Actions で `learn` を手動実行する。
- 配信元に負担をかけない（過去データの取得には間隔をあける。取得回数を増やしすぎない）。
- 的中や利益を保証する表現を画面や文章に書かない。

## 動作確認のしかた
- `bash tests/run_sim.sh` … 模擬データ（tests/make_fixture.py）で 取得→学習→予想→照合 を一通り実行し、検査する（約1分）。
  ネットには接続しない（環境変数 TODA_FIXTURE_DIR で読み込み先を差し替え、TODA_NOW で「今」を固定）。
- 画面を変えたら、run_sim.sh の最後に出るフォルダで `python3 -m http.server` を起動し、幅390pxで表示を確認する。
- 本物のデータでの実行: `python -m engine.pipeline run`（store/ などが更新されるので注意）。

## データの注意
- Boatrace Open API は有志による非公式データ（MIT ライセンス）。更新は数分おきで、項目の意味は要確認のものがある
  （racer_class_number の 1〜4 = A1〜B2、race_weather_number、race_wind_direction_number の対応は推測）。
- API の仕様が変わったら engine/data.py と engine/model.py の race_features() を直す。
