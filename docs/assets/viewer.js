// Wrapper around <go-gocam-viewer> that:
//   1. Loads model + provenance from same-directory JSON files
//   2. Injects the model via setModelData (no api fetch)
//   3. Surfaces both node AND edge clicks (upstream emits nodeClick only —
//      we reach into the shadow DOM for the cytoscape instance to wire
//      edge clicks ourselves)
//   4. Renders a custom provenance panel keyed by assertion id

const SOURCE_META = {
  literature: { emoji: "\u{1F4DA}", label: "Literature" },
  database:   { emoji: "\u{1F5C4}", label: "Database" },
  amigo:      { emoji: "\u{1F50D}", label: "AmiGO" },
  instinct:   { emoji: "\u{26A0}\u{FE0F}",  label: "Instinct" },
};

const SLOT_PRETTY = {
  enabled_by:          "enabled by",
  molecular_function:  "molecular function",
  part_of:             "part of (BP)",
  occurs_in:           "occurs in (CC)",
  causal:              "causal edge",
};

async function main() {
  installOffsiteLinkDefault();

  const [viewerData, prov] = await Promise.all([
    fetchJson("viewer.json"),
    fetchJson("provenance.json"),
  ]);

  // Pretty the page title from the model annotations.
  const titleAnn = (viewerData.annotations || []).find(a => a.key === "title");
  document.querySelector("#run-title").textContent =
    titleAnn?.value || viewerData.id || "Run";

  await customElements.whenDefined("go-gocam-viewer");
  const viewerEl = document.querySelector("#viewer");

  hideBuiltinSidebar(viewerEl);
  await viewerEl.setModelData(viewerData);

  // Node-click is upstream-supported — wire it directly.
  viewerEl.addEventListener("nodeClick", (e) => {
    handleNodeClick(e.detail, prov);
  });

  // Edge-click is NOT upstream-supported. Try multiple paths to the
  // cytoscape instance; fall back to wiring on first node click.
  await wireEdgeClicks(viewerEl, prov);
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

async function wireEdgeClicks(viewerEl, prov) {
  let cy = null;
  for (let attempt = 0; attempt < 60 && !cy; attempt++) {
    cy = findCy(viewerEl);
    if (!cy) await sleep(100);
  }
  if (cy) {
    attachEdgeHandlers(cy, prov);
    return;
  }
  console.warn("Could not reach cytoscape instance after 6s; falling back to first-node-click wiring.");
  viewerEl.addEventListener("nodeClick", function bootstrap(e) {
    const fromNode = e.detail?.cy && typeof e.detail.cy === "function"
      ? e.detail.cy() : null;
    if (fromNode) {
      attachEdgeHandlers(fromNode, prov);
      viewerEl.removeEventListener("nodeClick", bootstrap);
    }
  });
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

function attachEdgeHandlers(cy, prov) {
  if (cy._gocamProtoWired) return;
  cy._gocamProtoWired = true;
  cy.edges().on("tap", (evt) => handleEdgeClick(evt.target, prov));
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

function handleNodeClick(detail, prov) {
  const node = unwrapNode(detail);
  const id = nodeId(node);
  if (!id) {
    renderEmpty("Unrecognized node payload.");
    return;
  }

  // Case 1: the clicked id is itself an assertion key. This happens when the
  // user clicks a gene-product / BP / CC sub-individual (whose IRI is
  // `<activity>/enabled_by` / `.../part_of` / `.../occurs_in`).
  if (prov.assertions[id]) {
    const slot = lastSegment(id);
    renderPanel(prettySlotHeader(slot), id, [{ slot, src: prov.assertions[id] }]);
    return;
  }

  // Case 2: the clicked id is an activity IRI (the molecular_function instance).
  // Aggregate every slot's source object so the panel shows the full per-activity
  // breakdown.
  const slots = ["enabled_by", "molecular_function", "part_of", "occurs_in"];
  const entries = slots
    .map((slot) => ({ slot, src: prov.assertions[`${id}/${slot}`] }))
    .filter((x) => x.src);
  if (entries.length > 0) {
    renderPanel("Activity", id, entries);
    return;
  }

  // Case 3: an evidence-ECO individual or other auxiliary node.
  renderPanel("Node", id, [],
    "No direct provenance for this node — it may be an evidence individual. " +
    "Click the activity rectangle or one of its slot neighbours (gene product, BP, CC) " +
    "to see a source breakdown."
  );
}

function handleEdgeClick(edge, prov) {
  const subj = edge.source().id();
  const obj  = edge.target().id();
  // Causal edges (RO predicates) emit assertion keys like `<source>/causal/<target>`.
  // Other slot edges (RO:0002333 enabled_by, BFO:0000050 part_of, BFO:0000066 occurs_in)
  // point at the slot sub-individual whose IRI already IS an assertion key.
  const causalKey = `${subj}/causal/${obj}`;
  if (prov.assertions[causalKey]) {
    renderPanel(
      `Causal edge: ${lastSegment(subj)} → ${lastSegment(obj)}`,
      causalKey,
      [{ slot: "causal", src: prov.assertions[causalKey] }],
    );
    return;
  }
  if (prov.assertions[obj]) {
    const slot = lastSegment(obj);
    renderPanel(
      `${prettySlotHeader(slot)} edge: ${lastSegment(subj)} → ${lastSegment(obj)}`,
      obj,
      [{ slot, src: prov.assertions[obj] }],
    );
    return;
  }
  renderPanel(
    `Edge: ${lastSegment(subj)} → ${lastSegment(obj)}`,
    causalKey,
    [],
    "No provenance recorded for this edge in the ledger.",
  );
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

function renderPanel(headerText, assertionId, entries, note) {
  const panel = document.querySelector("#provenance-panel");
  panel.innerHTML = "";

  const h = document.createElement("h2");
  h.textContent = headerText;
  panel.appendChild(h);

  const idEl = document.createElement("code");
  idEl.className = "assertion-id";
  idEl.textContent = assertionId;
  panel.appendChild(idEl);

  if (note) {
    const p = document.createElement("p");
    p.textContent = note;
    panel.appendChild(p);
  }

  if (entries.length === 0) {
    return;
  }

  for (const entry of entries) {
    panel.appendChild(renderSource(entry.slot, entry.src));
  }
}

function renderSource(slot, src) {
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
  return "#";
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
