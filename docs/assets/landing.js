// Landing-page interactivity for the 'Submit a figure' form.
//
// The primary submit path opens GitHub's pre-populated Issue Form for our
// `run-agent.yml` template — the workflow listens for `issues.opened` with
// the `run-agent-request` label, so the curator's flow becomes:
//
//   1. Fill in the form on this page.
//   2. Click "Open prefilled GitHub form" — a new tab opens with the GitHub
//      Issue Form already populated with the values.
//   3. Click Submit on GitHub. The workflow fires within seconds.
//   4. The workflow comments back on the issue with the published draft URL,
//      and closes the issue.
//
// No backend, no PAT in localStorage — GitHub's own auth is the auth.
// The `gh` CLI command is still offered as a fallback for users without
// a browser session signed into GitHub.

const REPO = "geneontology/go-prototype-0000001";
const WORKFLOW = "run-agent.yml";
const ISSUE_TEMPLATE = "run-agent.yml";

const FIELDS = ["image_url", "species", "species_taxon", "process_hint", "run_id"];

function quote(s) {
  if (s == null || s === "") return "''";
  return "'" + String(s).replace(/'/g, "'\\''") + "'";
}

function buildIssueFormUrl(form) {
  // GitHub Issue Forms accept query-param prefill where each key matches a
  // form field's `id`. The value just needs URL-encoding — newlines and
  // special chars are preserved.
  const data = new FormData(form);
  const params = new URLSearchParams({ template: ISSUE_TEMPLATE });
  for (const field of FIELDS) {
    const v = (data.get(field) || "").toString().trim();
    if (v) params.set(field, v);
  }
  return `https://github.com/${REPO}/issues/new?${params.toString()}`;
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

function renderResult(container, form) {
  const issueUrl = buildIssueFormUrl(form);
  const cmd = buildCommand(form);

  container.hidden = false;
  container.innerHTML = "";

  // Primary path: open the prefilled GH Issue Form. Real "click and ship."
  const primaryCard = document.createElement("div");
  primaryCard.className = "submit-primary";

  const primaryIntro = document.createElement("p");
  primaryIntro.className = "submit-intro";
  primaryIntro.textContent =
    "Open the prefilled GitHub form in a new tab; the workflow fires the moment you click Submit there.";
  primaryCard.appendChild(primaryIntro);

  const primaryLink = document.createElement("a");
  primaryLink.href = issueUrl;
  primaryLink.target = "_blank";
  primaryLink.rel = "noopener noreferrer";
  primaryLink.className = "primary-link";
  primaryLink.textContent = "Open prefilled GitHub form ↗";
  primaryCard.appendChild(primaryLink);

  container.appendChild(primaryCard);

  // Secondary path: gh CLI for users without a GH browser session.
  const secondary = document.createElement("details");
  secondary.className = "submit-secondary";
  const summary = document.createElement("summary");
  summary.textContent = "Or run from a terminal (gh CLI)";
  secondary.appendChild(summary);

  const pre = document.createElement("pre");
  pre.className = "submit-cmd";
  pre.textContent = cmd;
  secondary.appendChild(pre);

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
  secondary.appendChild(actions);

  container.appendChild(secondary);

  const note = document.createElement("p");
  note.className = "submit-note";
  note.textContent =
    "Once the workflow finishes (typically 2-5 minutes), the issue you opened will be commented with the draft model's URL and closed automatically.";
  container.appendChild(note);
}

function init() {
  const form = document.querySelector("#submit-form");
  if (!form) return;
  const result = document.querySelector("#submit-result");
  form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    renderResult(result, form);
  });
}

document.addEventListener("DOMContentLoaded", init);
