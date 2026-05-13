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

  await viewerEl.setModelData(viewerData);

  // Node-click is upstream-supported — wire it directly.
  viewerEl.addEventListener("nodeClick", (e) => {
    const node = e.detail;
    handleNodeClick(node, prov);
  });

  // Edge-click is NOT upstream-supported. Try multiple paths to the
  // cytoscape instance; fall back to wiring on first node click.
  await wireEdgeClicks(viewerEl, prov);
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

function handleNodeClick(node, prov) {
  const id = (typeof node?.id === "function") ? node.id() : node?.id;
  if (!id) {
    renderEmpty("Unrecognized node payload.");
    return;
  }
  const slots = ["enabled_by", "molecular_function", "part_of", "occurs_in"];
  const entries = slots
    .map((slot) => ({ slot, src: prov.assertions[`${id}/${slot}`] }))
    .filter((x) => x.src);

  if (entries.length === 0) {
    // Probably an evidence sub-individual or unmodelled node.
    renderPanel(
      "Node",
      id,
      [],
      "No direct provenance for this node — it may be an evidence-ECO individual. Click an activity (gene-product) node to see its source breakdown."
    );
    return;
  }
  renderPanel(activityHeader(id), id, entries);
}

function handleEdgeClick(edge, prov) {
  const subj = edge.source().id();
  const obj  = edge.target().id();
  const stripActivity = (s) => s; // keep full IRI for now
  const key  = `${stripActivity(subj)}/causal/${stripActivity(obj)}`;
  const src  = prov.assertions[key];
  const header = `Causal edge: ${shortIdLabel(subj, prov)} → ${shortIdLabel(obj, prov)}`;
  if (src) {
    renderPanel(header, key, [{ slot: "causal", src }]);
  } else {
    renderPanel(header, key, [],
      "No provenance recorded for this edge in the ledger.");
  }
}

function activityHeader(activityIri) {
  return "Activity";
}

function shortIdLabel(iri, prov) {
  // The viewer JSON's individuals carry labels; fall back to last segment of the IRI.
  const parts = iri.split("/");
  return parts[parts.length - 1] || iri;
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
