// Per-run page: probe for ./figure.<ext>, and if found, inject a small
// thumbnail in the top-right corner of the viewer pane. Clicking the
// thumbnail opens the original at full size in a click-to-dismiss
// lightbox (Esc / click-outside both close).
//
// Probing 4-5 extensions on page load is fine for a prototype — the
// successful one resolves first, and the failures are negligible.

const EXTS = ["png", "jpg", "jpeg", "webp", "gif"];

function tryLoad(url) {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => resolve(url);
    img.onerror = () => resolve(null);
    img.src = url;
  });
}

async function findFigure() {
  for (const ext of EXTS) {
    const ok = await tryLoad(`figure.${ext}`);
    if (ok) return ok;
  }
  return null;
}

function ensureLightbox() {
  let box = document.querySelector("#figure-lightbox");
  if (box) return box;
  box = document.createElement("div");
  box.id = "figure-lightbox";
  box.className = "figure-lightbox";
  box.hidden = true;
  const img = document.createElement("img");
  img.alt = "Source figure (full size)";
  const close = document.createElement("button");
  close.type = "button";
  close.className = "figure-lightbox-close";
  close.setAttribute("aria-label", "Close");
  close.textContent = "×";
  box.append(img, close);
  const dismiss = () => { box.hidden = true; };
  box.addEventListener("click", (ev) => {
    if (ev.target === box || ev.target === close) dismiss();
  });
  document.addEventListener("keydown", (ev) => {
    if (!box.hidden && ev.key === "Escape") dismiss();
  });
  document.body.appendChild(box);
  return box;
}

function openLightbox(src) {
  const box = ensureLightbox();
  box.querySelector("img").src = src;
  box.hidden = false;
}

async function init() {
  const pane = document.querySelector(".viewer-pane");
  if (!pane) return;
  const figureUrl = await findFigure();
  if (!figureUrl) return;

  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "figure-thumb";
  btn.title = "Click to view the source figure at full size";
  const img = document.createElement("img");
  img.src = figureUrl;
  img.alt = "Source figure (click to enlarge)";
  const label = document.createElement("span");
  label.className = "figure-thumb-label";
  label.textContent = "source figure";
  btn.append(img, label);
  btn.addEventListener("click", () => openLightbox(figureUrl));
  pane.appendChild(btn);
}

document.addEventListener("DOMContentLoaded", init);
