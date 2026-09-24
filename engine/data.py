"""データ取得と保存。

Boatrace Open API（有志による非公式の無料データ）から、戸田の分だけを取り出して
store/YYYYMMDD.json に日ごとに保存する。
  https://github.com/BoatraceOpenAPI
"""
import datetime as dt
import json
import os
import ssl
import subprocess
import time
import urllib.error
import urllib.request

from .config import BASE_URL, STADIUM, STORE_DIR, JST

KINDS = ("programs", "previews", "results")


def now_jst():
    fixed = os.environ.get("TODA_NOW")          # テスト用に「今」を固定できる
    if fixed:
        return dt.datetime.fromisoformat(fixed).replace(tzinfo=JST)
    return dt.datetime.now(JST)


def _download(url):
    """JSONを取得。404ならNone。証明書エラー等はcurlで再挑戦。"""
    fixture = os.environ.get("TODA_FIXTURE_DIR")  # テスト用：ネットの代わりにフォルダから読む
    if fixture:
        path = os.path.join(fixture, url.replace(BASE_URL + "/", "").replace("/", "_"))
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    req = urllib.request.Request(url, headers={"User-Agent": "toda-yosou-app/1.0"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if attempt == 2:
                raise
        except (ssl.SSLError, urllib.error.URLError):
            out = subprocess.run(["curl", "-sSfL", "--max-time", "40", url],
                                 capture_output=True, text=True)
            if out.returncode == 0:
                return json.loads(out.stdout)
            if "404" in out.stderr:
                return None
            if attempt == 2:
                raise RuntimeError(f"ダウンロード失敗: {url} {out.stderr}")
        time.sleep(3 * (attempt + 1))
    return None


def _fetch_kind(kind, date, today):
    ymd = date.strftime("%Y%m%d")
    data = None
    if date == today:
        data = _download(f"{BASE_URL}/{kind}/v2/today.json")
        items = (data or {}).get(kind) or []
        if items and items[0].get("race_date") != date.isoformat():
            data = None                       # まだ今日の分に切り替わっていない
    if not data:
        data = _download(f"{BASE_URL}/{kind}/v2/{date.year}/{ymd}.json")
    items = (data or {}).get(kind) or []
    return [x for x in items if x.get("race_stadium_number") == STADIUM]


def store_path(date):
    return os.path.join(STORE_DIR, date.strftime("%Y%m%d") + ".json")


def load_store(date):
    p = store_path(date)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def update_day(date, today):
    """その日の戸田のデータを取得して保存。開催がなければ空の記録を残す。"""
    rec = {"date": date.isoformat()}
    for kind in KINDS:
        rec[kind] = sorted(_fetch_kind(kind, date, today), key=lambda r: r["race_number"])
    rec["held"] = bool(rec["programs"])
    rec["complete"] = rec["held"] and len(rec["results"]) >= len(rec["programs"])
    rec["fetched_at"] = now_jst().isoformat(timespec="seconds")
    os.makedirs(STORE_DIR, exist_ok=True)
    with open(store_path(date), "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, separators=(",", ":"))
    return rec


def sync(today, backfill_days, max_new=400):
    """今日・昨日は毎回取り直し、過去分は足りない日だけ取得する。"""
    fetched = 0
    for back in range(backfill_days, -1, -1):
        d = today - dt.timedelta(days=back)
        rec = load_store(d)
        need = rec is None or back <= 1
        if rec and not rec.get("complete") and rec.get("held") and back <= 7:
            need = True                           # 結果の出そろっていない直近の日
        if not need:
            continue
        if fetched >= max_new and back > 1:
            continue
        update_day(d, today)
        fetched += 1
        if back > 1 and not os.environ.get("TODA_FIXTURE_DIR"):
            time.sleep(0.3)                       # 配信元に負担をかけないよう間隔をあける
    return fetched


def iter_days(until, days):
    """until の前日まで、さかのぼって保存済みの日を古い順に返す。"""
    for back in range(days, 0, -1):
        d = until - dt.timedelta(days=back)
        rec = load_store(d)
        if rec and rec.get("held"):
            yield d, rec


def races_of(rec):
    """保存データを {レース番号: {program, preview, result}} にまとめる。"""
    prevs = {p["race_number"]: p for p in rec.get("previews") or []}
    ress = {r["race_number"]: r for r in rec.get("results") or []}
    return {p["race_number"]: {"program": p, "preview": prevs.get(p["race_number"]),
                                "result": ress.get(p["race_number"])}
            for p in rec.get("programs") or []}
