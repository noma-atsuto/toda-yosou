"""予想モデル。

各艇の「強さ（スコア）」を、データ×重みの合計で計算し、
プラケット・ルース模型（強い艇から順に、残った艇の中で強さの割合で着順が決まる考え方）で
全ての着順の確率を出す。重みは過去の結果から学習する。
"""
import json
import math
import os

from .config import MODEL_DIR, BETS

FEATURES = [
    ("c2", "2コース"), ("c3", "3コース"), ("c4", "4コース"),
    ("c5", "5コース"), ("c6", "6コース"),
    ("nat_win", "全国勝率"), ("loc_win", "戸田勝率"), ("nat_2", "全国2連率"),
    ("cls", "級別（数字が大きいほど下位）"), ("motor", "モーター2連率"), ("boat", "ボート2連率"),
    ("avg_st", "平均スタート"), ("f_flag", "フライング持ち"), ("weight", "体重"),
    ("exh_time", "展示タイム"), ("exh_st", "展示スタート"), ("tilt", "チルト角度"),
    ("c1_wind", "1コース×風の強さ"), ("c1_wave", "1コース×波の高さ"),
    ("out_wind", "4〜6コース×風の強さ"),
]
FNAMES = [f[0] for f in FEATURES]
LABELS = dict(FEATURES)
COURSE = {"c2", "c3", "c4", "c5", "c6"}

# 学習前の初期値（一般的な傾向の目安。学習するとすぐ置き換わる）
DEFAULT_WEIGHTS = {
    "c2": -1.0, "c3": -1.2, "c4": -1.3, "c5": -1.8, "c6": -2.5,
    "nat_win": 0.5, "loc_win": 0.15, "nat_2": 0.0, "cls": -0.2,
    "motor": 0.02, "boat": 0.005, "avg_st": -8.0, "f_flag": -0.2, "weight": 0.0,
    "exh_time": -3.0, "exh_st": -3.0, "tilt": 0.1,
    "c1_wind": -0.05, "c1_wave": -0.02, "out_wind": 0.02,
}


def _num(v, default=None):
    try:
        return default if v is None else float(v)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# 特徴量
# ---------------------------------------------------------------------------
def race_features(race):
    """1レースの各艇の特徴量。返り値: [(艇番, 特徴量リスト, 表示用dict), ...]"""
    prog = race["program"]
    prev = race.get("preview") or {}
    prev_boats = prev.get("boats") or []
    if isinstance(prev_boats, dict):          # 古いAPI形式（艇番文字列→辞書）への対応
        prev_boats = list(prev_boats.values())
    pv_boats = {b["racer_boat_number"]: b for b in prev_boats}
    wind = _num(prev.get("race_wind"), 2.0)
    wave = _num(prev.get("race_wave"), 2.0)

    rows = []
    for b in prog.get("boats") or []:
        bn = b["racer_boat_number"]
        pv = pv_boats.get(bn, {})
        nat = _num(b.get("racer_national_top_1_percent"), 0.0)
        loc = _num(b.get("racer_local_top_1_percent"), 0.0) or nat   # 戸田の実績がなければ全国で代用
        exh_t = _num(pv.get("racer_exhibition_time"))
        if exh_t is not None and exh_t <= 0:
            exh_t = None
        exh_st = _num(pv.get("racer_start_timing"))
        rows.append({
            "bn": bn,
            "course": int(_num(pv.get("racer_course_number"), 0) or bn),
            "nat_win": nat, "loc_win": loc,
            "nat_2": _num(b.get("racer_national_top_2_percent"), 0.0),
            "cls": _num(b.get("racer_class_number"), 3.0),
            "motor": _num(b.get("racer_assigned_motor_top_2_percent"), 0.0),
            "boat": _num(b.get("racer_assigned_boat_top_2_percent"), 0.0),
            "avg_st": _num(b.get("racer_average_start_timing"), 0.18) or 0.18,
            "f_flag": 1.0 if (_num(b.get("racer_flying_count"), 0) or 0) > 0 else 0.0,
            "weight": _num(pv.get("racer_weight")) or _num(b.get("racer_weight")),
            "exh_time": exh_t,
            "exh_st": None if exh_st is None else max(-0.1, min(exh_st, 0.5)),
            "tilt": _num(pv.get("racer_tilt_adjustment"), 0.0),
            "name": b.get("racer_name", ""), "number": b.get("racer_number"),
        })
    if not rows:
        return []

    for key in ("nat_win", "loc_win", "nat_2", "cls", "motor", "boat",
                "avg_st", "weight", "exh_time", "exh_st"):
        vals = [r[key] for r in rows if r[key] is not None]
        m = sum(vals) / len(vals) if vals else 0.0
        for r in rows:                       # レース内の平均との差（相対的な強さ）
            r[key + "_c"] = 0.0 if r[key] is None else r[key] - m

    out = []
    for r in rows:
        c = r["course"]
        x = [1.0 if c == 2 else 0.0, 1.0 if c == 3 else 0.0, 1.0 if c == 4 else 0.0,
             1.0 if c == 5 else 0.0, 1.0 if c >= 6 else 0.0,
             r["nat_win_c"], r["loc_win_c"], r["nat_2_c"], r["cls_c"],
             r["motor_c"], r["boat_c"], r["avg_st_c"], r["f_flag"], r["weight_c"],
             r["exh_time_c"], r["exh_st_c"], r["tilt"],
             (wind - 2) if c == 1 else 0.0, (wave - 2) if c == 1 else 0.0,
             (wind - 2) if c >= 4 else 0.0]
        out.append((r["bn"], x, r))
    return out


def finish_order(result, boat_numbers):
    """結果から 1着→2着→3着… の艇番（失格などで途切れたらそこまで）。"""
    places = {}
    for b in (result or {}).get("boats") or []:
        p = b.get("racer_place_number")
        if isinstance(p, int) and 1 <= p <= 6:
            places[p] = b["racer_boat_number"]
    order = []
    for p in range(1, 7):
        if places.get(p) not in boat_numbers:
            break
        order.append(places[p])
    return order


# ---------------------------------------------------------------------------
# モデル本体
# ---------------------------------------------------------------------------
class Model:
    def __init__(self, w=None, mean=None, std=None, info=None):
        n = len(FNAMES)
        self.w = w or [DEFAULT_WEIGHTS[k] for k in FNAMES]
        self.mean = mean or [0.0] * n
        self.std = std or [1.0] * n
        self.info = info or {"trained": False}

    def score(self, x):
        return sum(w * (xi - m) / s for w, xi, m, s in zip(self.w, x, self.mean, self.std))

    def to_dict(self):
        return {"features": FNAMES, "w": self.w, "mean": self.mean, "std": self.std,
                "info": self.info}

    def save(self, name="current.json"):
        os.makedirs(MODEL_DIR, exist_ok=True)
        with open(os.path.join(MODEL_DIR, name), "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=1)

    @classmethod
    def load(cls, name="current.json"):
        p = os.path.join(MODEL_DIR, name)
        if not os.path.exists(p):
            return cls()
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("features") != FNAMES:
            return cls()                     # 項目が変わった → 初期値からやり直し
        return cls(d["w"], d["mean"], d["std"], d.get("info"))

    def importance(self):
        """1標準偏差あたりの効き目（大きいほど着順に影響）。"""
        return sorted(({"key": k, "label": LABELS[k], "w": round(w, 3)}
                       for k, w in zip(FNAMES, self.w)), key=lambda d: -abs(d["w"]))


def standardize_stats(samples):
    n = len(FNAMES)
    mean, std = [0.0] * n, [1.0] * n
    xs = [x for s in samples for x in s["X"]]
    for j, k in enumerate(FNAMES):
        if k in COURSE:
            continue
        col = [x[j] for x in xs]
        m = sum(col) / len(col)
        v = sum((c - m) ** 2 for c in col) / len(col)
        mean[j], std[j] = m, (math.sqrt(v) or 1.0)
    return mean, std


def train(samples, l2=0.01, half_life=None, iters=250, lr=0.08, init=None, log=print):
    """samples: [{"X": 特徴量, "idx": 着順(何番目の艇が1着,2着,3着), "age": 何日前}]
    half_life: 何日前のレースの影響を半分にするか（Noneなら全部同じ重さ）"""
    n = len(FNAMES)
    mean, std = standardize_stats(samples)
    Z = []
    for s in samples:
        wt = 1.0 if not half_life else 0.5 ** (s["age"] / half_life)
        Z.append(([[(xi - mean[j]) / std[j] for j, xi in enumerate(x)] for x in s["X"]],
                  s["idx"][:3], wt))
    W = sum(z[2] for z in Z)
    if init is not None:                     # 前回のモデルから続けて学習（成長）
        w = [init.w[j] * (std[j] / init.std[j] if init.std[j] else 1) for j in range(n)]
    else:
        w = [DEFAULT_WEIGHTS[k] * (1 if k in COURSE else std[j]) for j, k in enumerate(FNAMES)]
    m1, m2 = [0.0] * n, [0.0] * n
    ll = 0.0
    for it in range(1, iters + 1):
        g = [0.0] * n
        ll = 0.0
        for X, order, wt in Z:
            u = [sum(a * b for a, b in zip(w, x)) for x in X]
            alive = list(range(len(X)))
            for win in order:
                mx = max(u[i] for i in alive)
                ex = [math.exp(u[i] - mx) for i in alive]
                s = sum(ex)
                ll += wt * (u[win] - mx - math.log(s))
                xw = X[win]
                for j in range(n):
                    g[j] += wt * xw[j]
                for i, e in zip(alive, ex):
                    p = wt * e / s
                    xi = X[i]
                    for j in range(n):
                        g[j] -= p * xi[j]
                alive.remove(win)
        for j in range(n):
            gj = g[j] / W - l2 * w[j]
            m1[j] = 0.9 * m1[j] + 0.1 * gj
            m2[j] = 0.999 * m2[j] + 0.001 * gj * gj
            w[j] += lr * (m1[j] / (1 - 0.9 ** it)) / (math.sqrt(m2[j] / (1 - 0.999 ** it)) + 1e-8)
        if log and it % 50 == 0:
            log(f"    学習 {it}/{iters}  平均対数尤度 {ll / W:.4f}")
    return Model(w, mean, std)


# ---------------------------------------------------------------------------
# 確率
# ---------------------------------------------------------------------------
def probabilities(model, feats):
    bns = [bn for bn, _, _ in feats]
    u = [model.score(x) for _, x, _ in feats]
    mx = max(u)
    e = {bn: math.exp(v - mx) for bn, v in zip(bns, u)}
    S = sum(e.values())
    tri = {}
    for a in bns:
        for b in bns:
            if b == a:
                continue
            for c in bns:
                if c in (a, b):
                    continue
                tri[(a, b, c)] = (e[a] / S) * (e[b] / (S - e[a])) * (e[c] / (S - e[a] - e[b]))
    win = {a: e[a] / S for a in bns}
    exa, quin, trio = {}, {}, {}
    top2 = {a: 0.0 for a in bns}
    top3 = {a: 0.0 for a in bns}
    for (a, b, c), p in tri.items():
        exa[(a, b)] = exa.get((a, b), 0) + p
        k = tuple(sorted((a, b, c)))
        trio[k] = trio.get(k, 0) + p
        for x in (a, b, c):
            top3[x] += p
    for (a, b), p in exa.items():
        top2[a] += p
        top2[b] += p
        k = tuple(sorted((a, b)))
        quin[k] = quin.get(k, 0) + p
    return {"win": win, "top2": top2, "top3": top3, "exacta": exa,
            "quinella": quin, "trifecta": tri, "trio": trio}


def top(d, n):
    return sorted(d.items(), key=lambda kv: -kv[1])[:n]


def combo_str(kind, k):
    if kind in ("win", "place"):
        return str(k)
    if kind in ("trio", "quinella"):
        return "=".join(map(str, k))
    return "-".join(map(str, k))


PAYOUT_KEY = {"win": "win", "exacta": "exacta", "trifecta": "trifecta",
              "trio": "trio", "quinella": "quinella"}


def payout(result, kind, combo):
    for p in ((result or {}).get("payouts") or {}).get(PAYOUT_KEY[kind]) or []:
        if p.get("combination") == combo:
            return p.get("payout") or 0
    return 0


def hit_of(kind, k, order):
    if len(order) < 3:
        return False
    a, b, c = order[:3]
    return {"win": k == a, "exacta": k == (a, b), "trifecta": k == (a, b, c),
            "trio": k == tuple(sorted((a, b, c))),
            "quinella": k == tuple(sorted((a, b)))}[kind]


# ---------------------------------------------------------------------------
# 成績の検証
# ---------------------------------------------------------------------------
def evaluate(model, samples):
    """学習に使っていないレースで、当たり具合と回収率を調べる。"""
    n = len(samples)
    if not n:
        return None
    ll = 0.0
    hits = {k: 0 for k in BETS}
    cost = {k: 0 for k in BETS}
    ret = {k: 0 for k in BETS}
    for s in samples:
        feats, order, result = s["feats"], s["order"], s["result"]
        pr = probabilities(model, feats)
        bns = [bn for bn, _, _ in feats]
        u = {bn: math.log(pr["win"][bn]) for bn in bns}
        alive = list(bns)
        for w in order[:3]:
            mx = max(u[i] for i in alive)
            ll += u[w] - mx - math.log(sum(math.exp(u[i] - mx) for i in alive))
            alive.remove(w)
        for key, bet in BETS.items():
            picks = [k for k, _ in top(pr[bet["kind"]], bet["n"])]
            cost[key] += 100 * len(picks)
            for k in picks:
                if hit_of(bet["kind"], k, order):
                    hits[key] += 1
                    ret[key] += payout(result, bet["kind"], combo_str(bet["kind"], k))
    return {"races": n, "loglik": round(ll / n, 4),
            "hit": {k: round(v / n, 4) for k, v in hits.items()},
            "roi": {k: round(ret[k] / cost[k], 4) if cost[k] else 0 for k in BETS}}
