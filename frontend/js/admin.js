// Phase 12: admin dashboard. Every request goes to the same /api/v1/admin/... routes the API tests cover, and the
// server checks the admin role on each one: this page only makes them easy to use.
// Safety rule used throughout: text from the server is inserted with textContent, never innerHTML.
const TOKEN_KEY = "pgpc_token";
const PAGE = 15;

// ----------------------------------------------------------------------------- small helpers
function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (k === "value") n.value = v;
    else n.setAttribute(k, v === true ? "" : v);
  }
  kids.flat().forEach((c) => c !== null && c !== undefined && n.append(c.nodeType ? c : document.createTextNode(String(c))));
  return n;
}
const $ = (id) => document.getElementById(id);
const get = (obj, path) => path.split(".").reduce((o, k) => (o == null ? o : o[k]), obj);
const when = (iso) => (iso ? new Date(iso).toLocaleString() : "");

function flash(text, kind = "success") {
  const box = $("flash");
  box.replaceChildren(el("div", { class: `alert alert-${kind} py-2`, role: "alert" }, text));
  window.scrollTo({ top: 0, behavior: "smooth" });
  if (kind === "success") setTimeout(() => box.replaceChildren(), 4000);
}

function logout() { sessionStorage.removeItem(TOKEN_KEY); window.location.href = "login.html"; }

async function api(path, { method = "GET", json, form, raw } = {}) {
  const headers = { Authorization: "Bearer " + sessionStorage.getItem(TOKEN_KEY) };
  let body;
  if (json !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(json); }
  if (form) body = form;
  const res = await fetch("/api/v1" + path, { method, headers, body });
  if (res.status === 401) { logout(); throw new Error("Please sign in again."); }
  if (raw && res.ok) return res;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(describeError(data, res.status));
  return data;
}

function describeError(data, status) {
  const d = data && data.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((e) => `${(e.loc || []).slice(1).join(".") || "input"}: ${e.msg}`).join("; ");
  return `Request failed (${status}).`;
}

async function guarded(fn) {            // run an action and show any error instead of failing silently
  try { return await fn(); } catch (e) { flash(e.message, "danger"); }
}

// ----------------------------------------------------------------------------- modal
const modal = new bootstrap.Modal($("modal"));
function openModal(title, body, buttons = []) {
  $("modalTitle").textContent = title;
  $("modalBody").replaceChildren(body);
  $("modalFooter").replaceChildren(
    el("button", { class: "btn btn-outline-secondary", "data-bs-dismiss": "modal", type: "button" }, "Close"), ...buttons);
  modal.show();
}

// ----------------------------------------------------------------------------- module configuration
const T = (name, label, extra = {}) => ({ name, label, type: "text", ...extra });
const TA = (name, label, extra = {}) => ({ name, label, type: "textarea", ...extra });
const full = (r) => [r.first_name, r.middle_name, r.last_name].filter(Boolean).join(" ");

const MODULES = {
  employees: { label: "Employees", singular: "employee", group: "People",
    columns: [["Name", full], ["No.", "employee_number"], ["Position", "position.name"], ["Office", "office.name"],
              ["Email", "email"], ["Status", "status"]],
    fields: [T("first_name", "First name", { required: true }), T("middle_name", "Middle name"),
             T("last_name", "Last name", { required: true }), T("employee_number", "Employee number"),
             { name: "position_id", label: "Position", type: "select", ref: "positions" },
             { name: "office_id", label: "Office", type: "select", ref: "offices" },
             T("email", "Email", { inputType: "email" }), T("contact_number", "Contact number"),
             T("status", "Status", { default: "active", required: true }), TA("description", "Description")] },
  positions: { label: "Positions", singular: "position", group: "People",
    columns: [["Name", "name"], ["Description", "description"]],
    fields: [T("name", "Name", { required: true }), TA("description", "Description")] },
  offices: { label: "Offices", singular: "office", group: "Campus",
    columns: [["Name", "name"], ["Building", "building"], ["Floor", "floor"], ["Room", "room_number"],
              ["Contact", "contact_number"], ["Email", "email"]],
    fields: [T("name", "Name", { required: true }), T("building", "Building"), T("floor", "Floor"),
             T("room_number", "Room number"), T("contact_number", "Contact number"),
             T("email", "Email", { inputType: "email" }), TA("description", "Description")] },
  facilities: { label: "Facilities", singular: "facility", group: "Campus",
    columns: [["Name", "name"], ["Building", "building"], ["Location", "location"], ["Hours", "operating_hours"]],
    fields: [T("name", "Name", { required: true }), T("building", "Building"), T("location", "Location"),
             T("operating_hours", "Operating hours"), TA("available_equipment", "Available equipment"),
             TA("description", "Description")] },
  rooms: { label: "Rooms", singular: "room", group: "Campus",
    columns: [["Room", "room_number"], ["Name", "room_name"], ["Building", "building"], ["Floor", "floor"],
              ["Type", "room_type"]],
    fields: [T("room_number", "Room number", { required: true }), T("room_name", "Room name"),
             T("building", "Building"), T("floor", "Floor"), T("room_type", "Room type"),
             { name: "facility_id", label: "Facility", type: "select", ref: "facilities" },
             TA("description", "Description")] },
  handbook: { label: "Handbook", singular: "handbook section", group: "Knowledge",
    columns: [["Section", "section_number"], ["Title", "title"], ["Category", "category"], ["Page", "source_page"]],
    fields: [T("title", "Title", { required: true }), T("section_number", "Section number"),
             T("category", "Category"), T("source_document", "Source document"), T("source_page", "Source page"),
             TA("content", "Content", { required: true, rows: 10 })] },
  history: { label: "School history", singular: "history entry", group: "Knowledge",
    columns: [["Year", "year"], ["Title", "title"], ["Source", "source"]],
    fields: [T("title", "Title", { required: true }), T("year", "Year"), T("source", "Source"),
             TA("content", "Content", { required: true, rows: 8 })] },
  faqs: { label: "FAQs", singular: "FAQ", group: "Knowledge", adminList: true,
    columns: [["Question", "question"], ["Category", "category"], ["Active", (r) => (r.is_active ? "Yes" : "Hidden")]],
    fields: [TA("question", "Question", { required: true, rows: 2 }), TA("answer", "Answer", { required: true, rows: 5 }),
             T("category", "Category"), T("keywords", "Keywords (comma separated)"), T("source", "Source"),
             { name: "is_active", label: "Show to students", type: "checkbox", default: true }] },
  "quick-links": { label: "Quick links", singular: "quick link", group: "Knowledge", adminList: true,
    columns: [["Title", "title"], ["Words that trigger it", "keywords"], ["Link", "url"],
              ["Active", (r) => (r.is_active ? "Yes" : "Hidden")]],
    fields: [T("title", "Title (e.g. Scholarship application)", { required: true }),
             TA("keywords", "Words that trigger it (separate phrases with commas, e.g. scholarship application, apply scholarship)", { required: true, rows: 3 }),
             T("url", "Link (starts with https://)", { required: true, inputType: "url" }),
             TA("message", "Text shown above the link (optional)", { rows: 3 }),
             { name: "is_active", label: "Active", type: "checkbox", default: true }] },
  library: { label: "Library", singular: "library book", group: "Knowledge",
    columns: [["Title", "title"], ["Author", "author"], ["ISBN", "isbn"], ["Category", "category"],
              ["Availability", "availability"]],
    fields: [T("title", "Title", { required: true }), T("author", "Author"), T("isbn", "ISBN"),
             T("category", "Category"), T("publisher", "Publisher"), T("year", "Year"),
             T("availability", "Availability"), T("location", "Shelf / location")] },
};

// ----------------------------------------------------------------------------- generic table + form
function cell(row, col) {
  const v = typeof col === "function" ? col(row) : get(row, col);
  return v === null || v === undefined || v === "" ? "" : String(v);
}

function pager(state, reload) {
  const last = Math.max(0, Math.ceil(state.total / PAGE) - 1), page = state.skip / PAGE;
  return el("div", { class: "d-flex align-items-center gap-2 mt-2" },
    el("button", { class: "btn btn-sm btn-outline-secondary", disabled: page <= 0,
                   onclick: () => { state.skip -= PAGE; reload(); } }, "Previous"),
    el("span", { class: "small" }, `Page ${page + 1} of ${last + 1} (${state.total} total)`),
    el("button", { class: "btn btn-sm btn-outline-secondary", disabled: page >= last,
                   onclick: () => { state.skip += PAGE; reload(); } }, "Next"));
}

async function refOptions(path) {       // all rows of a small table, for the drop-down lists
  const out = [];
  for (let skip = 0; ; skip += 100) {
    const page = await api(`/${path}?limit=100&skip=${skip}`);
    out.push(...page.items);
    if (out.length >= page.total || !page.items.length) break;
  }
  return out;
}
const refLabel = (r) => r.name || r.room_number || r.title || "#" + r.id;

async function openForm(key, record, onSaved, prefill) {
  const cfg = MODULES[key];
  const form = el("form", { novalidate: true, class: "row g-3" });
  const inputs = {};
  for (const f of cfg.fields) {
    let input;
    const current = record ? record[f.name] : (prefill && prefill[f.name] !== undefined ? prefill[f.name] : f.default);
    if (f.type === "textarea") input = el("textarea", { class: "form-control", rows: f.rows || 3 });
    else if (f.type === "checkbox") input = el("input", { type: "checkbox", class: "form-check-input" });
    else if (f.type === "select") {
      input = el("select", { class: "form-select" }, el("option", { value: "" }, "(none)"));
      (await refOptions(f.ref)).forEach((o) => input.append(el("option", { value: o.id }, refLabel(o))));
    } else input = el("input", { type: f.inputType || "text", class: "form-control" });
    if (f.type === "checkbox") input.checked = current === undefined ? true : !!current;
    else if (f.type === "select") input.value = record ? (record[f.name] ?? get(record, f.name.replace(/_id$/, "") + ".id") ?? "") : "";
    else input.value = current ?? "";
    input.id = "f_" + f.name;
    inputs[f.name] = input;
    const wrap = f.type === "checkbox"
      ? el("div", { class: "form-check" }, input, el("label", { class: "form-check-label", for: input.id }, f.label))
      : el("div", {}, el("label", { class: "form-label", for: input.id }, f.label + (f.required ? " *" : "")), input);
    form.append(el("div", { class: f.type === "textarea" ? "col-12" : "col-md-6" }, wrap));
  }
  const err = el("div", { class: "text-danger small col-12", role: "alert" });
  form.append(err);

  const save = el("button", { class: "btn sg-send", type: "button", onclick: async () => {
    err.textContent = "";
    const payload = {};
    for (const f of cfg.fields) {
      const i = inputs[f.name];
      if (f.type === "checkbox") payload[f.name] = i.checked;
      else if (f.type === "select") payload[f.name] = i.value ? Number(i.value) : null;
      else payload[f.name] = i.value;
    }
    save.disabled = true;
    try {
      await api(`/admin/${key}` + (record ? `/${record.id}` : ""), { method: record ? "PUT" : "POST", json: payload });
      modal.hide();
      flash(`${cfg.singular[0].toUpperCase() + cfg.singular.slice(1)} ${record ? "updated" : "added"}.`);
      onSaved();
    } catch (e) { err.textContent = e.message; } finally { save.disabled = false; }
  } }, record ? "Save changes" : "Add");
  openModal((record ? "Edit " : "Add ") + cfg.singular, form, [save]);
}

async function crudView(key) {
  const cfg = MODULES[key];
  const state = { skip: 0, total: 0, q: "" };
  const view = $("view");
  const search = el("input", { class: "form-control", type: "search", placeholder: `Search ${cfg.label.toLowerCase()}...`,
                               "aria-label": "Search" });
  const tableBox = el("div");
  const reload = () => guarded(async () => {
    const base = cfg.adminList ? `/admin/${key}` : `/${key}`;
    const data = await api(`${base}?skip=${state.skip}&limit=${PAGE}` + (state.q ? `&q=${encodeURIComponent(state.q)}` : ""));
    state.total = data.total;
    const head = el("tr", {}, ...cfg.columns.map(([h]) => el("th", {}, h)), el("th", {}, ""));
    const rows = data.items.map((r) => el("tr", {},
      ...cfg.columns.map(([, c]) => el("td", { title: cell(r, c) }, cell(r, c))),
      el("td", { class: "text-nowrap text-end" },
        el("button", { class: "btn btn-sm btn-outline-primary me-1", onclick: () => guarded(() => openForm(key, r, reload)) }, "Edit"),
        el("button", { class: "btn btn-sm btn-outline-danger", onclick: () => remove(r) }, "Delete"))));
    tableBox.replaceChildren(
      el("div", { class: "sg-table-wrap" }, el("table", { class: "table table-hover align-middle" },
        el("thead", {}, head), el("tbody", {}, rows.length ? rows : el("tr", {}, el("td", { colspan: cfg.columns.length + 1, class: "text-muted p-3" }, "Nothing here yet."))))),
      pager(state, reload));
  });
  const remove = (r) => guarded(async () => {
    if (!confirm(`Delete this ${cfg.singular}? This cannot be undone.`)) return;
    await api(`/admin/${key}/${r.id}`, { method: "DELETE" });
    flash(`${cfg.singular[0].toUpperCase() + cfg.singular.slice(1)} deleted.`);
    if (state.skip >= state.total - 1 && state.skip > 0) state.skip -= PAGE;
    reload();
  });
  let timer;
  search.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => { state.q = search.value.trim(); state.skip = 0; reload(); }, 300); });
  view.replaceChildren(
    el("div", { class: "d-flex justify-content-between align-items-center mb-3 gap-2" },
      el("h2", { class: "h4 m-0" }, cfg.label),
      el("div", { class: "d-flex gap-2" }, search,
         el("button", { class: "btn sg-send text-nowrap", onclick: () => guarded(() => openForm(key, null, reload)) }, "+ Add"))),
    tableBox);
  reload();
}

// ----------------------------------------------------------------------------- overview
async function overviewView() {
  const view = $("view");
  view.replaceChildren(el("h2", { class: "h4 mb-3" }, "Overview"), el("p", { class: "text-muted" }, "Loading..."));
  await guarded(async () => {
    const [chat, docs, offices, facilities, ...counts] = await Promise.all([
      api("/admin/chat/summary"), api("/admin/documents?status=active&limit=1"),
      api("/offices?limit=100"), api("/facilities?limit=100"),
      ...Object.keys(MODULES).map((k) => api(`${MODULES[k].adminList ? "/admin" : ""}/${k}?limit=1`))]);
    const total = {};
    Object.keys(MODULES).forEach((k, i) => { total[k] = counts[i].total; });
    const stat = (n, label) => el("div", { class: "col-6 col-md-3" }, el("div", { class: "sg-card" },
      el("div", { class: "sg-stat" }, n), el("div", { class: "sg-stat-label" }, label)));
    const answeredPct = chat.questions ? Math.round((100 * chat.answered) / chat.questions) + "%" : "-";
    // What the chatbot cannot answer yet because the records are missing. Each line opens the page where it is fixed.
    const todo = [];
    const noPlace = offices.items.filter((o) => !o.building && !o.room_number).length;
    const noHours = facilities.items.filter((f) => !f.operating_hours).length;
    if (total.positions < Math.max(3, Math.round(total.employees / 8)))
      todo.push(["positions", `Only ${total.positions} position${total.positions === 1 ? "" : "s"} for ${total.employees} employees. Add job titles (for example Utility Staff, Cashier, Librarian) and assign them, so "who is the cashier?" works.`]);
    if (noPlace) todo.push(["offices", `${noPlace} of ${offices.total} offices have no building or room, so "where is the registrar's office?" cannot say where.`]);
    if (noHours) todo.push(["facilities", `${noHours} of ${facilities.total} facilities have no opening hours, so "what time is the library open?" cannot be answered.`]);
    if (!total.rooms) todo.push(["rooms", "No rooms yet. Add rooms with their building and floor so students can find them."]);
    if (total.faqs < 10) todo.push(["faqs", `Only ${total.faqs} FAQ${total.faqs === 1 ? "" : "s"}. Add answers for things the handbook does not cover: student counts per program, contact numbers, the school hymn.`]);
    if (!total["quick-links"]) todo.push(["quick-links", "No quick links yet. Add the pages students ask for, such as the enrollment portal or the school Facebook page."]);
    const checklist = todo.length
      ? el("div", { class: "sg-card mb-4 sg-todo" }, el("h3", { class: "h6 mb-2" }, "Add these to improve answers"),
          el("ul", { class: "list-unstyled mb-0" }, ...todo.map(([key, text]) => el("li", { class: "d-flex gap-3 align-items-start py-2" },
            el("span", { class: "flex-grow-1" }, text),
            el("button", { type: "button", class: "btn btn-sm sg-btn-line",
                           onclick: () => show(key, () => crudView(key)) }, "Go to " + MODULES[key].label)))))
      : el("div", { class: "sg-card mb-4 sg-todo" }, el("strong", {}, "The records look complete. "),
          "Check the To improve page to see what students are still asking for.");
    view.replaceChildren(
      el("h2", { class: "h4 mb-3" }, "Overview"),
      checklist,
      el("h3", { class: "h6 text-muted" }, "Chatbot use"),
      el("div", { class: "row g-3 mb-4" }, stat(chat.questions, "Questions asked"), stat(answeredPct, "Answered from records"),
        stat(chat.unanswered, "Not found (PGPC questions)"), stat(chat.active_sessions, "Open chats"),
        stat(chat.helpful + chat.not_helpful ? Math.round((100 * chat.helpful) / (chat.helpful + chat.not_helpful)) + "%" : "-",
             `Rated helpful (${chat.helpful + chat.not_helpful} votes)`)),
      el("h3", { class: "h6 text-muted" }, "Knowledge base"),
      el("div", { class: "row g-3 mb-4" },
        ...Object.keys(MODULES).map((k, i) => stat(counts[i].total, MODULES[k].label)),
        stat(docs.total, "Active documents")),
      el("h3", { class: "h6 text-muted" }, "Recent questions the chatbot could not answer"),
      chat.recent_unanswered.length
        ? el("ul", { class: "list-group" }, ...chat.recent_unanswered.map((r) =>
            el("li", { class: "list-group-item d-flex justify-content-between" }, el("span", {}, r.question),
               el("small", { class: "text-muted" }, when(r.asked_at)))))
        : el("p", { class: "text-muted" }, "None yet. Questions with no matching record will appear here, so you know what to add."));
  });
}

// ----------------------------------------------------------------------------- documents
async function documentsView() {
  const view = $("view");
  const state = { skip: 0, total: 0, status: "" };
  const tableBox = el("div");
  const file = el("input", { type: "file", class: "form-control", accept: ".pdf,.docx,.txt", required: true });
  const title = el("input", { class: "form-control", placeholder: "Title (defaults to the file name)" });
  const source = el("input", { class: "form-control", placeholder: "Source, e.g. Student Handbook 2026" });
  const category = el("input", { class: "form-control", placeholder: "Category (optional)" });
  const description = el("input", { class: "form-control", placeholder: "Description (optional)" });
  const replaces = el("select", { class: "form-select" }, el("option", { value: "" }, "New document (replaces nothing)"));
  const msg = el("div", { class: "small mt-2", role: "status" });

  const loadReplaceChoices = () => guarded(async () => {
    const d = await api("/admin/documents?status=active&limit=100");
    replaces.replaceChildren(el("option", { value: "" }, "New document (replaces nothing)"),
      ...d.items.map((x) => el("option", { value: x.id }, "Replace: " + x.title)));
  });
  const reload = () => guarded(async () => {
    const d = await api(`/admin/documents?skip=${state.skip}&limit=${PAGE}` + (state.status ? `&status=${state.status}` : ""));
    state.total = d.total;
    const rows = d.items.map((x) => el("tr", {},
      el("td", { title: x.title }, x.title), el("td", {}, x.file_type.toUpperCase()), el("td", {}, x.chunks),
      el("td", {}, el("span", { class: "badge " + (x.status === "active" ? "text-bg-success" : "text-bg-secondary") }, x.status)),
      el("td", {}, when(x.uploaded_at)),
      el("td", { class: "text-nowrap text-end" },
        btn("Preview", () => preview(x)), btn("Edit", () => edit(x)), btn("Download", () => download(x)),
        x.status === "active" ? btn("Archive", () => act(x, "archive", "Archive this document? It will no longer be used to answer questions."))
                              : btn("Restore", () => act(x, "restore")),
        btn("Re-read", () => act(x, "reprocess")),
        x.status === "archived" ? btn("Delete", () => del(x), "danger") : null)));
    tableBox.replaceChildren(
      el("div", { class: "sg-table-wrap" }, el("table", { class: "table table-hover align-middle" },
        el("thead", {}, el("tr", {}, ...["Title", "Type", "Passages", "Status", "Uploaded", ""].map((h) => el("th", {}, h)))),
        el("tbody", {}, rows.length ? rows : el("tr", {}, el("td", { colspan: 6, class: "text-muted p-3" }, "No documents yet.")))),
      ), pager(state, reload));
  });
  const btn = (label, fn, kind = "primary") => el("button", { class: `btn btn-sm btn-outline-${kind} me-1`, onclick: () => guarded(fn) }, label);

  const act = async (x, what, ask) => {
    if (ask && !confirm(ask)) return;
    const res = await api(`/admin/documents/${x.id}/${what}`, { method: "POST" });
    flash(what === "reprocess" ? `Re-read the file: ${res.chunks} passages.` : `Document ${what}d.`);
    reload(); loadReplaceChoices();
  };
  const del = async (x) => {
    if (!confirm(`Permanently delete "${x.title}" and its file? This cannot be undone.`)) return;
    await api(`/admin/documents/${x.id}`, { method: "DELETE" });
    flash("Document deleted.");
    reload();
  };
  const download = async (x) => {
    const res = await api(`/admin/documents/${x.id}/file`, { raw: true });
    const url = URL.createObjectURL(await res.blob());
    const a = el("a", { href: url, download: x.file_name });
    document.body.append(a); a.click(); a.remove(); URL.revokeObjectURL(url);
  };
  const preview = async (x) => {
    const d = await api(`/admin/documents/${x.id}/chunks?limit=100`);
    openModal(`${x.title} (${d.total} passages)`, el("div", {}, ...d.items.map((c) => el("div", { class: "mb-3" },
      el("div", { class: "small text-muted" }, `#${c.index + 1}` + (c.page ? ` | page ${c.page}` : "") + (c.keywords ? ` | keywords: ${c.keywords}` : "")),
      el("div", { class: "sg-pre" }, c.content)))));
  };
  const edit = async (x) => {
    const t = el("input", { class: "form-control mb-2", value: x.title });
    const s = el("input", { class: "form-control mb-2", value: x.source || "" });
    const d = el("textarea", { class: "form-control", rows: 3 }); d.value = x.description || "";
    const err = el("div", { class: "text-danger small mt-2", role: "alert" });
    const save = el("button", { class: "btn sg-send", onclick: async () => {
      try {
        await api(`/admin/documents/${x.id}`, { method: "PUT", json: { title: t.value, source: s.value, description: d.value } });
        modal.hide(); flash("Document updated."); reload();
      } catch (e) { err.textContent = e.message; }
    } }, "Save changes");
    openModal("Edit document", el("div", {}, el("label", { class: "form-label" }, "Title"), t,
      el("label", { class: "form-label" }, "Source"), s, el("label", { class: "form-label" }, "Description"), d, err), [save]);
  };

  const upload = el("form", { class: "sg-card mb-4", novalidate: true, onsubmit: async (e) => {
    e.preventDefault();
    msg.className = "small mt-2"; msg.textContent = "";
    if (!file.files.length) { msg.className = "small mt-2 text-danger"; msg.textContent = "Choose a PDF, DOCX or TXT file."; return; }
    const fd = new FormData();
    fd.append("file", file.files[0]);
    [["title", title], ["source", source], ["category", category], ["description", description], ["replaces_id", replaces]]
      .forEach(([k, i]) => i.value.trim() && fd.append(k, i.value.trim()));
    submit.disabled = true; msg.textContent = "Uploading and reading the file...";
    try {
      const doc = await api("/admin/documents", { method: "POST", form: fd });
      upload.reset(); msg.textContent = "";
      flash(`"${doc.title}" uploaded: ${doc.chunks} searchable passages.`);
      state.skip = 0; reload(); loadReplaceChoices();
    } catch (e2) { msg.className = "small mt-2 text-danger"; msg.textContent = e2.message; }
    finally { submit.disabled = false; }
  } });
  const submit = el("button", { class: "btn sg-send", type: "submit" }, "Upload");
  upload.append(el("h3", { class: "h6" }, "Upload a document (PDF, DOCX or TXT)"),
    el("div", { class: "row g-2" }, el("div", { class: "col-md-6" }, file), el("div", { class: "col-md-6" }, title),
      el("div", { class: "col-md-6" }, source), el("div", { class: "col-md-6" }, category),
      el("div", { class: "col-md-6" }, description), el("div", { class: "col-md-6" }, replaces)),
    el("div", { class: "mt-2" }, submit), msg);

  const filter = el("select", { class: "form-select w-auto", "aria-label": "Filter by status",
    onchange: () => { state.status = filter.value; state.skip = 0; reload(); } },
    el("option", { value: "" }, "All documents"), el("option", { value: "active" }, "Active"), el("option", { value: "archived" }, "Archived"));
  view.replaceChildren(el("div", { class: "d-flex justify-content-between align-items-center mb-3" },
    el("h2", { class: "h4 m-0" }, "Documents"), filter), upload, tableBox);
  reload(); loadReplaceChoices();
}

// ----------------------------------------------------------------------------- chat logs
async function chatView() {
  const view = $("view");
  const f = { q: "", found: "", pgpc: "", skip: 0, total: 0 };
  const tableBox = el("div");
  const q = el("input", { class: "form-control", type: "search", placeholder: "Search questions...", "aria-label": "Search questions" });
  const found = el("select", { class: "form-select w-auto", "aria-label": "Answer status" },
    el("option", { value: "" }, "All answers"), el("option", { value: "true" }, "Answered"), el("option", { value: "false" }, "Not found"));
  const pgpc = el("select", { class: "form-select w-auto", "aria-label": "PGPC related" },
    el("option", { value: "" }, "All questions"), el("option", { value: "true" }, "PGPC related"), el("option", { value: "false" }, "Not PGPC related"));
  const badge = (v, yes, no) => el("span", { class: "badge " + (v === true ? "text-bg-success" : v === false ? "text-bg-warning" : "text-bg-secondary") },
    v === true ? yes : v === false ? no : "n/a");

  const reload = () => guarded(async () => {
    const p = new URLSearchParams({ skip: f.skip, limit: PAGE });
    if (f.q) p.set("q", f.q); if (f.found) p.set("found", f.found); if (f.pgpc) p.set("pgpc_related", f.pgpc);
    const d = await api("/admin/chat/logs?" + p);
    f.total = d.total;
    const rows = d.items.map((r) => el("tr", { role: "button", onclick: () => detail(r), style: "cursor:pointer" },
      el("td", {}, when(r.asked_at)), el("td", { title: r.question }, r.question), el("td", {}, r.intent || ""),
      el("td", {}, badge(r.found, "Found", "Not found")), el("td", {}, badge(r.pgpc_related, "Yes", "No")),
      el("td", {}, el("button", { class: "btn btn-sm btn-outline-secondary", onclick: (e) => { e.stopPropagation(); transcript(r.session_id); } }, "Chat #" + r.session_id))));
    tableBox.replaceChildren(el("div", { class: "sg-table-wrap" }, el("table", { class: "table table-hover align-middle" },
      el("thead", {}, el("tr", {}, ...["Asked", "Question", "Intent", "Answer", "PGPC", ""].map((h) => el("th", {}, h)))),
      el("tbody", {}, rows.length ? rows : el("tr", {}, el("td", { colspan: 6, class: "text-muted p-3" }, "No questions match.")))), ), pager(f, reload));
  });
  const detail = (r) => openModal("Question and answer", el("div", {},
    el("h3", { class: "h6" }, "Question"), el("p", { class: "sg-pre" }, r.question),
    r.interpreted_as ? el("p", { class: "small text-muted" }, "Understood as: " + r.interpreted_as) : null,
    el("p", { class: "small text-muted" }, `Intent: ${r.intent || "?"} (${r.intent_confidence ?? "?"})`),
    el("h3", { class: "h6" }, "Answer"), el("p", { class: "sg-pre" }, r.answer || "(none)"),
    r.source ? el("p", { class: "small text-muted" }, "Source: " + r.source) : null));
  const transcript = (id) => guarded(async () => {
    const d = await api(`/admin/chat/sessions/${id}`);
    const del = el("button", { class: "btn btn-outline-danger", onclick: () => guarded(async () => {
      if (!confirm("Delete this whole conversation?")) return;
      await api(`/admin/chat/sessions/${id}`, { method: "DELETE" });
      modal.hide(); flash("Conversation deleted."); reload();
    }) }, "Delete conversation");
    openModal(`Conversation #${id}` + (d.session.expired ? " (expired)" : ""), el("div", {}, ...d.messages.map((m) =>
      el("div", { class: "mb-2" }, el("div", { class: "small text-muted" }, `${m.role === "user" ? "Visitor" : "SmartGuide"} | ${when(m.created_at)}`),
        el("div", { class: "sg-pre" }, m.message)))), [del]);
  });
  const purge = () => guarded(async () => {
    if (!confirm("Delete expired conversations older than the retention period?")) return;
    const r = await api("/admin/chat/expired-sessions", { method: "DELETE" });
    flash(`${r.deleted} old conversation(s) deleted.`); reload();
  });

  let timer;
  q.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => { f.q = q.value.trim(); f.skip = 0; reload(); }, 300); });
  found.addEventListener("change", () => { f.found = found.value; f.skip = 0; reload(); });
  pgpc.addEventListener("change", () => { f.pgpc = pgpc.value; f.skip = 0; reload(); });
  view.replaceChildren(
    el("div", { class: "d-flex justify-content-between align-items-center mb-3" }, el("h2", { class: "h4 m-0" }, "Chat logs"),
      el("button", { class: "btn btn-sm btn-outline-danger", onclick: purge }, "Purge old expired chats")),
    el("div", { class: "d-flex flex-wrap gap-2 mb-3" }, q, found, pgpc),
    tableBox);
  reload();
}

// ----------------------------------------------------------------------------- to improve (weekly review)
// Questions nobody could answer (grouped, with a count) and answers students marked "not helpful". Each unanswered
// question has buttons that open the FAQ / Quick link form with the question already filled in.
async function improveView() {
  const view = $("view");
  const intro = el("p", { class: "text-muted" }, "Work through this list each week: add a FAQ, add a quick link, or fix the handbook text.");
  view.replaceChildren(el("h2", { class: "h4 mb-1" }, "To improve"), intro, el("p", { class: "text-muted" }, "Loading..."));
  await guarded(async () => {
    const [un, bad] = await Promise.all([api("/admin/chat/unanswered?limit=30"), api("/admin/chat/feedback?value=down&limit=15")]);
    const unRows = un.items.map((r) => el("tr", {},
      el("td", {}, String(r.count)), el("td", {}, r.question), el("td", { class: "small text-muted" }, when(r.last_asked)),
      el("td", { class: "text-nowrap text-end" },
        el("button", { class: "btn btn-sm btn-outline-primary me-1",
                       onclick: () => guarded(() => openForm("faqs", null, improveView, { question: r.question })) }, "Add FAQ"),
        el("button", { class: "btn btn-sm btn-outline-secondary",
                       onclick: () => guarded(() => openForm("quick-links", null, improveView, { title: r.question, keywords: r.question })) }, "Add link"))));
    const badRows = bad.items.map((r) => el("tr", {},
      el("td", {}, r.question || ""), el("td", { class: "small" }, (r.answer || "").slice(0, 140) + ((r.answer || "").length > 140 ? "..." : "")),
      el("td", { class: "small" }, r.comment || ""), el("td", { class: "small text-muted" }, when(r.created_at))));
    const table = (head, rows, empty) => el("div", { class: "sg-table-wrap mb-4" }, el("table", { class: "table table-hover align-middle" },
      el("thead", {}, el("tr", {}, ...head.map((h) => el("th", {}, h)))),
      el("tbody", {}, rows.length ? rows : el("tr", {}, el("td", { colspan: head.length, class: "text-muted p-3" }, empty)))));
    view.replaceChildren(el("h2", { class: "h4 mb-1" }, "To improve"), intro,
      el("h3", { class: "h6 text-muted" }, `Questions the chatbot could not answer (${un.total})`),
      table(["Times", "Question", "Last asked", ""], unRows, "Nothing unanswered yet."),
      el("h3", { class: "h6 text-muted" }, `Answers students marked "not helpful" (${bad.total})`),
      table(["Question", "Answer given", "What was wrong", "When"], badRows, "No thumbs-down votes yet."));
  });
}

// ----------------------------------------------------------------------------- navigation
const VIEWS = [["overview", "Overview", overviewView], ["improve", "To improve", improveView], ["chat", "Chat logs", chatView],
               ["documents", "Documents", documentsView]];
function buildNav() {
  const nav = $("nav");
  const add = (key, label, fn) => nav.append(el("button", { type: "button", "data-key": key, onclick: () => show(key, fn) }, label));
  add(...VIEWS[0]);
  add(...VIEWS[1]);
  add(...VIEWS[2]);
  let group = "";
  for (const [key, cfg] of Object.entries(MODULES)) {
    if (cfg.group !== group) { group = cfg.group; nav.append(el("div", { class: "sg-nav-h" }, group)); }
    add(key, cfg.label, () => crudView(key));
  }
  nav.append(el("div", { class: "sg-nav-h" }, "Files"));
  add(...VIEWS[3]);
}
function show(key, fn) {
  $("flash").replaceChildren();
  document.querySelectorAll("#nav button").forEach((b) => b.classList.toggle("active", b.dataset.key === key));
  fn();
  location.hash = key;
}

// ----------------------------------------------------------------------------- start (admin check first)
(async () => {
  if (!sessionStorage.getItem(TOKEN_KEY)) return logout();
  const res = await fetch("/api/v1/auth/me", { headers: { Authorization: "Bearer " + sessionStorage.getItem(TOKEN_KEY) } });
  if (!res.ok) return logout();
  const me = await res.json();
  if (me.role !== "admin") return logout();
  $("adminWho").textContent = "Signed in as " + me.username;
  buildNav();
  const start = location.hash.slice(1);
  const known = { overview: overviewView, improve: improveView, chat: chatView, documents: documentsView };
  for (const k of Object.keys(MODULES)) known[k] = () => crudView(k);
  show(known[start] ? start : "overview", known[start] || overviewView);
})();
$("logoutBtn").addEventListener("click", logout);
