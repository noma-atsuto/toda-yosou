"""テスト用の模擬データを作る（本物のAPIと同じ形のJSON）。
使い方: python tests/make_fixture.py 出力フォルダ 開始日 日数
"""
import datetime as dt
import json
import math
import os
import random
import sys

out, start, days = sys.argv[1], dt.date.fromisoformat(sys.argv[2]), int(sys.argv[3])
random.seed(7)
os.makedirs(out, exist_ok=True)
racers = [dict(num=3000 + i, name=f"選手{i:03d}", nat=random.uniform(3, 8),
               cls=random.randint(1, 4)) for i in range(300)]


def dump(kind, d, items):
    with open(os.path.join(out, f"{kind}_v2_{d.year}_{d:%Y%m%d}.json"), "w") as f:
        json.dump({kind: items}, f, ensure_ascii=False)


for k in range(days):
    d = start + dt.timedelta(days=k)
    P, V, R = [], [], []
    held = (k // 6) % 2 == 0          # 6日開催→6日休み
    for st in ([2, 5] if held else [5]):
        for rn in range(1, 13):
            ent = random.sample(racers, 6 if not (rn == 12 and k % 5 == 0) else 5)
            boats, pb, u = [], [], {}
            for bn, r in enumerate(ent, 1):
                mot = random.uniform(20, 60)
                ex = random.gauss(6.75, 0.07)
                boats.append(dict(racer_boat_number=bn, racer_name=r["name"], racer_number=r["num"],
                                  racer_class_number=r["cls"], racer_weight=52, racer_flying_count=0,
                                  racer_average_start_timing=round(random.uniform(.12, .22), 2),
                                  racer_national_top_1_percent=round(r["nat"], 2),
                                  racer_national_top_2_percent=round(r["nat"] * 6, 2),
                                  racer_local_top_1_percent=round(r["nat"] + random.gauss(0, .4), 2),
                                  racer_assigned_motor_top_2_percent=round(mot, 2),
                                  racer_assigned_boat_top_2_percent=40.0))
                course = bn if random.random() > .05 else max(1, bn - 1)
                pb.append(dict(racer_boat_number=bn, racer_course_number=course,
                               racer_start_timing=round(random.uniform(.05, .25), 2), racer_weight=52,
                               racer_exhibition_time=round(ex, 2), racer_tilt_adjustment=-0.5))
                u[bn] = ([0, -1, -1.2, -1.4, -1.9, -2.6][course - 1] + .6 * (r["nat"] - 5.5)
                         + .03 * (mot - 40) - 4 * (ex - 6.75))
            wind = random.randint(0, 7)
            P.append(dict(race_date=d.isoformat(), race_stadium_number=st, race_number=rn,
                          race_closed_at=f"{d} {10 + (rn * 30) // 60:02d}:{(rn * 30) % 60:02d}:00",
                          race_title="模擬カップ", race_subtitle="一般戦", boats=boats))
            V.append(dict(race_date=d.isoformat(), race_stadium_number=st, race_number=rn,
                          race_wind=wind, race_wave=wind // 2, race_weather_number=random.choice([1, 2]),
                          boats=pb))
            alive, order = list(u), []
            while alive:
                w = [math.exp(u[b]) for b in alive]
                x = random.random() * sum(w)
                for b, ww in zip(alive, w):
                    x -= ww
                    if x <= 0:
                        break
                order.append(b)
                alive.remove(b)
            a, b, c = order[:3]
            s = sorted(order[:3])
            pw = [math.exp(u[i]) / sum(math.exp(v) for v in u.values()) for i in (a,)][0]
            R.append(dict(race_date=d.isoformat(), race_stadium_number=st, race_number=rn,
                          boats=[dict(racer_boat_number=b_, racer_place_number=i + 1)
                                 for i, b_ in enumerate(order)],
                          payouts=dict(
                              win=[dict(combination=str(a), payout=int(75 / pw) // 10 * 10)],
                              exacta=[dict(combination=f"{a}-{b}", payout=random.randint(300, 6000))],
                              trifecta=[dict(combination=f"{a}-{b}-{c}", payout=random.randint(800, 40000))],
                              trio=[dict(combination=f"{s[0]}={s[1]}={s[2]}", payout=random.randint(300, 9000))])))
    dump("programs", d, P)
    dump("previews", d, V)
    dump("results", d, R)
print("ok", out)
