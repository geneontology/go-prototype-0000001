// Landing-page interactivity: the 'Submit a figure' form generates the
// `gh workflow run` invocation that triggers an agent draft. Honest about
// the prototype limit — v1 will run this server-side and the user will
// just click "submit".

const REPO = "geneontology/go-prototype-0000001";
const WORKFLOW = "run-agent.yml";

function quote(s) {
  if (s == null || s === "") return "''";
  return "'" + String(s).replace(/'/g, "'\\''") + "'";
}

function buildCommand(form) {
  const data = new FormData(form);
  const parts = [
    "gh", "workflow", "run", WORKFLOW,
    "--repo", REPO,
    "-f", `image_url=${quote(data.get("image_url") || "")}`,
  ];
  for (const field of ["species", "species_taxon", "process_hint", "run_id"]) {
    const v = (data.get(field) || "").toString().trim();
    if (v) parts.push("-f", `${field}=${quote(v)}`);
  }
  return parts.join(" ");
}

async function copyToClipboard(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

function renderResult(container, cmd) {
  container.hidden = false;
  container.innerHTML = "";

  const intro = document.createElement("p");
  intro.className = "submit-intro";
  intro.textContent = "Copy this into a terminal that has `gh` authenticated for the repo:";
  container.appendChild(intro);

  const pre = document.createElement("pre");
  pre.className = "submit-cmd";
  pre.textContent = cmd;
  container.appendChild(pre);

  const actions = document.createElement("div");
  actions.className = "submit-cmd-actions";

  const copyBtn = document.createElement("button");
  copyBtn.type = "button";
  copyBtn.className = "secondary";
  copyBtn.textContent = "Copy command";
  copyBtn.addEventListener("click", async () => {
    const ok = await copyToClipboard(cmd);
    copyBtn.textContent = ok ? "Copied ✓" : "Copy failed — select and ⌘C";
    setTimeout(() => (copyBtn.textContent = "Copy command"), 2500);
  });
  actions.appendChild(copyBtn);

  const link = document.createElement("a");
  link.href = `https://github.com/${REPO}/actions/workflows/${WORKFLOW}`;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.textContent = "Or trigger from the Actions UI ↗";
  actions.appendChild(link);

  container.appendChild(actions);

  const note = document.createElement("p");
  note.className = "submit-note";
  note.textContent =
    "v1 will wire this submit button to a small backend that issues the dispatch on your behalf — the form fields you filled out will carry over unchanged.";
  container.appendChild(note);
}

function init() {
  const form = document.querySelector("#submit-form");
  if (!form) return;
  const result = document.querySelector("#submit-result");
  form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    const cmd = buildCommand(form);
    renderResult(result, cmd);
  });
}

document.addEventListener("DOMContentLoaded", init);
