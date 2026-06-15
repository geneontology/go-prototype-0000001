// Wrapper around <go-gocam-viewer> that:
//   1. Loads model + provenance from same-directory JSON files
//   2. Injects the model via setModelData (no api fetch)
//   3. Surfaces both node AND edge clicks (upstream emits nodeClick only —
//      we reach into the shadow DOM for the cytoscape instance to wire
//      edge clicks ourselves)
//   4. Renders a custom provenance panel keyed by assertion id

const SOURCE_META = {
  literature:        { emoji: "\u{1F4DA}",          label: "Literature" },
  go_annotation:     { emoji: "\u{1F5C2}\u{FE0F}",  label: "GO annotation" },
  alliance:          { emoji: "\u{1F9EC}",          label: "Alliance" },
  amigo:             { emoji: "\u{1F50D}",          label: "AmiGO" },
  orthology:         { emoji: "\u{2197}\u{FE0F}",   label: "Orthology" },
  pathway_resource:  { emoji: "\u{1F6E4}\u{FE0F}",  label: "Pathway" },
  expert_review:     { emoji: "\u{2714}\u{FE0F}",   label: "Expert review" },
  instinct:          { emoji: "\u{26A0}\u{FE0F}",   label: "Instinct" },
  // Weakest tier — a raw reading of the figure (below instinct). Flagged
  // (🚩) like a warning so the curator treats it as "verify this".
  figure:            { emoji: "\u{1F6A9}",          label: "Figure" },
  go_term_request:   { emoji: "\u{2753}",           label: "GO term request" },
};

const SLOT_PRETTY = {
  enabled_by:          "enabled by",
  molecular_function:  "molecular function",
  part_of:             "part of (BP)",
  occurs_in:           "occurs in (CC)",
  has_input:           "has input",
  has_output:          "has output",
  causal:              "causal edge",
};

// Local-only "curator actions" store. Keyed per model so a curator's
// confirm / dispute / comment actions persist across page reloads in the
// same browser. v1 will swap this for a real curator-review backend.
const ACTIONS_STORE_KEY = (modelId) => `gocam-proto-actions/${modelId}`;

// GH issue-forms bridge: every curator action also opens a pre-populated
// GitHub Issue Form so the curator's click escapes localStorage. The
// user's GH auth in the browser is the auth — no backend required.
const REPO = "geneontology/go-prototype-0000001";
const CURATOR_ACTION_TEMPLATE = "curator-action.yml";

// Per-run id derived from the URL: `/runs/<run-id>/`. The viewer page is
// served from that path on GH Pages.
function inferRunId() {
  const m = window.location.pathname.match(/\/runs\/([^/]+)\/?(?:index\.html)?$/);
  return m ? m[1] : "";
}
const CURRENT_RUN_ID = inferRunId();

function curatorActionIssueUrl({ actionKind, assertionId, slot, srcSummary, note, curator }) {
  const params = new URLSearchParams({ template: CURATOR_ACTION_TEMPLATE });
  if (actionKind)     params.set("action_kind", actionKind);
  if (CURRENT_RUN_ID) params.set("model_run_id", CURRENT_RUN_ID);
  if (assertionId)    params.set("assertion_id", assertionId);
  if (slot)           params.set("slot", slot);
  if (srcSummary)     params.set("current_source", srcSummary);
  if (note)           params.set("note", note);
  if (curator?.orcid)    params.set("curator_orcid", curator.orcid);
  if (curator?.nickname) params.set("curator_nickname", curator.nickname);
  // Help GH pre-render a usable issue title.
  if (actionKind && assertionId) {
    const shortId = assertionId.split("/").slice(-2).join("/");
    params.set("title", `[curator] ${actionKind} ${shortId}`);
  }
  return `https://github.com/${REPO}/issues/new?${params.toString()}`;
}

// v2 provenance stores a LIST of sources per assertion key so one statement
// can carry separately-attributed claims (id-resolution vs the biological
// fact; #40). v1 files stored a single object. Normalize either shape to an
// array so the rest of the viewer is version-agnostic.
function srcList(v) {
  return Array.isArray(v) ? v : (v ? [v] : []);
}

function summarizeSource(src) {
  if (!src) return "";
  if (Array.isArray(src)) {
    return src.map(summarizeSource).filter(Boolean).join("\n---\n");
  }
  const lines = [];
  if (src.source_type)   lines.push(`source_type: ${src.source_type}`);
  if (src.source_id)     lines.push(`source_id:   ${src.source_id}`);
  if (src.tool_name)     lines.push(`tool_name:   ${src.tool_name}`);
  if (src.snippet)       lines.push(`snippet:     ${src.snippet}`);
  if (src.justification) lines.push(`justification: ${src.justification}`);
  return lines.join("\n");
}

function openInNewTab(url) {
  const w = window.open(url, "_blank", "noopener,noreferrer");
  if (!w) {
    // Popup blocked — fallback to nav in current tab via a temp anchor.
    const a = document.createElement("a");
    a.href = url; a.target = "_blank"; a.rel = "noopener noreferrer";
    document.body.appendChild(a); a.click(); a.remove();
  }
}

function loadActions(modelId) {
  try {
    return JSON.parse(localStorage.getItem(ACTIONS_STORE_KEY(modelId)) || "[]");
  } catch { return []; }
}
function saveActions(modelId, actions) {
  try { localStorage.setItem(ACTIONS_STORE_KEY(modelId), JSON.stringify(actions)); }
  catch { /* private browsing / quota — silently drop */ }
}
function recordAction(modelId, assertionId, kind, payload, curator) {
  const actions = loadActions(modelId);
  actions.push({
    assertionId, kind, payload: payload || null, ts: new Date().toISOString(),
    curator: curator ? { nickname: curator.nickname, orcid: curator.orcid } : null,
  });
  saveActions(modelId, actions);
  notifyActionsChanged();
  return actions;
}
function actionsFor(modelId, assertionId) {
  return loadActions(modelId).filter((a) => a.assertionId === assertionId);
}

function notifyActionsChanged() {
  document.dispatchEvent(new CustomEvent("gocam-proto-actions-changed"));
}

/* ----------------------------------------------------- curator identity (#52 pt5)
   The static GH-Pages site has no auth, so a chosen curator is SELF-ASSERTED /
   unverified — verified attribution into the LinkML ProvenanceInfo.contributor
   only happens via the authenticated GitHub-issue -> re-run path. The picker is
   populated from the vendored allow-edit roster (assets/curators.json, built from
   go-site users.yaml by gocam_prototype/curators.py). */
const CURATOR_KEY = "gocam-proto-curator";
let CURATORS = [];

function getCurrentCurator() {
  try { return JSON.parse(localStorage.getItem(CURATOR_KEY) || "null"); } catch { return null; }
}
function setCurrentCurator(c) {
  try { localStorage.setItem(CURATOR_KEY, JSON.stringify(c)); } catch { /* ignore */ }
  document.dispatchEvent(new CustomEvent("gocam-proto-curator-changed"));
}
async function loadCurators() {
  if (CURATORS.length) return CURATORS;
  try {
    const r = await fetch("../../assets/curators.json");
    if (r.ok) CURATORS = await r.json();
  } catch { /* offline / missing — picker just shows none */ }
  return CURATORS;
}

// Modal picker — resolves to the chosen {nickname, orcid, github} or null.
async function pickCurator() {
  const curators = await loadCurators();
  return new Promise((resolve) => {
    document.querySelector("#curator-modal")?.remove();
    const m = document.createElement("div");
    m.id = "curator-modal";
    m.className = "modal-backdrop";
    const options = curators
      .map((c, i) => `<option value="${i}">${escapeHtml(c.nickname)}</option>`).join("");
    m.innerHTML = `
      <div class="modal" role="dialog" aria-modal="true" aria-label="Identify yourself">
        <h3>Who are you?</h3>
        <p>Pick your name — GO curators with edit access. Stored locally and
           <strong>self-asserted / unverified</strong>; only actions you escalate to a
           GitHub issue carry verified attribution.</p>
        <select class="modal-input curator-select">
          <option value="" disabled selected>Select a curator…</option>
          ${options}
        </select>
        <div class="modal-actions">
          <button type="button" class="curator-btn cancel">Cancel</button>
          <button type="button" class="curator-btn primary submit">Save</button>
        </div>
      </div>`;
    const sel = m.querySelector(".curator-select");
    const done = (val) => { m.remove(); resolve(val); };
    m.querySelector(".submit").addEventListener("click", () =>
      done(sel.value === "" ? null : curators[Number(sel.value)]));
    m.querySelector(".cancel").addEventListener("click", () => done(null));
    m.addEventListener("click", (ev) => { if (ev.target === m) done(null); });
    document.body.appendChild(m);
  });
}

// Ensure a curator is chosen (prompting once). Returns it, or null if declined.
async function ensureCurator() {
  let c = getCurrentCurator();
  if (!c) {
    c = await pickCurator();
    if (c) setCurrentCurator(c);
  }
  return c;
}

let CURRENT_MODEL_ID = null;  // populated in main()

async function main() {
  installOffsiteLinkDefault();

  const [viewerData, prov] = await Promise.all([
    fetchJson("viewer.json"),
    fetchJson("provenance.json"),
  ]);

  CURRENT_MODEL_ID = viewerData.id || "unknown-model";
  TERM_LABELS = buildTermLabelIndex(viewerData);

  // Pretty the page title from the model annotations.
  const titleAnn = (viewerData.annotations || []).find(a => a.key === "title");
  document.querySelector("#run-title").textContent =
    titleAnn?.value || viewerData.id || "Run";

  await customElements.whenDefined("go-gocam-viewer");
  const viewerEl = document.querySelector("#viewer");

  hideBuiltinSidebar(viewerEl);
  await viewerEl.setModelData(viewerData);

  // Build a label index for the panel (so subject/object labels in edges
  // resolve to human-readable text instead of the bare IRI).
  const labelIndex = buildLabelIndex(viewerData);

  // Node-click is upstream-supported — wire it directly.
  viewerEl.addEventListener("nodeClick", (e) => {
    handleNodeClick(e.detail, prov, labelIndex);
  });

  // Edge-click is NOT upstream-supported. Try multiple paths to the
  // cytoscape instance; fall back to wiring on first node click.
  const cy = await wireEdgeClicks(viewerEl, prov, labelIndex);
  if (cy) {
    emphasizeCausalEdges(cy);
    keepGraphFitted(cy, viewerEl);
    installSourceChipsOverlay(cy, prov, viewerEl, labelIndex);
  }

  installModelActionsHeader();
  installToastHost();
}

// Model-level "Propose changes" affordance, shown above the (per-assertion)
// provenance panel. Surfaces the count of recorded actions for the current
// model so a curator can see at a glance whether they've started reviewing.
function installModelActionsHeader() {
  // Attach into the page header rather than the prov-panel; the panel gets
  // wiped on every renderPanel() call and the run-layout is a fixed grid.
  const runHeader = document.querySelector(".run-header");
  if (!runHeader) return;
  const header = document.createElement("div");
  header.id = "model-actions-header";
  header.className = "model-actions-header";
  const refresh = () => {
    const count = loadActions(CURRENT_MODEL_ID).length;
    header.innerHTML = `
      <button type="button" class="curator-btn primary" data-action="propose">
        \u{1F4DD} Propose changes
      </button>
      <span class="pending-count" ${count ? "" : "hidden"}>${count} pending action${count === 1 ? "" : "s"}</span>
    `;
  };
  refresh();
  document.addEventListener("gocam-proto-actions-changed", refresh);
  runHeader.appendChild(header);
  header.addEventListener("click", (ev) => {
    const btn = ev.target.closest("[data-action='propose']");
    if (!btn) return;
    const actions = loadActions(CURRENT_MODEL_ID);
    showProposeChangesModal(actions);
  });
}

function showProposeChangesModal(actions) {
  if (!actions.length) {
    showModal({
      title: "Propose changes",
      body: "No pending actions yet. Use the per-assertion buttons (confirm / dispute / comment / add evidence / edit relation) on the source cards to mark things up; once you have a few, this button bundles them into a single GitHub issue for review.",
    });
    return;
  }
  const noteBody = renderActionsAsMarkdown(actions);
  const issueUrl = curatorActionIssueUrl({
    actionKind: "propose-changes-batch",
    assertionId: "model",
    slot: "model",
    srcSummary: "",
    note: noteBody,
  });
  // Reuse showModal for visual consistency, then append a primary CTA.
  document.querySelector("#dummy-modal")?.remove();
  const m = document.createElement("div");
  m.id = "dummy-modal";
  m.className = "modal-backdrop";
  m.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true" aria-label="Propose changes">
      <h3>Propose changes — ${actions.length} pending action${actions.length === 1 ? "" : "s"}</h3>
      <p>Bundle all pending actions into a single curator-review issue. Your local
         records stay in place; the issue is the durable, reviewable artifact.</p>
      <pre class="modal-actions-preview">${escapeHtml(noteBody)}</pre>
      <div class="modal-actions">
        <a class="curator-btn primary" href="${issueUrl}" target="_blank" rel="noopener noreferrer">Open as GitHub issue ↗</a>
        <button type="button" class="curator-btn">Close</button>
      </div>
    </div>
  `;
  m.addEventListener("click", (ev) => {
    if (ev.target === m) m.remove();
    if (ev.target.closest("button.curator-btn")) m.remove();
    // Anchor click — let it open the new tab, then dismiss.
    if (ev.target.closest("a.curator-btn")) setTimeout(() => m.remove(), 100);
  });
  document.body.appendChild(m);
}

function renderActionsAsMarkdown(actions) {
  // Most recent first; cap at 50 to keep the issue URL within reasonable
  // limits (GitHub silently truncates very long query strings).
  const recent = actions.slice(-50).reverse();
  const lines = [
    `Curator submitted ${actions.length} pending action${actions.length === 1 ? "" : "s"} on \`${CURRENT_RUN_ID || "(unknown run)"}\`.`,
    "",
    "| # | Action | Assertion | Note | Timestamp |",
    "| - | ------ | --------- | ---- | --------- |",
  ];
  recent.forEach((a, i) => {
    const note = (a.payload || "").replace(/\|/g, "\\|").replace(/\n/g, " ⏎ ");
    lines.push(`| ${i + 1} | ${a.kind} | \`${a.assertionId}\` | ${note} | ${a.ts} |`);
  });
  return lines.join("\n");
}

function installToastHost() {
  if (document.querySelector("#toast-host")) return;
  const host = document.createElement("div");
  host.id = "toast-host";
  host.className = "toast-host";
  document.body.appendChild(host);
}

function toast(message) {
  installToastHost();
  const host = document.querySelector("#toast-host");
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = message;
  host.appendChild(el);
  setTimeout(() => el.classList.add("fade-out"), 2200);
  setTimeout(() => el.remove(), 2800);
}

function showModal({ title, body, details }) {
  // Replace any existing modal.
  document.querySelector("#dummy-modal")?.remove();
  const m = document.createElement("div");
  m.id = "dummy-modal";
  m.className = "modal-backdrop";
  m.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true" aria-label="${escapeHtml(title)}">
      <h3>${escapeHtml(title)}</h3>
      <p>${escapeHtml(body)}</p>
      <div class="modal-actions">
        <button type="button" class="curator-btn">Close</button>
      </div>
    </div>
  `;
  if (Array.isArray(details) && details.length) {
    const list = document.createElement("ul");
    list.className = "modal-details";
    for (const a of details.slice(-10).reverse()) {
      const li = document.createElement("li");
      li.innerHTML = `<code>${escapeHtml(a.kind)}</code> on <code>${escapeHtml(a.assertionId)}</code> at <time>${escapeHtml(a.ts)}</time>`;
      if (a.payload) {
        const note = document.createElement("blockquote");
        note.textContent = a.payload;
        li.appendChild(note);
      }
      list.appendChild(li);
    }
    m.querySelector(".modal").insertBefore(list, m.querySelector(".modal-actions"));
  }
  m.addEventListener("click", (ev) => {
    if (ev.target === m || ev.target.closest("button.curator-btn")) m.remove();
  });
  document.body.appendChild(m);
}

// In-page text-input modal — replaces the browser-native prompt() (which shows
// "geneontology.github.io says …"). Returns a Promise resolving to the trimmed
// text, or null if cancelled. (#52 pt6)
function textInputModal({ title, placeholder = "", submitLabel = "Submit" }) {
  return new Promise((resolve) => {
    document.querySelector("#input-modal")?.remove();
    const m = document.createElement("div");
    m.id = "input-modal";
    m.className = "modal-backdrop";
    m.innerHTML = `
      <div class="modal" role="dialog" aria-modal="true" aria-label="${escapeHtml(title)}">
        <h3>${escapeHtml(title)}</h3>
        <textarea class="modal-input" rows="3" placeholder="${escapeHtml(placeholder)}"></textarea>
        <div class="modal-actions">
          <button type="button" class="curator-btn cancel">Cancel</button>
          <button type="button" class="curator-btn primary submit">${escapeHtml(submitLabel)}</button>
        </div>
      </div>`;
    const ta = m.querySelector(".modal-input");
    const done = (val) => { m.remove(); resolve(val); };
    m.querySelector(".submit").addEventListener("click", () => done(ta.value.trim() || null));
    m.querySelector(".cancel").addEventListener("click", () => done(null));
    m.addEventListener("click", (ev) => { if (ev.target === m) done(null); });
    ta.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" && (ev.metaKey || ev.ctrlKey)) done(ta.value.trim() || null);
      else if (ev.key === "Escape") done(null);
    });
    document.body.appendChild(m);
    ta.focus();
  });
}

// Build {iri -> human-readable label} from viewer.json's individuals and objects.
function buildLabelIndex(viewerData) {
  const index = {};
  for (const ind of viewerData.individuals || []) {
    const t = (ind.type || [])[0];
    if (t?.label) index[ind.id] = t.label;
  }
  return index;
}

// CURIE -> label, built from the LinkML objects[] cache surfaced into the
// viewer individuals' type[] entries (every GO/gene/ECO/predicate term used).
// Lets the panel show "GO:0004510 — tryptophan 5-monooxygenase activity" for
// any cited CURIE, not only ones carrying an explicit term_label (#52 pt3).
let TERM_LABELS = {};
function buildTermLabelIndex(viewerData) {
  const m = {};
  for (const ind of viewerData.individuals || []) {
    for (const t of ind.type || []) {
      if (t?.id && t?.label && t.id !== t.label) m[t.id] = t.label;
    }
  }
  return m;
}
function termLabel(curie) {
  return (curie && TERM_LABELS[curie]) || null;
}

// Walk Cytoscape edges and visually distinguish causal predicates (RO CURIEs) from
// the structural slot edges (RO:0002333 enabled_by, BFO:0000050 part_of,
// BFO:0000066 occurs_in). Doing it here, outside the upstream component, keeps
// our taxonomy intent local — no fork required.
function emphasizeCausalEdges(cy) {
  cy.edges().forEach((edge) => {
    const data = edge.data() || {};
    const property = data.property || data.predicate || data.label || "";
    const isCausal = /^RO:00/.test(property) &&
      property !== "RO:0002333" /* enabled_by */;
    if (isCausal) {
      edge.style({
        "width": 3.5,
        "line-color": "#6a1b9a",
        "target-arrow-color": "#6a1b9a",
        "z-index": 5,
      });
    } else if (property === "RO:0002333") {
      edge.style({
        "line-color": "#90a4ae",
        "target-arrow-color": "#90a4ae",
        "line-style": "solid",
        "width": 1.5,
      });
    } else if (property === "BFO:0000050" || property === "BFO:0000066") {
      edge.style({
        "line-color": "#cfd8dc",
        "target-arrow-color": "#cfd8dc",
        "line-style": "dashed",
        "width": 1.5,
      });
    }
  });
  cy.style().update();
}

/* --------------------------------------------- evidence-chip overlay ---- */

// Canonical render order matches the landing-page legend.
// Descending evidence strength. 'figure' (a raw reading of the figure) is the
// WEAKEST tier — below 'instinct' — so it sorts last among evidence, and
// edgeChipEmoji shows it only when nothing stronger is attached.
const CHIP_SOURCE_ORDER = [
  "literature", "go_annotation", "alliance", "amigo",
  "orthology", "pathway_resource", "expert_review", "instinct", "figure", "go_term_request",
];
// The four slots a GoCamBuilder activity may carry provenance for.
const CHIP_SLOTS = ["enabled_by", "molecular_function", "part_of", "occurs_in"];

function nodeChipEmojis(prov, nodeId) {
  const seen = new Set();
  for (const slot of CHIP_SLOTS) {
    for (const a of srcList(prov.assertions?.[`${nodeId}/${slot}`])) {
      if (a?.source_type) seen.add(a.source_type);
    }
  }
  for (const a of srcList(prov.assertions?.[nodeId])) {
    if (a?.source_type) seen.add(a.source_type);
  }
  return CHIP_SOURCE_ORDER
    .filter((t) => seen.has(t))
    .map((t) => SOURCE_META[t]?.emoji)
    .filter(Boolean);
}

function edgeChipEmoji(prov, edge) {
  const data = edge.data() || {};
  const src = data.source || data.subject;
  const tgt = data.target || data.object;
  if (!src || !tgt) return null;
  // A causal edge carries its sources under <src>/causal/<tgt>. A has_input /
  // has_output edge points at a molecule individual whose IRI *is* the
  // assertion key (<activity>/has_input|has_output/<molecule>), so read the
  // sources off the object. (Slot edges to gene-product/BP/CC are left to the
  // aggregated node chip, so we only fall back for has_input/has_output.)
  let sources = srcList(prov.assertions?.[`${src}/causal/${tgt}`]);
  if (!sources.length) {
    // has_input/has_output: the molecule individual (whose IRI is the key) may
    // be on either end depending on edge orientation (has_input is drawn
    // molecule→activity, so the key is the source there).
    for (const end of [tgt, src]) {
      if (end && (end.includes("/has_input/") || end.includes("/has_output/"))) {
        const s = srcList(prov.assertions?.[end]);
        if (s.length) { sources = s; break; }
      }
    }
  }
  // A causal edge may carry several sources; show the highest-priority type's
  // emoji (CHIP_SOURCE_ORDER is the canonical legend order).
  const types = new Set(sources.map((a) => a?.source_type).filter(Boolean));
  if (!types.size) return null;
  const t = CHIP_SOURCE_ORDER.find((x) => types.has(x));
  return t ? (SOURCE_META[t]?.emoji || null) : null;
}

// Paint per-node and per-edge evidence-type emoji onto an HTML overlay
// stacked over the cytoscape canvas. pointer-events: none so clicks
// pass through. Re-renders on pan / zoom / resize.
// A chip click opens the panel (via the node/edge handler) and then draws the
// curator's eye to the supporting source cards — scroll the panel into view and
// briefly flash its source cards. (#52 pt8)
function chipOpenPanel(openHandler) {
  openHandler();
  const panel = document.querySelector("#provenance-panel");
  if (!panel) return;
  panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
  panel.querySelectorAll(".source-card").forEach((c) => {
    c.classList.remove("flash");
    void c.offsetWidth;        // restart the CSS animation
    c.classList.add("flash");
    c.addEventListener("animationend", () => c.classList.remove("flash"), { once: true });
  });
}

function installSourceChipsOverlay(cy, prov, viewerEl, labelIndex) {
  const host = viewerEl.parentElement; // .viewer-pane
  if (!host) return;
  if (getComputedStyle(host).position === "static") host.style.position = "relative";

  const overlay = document.createElement("div");
  overlay.className = "source-chips-overlay";
  host.appendChild(overlay);

  // Position the overlay so its (0,0) matches cytoscape's container origin.
  function syncOverlayRect() {
    const cyContainer = cy.container();
    if (!cyContainer) return;
    const hr = host.getBoundingClientRect();
    const cr = cyContainer.getBoundingClientRect();
    overlay.style.left = `${cr.left - hr.left}px`;
    overlay.style.top  = `${cr.top  - hr.top }px`;
    overlay.style.width  = `${cr.width}px`;
    overlay.style.height = `${cr.height}px`;
  }

  function chipEl(emojis, className, onClick) {
    const el = document.createElement("span");
    el.className = `source-chips ${className}`;
    el.textContent = emojis.join("");
    if (onClick) {
      // Re-enable pointer events on the chip itself (the overlay stays
      // click-through) so it links into the panel. (#52 pt8)
      el.classList.add("clickable");
      el.title = "Show this evidence in the panel";
      el.addEventListener("click", (ev) => { ev.stopPropagation(); onClick(); });
    }
    return el;
  }

  function render() {
    syncOverlayRect();
    overlay.innerHTML = "";

    cy.nodes().forEach((node) => {
      const id = node.id();
      // Render chips only on activity individuals: gomodel:<run>/<activity>
      // (Not on slot sub-individuals, which carry a third path segment.)
      if (!/^gomodel:[^/]+\/[^/]+$/.test(id)) return;
      const emojis = nodeChipEmojis(prov, id);
      if (!emojis.length) return;
      const bbox = node.renderedBoundingBox({ includeLabels: false });
      const el = chipEl(emojis, "node-chip", () => chipOpenPanel(() => handleNodeClick(node, prov, labelIndex)));
      // Anchor outside the top-right corner of the node — clear of the
      // edge midpoints where the per-edge chips sit.
      el.style.left = `${bbox.x2 + 4}px`;
      el.style.top  = `${bbox.y1 - 6}px`;
      overlay.appendChild(el);
    });

    cy.edges().forEach((edge) => {
      const e = edgeChipEmoji(prov, edge);
      if (!e) return;
      const mid = edge.renderedMidpoint();
      if (!mid || !Number.isFinite(mid.x)) return;
      const el = chipEl([e], "edge-chip", () => chipOpenPanel(() => handleEdgeClick(edge, prov, labelIndex)));
      el.style.left = `${mid.x}px`;
      el.style.top  = `${mid.y}px`;
      overlay.appendChild(el);
    });
  }

  render();
  cy.on("pan zoom viewport position", render);
  if (typeof ResizeObserver === "function") {
    new ResizeObserver(render).observe(host);
  } else {
    window.addEventListener("resize", render);
  }
}

/* --------------------------------------------- shadow-DOM customisations */

// `<go-gocam-viewer>` declares `shadow: true` (gocam-viewer.tsx:56) and
// internally renders `<go-gocam-viewer-sidebar>` (line 809). The built-in
// sidebar exposes PMID / AmiGO / WormBase links that open same-tab and
// competes with our own custom provenance panel. Inject a <style> into the
// shadow root to hide it. show-legend="false" already gates the legend.
function hideBuiltinSidebar(viewerEl) {
  if (!viewerEl?.shadowRoot) return;
  const css = `
    go-gocam-viewer-sidebar { display: none !important; }
    /* The viewer splits its area into an 8/12 graph panel + a 4/12 activities
       panel, and sizes the graph panel to its CONTENT height — so the graph
       underfills the column width (a ~1/3 dead strip on the right, next to our
       provenance panel) and overflows vertically. We render our OWN provenance
       panel, so hand the full width+height to the graph. The whole ancestor
       chain needs an explicit height or the inner height:100% collapses the
       canvas to 0. Class names per @geneontology/web-components 1.0.0, verified
       against the live shadow DOM. */
    :host { display: block; width: 100%; height: 100%; }
    .gocam-graph-and-activities-container { width: 100% !important; height: 100% !important; }
    .panel.w-4 { display: none !important; }   /* built-in activities list — superseded by our panel */
    .panel.w-8 { width: 100% !important; }     /* graph panel → full column width */
    .panel, .panel-body, .gocam-graph { height: 100% !important; }
  `;
  const sheet = document.createElement("style");
  sheet.setAttribute("data-injected-by", "go-prototype-viewer-wrapper");
  sheet.textContent = css;
  viewerEl.shadowRoot.appendChild(sheet);
}

// Audit + default any off-site anchor click to `target=_blank` + `rel=noopener`,
// so future links anywhere on the page inherit the behaviour without per-call
// wiring. Same-origin links are left alone (so '← all runs' still navigates
// in-tab). Anchors that already declare a target are not touched.
function installOffsiteLinkDefault() {
  document.addEventListener("click", (ev) => {
    const a = ev.target instanceof Element ? ev.target.closest("a[href]") : null;
    if (!a || a.target) return;
    const href = a.getAttribute("href");
    if (!href || href.startsWith("#")) return;
    try {
      const url = new URL(href, window.location.href);
      if (url.origin === window.location.origin) return;
      a.target = "_blank";
      a.rel = a.rel ? `${a.rel} noopener noreferrer` : "noopener noreferrer";
    } catch {
      /* relative or otherwise non-URL href — leave it */
    }
  }, /* useCapture */ true);
}

async function fetchJson(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`fetch ${path}: HTTP ${r.status}`);
  return r.json();
}

/* -------------------------------------------------------- cytoscape access */

async function wireEdgeClicks(viewerEl, prov, labelIndex) {
  let cy = null;
  for (let attempt = 0; attempt < 60 && !cy; attempt++) {
    cy = findCy(viewerEl);
    if (!cy) await sleep(100);
  }
  if (cy) {
    attachEdgeHandlers(cy, prov, labelIndex);
    return cy;
  }
  console.warn("Could not reach cytoscape instance after 6s; falling back to first-node-click wiring.");
  let bootstrappedCy = null;
  viewerEl.addEventListener("nodeClick", function bootstrap(e) {
    const detail = e.detail;
    const node = (detail && typeof detail.target?.id === "function") ? detail.target : detail;
    bootstrappedCy = node?.cy && typeof node.cy === "function" ? node.cy() : null;
    if (bootstrappedCy) {
      attachEdgeHandlers(bootstrappedCy, prov, labelIndex);
      emphasizeCausalEdges(bootstrappedCy);
      viewerEl.removeEventListener("nodeClick", bootstrap);
    }
  });
  return null;
}

function findCy(viewerEl) {
  // Stencil exposes class fields on the element itself.
  if (viewerEl.cy && typeof viewerEl.cy.edges === "function") return viewerEl.cy;
  // Otherwise look inside the shadow DOM for an element that cytoscape attached state to.
  const root = viewerEl.shadowRoot;
  if (!root) return null;
  for (const el of root.querySelectorAll("*")) {
    if (el._cyreg?.cy) return el._cyreg.cy;
    if (el.__cy__) return el.__cy__;
  }
  return null;
}

function attachEdgeHandlers(cy, prov, labelIndex) {
  if (cy._gocamProtoWired) return;
  cy._gocamProtoWired = true;
  cy.edges().on("tap", (evt) => handleEdgeClick(evt.target, prov, labelIndex));
}

// The cytoscape canvas inside <go-gocam-viewer> ends up zoomed so the nodes
// overflow vertically yet only fill the left part of the column — a big gap on
// the right, next to the provenance panel (see issue feedback). Force cytoscape
// to fill its column and stay fitted: resize() picks up the real pixel
// dimensions, fit() re-centers/zooms the graph to the pane.
//
// CRITICAL: only fit once the component's layout has positioned the nodes. A
// fit() against an empty / degenerate bounding box (pre-layout, all nodes at
// 0,0) throws the view off-screen and the component never recovers it — so we
// guard on a finite bounding box and (re)fit on cytoscape's `layoutstop`.
function keepGraphFitted(cy, viewerEl) {
  const pane = (viewerEl.closest && viewerEl.closest(".viewer-pane")) || viewerEl.parentElement;
  const refit = () => {
    try {
      if (!cy || (cy.destroyed && cy.destroyed())) return;
      const els = cy.elements();
      if (els.length === 0) return;
      const bb = els.boundingBox();
      if (!bb || !isFinite(bb.w) || bb.w <= 0 || bb.h <= 0) return;
      cy.resize();
      cy.fit(els, 28); // 28px padding around the graph
    } catch { /* cy detached / not ready — ignore */ }
  };
  // Re-fit whenever the component finishes (re)laying out the graph; our handler
  // is registered after the component's, so our fit has the last word.
  cy.on("layoutstop", refit);
  cy.ready(refit);
  // Fallback passes in case layout finished before we reached cy, or for late
  // web-font / container settles. The bounding-box guard makes early calls no-op.
  [200, 600, 1200].forEach((ms) => setTimeout(refit, ms));
  if (pane && typeof ResizeObserver === "function") {
    let raf = 0;
    new ResizeObserver(() => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(refit);
    }).observe(pane);
  } else {
    window.addEventListener("resize", refit);
  }
}

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

/* ----------------------------------------------------- click handlers */

// gocam-viewer.tsx (line 698) emits the Cytoscape event object via nodeClick.emit(evt),
// NOT the node directly. We need to dig the node out of evt.target before asking for
// its id. Doing this defensively also covers the case where a future viewer version
// emits the node directly.
function unwrapNode(detail) {
  if (detail && typeof detail.target?.id === "function") return detail.target;
  return detail;
}

function nodeId(node) {
  if (!node) return null;
  if (typeof node.id === "function") {
    try { return node.id(); } catch { return null; }
  }
  return typeof node.id === "string" ? node.id : null;
}

function handleNodeClick(detail, prov, labelIndex) {
  const node = unwrapNode(detail);
  const id = nodeId(node);
  if (!id) {
    renderEmpty("Unrecognized node payload.");
    return;
  }

  // Case 1: clicked id is itself an assertion key (a slot sub-individual,
  // including a has_input/has_output molecule node).
  if (srcList(prov.assertions[id]).length) {
    const slot = slotOf(id);
    renderPanel({
      kind: "slot",
      header: prettySlotHeader(slot),
      assertionId: id,
      entries: [{ slot, srcs: srcList(prov.assertions[id]), assertionId: id }],
    });
    return;
  }

  // Case 2: clicked id is an activity IRI. Aggregate the fixed per-slot
  // assertions plus any has_input/has_output molecule keys for this activity.
  const slots = ["enabled_by", "molecular_function", "part_of", "occurs_in"];
  const entries = slots
    .map((slot) => ({ slot, srcs: srcList(prov.assertions[`${id}/${slot}`]), assertionId: `${id}/${slot}` }))
    .filter((x) => x.srcs.length);
  for (const k of Object.keys(prov.assertions || {})) {
    if (k.startsWith(`${id}/has_input/`) || k.startsWith(`${id}/has_output/`)) {
      entries.push({ slot: slotOf(k), srcs: srcList(prov.assertions[k]), assertionId: k });
    }
  }
  if (entries.length > 0) {
    renderPanel({
      kind: "activity",
      header: "Activity",
      assertionId: id,
      entries,
    });
    return;
  }

  // Case 3: evidence-ECO individual or auxiliary node.
  renderPanel({
    kind: "other",
    header: "Node",
    assertionId: id,
    entries: [],
    note: "No direct provenance for this node — it may be an evidence individual. " +
          "Click the activity rectangle or one of its slot neighbours (gene product, BP, CC) " +
          "to see a source breakdown.",
  });
}

function handleEdgeClick(edge, prov, labelIndex) {
  const subj = edge.source().id();
  const obj  = edge.target().id();
  const property = edge.data("property") || edge.data("predicate") || edge.data("label") || "";

  const causalKey = `${subj}/causal/${obj}`;
  const subjLabel = labelOf(subj, labelIndex);
  const objLabel  = labelOf(obj,  labelIndex);

  if (srcList(prov.assertions[causalKey]).length) {
    renderPanel({
      kind: "causal",
      header: "Causal edge",
      assertionId: causalKey,
      edgeFacts: {
        property,
        propertyLabel: edge.data("property-label") || property,
        subj, subjLabel,
        obj,  objLabel,
      },
      entries: [{ slot: "causal", srcs: srcList(prov.assertions[causalKey]), assertionId: causalKey }],
    });
    return;
  }
  // Slot / has_input / has_output edge: one endpoint IS the assertion key (a
  // slot sub-individual or a has_input/has_output molecule). The molecule can
  // sit on EITHER end depending on how the viewer orients the edge (has_input
  // is drawn molecule→activity), so check the object first, then the subject.
  const slotKey = srcList(prov.assertions[obj]).length ? obj
                : srcList(prov.assertions[subj]).length ? subj
                : null;
  if (slotKey) {
    const slot = slotOf(slotKey);
    renderPanel({
      kind: "slot-edge",
      header: prettySlotHeader(slot),
      assertionId: slotKey,
      edgeFacts: { property, propertyLabel: edge.data("property-label") || property,
                   subj, subjLabel, obj, objLabel },
      entries: [{ slot, srcs: srcList(prov.assertions[slotKey]), assertionId: slotKey }],
    });
    return;
  }
  renderPanel({
    kind: "causal",
    header: "Edge",
    assertionId: causalKey,
    edgeFacts: { property, propertyLabel: edge.data("property-label") || property,
                 subj, subjLabel, obj, objLabel },
    entries: [],
    note: "No provenance recorded for this edge in the ledger.",
  });
}

function labelOf(iri, labelIndex) {
  return labelIndex[iri] || lastSegment(iri) || iri;
}

function lastSegment(iri) {
  const i = iri.lastIndexOf("/");
  return i >= 0 ? iri.slice(i + 1) : iri;
}

// The slot an assertion key belongs to. has_input/has_output keys carry a
// trailing molecule CURIE (`<act>/has_input/<mol>`), so lastSegment() would
// return the molecule — special-case them to the real slot name.
function slotOf(key) {
  if (key.includes("/has_input/")) return "has_input";
  if (key.includes("/has_output/")) return "has_output";
  return lastSegment(key);
}

function prettySlotHeader(slot) {
  return {
    enabled_by: "Enabled by (gene product)",
    molecular_function: "Molecular function",
    part_of: "Biological process",
    occurs_in: "Cellular component",
    has_input: "Has input",
    has_output: "Has output",
    causal: "Causal edge",
  }[slot] || "Node";
}

/* ------------------------------------------------------ panel rendering */

function renderEmpty(text) {
  const panel = document.querySelector("#provenance-panel");
  panel.innerHTML = "";
  const p = document.createElement("p");
  p.className = "prov-placeholder";
  p.textContent = text;
  panel.appendChild(p);
}

function renderPanel({ kind, header, assertionId, entries, edgeFacts, note }) {
  const panel = document.querySelector("#provenance-panel");
  panel.innerHTML = "";
  panel.dataset.kind = kind || "";

  const h = document.createElement("h2");
  h.textContent = header;
  panel.appendChild(h);

  // For causal-edge panels, render the relationship as a structured fact-block
  // before the source card. The edge IS the assertion; the node labels and the
  // predicate are the headline.
  if (edgeFacts) {
    const facts = document.createElement("div");
    facts.className = "edge-facts";
    // Direct grid children — label / value / label / value / label / value —
    // so the two-column template (`max-content 1fr`) actually flows.
    facts.innerHTML = `
      <span class="edge-fact-label">Subject</span>
      <code class="edge-fact-value">${escapeHtml(edgeFacts.subjLabel)}</code>
      <span class="edge-fact-label">Predicate</span>
      <span class="edge-fact-value predicate">
        <span class="predicate-name">${escapeHtml(edgeFacts.propertyLabel || edgeFacts.property)}</span>
        <a class="curie" href="${sourceUrl(edgeFacts.property)}" target="_blank" rel="noopener noreferrer">${escapeHtml(edgeFacts.property)}</a>
      </span>
      <span class="edge-fact-label">Object</span>
      <code class="edge-fact-value">${escapeHtml(edgeFacts.objLabel)}</code>
    `;
    panel.appendChild(facts);
  }

  const idEl = document.createElement("code");
  idEl.className = "assertion-id";
  idEl.textContent = assertionId;
  panel.appendChild(idEl);

  if (note) {
    const p = document.createElement("p");
    p.className = "prov-note";
    p.textContent = note;
    panel.appendChild(p);
  }

  for (const entry of (entries || [])) {
    const eid = entry.assertionId ?? assertionId;
    // v2: each slot/edge may carry several sources (id-resolution vs the
    // biological fact); render one card per source. `src` (singular) is the
    // v1 back-compat shape.
    const srcs = entry.srcs ?? srcList(entry.src);
    // Group the source card(s) AND their curator-action buttons into one unit,
    // so the buttons visually belong to THIS statement, not the next one below.
    const group = document.createElement("div");
    group.className = "assertion-group";
    for (const src of srcs) {
      group.appendChild(renderSource(entry.slot, src, eid));
    }
    // One curator-action block per assertion, regardless of source count —
    // the curator acts on the statement, not on each individual citation.
    SRC_BY_ASSERTION.set(eid, srcs);
    group.appendChild(renderCuratorActions(eid, entry.slot));
    panel.appendChild(group);
  }
}

// Lookup of the live source object by assertion id. Filled lazily as
// renderSource gets called for each slot in the current panel; the
// curator-action handler reads it back when building the GH issue body.
const SRC_BY_ASSERTION = new Map();

// Renders a single source card. The curator-action block and the
// SRC_BY_ASSERTION bookkeeping live in renderPanel now, so one slot with
// several sources gets several cards but a single action block (#40).
function renderSource(slot, src, assertionId) {
  const card = document.createElement("div");
  card.className = `source-card ${src.source_type}`;
  // Tag the card so an evidence chip can scroll to / highlight this exact
  // source in the panel (#52 pt8).
  if (assertionId) card.dataset.assertionId = assertionId;

  const meta = SOURCE_META[src.source_type] || { emoji: "?", label: src.source_type };
  const badge = document.createElement("span");
  badge.className = `badge ${src.source_type}`;
  badge.textContent = `${meta.emoji} ${meta.label}`;
  card.appendChild(badge);

  const slotEl = document.createElement("span");
  slotEl.className = "slot";
  slotEl.textContent = SLOT_PRETTY[slot] || slot;
  card.appendChild(slotEl);

  if (src.source_id) {
    const a = document.createElement("a");
    a.className = "source-id";
    // #52 pt3: show the id AND its label (e.g. "GO:0004510 — tryptophan 5-…").
    // #52 pt3 / kltm: render as "label (ID)" — label-forward, with the CURIE in
    // parens and the whole thing linked out for a sanity check.
    const label = src.term_label || termLabel(src.source_id);
    a.textContent = label && label !== src.source_id ? `${label} (${src.source_id})` : src.source_id;
    const url = sourceUrl(src.source_id);
    a.href = url;
    if (url !== "#") {
      a.target = "_blank";
      a.rel = "noopener";
    }
    card.appendChild(a);
  }
  // #52 pts 1,2: structured evidence — the GAF code and a LINKED reference
  // (PMID/GO_REF), shown consistently regardless of which tool retrieved it.
  if (src.evidence_code || src.reference) {
    const ev = document.createElement("p");
    ev.className = "evidence-line";
    let html = "";
    if (src.evidence_code) html += `<strong>Evidence:</strong> ${escapeHtml(src.evidence_code)}`;
    if (src.reference) {
      const refUrl = sourceUrl(src.reference);
      const refLink = refUrl !== "#"
        ? `<a href="${refUrl}" target="_blank" rel="noopener noreferrer">${escapeHtml(src.reference)}</a>`
        : escapeHtml(src.reference);
      html += `${html ? " · " : ""}<span class="ref">${refLink}</span>`;
    }
    ev.innerHTML = html;
    card.appendChild(ev);
  }
  if (src.supporting_text) {
    const q = document.createElement("blockquote");
    q.className = "supporting-text";
    q.textContent = src.supporting_text;
    card.appendChild(q);
  }
  if (src.snippet) {
    const q = document.createElement("blockquote");
    q.className = "snippet";
    q.textContent = src.snippet;
    card.appendChild(q);
  }
  if (src.justification) {
    const p = document.createElement("p");
    p.className = "justification";
    p.innerHTML = `<strong>Justification:</strong> ${escapeHtml(src.justification)}`;
    card.appendChild(p);
  }
  if (src.extra && Object.keys(src.extra).length) {
    const dl = document.createElement("dl");
    dl.className = "extra";
    for (const [k, v] of Object.entries(src.extra)) {
      const dt = document.createElement("dt"); dt.textContent = prettifyKey(k);
      const dd = document.createElement("dd");
      if (k === "pathway_url" || /^https?:/.test(String(v))) {
        const a = document.createElement("a");
        a.href = String(v); a.textContent = String(v);
        a.target = "_blank"; a.rel = "noopener noreferrer";
        dd.appendChild(a);
      } else {
        dd.textContent = String(v);
      }
      dl.appendChild(dt); dl.appendChild(dd);
    }
    card.appendChild(dl);
  }
  if (src.tool_name) {
    const t = document.createElement("p");
    t.className = "tool";
    t.textContent = `via ${src.tool_name}`;
    card.appendChild(t);
  }
  if (src.retrieved_at) {
    const d = document.createElement("p");
    d.className = "retrieved";
    d.textContent = `retrieved ${src.retrieved_at}`;
    card.appendChild(d);
  }

  return card;
}

function renderCuratorActions(assertionId, slot) {
  const wrap = document.createElement("div");
  wrap.className = "curator-actions";

  const isCausal = slot === "causal";
  const buttons = isCausal
    ? [
        { kind: "edit-relation",   label: "✏️ Edit relation" },
        { kind: "add-evidence",    label: "\u{1F4DD} Add evidence" },
        { kind: "dispute",         label: "\u{1F44E} Dispute" },
        { kind: "comment",         label: "\u{1F4AC} Comment" },
      ]
    : [
        { kind: "confirm",         label: "\u{1F44D} Confirm" },
        { kind: "dispute",         label: "\u{1F44E} Dispute" },
        { kind: "comment",         label: "\u{1F4AC} Comment" },
      ];

  for (const b of buttons) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `curator-btn micro action-${b.kind}`;
    btn.textContent = b.label;
    btn.title = "Records locally, then offers to open a GitHub issue with the details pre-filled.";
    btn.addEventListener("click", () => handleCuratorAction(assertionId, slot, b.kind));
    wrap.appendChild(btn);
  }

  // Existing-action records: show what's been done, BY WHOM and WHEN (#52 pt5).
  const previous = actionsFor(CURRENT_MODEL_ID, assertionId);
  if (previous.length) {
    const chips = document.createElement("div");
    chips.className = "prior-actions";
    for (const a of previous) {
      const chip = document.createElement("span");
      chip.className = `prior-action ${a.kind}`;
      const who = a.curator?.nickname ? ` by ${a.curator.nickname}` : "";
      const when = a.ts ? ` · ${formatActionTime(a.ts)}` : "";
      chip.textContent = `${a.kind}${who}${when}`;
      chip.title = `${a.kind}${who}${a.ts ? " at " + a.ts : ""}` + (a.payload ? `\n${a.payload}` : "");
      chips.appendChild(chip);
    }
    wrap.appendChild(chips);
  }
  return wrap;
}

function formatActionTime(iso) {
  try { return new Date(iso).toLocaleString(); } catch { return iso; }
}

async function handleCuratorAction(assertionId, slot, kind) {
  let note = null;
  if (kind === "comment" || kind === "add-evidence" || kind === "edit-relation") {
    const title = kind === "comment" ? "Please add your comment"
                : kind === "add-evidence" ? "Add evidence (PMID and/or supporting text)"
                : "Suggest a new relation";
    const placeholder = kind === "comment" ? "Your comment…"
                : kind === "add-evidence" ? "PMID:… and/or a sentence of support"
                : "e.g. directly negatively regulates";
    note = await textInputModal({ title, placeholder });
    if (!note) return;
  }
  // Identify the curator once (self-asserted; declining keeps it anonymous).
  const curator = await ensureCurator();
  recordAction(CURRENT_MODEL_ID, assertionId, kind, note, curator);

  // Offer a one-click GH-issue path. The action is already saved locally —
  // this just escalates it from "noted in this browser" to "filed in the
  // project tracker", carrying the curator so the issue->re-run path can write
  // a verified ProvenanceInfo.contributor into the model.
  const src = SRC_BY_ASSERTION.get(assertionId);
  const issueUrl = curatorActionIssueUrl({
    actionKind: kind,
    assertionId,
    slot,
    srcSummary: summarizeSource(src),
    note: note || "",
    curator,
  });
  toastWithAction(
    `✓ ${kind} saved locally${curator ? ` (as ${curator.nickname})` : ""}`,
    "Open as GitHub issue ↗",
    () => openInNewTab(issueUrl),
  );
  document.querySelector("#provenance-panel")?.dispatchEvent(new CustomEvent("rerender"));
}

// Toast variant with an inline action link. The action button persists
// until the toast fades; clicking it doesn't dismiss early because the
// open-in-new-tab navigation also closes the parent toast naturally.
function toastWithAction(message, actionLabel, onClick) {
  installToastHost();
  const host = document.querySelector("#toast-host");
  const el = document.createElement("div");
  el.className = "toast toast-with-action";
  const text = document.createElement("span");
  text.textContent = message;
  el.appendChild(text);
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "toast-action";
  btn.textContent = actionLabel;
  btn.addEventListener("click", onClick);
  el.appendChild(btn);
  host.appendChild(el);
  setTimeout(() => el.classList.add("fade-out"), 6000);
  setTimeout(() => el.remove(), 6600);
}

function sourceUrl(id) {
  if (!id) return "#";
  if (id.startsWith("PMID:")) return `https://pubmed.ncbi.nlm.nih.gov/${id.slice(5)}/`;
  if (id.startsWith("DOI:"))  return `https://doi.org/${id.slice(4)}`;
  if (id.startsWith("GO:"))   return `https://amigo.geneontology.org/amigo/term/${id}`;
  if (id.startsWith("WB:"))   return `https://wormbase.org/species/c_elegans/gene/${id.slice(3)}`;
  if (id.startsWith("RO:"))   return `https://www.ebi.ac.uk/ols/ontologies/ro/terms?obo_id=${id}`;
  if (id.startsWith("ECO:"))  return `https://www.evidenceontology.org/term/${id}`;
  if (id.startsWith("CL:"))   return `https://amigo.geneontology.org/amigo/term/${id}`;
  if (id.startsWith("GO_REF:")) return `https://github.com/geneontology/go-site/blob/master/metadata/gorefs/${id}`;
  if (id.startsWith("HGNC:")) return `https://www.genenames.org/data/gene-symbol-report/#!/hgnc_id/${id}`;
  if (id.startsWith("MGI:"))  return `https://www.informatics.jax.org/marker/${id}`;
  if (id.startsWith("ZFIN:")) return `https://zfin.org/${id.slice(5)}`;
  if (id.startsWith("RGD:"))  return `https://rgd.mcw.edu/rgdweb/report/gene/main.html?id=${id.slice(4)}`;
  if (id.startsWith("FB:") || id.startsWith("FlyBase:")) return `https://flybase.org/reports/${id.split(":")[1]}.html`;
  if (id.startsWith("SGD:"))  return `https://www.yeastgenome.org/locus/${id.slice(4)}`;
  if (/^R-[A-Z]{3,4}-\d+/.test(id)) return `https://reactome.org/content/detail/${id}`;
  if (/^WP\d+/.test(id))      return `https://www.wikipathways.org/pathways/${id}.html`;
  if (/^https?:/.test(id))    return id;
  return "#";
}

function prettifyKey(k) {
  return k.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function escapeHtml(s) {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

main().catch((e) => {
  const errEl = document.querySelector("#error");
  errEl.textContent = `Failed to load model: ${e.message}`;
  console.error(e);
});
