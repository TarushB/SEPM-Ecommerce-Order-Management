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

/* ------------------------------------------------------------------ modal forms */
function modal(html, wide) {
  closeModal();
  const bg = document.createElement("div");
  bg.className = "modal-bg"; bg.id = "modal";
  bg.innerHTML = `<div class="modal ${wide ? "wide" : ""}">${html}</div>`;
  bg.addEventListener("mousedown", e => { if (e.target === bg) closeModal(); });
  document.body.appendChild(bg);
  const first = bg.querySelector("input,select,textarea"); if (first) first.focus();
}
function closeModal() { const m = $("#modal"); if (m) m.remove(); }
function formModal(title, fields, onSubmit, note) {
  modal(`<h2>${esc(title)}</h2>${note ? `<div class="muted small">${note}</div>` : ""}
    <form id="mform"><div class="form-grid">${fields.map(f => `<div class="field ${f.full ? "full" : ""}">
      <label>${esc(f.label)}</label>${f.options ? `<select name="${f.name}">${f.options.map(o =>
        `<option value="${esc(o.value ?? o)}" ${String(o.value ?? o) === String(f.value ?? "") ? "selected" : ""}>${esc(o.label ?? o)}</option>`).join("")}</select>`
        : f.textarea ? `<textarea name="${f.name}" rows="3">${esc(f.value ?? "")}</textarea>`
        : `<input name="${f.name}" type="${f.type || "text"}" value="${esc(f.value ?? "")}" ${f.required ? "required" : ""} ${f.step ? `step="${f.step}"` : ""}>`}
    </div>`).join("")}</div>
    <div class="btn-row"><button class="primary" type="submit">Save</button><button type="button" onclick="closeModal()">Cancel</button></div></form>`);
  $("#mform").addEventListener("submit", async e => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(e.target).entries());
    const ok = await onSubmit(data);
    if (ok) closeModal();
  });
}
async function confirmDelete(what, url, after) {
  if (!confirm(`Delete ${what}? The database will refuse if other rows depend on it.`)) return;
  const j = await DEL(url);
  if (j.ok) { toast(j.data.deleted ? "Deleted" : "Nothing deleted", "good"); after && after(); }
}
const statusBadge = s => `<span class="badge ${s === "delivered" ? "good" : s === "canceled" || s === "unavailable" ? "bad" : "info"}">${esc(s)}</span>`;
const stars = n => n ? `<span class="badge ${n <= 2 ? "bad" : n === 3 ? "warn" : "good"}">${"★".repeat(n)}</span>` : "";

/* ------------------------------------------------------------------ shell */
const NAV = [
  ["Overview", [["dashboard", "Dashboard"]]],
  ["Data (CRUD)", [["orders", "Orders"], ["products", "Products"], ["customers", "Customers", ["admin", "manager", "analyst", "support"]],
    ["sellers", "Sellers", ["admin", "manager", "analyst"]], ["reviews", "Reviews"], ["categories", "Categories"]]],
  ["SQL", [["reports", "Reports (Q1–Q16)"], ["console", "SQL console", ["admin", "manager", "analyst"]],
    ["lab", "Transactions lab", ["admin", "manager"]]]],
  ["Intelligence", [["ml", "ML: late deliveries", ["admin", "manager", "analyst"]]]],
  ["Model", [["schema", "ER model & schema"], ["users", "Users & roles", ["admin"]]]],
];
function renderShell() {
  $("#root").innerHTML = `<div class="app ${S.sqlCollapsed ? "sql-collapsed" : ""}">
    <nav class="side"><div class="brand">Olist DBMS</div><div class="brand-sub">E-Commerce & Order Management</div>
      ${NAV.map(([g, items]) => {
        const vis = items.filter(i => !i[2] || can(...i[2]));
        return vis.length ? `<div class="group">${g}</div>` + vis.map(([k, l]) => `<a href="#/${k}" data-k="${k}">${l}</a>`).join("") : "";
      }).join("")}
      <div class="who">Signed in as <b>${esc(S.user.username)}</b><br>DB role: <span class="mono">olist_${esc(S.user.app_role)}</span>
        <br><a onclick="logout()">Sign out</a></div>
    </nav>
    <main id="main"></main>
    <aside class="sql"><header><b>SQL executed</b><button id="sql-toggle" class="small" onclick="toggleSql()">${S.sqlCollapsed ? "SQL ◂" : "Hide ▸"}</button></header>
      <div class="flow"><span>Front end</span>→<span>SQL</span>→<span>PostgreSQL</span>→<span>Result</span></div>
      <div class="sql-list" id="sql-list"><div class="muted small" style="color:#94a3b8">Every statement the server runs for you appears here, exactly as PostgreSQL received it.</div></div>
    </aside></div>`;
}
function renderLogin(msg) {
  $("#root").innerHTML = `<div class="login-wrap"><div class="login">
    <h1>Olist E-Commerce DBMS</h1><div class="muted">PostgreSQL · SQL-first demo application</div>
    <form id="lf" style="margin-top:18px;display:grid;gap:10px">
      <div class="field"><label>Username</label><input name="username" autocomplete="username" required></div>
      <div class="field"><label>Password</label><input name="password" type="password" autocomplete="current-password" required></div>
      <button class="primary">Sign in</button>
      <div id="lerr" class="small" style="color:var(--bad)">${esc(msg || "")}</div>
    </form>
    <div class="small muted" style="margin-top:14px">Demo users (password = username + 123). Each maps to a PostgreSQL role:</div>
    <div class="users">${["admin", "manager", "analyst", "seller", "support"].map(u =>
      `<button type="button" onclick="quickLogin('${u}')">${u}</button>`).join("")}</div>
  </div></div>`;
  $("#lf").addEventListener("submit", async e => {
    e.preventDefault(); const d = Object.fromEntries(new FormData(e.target).entries()); await doLogin(d.username, d.password);
  });
}
async function quickLogin(u) { await doLogin(u, u + "123"); }
async function doLogin(username, password) {
  const r = await fetch("/api/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username, password }) });
  const j = await r.json();
  if (!j.ok) { $("#lerr").textContent = j.error; return; }
  S.user = j.data; S.meta = null; renderShell(); showQueries(j.queries, "/api/login", "POST");
  if (!location.hash || location.hash === "#/") location.hash = "#/dashboard"; else route();
}
async function logout() { await fetch("/api/logout", { method: "POST" }); S.user = null; renderLogin(); }

async function meta() {
  if (!S.meta) { const j = await GET("/api/lookup/meta"); if (j.ok) S.meta = j.data; }
  return S.meta || { states: [], categories: [], payment_types: [], statuses: [] };
}
const stateOptions = m => [{ value: "", label: "any" }, ...m.states.map(s => ({ value: s.state_code, label: s.state_code + " – " + s.state_name }))];
const catOptions = (m, anyLabel = "any") => [{ value: "", label: anyLabel }, ...m.categories.map(c => ({ value: c.category_name_en, label: c.category_name_en }))];
const sel = (name, options, value = "") => `<select name="${name}">${options.map(o => `<option value="${esc(o.value ?? o)}" ${String(o.value ?? o) === String(value) ? "selected" : ""}>${esc(o.label ?? o)}</option>`).join("")}</select>`;
const fld = (label, inner) => `<div class="field"><label>${label}</label>${inner}</div>`;
function formData(id) { return Object.fromEntries(new FormData($(id)).entries()); }

/* Dropdown result counts ("facets"): every option shows how many rows it would
   return together with the other filters; options are sorted by that count and
   options that would return nothing move to the bottom, greyed out. */
function applyFacets(container, facets) {
  if (!container || !facets) return;
  Object.entries(facets).forEach(([name, fc]) => {
    const el = container.querySelector(`select[name="${name}"]`);
    if (!el) return;
    [...el.options].forEach(o => { if (o.dataset.base === undefined) o.dataset.base = o.textContent; });
    const cur = el.value;
    const counts = new Map(fc.values.map(v => [String(v.value), v.n]));
    const opts = [...el.options].map(o => ({ value: o.value, base: o.dataset.base }));
    const any = opts.find(o => o.value === "") || { value: "", base: "any" };
    fc.values.forEach(v => { if (!opts.some(o => o.value === String(v.value))) opts.push({ value: String(v.value), base: String(v.value) }); });
    const rest = opts.filter(o => o.value !== "").map(o => ({ ...o, n: counts.get(o.value) || 0 }));
    rest.sort((a, b) => b.n - a.n || a.base.localeCompare(b.base));
    el.innerHTML = [`<option value="" data-base="${esc(any.base)}">${esc(any.base)} (${fmtNum(fc.total)})</option>`,
      ...rest.map(o => `<option value="${esc(o.value)}" data-base="${esc(o.base)}" ${o.n === 0 && o.value !== cur ? "disabled" : ""}>${esc(o.base)} (${fmtNum(o.n)})</option>`)].join("");
    el.value = cur;
  });
}
function autoSearch(formSel, run) {
  $(formSel).addEventListener("change", e => { if (e.target.tagName === "SELECT") run(); });
}

/* ------------------------------------------------------------------ router */
const PAGES = {};
function route() {
  if (!S.user) return;
  const [, page = "dashboard", arg] = (location.hash || "#/dashboard").split("/");
  document.querySelectorAll("nav.side a[data-k]").forEach(a => a.classList.toggle("active",
    a.dataset.k === page || (page === "order" && a.dataset.k === "orders") || (page === "customer" && a.dataset.k === "customers")));
  closeModal();
  const fn = PAGES[page] || PAGES.dashboard;
  $("#main").innerHTML = `<div class="muted">Loading…</div>`;
  fn(arg ? decodeURIComponent(arg) : undefined);
}
window.addEventListener("hashchange", route);

/* ================================================================== PAGES */
PAGES.dashboard = async () => {
  const j = await GET("/api/dashboard"); if (!j.ok) return $("#main").innerHTML = `<div class="callout bad">${esc(j.error)}</div>`;
  const d = j.data, k = d.kpi;
  $("#main").innerHTML = `<div class="page-head"><div><h1>Dashboard</h1>
    <div class="muted">${S.user.app_role === "seller" ? "Row-level security: you only see orders that contain your items." : "All figures are computed live with SQL on the full dataset."}</div></div></div>
    <div class="grid k5">
      ${[["Orders", fmtNum(k.orders)], ["Item revenue", "R$ " + fmtNum(k.revenue / 1e6, 2) + "M"], ["Average rating", fmtNum(k.avg_rating, 2) + " ★"],
        ["Delivered late", fmtNum(k.late_pct, 1) + "%"], ["Open orders", fmtNum(k.open_orders)]].map(([l, v]) =>
        `<div class="card kpi"><div class="label">${l}</div><div class="value">${v}</div></div>`).join("")}
    </div>
    <div class="card"><h2>Monthly item revenue (R$), Jan 2017 – Aug 2018</h2>${lineChart(d.monthly, "month", "revenue", { fmt: v => fmtNum(v / 1000) + "k" })}</div>
    <div class="grid two">
      <div class="card"><h2>Top 10 categories by revenue</h2>${hbar(d.categories, "category", "revenue", { fmt: v => fmtNum(v / 1000) + "k" })}</div>
      <div class="card"><h2>Orders by customer state (top 12)</h2>${hbar(d.states, "state", "orders")}</div>
    </div>
    <div class="grid two">
      <div class="card"><h2>Review score distribution</h2>${vbars(d.ratings.map(r => ({ ...r, score: r.review_score + "★" })), "score", ["reviews"])}</div>
      <div class="card"><h2>Order status</h2>${table(d.status, [{ key: "order_status", label: "status", render: statusBadge }, { key: "orders", num: true }])}</div>
    </div>`;
};

/* ---------------- ORDERS */
PAGES.orders = async () => {
  const m = await meta();
  $("#main").innerHTML = `<div class="page-head"><div><h1>Orders</h1><div class="muted">Search with any combination of filters; the WHERE clause is built from what you fill in.</div></div>
    ${can("admin", "manager") ? `<button class="primary" onclick="newOrder()">+ New order</button>` : ""}</div>
    <div class="card"><form id="of" class="filters">
      ${fld("Status", sel("status", [{ value: "", label: "any" }, ...m.statuses]))}
      ${fld("Customer state", sel("state", stateOptions(m)))}
      ${fld("From", `<input type="date" name="date_from">`)}${fld("To", `<input type="date" name="date_to">`)}
      ${fld("Rating ≤", sel("max_rating", [{ value: "", label: "any" }, ...[1, 2, 3, 4, 5].map(n => ({ value: String(n), label: "≤ " + n + " ★" }))]))}
      ${fld("Delivered late", sel("late", [{ value: "", label: "any" }, { value: "yes", label: "late" }, { value: "no", label: "on time" }]))}
      ${fld("Order id starts with", `<input name="order_id" size="12">`)}
      <button class="primary">Search</button></form></div>
    <div class="card" id="orders-res"></div>`;
  S.cache.orderPage = 0;
  $("#of").addEventListener("submit", e => { e.preventDefault(); S.cache.orderPage = 0; searchOrders(); });
  autoSearch("#of", () => { S.cache.orderPage = 0; searchOrders(); });
  searchOrders();
};
async function searchOrders() {
  const f = formData("#of");
  const j = await GET("/api/orders?" + qs({ ...f, page: S.cache.orderPage, facets: 1 }));
  if (!j.ok) return;
  applyFacets($("#of"), j.facets);
  $("#orders-res").innerHTML = `<div class="muted small" style="margin-bottom:8px">Page ${S.cache.orderPage + 1} · ${j.data.length} rows
    ${S.cache.orderPage > 0 ? `<a onclick="S.cache.orderPage--;searchOrders()">◂ prev</a>` : ""} ${j.data.length === 50 ? `<a onclick="S.cache.orderPage++;searchOrders()">next ▸</a>` : ""}</div>` +
    table(j.data, [
      { key: "order_id", label: "order", render: v => shortId(v) }, { key: "order_status", label: "status", render: statusBadge },
      { key: "purchase_ts", label: "purchased" }, { key: "customer_city", label: "city" }, { key: "customer_state", label: "state" },
      { key: "items", num: true }, { key: "total", label: "total (R$)", num: true, render: v => fmtNum(v, 2) },
      { key: "rating", render: stars },
      { key: "delivered_customer_date", label: "delivery", render: (v, r) => v ? (v > r.estimated_delivery_date ? `<span class="badge bad">late</span>` : `<span class="badge good">on time</span>`) : "" },
    ], { onRow: r => `location.hash='#/order/${r.order_id}'` });
}
PAGES.order = async id => {
  const j = await GET("/api/orders/" + id);
  if (!j.ok) return $("#main").innerHTML = `<div class="callout bad">${esc(j.error)}</div><a href="#/orders">◂ back to orders</a>`;
  const d = j.data, o = d.order, p = d.prediction;
  const next = { created: "approved", approved: "invoiced", invoiced: "processing", processing: "shipped", shipped: "delivered" }[o.order_status];
  $("#main").innerHTML = `<a href="#/orders">◂ Orders</a>
    <div class="page-head"><div><h1>Order <span class="mono" style="font-size:15px">${esc(o.order_id)}</span></h1>
      <div>${statusBadge(o.order_status)} <span class="muted">purchased ${esc(o.purchase_ts)} · ${esc(o.customer_city)} / ${esc(o.customer_state)}</span></div></div>
      <div class="btn-row">
        ${next && can("admin", "manager", "seller") ? `<button class="primary" onclick="setStatus('${o.order_id}','${next}')">Mark ${next}</button>` : ""}
        ${can("admin", "manager") ? `<button onclick="setStatusPick('${o.order_id}')">Set status…</button>
          <button onclick="cancelOrder('${o.order_id}')">Cancel order</button>
          <button class="danger" onclick="confirmDelete('order ${o.order_id.slice(0, 8)}','/api/orders/${o.order_id}',()=>location.hash='#/orders')">Delete</button>` : ""}
      </div></div>
    <div class="grid two">
      <div class="card"><h2>Details</h2><div class="kv">
        <div>Customer (person)</div><div class="mono">${esc(o.customer_unique_id)}</div>
        <div>Approved</div><div>${esc(o.approved_at || "–")}</div>
        <div>Handed to carrier</div><div>${esc(o.delivered_carrier_date || "–")}</div>
        <div>Delivered</div><div>${esc(o.delivered_customer_date || "–")}</div>
        <div>Promised by</div><div>${esc(o.estimated_delivery_date)}</div>
        <div>Delivery time</div><div>${o.delivery_days !== null ? fmtNum(o.delivery_days, 1) + " days" : "–"}</div>
        <div>Order total</div><div>${money(o.order_total)} <span class="muted small">fn_order_total()</span></div></div></div>
      <div class="card"><h2>ML late-delivery risk</h2>${!d.prediction_access ? `<div class="muted">Your role cannot read ml_prediction (permission denied - see SQL panel).</div>`
        : p ? riskBlock(p.late_probability, p.predicted_days, p.model_version, null, p.threshold) : `<div class="muted">No prediction stored for this order.</div>`}
        ${o.delivered_customer_date ? `<div class="small muted" style="margin-top:8px">Actual outcome: ${o.delivered_customer_date > o.estimated_delivery_date ? `<span class="badge bad">late</span>` : `<span class="badge good">on time</span>`}</div>` : ""}</div>
    </div>
    <div class="card"><h2>Items</h2>${table(d.items, [{ key: "order_item_id", label: "#" }, { key: "product_id", label: "product" }, { key: "category" },
      { key: "seller_id", label: "seller" }, { key: "seller_city", label: "seller city" }, { key: "seller_state", label: "st" },
      { key: "price", num: true, render: v => fmtNum(v, 2) }, { key: "freight_value", label: "freight", num: true, render: v => fmtNum(v, 2) }])}</div>
    <div class="grid two">
      <div class="card"><h2>Payments</h2>${d.payments === null ? `<div class="muted">Permission denied for your role.</div>` : table(d.payments)}</div>
      <div class="card"><h2>Reviews</h2>${d.reviews === null ? `<div class="muted">Permission denied for your role.</div>` : table(d.reviews, [
        { key: "review_score", label: "score", render: stars }, { key: "comment_title", label: "title" }, { key: "comment_message", label: "comment" }, { key: "creation_date", label: "date" }])}
        ${can("admin", "manager") ? `<button class="small" style="margin-top:8px" onclick="newReview('${o.order_id}')">+ Add review</button>` : ""}</div>
    </div>
    <div class="card"><h2>Status history <span class="muted small">(written by trigger trg_order_status_log)</span></h2>${d.history === null ? `<div class="muted">Permission denied.</div>` : table(d.history, null, { empty: "No changes since the data was loaded." })}</div>`;
};
function riskBlock(prob, days, version, promised, threshold) {
  const t = (threshold || 0.57) * 100, pct = prob * 100, col = pct >= t ? "var(--bad)" : pct >= t * 0.75 ? "var(--warn)" : "var(--good)";
  return `<div class="risk"><b style="font-size:22px;color:${col}">${fmtNum(pct, 1)}%</b><div class="meter"><i style="width:${pct}%;background:${col}"></i></div></div>
    <div class="small muted">risk score of arriving after the promised date · <b>${pct >= t ? "HIGH risk" : pct >= t * 0.75 ? "medium risk" : "low risk"}</b> (alert threshold ${fmtNum(t, 0)})</div>
    <div style="margin-top:8px">Predicted delivery time: <b>${fmtNum(days, 1)} days</b>${promised ? ` (promised: ${fmtNum(promised, 0)} days)` : ""}</div>
    <div class="small muted">model ${esc(version)}</div>`;
}
async function setStatus(id, status) {
  const j = await POST(`/api/orders/${id}/status`, { status }); if (j.ok) { toast("Status changed to " + status, "good"); route(); }
}
async function setStatusPick(id) {
  const m = await meta();
  formModal("Change order status", [{ name: "status", label: "New status", options: m.statuses }], async d => {
    const j = await POST(`/api/orders/${id}/status`, d); if (j.ok) { toast("Status changed", "good"); route(); } return true;
  }, "The trigger trg_validate_status_transition rejects backward moves; try one to see the error.");
}
async function cancelOrder(id) { const j = await POST(`/api/orders/${id}/cancel`); if (j.ok) { toast("Order canceled, stock returned", "good"); route(); } }

async function newOrder(predictOnly = false) {
  const m = await meta();
  S.cart = []; S.customer = null; S.customerLabel = ""; S.custs = []; S.found = [];
  modal(`<h2>${predictOnly ? "Try a prediction" : "New order"}</h2>
    <div class="muted small">${predictOnly
      ? "Pick a customer and a product. <b>Predict risk only</b> places the order inside a transaction, reads its features with SQL, scores it, then ROLLBACKs, so nothing is saved."
      : "Runs <span class='mono'>CALL sp_place_order(...)</span>: order, items and payment are inserted atomically, stock is reduced by trigger, then the ML model scores the new order."}</div>

    <h3>Step 1 · Customer</h3>
    <div class="filters"><div class="field" style="flex:1"><label>City (e.g. sao paulo, campinas, rio de janeiro) or customer id</label>
      <input id="cq" placeholder="type at least 2 letters, then pick a row" autocomplete="off"></div>
      <button type="button" onclick="findCustomers($('#cq').value)">Search</button></div>
    <div id="cres" style="max-height:230px;overflow-y:auto;margin-top:6px"></div>

    <h3>Step 2 · Product(s)</h3>
    <div class="filters">${fld("Category", sel("pcat", catOptions(m, "any category")))}
      ${fld("Product id starts with", `<input id="pq" placeholder="optional" size="14">`)}
      <button type="button" onclick="findProducts()">Find products</button></div>
    <div id="pres" style="max-height:260px;overflow-y:auto;margin-top:6px"></div>
    <div class="field" style="margin-top:8px"><label>Cart</label><div id="cart" class="muted small">empty: click <b>Add</b> on a product above</div></div>

    <h3>Step 3 · Payment</h3>
    <div class="filters">${fld("Payment type", sel("ptype", m.payment_types.filter(p => p.payment_type !== "not_defined").map(p => p.payment_type)))}
      ${fld("Installments", `<input id="inst" type="number" min="1" max="24" value="1" style="width:90px">`)}</div>

    <div id="order-status" class="callout" style="margin-top:14px"></div>
    <div class="btn-row">
      ${can("admin", "manager") ? `<button id="btn-predict" class="${predictOnly ? "primary" : ""}" onclick="whatIf()">Predict risk only (ROLLBACK)</button>` : ""}
      <button id="btn-place" class="${predictOnly ? "" : "primary"}" onclick="submitOrder()">Place order</button>
      <button onclick="closeModal()">Close</button></div>
    <div id="ores"></div>`, true);
  let t;
  $("#cq").addEventListener("input", e => { clearTimeout(t); t = setTimeout(() => findCustomers(e.target.value), 350); });
  $("#cq").addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); findCustomers(e.target.value); } });
  $("#pq").addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); findProducts(); } });
  $("[name=pcat]").addEventListener("change", findProducts);
  updateOrderStatus();
  findProducts();                       // show some products straight away
}
function updateOrderStatus() {
  const box = $("#order-status"); if (!box) return;
  const okC = !!S.customer, okP = S.cart.length > 0;
  box.className = "callout " + (okC && okP ? "good" : "");
  box.innerHTML = `${okC ? "✓ Customer: <b>" + esc(S.customerLabel) + "</b>" : "✗ No customer yet: search in step 1 and click <b>Select</b>"}<br>
    ${okP ? "✓ Cart: <b>" + S.cart.length + " product" + (S.cart.length > 1 ? "s" : "") + "</b>" : "✗ No product yet: click <b>Add</b> on a product in step 2"}`;
  ["#btn-predict", "#btn-place"].forEach(id => { const b = $(id); if (b) b.disabled = !(okC && okP); });
}
async function findCustomers(q) {
  q = (q || "").trim().toLowerCase();
  if (q.length < 2) return;
  const j = await GET("/api/lookup/customers?q=" + encodeURIComponent(q));
  if (!j.ok || !$("#cres")) return;
  S.custs = j.data;
  if (!j.data.length) { $("#cres").innerHTML = `<div class="empty">No customer matches "${esc(q)}". Try a city name such as sao paulo.</div>`; return; }
  renderCustomers();
  if (j.data.length === 1 && j.data[0].customer_id === q) pickCustomer(0);   // pasted a full id
}
function renderCustomers() {
  $("#cres").innerHTML = table(S.custs, [
    { key: "_", label: "", render: (v, r) => r.customer_id === S.customer ? `<span class="badge good">selected</span>`
      : `<button type="button" class="small primary" onclick="event.stopPropagation();pickCustomer(${S.custs.indexOf(r)})">Select</button>` },
    { key: "customer_id", render: v => shortId(v) }, { key: "city" }, { key: "state_code", label: "state" }],
    { onRow: (r, i) => `pickCustomer(${i})` });
}
function pickCustomer(i) {
  const c = S.custs[i]; if (!c) return;
  S.customer = c.customer_id; S.customerLabel = `${c.customer_id.slice(0, 8)}… (${c.city} / ${c.state_code})`;
  renderCustomers(); updateOrderStatus();
}
async function findProducts() {
  const j = await GET("/api/lookup/products?" + qs({ category: $("[name=pcat]").value, q: ($("#pq").value || "").trim().toLowerCase(), facets: 1 }));
  if (!j.ok || !$("#pres")) return;
  if (j.facets) applyFacets($("#modal"), { pcat: j.facets.category });
  S.found = j.data;
  if (!j.data.length) { $("#pres").innerHTML = `<div class="empty">No products with stock found. Try another category.</div>`; return; }
  $("#pres").innerHTML = table(j.data, [
    { key: "_", label: "", render: (v, r) => `<button type="button" class="small primary" onclick="event.stopPropagation();addToCart(${S.found.indexOf(r)})">Add</button>` },
    { key: "product_id", render: v => shortId(v) }, { key: "category" }, { key: "stock_qty", label: "stock", num: true },
    { key: "price", label: "last price", num: true, render: v => fmtNum(v, 2) }, { key: "seller_id", label: "seller", render: v => shortId(v) }],
    { onRow: (r, i) => `addToCart(${i})` });
}
function addToCart(i) {
  const item = S.found[i]; if (!item) return;
  S.cart.push(item); renderCart();
  toast("Added to cart", "good");
}
function removeFromCart(k) { S.cart.splice(k, 1); renderCart(); }
function renderCart() {
  $("#cart").innerHTML = S.cart.length ? S.cart.map((c, k) => `${k + 1}. <span class="mono">${esc(c.product_id.slice(0, 8))}…</span> ${esc(c.category)} –
    ${money(c.price)} + freight ${money(c.freight_value)} <a onclick="removeFromCart(${k})">remove</a>`).join("<br>")
    : `empty: click <b>Add</b> on a product above`;
  updateOrderStatus();
}
function orderReady() {
  if (!S.customer) { toast("Step 1: search for a customer and click Select on a row", "bad"); return false; }
  if (!S.cart.length) { toast("Step 2: click Add on at least one product", "bad"); return false; }
  return true;
}
async function submitOrder() {
  if (!orderReady()) return;
  const j = await POST("/api/orders", { customer_id: S.customer, payment_type: $("[name=ptype]").value, installments: $("#inst").value,
    items: S.cart.map(c => ({ product_id: c.product_id, seller_id: c.seller_id })) });
  if (!j.ok) return;
  const p = j.data.prediction;
  $("#ores").innerHTML = `<div class="callout good" style="margin-top:12px">Order <a href="#/order/${j.data.order_id}" onclick="closeModal()">${j.data.order_id}</a> created.</div>
    ${p ? `<div class="card">${riskBlock(p.late_probability, p.predicted_days, p.model_version, p.promised_days, p.threshold)}</div>` : ""}`;
}
async function whatIf() {
  if (!orderReady()) return;
  const c = S.cart[0];
  const j = await POST("/api/ml/predict", { customer_id: S.customer, product_id: c.product_id, seller_id: c.seller_id, payment_type: $("[name=ptype]").value, installments: $("#inst").value });
  if (!j.ok) return;
  const p = j.data.prediction, f = j.data.features;
  $("#ores").innerHTML = `<div class="card" style="margin-top:12px"><div class="muted small">The order was created inside a transaction, its features were read from v_order_features, then ROLLBACK - nothing was saved.${S.cart.length > 1 ? " (Prediction uses the first product in the cart.)" : ""}</div>
    ${riskBlock(p.late_probability, p.predicted_days, p.model_version, p.promised_days, p.threshold)}
    <div class="small muted" style="margin-top:6px">distance ${fmtNum(f.distance_km)} km · ${esc(f.seller_state)} → ${esc(f.customer_state)} · seller's past late rate ${f.seller_prior_late_rate !== null ? fmtNum(f.seller_prior_late_rate * 100, 1) + "%" : "n/a"}</div></div>`;
  $("#ores").scrollIntoView({ behavior: "smooth", block: "nearest" });
}
async function newReview(orderId) {
  formModal("Add review", [{ name: "review_score", label: "Score (1-5)", type: "number", value: 5 }, { name: "comment_title", label: "Title" },
    { name: "comment_message", label: "Comment", textarea: true, full: true }], async d => {
    const j = await POST("/api/reviews", { ...d, order_id: orderId }); if (j.ok) { toast("Review saved", "good"); route(); return true; }
  }, "Try a score of 7 (CHECK constraint) or a review on an order that is not delivered (trigger).");
}

/* ---------------- PRODUCTS */
PAGES.products = async () => {
  const m = await meta();
  $("#main").innerHTML = `<div class="page-head"><div><h1>Products</h1><div class="muted">32,951 products; sorted by units sold.</div></div>
    ${can("admin", "manager") ? `<button class="primary" onclick="editProduct()">+ New product</button>` : ""}</div>
    <div class="card"><form id="pf" class="filters">${fld("Category", sel("category", catOptions(m)))}
      ${fld("Min weight (g)", `<input name="min_weight" type="number" size="8">`)}${fld("Max weight (g)", `<input name="max_weight" type="number" size="8">`)}
      ${fld("Low stock", sel("low_stock", [{ value: "", label: "any" }, { value: "yes", label: "< 30 units" }]))}
      ${fld("Id starts with", `<input name="q" size="10">`)}<button class="primary">Search</button></form></div>
    <div class="card" id="pres-main"></div>`;
  $("#pf").addEventListener("submit", e => { e.preventDefault(); searchProducts(); });
  autoSearch("#pf", searchProducts); searchProducts();
};
async function searchProducts() {
  const j = await GET("/api/products?" + qs({ ...formData("#pf"), facets: 1 })); if (!j.ok) return;
  applyFacets($("#pf"), j.facets);
  S.products = j.data;
  $("#pres-main").innerHTML = table(j.data, [{ key: "product_id", label: "product" }, { key: "category" }, { key: "weight_g", label: "weight g", num: true },
    { key: "length_cm", label: "L", num: true }, { key: "height_cm", label: "H", num: true }, { key: "width_cm", label: "W", num: true },
    { key: "stock_qty", label: "stock", num: true }, { key: "units_sold", label: "sold", num: true },
    ...(can("admin", "manager") ? [{ key: "_", label: "", render: (v, r) => `<button class="small" onclick="event.stopPropagation();editProduct('${r.product_id}')">Edit</button>
      <button class="small danger" onclick="event.stopPropagation();confirmDelete('product','/api/products/${r.product_id}',searchProducts)">Delete</button>` }] : [])]);
}
async function editProduct(id) {
  const m = await meta(), p = id ? S.products.find(x => x.product_id === id) : {};
  formModal(id ? "Edit product" : "New product", [
    { name: "category_name", label: "Category", options: m.categories.map(c => ({ value: c.category_name, label: c.category_name_en })), value: p.category_name },
    { name: "weight_g", label: "Weight (g)", type: "number", value: p.weight_g }, { name: "stock_qty", label: "Stock", type: "number", value: p.stock_qty ?? 50 },
    { name: "length_cm", label: "Length (cm)", type: "number", value: p.length_cm }, { name: "height_cm", label: "Height (cm)", type: "number", value: p.height_cm },
    { name: "width_cm", label: "Width (cm)", type: "number", value: p.width_cm }, { name: "photos_qty", label: "Photos", type: "number", value: p.photos_qty ?? 1 }],
    async d => { const j = id ? await PUT("/api/products/" + id, d) : await POST("/api/products", d); if (j.ok) { toast("Saved", "good"); searchProducts(); return true; } },
    "Negative stock or weight is rejected by CHECK constraints.");
}

/* ---------------- CUSTOMERS */
PAGES.customers = async () => {
  const m = await meta();
  $("#main").innerHTML = `<div class="page-head"><div><h1>Customers</h1><div class="muted">Read through the privacy view <span class="mono">v_customer_public</span> (no coordinates).</div></div>
    ${can("admin", "manager") ? `<button class="primary" onclick="newCustomer()">+ New customer</button>` : ""}</div>
    <div class="card"><form id="cf" class="filters">${fld("State", sel("state", stateOptions(m)))}${fld("City starts with", `<input name="city">`)}
      ${fld("Id starts with", `<input name="q" size="10">`)}${fld("Repeat buyers", sel("repeat", [{ value: "", label: "any" }, { value: "yes", label: "2+ orders" }]))}
      <button class="primary">Search</button></form></div><div class="card" id="cres-main"></div>`;
  $("#cf").addEventListener("submit", e => { e.preventDefault(); searchCustomers(); });
  autoSearch("#cf", searchCustomers); searchCustomers();
};
async function searchCustomers() {
  const j = await GET("/api/customers?" + qs({ ...formData("#cf"), facets: 1 })); if (!j.ok) return;
  applyFacets($("#cf"), j.facets);
  $("#cres-main").innerHTML = table(j.data, [{ key: "customer_id", label: "customer_id (account)" }, { key: "customer_unique_id", label: "person" },
    { key: "city" }, { key: "state_code", label: "state" }, { key: "orders", num: true }], { onRow: r => `location.hash='#/customer/${r.customer_id}'` });
}
PAGES.customer = async id => {
  const j = await GET("/api/customers/" + id); if (!j.ok) return $("#main").innerHTML = `<div class="callout bad">${esc(j.error)}</div>`;
  const c = j.data.customer;
  $("#main").innerHTML = `<a href="#/customers">◂ Customers</a><div class="page-head"><div><h1>Customer</h1><div class="mono">${esc(c.customer_id)}</div></div>
    ${can("admin", "manager") ? `<div class="btn-row"><button onclick="moveCustomer('${c.customer_id}')">Change zip code</button>
      <button class="danger" onclick="confirmDelete('customer account','/api/customers/${c.customer_id}',()=>location.hash='#/customers')">Delete</button></div>` : ""}</div>
    <div class="card"><div class="kv"><div>Person (customer_unique_id)</div><div class="mono">${esc(c.customer_unique_id)}</div><div>City / state</div><div>${esc(c.city)} / ${esc(c.state_code)}</div>
      <div>Zip prefix</div><div>${j.data.zip_prefix ?? "<span class='muted'>hidden for your role</span>"}</div></div></div>
    <div class="card"><h2>All orders of this person (across their accounts)</h2>${table(j.data.orders, [{ key: "order_id", render: v => shortId(v) },
      { key: "order_status", label: "status", render: statusBadge }, { key: "purchase_ts", label: "purchased" }, { key: "total", num: true, render: v => fmtNum(v, 2) },
      { key: "rating", render: stars }], { onRow: r => `location.hash='#/order/${r.order_id}'` })}</div>`;
};
function newCustomer() {
  formModal("New customer", [{ name: "zip_prefix", label: "Zip prefix (e.g. 1037 = São Paulo, 20040 = Rio)", type: "number", required: true },
    { name: "customer_unique_id", label: "Existing person id (optional)" }], async d => {
    const j = await POST("/api/customers", d); if (j.ok) { toast(`Created in ${j.data.city}/${j.data.state_code}`, "good"); location.hash = "#/customer/" + j.data.customer_id; return true; }
  }, "City and state are NOT stored on the customer: they come from zip_code (3NF). An unknown zip fails the foreign key.");
}
function moveCustomer(id) {
  formModal("Change zip code", [{ name: "zip_prefix", label: "New zip prefix", type: "number", required: true }], async d => {
    const j = await PUT("/api/customers/" + id, d); if (j.ok) { toast("Updated", "good"); route(); return true; }
  });
}

/* ---------------- SELLERS */
PAGES.sellers = async () => {
  const m = await meta();
  $("#main").innerHTML = `<div class="page-head"><div><h1>Sellers</h1><div class="muted">Scorecard from the view <span class="mono">v_seller_performance</span>.</div></div>
    ${can("admin", "manager") ? `<button class="primary" onclick="newSeller()">+ New seller</button>` : ""}</div>
    <div class="card"><form id="sf" class="filters">${fld("State", sel("state", stateOptions(m)))}${fld("Min orders", `<input name="min_orders" type="number" size="6">`)}
      ${fld("Max rating", `<input name="max_rating" type="number" step="0.1" size="6">`)}${fld("Sort by", sel("sort", [{ value: "revenue", label: "revenue" }, { value: "rating", label: "worst rating" }, { value: "late", label: "most late" }]))}
      <button class="primary">Search</button></form></div><div class="card" id="sres"></div>`;
  $("#sf").addEventListener("submit", e => { e.preventDefault(); searchSellers(); });
  autoSearch("#sf", searchSellers); searchSellers();
};
async function searchSellers() {
  const j = await GET("/api/sellers?" + qs({ ...formData("#sf"), facets: 1 })); if (!j.ok) return;
  applyFacets($("#sf"), j.facets);
  $("#sres").innerHTML = table(j.data, [{ key: "seller_id", label: "seller" }, { key: "seller_city", label: "city" }, { key: "seller_state", label: "state" },
    { key: "orders", num: true }, { key: "revenue", label: "revenue (R$)", num: true, render: v => fmtNum(v, 2) }, { key: "avg_rating", label: "rating", num: true, render: v => fmtNum(v, 2) },
    { key: "late_pct", label: "late %", num: true, render: v => fmtNum(v, 1) },
    ...(can("admin", "manager") ? [{ key: "_", label: "", render: (v, r) => `<button class="small" onclick="editSeller('${r.seller_id}')">Zip</button>
      <button class="small danger" onclick="confirmDelete('seller','/api/sellers/${r.seller_id}',searchSellers)">Delete</button>` }] : [])]);
}
function newSeller() {
  formModal("New seller", [{ name: "zip_prefix", label: "Zip prefix", type: "number", required: true }], async d => {
    const j = await POST("/api/sellers", d); if (j.ok) { toast("Seller " + j.data.seller_id.slice(0, 8) + "… created", "good"); return true; }
  });
}
function editSeller(id) {
  formModal("Change seller zip", [{ name: "zip_prefix", label: "Zip prefix", type: "number", required: true }], async d => {
    const j = await PUT("/api/sellers/" + id, d); if (j.ok) { toast("Updated", "good"); searchSellers(); return true; }
  });
}

/* ---------------- REVIEWS */
PAGES.reviews = async () => {
  $("#main").innerHTML = `<div class="page-head"><div><h1>Reviews</h1><div class="muted">Word search uses PostgreSQL full-text search (Portuguese stemming) on a GIN index. Try <i>atraso</i> (delay), <i>quebrado</i> (broken), <i>recomendo</i>.</div></div></div>
    <div class="card"><form id="rf" class="filters">${fld("Word", `<input name="word" value="atraso">`)}${fld("Score", sel("score", [{ value: "", label: "any" }, ...[1, 2, 3, 4, 5].map(n => ({ value: String(n), label: n + " ★" }))]))}
      ${fld("With comment", sel("has_comment", [{ value: "", label: "any" }, { value: "yes", label: "yes" }]))}
      ${fld("Unanswered", sel("unanswered", [{ value: "", label: "any" }, { value: "yes", label: "yes" }]))}
      ${fld("Order id", `<input name="order_id" size="12">`)}<button class="primary">Search</button></form></div><div class="card" id="rres"></div>`;
  $("#rf").addEventListener("submit", e => { e.preventDefault(); searchReviews(); });
  autoSearch("#rf", searchReviews); searchReviews();
};
async function searchReviews() {
  const j = await GET("/api/reviews?" + qs({ ...formData("#rf"), facets: 1 })); if (!j.ok) return;
  applyFacets($("#rf"), j.facets);
  $("#rres").innerHTML = table(j.data, [{ key: "order_id", label: "order", render: v => `<a href="#/order/${v}">${esc(v.slice(0, 8))}…</a>` },
    { key: "review_score", label: "score", render: stars }, { key: "comment_title", label: "title" }, { key: "comment_message", label: "comment" },
    { key: "creation_date", label: "date" }, { key: "answer_ts", label: "answered" },
    { key: "_", label: "", render: (v, r) => (can("admin", "manager", "support") ? `<button class="small" onclick="answerReview('${r.review_id}','${r.order_id}')">Mark answered</button> ` : "")
      + (can("admin", "manager") ? `<button class="small" onclick="rescore('${r.review_id}','${r.order_id}')">Score</button> <button class="small danger" onclick="confirmDelete('review','/api/reviews/${r.review_id}/${r.order_id}',searchReviews)">Delete</button>` : "") }]);
}
async function answerReview(rid, oid) { const j = await PUT(`/api/reviews/${rid}/${oid}`, { answer: true }); if (j.ok) { toast("Marked answered", "good"); searchReviews(); } }
function rescore(rid, oid) {
  formModal("Change score", [{ name: "review_score", label: "Score", type: "number", value: 3 }], async d => {
    const j = await PUT(`/api/reviews/${rid}/${oid}`, d); if (j.ok) { toast("Updated", "good"); searchReviews(); return true; }
  }, "Scores outside 1-5 violate the CHECK constraint.");
}

/* ---------------- CATEGORIES */
PAGES.categories = async () => {
  const j = await GET("/api/categories"); if (!j.ok) return;
  $("#main").innerHTML = `<div class="page-head"><div><h1>Categories</h1><div class="muted">Two candidate keys: Portuguese name (PK) and English name (UNIQUE).</div></div>
    ${can("admin", "manager") ? `<button class="primary" onclick="newCategory()">+ New category</button>` : ""}</div>
    <div class="card">${table(j.data, [{ key: "category_name", label: "category_name (PK)" }, { key: "category_name_en", label: "English (UNIQUE)" }, { key: "products", num: true },
      ...(can("admin", "manager") ? [{ key: "_", label: "", render: (v, r) => `<button class="small" onclick="renameCategory('${r.category_name}','${r.category_name_en}')">Rename</button>
        <button class="small danger" onclick="confirmDelete('category ${r.category_name_en}','/api/categories/${r.category_name}',()=>{S.meta=null;route()})">Delete</button>` }] : [])])}</div>`;
};
function newCategory() {
  formModal("New category", [{ name: "category_name", label: "Portuguese name", required: true }, { name: "category_name_en", label: "English name", required: true }], async d => {
    const j = await POST("/api/categories", d); if (j.ok) { S.meta = null; toast("Created", "good"); route(); return true; }
  }, "A duplicate English name violates the UNIQUE constraint. Deleting a category that has products is blocked by the foreign key.");
}
function renameCategory(pt, en) {
  formModal("Rename category", [{ name: "category_name_en", label: "English name", value: en, required: true }], async d => {
    const j = await PUT("/api/categories/" + pt, d); if (j.ok) { S.meta = null; toast("Renamed: one row changed, every product sees it", "good"); route(); return true; }
  });
}

/* ---------------- REPORTS */
PAGES.reports = async () => {
  const j = await GET("/api/reports"); if (!j.ok) return;
  S.reports = j.data;
  $("#main").innerHTML = `<div class="page-head"><div><h1>Reports</h1><div class="muted">Each report demonstrates one SQL concept. Pick one, adjust its parameters, run it, and see the plan with EXPLAIN ANALYZE.</div></div></div>
    <div class="grid" style="grid-template-columns:300px 1fr">
      <div class="card" style="padding:8px">${j.data.map((q, i) => `<a style="display:block;padding:7px 8px;border-radius:6px" id="rep-${i}" onclick="pickReport(${i})">
        <b>${q.id}</b> <span class="small muted">${esc(q.concept)}</span><br><span class="small">${esc(q.title)}</span></a>`).join("")}</div>
      <div id="report-body"><div class="card muted">Choose a report on the left.</div></div></div>`;
  pickReport(0);
};
function pickReport(i) {
  const q = S.reports[i]; S.report = q;
  document.querySelectorAll("[id^=rep-]").forEach((a, k) => a.style.background = k === i ? "var(--accent-soft)" : "");
  $("#report-body").innerHTML = `<div class="card"><h2>${q.id} · ${esc(q.title)}</h2><div class="badge info">${esc(q.concept)}</div>
    <pre class="code">${hl(q.sql.trim())}</pre>
    <form id="repf" class="filters">${Object.entries(q.params).map(([k, v]) => fld(k, `<input name="${k}" value="${esc(v)}" size="10">`)).join("")}
      <button class="primary">Run</button><button type="button" onclick="explainReport()">EXPLAIN ANALYZE</button>
      <button type="button" onclick="csvReport()">Download CSV</button></form></div><div class="card" id="rep-res"></div>`;
  $("#repf").addEventListener("submit", e => { e.preventDefault(); runReport(); }); runReport();
}
async function runReport() {
  const j = await POST("/api/reports/" + S.report.id, formData("#repf")); if (!j.ok) return $("#rep-res").innerHTML = `<div class="callout bad">${esc(j.error)}</div>`;
  $("#rep-res").innerHTML = `<div class="muted small" style="margin-bottom:6px">${j.data.row_count} rows · ${j.queries.find(q => q.label && q.label.startsWith(S.report.id))?.ms ?? ""} ms</div>` + genericTable(j.data);
}
async function explainReport() {
  const j = await POST(`/api/reports/${S.report.id}/explain`, formData("#repf")); if (!j.ok) return;
  $("#rep-res").innerHTML = `<h2>Query plan</h2><pre class="code">${esc(j.data.plan)}</pre>`;
}
function csvReport() { location.href = `/api/reports/${S.report.id}/csv?` + qs(formData("#repf")); }

/* ---------------- SQL CONSOLE */
PAGES.console = async () => {
  $("#main").innerHTML = `<div class="page-head"><div><h1>SQL console</h1><div class="muted">Runs ONE read-only statement as your role (<span class="mono">SET TRANSACTION READ ONLY</span>, 15 s timeout).</div></div></div>
    <div class="card"><textarea id="sqlbox" rows="8" style="width:100%">SELECT z.state_code, COUNT(*) AS orders,
       ROUND(AVG(r.review_score), 2) AS avg_rating
FROM orders o
JOIN customer_account ca ON ca.customer_id = o.customer_id
JOIN zip_code z          ON z.zip_prefix   = ca.zip_prefix
LEFT JOIN review r       ON r.order_id     = o.order_id
GROUP BY z.state_code
ORDER BY orders DESC</textarea>
    <div class="btn-row" style="margin-top:8px"><button class="primary" onclick="runConsole()">Run (Ctrl+Enter)</button>
      ${["SELECT * FROM v_data_quality LIMIT 50", "SELECT * FROM v_high_risk_orders ORDER BY late_probability DESC LIMIT 20",
         "SELECT * FROM order_status_log ORDER BY log_id DESC LIMIT 20", "SELECT * FROM pg_policies",
         "EXPLAIN ANALYZE SELECT * FROM orders WHERE purchase_ts BETWEEN '2018-01-01' AND '2018-01-07'"].map(s =>
        `<button class="small" onclick="$('#sqlbox').value=${esc(JSON.stringify(s))};runConsole()">${esc(s.slice(0, 34))}…</button>`).join("")}</div></div>
    <div class="card" id="cons-res"></div>`;
  $("#sqlbox").addEventListener("keydown", e => { if (e.ctrlKey && e.key === "Enter") runConsole(); });
};
async function runConsole() {
  const j = await POST("/api/sql", { sql: $("#sqlbox").value });
  $("#cons-res").innerHTML = j.ok ? `<div class="muted small">${j.data.row_count} rows (max 500 shown)</div>` + genericTable(j.data) : `<div class="callout bad">${esc(j.error)}</div>`;
}

/* ---------------- TRANSACTIONS LAB */
PAGES.lab = async () => {
  $("#main").innerHTML = `<div class="page-head"><div><h1>Transactions & concurrency lab</h1>
    <div class="muted">Live ACID demonstrations. Every demo undoes its own changes.</div></div></div>
    <div class="grid two">
      <div class="card"><h2>A · Atomicity</h2><p class="muted">Place an order whose 2nd item is an unknown product. The stored procedure fails, and the 1st item and the order row disappear with it.</p>
        <button class="primary" onclick="lab('atomicity')">Run</button><div id="lab-atomicity"></div></div>
      <div class="card"><h2>C · Consistency</h2><p class="muted">Six writes that break a rule: CHECK constraints, a foreign key and two triggers. PostgreSQL rejects each one.</p>
        <button class="primary" onclick="lab('consistency')">Run</button><div id="lab-consistency"></div></div>
      <div class="card"><h2>I · Isolation (non-repeatable read)</h2><p class="muted">Session A reads a product's stock twice; between the reads session B adds 5 and commits.</p>
        <div class="btn-row"><button class="primary" onclick="lab('isolation',{level:'READ COMMITTED'})">READ COMMITTED</button>
        <button class="primary" onclick="lab('isolation',{level:'REPEATABLE READ'})">REPEATABLE READ</button></div><div id="lab-isolation"></div></div>
      <div class="card"><h2>Concurrency · Lost update</h2><p class="muted">Two sessions sell the same product at the same time (read stock, write stock − 1).</p>
        <div class="btn-row"><button class="primary" onclick="lab('lost_update',{locking:false})">Without locking</button>
        <button class="primary" onclick="lab('lost_update',{locking:true})">With SELECT … FOR UPDATE</button></div><div id="lab-lost_update"></div></div>
    </div>
    <div class="card"><h2>D · Durability</h2><p>A committed row survives a crash because PostgreSQL writes it to the write-ahead log (WAL) before <span class="mono">COMMIT</span> returns.
      Demo: create an order, restart the PostgreSQL service (Windows: <span class="mono">services.msc → postgresql-x64-16 → Restart</span>), then search for the order again.
      See <span class="mono">db/10_transactions_demo.sql</span> and <span class="mono">db/11_concurrency_demo.sql</span> for the psql versions (including serializable and deadlock demos).</p></div>`;
};
async function lab(name, body) {
  const box = $("#lab-" + name); box.innerHTML = `<div class="muted">running…</div>`;
  const j = await POST("/api/lab/" + name, body || {});
  if (!j.ok) return box.innerHTML = `<div class="callout bad">${esc(j.error)}</div>`;
  const d = j.data;
  if (name === "atomicity") box.innerHTML = `<div class="callout bad">Error: ${esc(d.error)}</div>
    ${table([{ when: "before", ...d.before }, { when: "after", ...d.after }])}<div class="callout good">${esc(d.explanation)}</div>`;
  else if (name === "consistency") box.innerHTML = table(d, [{ key: "rule" }, { key: "result", render: v => `<span class="badge ${v === "rejected" ? "good" : "bad"}">${v}</span>` }, { key: "error" }]);
  else {
    box.innerHTML = `<div class="steps" style="margin-top:10px">${d.steps.map(s => `<div class="step"><div class="who ${s.session}">${s.session}</div>
      <div><pre class="code" style="margin:0">${hl(s.sql)}</pre><div class="small"><b>${esc(s.result)}</b></div></div></div>`).join("")}</div>
      <div class="callout ${name === "lost_update" && !d.locking ? "bad" : "good"}">${esc(d.explanation)}</div>${d.note ? `<div class="small muted">${esc(d.note)}</div>` : ""}`;
  }
}

/* ---------------- ML */
PAGES.ml = async () => {
  const j = await GET("/api/ml/summary"); if (!j.ok) return;
  const d = j.data, m = d.model;
  if (!m) return $("#main").innerHTML = `<h1>ML: late deliveries</h1><div class="callout">No trained model yet. Run <span class="mono">train_model.bat</span> (or <span class="mono">python ml/train.py</span>), then reload.</div>`;
  const det = m.details || {};
  $("#main").innerHTML = `<div class="page-head"><div><h1>ML: late-delivery prediction</h1>
    <div class="muted">Model <span class="mono">${esc(m.model_version)}</span> · ${esc(m.algorithm)} · trained on ${fmtNum(m.train_rows)} orders, tested on ${fmtNum(m.test_rows)} orders from Jun–Aug 2018 it never saw.</div></div>
    ${can("admin", "manager") ? `<button class="primary" onclick="newOrder(true)">Try a prediction</button>` : ""}</div>
    <div class="grid k5">${[["ROC-AUC (test)", fmtNum(m.roc_auc, 3)], ["PR-AUC (test)", fmtNum(m.pr_auc, 3) + ` <span class="small muted">base ${fmtNum((det.late_rate_test || 0), 3)}</span>`],
      ["Recall at threshold", fmtNum(m.recall_at_t * 100, 0) + "%"], ["Delivery-days error", fmtNum(m.mae_days, 1) + " days"], ["Olist's promise error", fmtNum(m.baseline_mae_days, 1) + " days"]]
      .map(([l, v]) => `<div class="card kpi"><div class="label">${l}</div><div class="value">${v}</div></div>`).join("")}</div>
    <div class="grid two">
      <div class="card"><h2>Actual late rate by predicted-risk decile</h2><div class="muted small">Test months (Jun–Aug 2018), computed in SQL with NTILE(10). D1 = the 10% of orders the model found safest, D10 = riskiest.
        A useful model makes the bars rise from left to right. Overall late rate: ${fmtNum((det.late_rate_test || 0) * 100, 1)}%.</div>
        ${vbars(d.deciles.map(x => ({ ...x, decile: "D" + x.risk_decile })), "decile", ["actual_late_pct"], { fmt: v => fmtNum(v, 1) + "%" })}
        <div class="small muted">The model was trained with balanced class weights, so its raw scores rank risk well but overstate the probability; read them as a risk score.</div></div>
      <div class="card"><h2>Confusion matrix (SQL on ml_prediction)</h2>${table(d.confusion)}
        <h3>Model comparison (rolling time-series CV, then test)</h3>${table((det.comparison || []).map(r => ({ model: r.model, cv_roc_auc: r.cv_roc_auc, cv_pr_auc: r.cv_pr_auc, test_roc_auc: r.test_roc_auc, test_pr_auc: r.test_pr_auc })))}</div>
    </div>
    <div class="grid two">
      <div class="card"><h2>What drives the prediction</h2><div class="muted small">Permutation importance on the test months (drop in PR-AUC when a feature is shuffled).</div>
        ${hbar((det.feature_importance || []).slice(0, 10).map(f => ({ ...f, importance: Math.max(f.importance, 0) })), "feature", "importance", { fmt: v => fmtNum(v, 4) })}</div>
      <div class="card"><h2>Delivery time: model vs promise</h2>
        <p>Average error on ${fmtNum(d.days.orders)} test orders: the model is off by <b>${fmtNum(d.days.model_mae_days, 1)} days</b>; Olist's promised date is off by <b>${fmtNum(d.days.promise_mae_days, 1)} days</b>.</p>
        <p class="muted small">Olist promises very conservative dates, which is why only ~8% of orders are late. The regression model gives a far more accurate delivery estimate to show the customer.</p>
        <h3>Pipeline</h3><ol class="small"><li>Features are built in SQL (<span class="mono">v_order_features</span>, <span class="mono">mv_order_features</span>): distance from zip coordinates, freight, weight, seller's past late rate (only deliveries completed before the purchase: no leakage).</li>
        <li>Rolling time-series cross-validation picks the model; the threshold is tuned on out-of-fold predictions.</li>
        <li>Metrics go into <span class="mono">ml_model</span>, scores into <span class="mono">ml_prediction</span>; new orders are scored live when they are placed.</li></ol></div>
    </div>
    <div class="card"><h2>Open orders with the highest risk <span class="muted small">(view v_high_risk_orders)</span></h2>${table(d.risky, [{ key: "order_id", render: v => shortId(v) },
      { key: "order_status", label: "status", render: statusBadge }, { key: "purchase_ts", label: "purchased" }, { key: "seller_state", label: "from" }, { key: "customer_state", label: "to" },
      { key: "distance_km", label: "km", num: true }, { key: "main_category", label: "category" }, { key: "late_probability", label: "late risk", num: true, render: v => fmtNum(v * 100, 1) + "%" },
      { key: "predicted_days", label: "pred. days", num: true, render: v => fmtNum(v, 1) }], { onRow: r => `location.hash='#/order/${r.order_id}'` })}</div>`;
};

/* ---------------- SCHEMA */
PAGES.schema = async () => {
  $("#main").innerHTML = `<div class="page-head"><div><h1>ER model & database schema</h1><div class="muted">The diagram is the design; the tabs below are read live from PostgreSQL's catalog.</div></div></div>
    <div class="tabs">${["ER diagram", "Tables & keys", "Constraints", "Objects", "Privileges", "Normalization"].map((t, i) => `<button onclick="schemaTab(${i})" data-t="${i}">${t}</button>`).join("")}</div>
    <div id="schema-body"></div>`;
  const j = await GET("/api/schema"); S.schema = j.ok ? j.data : null; schemaTab(0);
};
async function schemaTab(i) {
  document.querySelectorAll(".tabs button").forEach(b => b.classList.toggle("on", +b.dataset.t === i));
  const d = S.schema, box = $("#schema-body");
  if (i === 0) {
    box.innerHTML = `<div class="card"><div class="btn-row" style="margin-bottom:8px"><button class="small" onclick="$('#er-diagram').classList.toggle('zoom')">Toggle zoom</button></div><div id="er-diagram">rendering…</div><div class="small muted" style="margin-top:8px">|| one · o{ zero or many · |{ one or many · PK primary key · FK foreign key · UK unique (candidate key)</div></div>`;
    try {
      mermaid.initialize({ startOnLoad: false, theme: "default", er: { useMaxWidth: true, fontSize: 13 }, securityLevel: "strict" });
      const { svg } = await mermaid.render("erd" + Date.now(), window.ER_DIAGRAM);
      $("#er-diagram").innerHTML = svg;
    } catch (e) { $("#er-diagram").innerHTML = `<pre class="code">${esc(window.ER_DIAGRAM)}</pre>`; }
    return;
  }
  if (!d) return box.innerHTML = `<div class="callout bad">Could not read the catalog.</div>`;
  if (i === 1) {
    const counts = Object.fromEntries(d.counts.map(c => [c.table_name, c.approx_rows]));
    const tables = [...new Set(d.columns.map(c => c.table_name))];
    box.innerHTML = `<div class="grid three">${tables.map(t => `<div class="card"><h2>${t} <span class="muted small">~${fmtNum(Math.max(counts[t] || 0, 0))} rows</span></h2>
      ${table(d.columns.filter(c => c.table_name === t), [{ key: "column_name", label: "column", render: (v, r) => (r.is_pk ? "🔑 " : "") + esc(v) },
        { key: "data_type", label: "type", render: (v, r) => esc(v) + (r.max_len ? `(${r.max_len})` : "") }, { key: "is_nullable", label: "null" }])}</div>`).join("")}</div>`;
  } else if (i === 2) box.innerHTML = `<div class="card">${table(d.constraints)}</div>`;
  else if (i === 3) box.innerHTML = `<div class="card">${table(d.objects)}</div>`;
  else if (i === 4) box.innerHTML = `<div class="card"><div class="muted small">GRANTs held by each group role (the app switches to one of them per request with SET LOCAL ROLE).</div>${table(d.grants)}</div>`;
  else if (i === 5) box.innerHTML = `<div class="card"><h2>Functional dependencies</h2><div class="muted small">In every table the determinant is a candidate key, so each table is in BCNF.</div>
    ${table(window.NORMALIZATION.map(([l, r, t]) => ({ determinant: l, "→ determines": r, "table (BCNF)": t })))}
    <h3>Decomposition steps</h3><ol><li><b>1NF:</b> items and payments were repeating groups of an order → separate rows (order_item, payment).</li>
    <li><b>2NF:</b> status and dates depend on order_id only, not on (order_id, order_item_id) → ORDERS split from ORDER_ITEM; product attributes → PRODUCT.</li>
    <li><b>3NF:</b> removed transitive dependencies: customer_id → zip → city/state (ZIP_CODE, STATE), product → category → English name (CATEGORY), payment_type → description (PAYMENT_TYPE).</li>
    <li><b>BCNF:</b> CATEGORY has two determinants, both candidate keys; no other non-key determinants remain.</li></ol>
    <p class="muted">Run <span class="mono">db/14_normalization_demo.sql</span> to see update / insert / delete anomalies on the real data.</p></div>`;
}

/* ---------------- USERS */
PAGES.users = async () => {
  const j = await GET("/api/admin/users"); if (!j.ok) return;
  $("#main").innerHTML = `<div class="page-head"><div><h1>Users & roles</h1><div class="muted">Passwords are hashed with bcrypt inside PostgreSQL (pgcrypto). The app never sees a stored hash; login calls <span class="mono">fn_login()</span>.</div></div>
    <button class="primary" onclick="newUser()">+ New user</button></div>
    <div class="card">${table(j.data)}</div>
    <div class="card"><h2>Role → what the database allows</h2>${table([
      { role: "admin", "PostgreSQL role": "olist_admin", allowed: "everything, incl. DDL and users" },
      { role: "manager", "PostgreSQL role": "olist_manager", allowed: "CRUD on business tables, procedures, all views" },
      { role: "analyst", "PostgreSQL role": "olist_analyst", allowed: "read-only; zip_code lat/lng hidden by column privileges" },
      { role: "seller", "PostgreSQL role": "olist_seller", allowed: "only orders containing own items (row-level security); update status" },
      { role: "support", "PostgreSQL role": "olist_support", allowed: "read orders/customers (privacy view), mark reviews answered" }])}</div>`;
};
function newUser() {
  formModal("New application user", [{ name: "username", label: "Username", required: true }, { name: "password", label: "Password", type: "password", required: true },
    { name: "app_role", label: "Role", options: ["manager", "analyst", "support", "seller", "admin"] }, { name: "seller_id", label: "Seller id (only for role seller)", full: true }],
    async d => { const j = await POST("/api/admin/users", d); if (j.ok) { toast("User created", "good"); route(); return true; } },
    "A seller user without a seller_id violates a CHECK constraint.");
}

/* ------------------------------------------------------------------ boot */
(async function boot() {
  try {
    const r = await fetch("/api/me"); const j = await r.json();
    if (j.data) { S.user = j.data; renderShell(); route(); } else renderLogin();
  } catch (e) { renderLogin("Server not reachable - is backend/app.py running?"); }
})();
