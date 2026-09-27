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
