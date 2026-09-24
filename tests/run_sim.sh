#!/bin/bash
# 模擬データで全体の流れを確認するテスト（本物のデータには触りません）
# 使い方: bash tests/run_sim.sh
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d)"
echo "作業フォルダ: $WORK"
python3 "$ROOT/tests/make_fixture.py" "$WORK/fx" 2026-03-01 200 >/dev/null
mkdir -p "$WORK/app" && cp -r "$ROOT/engine" "$ROOT/docs" "$WORK/app/"
rm -rf "$WORK/app/docs/data"
cd "$WORK/app"
export TODA_FIXTURE_DIR="$WORK/fx"
TODA_NOW=2026-09-01T08:30:00 python3 -m engine.pipeline setup --days 150
for t in 2026-09-02T08:30:00 2026-09-02T12:00:00 2026-09-02T17:30:00; do
  TODA_NOW=$t python3 -m engine.pipeline run
done
python3 - <<'PY'
import json
r = json.load(open("docs/data/record.json"))
m = json.load(open("docs/data/model.json"))
d = json.load(open("docs/data/days/20260902.json"))
assert r["total"]["races"] > 0, "照合されたレースがありません"
assert m["info"]["trained"], "学習されていません"
assert all(e["frozen"] for e in d["races"]), "締切後の予想が固定されていません"
for e in d["races"]:
    s = sum(b["p1"] for b in e["boats"])
    assert abs(s - 1) < 0.01, f"{e['rn']}Rの1着率の合計が100%になりません: {s}"
print("OK: 照合", r["total"]["races"], "レース / 学習", m["info"]["races"], "レース")
PY
echo "画面の確認: cd $WORK/app/docs && python3 -m http.server 8000 → http://localhost:8000"
