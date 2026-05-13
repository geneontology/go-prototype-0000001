// Poll GitHub for new draft models. Slow on purpose — this is a demo,
// and unauthenticated GitHub API allows 60 requests / hour / IP.
//
// We list the directories under docs/runs/, diff against the run-ids
// rendered on the page, and show a small banner offering a refresh when
// new ones appear. No partial DOM updates — a click on the banner just
// reloads, which is enough for a prototype.

const REPO = "geneontology/go-prototype-0000001";
const CONTENTS_URL = `https://api.github.com/repos/${REPO}/contents/docs/runs`;
const POLL_INTERVAL_MS = 10 * 60 * 1000; // 10 min
const MIN_CHECK_GAP_MS = 2 * 60 * 1000;  // throttle focus-triggered checks
let lastCheck = 0;

function shownRunIds() {
  return new Set(
    Array.from(document.querySelectorAll(".draft-model a.draft-title"))
      .map((a) => {
        const m = (a.getAttribute("href") || "").match(/^runs\/([^/]+)\/?$/);
        return m ? m[1] : null;
      })
      .filter(Boolean)
  );
}

async function fetchLiveRunIds() {
  const r = await fetch(CONTENTS_URL, {
    headers: { Accept: "application/vnd.github+json" },
  });
  if (!r.ok) return null;
  const items = await r.json();
  if (!Array.isArray(items)) return null;
  return new Set(items.filter((x) => x.type === "dir").map((x) => x.name));
}

function showNewDraftsBanner(newIds) {
  const existing = document.querySelector("#new-drafts-banner");
  if (existing) {
    existing.querySelector(".count").textContent = newIds.size;
    return;
  }
  const banner = document.createElement("div");
  banner.id = "new-drafts-banner";
  banner.className = "new-drafts-banner";
  const msg = document.createElement("span");
  msg.innerHTML = `<strong class="count">${newIds.size}</strong> new draft model(s) ready on GitHub.`;
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "reload-btn";
  btn.textContent = "Refresh page";
  btn.addEventListener("click", () => location.reload());
  banner.append(msg, btn);
  const main = document.querySelector(".landing-main");
  if (main) main.prepend(banner);
}

async function checkForNewDrafts() {
  const now = Date.now();
  if (now - lastCheck < MIN_CHECK_GAP_MS) return;
  lastCheck = now;
  let live;
  try {
    live = await fetchLiveRunIds();
  } catch {
    return; // network/CORS/rate-limit — silently skip
  }
  if (!live) return;
  const shown = shownRunIds();
  const newIds = new Set([...live].filter((x) => !shown.has(x)));
  if (newIds.size > 0) showNewDraftsBanner(newIds);
}

function init() {
  if (!document.querySelector(".runs-list")) return;
  setTimeout(checkForNewDrafts, 2000);
  setInterval(checkForNewDrafts, POLL_INTERVAL_MS);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") checkForNewDrafts();
  });
}

document.addEventListener("DOMContentLoaded", init);
