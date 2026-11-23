// Chemprop frontend helpers: talk to the backend, fill the Class dropdown, accept pasted screenshots.
// Works in plain JS, React or Next.js. Copy this file into your frontend's source folder.
//
// The board is always CBSE, so the UI has no board selector and nothing here sends one.
//
// Class dropdown (plain HTML):
//   <label for="grade">Class</label>
//   <select id="grade"></select>
//   <script type="module">
//     import { fillGradeSelect } from "./chemprop-api.js";
//     fillGradeSelect(document.getElementById("grade"));
//   </script>
//
// React: render <select value={grade} onChange={e => setGrade(Number(e.target.value))}>
//   {[10, 11, 12].map(g => <option key={g} value={g}>Class {g}</option>)}</select>
//
// Analyse typed input or a pasted screenshot:
//   const result = await analyzeText({ name: "aspirin" }, grade);     // or { smiles: "CCO" }
//   enableImagePaste(dropZone, async (file) => { const result = await analyzeImage(file, grade); });

// A page served by the backend itself (like /demo/) sets window.CHEMPROP_API = "" to use same-origin URLs.
export const API = (typeof window !== "undefined" && window.CHEMPROP_API !== undefined)
  ? window.CHEMPROP_API
  : "http://localhost:8000";
const FALLBACK_GRADES = [10, 11, 12];

// ---- config and the Class dropdown ---------------------------------------------------

export async function fetchConfig() {
  const res = await fetch(`${API}/api/config`);
  if (!res.ok) throw new Error("Could not load settings from the server.");
  return res.json();   // { boards: ["CBSE"], grades: [10, 11, 12], image_input: true|false }
}

export async function fillGradeSelect(selectEl, defaultGrade = 12) {
  let grades = FALLBACK_GRADES;
  try {
    const cfg = await fetchConfig();
    if (Array.isArray(cfg.grades) && cfg.grades.length) grades = cfg.grades;
  } catch (_) {
    // Backend not reachable yet: the fallback list keeps the dropdown usable.
  }
  selectEl.innerHTML = "";
  for (const g of grades) {
    const opt = document.createElement("option");
    opt.value = String(g);
    opt.textContent = `Class ${g}`;
    selectEl.appendChild(opt);
  }
  selectEl.value = String(defaultGrade);
}

// ---- calling the analysis endpoint -----------------------------------------------------

async function send(form) {
  // Do not set Content-Type yourself; the browser adds the multipart boundary.
  const res = await fetch(`${API}/api/analyze`, { method: "POST", body: form });
  const data = await res.json();
  if (!res.ok) {
    // data.code examples: INVALID_SMILES, NAME_NOT_FOUND, PUBCHEM_UNAVAILABLE,
    // OCR_UNAVAILABLE, STRUCTURE_NOT_RECOGNISED, INVALID_IMAGE, IMAGE_TOO_LARGE
    throw Object.assign(new Error(data.error || "Request failed"), { code: data.code, data });
  }
  return data;
}

// input is { smiles: "CCO" } or { name: "aspirin" }, not both.
export function analyzeText(input, grade) {
  const form = new FormData();
  form.append("grade", String(grade));
  if (input.smiles) form.append("smiles", input.smiles);
  if (input.name) form.append("name", input.name);
  return send(form);
}

export function analyzeImage(file, grade) {
  const form = new FormData();
  form.append("grade", String(grade));
  form.append("image", file, file.name || "screenshot.png");
  return send(form);
}

// ---- pasted and dropped screenshots ------------------------------------------------------

function nameIt(file) {
  // Clipboard images have no file name, and the backend ignores an upload without one.
  return file.name ? file : new File([file], "screenshot.png", { type: file.type || "image/png" });
}

export function enableImagePaste(dropZone, onImage) {
  // Ctrl+V anywhere on the page, when the clipboard holds an image.
  document.addEventListener("paste", (e) => {
    const items = (e.clipboardData && e.clipboardData.items) || [];
    for (const item of items) {
      if (item.kind === "file" && item.type.startsWith("image/")) {
        e.preventDefault();
        onImage(nameIt(item.getAsFile()));
        return;
      }
    }
  });
  // Dragging an image file onto the drop zone.
  dropZone.addEventListener("dragover", (e) => e.preventDefault());
  dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    const file = Array.from(e.dataTransfer.files).find((f) => f.type.startsWith("image/"));
    if (file) onImage(nameIt(file));
  });
}
