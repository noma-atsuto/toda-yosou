"use strict";
/* 戸田予想アプリ（画面側）
   データは docs/data/ の JSON を読むだけ。計算はすべて GitHub Actions 側で行う。 */

const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (p, d = 1) => (p * 100).toFixed(d) + "%";
const odds = (p) => (p > 0 ? (1 / p).toFixed(1) + "倍" : "-");
const yen = (n) => n.toLocaleString("ja-JP") + "円";

const state = { index: null, dates: [], cur: null, day: null, record: null, model: null, open: new Set() };

async function getJSON(path) {
  const r = await fetch(`data/${path}?t=${Date.now()}`, { cache: "no-store" });
  if (!r.ok) throw new Error(path);
  return r.json();
}

function chip(n) { return `<span class="chip b${n}">${n}</span>`; }
function combo(s) {
  const sep = s.includes("=") ? "=" : "-";
  return `<span class="combo">${s.split(sep).map((x) => chip(x)).join(`<span class="sep">${sep}</span>`)}</span>`;
}
function confTag(c) {
  const cls = { "堅い": "t-solid", "やや堅い": "t-mid", "混戦": "t-open" }[c] || "t-info";
  return `<span class="tag ${cls}">${esc(c)}</span>`;
}
function fmtDate(iso) {
  const d = new Date(iso + "T00:00:00+09:00");
  const w = "日月火水木金土"[d.getDay()];
  return `${d.getMonth() + 1}月${d.getDate()}日（${w}）`;
}
function nowJST() { return new Date(Date.now()); }
function closeTime(e) { return e.closed_at ? new Date(e.closed_at.replace(" ", "T") + "+09:00") : null; }

/* ---------------- 予想 ---------------- */
function renderToday() {
  const v = $("#view-today");
  const day = state.day;
  if (!day) {
    v.innerHTML = `<div class="empty">まだ予想がありません。<br>開催日になると自動で表示されます。</div>`;
    return;
  }
  $("#dayTitle").textContent = `${day.stadium} ${fmtDate(day.date)}`;
  const upd = day.updated_at ? day.updated_at.slice(11, 16) : "-";
  const td = state.model?.info?.trained_date;
  $("#daySub").textContent = `予想の更新 ${upd}　／　${td ? `モデル ${td.slice(5).replace("-", "/")} 学習` : "学習前"}`;

  const now = nowJST();
  const races = day.races;
  const next = races.find((e) => { const t = closeTime(e); return t && t > now; });
  let html = "";

  if (!state.model?.info?.trained) {
    html += `<div class="banner">まだ学習前のため、一般的な傾向（初期値）で予想しています。</div>`;
  }

  // 1日のまとめ
  const graded = races.filter((e) => e.result && !e.result.void);
  if (graded.length) {
    const h = (k) => graded.filter((e) => e.result.hits?.[k]).length;
    const ret = (k) => graded.reduce((a, e) => a + (e.result.ret?.[k] || 0), 0);
    html += `<div class="card"><h2>この日の答え合わせ（${graded.length}レース終了）</h2>
      <div class="kpis">
        <div class="kpi"><div class="l">本命が1着</div><div class="v num">${h("win1")}<small>/${graded.length}</small></div></div>
        <div class="kpi"><div class="l">3連単 上位5点</div><div class="v num">${h("tri5")}<small>/${graded.length}</small></div>
          <div class="s">払戻 ${yen(ret("tri5"))}／投資 ${yen(graded.length * 500)}</div></div>
      </div></div>`;
  }

  // 注目レース
  const upcoming = races.filter((e) => !e.result);
  if (upcoming.length) {
    const solid = [...upcoming].sort((a, b) => b.fav - a.fav).slice(0, 3);
    const rough = [...upcoming].sort((a, b) => a.fav - b.fav).slice(0, 2);
    const row = (e, why) => `<div class="pick" data-go="${e.rn}"><span class="rn">${e.rn}R</span>
      ${combo(e.bets.trifecta[0][0])}<span class="why">${why}</span></div>`;
    html += `<div class="card"><h2>今日の注目</h2><div class="picks">
      ${solid.map((e) => row(e, `本命 ${chip(e.boats.find((b) => b.p1 === Math.max(...e.boats.map((x) => x.p1))).bn)} 1着率 ${pct(e.fav, 0)}`)).join("")}
      </div><h3>荒れそうなレース</h3><div class="picks">
      ${rough.map((e) => row(e, `本命でも1着率 ${pct(e.fav, 0)}`)).join("")}</div>
      <p class="note">上の買い目は3連単の1点目です。タップするとそのレースを開きます。</p></div>`;
  }

  html += races.map((e) => raceCard(e, e === next)).join("");
  html += `<p class="note">「目安オッズ」は確率から計算した"トントンになるオッズ"です。実際のオッズがこれより高ければ割安です。
    確率は過去データからの推定で、的中を保証するものではありません。</p>`;
  v.innerHTML = html;

  v.querySelectorAll(".race-head").forEach((h) => h.addEventListener("click", () => {
    const rn = +h.parentElement.dataset.rn;
    state.open.has(rn) ? state.open.delete(rn) : state.open.add(rn);
    h.parentElement.classList.toggle("open");
  }));
  v.querySelectorAll("[data-go]").forEach((p) => p.addEventListener("click", () => {
    const rn = +p.dataset.go;
    state.open.add(rn);
    const el = v.querySelector(`.race[data-rn="${rn}"]`);
    el.classList.add("open");
    el.scrollIntoView({ behavior: "smooth", block: "start" });
  }));
}

function raceCard(e, isNext) {
  const r = e.result;
  const time = e.closed_at ? e.closed_at.slice(11, 16) : "--:--";
  let status = "";
  if (r && !r.void) {
    status = `<span class="tag ${r.hits.win1 ? "hit" : "miss"}">単 ${r.hits.win1 ? "◯" : "×"}</span>
      <span class="tag ${r.hits.tri5 ? "hit" : "miss"}">3単5点 ${r.hits.tri5 ? "◯" : "×"}</span>`;
  } else if (r && r.void) {
    status = `<span class="tag t-info">不成立</span>`;
  } else if (isNext) {
    status = `<span class="tag t-info">次のレース</span>`;
  }
  const fav = [...e.boats].sort((a, b) => b.p1 - a.p1).slice(0, 3);
  const open = state.open.has(e.rn) ? " open" : "";
  return `<article class="race${isNext ? " next" : ""}${open}" data-rn="${e.rn}">
    <div class="race-head">
      <div class="rn">${e.rn}R</div>
      <div class="meta">
        <div class="line1"><span>締切 ${time}</span>${confTag(e.confidence)}
          ${e.has_preview ? "" : `<span class="tag t-info">展示前</span>`}${status}</div>
        <div class="line2">${fav.map((b) => `${chip(b.bn)}<span class="num sub-stats">${pct(b.p1, 0)}</span>`).join(" ")}</div>
      </div>
      <span class="caret">›</span>
    </div>
    <div class="race-body">${raceDetail(e)}</div>
  </article>`;
}

function raceDetail(e) {
  const r = e.result && !e.result.void ? e.result : null;
  const cond = e.has_preview
    ? `${esc(e.weather ?? "-")}　風 ${e.wind ?? "-"}m　波 ${e.wave ?? "-"}cm`
    : "展示（直前の試運転）前の予想です。展示後に自動で更新されます。";
  const rows = e.boats.map((b) => `<tr>
      <td>${chip(b.bn)}</td>
      <td class="name"><b>${esc(b.name)}</b><small>${esc(b.cls)}・${b.course}コース</small></td>
      <td><span class="pbar"><i style="width:${Math.round(b.p1 * 100)}%"></i><span class="num">${pct(b.p1)}</span></span></td>
      <td class="num">${pct(b.p2, 0)}</td><td class="num">${pct(b.p3, 0)}</td>
      <td class="num">${b.exh ? b.exh.toFixed(2) : "-"}<br><span class="sub-stats">${b.nat.toFixed(2)}</span></td>
    </tr>`).join("");
  const win = r ? r.order.slice(0, 3) : null;
  const isWin = (kind, s) => {
    if (!win) return false;
    const [a, b, c] = win;
    if (kind === "trifecta") return s === `${a}-${b}-${c}`;
    if (kind === "exacta") return s === `${a}-${b}`;
    if (kind === "trio") return s === [a, b, c].sort().join("=");
    if (kind === "quinella") return s === [a, b].sort().join("=");
    if (kind === "win") return s === String(a);
    if (kind === "place") return s === String(a) || s === String(b);
    return false;
  };
  const list = (title, kind, cls = "") => `<div class="bet ${cls}"><h4>${title}</h4><ol>
    ${e.bets[kind].map(([s, p]) => `<li class="${isWin(kind, s) ? "win" : ""}">${s.length === 1 ? chip(s) : combo(s)}
      <span class="p num">${pct(p)}</span><span class="o num">${odds(p)}</span></li>`).join("")}</ol></div>`;
  let res = "";
  if (r) {
    const pay = (k, label) => r.payouts?.[k] ? `<span>${label} ${combo(r.payouts[k][0])} ${yen(r.payouts[k][1])}</span>` : "";
    res = `<div class="result"><div class="row"><b>結果</b>${combo(r.order.slice(0, 3).join("-"))}</div>
      <div class="row" style="margin-top:6px">${pay("trifecta", "3連単")}${pay("trio", "3連複")}</div></div>`;
  }
  return `<p class="note">${cond}</p>
    <table class="boats"><thead><tr><th>枠</th><th>選手</th><th>1着率</th><th>2着内</th><th>3着内</th><th>展示<br>勝率</th></tr></thead>
    <tbody>${rows}</tbody></table>
    ${res}
    <div class="bets">
      ${list("3連単", "trifecta", "full")}
      ${list("3連複", "trio", "full")}${list("2連単", "exacta", "full")}
      ${list("2連複", "quinella")}${list("単勝", "win")}
    </div>
    <p class="note">予想の最終更新 ${esc(e.updated_at ?? "-")}${e.frozen ? "（締切時点で確定）" : ""}</p>`;
}

/* ---------------- 折れ線グラフ（なぞると数値が出る） ---------------- */
function lineChart(el, { labels, series, yFmt = (v) => pct(v, 0), ref = null, yMin = 0, yMax = null }) {
  const W = 340, H = 190, L = 34, R = 44, T = 10, B = 22;
  const all = series.flatMap((s) => s.values).filter((v) => v != null);
  if (!all.length) { el.innerHTML = `<p class="note">データがたまると表示されます。</p>`; return; }
  let hi = yMax ?? Math.max(...all, ref ?? 0) * 1.1;
  if (hi <= yMin) hi = yMin + 1;
  const n = labels.length;
  const x = (i) => L + (n === 1 ? (W - L - R) / 2 : (i * (W - L - R)) / (n - 1));
  const y = (v) => T + (H - T - B) * (1 - (v - yMin) / (hi - yMin));
  const ticks = 4;
  let g = "";
  for (let k = 0; k <= ticks; k++) {
    const v = yMin + ((hi - yMin) * k) / ticks;
    g += `<line class="gridline" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/>
      <text class="axis-t" x="${L - 4}" y="${y(v) + 3}" text-anchor="end">${yFmt(v)}</text>`;
  }
  const step = Math.max(1, Math.ceil(n / 4));
  labels.forEach((lb, i) => {
    if (i % step === 0 || i === n - 1) g += `<text class="axis-t" x="${x(i)}" y="${H - 6}" text-anchor="middle">${lb.slice(5).replace("-", "/")}</text>`;
  });
  if (ref != null) g += `<line class="ref" x1="${L}" x2="${W - R}" y1="${y(ref)}" y2="${y(ref)}"/>`;
  series.forEach((s) => {
    const pts = s.values.map((v, i) => (v == null ? null : [x(i), y(v)])).filter(Boolean);
    if (pts.length > 1) g += `<polyline fill="none" stroke="${s.color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" points="${pts.map((p) => p.join(",")).join(" ")}"/>`;
    if (pts.length <= 12) pts.forEach((p) => { g += `<circle cx="${p[0]}" cy="${p[1]}" r="3.5" fill="${s.color}" stroke="var(--surface)" stroke-width="2"/>`; });
  });
  // 右端の数値ラベル（重ならないようにずらす）
  const ends = series.map((s) => {
    const i = s.values.length - 1;
    return s.values[i] == null ? null : { y: y(s.values[i]), x: x(i), t: yFmt(s.values[i]) };
  }).filter(Boolean).sort((a, b) => a.y - b.y);
  for (let k = 1; k < ends.length; k++) if (ends[k].y - ends[k - 1].y < 11) ends[k].y = ends[k - 1].y + 11;
  if (series.length <= 4) ends.forEach((e) => { g += `<text class="lbl" x="${e.x + 6}" y="${e.y + 3}">${e.t}</text>`; });
  el.innerHTML = `<div class="legend">${series.map((s) => `<span><i style="background:${s.color}"></i>${esc(s.name)}</span>`).join("")}</div>
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(series.map((s) => s.name).join("、"))}の推移">${g}
    <line class="cross" x1="0" x2="0" y1="${T}" y2="${H - B}" visibility="hidden"/>
    <rect x="${L}" y="${T}" width="${W - L - R}" height="${H - T - B}" fill="transparent"/></svg>`;
  const svg = el.querySelector("svg"), cross = svg.querySelector(".cross"), tip = $("#tip");
  const move = (ev) => {
    const b = svg.getBoundingClientRect();
    const px = ((ev.clientX - b.left) / b.width) * W;
    const i = Math.max(0, Math.min(n - 1, Math.round(((px - L) / (W - L - R)) * (n - 1))));
    cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("visibility", "visible");
    tip.innerHTML = `<b>${esc(labels[i])}</b>` + series.map((s) => `<div class="r"><i style="background:${s.color}"></i>${esc(s.name)} <span class="num">${s.values[i] == null ? "-" : yFmt(s.values[i])}</span></div>`).join("");
    tip.hidden = false;
    const tx = Math.min(window.innerWidth - 230, Math.max(8, ev.clientX - 110));
    tip.style.left = tx + "px"; tip.style.top = (b.top - 8 - tip.offsetHeight) + "px";
  };
  const hide = () => { tip.hidden = true; cross.setAttribute("visibility", "hidden"); };
  svg.addEventListener("pointermove", move);
  svg.addEventListener("pointerdown", move);
  svg.addEventListener("pointerleave", hide);
  svg.addEventListener("pointerup", (ev) => { if (ev.pointerType !== "mouse") setTimeout(hide, 1500); });
}

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

/* ---------------- 成績 ---------------- */
function renderRecord() {
  const v = $("#view-record");
  const rec = state.record;
  if (!rec || !rec.total.races) {
    v.innerHTML = `<div class="card"><h2>本番の成績</h2><p class="muted">まだ答え合わせしたレースがありません。
      開催日にアプリが自動で予想し、レース後に結果と照合してここに記録していきます。</p></div>` + validCard();
    bindValidChart();
    return;
  }
  const t = rec.total, keys = Object.keys(rec.bets);
  const rows = keys.map((k) => {
    const roi = t.cost[k] ? t.ret[k] / t.cost[k] : 0;
    return `<tr><td>${esc(rec.bets[k])}</td><td class="num">${pct(t.hits[k] / t.races)}</td>
      <td class="num ${roi >= 1 ? "good-t" : ""}">${pct(roi)}</td><td class="num">${yen(t.ret[k] - t.cost[k])}</td></tr>`;
  }).join("");
  const days = rec.daily;
  v.innerHTML = `
    <div class="card"><h2>本番の成績（締切前の予想と実際の結果を照合）</h2>
      <div class="kpis">
        <div class="kpi"><div class="l">照合したレース</div><div class="v num">${t.races}</div><div class="s">${days.length}日分</div></div>
        <div class="kpi"><div class="l">本命が1着</div><div class="v num">${pct(t.hits.win1 / t.races)}</div><div class="s">${t.hits.win1}回</div></div>
      </div>
      <h3>毎レース100円ずつ機械的に買った場合</h3>
      <table class="tbl"><thead><tr><th>買い方</th><th>的中率</th><th>回収率</th><th>収支</th></tr></thead><tbody>${rows}</tbody></table>
      <p class="note">回収率が100%未満なら、そのまま買い続けると損になる計算です。</p>
    </div>
    <div class="card"><h2>的中率の推移（直近7開催日の平均）</h2><div class="chart" id="chHit"></div></div>
    <div class="card"><h2>回収率の推移（累計）</h2><div class="chart" id="chRoi"></div>
      <p class="note">点線が100%（トントン）の線です。</p></div>
    <div class="card"><h2>日ごとの結果</h2>
      <table class="tbl"><thead><tr><th>日付</th><th>R数</th><th>本命1着</th><th>3単5点</th><th>3複3点</th></tr></thead>
      <tbody>${[...days].reverse().slice(0, 30).map((d) => `<tr><td>${d.date.slice(5).replace("-", "/")}</td><td class="num">${d.races}</td>
        <td class="num">${d.hits.win1}</td><td class="num">${d.hits.tri5}</td><td class="num">${d.hits.trio3}</td></tr>`).join("")}</tbody></table></div>
    ${validCard()}`;

  const roll = (k) => days.map((_, i) => {
    const w = days.slice(Math.max(0, i - 6), i + 1);
    const n = w.reduce((a, d) => a + d.races, 0);
    return n ? w.reduce((a, d) => a + d.hits[k], 0) / n : null;
  });
  const cum = (k) => { let c = 0, r = 0; return days.map((d) => { c += d.cost[k]; r += d.ret[k]; return c ? r / c : null; }); };
  const S = [["win1", "--s1"], ["tri5", "--s2"], ["trio3", "--s3"]];
  lineChart($("#chHit"), { labels: days.map((d) => d.date), series: S.map(([k, c]) => ({ name: rec.bets[k], color: css(c), values: roll(k) })) });
  lineChart($("#chRoi"), { labels: days.map((d) => d.date), series: S.map(([k, c]) => ({ name: rec.bets[k], color: css(c), values: cum(k) })), ref: 1 });
  bindValidChart();
}

function validCard() {
  const vi = state.model?.info?.valid;
  if (!vi) return "";
  const bets = state.model.bets;
  const d = state.model.info.valid_default;
  return `<div class="card"><h2>学習時の検証（過去のレースで試した成績）</h2>
    <table class="tbl"><thead><tr><th>買い方</th><th>的中率</th><th>学習前</th><th>回収率</th></tr></thead><tbody>
    ${Object.keys(bets).map((k) => `<tr><td>${esc(bets[k])}</td><td class="num">${pct(vi.hit[k])}</td>
      <td class="num muted">${pct(d.hit[k])}</td><td class="num">${pct(vi.roi[k])}</td></tr>`).join("")}</tbody></table>
    <p class="note">学習に使っていない直近${vi.races}レースで試した数字です。</p></div>`;
}
function bindValidChart() {}

/* ---------------- 学習 ---------------- */
function renderModel() {
  const v = $("#view-model");
  const m = state.model;
  if (!m) { v.innerHTML = `<div class="empty">学習データがありません。</div>`; return; }
  const i = m.info;
  const hist = m.history || [];
  const maxW = Math.max(...m.importance.map((d) => Math.abs(d.w)), 0.01);
  const imp = m.importance.slice(0, 12).map((d) => {
    const w = (Math.abs(d.w) / maxW) * 50;
    const left = d.w >= 0 ? 50 : 50 - w;
    return `<div class="imp-row"><div>${esc(d.label)} <span class="muted num">${d.w >= 0 ? "+" : "−"}${Math.abs(d.w).toFixed(2)}</span></div>
      <div class="imp-bar"><span class="axis"></span><i style="left:${left}%;width:${w}%;background:var(${d.w >= 0 ? "--pos" : "--neg"})"></i></div></div>`;
  }).join("");
  v.innerHTML = `
    <div class="card"><h2>いまの予想モデル</h2>
      ${i.trained ? `<table class="tbl"><tbody>
        <tr><td>最後に学習した日</td><td>${esc(i.trained_at)}</td></tr>
        <tr><td>学習に使ったレース</td><td class="num">${i.races}件</td></tr>
        <tr><td>期間</td><td>${esc(i.from)} 〜 ${esc(i.to)}</td></tr>
        <tr><td>選ばれた設定</td><td>強さの抑え ${i.params.l2}・${i.params.half_life ? `${i.params.half_life}日で重み半分` : "全期間同じ重み"}</td></tr>
      </tbody></table>` : `<p class="muted">まだ学習していません（初期値で予想中）。</p>`}
    </div>
    <div class="card"><h2>学習による成長（毎日の検証での的中率）</h2><div class="chart" id="chGrow"></div>
      <p class="note">毎朝、前日までの結果を加えて学習し直し、学習に使っていない直近のレースで当たり具合を確かめています。</p></div>
    <div class="card"><h2>着順に効いている項目</h2>
      <div class="legend"><span><i style="background:var(--pos)"></i>有利になる</span><span><i style="background:var(--neg)"></i>不利になる</span></div>
      <div class="imp" style="grid-template-columns:minmax(9em,46%) 1fr">${imp}</div>
      <p class="note">数字は「その項目が平均より1段階（標準偏差1つ分）良いと、強さがどれだけ変わるか」。コースは1コースとの差です。</p></div>
    <div class="card"><h2>しくみ</h2><details><summary>どうやって学習しているの？</summary>
      <p class="note">① 毎日、出走表・展示・結果のデータを自動で集めます。<br>
      ② 朝に、これまでの全レースから「どの数字が着順にどれだけ効くか」を学び直します。
         4通りの設定を試し、直近のレースでいちばん当たった設定を採用します。<br>
      ③ 日中は展示が出るたびに予想を更新し、締切の時点で予想を固定します。<br>
      ④ レース後に結果と照合し、「成績」タブに記録します。</p></details></div>`;
  lineChart($("#chGrow"), {
    labels: hist.map((h) => h.date),
    series: [
      { name: "本命が1着", color: css("--s1"), values: hist.map((h) => h.hit.win1) },
      { name: "3連単 上位5点", color: css("--s2"), values: hist.map((h) => h.hit.tri5) },
      { name: "3連複 上位3点", color: css("--s3"), values: hist.map((h) => h.hit.trio3) },
    ],
  });
}

/* ---------------- 日付の切り替え ---------------- */
async function loadDay(date, keepOpen = false) {
  state.cur = date;
  if (!keepOpen) state.open.clear();
  try { state.day = await getJSON(`days/${date.replaceAll("-", "")}.json`); }
  catch { state.day = null; }
  const i = state.dates.indexOf(date);
  $("#prevDay").disabled = i <= 0;
  $("#nextDay").disabled = i < 0 || i >= state.dates.length - 1;
  renderToday();
}

function pickDefaultDate() {
  const today = state.index.today;
  if (state.dates.includes(today)) return today;
  const after = state.dates.filter((d) => d > today);
  return after[0] || state.dates[state.dates.length - 1];
}

async function loadData() {
  const [index, record, model] = await Promise.all([getJSON("index.json"), getJSON("record.json").catch(() => null), getJSON("model.json").catch(() => null)]);
  state.index = index; state.record = record; state.model = model;
  state.dates = index.dates || [];
  renderRecord();
  renderModel();
}

async function init() {
  document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("active", x === t));
    document.querySelectorAll(".view").forEach((x) => x.classList.toggle("active", x.id === "view-" + t.dataset.view));
    $("#tip").hidden = true;
    window.scrollTo(0, 0);
  }));
  $("#prevDay").addEventListener("click", () => { const i = state.dates.indexOf(state.cur); if (i > 0) loadDay(state.dates[i - 1]); });
  $("#nextDay").addEventListener("click", () => { const i = state.dates.indexOf(state.cur); if (i < state.dates.length - 1) loadDay(state.dates[i + 1]); });

  try {
    await loadData();
  } catch {
    $("#daySub").textContent = "データを読み込めませんでした";
    $("#view-today").innerHTML = `<div class="empty">データがまだありません。<br>初回セットアップが終わると表示されます。</div>`;
    return;
  }
  if (state.dates.length) await loadDay(pickDefaultDate());
  else renderToday();
}

// 開いている間、裏で数分おきに最新データを取りに行き、見ている場所（開いているレースなど）を保ったまま画面だけ更新する。
// ネットにつながらないとき（オフライン時）は、サービスワーカーが前回保存分を返すか、失敗しても何もせず今の画面を保つ。
async function refresh() {
  try {
    await loadData();
    if (state.dates.length) await loadDay(state.dates.includes(state.cur) ? state.cur : pickDefaultDate(), true);
  } catch { /* オフライン等。今の画面のまま */ }
}

let lastRefresh = Date.now();
function refreshIfVisible() {
  if (document.visibilityState !== "visible") return;
  lastRefresh = Date.now();
  refresh();
}
setInterval(refreshIfVisible, 3 * 60 * 1000);
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && Date.now() - lastRefresh > 60 * 1000) refreshIfVisible();
});

if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
init();
