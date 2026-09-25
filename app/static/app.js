/* Gráficos SVG sem dependências + interações leves (ordenar, filtrar, upload).
   Os dados chegam em <script type="application/json" id="data-*">, compatível com a CSP local. */
(function () {
  "use strict";

  const NS = "http://www.w3.org/2000/svg";
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const COLORS = () => [css("--s1"), css("--s2"), css("--s3"), css("--s4"), css("--s5")];
  const MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];

  // ---------------------------------------------------------------- formatação
  const nf = (digits) => new Intl.NumberFormat("pt-BR", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  const money = (cents) => "R$ " + nf(2).format(cents / 100);
  const moneyShort = (cents) => {
    const v = Math.abs(cents / 100), sign = cents < 0 ? "−" : "";
    if (v >= 1e9) return sign + "R$ " + nf(1).format(v / 1e9) + " bi";
    if (v >= 1e6) return sign + "R$ " + nf(1).format(v / 1e6) + " mi";
    if (v >= 1e3) return sign + "R$ " + nf(v >= 1e5 ? 0 : 1).format(v / 1e3) + " mil";
    return sign + "R$ " + nf(0).format(v);
  };
  const pct = (x, d = 2) => (x > 0.000001 ? "+" : x < -0.000001 ? "−" : "") + nf(d).format(Math.abs(x * 100)) + "%";
  const pctAxis = (x) => (x > 0 ? "+" : x < 0 ? "−" : "") + nf(Math.abs(x) < 0.1 ? 1 : 0).format(Math.abs(x * 100)) + "%";
  const dayLabel = (iso) => iso.slice(8, 10) + "/" + iso.slice(5, 7) + "/" + iso.slice(2, 4);
  const monthLabel = (iso) => MONTHS[+iso.slice(5, 7) - 1] + "/" + iso.slice(2, 4);
  const toTime = (iso) => Date.parse(iso + "T12:00:00");

  const readData = (id) => {
    const node = document.getElementById(id);
    if (!node) return null;
    try { return JSON.parse(node.textContent); } catch (e) { return null; }
  };

  const el = (tag, attrs, parent) => {
    const node = document.createElementNS(NS, tag);
    for (const k in attrs) node.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(node);
    return node;
  };

  // ---------------------------------------------------------------- escalas
  function niceTicks(min, max, count) {
    if (min === max) { min -= 1; max += 1; }
    const span = max - min;
    const step0 = Math.pow(10, Math.floor(Math.log10(span / count)));
    const err = (count / span) * step0;
    const step = step0 * (err <= 0.15 ? 10 : err <= 0.35 ? 5 : err <= 0.75 ? 2 : 1);
    const lo = Math.floor(min / step) * step, hi = Math.ceil(max / step) * step;
    const ticks = [];
    for (let v = lo; v <= hi + step / 2; v += step) ticks.push(+v.toFixed(10));
    return ticks;
  }

  function timeTicks(t0, t1, width) {
    const n = Math.max(2, Math.min(6, Math.floor(width / 110)));
    const out = [];
    for (let i = 0; i < n; i++) out.push(t0 + ((t1 - t0) * i) / (n - 1));
    return out;
  }

  // ---------------------------------------------------------------- tooltip
  let tip;
  function tooltip() {
    if (!tip) {
      tip = document.createElement("div");
      tip.className = "chart-tip";
      tip.setAttribute("role", "status");
      document.body.appendChild(tip);
    }
    return tip;
  }
  function showTip(evt, title, rows) {
    const t = tooltip();
    t.replaceChildren();
    const head = document.createElement("div");
    head.className = "chart-tip-title";
    head.textContent = title;
    t.appendChild(head);
    rows.forEach((r) => {
      const line = document.createElement("div");
      line.className = "chart-tip-row";
      const key = document.createElement("span");
      if (r.color) {
        const sw = document.createElement("i");
        sw.style.background = r.color;
        key.appendChild(sw);
      }
      key.appendChild(document.createTextNode(r.label));
      const val = document.createElement("b");
      val.textContent = r.value;
      line.append(key, val);
      t.appendChild(line);
    });
    t.classList.add("on");
    const pad = 14, w = t.offsetWidth, h = t.offsetHeight;
    let x = evt.clientX + pad, y = evt.clientY + pad;
    if (x + w > window.innerWidth - 8) x = evt.clientX - w - pad;
    if (y + h > window.innerHeight - 8) y = evt.clientY - h - pad;
    t.style.left = x + "px";
    t.style.top = y + "px";
  }
  const hideTip = () => tip && tip.classList.remove("on");

  // ---------------------------------------------------------------- legenda
  function legend(container, items) {
    let box = container.parentElement.querySelector(".legend");
    if (!box) {
      box = document.createElement("div");
      box.className = "legend";
      container.parentElement.insertBefore(box, container);
    }
    box.replaceChildren();
    if (items.length < 2) return;
    items.forEach((it) => {
      const item = document.createElement("span");
      const sw = document.createElement("i");
      sw.style.background = it.color;
      if (it.line) sw.className = "line";
      item.append(sw, document.createTextNode(it.label));
      box.appendChild(item);
    });
  }

  function emptyState(container, text) {
    container.replaceChildren();
    const p = document.createElement("div");
    p.className = "chart-empty";
    p.textContent = text;
    container.appendChild(p);
  }

  // ---------------------------------------------------------------- linha / área
  /* series: [{label, color, values:[number|null], area?, stack?}], dates: [iso] */
  function lineChart(container, cfg) {
    const { dates, series, yFormat, tipFormat, refLine } = cfg;
    legend(container, series.map((s) => ({ label: s.label, color: s.color, line: !s.area })));
    if (!dates.length) return emptyState(container, cfg.empty || "Sem dados no período.");
    const W = container.clientWidth || 600, H = cfg.height || 260;
    const m = { t: 12, r: 16, b: 26, l: 64 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b;
    // empilhamento
    const stacked = series.some((s) => s.stack);
    const tops = series.map(() => []);
    const bases = series.map(() => []);
    dates.forEach((_, i) => {
      let acc = 0;
      series.forEach((s, k) => {
        const v = s.values[i];
        if (s.stack) { bases[k][i] = acc; acc += v || 0; tops[k][i] = acc; }
        else { bases[k][i] = 0; tops[k][i] = v; }
      });
    });
    let lo = Infinity, hi = -Infinity;
    tops.forEach((arr, k) => arr.forEach((v, i) => {
      if (v == null) return;
      lo = Math.min(lo, v, series[k].area || stacked ? bases[k][i] : v);
      hi = Math.max(hi, v);
    }));
    if (refLine != null) { lo = Math.min(lo, refLine.value); hi = Math.max(hi, refLine.value); }
    if (cfg.zeroBased) lo = Math.min(0, lo);
    if (!isFinite(lo)) return emptyState(container, "Sem dados no período.");
    const pad = (hi - lo) * 0.06 || Math.abs(hi) * 0.05 || 1;
    // série só positiva nunca desenha eixo negativo
    const ticks = niceTicks(cfg.zeroBased && lo >= 0 ? 0 : lo >= 0 ? Math.max(0, lo - pad) : lo - pad, hi + pad, 4);
    const y0 = ticks[0], y1 = ticks[ticks.length - 1];
    const t0 = toTime(dates[0]), t1 = toTime(dates[dates.length - 1]) || t0 + 1;
    const x = (i) => m.l + (t1 === t0 ? iw / 2 : ((toTime(dates[i]) - t0) / (t1 - t0)) * iw);
    const y = (v) => m.t + ih - ((v - y0) / (y1 - y0)) * ih;

    container.replaceChildren();
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: "chart-svg", role: "img", "aria-label": cfg.aria || "Gráfico" }, container);
    const grid = el("g", { class: "grid" }, svg);
    ticks.forEach((v) => {
      el("line", { x1: m.l, x2: W - m.r, y1: y(v), y2: y(v), class: v === 0 && y0 < 0 ? "zero" : "" }, grid);
      el("text", { x: m.l - 10, y: y(v) + 4, "text-anchor": "end", class: "tick" }, grid).textContent = yFormat(v);
    });
    const span = (t1 - t0) / 864e5;
    timeTicks(t0, t1, iw).forEach((t) => {
      const iso = new Date(t).toISOString().slice(0, 10);
      const px = m.l + (t1 === t0 ? iw / 2 : ((t - t0) / (t1 - t0)) * iw);
      el("text", { x: px, y: H - 6, "text-anchor": "middle", class: "tick" }, grid).textContent =
        cfg.xFormat ? cfg.xFormat(iso) : span > 120 ? monthLabel(iso) : dayLabel(iso).slice(0, 5);
    });

    const draw = el("g", {}, svg);
    series.forEach((s, k) => {
      let d = "", area = "", started = false, firstI = -1, lastI = -1;
      tops[k].forEach((v, i) => {
        if (v == null) { started = false; return; }
        d += (started ? "L" : "M") + x(i).toFixed(1) + "," + y(v).toFixed(1);
        if (firstI < 0) firstI = i;
        lastI = i;
        started = true;
      });
      if (s.area && firstI >= 0) {
        area = d;
        for (let i = lastI; i >= firstI; i--) area += "L" + x(i).toFixed(1) + "," + y(stacked ? bases[k][i] : Math.max(y0, 0)).toFixed(1);
        el("path", { d: area + "Z", fill: s.color, "fill-opacity": stacked ? 0.22 : 0.1, stroke: "none" }, draw);
      }
      el("path", { d, fill: "none", stroke: s.color, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }, draw);
      if (lastI >= 0 && dates.length > 1) {
        el("circle", { cx: x(lastI), cy: y(tops[k][lastI]), r: 4, fill: s.color, class: "end-dot" }, draw);
      }
    });
    if (refLine != null) {
      el("line", { x1: m.l, x2: W - m.r, y1: y(refLine.value), y2: y(refLine.value), class: "ref-line" }, draw);
      const label = el("text", { x: W - m.r - 4, y: y(refLine.value) - 6, "text-anchor": "end", class: "ref-label" }, draw);
      label.textContent = refLine.label;
    }

    // camada de hover: cruz + pontos + tooltip
    const hover = el("g", { class: "hover", visibility: "hidden" }, svg);
    const cross = el("line", { y1: m.t, y2: m.t + ih, class: "crosshair" }, hover);
    const dots = series.map((s) => el("circle", { r: 4, fill: s.color, class: "end-dot" }, hover));
    const hit = el("rect", { x: m.l, y: m.t, width: iw, height: ih, fill: "transparent" }, svg);
    const move = (evt) => {
      const box = svg.getBoundingClientRect();
      const px = ((evt.clientX - box.left) / box.width) * W;
      const t = t0 + ((px - m.l) / iw) * (t1 - t0);
      let i = 0, best = Infinity;
      dates.forEach((d, j) => { const dist = Math.abs(toTime(d) - t); if (dist < best) { best = dist; i = j; } });
      hover.setAttribute("visibility", "visible");
      cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i));
      series.forEach((s, k) => {
        const v = tops[k][i];
        dots[k].setAttribute("visibility", v == null ? "hidden" : "visible");
        if (v != null) { dots[k].setAttribute("cx", x(i)); dots[k].setAttribute("cy", y(v)); }
      });
      const rows = series.map((s) => ({ label: s.label, color: s.color, value: s.values[i] == null ? "—" : (tipFormat || yFormat)(s.values[i]) }));
      if (cfg.tipExtra) rows.push(...cfg.tipExtra(i));
      showTip(evt, cfg.titleFormat ? cfg.titleFormat(dates[i], i) : dayLabel(dates[i]), rows);
    };
    hit.addEventListener("pointermove", move);
    hit.addEventListener("pointerleave", () => { hover.setAttribute("visibility", "hidden"); hideTip(); });
  }

  // ---------------------------------------------------------------- colunas agrupadas (aceita negativos)
  function columnChart(container, cfg) {
    const { labels, series, yFormat } = cfg;
    legend(container, series);
    if (!labels.length) return emptyState(container, cfg.empty || "Sem dados no período.");
    const W = container.clientWidth || 600, H = cfg.height || 240;
    const m = { t: 12, r: 12, b: 26, l: 64 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b;
    let lo = 0, hi = 0;
    series.forEach((s) => s.values.forEach((v) => { if (v != null) { lo = Math.min(lo, v); hi = Math.max(hi, v); } }));
    if (cfg.refLine) { lo = Math.min(lo, cfg.refLine.value); hi = Math.max(hi, cfg.refLine.value); }
    const ticks = niceTicks(lo, hi || 1, 4);
    const y0 = ticks[0], y1 = ticks[ticks.length - 1];
    const y = (v) => m.t + ih - ((v - y0) / (y1 - y0)) * ih;
    const band = iw / labels.length;
    const barW = Math.min(24, (band * 0.7) / series.length);
    const gap = 2;

    container.replaceChildren();
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: "chart-svg", role: "img", "aria-label": cfg.aria || "Gráfico" }, container);
    const grid = el("g", { class: "grid" }, svg);
    ticks.forEach((v) => {
      el("line", { x1: m.l, x2: W - m.r, y1: y(v), y2: y(v), class: v === 0 ? "zero" : "" }, grid);
      el("text", { x: m.l - 10, y: y(v) + 4, "text-anchor": "end", class: "tick" }, grid).textContent = yFormat(v);
    });
    const every = Math.ceil(labels.length / Math.max(2, Math.floor(iw / 56)));
    labels.forEach((lab, i) => {
      if (i % every) return;
      el("text", { x: m.l + band * i + band / 2, y: H - 6, "text-anchor": "middle", class: "tick" }, grid).textContent = cfg.labelFormat ? cfg.labelFormat(lab) : lab;
    });
    const groupW = barW * series.length + gap * (series.length - 1);
    labels.forEach((lab, i) => {
      const gx = m.l + band * i + (band - groupW) / 2;
      const hitRect = el("rect", { x: m.l + band * i, y: m.t, width: band, height: ih, fill: "transparent", class: "col-hit" }, svg);
      series.forEach((s, k) => {
        const v = s.values[i];
        if (v == null || v === 0) return;
        const top = y(Math.max(v, 0)), bottom = y(Math.min(v, 0));
        const h = Math.max(1, bottom - top), bx = gx + k * (barW + gap);
        const r = Math.min(4, h / 2, barW / 2);
        const color = s.colorFor ? s.colorFor(v, i) : s.color;
        // canto arredondado só na ponta do dado; base reta no eixo
        const path = v >= 0
          ? `M${bx},${bottom}V${top + r}Q${bx},${top} ${bx + r},${top}H${bx + barW - r}Q${bx + barW},${top} ${bx + barW},${top + r}V${bottom}Z`
          : `M${bx},${top}V${bottom - r}Q${bx},${bottom} ${bx + r},${bottom}H${bx + barW - r}Q${bx + barW},${bottom} ${bx + barW},${bottom - r}V${top}Z`;
        el("path", { d: path, fill: color, class: "bar" }, svg);
      });
      hitRect.addEventListener("pointermove", (evt) => {
        showTip(evt, cfg.labelFormat ? cfg.labelFormat(lab) : lab, series.map((s) => ({
          label: s.label, color: s.colorFor ? null : s.color, value: s.values[i] == null ? "—" : (cfg.tipFormat || yFormat)(s.values[i]),
        })).concat(cfg.tipExtra ? cfg.tipExtra(i) : []));
      });
      hitRect.addEventListener("pointerleave", hideTip);
      svg.appendChild(hitRect);
    });
    if (cfg.refLine) {
      const ry = y(cfg.refLine.value);
      el("line", { x1: m.l, x2: W - m.r, y1: ry, y2: ry, class: "ref-line", "pointer-events": "none" }, svg);
      el("text", { x: W - m.r - 4, y: ry - 6, "text-anchor": "end", class: "ref-label", "pointer-events": "none" }, svg).textContent = cfg.refLine.label;
    }
  }

  // ---------------------------------------------------------------- seleção de período
  function rangeStart(lastIso, key, firstIso) {
    const d = new Date(lastIso + "T12:00:00");
    if (key === "1M") d.setMonth(d.getMonth() - 1);
    else if (key === "3M") d.setMonth(d.getMonth() - 3);
    else if (key === "6M") d.setMonth(d.getMonth() - 6);
    else if (key === "12M") d.setFullYear(d.getFullYear() - 1);
    else if (key === "YTD") return lastIso.slice(0, 4) + "-01-01";
    else return firstIso;
    return d.toISOString().slice(0, 10);
  }

  function withRange(chartEl, render) {
    const card = chartEl.closest(".card");
    const control = card && card.querySelector(".seg");
    let current = control ? (control.querySelector("[aria-pressed=true]") || {}).dataset?.range || "12M" : "ALL";
    const redraw = () => render(current);
    if (control) {
      control.addEventListener("click", (evt) => {
        const btn = evt.target.closest("button[data-range]");
        if (!btn) return;
        current = btn.dataset.range;
        control.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", b === btn ? "true" : "false"));
        redraw();
      });
    }
    let width = chartEl.clientWidth;
    new ResizeObserver(() => { if (Math.abs(chartEl.clientWidth - width) > 4) { width = chartEl.clientWidth; redraw(); } }).observe(chartEl);
    redraw();
  }

  // ---------------------------------------------------------------- gráficos da aplicação
  const charts = {
    "net-worth"(node) {
      const data = readData("data-net-worth") || [];
      const [c1, c2, c3] = COLORS();
      withRange(node, (range) => {
        const first = data.length ? data[0].d : "";
        const start = data.length ? rangeStart(data[data.length - 1].d, range, first) : "";
        const rows = data.filter((p) => p.d >= start);
        lineChart(node, {
          dates: rows.map((p) => p.d), yFormat: moneyShort, tipFormat: money, aria: "Evolução do patrimônio", zeroBased: true,
          empty: "Importe extratos ou posições para ver a evolução.",
          series: [
            { label: "Renda variável", color: c1, values: rows.map((p) => p.eq), area: true, stack: true },
            { label: "Renda fixa", color: c2, values: rows.map((p) => p.fi), area: true, stack: true },
            ...(rows.some((p) => p.pv) ? [{ label: "Previdência", color: COLORS()[3], values: rows.map((p) => p.pv || 0), area: true, stack: true }] : []),
            { label: "Caixa", color: c3, values: rows.map((p) => p.cash), area: true, stack: true },
          ],
          tipExtra: (i) => [
            ...(rows[i].debt ? [{ label: "Cartão (dívida)", value: money(rows[i].debt) }] : []),
            { label: "Total", value: money(rows[i].nw) },
          ],
        });
      });
    },

    "cash-flow"(node) {
      const data = readData("data-cash-flow") || [];
      // receita e despesa usam as cores de sentido da marca: verde entra, vermelho sai
      const [c1, c2] = [css("--up"), css("--down")];
      withRange(node, () => columnChart(node, {
        labels: data.map((r) => r.m), labelFormat: (m) => monthLabel(m + "-01"),
        yFormat: moneyShort, tipFormat: money, aria: "Receitas e despesas por mês",
        empty: "Importe o extrato da conta ou a fatura para ver o fluxo.",
        series: [
          { label: "Receitas", color: c1, values: data.map((r) => r.in) },
          { label: "Despesas", color: c2, values: data.map((r) => r.out) },
        ],
        tipExtra: (i) => [{ label: "Saldo", value: money(data[i].net) }],
      }));
    },

    returns(node) {
      const data = readData("data-returns") || { series: [], cdi: [], ibov: [] };
      const [c1, c2, c3] = COLORS();
      const cdi = new Map(data.cdi), ibovDates = data.ibov.map((r) => r[0]), ibovVals = data.ibov.map((r) => r[1]);
      const ibovAt = (d) => { let lo = 0, hi = ibovDates.length - 1, ans = null; while (lo <= hi) { const mid = (lo + hi) >> 1; if (ibovDates[mid] <= d) { ans = ibovVals[mid]; lo = mid + 1; } else hi = mid - 1; } return ans; };
      const cdiDates = data.cdi.map((r) => r[0]);
      withRange(node, (range) => {
        const s = data.series;
        if (!s.length) return lineChart(node, { dates: [], series: [], yFormat: pctAxis, empty: "Sem histórico de cotações ainda. Atualize o mercado." });
        const start = rangeStart(s[s.length - 1].d, range, s[0].d);
        const rows = s.filter((p) => p.d > start);
        let acc = 1, cdiAcc = 1, ci = cdiDates.findIndex((d) => d > start);
        if (ci < 0) ci = cdiDates.length;
        const ibov0 = ibovAt(start) || ibovAt(rows.length ? rows[0].d : start);
        const port = [], bench = [], ib = [];
        rows.forEach((p) => {
          acc *= 1 + p.r;
          while (ci < cdiDates.length && cdiDates[ci] <= p.d) { cdiAcc *= 1 + cdi.get(cdiDates[ci]) / 100; ci++; }
          port.push(acc - 1);
          bench.push(cdiDates.length ? cdiAcc - 1 : null);
          const iv = ibovAt(p.d);
          ib.push(ibov0 && iv ? iv / ibov0 - 1 : null);
        });
        const series = [{ label: "Carteira", color: c1, values: port }];
        if (bench.some((v) => v != null)) series.push({ label: "CDI", color: c2, values: bench });
        if (ib.some((v) => v != null)) series.push({ label: "Ibovespa", color: c3, values: ib });
        lineChart(node, { dates: rows.map((p) => p.d), series, yFormat: pctAxis, tipFormat: (v) => pct(v), aria: "Rentabilidade acumulada" });
      });
    },

    "invested"(node) {
      const data = readData("data-invested") || [];
      const [c1, c2] = COLORS();
      withRange(node, (range) => {
        const start = data.length ? rangeStart(data[data.length - 1].d, range, data[0].d) : "";
        const rows = data.filter((p) => p.d >= start);
        lineChart(node, {
          dates: rows.map((p) => p.d), yFormat: moneyShort, tipFormat: money, zeroBased: true, aria: "Valor de mercado e capital aplicado",
          series: [
            { label: "Valor de mercado", color: c1, values: rows.map((p) => p.eq), area: true },
            { label: "Capital aplicado", color: c2, values: rows.map((p) => p.cap) },
          ],
          tipExtra: (i) => [{ label: "Resultado", value: money(rows[i].eq - rows[i].cap) }],
        });
      });
    },

    quarters(node) {
      const data = readData("data-quarters") || [];
      const [c1, c2] = COLORS();
      withRange(node, () => columnChart(node, {
        labels: data.map((r) => r.m), yFormat: moneyShort, tipFormat: money, aria: "Receita e lucro por trimestre",
        empty: "Sem demonstrações da CVM para esta empresa.",
        series: [
          ...(data.some((r) => r.revenue != null) ? [{ label: "Receita", color: c1, values: data.map((r) => r.revenue) }] : []),
          { label: "Lucro líquido", color: c2, values: data.map((r) => r.net_income) },
        ],
      }));
    },

    income(node) {
      const data = readData("data-income") || [];
      const [c1, c2] = COLORS();
      withRange(node, () => columnChart(node, {
        labels: data.map((r) => r.m), labelFormat: (m) => monthLabel(m + "-01"),
        yFormat: moneyShort, tipFormat: money, aria: "Proventos e rendimento do CDI por mês",
        empty: "Sem proventos ou saldo rendendo no período.",
        series: [
          { label: "Proventos", color: c1, values: data.map((r) => r.prov) },
          { label: "Rendimento CDI", color: c2, values: data.map((r) => r.cdi) },
        ],
        tipExtra: (i) => [{ label: "Total", value: money(data[i].prov + data[i].cdi) }],
      }));
    },

    pension(node) {
      const data = readData("data-pension") || [];
      const [c1, c2] = COLORS();
      withRange(node, (range) => {
        const start = data.length ? rangeStart(data[data.length - 1].d, range, data[0].d) : "";
        const rows = data.filter((p) => p.d >= start);
        const series = [{ label: "Saldo", color: c1, values: rows.map((p) => p.eq), area: true }];
        if (rows.some((p) => p.cap != null)) series.push({ label: "Contribuído", color: c2, values: rows.map((p) => p.cap) });
        lineChart(node, {
          dates: rows.map((p) => p.d), yFormat: moneyShort, tipFormat: money, zeroBased: true, aria: "Saldo da previdência",
          empty: "Lance dois ou mais extratos para ver a evolução.", series,
          tipExtra: (i) => (rows[i].cap != null ? [{ label: "Rendimento", value: money(rows[i].eq - rows[i].cap) }] : []),
        });
      });
    },

    monthly(node) {
      const data = readData("data-monthly") || [];
      const [c1, c2] = COLORS();
      const series = [{ label: "Carteira", color: c1, values: data.map((r) => r.r) }];
      if (data.some((r) => r.cdi != null)) series.push({ label: "CDI", color: c2, values: data.map((r) => r.cdi) });
      withRange(node, () => columnChart(node, {
        labels: data.map((r) => r.m), labelFormat: (m) => monthLabel(m + "-01"), yFormat: pctAxis, tipFormat: (v) => pct(v),
        series, aria: "Rentabilidade mensal", empty: "Sem meses completos ainda.",
      }));
    },

    "category-monthly"(node) {
      const data = readData("data-category");
      if (!data) return;
      const rows = data.months, last = rows.length - 1;
      const [c1, c2] = COLORS();
      withRange(node, () => columnChart(node, {
        labels: rows.map((r) => r.m), labelFormat: (m) => monthLabel(m + "-01"),
        yFormat: moneyShort, tipFormat: money, aria: "Gasto da categoria por mês", height: 320,
        series: [{ label: "Gasto", color: c2, values: rows.map((r) => r.v), colorFor: (v, i) => (i === last ? c1 : c2) }],
        refLine: data.avg > 0 ? { value: data.avg, label: "Média " + moneyShort(data.avg) } : null,
        tipExtra: (i) => [
          ...(i === last ? [{ label: "Mês corrente", value: "incompleto" }] : []),
          ...(data.avg > 0 ? [{ label: "vs média", value: pct(rows[i].v / data.avg - 1, 0) }] : []),
        ],
      }));
    },

    "category-pace"(node) {
      const data = readData("data-category");
      if (!data) return;
      const p = data.pace, [c1, c2, , , c5] = COLORS();
      const dates = Array.from({ length: p.days }, (_, i) => p.month + "-" + String(i + 1).padStart(2, "0"));
      const series = [{ label: "Este mês", color: c1, values: p.current, area: true }];
      if (p.previous.length) series.push({ label: "Mês passado", color: c2, values: p.previous });
      if (p.average.length) series.push({ label: "Média 3 meses", color: c5, values: p.average });
      withRange(node, () => lineChart(node, {
        dates, series, yFormat: moneyShort, tipFormat: money, zeroBased: true, aria: "Gasto acumulado no mês",
        xFormat: (iso) => "dia " + +iso.slice(8, 10), titleFormat: (iso) => "Dia " + +iso.slice(8, 10),
      }));
    },

    "category-weekday"(node) {
      const data = readData("data-category");
      if (!data) return;
      const w = data.weekday, [, , c3] = COLORS();
      withRange(node, () => columnChart(node, {
        labels: w.labels, yFormat: moneyShort, tipFormat: money, aria: "Gasto por dia da semana",
        series: [{ label: "Gasto", color: c3, values: w.values }],
        tipExtra: (i) => [
          { label: "Compras", value: String(w.counts[i]) },
          { label: "Ticket médio", value: w.counts[i] ? money(Math.round(w.values[i] / w.counts[i])) : "—" },
        ],
      }));
    },

    price(node) {
      const data = readData("data-price") || { prices: [] };
      const [c1] = COLORS();
      withRange(node, (range) => {
        const p = data.prices;
        const start = p.length ? rangeStart(p[p.length - 1].d, range, p[0].d) : "";
        const rows = p.filter((r) => r.d >= start);
        lineChart(node, {
          dates: rows.map((r) => r.d), yFormat: (v) => "R$ " + nf(v >= 10000 ? 0 : 2).format(v / 100), tipFormat: money, aria: "Preço de fechamento",
          series: [{ label: "Fechamento", color: c1, values: rows.map((r) => r.v), area: true }],
          refLine: data.avg ? { value: data.avg, label: "Preço médio " + money(data.avg) } : null,
          empty: "Sem cotações. Use “Atualizar mercado”.",
        });
      });
    },
  };

  // ---------------------------------------------------------------- barras horizontais (larguras via CSSOM)
  function bars() {
    document.querySelectorAll("[data-left]").forEach((node) => {
      node.style.left = Math.max(0, Math.min(100, parseFloat(node.dataset.left) || 0)) + "%";
    });
    document.querySelectorAll("[data-w]").forEach((node) => {
      node.style.width = Math.max(0.5, Math.min(100, parseFloat(node.dataset.w) || 0)) + "%";
    });
  }

  // ---------------------------------------------------------------- tabelas: ordenar e filtrar
  function sortable() {
    document.querySelectorAll("table[data-sortable]").forEach((table) => {
      const heads = table.querySelectorAll("th[data-sort]");
      heads.forEach((th, index) => {
        th.tabIndex = 0;
        const run = () => {
          const col = Array.from(th.parentElement.children).indexOf(th);
          const numeric = th.dataset.sort === "num";
          const dir = th.getAttribute("aria-sort") === "descending" ? 1 : -1;
          heads.forEach((h) => h.removeAttribute("aria-sort"));
          th.setAttribute("aria-sort", dir === 1 ? "ascending" : "descending");
          const body = table.tBodies[0];
          Array.from(body.rows)
            .sort((a, b) => {
              const va = a.cells[col].dataset.v ?? a.cells[col].textContent.trim();
              const vb = b.cells[col].dataset.v ?? b.cells[col].textContent.trim();
              if (numeric) {
                const na = va === "" ? -Infinity : parseFloat(va), nb = vb === "" ? -Infinity : parseFloat(vb);
                return (na - nb) * dir;
              }
              return va.localeCompare(vb, "pt-BR") * dir;
            })
            .forEach((row) => body.appendChild(row));
        };
        th.addEventListener("click", run);
        th.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); run(); } });
        void index;
      });
    });
    document.querySelectorAll("input[data-filter]").forEach((input) => {
      const table = document.getElementById(input.dataset.filter);
      const select = document.querySelector(`select[data-filter-for="${input.dataset.filter}"]`);
      const apply = () => {
        const q = input.value.trim().toLowerCase();
        const cat = select ? select.value : "";
        let shown = 0;
        Array.from(table.tBodies[0].rows).forEach((row) => {
          const ok = (!q || row.textContent.toLowerCase().includes(q)) && (!cat || row.dataset.cat === cat);
          row.hidden = !ok;
          if (ok) shown++;
        });
        const counter = document.querySelector(`[data-count-for="${input.dataset.filter}"]`);
        if (counter) counter.textContent = shown + " lançamentos";
      };
      input.addEventListener("input", apply);
      if (select) select.addEventListener("change", apply);
    });
  }

  // ---------------------------------------------------------------- upload
  function dropzone() {
    document.querySelectorAll(".dropzone").forEach((zone) => {
      const input = zone.querySelector("input[type=file]");
      const list = zone.querySelector(".dropzone-files");
      const submit = zone.closest("form").querySelector("button[type=submit]");
      const render = () => {
        list.replaceChildren();
        Array.from(input.files).forEach((f) => {
          const li = document.createElement("li");
          li.textContent = f.name;
          list.appendChild(li);
        });
        zone.classList.toggle("has-files", input.files.length > 0);
        if (submit) submit.disabled = input.files.length === 0;
      };
      ["dragenter", "dragover"].forEach((t) => zone.addEventListener(t, (e) => { e.preventDefault(); zone.classList.add("drag"); }));
      ["dragleave", "drop"].forEach((t) => zone.addEventListener(t, (e) => { e.preventDefault(); zone.classList.remove("drag"); }));
      zone.addEventListener("drop", (e) => { input.files = e.dataTransfer.files; render(); });
      input.addEventListener("change", render);
      render();
    });
  }

  function busyForms() {
    document.querySelectorAll("form[data-busy]").forEach((form) => {
      form.addEventListener("submit", () => {
        const btn = form.querySelector("button[type=submit]");
        if (btn) { btn.disabled = true; btn.dataset.label = btn.textContent; btn.textContent = form.dataset.busy; }
      });
    });
  }

  // ---------------------------------------------------------------- manter a rolagem depois de salvar
  /* Todo formulário POST volta para a mesma página por redirecionamento, que abriria no topo (ou na âncora).
     Guarda a posição ao enviar e restaura ao voltar para o mesmo caminho; o aviso vira um toast fixo. */
  const SCROLL_KEY = "tabimoney:scroll";
  function keepScroll() {
    // pede confirmação antes de ações destrutivas; registrado antes para cancelar e não gravar a rolagem
    document.addEventListener("submit", (evt) => {
      const message = evt.target && evt.target.dataset ? evt.target.dataset.confirm : null;
      if (message && !window.confirm(message)) evt.preventDefault();
    });
    document.addEventListener("submit", (evt) => {
      const form = evt.target;
      if (!form || (form.getAttribute("method") || "").toLowerCase() !== "post" || evt.defaultPrevented) return;
      try { sessionStorage.setItem(SCROLL_KEY, JSON.stringify({ path: location.pathname, y: window.scrollY, t: Date.now() })); } catch (e) { /* sem storage */ }
    });
    let saved = null;
    try { saved = JSON.parse(sessionStorage.getItem(SCROLL_KEY) || "null"); sessionStorage.removeItem(SCROLL_KEY); } catch (e) { saved = null; }
    if (!saved || saved.path !== location.pathname || Date.now() - saved.t > 120000) return;
    const flashes = document.querySelector(".flash-stack");
    if (flashes && saved.y > 80) flashes.classList.add("toast");
    const restore = () => window.scrollTo({ top: saved.y, behavior: "instant" });
    restore();
    requestAnimationFrame(restore);
    // a âncora do redirecionamento (#orcamento) rola a página no load; restaura depois dela
    window.addEventListener("load", () => { restore(); setTimeout(restore, 30); }, { once: true });
  }

  document.addEventListener("DOMContentLoaded", () => {
    keepScroll();
    bars();
    sortable();
    dropzone();
    busyForms();
    document.querySelectorAll("[data-chart]").forEach((node) => {
      const fn = charts[node.dataset.chart];
      if (fn) fn(node);
    });
    // trocar a categoria de um lançamento envia o formulário da linha
    document.querySelectorAll("select[data-autosubmit]").forEach((select) => {
      select.addEventListener("change", () => select.form && select.form.requestSubmit());
    });
    document.querySelectorAll("select[data-navigate]").forEach((select) => {
      select.addEventListener("change", () => { if (select.value.startsWith("/")) location.href = select.value; });
    });
  });
})();
