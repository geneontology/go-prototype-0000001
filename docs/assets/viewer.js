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
};

const SLOT_PRETTY = {
  enabled_by:          "enabled by",
  molecular_function:  "molecular function",
  part_of:             "part of (BP)",
  occurs_in:           "occurs in (CC)",
  causal:              "causal edge",
};

// Local-only "curator actions" store. Keyed per model so a curator's
// confirm / dispute / comment actions persist across page reloads in the
// same browser. v1 will swap this for a real curator-review backend.
const ACTIONS_STORE_KEY = (modelId) => `gocam-proto-actions/${modelId}`;

function loadActions(modelId) {
  try {
    return JSON.parse(localStorage.getItem(ACTIONS_STORE_KEY(modelId)) || "[]");
  } catch { return []; }
}
function saveActions(modelId, actions) {
  try { localStorage.setItem(ACTIONS_STORE_KEY(modelId), JSON.stringify(actions)); }
  catch { /* private browsing / quota — silently drop */ }
}
function recordAction(modelId, assertionId, kind, payload) {
  const actions = loadActions(modelId);
  actions.push({ assertionId, kind, payload: payload || null, ts: new Date().toISOString() });
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

let CURRENT_MODEL_ID = null;  // populated in main()

async function main() {
  installOffsiteLinkDefault();

  const [viewerData, prov] = await Promise.all([
    fetchJson("viewer.json"),
    fetchJson("provenance.json"),
  ]);

  CURRENT_MODEL_ID = viewerData.id || "unknown-model";

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
  if (cy) emphasizeCausalEdges(cy);

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
    showModal({
      title: "Propose changes (prototype)",
      body: actions.length
        ? `You've recorded ${actions.length} pending action${actions.length === 1 ? "" : "s"} on this model. In v1 these would batch into a curator-review submission; today they're stored locally in your browser.`
        : "No pending actions yet. Use the per-assertion buttons (confirm / dispute / comment) on the source cards to mark things up; this button would package them into a curator-review submission in v1.",
      details: actions,
    });
  });
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

// Build {iri -> human-readable label} from viewer.json's individuals and objects.
function buildLabelIndex(viewerData) {
  const index = {};
  for (const ind of viewerData.individuals || []) {
    const t = (ind.type || [])[0];
    if (t?.label) index[ind.id] = t.label;
  }
  return index;
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
    /* Take the freed real estate. */
    .gocam-graph, .gocam-viz, [class*="graph"] { width: 100% !important; }
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

  // Case 1: clicked id is itself an assertion key (a slot sub-individual).
  if (prov.assertions[id]) {
    const slot = lastSegment(id);
    renderPanel({
      kind: "slot",
      header: prettySlotHeader(slot),
      assertionId: id,
      entries: [{ slot, src: prov.assertions[id] }],
    });
    return;
  }

  // Case 2: clicked id is an activity IRI. Aggregate per-slot assertions.
  const slots = ["enabled_by", "molecular_function", "part_of", "occurs_in"];
  const entries = slots
    .map((slot) => ({ slot, src: prov.assertions[`${id}/${slot}`] }))
    .filter((x) => x.src);
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

  if (prov.assertions[causalKey]) {
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
      entries: [{ slot: "causal", src: prov.assertions[causalKey] }],
    });
    return;
  }
  if (prov.assertions[obj]) {
    const slot = lastSegment(obj);
    renderPanel({
      kind: "slot-edge",
      header: prettySlotHeader(slot),
      assertionId: obj,
      edgeFacts: { property, propertyLabel: edge.data("property-label") || property,
                   subj, subjLabel, obj, objLabel },
      entries: [{ slot, src: prov.assertions[obj] }],
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

function prettySlotHeader(slot) {
  return {
    enabled_by: "Enabled by (gene product)",
    molecular_function: "Molecular function",
    part_of: "Biological process",
    occurs_in: "Cellular component",
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
    facts.innerHTML = `
      <div class="edge-fact-row">
        <span class="edge-fact-label">Subject</span>
        <code class="edge-fact-value">${escapeHtml(edgeFacts.subjLabel)}</code>
      </div>
      <div class="edge-fact-row">
        <span class="edge-fact-label">Predicate</span>
        <span class="edge-fact-value predicate">
          ${escapeHtml(edgeFacts.propertyLabel || edgeFacts.property)}
          <a class="curie" href="${sourceUrl(edgeFacts.property)}" target="_blank" rel="noopener noreferrer">${escapeHtml(edgeFacts.property)}</a>
        </span>
      </div>
      <div class="edge-fact-row">
        <span class="edge-fact-label">Object</span>
        <code class="edge-fact-value">${escapeHtml(edgeFacts.objLabel)}</code>
      </div>
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
    panel.appendChild(renderSource(entry.slot, entry.src, assertionId));
  }
}

function renderSource(slot, src, assertionId) {
  const card = document.createElement("div");
  card.className = `source-card ${src.source_type}`;

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
    a.textContent = src.source_id;
    const url = sourceUrl(src.source_id);
    a.href = url;
    if (url !== "#") {
      a.target = "_blank";
      a.rel = "noopener";
    }
    card.appendChild(a);
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

  // Curator-action affordances. These don't yet round-trip to a backend;
  // they stash to localStorage so the buttons feel alive and the model
  // can show 'X pending actions' at the page level.
  card.appendChild(renderCuratorActions(assertionId, slot));

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
    btn.addEventListener("click", () => handleCuratorAction(assertionId, b.kind));
    wrap.appendChild(btn);
  }

  // Existing-action chips: show what the user has already done with this assertion.
  const previous = actionsFor(CURRENT_MODEL_ID, assertionId);
  if (previous.length) {
    const chips = document.createElement("div");
    chips.className = "prior-actions";
    for (const a of previous) {
      const chip = document.createElement("span");
      chip.className = `prior-action ${a.kind}`;
      chip.title = `${a.kind} at ${a.ts}` + (a.payload ? `\n${a.payload}` : "");
      chip.textContent = a.kind;
      chips.appendChild(chip);
    }
    wrap.appendChild(chips);
  }
  return wrap;
}

function handleCuratorAction(assertionId, kind) {
  if (kind === "comment" || kind === "add-evidence" || kind === "edit-relation") {
    const label = kind === "comment" ? "Comment" :
                  kind === "add-evidence" ? "New evidence (PMID / snippet)" :
                  "New relation (free-text suggestion)";
    const text = prompt(`${label}:`);
    if (!text) return;
    recordAction(CURRENT_MODEL_ID, assertionId, kind, text);
    toast(`\u{1F4DD} ${kind} recorded (prototype — saved locally)`);
  } else {
    recordAction(CURRENT_MODEL_ID, assertionId, kind, null);
    toast(`✓ ${kind} recorded (prototype — saved locally)`);
  }
  // Re-render the current panel so the new chip shows up without a full page click.
  document.querySelector("#provenance-panel")?.dispatchEvent(new CustomEvent("rerender"));
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
