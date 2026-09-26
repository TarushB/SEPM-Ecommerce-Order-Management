/* Olist DBMS front end - plain JavaScript, no build step.
   Every API response carries the SQL the server executed; it is shown in the
   right-hand "SQL executed" panel:  Front End -> SQL -> Database -> Result. */
"use strict";

const S = { user: null, meta: null, sqlCollapsed: false, cache: {} };
const $ = (sel, root = document) => root.querySelector(sel);
const esc = v => v === null || v === undefined ? "" : String(v)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
const fmtNum = (v, d = 0) => v === null || v === undefined || v === "" ? "" :
  Number(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
const money = v => v === null || v === undefined ? "" : "R$ " + fmtNum(v, 2);
const shortId = id => id ? `<span class="id" title="${esc(id)}">${esc(String(id).slice(0, 8))}…</span>` : "";
const can = (...roles) => S.user && roles.includes(S.user.app_role);

/* ------------------------------------------------------------------ API */
async function api(method, url, body, opts = {}) {
  setFlow(1);
  let j;
  try {
    const r = await fetch(url, { method, headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined, credentials: "same-origin" });
    j = await r.json();
    if (r.status === 401 && url !== "/api/login") { S.user = null; renderLogin(); return j; }
  } catch (e) {
    j = { ok: false, error: "Cannot reach the server: " + e.message, queries: [] };
  }
  if (j.queries && j.queries.length) showQueries(j.queries, url, method);
  setFlow(j.ok ? 4 : 0);
  if (!j.ok && !opts.quiet) toast(j.error || "Request failed", "bad");
  return j;
}
const GET = (u, o) => api("GET", u, null, o);
const POST = (u, b, o) => api("POST", u, b || {}, o);
const PUT = (u, b, o) => api("PUT", u, b || {}, o);
const DEL = (u, o) => api("DELETE", u, null, o);
const qs = obj => Object.entries(obj).filter(([, v]) => v !== "" && v !== null && v !== undefined)
  .map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&");

function toast(msg, kind = "") {
  const t = document.createElement("div");
  t.className = "toast " + kind; t.textContent = msg; document.body.appendChild(t);
  setTimeout(() => t.remove(), kind === "bad" ? 6000 : 3000);
}

/* ------------------------------------------------------------------ SQL panel */
const SQL_KW = "SELECT|FROM|WHERE|AND|OR|NOT|IN|IS|NULL|JOIN|LEFT|RIGHT|INNER|OUTER|FULL|CROSS|LATERAL|ON|AS|GROUP|BY|ORDER|HAVING|LIMIT|OFFSET|INSERT|INTO|VALUES|UPDATE|SET|DELETE|RETURNING|CALL|WITH|RECURSIVE|UNION|ALL|INTERSECT|EXCEPT|DISTINCT|CASE|WHEN|THEN|ELSE|END|EXISTS|BETWEEN|LIKE|ASC|DESC|NULLS|LAST|FIRST|BEGIN|COMMIT|ROLLBACK|SAVEPOINT|TO|LOCAL|ROLE|EXPLAIN|ANALYZE|OVER|PARTITION|FILTER|CONFLICT|DO|COUNT|SUM|AVG|MIN|MAX|ROUND|COALESCE|RANK|NTILE|LAG|ANY|FOR|TRANSACTION|ISOLATION|LEVEL|READ|COMMITTED|REPEATABLE|ONLY";
const SQL_RE = new RegExp(`('(?:[^']|'')*')|(--[^\\n]*)|\\b(\\d+(?:\\.\\d+)?)\\b|\\b(${SQL_KW})\\b`, "gi");
function hl(sql) {
  let out = "", last = 0;
  String(sql).replace(SQL_RE, (m, str, cm, num, kw, idx) => {
    out += esc(sql.slice(last, idx));
    out += str ? `<span class="st">${esc(str)}</span>` : cm ? `<span class="cm">${esc(cm)}</span>`
      : num ? `<span class="nu">${num}</span>` : `<span class="kw">${esc(kw.toUpperCase())}</span>`;
    last = idx + m.length; return m;
  });
  return out + esc(String(sql).slice(last));
}
function setFlow(step) {
  document.querySelectorAll(".flow span").forEach((el, i) => el.classList.toggle("on", step > 0 && i < step));
}
function showQueries(queries, url, method) {
  const list = $("#sql-list"); if (!list) return;
  list.innerHTML = `<div class="small" style="color:#94a3b8;margin:0 2px 8px">${esc(method)} ${esc(url.split("?")[0])} ·
    ${queries.length} statement${queries.length === 1 ? "" : "s"} in one transaction</div>` +
    queries.map(q => `<div class="sql-item ${q.error ? "error" : ""}">
      <div class="meta"><span class="lbl">${esc(q.label || "statement")}</span>
      <span>${q.ms !== null && q.ms !== undefined ? q.ms + " ms" : ""}</span></div>
      <pre>${hl(q.sql || "")}</pre>
      ${q.error ? `<div class="err">ERROR${q.sqlstate ? " " + esc(q.sqlstate) : ""}: ${esc(q.error)}</div>`
        : (q.row_count !== null && q.row_count !== undefined && !["end", "session setup", "savepoint", "rollback to savepoint"].includes(q.label)
          ? `<div class="res">→ ${fmtNum(q.row_count)} row${q.row_count === 1 ? "" : "s"}</div>` : "")}
    </div>`).join("");
  list.scrollTop = 0;
}
function toggleSql() {
  S.sqlCollapsed = !S.sqlCollapsed;
  $(".app").classList.toggle("sql-collapsed", S.sqlCollapsed);
  $("#sql-toggle").textContent = S.sqlCollapsed ? "SQL ◂" : "Hide ▸";
}

/* ------------------------------------------------------------------ tables & charts */
function table(rows, cols, opts = {}) {
  if (!rows || !rows.length) return `<div class="empty">${opts.empty || "No rows"}</div>`;
  cols = cols || Object.keys(rows[0]).map(k => ({ key: k }));
  const isNum = v => typeof v === "number";
  return `<div class="table-wrap"><table><thead><tr>${cols.map(c =>
    `<th class="${c.num ? "num" : ""}">${esc(c.label ?? c.key)}</th>`).join("")}</tr></thead><tbody>${
    rows.map((r, i) => `<tr ${opts.onRow ? `class="clickable" onclick="${opts.onRow(r, i)}"` : ""}>${cols.map(c => {
      const v = r[c.key];
      const html = c.render ? c.render(v, r) : (isNum(v) ? fmtNum(v, Number.isInteger(v) ? 0 : 2) :
        (typeof v === "string" && /^[0-9a-f]{32}$/.test(v) ? shortId(v) : esc(v)));
      return `<td class="${c.num || isNum(v) ? "num" : ""}">${html}</td>`;
    }).join("")}</tr>`).join("")}</tbody></table></div>`;
}
function genericTable(res) {  // {columns, rows}
  if (!res) return "";
  return table(res.rows, res.columns.map(c => ({ key: c })));
}
function lineChart(data, x, y, { height = 220, fmt = v => fmtNum(v) } = {}) {
  if (!data.length) return "";
  const W = 720, H = height, P = { l: 58, r: 12, t: 12, b: 34 };
  const max = Math.max(...data.map(d => +d[y])) * 1.1 || 1;
  const sx = i => P.l + i * (W - P.l - P.r) / Math.max(data.length - 1, 1);
  const sy = v => H - P.b - (v / max) * (H - P.t - P.b);
  const pts = data.map((d, i) => `${sx(i)},${sy(+d[y])}`).join(" ");
  const ticks = [0, .25, .5, .75, 1].map(f => max * f);
  const step = Math.ceil(data.length / 10);
  return `<svg class="chart" viewBox="0 0 ${W} ${H}">
    ${ticks.map(t => `<line class="grid" x1="${P.l}" x2="${W - P.r}" y1="${sy(t)}" y2="${sy(t)}"/>
      <text x="${P.l - 6}" y="${sy(t) + 4}" text-anchor="end">${fmt(t)}</text>`).join("")}
    <polygon class="area" points="${P.l},${H - P.b} ${pts} ${sx(data.length - 1)},${H - P.b}"/>
    <polyline class="line" points="${pts}"/>
    ${data.map((d, i) => i % step === 0 ? `<text x="${sx(i)}" y="${H - 12}" text-anchor="middle">${esc(d[x])}</text>` : "").join("")}
    ${data.map((d, i) => `<circle cx="${sx(i)}" cy="${sy(+d[y])}" r="2.5" fill="var(--accent)"><title>${esc(d[x])}: ${fmt(+d[y])}</title></circle>`).join("")}
  </svg>`;
}
function hbar(data, label, value, { fmt = v => fmtNum(v), width = 460 } = {}) {
  if (!data.length) return "";
  const rowH = 24, P = 150, H = data.length * rowH + 8, max = Math.max(...data.map(d => +d[value])) || 1;
  return `<svg class="chart" viewBox="0 0 ${width} ${H}">${data.map((d, i) => {
    const w = (+d[value] / max) * (width - P - 90);
    return `<text x="${P - 8}" y="${i * rowH + 16}" text-anchor="end">${esc(d[label])}</text>
      <rect class="bar" x="${P}" y="${i * rowH + 4}" width="${Math.max(w, 1)}" height="${rowH - 8}" rx="3"><title>${esc(d[label])}: ${fmt(+d[value])}</title></rect>
      <text x="${P + w + 6}" y="${i * rowH + 16}">${fmt(+d[value])}</text>`;
  }).join("")}</svg>`;
}
function vbars(data, label, series, { height = 200, colors = ["bar", "bar alt"], fmt = v => fmtNum(v) } = {}) {
  if (!data.length) return "";
  const W = 460, H = height, P = { l: 44, r: 10, t: 10, b: 26 };
  const max = Math.max(...data.flatMap(d => series.map(s => +d[s] || 0))) * 1.1 || 1;
  const gw = (W - P.l - P.r) / data.length, bw = Math.min(40, (gw - 8) / series.length);
  const sy = v => H - P.b - (v / max) * (H - P.t - P.b);
  return `<svg class="chart" viewBox="0 0 ${W} ${H}">
    ${[0, .5, 1].map(f => `<line class="grid" x1="${P.l}" x2="${W - P.r}" y1="${sy(max * f)}" y2="${sy(max * f)}"/>
      <text x="${P.l - 6}" y="${sy(max * f) + 4}" text-anchor="end">${fmt(max * f)}</text>`).join("")}
    ${data.map((d, i) => series.map((s, j) => {
      const x = P.l + i * gw + (gw - bw * series.length) / 2 + j * bw, v = +d[s] || 0;
      return `<rect class="${colors[j]}" x="${x}" y="${sy(v)}" width="${bw - 2}" height="${H - P.b - sy(v)}" rx="2"><title>${esc(d[label])} · ${esc(s)}: ${fmt(v)}</title></rect>`;
    }).join("") + `<text x="${P.l + i * gw + gw / 2}" y="${H - 10}" text-anchor="middle">${esc(d[label])}</text>`).join("")}
  </svg>`;
}
