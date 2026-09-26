let G = null;
let D = null;
const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
const $ = (s) => document.querySelector(s);
const usd = (v, d = 0) => (v < 0 ? "-$" : "$") + Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
const sUsd = (v) => (v > 0 ? "+" : "") + usd(v);
const pct = (v, d = 1) => (v * 100).toFixed(d) + "%";
const sPct = (v, d = 1) => (v > 0 ? "+" : "") + pct(v, d);
const tone = (v) => (v > 0 ? "up" : v < 0 ? "down" : "");
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const WEEK = 7 * 864e5;

/* ---------- rail: active chapter ---------- */
(function rail() {
  const links = [...document.querySelectorAll("#chapters a")];
  const marker = $("#marker");
  const set = (id) => links.forEach((a) => {
    const on = a.dataset.ch === id;
    a.setAttribute("aria-current", on ? "true" : "false");
    if (on) marker.style.setProperty("--y", a.offsetTop + (a.offsetHeight - 22) / 2 + "px");
  });
  set("pulse");
  const io = new IntersectionObserver((es) => es.forEach((e) => e.isIntersecting && set(e.target.id)), { rootMargin: "-40% 0px -55% 0px" });
  document.querySelectorAll("main .chapter").forEach((s) => io.observe(s));
  const sheet = $("#sheet");
  $("#open-sheet").onclick = () => sheet.showModal();
  $("#close-sheet").onclick = () => sheet.close();
  sheet.querySelectorAll("a").forEach((a) => a.addEventListener("click", () => sheet.close()));
})();

function start() {
/* ---------- chapter 1: the pulse ---------- */
(function pulse() {
  const el = $("#pulse-chart"), svg = $("#pulse-svg"), tip = $("#pulse-tip");
  const n = G.median.length, TOP = 120, BOT = -20;
  let geo = null, played = false;
  function render() {
    const W = Math.max(300, svg.getBoundingClientRect().width), narrow = W < 560;
    const H = narrow ? 340 : 410, l = narrow ? 40 : 56, r = 10, t1 = 46, b1 = H - 128, t2 = H - 100, b2 = H - 34;
    const x = (i) => l + (i / (n - 1)) * (W - l - r);
    const yF = (v) => t1 + (1 - (Math.max(BOT, Math.min(TOP, v)) - BOT) / (TOP - BOT)) * (b1 - t1);
    const yH = (v) => b2 - (v / 10) * (b2 - t2);
    geo = { W, l, r, x };
    let g = `<text class="title" x="0" y="14">Funding, % a year</text>`;
    [0, 40, 80, 120].forEach((v) => {
      g += `<line x1="${l}" x2="${W - r}" y1="${yF(v)}" y2="${yF(v)}" stroke="${v === 0 ? "var(--lichen)" : "var(--moss)"}"/>` +
        `<text x="${l - 8}" y="${yF(v) + 4}" text-anchor="end">${v}%</text>`;
    });
    for (let yr = 2021; yr <= 2026; yr++) {
      const i = Math.round((Date.UTC(yr, 0, 1) - G.start) / WEEK);
      g += `<line x1="${x(i)}" x2="${x(i)}" y1="${t1}" y2="${b2}" stroke="var(--moss)" stroke-dasharray="2 4"/>`;
    }
    for (let yr = 2020; yr <= 2026; yr++) {
      const a = Math.max(0, (Date.UTC(yr, 0, 1) - G.start) / WEEK), b = Math.min(n - 1, (Date.UTC(yr + 1, 0, 1) - G.start) / WEEK);
      g += `<text x="${x((a + b) / 2)}" y="${H - 10}" text-anchor="middle">${yr}</text>`;
    }
    g += `<text class="title" x="0" y="${t2 - 10}">Positions NIRU held</text>`;
    [0, 10].forEach((v) => { g += `<text x="${l - 8}" y="${yH(v) + 4}" text-anchor="end">${v}</text>`; });
    g += `<line x1="${l}" x2="${W - r}" y1="${b2}" y2="${b2}" stroke="var(--lichen)"/>`;

    const top = G.p90.map((v, i) => `${x(i).toFixed(1)},${yF(v).toFixed(1)}`);
    const mid = G.median.map((v, i) => `${x(i).toFixed(1)},${yF(v).toFixed(1)}`);
    let data = `<polygon points="${top.join(" ")} ${mid.slice().reverse().join(" ")}" fill="rgb(86 199 154 / 0.24)"/>` +
      `<polyline points="${top.join(" ")}" fill="none" stroke="var(--jade)" stroke-width="1.5" stroke-linejoin="round"/>` +
      `<polyline points="${mid.join(" ")}" fill="none" stroke="var(--bone)" stroke-width="1.75" stroke-linejoin="round"/>`;
    const bw = Math.max(1, (W - l - r) / n - 1);
    G.held.forEach((v, i) => {
      if (v > 0) data += `<rect x="${(x(i) - bw / 2).toFixed(1)}" y="${yH(v).toFixed(1)}" width="${bw.toFixed(1)}" height="${(b2 - yH(v)).toFixed(1)}" rx="1" fill="var(--necrotic)"/>`;
    });
    let peak = 0;
    G.p90.forEach((v, i) => { if (v > G.p90[peak]) peak = i; });
    data += `<text class="note" x="${Math.min(x(peak) + 8, W - r - 150)}" y="${t1 - 10}">Peak week ${Math.round(G.p90[peak])}%, clipped</text>`;
    if (!narrow) {
      [[2022, "2022: median 2%"], [2025, "2025: median 5%"]].forEach(([yr, label]) => {
        const i = Math.round((Date.UTC(yr, 6, 1) - G.start) / WEEK);
        data += `<text class="note" x="${x(i)}" y="${yF(55)}" text-anchor="middle">${label}</text>`;
      });
    }
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.setAttribute("height", H);
    svg.innerHTML = g + `<g id="pulse-data">${data}</g>` +
      `<line id="pulse-xh" y1="${t1}" y2="${b2}" stroke="var(--ash)" visibility="hidden"/>` +
      `<rect x="${l}" y="${t1}" width="${W - l - r}" height="${b2 - t1}" fill="transparent"/>`;
    if (!played && !reduce) {
      played = true;
      svg.querySelector("#pulse-data").animate([{ clipPath: "inset(0 100% 0 0)" }, { clipPath: "inset(0 0 0 0)" }],
        { duration: 1500, easing: "cubic-bezier(0.77, 0, 0.175, 1)" });
    }
  }
  new ResizeObserver(render).observe(el);
  svg.addEventListener("pointermove", (e) => {
    if (!geo) return;
    const rr = svg.getBoundingClientRect(), sx = (e.clientX - rr.left) * (geo.W / rr.width);
    const i = Math.max(0, Math.min(n - 1, Math.round(((sx - geo.l) / (geo.W - geo.l - geo.r)) * (n - 1))));
    const xh = svg.querySelector("#pulse-xh");
    xh.setAttribute("x1", geo.x(i)); xh.setAttribute("x2", geo.x(i)); xh.setAttribute("visibility", "visible");
    const sg = (v) => (v > 0 ? "+" : "") + v;
    tip.innerHTML = `<b>Week of ${new Date(G.start + i * WEEK).toISOString().slice(0, 10)}</b>` +
      `<span>Median coin ${sg(G.median[i])}% a year</span><span>Top 10% of coins ${sg(G.p90[i])}% a year</span>` +
      `<span class="held-line">NIRU held ${G.held[i]} position${G.held[i] === 1 ? "" : "s"}</span><span>${G.listed[i]} coins listed</span>`;
    const px = (geo.x(i) / geo.W) * rr.width;
    tip.style.left = Math.min(px + 30, rr.width - 190) + "px";
    tip.style.top = "40px";
    tip.classList.add("on");
  });
  svg.addEventListener("pointerleave", () => {
    tip.classList.remove("on");
    const xh = svg.querySelector("#pulse-xh");
    if (xh) xh.setAttribute("visibility", "hidden");
  });
})();

/* ---------- figures under the hero ---------- */
(function figures() {
  const L = D.life, yrs = D.pnl.length / 365.25, annual = Math.pow(1 + L.pnl_pct, 1 / yrs) - 1;
  $("#figures").innerHTML = [
    [pct(annual), "a year after every fee"], [pct(L.accuracy), "of positions closed in profit"],
    [pct(L.payment_accuracy), "of funding payments in its favour"], [pct(L.dd_pct), "worst drawdown since 2020"],
  ].map(([b, s]) => `<div><b class="num">${b}</b><span>${s}</span></div>`).join("");
})();

/* ---------- chapter 2: the ritual ---------- */
(function ritual() {
  const svg = $("#ritual-svg"), W = 600, L = 64, R = 12;
  const n = 97, xs = (i) => L + (i / (n - 1)) * (W - L - R);
  const price = Array.from({ length: n }, (_, i) => Math.sin(i / 7) * 0.9 + Math.sin(i / 3.1) * 0.35 + Math.sin(i / 17) * 1.4);
  const lanes = [
    { key: "spot", label: "Spot, long", y0: 60, sign: 1 },
    { key: "perp", label: "Perp, short", y0: 160, sign: -1 },
  ];
  const pay = [32, 64, 96];
  let html = "";
  lanes.forEach((ln) => {
    const pts = price.map((p, i) => `${xs(i).toFixed(1)},${(ln.y0 - p * ln.sign * 16).toFixed(1)}`).join(" ");
    html += `<g class="lane lane-${ln.key}"><line x1="${L}" x2="${W - R}" y1="${ln.y0}" y2="${ln.y0}" stroke="var(--moss)"/>` +
      `<text x="0" y="${ln.y0 + 4}">${ln.label}</text>` +
      `<polyline class="trace" points="${pts}" fill="none" stroke="${ln.key === "spot" ? "var(--jade)" : "var(--ash)"}" stroke-width="2" stroke-linejoin="round"/></g>`;
  });
  const netY = 270, stepH = 14;
  let d = `M${L},${netY}`, level = netY;
  pay.forEach((p) => { d += ` H${xs(p)} V${level - stepH}`; level -= stepH; });
  d += ` H${W - R}`;
  html += `<g class="lane lane-net"><line x1="${L}" x2="${W - R}" y1="${netY}" y2="${netY}" stroke="var(--moss)"/><text x="0" y="${netY + 4}">Net</text>` +
    `<path class="trace" d="${d}" fill="none" stroke="var(--necrotic)" stroke-width="2.5" stroke-linejoin="round"/>` +
    pay.map((p, k) => `<g class="drop" data-k="${k}"><line x1="${xs(p)}" x2="${xs(p)}" y1="18" y2="${netY - k * stepH - 6}" stroke="var(--necrotic)" stroke-dasharray="2 5" opacity="0.5"/>` +
      `<circle cx="${xs(p)}" cy="18" r="5" fill="var(--necrotic)"/><text x="${xs(p)}" y="10" text-anchor="middle">${String(8 * (k + 1)).padStart(2, "0")}:00</text></g>`).join("") + `</g>`;
  svg.innerHTML = html;
  const diag = $("#diagram"), collected = $("#collected");
  const traces = [...svg.querySelectorAll(".trace")], drops = [...svg.querySelectorAll(".drop")];
  function play() {
    collected.textContent = "+0.000%";
    if (reduce) { collected.textContent = "+0.030%"; return; }
    traces.forEach((t) => { const len = t.getTotalLength(); t.animate([{ strokeDasharray: len, strokeDashoffset: len * 0.6 }, { strokeDasharray: len, strokeDashoffset: 0 }], { duration: 1400, easing: "cubic-bezier(0.23, 1, 0.32, 1)" }); });
    drops.forEach((g, k) => {
      const c = g.querySelector("circle");
      const fall = +g.querySelector("line").getAttribute("y2") - 18;
      c.animate([{ transform: "translateY(0)", opacity: 1 }, { transform: `translateY(${fall}px)`, opacity: 1 }, { transform: `translateY(${fall}px)`, opacity: 0 }],
        { duration: 700, delay: 500 + k * 450, easing: "cubic-bezier(0.55, 0, 1, 0.45)" })
        .finished.then(() => { collected.textContent = "+" + (0.01 * (k + 1)).toFixed(3) + "%"; });
    });
  }
  new IntersectionObserver((es, o) => es.forEach((e) => { if (e.isIntersecting) { play(); o.disconnect(); } }), { threshold: 0.4 }).observe(diag);
  document.querySelectorAll(".step").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll(".step").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    diag.dataset.focus = b.dataset.focus;
    if (b.dataset.focus === "net") play();
  }));
})();

/* ---------- chapter 3: the autopsy ---------- */
(function autopsy() {
  const stages = D.stages;
  const notes = [
    "Clean code on an optimistic model. Every figure here was later shown to be flattered.",
    "Ten flaws closed. Profit fell by more than a third and accuracy slipped under 60%. These are the honest numbers.",
    "Two entry filters: seven straight days of positive funding and a liquidity floor. Chosen on 2020 to 2023, confirmed on unseen 2024 to 2026 data.",
  ];
  const fields = [["pnl", "profit after deposits", (v) => sUsd(v)], ["acc", "of positions in profit", (v) => pct(v)],
    ["dd", "worst drawdown", (v) => pct(v, 2)], ["pos", "positions", (v) => Math.round(v).toLocaleString("en-US")]];
  const box = $("#stages"), out = $("#readout"), note = $("#readout-note");
  box.innerHTML = stages.map((s, i) => `<button type="button" aria-pressed="${i === 2}" data-i="${i}">${s.name}</button>`).join("");
  out.innerHTML = fields.map(([k, label]) => `<div><b class="num" data-k="${k}"></b><span>${label}</span></div>`).join("");
  let cur = { ...stages[2] };
  const paint = (s) => fields.forEach(([k, , f]) => { out.querySelector(`[data-k="${k}"]`).textContent = f(s[k]); });
  paint(cur); note.textContent = notes[2];
  box.addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    box.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    const to = stages[+b.dataset.i], from = { ...cur }; note.textContent = notes[+b.dataset.i];
    if (reduce) { cur = { ...to }; paint(cur); return; }
    const t0 = performance.now(), dur = 520;
    const tick = (t) => {
      const k = Math.min(1, (t - t0) / dur), e2 = 1 - Math.pow(1 - k, 3);
      fields.forEach(([f]) => { cur[f] = from[f] + (to[f] - from[f]) * e2; });
      paint(cur); if (k < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });

  const W = [
    ["Funding on the wrong day", "Binance stamps many funding payments a few milliseconds after the hour. Grouping by day pushed the midnight payment into the next day, so new positions were credited with a payment made before they opened.", "About <b>half</b> of all funding records carry an off hour timestamp such as 00:00:00.002."],
    ["Dead contracts traded", "After a perpetual is delisted, the public archive keeps publishing flat candles with zero volume at the settlement price. The model read them as a live market.", "<b>GLMR</b> stopped trading on 2024-05-15. The first model bought it two days later and held it for over two years while spot fell 97%."],
    ["Exits priced on faith", "The watchdog that closes a position before liquidation assumed spot moved in step with the perp. It now prices both legs from their real 15 minute candles.", "At real trigger candles the gap between spot and perp ranged from <b>-47% to +29%</b>."],
    ["Squeezes skipped", "Watchdog and liquidation checks only ran on days when spot and perp agreed. Squeeze days are exactly the days they disagree.", "Checks now run on every day with a price, whatever the spread."],
    ["Stale exit prices", "When data broke, positions were closed and marked at prices from before the break, which hid the loss that followed.", "Positions now close at the prices in force on the day, or at the settlement price for a delisted perp."],
    ["Impossible orders", "Binance order minimums and quantity steps were ignored. Small early slots placed orders the exchange would have rejected.", "The BTC perp moves in steps of <b>0.001 BTC</b>, about $87 at September 2026 prices, with a $50 minimum order."],
    ["Maker fills assumed", "Perp orders were assumed to rest and fill at the maker fee. Nothing in the data proves they would have filled.", "Every order now pays the <b>taker fee</b> on both legs."],
    ["Gaps treated as exits", "A maintenance gap with no candle at midnight forced a position closed. A real bot would wait for trading to resume.", "Only a market that never trades again forces an exit now."],
    ["Future prices in funding", "Across a data gap, a funding payment was valued at the next available candle, a price from after the payment.", "Payments are valued at the price in force at that moment."],
    ["Missing September data", "Monthly spot files for September 2026 were not yet published, so every open position was force closed on the first of the month.", "The backtest now ends on <b>2026-08-31</b>, the last day both markets have data."],
  ];
  const list = $("#wound-list"), detail = $("#wound-detail");
  list.innerHTML = W.map(([t], i) => `<li><button type="button" role="option" aria-selected="${i === 1}" data-i="${i}"><span>${String(i + 1).padStart(2, "0")}</span>${t}</button></li>`).join("");
  const show = (i, animate) => {
    const [t, p, e] = W[i];
    const fill = () => { detail.innerHTML = `<h3>${t}</h3><p>${p}</p><div class="evidence">${e}</div>`; };
    if (!animate || reduce) return fill();
    detail.classList.add("swap");
    setTimeout(() => { fill(); detail.classList.remove("swap"); }, 160);
  };
  show(1, false);
  list.addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    list.querySelectorAll("button").forEach((x) => x.setAttribute("aria-selected", String(x === b)));
    show(+b.dataset.i, true);
  });
  list.addEventListener("keydown", (e) => {
    if (!["ArrowDown", "ArrowUp"].includes(e.key)) return;
    e.preventDefault();
    const bs = [...list.querySelectorAll("button")], i = bs.indexOf(document.activeElement);
    const j = Math.max(0, Math.min(bs.length - 1, i + (e.key === "ArrowDown" ? 1 : -1)));
    bs[j].focus(); bs[j].click();
  });
})();

/* ---------- chapter 4: the ledger ---------- */
(function ledger() {
  const tabs = [...document.querySelectorAll("#tabs [role=tab]")], bar = $("#tab-bar");
  const moveBar = (t) => { bar.style.setProperty("--x", t.offsetLeft + "px"); bar.style.setProperty("--w", t.offsetWidth + "px"); };
  const select = (t) => {
    tabs.forEach((x) => {
      const on = x === t; x.setAttribute("aria-selected", String(on)); x.tabIndex = on ? 0 : -1;
      const p = document.getElementById(x.getAttribute("aria-controls")); p.hidden = !on;
      if (on) { p.classList.remove("enter"); void p.offsetWidth; p.classList.add("enter"); }
    });
    moveBar(t);
  };
  tabs.forEach((t) => t.addEventListener("click", () => select(t)));
  $("#tabs").addEventListener("keydown", (e) => {
    const i = tabs.indexOf(document.activeElement); if (i < 0) return;
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") { const j = (i + (e.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length; tabs[j].focus(); select(tabs[j]); }
  });
  requestAnimationFrame(() => moveBar(tabs[0]));
  addEventListener("resize", () => moveBar(tabs.find((t) => t.getAttribute("aria-selected") === "true")));

  // profit curve
  (function curve() {
    const v = D.pnl, n = v.length, Wd = 900, Hd = 320, l = 62, r = 14, t = 14, b = 30;
    const max = Math.max(...v) * 1.08, min = Math.min(0, ...v);
    const x = (i) => l + (i / (n - 1)) * (Wd - l - r), y = (a) => t + (1 - (a - min) / (max - min)) * (Hd - t - b);
    let g = "";
    [0, 250, 500, 750, 1000].forEach((a) => { g += `<line x1="${l}" x2="${Wd - r}" y1="${y(a)}" y2="${y(a)}" stroke="var(--moss)"/><text x="${l - 10}" y="${y(a) + 4}" text-anchor="end">${usd(a)}</text>`; });
    for (let yr = 2020; yr <= 2026; yr++) { const i = Math.round((Date.UTC(yr, 0, 1) - D.start) / 864e5); if (i >= 0) g += `<text x="${x(i)}" y="${Hd - 8}" text-anchor="middle">${yr}</text>`; }
    const pts = v.map((a, i) => `${x(i).toFixed(1)},${y(a).toFixed(1)}`).join(" ");
    const el = $("#curve");
    el.innerHTML = `<svg viewBox="0 0 ${Wd} ${Hd}" role="img" aria-label="Profit after deposits rising from $0 to ${usd(D.life.pnl_usd)} between 2020 and 2026">${g}` +
      `<polygon points="${x(0)},${y(0)} ${pts} ${x(n - 1)},${y(0)}" fill="rgb(180 224 106 / 0.07)"/>` +
      `<polyline points="${pts}" fill="none" stroke="var(--necrotic)" stroke-width="2" stroke-linejoin="round"/>` +
      `<line class="xh" y1="${t}" y2="${Hd - b}" stroke="var(--lichen)" visibility="hidden"/><circle class="dot" r="4.5" fill="var(--necrotic)" stroke="var(--void)" stroke-width="2" visibility="hidden"/>` +
      `<rect x="${l}" y="${t}" width="${Wd - l - r}" height="${Hd - t - b}" fill="transparent"/></svg><div class="tip"></div>`;
    const svg = el.querySelector("svg"), tip = el.querySelector(".tip"), xh = el.querySelector(".xh"), dot = el.querySelector(".dot");
    svg.addEventListener("pointermove", (e) => {
      const rr = svg.getBoundingClientRect(), sx = (e.clientX - rr.left) * (Wd / rr.width);
      const i = Math.max(0, Math.min(n - 1, Math.round(((sx - l) / (Wd - l - r)) * (n - 1))));
      xh.setAttribute("x1", x(i)); xh.setAttribute("x2", x(i)); xh.setAttribute("visibility", "visible");
      dot.setAttribute("cx", x(i)); dot.setAttribute("cy", y(v[i])); dot.setAttribute("visibility", "visible");
      tip.innerHTML = `<b>${new Date(D.start + i * 864e5).toISOString().slice(0, 10)}</b><span>Profit ${sUsd(v[i])}</span><span>Deposited ${usd(D.deposits[i])}</span>`;
      tip.style.left = Math.min((x(i) / Wd) * rr.width + 34, rr.width - 150) + "px"; tip.style.top = "18px"; tip.classList.add("on");
    });
    svg.addEventListener("pointerleave", () => { tip.classList.remove("on"); xh.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); });
  })();

  // years
  (function years() {
    const ys = Object.entries(D.years), m = Math.max(...ys.map(([, s]) => Math.abs(s.pnl_pct))), zero = 14;
    $("#ybars").innerHTML = ys.map(([yr, s]) => {
      const w = (Math.abs(s.pnl_pct) / m) * (100 - zero), pos = s.pnl_pct >= 0;
      return `<div class="ybar"><span>${yr === "2026" ? "2026 YTD" : yr}</span><div class="track"><span class="zero" style="left:${zero}%"></span>` +
        `<i style="left:${pos ? zero : zero - w}%;width:${Math.max(w, 0.6)}%;background:${pos ? "var(--necrotic)" : "var(--ichor)"}"></i></div>` +
        `<b class="${tone(s.pnl_pct)}">${sPct(s.pnl_pct)}</b></div>`;
    }).join("");
    const row = (lab, s) => `<td>${lab}</td><td class="${tone(s.pnl_usd)}">${sUsd(s.pnl_usd)}</td><td>${pct(s.dd_pct, 2)}</td><td>${s.positions}</td><td>${pct(s.accuracy)}</td><td>${usd(s.fees)}</td><td>${usd(s.funding)}</td>`;
    $("#ytable").innerHTML = `<thead><tr><th>Year</th><th>Profit</th><th>Worst drawdown</th><th>Positions</th><th>Accuracy</th><th>Fees</th><th>Funding</th></tr></thead>` +
      `<tbody>${ys.map(([y, s]) => `<tr>${row(y === "2026" ? "2026 YTD" : y, s)}</tr>`).join("")}</tbody><tfoot><tr>${row("Lifetime", D.life)}</tr></tfoot>`;
  })();

  // coins
  (function coins() {
    const cols = [["s", "Coin"], ["pnl", "Profit"], ["ret", "Return on capital used"], ["n", "Positions"], ["acc", "Accuracy"], ["fund", "Funding"], ["days", "Days held"]];
    let key = "pnl", dir = -1;
    const fmt = { s: (v) => esc(v), pnl: (v) => sUsd(v), ret: (v) => sPct(v, 2), n: (v) => v, acc: (v) => pct(v), fund: (v) => usd(v, 2), days: (v) => v };
    const render = () => {
      const q = $("#coin-q").value.trim().toUpperCase();
      const rows = D.coins.filter((c) => !q || c.s.includes(q)).sort((a, b) => (a[key] > b[key] ? 1 : a[key] < b[key] ? -1 : 0) * dir);
      $("#ctable").innerHTML = `<thead><tr>${cols.map(([k, lab]) => `<th aria-sort="${k === key ? (dir > 0 ? "ascending" : "descending") : "none"}"><button type="button" data-k="${k}">${lab}</button></th>`).join("")}</tr></thead>` +
        `<tbody>${rows.length ? rows.map((c) => `<tr>${cols.map(([k]) => `<td class="${k === "pnl" || k === "ret" ? tone(c[k]) : ""}">${fmt[k](c[k])}</td>`).join("")}</tr>`).join("")
          : `<tr><td colspan="7">No traded coin matches "${esc(q)}". NIRU traded ${D.coins.length} of the ${D.coinsTested} coins.</td></tr>`}</tbody>`;
    };
    $("#ctable").addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; const k = b.dataset.k; dir = key === k ? -dir : (k === "s" ? 1 : -1); key = k; render(); });
    $("#coin-q").addEventListener("input", render);
    render();
  })();

  // variants
  (function variants() {
    const info = { main: "The rules this site reports", slip10: "Execution twice as costly", slip15: "Execution three times as costly", safer: "7 day lookback and a $50k liquidity floor", unfiltered: "The audited model before the two filters" };
    const name = { main: "Main", slip10: "0.10% slippage", slip15: "0.15% slippage", safer: "Safer", unfiltered: "Without filters" };
    $("#variants").innerHTML = D.variants.map((v) => `<div class="variant ${v.key === "main" ? "main" : ""}"><div><h3>${name[v.key] || v.key}</h3><p>${info[v.key] || ""}</p></div>` +
      `<div class="v"><b class="${tone(v.pnl_usd)}">${sUsd(v.pnl_usd)}</b><span>profit</span></div>` +
      `<div class="v"><b>${pct(v.accuracy)}</b><span>accuracy</span></div>` +
      `<div class="v"><b>${pct(v.dd_pct, 2)}</b><span>worst drawdown</span></div>` +
      `<div class="v"><b>${v.positions}</b><span>positions</span></div></div>`).join("");
  })();
})();
}

Promise.all([fetch("data/pulse.json"), fetch("data/results.json")])
  .then((rs) => Promise.all(rs.map((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })))
  .then(([pulse, results]) => { G = pulse; D = results; document.body.classList.remove("loading"); start(); })
  .catch(() => {
    document.body.classList.remove("loading");
    document.querySelectorAll("[data-needs-data]").forEach((el) => {
      el.innerHTML = '<p class="load-error">The results did not load. Refresh the page to try again.</p>';
    });
  });
