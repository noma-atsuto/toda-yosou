"""設定値（ここを変えれば他の競艇場にも使えます）"""
import datetime as dt
import os

STADIUM = 2                  # 戸田 = 02（例：平和島 = 04、多摩川 = 05）
STADIUM_NAME = "戸田"
BASE_URL = "https://boatraceopenapi.github.io"
JST = dt.timezone(dt.timedelta(hours=9))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORE_DIR = os.path.join(ROOT, "store")            # 取得した戸田のデータ（日ごと）
PRED_DIR = os.path.join(ROOT, "predictions")       # その日の予想（締切時点で確定）
MODEL_DIR = os.path.join(ROOT, "model")            # 学習済みモデル
SITE_DATA = os.path.join(ROOT, "docs", "data")     # アプリが読むデータ

BACKFILL_DAYS = 365          # 最初にさかのぼって集める日数
TRAIN_DAYS = 540             # 学習に使う最大日数
VALID_DAYS = 45              # 学習の良し悪しを確かめる直近の日数
MIN_TRAIN_RACES = 150        # これ未満なら学習せず初期値で予想

# 1日の買い目（成績の計算に使う「毎レース100円ずつ機械的に買った場合」）
BETS = {
    "win1":  {"label": "単勝 本命1点",   "kind": "win",      "n": 1},
    "exa3":  {"label": "2連単 上位3点",  "kind": "exacta",   "n": 3},
    "tri5":  {"label": "3連単 上位5点",  "kind": "trifecta", "n": 5},
    "tri10": {"label": "3連単 上位10点", "kind": "trifecta", "n": 10},
    "trio3": {"label": "3連複 上位3点",  "kind": "trio",     "n": 3},
}
