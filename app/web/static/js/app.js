// Local Diff Viewer -- frontend application (vanilla JS, no build step).
"use strict";

// ============================================================== state
const state = {
  sides: {
    left: { mode: "folder", entries: null, zipFile: null, topName: "" },
    right: { mode: "folder", entries: null, zipFile: null, topName: "" },
  },
  comparisonId: null,
  summary: null,
  tree: null,
  filterStatus: "all",
  hideUnchanged: false,
  sidebarTab: "tree",
  selectedPath: null,
  diffCache: new Map(),
  currentDiff: null,
  viewMode: "side-by-side",
  flatOrder: [], // rel_paths in current visible order, for keyboard nav
  selectedIndex: -1,
  markerRows: [], // DOM rows representing a change, for prev/next navigation
  markerIndex: -1,
  expandedDiffPaths: new Set(), // paths where user asked to fully expand context
};

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

// ============================================================== utils
function fmtBytes(n) {
  if (n === null || n === undefined) return "—";
  if (n < 1024) return `${n} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let v = n / 1024, i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(1)} ${units[i]}`;
}

function escapeHtml(s) {
  return (s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function showLoading(text) {
  $("#loading-text").textContent = text || "Working…";
  $("#loading-overlay").classList.add("active");
}
function hideLoading() { $("#loading-overlay").classList.remove("active"); }

function showView(name) {
  $$(".view").forEach((v) => v.classList.remove("active"));
  $(`#view-${name}`).classList.add("active");
}

const STATUS_ICON = { added: "+", deleted: "-", modified: "~", renamed: "→", unchanged: "=" };

// ============================================================== drag & drop / file selection
let pendingSide = null;

function traverseEntry(entry, path, out) {
  return new Promise((resolve) => {
    if (entry.isFile) {
      entry.file((file) => {
        out.push({ file, relPath: path + entry.name });
        resolve();
      }, () => resolve());
    } else if (entry.isDirectory) {
      const reader = entry.createReader();
      const readAll = () => {
        reader.readEntries(async (batch) => {
          if (!batch.length) { resolve(); return; }
          await Promise.all(batch.map((e) => traverseEntry(e, path + entry.name + "/", out)));
          readAll(); // directory readers may need multiple calls to exhaust
        }, () => resolve());
      };
      readAll();
    } else {
      resolve();
    }
  });
}

async function handleDataTransferItems(side, items) {
  const entries = Array.from(items).map((it) => it.webkitGetAsEntry && it.webkitGetAsEntry()).filter(Boolean);
  if (!entries.length) return;

  // Single dropped ZIP file -> switch that side to ZIP mode automatically.
  if (entries.length === 1 && entries[0].isFile && /\.zip$/i.test(entries[0].name)) {
    entries[0].file((file) => {
      setMode(side, "zip");
      setZipFile(side, file);
    });
    return;
  }

  setMode(side, "folder");
  showLoading("Reading folder…");
  const out = [];
  await Promise.all(entries.map((e) => traverseEntry(e, "", out)));
  hideLoading();
  setFolderEntries(side, out);
}

function setMode(side, mode) {
  state.sides[side].mode = mode;
  $$(`.mode-tabs[data-side="${side}"] button`).forEach((b) => {
    b.classList.toggle("active", b.dataset.mode === mode);
  });
  clearSide(side, /*keepMode*/ true);
}

function clearSide(side, keepMode = false) {
  const s = state.sides[side];
  s.entries = null;
  s.zipFile = null;
  s.topName = "";
  if (!keepMode) s.mode = "folder";
  renderDropzone(side);
  updateCompareButton();
}

function setFolderEntries(side, entries) {
  const s = state.sides[side];
  s.entries = entries;
  s.zipFile = null;
  s.topName = entries.length ? entries[0].relPath.split("/")[0] : "";
  renderDropzone(side);
  updateCompareButton();
}

function setZipFile(side, file) {
  const s = state.sides[side];
  s.zipFile = file;
  s.entries = null;
  s.topName = file.name;
  renderDropzone(side);
  updateCompareButton();
}

function renderDropzone(side) {
  const dz = $(`.dropzone[data-side="${side}"]`);
  const s = state.sides[side];
  const clearBtn = $(`.clear-btn[data-side="${side}"]`);

  if (s.entries && s.entries.length) {
    const totalSize = s.entries.reduce((sum, e) => sum + (e.file.size || 0), 0);
    dz.classList.add("has-content");
    dz.querySelector(".dz-empty")?.remove();
    dz.innerHTML = `<div class="loaded-summary"><div class="icon">📁</div>
      <div><span class="n">${s.entries.length}</span> files &middot; ${fmtBytes(totalSize)}</div>
      <div class="loaded-name">${escapeHtml(s.topName || "")}</div></div>`;
    dz.appendChild(clearBtn);
    clearBtn.classList.remove("hidden");
  } else if (s.zipFile) {
    dz.classList.add("has-content");
    dz.innerHTML = `<div class="loaded-summary"><div class="icon">🗜️</div>
      <div>${fmtBytes(s.zipFile.size)}</div>
      <div class="loaded-name">${escapeHtml(s.zipFile.name)}</div></div>`;
    dz.appendChild(clearBtn);
    clearBtn.classList.remove("hidden");
  } else {
    dz.classList.remove("has-content");
    dz.innerHTML = `<div class="dz-empty"><div class="icon">${s.mode === "zip" ? "🗜️" : "📁"}</div>
      <div class="hint">Drag &amp; drop, or <span class="browse-link">browse</span></div></div>`;
    dz.appendChild(clearBtn);
    clearBtn.classList.add("hidden");
  }
}

function updateCompareButton() {
  const ok = (state.sides.left.entries?.length || state.sides.left.zipFile) &&
             (state.sides.right.entries?.length || state.sides.right.zipFile);
  $("#btn-compare").disabled = !ok;
}

function initDropzones() {
  for (const side of ["left", "right"]) {
    const dz = $(`.dropzone[data-side="${side}"]`);

    dz.addEventListener("click", (e) => {
      if (e.target.closest(".clear-btn")) return;
      pendingSide = side;
      if (state.sides[side].mode === "zip") $("#file-input-zip").click();
      else $("#file-input-folder").click();
    });
    dz.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); dz.click(); }
    });

    dz.addEventListener("dragover", (e) => { e.preventDefault(); dz.classList.add("dragover"); });
    dz.addEventListener("dragleave", () => dz.classList.remove("dragover"));
    dz.addEventListener("drop", (e) => {
      e.preventDefault();
      dz.classList.remove("dragover");
      if (e.dataTransfer.items && e.dataTransfer.items.length) {
        handleDataTransferItems(side, e.dataTransfer.items);
      }
    });

    $(`.clear-btn[data-side="${side}"]`).addEventListener("click", (e) => {
      e.stopPropagation();
      clearSide(side, true);
    });

    $$(`.mode-tabs[data-side="${side}"] button`).forEach((btn) => {
      btn.addEventListener("click", () => setMode(side, btn.dataset.mode));
    });
  }

  $("#file-input-folder").addEventListener("change", (e) => {
    const files = Array.from(e.target.files || []);
    if (!files.length || !pendingSide) return;
    const entries = files.map((f) => ({ file: f, relPath: f.webkitRelativePath || f.name }));
    setFolderEntries(pendingSide, entries);
    e.target.value = "";
  });

  $("#file-input-zip").addEventListener("change", (e) => {
    const file = e.target.files && e.target.files[0];
    if (!file || !pendingSide) return;
    setZipFile(pendingSide, file);
    e.target.value = "";
  });
}

// ============================================================== compare
async function runCompare() {
  const form = new FormData();
  const left = state.sides.left, right = state.sides.right;

  form.append("left_kind", left.mode);
  form.append("right_kind", right.mode);
  form.append("left_label", $('.label-input[data-side="left"]').value.trim());
  form.append("right_label", $('.label-input[data-side="right"]').value.trim());
  form.append("ignore_patterns", $("#ignore-patterns").value);
  form.append("ignore_whitespace", $("#opt-ignore-whitespace").checked);
  form.append("ignore_blank_lines", $("#opt-ignore-blank-lines").checked);
  form.append("ignore_case", $("#opt-ignore-case").checked);
  form.append("detect_renames", $("#opt-detect-renames").checked);

  if (left.mode === "zip") form.append("left_zip", left.zipFile);
  else left.entries.forEach((e) => form.append("left_files", e.file, e.relPath));

  if (right.mode === "zip") form.append("right_zip", right.zipFile);
  else right.entries.forEach((e) => form.append("right_files", e.file, e.relPath));

  $("#compare-error").classList.add("hidden");
  showLoading("Scanning and comparing…");
  try {
    const res = await fetch("/api/compare", { method: "POST", body: form });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || "Comparison failed");
    }
    const data = await res.json();
    state.comparisonId = data.comparison_id;
    await loadSummary();
    showView("summary");
    $("#topbar-crumb").classList.remove("hidden");
    $("#btn-new-comparison").classList.remove("hidden");
  } catch (err) {
    $("#compare-error").textContent = err.message;
    $("#compare-error").classList.remove("hidden");
  } finally {
    hideLoading();
  }
}

async function loadSummary() {
  const res = await fetch(`/api/comparison/${state.comparisonId}/summary`);
  const data = await res.json();
  state.summary = data;
  renderSummary(data);
  $("#crumb-left").textContent = data.left_label;
  $("#crumb-right").textContent = data.right_label;
}

function renderSummary(data) {
  const s = data.summary;
  $("#summary-left").textContent = data.left_label;
  $("#summary-right").textContent = data.right_label;
  $("#summary-meta").textContent = `${s.total} files compared in ${data.duration_seconds}s`;
  $("#stat-added").textContent = s.added;
  $("#stat-deleted").textContent = s.deleted;
  $("#stat-modified").textContent = s.modified;
  $("#stat-renamed").textContent = s.renamed;
  $("#stat-unchanged").textContent = s.unchanged;

  const total = Math.max(s.total, 1);
  const bar = $("#diffstat-bar");
  bar.innerHTML = "";
  [["seg-added", s.added], ["seg-deleted", s.deleted], ["seg-modified", s.modified],
   ["seg-renamed", s.renamed], ["seg-unchanged", s.unchanged]].forEach(([cls, n]) => {
    if (!n) return;
    const seg = document.createElement("span");
    seg.className = cls;
    seg.style.width = `${(n / total) * 100}%`;
    seg.title = `${cls.replace("seg-", "")}: ${n}`;
    bar.appendChild(seg);
  });

  $("#explorer-stats").innerHTML =
    `<span><b>${s.total}</b> files</span><span><b>${s.modified}</b> modified</span>` +
    `<span><b>${s.added}</b> added</span><span><b>${s.deleted}</b> deleted</span>`;
}

// ============================================================== explorer: tree
async function loadTree() {
  const res = await fetch(`/api/comparison/${state.comparisonId}/tree`);
  state.tree = await res.json();
  renderTree();
}

function nodeVisible(node) {
  if (node.type === "dir") return node.children.some(nodeVisible);
  if (state.hideUnchanged && node.status === "unchanged") return false;
  if (state.filterStatus !== "all" && node.status !== state.filterStatus) return false;
  return true;
}

function renderTree() {
  const root = $("#tree-scroll");
  root.innerHTML = "";
  state.flatOrder = [];

  if (!state.tree || !state.tree.children.length) {
    root.innerHTML = `<div class="empty-state">No files found.</div>`;
    return;
  }

  const frag = document.createDocumentFragment();
  const visibleTop = state.tree.children.filter(nodeVisible);
  if (!visibleTop.length) {
    root.innerHTML = `<div class="empty-state">No files match the current filter.</div>`;
    return;
  }
  visibleTop.forEach((child) => frag.appendChild(buildTreeNode(child, 0)));
  root.appendChild(frag);
}

function buildTreeNode(node, depth) {
  const wrap = document.createElement("div");
  wrap.className = "tree-node";

  const row = document.createElement("div");
  row.className = "tree-row";
  row.style.paddingLeft = `${8 + depth * 14}px`;
  row.dataset.path = node.path;

  if (node.type === "dir") {
    const childrenVisible = node.children.filter(nodeVisible);
    row.innerHTML = `<span class="chev">▾</span><span class="ic">📁</span><span class="nm">${escapeHtml(node.name)}</span>`;
    wrap.appendChild(row);

    const childWrap = document.createElement("div");
    childWrap.className = "tree-children open";
    childrenVisible.forEach((c) => childWrap.appendChild(buildTreeNode(c, depth + 1)));
    wrap.appendChild(childWrap);

    row.addEventListener("click", () => {
      const open = childWrap.classList.toggle("open");
      row.querySelector(".chev").textContent = open ? "▾" : "▸";
    });
  } else {
    const icon = node.is_binary ? "⬛" : "📄";
    row.innerHTML =
      `<span class="chev"></span><span class="ic">${icon}</span><span class="nm">${escapeHtml(node.name)}</span>` +
      `<span class="status-dot ${node.status}"></span>`;
    row.addEventListener("click", () => selectFile(node.path));
    wrap.appendChild(row);
    state.flatOrder.push(node.path);
  }

  return wrap;
}

// ============================================================== explorer: flat list
async function loadFileList() {
  const q = $("#global-search").value.trim();
  const params = new URLSearchParams({ status: state.filterStatus, q });
  const res = await fetch(`/api/comparison/${state.comparisonId}/changes?${params}`);
  const data = await res.json();
  let changes = data.changes;
  if (state.hideUnchanged) changes = changes.filter((c) => c.status !== "unchanged");
  renderFileList(changes);
}

function renderFileList(changes) {
  const root = $("#filelist-scroll");
  root.innerHTML = "";
  state.flatOrder = changes.map((c) => c.rel_path);

  if (!changes.length) {
    root.innerHTML = `<div class="empty-state">No files match.</div>`;
    return;
  }
  const frag = document.createDocumentFragment();
  changes.forEach((c) => {
    const row = document.createElement("div");
    row.className = "filerow";
    row.dataset.path = c.rel_path;
    const renameNote = c.status === "renamed" ? ` <span style="color:var(--text-faint)">(was ${escapeHtml(c.left_path)})</span>` : "";
    row.innerHTML = `<span class="badge ${c.status}">${STATUS_ICON[c.status]}</span><span class="p">${escapeHtml(c.rel_path)}${renameNote}</span>`;
    row.addEventListener("click", () => selectFile(c.rel_path));
    frag.appendChild(row);
  });
  root.appendChild(frag);
}

function refreshSidebar() {
  if (state.sidebarTab === "tree") loadTree(); else loadFileList();
}

function markSelectedInSidebar(path) {
  $$(".tree-row, .filerow").forEach((el) => el.classList.toggle("selected", el.dataset.path === path));
  state.selectedIndex = state.flatOrder.indexOf(path);
}

// ============================================================== diff panel
async function selectFile(path) {
  state.selectedPath = path;
  markSelectedInSidebar(path);
  await openDiff(path);
}

async function openDiff(path, { force = false } = {}) {
  const cacheKey = `${path}::${state.viewOptionsKey()}::${force}`;
  let diff = state.diffCache.get(cacheKey);
  if (!diff) {
    const params = new URLSearchParams({
      path,
      ignore_whitespace: $("#opt-ignore-whitespace").checked,
      ignore_blank_lines: $("#opt-ignore-blank-lines").checked,
      ignore_case: $("#opt-ignore-case").checked,
      collapse_unchanged: state.expandedDiffPaths.has(path) ? "false" : "true",
      force: force ? "true" : "false",
    });
    const res = await fetch(`/api/comparison/${state.comparisonId}/diff?${params}`);
    if (!res.ok) return;
    diff = await res.json();
    state.diffCache.set(cacheKey, diff);
  }
  state.currentDiff = diff;
  renderDiffPanel(diff);
}

state.viewOptionsKey = () =>
  [$("#opt-ignore-whitespace").checked, $("#opt-ignore-blank-lines").checked, $("#opt-ignore-case").checked].join(",");

function renderDiffPanel(diff) {
  $("#diff-header").classList.remove("hidden");
  $("#diff-file-path").textContent = diff.rel_path;
  const pill = $("#diff-status-pill");
  pill.className = `status-pill ${diff.status}`;
  pill.textContent = diff.status;
  $("#diff-stat-inline").innerHTML = diff.is_binary
    ? ""
    : `<span class="add-n">+${diff.additions}</span> <span class="del-n">-${diff.deletions}</span>`;

  const scroll = $("#diff-scroll");

  if (diff.is_binary) {
    scroll.innerHTML = renderBinaryPanel(diff);
    return;
  }
  if (diff.skipped_reason) {
    scroll.innerHTML = `<div class="large-file-warning">⚠️ ${escapeHtml(diff.skipped_reason)}
      <br><button class="btn primary" id="btn-force-diff">Diff anyway</button></div>`;
    $("#btn-force-diff").addEventListener("click", () => openDiff(diff.rel_path, { force: true }));
    return;
  }

  scroll.innerHTML = state.viewMode === "unified" ? renderUnified(diff) : renderSideBySide(diff);
  wireSkipRowExpansion(diff.rel_path);
  computeMarkers();
}

function renderBinaryPanel(diff) {
  const identical = diff.identical;
  return `<div class="binary-panel"><div class="box">
    <div class="box-header">Binary file ${identical ? "unchanged" : "changed"}</div>
    <div class="binary-cols">
      <div class="binary-col">
        <div><span class="k">Left size:</span> <span class="v">${diff.left_missing ? "— (missing)" : fmtBytes(diff.left_size)}</span></div>
        <div><span class="k">SHA-256:</span> <span class="v">${diff.left_hash || "—"}</span></div>
      </div>
      <div class="binary-col">
        <div><span class="k">Right size:</span> <span class="v">${diff.right_missing ? "— (missing)" : fmtBytes(diff.right_size)}</span></div>
        <div><span class="k">SHA-256:</span> <span class="v">${diff.right_hash || "—"}</span></div>
      </div>
    </div>
  </div>
  <div class="${identical ? "binary-identical" : "binary-changed"}">${identical ? "✓ Files are identical" : "⚠ Files differ"}</div>
  </div>`;
}

function renderSideBySide(diff) {
  const rows = diff.rows.map((r) => {
    if (r.op === "context_skip") {
      return `<tr class="row-skip" data-skip="1"><td colspan="4">⋮ ${r.skipped_count} unchanged line(s) hidden — click to expand ⋮</td></tr>`;
    }
    const cls = r.op === "add" ? "row-add" : r.op === "delete" ? "row-del" : r.op === "replace" ? "row-del" : "row-eq";
    const ln = r.left_no ?? "";
    const rn = r.right_no ?? "";
    const lt = r.left_text !== null && r.left_text !== undefined ? escapeHtml(r.left_text) : "";
    const rt = r.right_text !== null && r.right_text !== undefined ? escapeHtml(r.right_text) : "";
    if (r.op === "replace") {
      return `<tr class="row-del"><td class="lineno">${ln}</td><td class="code">${lt}</td>` +
             `<td class="lineno">${rn}</td><td class="code" style="background:var(--add-bg);color:var(--add-text)">${rt}</td></tr>`;
    }
    return `<tr class="${cls}"><td class="lineno">${ln}</td><td class="code">${lt}</td><td class="lineno">${rn}</td><td class="code">${rt}</td></tr>`;
  }).join("");
  return `<table class="diff-table">
    <colgroup><col style="width:44px"><col style="width:calc(50% - 44px)"><col style="width:44px"><col style="width:calc(50% - 44px)"></colgroup>
    ${rows}</table>`;
}

function renderUnified(diff) {
  let leftNo = 0, rightNo = 0;
  const rows = [];
  for (const line of diff.unified) {
    if (line.startsWith("---") || line.startsWith("+++")) continue;
    if (line.startsWith("@@")) {
      const m = /-(\d+)(?:,\d+)? \+(\d+)/.exec(line);
      if (m) { leftNo = parseInt(m[1], 10) - 1; rightNo = parseInt(m[2], 10) - 1; }
      rows.push(`<tr class="row-skip"><td colspan="3">${escapeHtml(line)}</td></tr>`);
      continue;
    }
    const marker = line[0];
    const text = escapeHtml(line.slice(1));
    if (marker === "+") { rightNo++; rows.push(`<tr class="row-add"><td class="marker">+</td><td class="lineno">${rightNo}</td><td class="code">${text}</td></tr>`); }
    else if (marker === "-") { leftNo++; rows.push(`<tr class="row-del"><td class="marker">-</td><td class="lineno">${leftNo}</td><td class="code">${text}</td></tr>`); }
    else { leftNo++; rightNo++; rows.push(`<tr class="row-eq"><td class="marker"></td><td class="lineno">${leftNo}</td><td class="code">${text}</td></tr>`); }
  }
  if (!rows.length) return `<div class="diff-empty"><div class="icon">✓</div><div>No textual differences</div></div>`;
  return `<table class="diff-table unified-view">${rows.join("")}</table>`;
}

function wireSkipRowExpansion(path) {
  $$('#diff-scroll tr.row-skip[data-skip="1"]').forEach((tr) => {
    tr.addEventListener("click", () => {
      state.expandedDiffPaths.add(path);
      openDiff(path);
    });
  });
}

function computeMarkers() {
  state.markerRows = $$('#diff-scroll tr.row-add, #diff-scroll tr.row-del');
  state.markerIndex = -1;
}

function gotoMarker(delta) {
  if (!state.markerRows.length) return;
  state.markerIndex = (state.markerIndex + delta + state.markerRows.length) % state.markerRows.length;
  const row = state.markerRows[state.markerIndex];
  row.scrollIntoView({ block: "center", behavior: "smooth" });
  row.style.outline = "1px solid var(--accent)";
  setTimeout(() => (row.style.outline = ""), 700);
}

// ============================================================== search
let searchDebounce = null;
function initSearch() {
  $("#global-search").addEventListener("input", () => {
    clearTimeout(searchDebounce);
    searchDebounce = setTimeout(() => {
      if (state.sidebarTab === "list") loadFileList();
      else {
        // filter tree client-side by name via a quick re-render pass
        renderTree();
      }
    }, 180);
  });
  $("#global-search").addEventListener("keydown", (e) => {
    if (e.key === "Escape") { $("#global-search").value = ""; $("#global-search").blur(); refreshSidebar(); }
  });
}

// ============================================================== export
function triggerDownload(url) {
  const a = document.createElement("a");
  a.href = url;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
}
function exportJson() { triggerDownload(`/api/comparison/${state.comparisonId}/export/json`); }
function exportHtml() { triggerDownload(`/api/comparison/${state.comparisonId}/export/html`); }

// ============================================================== wiring
function initFilterChips() {
  $$(".filter-chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      $$(".filter-chip").forEach((c) => c.classList.remove("active"));
      chip.classList.add("active");
      state.filterStatus = chip.dataset.status;
      refreshSidebar();
    });
  });
  $("#opt-hide-unchanged").addEventListener("change", (e) => {
    state.hideUnchanged = e.target.checked;
    refreshSidebar();
  });
}

function initSidebarTabs() {
  $$(".sidebar-tabs button").forEach((btn) => {
    btn.addEventListener("click", () => {
      $$(".sidebar-tabs button").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.sidebarTab = btn.dataset.tab;
      $("#tree-scroll").classList.toggle("hidden", state.sidebarTab !== "tree");
      $("#filelist-scroll").classList.toggle("hidden", state.sidebarTab !== "list");
      refreshSidebar();
    });
  });
}

function initViewToggle() {
  $$(".view-toggle button").forEach((btn) => {
    btn.addEventListener("click", () => {
      $$(".view-toggle button").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.viewMode = btn.dataset.mode;
      if (state.currentDiff) renderDiffPanel(state.currentDiff);
    });
  });
}

function initDiffOptionListeners() {
  ["opt-ignore-whitespace", "opt-ignore-blank-lines", "opt-ignore-case"].forEach((id) => {
    $(`#${id}`).addEventListener("change", () => {
      if (state.selectedPath) openDiff(state.selectedPath);
    });
  });
}

function initKeyboardNav() {
  document.addEventListener("keydown", (e) => {
    const typing = ["INPUT", "TEXTAREA"].includes(document.activeElement.tagName);

    if (e.key === "/" && !typing) {
      e.preventDefault();
      $("#global-search").focus();
      return;
    }
    if (typing) return;

    if (!$("#view-explorer").classList.contains("active")) return;

    if (e.key === "ArrowDown" || e.key === "j") {
      e.preventDefault();
      if (state.flatOrder.length) {
        const next = Math.min(state.selectedIndex + 1, state.flatOrder.length - 1);
        selectFile(state.flatOrder[Math.max(next, 0)]);
      }
    } else if (e.key === "ArrowUp" || e.key === "k") {
      e.preventDefault();
      if (state.flatOrder.length) {
        const prev = Math.max(state.selectedIndex - 1, 0);
        selectFile(state.flatOrder[prev]);
      }
    } else if (e.key === "n") {
      gotoMarker(1);
    } else if (e.key === "p" || e.key === "N") {
      gotoMarker(-1);
    }
  });
}

function initButtons() {
  $("#btn-compare").addEventListener("click", runCompare);
  $("#btn-open-explorer").addEventListener("click", async () => {
    showView("explorer");
    await loadTree();
  });
  $("#btn-new-comparison").addEventListener("click", () => {
    if (state.comparisonId) {
      fetch(`/api/comparison/${state.comparisonId}`, { method: "DELETE" }).catch(() => {});
    }
    Object.assign(state, {
      comparisonId: null, summary: null, tree: null, selectedPath: null,
      diffCache: new Map(), currentDiff: null, expandedDiffPaths: new Set(),
    });
    clearSide("left"); clearSide("right");
    $("#topbar-crumb").classList.add("hidden");
    $("#btn-new-comparison").classList.add("hidden");
    showView("landing");
  });
  $("#btn-export-json").addEventListener("click", exportJson);
  $("#btn-export-html").addEventListener("click", exportHtml);
  $("#btn-export-json-2").addEventListener("click", exportJson);
  $("#btn-export-html-2").addEventListener("click", exportHtml);
  $("#btn-prev-change").addEventListener("click", () => gotoMarker(-1));
  $("#btn-next-change").addEventListener("click", () => gotoMarker(1));
}

// ============================================================== init
function init() {
  initDropzones();
  initFilterChips();
  initSidebarTabs();
  initViewToggle();
  initDiffOptionListeners();
  initKeyboardNav();
  initSearch();
  initButtons();
}

document.addEventListener("DOMContentLoaded", init);
