"""毎回の自動処理（GitHub Actions から呼ばれる）

  python -m engine.pipeline run      ふだんの実行（取得→必要なら学習→予想→照合→アプリ用データ作成）
  python -m engine.pipeline setup    初回セットアップ（過去1年分を集めて学習）
  python -m engine.pipeline learn    今すぐ学習し直す
"""
import argparse
import datetime as dt
import json
import os
import time

from . import data
from .config import (BACKFILL_DAYS, BETS, MIN_TRAIN_RACES, PRED_DIR, SITE_DATA,
                     STADIUM, STADIUM_NAME, TRAIN_DAYS, VALID_DAYS, MODEL_DIR)
from .model import (Model, evaluate, finish_order, probabilities, race_features, top,
                    combo_str, hit_of, payout, train)

WEATHER = {1: "晴", 2: "曇", 3: "雨", 4: "雪", 5: "台風", 6: "霧"}
CLASS = {1: "A1", 2: "A2", 3: "B1", 4: "B2"}

# 学習のときに試す設定の候補（毎日いちばん成績のよいものを選ぶ）
CANDIDATES = [
    {"l2": 0.01, "half_life": None},
    {"l2": 0.03, "half_life": None},
    {"l2": 0.01, "half_life": 180},
    {"l2": 0.003, "half_life": 90},
]


def log(*a):
    print(*a, flush=True)


def _write_json(path, obj, pretty=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        if pretty:
            json.dump(obj, f, ensure_ascii=False, indent=1)
        else:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


def _read_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# 学習
# ---------------------------------------------------------------------------
def build_samples(today):
    out = []
    for d, rec in data.iter_days(today, TRAIN_DAYS):
        for rn, race in sorted(data.races_of(rec).items()):
            if not race["result"] or not race["preview"] or not race["preview"].get("boats"):
                continue
            feats = race_features(race)
            if len(feats) < 4:
                continue
            bns = [bn for bn, _, _ in feats]
            order = finish_order(race["result"], set(bns))
            if len(order) < 3:
                continue
            out.append({"date": d, "age": (today - d).days, "X": [x for _, x, _ in feats],
                        "idx": [bns.index(b) for b in order], "feats": feats,
                        "order": order, "result": race["result"]})
    return out


def learn(today, force=False):
    current = Model.load()
    if not force and current.info.get("trained_date") == today.isoformat():
        log("・今日はすでに学習済みです")
        return current
    samples = build_samples(today)
    log(f"・学習に使えるレース: {len(samples)}件")
    if not force and current.info.get("trained") and current.info.get("races") == len(samples):
        log("・前回の学習から新しい結果が増えていないため、学習はお休みします")
        return current
    if len(samples) < MIN_TRAIN_RACES:
        log(f"  {MIN_TRAIN_RACES}件未満のため、学習せず初期値で予想します")
        return current

    cut = today - dt.timedelta(days=VALID_DAYS)
    tr = [s for s in samples if s["date"] < cut]
    va = [s for s in samples if s["date"] >= cut]
    if len(va) < 40 or len(tr) < 100:
        k = int(len(samples) * 0.8)
        tr, va = samples[:k], samples[k:]
    log(f"・古い{len(tr)}件で学習し、直近{len(va)}件で成績を確かめます")

    init = current if current.info.get("trained") else None
    iters = 150 if init else 300
    best = None
    tried = []
    for cand in CANDIDATES:
        t0 = time.time()
        m = train(tr, l2=cand["l2"], half_life=cand["half_life"], iters=iters, init=init, log=None)
        ev = evaluate(m, va)
        tried.append({**cand, "loglik": ev["loglik"], "hit": ev["hit"]})
        log(f"  候補 {cand} → 対数尤度 {ev['loglik']}  本命1着 {ev['hit']['win1']:.1%}"
            f"  3連単5点 {ev['hit']['tri5']:.1%}  ({time.time() - t0:.0f}秒)")
        if best is None or ev["loglik"] > best[2]["loglik"]:
            best = (cand, m, ev)
    cand, m_best, ev_best = best
    base = evaluate(Model(), va)

    log(f"・いちばん良かった設定 {cand} で、全データを使って学習し直します")
    final = train(samples, l2=cand["l2"], half_life=cand["half_life"], iters=120, init=m_best,
                  log=log)
    final.info = {
        "trained": True, "trained_date": today.isoformat(),
        "trained_at": data.now_jst().strftime("%Y-%m-%d %H:%M"),
        "races": len(samples), "from": samples[0]["date"].isoformat(),
        "to": samples[-1]["date"].isoformat(), "params": cand,
        "valid": ev_best, "valid_default": base, "candidates": tried,
    }
    final.save()
    hist_path = os.path.join(MODEL_DIR, "history.json")
    hist = _read_json(hist_path, [])
    hist = [h for h in hist if h["date"] != today.isoformat()]
    hist.append({"date": today.isoformat(), "races": len(samples), "params": cand,
                 "loglik": ev_best["loglik"], "hit": ev_best["hit"], "roi": ev_best["roi"],
                 "default_hit": base["hit"]})
    _write_json(hist_path, hist[-400:], pretty=True)
    return final


# ---------------------------------------------------------------------------
# 予想
# ---------------------------------------------------------------------------
def _closed_at(prog):
    s = prog.get("race_closed_at")
    try:
        return dt.datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=data.JST)
    except (TypeError, ValueError):
        return None


def race_entry(rn, race, model):
    prog, prev = race["program"], race.get("preview") or {}
    feats = race_features(race)
    if not feats:
        return None
    pr = probabilities(model, feats)
    fav = max(pr["win"].values())
    conf = "堅い" if fav >= 0.55 else ("やや堅い" if fav >= 0.38 else "混戦")
    boats = []
    for bn, _, r in sorted(feats, key=lambda t: t[0]):
        boats.append({
            "bn": bn, "name": r["name"], "cls": CLASS.get(int(r["cls"]), "-"),
            "course": r["course"], "nat": round(r["nat_win"], 2), "loc": round(r["loc_win"], 2),
            "motor": round(r["motor"], 1), "st": round(r["avg_st"], 2),
            "exh": r["exh_time"], "exh_st": r["exh_st"],
            "p1": round(pr["win"][bn], 4), "p2": round(pr["top2"][bn], 4),
            "p3": round(pr["top3"][bn], 4),
        })
    lists = {"trifecta": 10, "trio": 5, "exacta": 5, "quinella": 3, "win": 3}
    bets = {k: [[combo_str(k, c), round(p, 4)] for c, p in top(pr[k], n)]
            for k, n in lists.items()}
    bets["place"] = [[str(c), round(p, 4)] for c, p in top(pr["top2"], 3)]
    has_prev = bool(prev.get("boats"))
    return {
        "rn": rn, "closed_at": prog.get("race_closed_at"),
        "title": prog.get("race_title"), "subtitle": prog.get("race_subtitle"),
        "has_preview": has_prev,
        "weather": WEATHER.get(prev.get("race_weather_number")) if has_prev else None,
        "wind": prev.get("race_wind") if has_prev else None,
        "wave": prev.get("race_wave") if has_prev else None,
        "confidence": conf, "fav": round(fav, 4),
        "model": model.info.get("trained_date") or "初期値",
        "boats": boats, "bets": bets,
    }


def predict(date, now, model):
    rec = data.load_store(date)
    if not rec or not rec.get("held"):
        return None
    path = os.path.join(PRED_DIR, date.strftime("%Y%m%d") + ".json")
    saved = _read_json(path, {"date": date.isoformat(), "races": {}})
    races = data.races_of(rec)
    changed = 0
    for rn, race in sorted(races.items()):
        key = str(rn)
        old = saved["races"].get(key)
        if old and old.get("frozen"):
            continue                          # 締切後は予想を固定（後から直さない＝公正な照合）
        entry = race_entry(rn, race, model)
        if not entry:
            continue
        ca = _closed_at(race["program"])
        entry["frozen"] = bool(ca and now >= ca)
        entry["updated_at"] = now.strftime("%H:%M")
        saved["races"][key] = entry
        changed += 1
    saved["updated_at"] = now.isoformat(timespec="seconds")
    _write_json(path, saved)
    log(f"・{date} の予想を更新: {changed}レース")
    return saved


# ---------------------------------------------------------------------------
# 照合（予想と結果の答え合わせ）
# ---------------------------------------------------------------------------
BET_LIST_KEY = {"win": "win", "exacta": "exacta", "trifecta": "trifecta", "trio": "trio"}


def _parse(kind, s):
    if kind == "win":
        return int(s)
    sep = "=" if kind == "trio" else "-"
    return tuple(int(x) for x in s.split(sep))


def grade_day(pred, rec):
    """1日分を照合して、レースごとの結果と1日の集計を返す。"""
    results = {r["race_number"]: r for r in (rec or {}).get("results") or []}
    day = {"date": pred["date"], "races": 0, "hits": {k: 0 for k in BETS},
           "cost": {k: 0 for k in BETS}, "ret": {k: 0 for k in BETS}}
    graded = {}
    for key, e in pred["races"].items():
        res = results.get(int(key))
        if not res:
            continue
        order = finish_order(res, {b["bn"] for b in e["boats"]})
        if len(order) < 3:
            graded[key] = {"order": order, "void": True}
            continue
        g = {"order": order, "hits": {}, "ret": {}, "payouts": {}}
        for kind in ("win", "exacta", "trifecta", "trio"):
            pays = ((res.get("payouts") or {}).get(kind) or [])
            if pays:
                g["payouts"][kind] = [pays[0].get("combination"), pays[0].get("payout")]
        day["races"] += 1
        for bkey, bet in BETS.items():
            picks = [_parse(bet["kind"], c) for c, _ in e["bets"][BET_LIST_KEY[bet["kind"]]][:bet["n"]]]
            day["cost"][bkey] += 100 * len(picks)
            hit = next((k for k in picks if hit_of(bet["kind"], k, order)), None)
            g["hits"][bkey] = hit is not None
            if hit is not None:
                day["hits"][bkey] += 1
                r = payout(res, bet["kind"], combo_str(bet["kind"], hit))
                day["ret"][bkey] += r
                g["ret"][bkey] = r
        graded[key] = g
    return graded, day


# ---------------------------------------------------------------------------
# アプリ用データ
# ---------------------------------------------------------------------------
def build_site(today, model):
    days_dir = os.path.join(SITE_DATA, "days")
    os.makedirs(days_dir, exist_ok=True)
    daily = []
    dates = []
    for fn in sorted(os.listdir(PRED_DIR)) if os.path.isdir(PRED_DIR) else []:
        if not fn.endswith(".json"):
            continue
        pred = _read_json(os.path.join(PRED_DIR, fn))
        date = dt.date.fromisoformat(pred["date"])
        rec = data.load_store(date)
        graded, day = grade_day(pred, rec)
        races = []
        for key in sorted(pred["races"], key=int):
            e = dict(pred["races"][key])
            if key in graded:
                e["result"] = graded[key]
            races.append(e)
        _write_json(os.path.join(days_dir, fn), {
            "date": pred["date"], "stadium": STADIUM_NAME, "updated_at": pred.get("updated_at"),
            "races": races})
        dates.append(pred["date"])
        if day["races"]:
            daily.append(day)

    tot = {"races": sum(d["races"] for d in daily)}
    for f in ("hits", "cost", "ret"):
        tot[f] = {k: sum(d[f][k] for d in daily) for k in BETS}
    _write_json(os.path.join(SITE_DATA, "record.json"), {
        "bets": {k: v["label"] for k, v in BETS.items()}, "daily": daily, "total": tot})

    hist = _read_json(os.path.join(MODEL_DIR, "history.json"), [])
    _write_json(os.path.join(SITE_DATA, "model.json"), {
        "info": model.info, "importance": model.importance(), "history": hist,
        "bets": {k: v["label"] for k, v in BETS.items()}})
    _write_json(os.path.join(SITE_DATA, "index.json"), {
        "stadium": STADIUM_NAME, "stadium_number": STADIUM,
        "generated_at": data.now_jst().isoformat(timespec="seconds"),
        "today": today.isoformat(), "dates": dates[-120:]})
    log(f"・アプリ用データを作成: 予想 {len(dates)}日分 / 照合済み {tot['races']}レース")


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="run", choices=["run", "setup", "learn"])
    ap.add_argument("--days", type=int, default=BACKFILL_DAYS)
    args = ap.parse_args()
    now = data.now_jst()
    today = now.date()
    log(f"■ {STADIUM_NAME} 予想アプリ 自動処理 {now:%Y-%m-%d %H:%M}（{args.cmd}）")

    if args.cmd == "setup":
        n = data.sync(today, args.days, max_new=10_000)
    else:
        n = data.sync(today, min(args.days, 14))       # ふだんは直近2週間ぶんを確認
    log(f"・データ取得: {n}日分")
    model = learn(today, force=args.cmd in ("setup", "learn"))
    predict(today, now, model)
    tomorrow = today + dt.timedelta(days=1)            # 翌日の出走表が出ていれば先に予想
    if now.hour >= 18:
        rec = data.update_day(tomorrow, today)
        if rec.get("held"):
            predict(tomorrow, now, model)
    build_site(today, model)
    log("■ 完了")


if __name__ == "__main__":
    main()
