const DEFAULT_SOURCE = `import "std:dnd/core"

attack_bonus = 7
target_ac = [ac:10, 12, 14, 16, 18, 20]

d20 + attack_bonus >= target_ac`;

const LEGACY_SOURCE_STORAGE_KEY = "dice-web:last-source";
const WORKSPACE_STORAGE_KEY = "dice-web:workspace";
const WORKSPACE_DB_NAME = "dice-web";
const WORKSPACE_DB_VERSION = 1;
const WORKSPACE_STORE_NAME = "workspace";
const WORKSPACE_RECORD_KEY = "current";

const runButton = document.querySelector("#run-button");
const shareButton = document.querySelector("#share-button");
const loadFileButton = document.querySelector("#load-file-button");
const saveFileButton = document.querySelector("#save-file-button");
const saveAsFileButton = document.querySelector("#save-as-file-button");
const loadSampleButton = document.querySelector("#load-sample-button");
const closeAllButton = document.querySelector("#close-all-button");
const textOutput = document.querySelector("#text-output");
const jsonOutput = document.querySelector("#json-output");
const diagnosticPanel = document.querySelector("#diagnostic-panel");
const diagnosticOutput = document.querySelector("#diagnostic-output");
const chartOutput = document.querySelector("#chart-output");
const chartEmpty = document.querySelector("#chart-empty");
const chartPanel = document.querySelector("#chart-panel");
const resultsPanel = document.querySelector(".results-panel");
const editorSurface = document.querySelector("#editor");
const fileTabs = document.querySelector("#file-tabs");
const fileInput = document.querySelector("#file-input");
const sampleDialog = document.querySelector("#sample-dialog");
const sampleDialogSelect = document.querySelector("#sample-dialog-select");
const sampleDialogConfirm = document.querySelector("#sample-dialog-confirm");
const resultTabs = Array.from(document.querySelectorAll("[data-result-tab]"));
const resultPanels = {
  charts: chartPanel,
  raw: document.querySelector("#raw-panel"),
  json: document.querySelector("#json-panel"),
};

let rpcId = 0;
let samples = [];
let saveUrlTimer = null;
let suppressEditorSync = false;
let fallbackTextarea = null;
let aceEditor = null;
let activeResultTab = "charts";
let editorResizeFrame = 0;
let editorResizeObserver = null;
let fileHandles = new Map();
let renamingFilePath = null;
let workspaceSavePromise = null;
let workspaceSaveQueued = false;
let completionRequestId = 0;
let diceAceModeRegistered = false;

let activeWorkspace = loadInitialWorkspace();

const worker = new Worker(new URL("./worker.js", import.meta.url));
const pendingRpc = new Map();

worker.addEventListener("message", (event) => {
  const { id, ok, result, error } = event.data;
  const entry = pendingRpc.get(id);
  if (!entry) {
    return;
  }
  pendingRpc.delete(id);
  if (ok) {
    entry.resolve(result);
    return;
  }
  entry.reject(new Error(error?.message ?? "Worker request failed"));
});

function callWorker(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++rpcId;
    pendingRpc.set(id, { resolve, reject });
    worker.postMessage({ id, method, params });
  });
}

function createWorkspace({ files, entryPath, samplePath = null, activeFilePath = null, openFiles = null }) {
  const normalizedFiles = Object.fromEntries(
    Object.entries(files ?? {}).map(([path, source]) => [path, String(source ?? "")]),
  );
  if (!Object.hasOwn(normalizedFiles, entryPath)) {
    normalizedFiles[entryPath] = "";
  }

  const fallbackOpenFiles = Object.keys(normalizedFiles).sort((left, right) => {
    if (left === entryPath) {
      return -1;
    }
    if (right === entryPath) {
      return 1;
    }
    return left.localeCompare(right);
  });
  const nextOpenFiles = Array.isArray(openFiles)
    ? [...new Set(openFiles.filter((path) => Object.hasOwn(normalizedFiles, path)))]
    : [];
  if (!nextOpenFiles.includes(entryPath)) {
    nextOpenFiles.unshift(entryPath);
  }

  const resolvedActiveFilePath =
    activeFilePath && Object.hasOwn(normalizedFiles, activeFilePath) ? activeFilePath : entryPath;
  if (!nextOpenFiles.includes(resolvedActiveFilePath)) {
    nextOpenFiles.push(resolvedActiveFilePath);
  }

  return {
    samplePath,
    files: normalizedFiles,
    entryPath,
    openFiles: nextOpenFiles.length > 0 ? nextOpenFiles : fallbackOpenFiles,
    activeFilePath: resolvedActiveFilePath,
  };
}

function serializeWorkspace() {
  return {
    samplePath: activeWorkspace.samplePath,
    files: activeWorkspace.files,
    entryPath: activeWorkspace.entryPath,
    openFiles: activeWorkspace.openFiles,
    activeFilePath: activeWorkspace.activeFilePath,
    updatedAt: Date.now(),
  };
}

function createWorkspaceFromSnapshot(snapshot) {
  if (
    !snapshot ||
    typeof snapshot !== "object" ||
    !snapshot.files ||
    typeof snapshot.files !== "object" ||
    typeof snapshot.entryPath !== "string"
  ) {
    return null;
  }

  return createWorkspace({
    files: snapshot.files,
    entryPath: snapshot.entryPath,
    samplePath: typeof snapshot.samplePath === "string" ? snapshot.samplePath : null,
    activeFilePath: typeof snapshot.activeFilePath === "string" ? snapshot.activeFilePath : null,
    openFiles: Array.isArray(snapshot.openFiles) ? snapshot.openFiles : null,
  });
}

function applyWorkspaceSnapshot(snapshot) {
  const nextWorkspace = createWorkspaceFromSnapshot(snapshot);
  if (!nextWorkspace) {
    return false;
  }
  activeWorkspace = nextWorkspace;
  fileHandles = new Map();
  renamingFilePath = null;
  renderFileTabs();
  setEditorValue(currentSource());
  return true;
}

function readStoredWorkspaceSnapshot() {
  try {
    const rawWorkspace = window.localStorage.getItem(WORKSPACE_STORAGE_KEY);
    if (!rawWorkspace) {
      return null;
    }
    const parsedWorkspace = JSON.parse(rawWorkspace);
    if (!createWorkspaceFromSnapshot(parsedWorkspace)) {
      return null;
    }
    return parsedWorkspace;
  } catch (_error) {
    return null;
  }
}

function openWorkspaceDb() {
  if (!("indexedDB" in window)) {
    return Promise.resolve(null);
  }

  return new Promise((resolve, reject) => {
    const request = window.indexedDB.open(WORKSPACE_DB_NAME, WORKSPACE_DB_VERSION);
    request.addEventListener("upgradeneeded", () => {
      const database = request.result;
      if (!database.objectStoreNames.contains(WORKSPACE_STORE_NAME)) {
        database.createObjectStore(WORKSPACE_STORE_NAME);
      }
    });
    request.addEventListener("success", () => {
      resolve(request.result);
    });
    request.addEventListener("error", () => {
      reject(request.error ?? new Error("Failed to open workspace database"));
    });
  });
}

async function writeWorkspaceSnapshotToIndexedDb(snapshot) {
  const database = await openWorkspaceDb();
  if (!database) {
    return;
  }

  await new Promise((resolve, reject) => {
    const transaction = database.transaction(WORKSPACE_STORE_NAME, "readwrite");
    const store = transaction.objectStore(WORKSPACE_STORE_NAME);
    store.put(snapshot, WORKSPACE_RECORD_KEY);
    transaction.addEventListener("complete", resolve);
    transaction.addEventListener("error", () => {
      reject(transaction.error ?? new Error("Failed to save workspace"));
    });
    transaction.addEventListener("abort", () => {
      reject(transaction.error ?? new Error("Failed to save workspace"));
    });
  });
}

async function readWorkspaceSnapshotFromIndexedDb() {
  const database = await openWorkspaceDb();
  if (!database) {
    return null;
  }

  return new Promise((resolve, reject) => {
    const transaction = database.transaction(WORKSPACE_STORE_NAME, "readonly");
    const store = transaction.objectStore(WORKSPACE_STORE_NAME);
    const request = store.get(WORKSPACE_RECORD_KEY);
    request.addEventListener("success", () => {
      resolve(request.result ?? null);
    });
    request.addEventListener("error", () => {
      reject(request.error ?? new Error("Failed to load workspace"));
    });
  });
}

async function restoreWorkspaceFromIndexedDb() {
  try {
    const indexedDbSnapshot = await readWorkspaceSnapshotFromIndexedDb();
    const localSnapshot = readStoredWorkspaceSnapshot();
    const indexedDbTimestamp = Number(indexedDbSnapshot?.updatedAt ?? 0);
    const localTimestamp = Number(localSnapshot?.updatedAt ?? 0);

    if (!indexedDbSnapshot || indexedDbTimestamp <= localTimestamp) {
      return Boolean(createWorkspaceFromSnapshot(localSnapshot));
    }

    if (!applyWorkspaceSnapshot(indexedDbSnapshot)) {
      return Boolean(createWorkspaceFromSnapshot(localSnapshot));
    }
    persistWorkspace();
    return true;
  } catch (_error) {
    return Boolean(createWorkspaceFromSnapshot(readStoredWorkspaceSnapshot()));
  }
}

function loadLegacySavedSource() {
  const saved = window.localStorage.getItem(LEGACY_SOURCE_STORAGE_KEY);
  return saved || DEFAULT_SOURCE;
}

function loadInitialWorkspace() {
  const storedWorkspace = readStoredWorkspaceSnapshot();
  const initialWorkspace = createWorkspaceFromSnapshot(storedWorkspace);
  if (initialWorkspace) {
    return initialWorkspace;
  }

  return createWorkspace({
    files: { "main.dice": loadLegacySavedSource() },
    entryPath: "main.dice",
  });
}

function currentEditorValue() {
  if (aceEditor) {
    return aceEditor.getValue();
  }
  return fallbackTextarea.value;
}

function setEditorValue(value) {
  suppressEditorSync = true;
  if (aceEditor) {
    aceEditor.session.setValue(value);
    aceEditor.clearSelection();
  } else {
    fallbackTextarea.value = value;
  }
  suppressEditorSync = false;
}

function syncEditorLayout() {
  if (!aceEditor) {
    return;
  }
  if (editorResizeFrame) {
    window.cancelAnimationFrame(editorResizeFrame);
  }
  editorResizeFrame = window.requestAnimationFrame(() => {
    editorResizeFrame = 0;
    aceEditor.resize(true);
  });
}

function installEditorResizeHandling() {
  const handleResize = () => {
    syncEditorLayout();
  };

  window.addEventListener("resize", handleResize);
  window.visualViewport?.addEventListener("resize", handleResize);

  if ("ResizeObserver" in window) {
    editorResizeObserver = new ResizeObserver(() => {
      syncEditorLayout();
    });
    editorResizeObserver.observe(editorSurface);
  }
}

function syncActiveFileFromEditor() {
  if (suppressEditorSync) {
    return;
  }
  activeWorkspace.files[activeWorkspace.activeFilePath] = currentEditorValue();
  persistWorkspace();
}

function currentSource() {
  return activeWorkspace.files[activeWorkspace.activeFilePath] ?? "";
}

function entrySource() {
  return activeWorkspace.files[activeWorkspace.entryPath] ?? "";
}

function queueWorkspaceSave(snapshot) {
  if (workspaceSavePromise) {
    workspaceSaveQueued = true;
    return;
  }

  workspaceSavePromise = writeWorkspaceSnapshotToIndexedDb(snapshot)
    .catch(() => {})
    .finally(() => {
      workspaceSavePromise = null;
      if (workspaceSaveQueued) {
        workspaceSaveQueued = false;
        queueWorkspaceSave(serializeWorkspace());
      }
    });
}

function persistWorkspace() {
  const snapshot = serializeWorkspace();
  window.localStorage.setItem(WORKSPACE_STORAGE_KEY, JSON.stringify(snapshot));
  window.localStorage.setItem(LEGACY_SOURCE_STORAGE_KEY, entrySource());
  queueWorkspaceSave(snapshot);
  saveUrlState();
}

function shouldWarnBeforeUnload() {
  return Boolean(workspaceSavePromise || workspaceSaveQueued);
}

function replaceCurrentFileSource(nextSource) {
  activeWorkspace.files[activeWorkspace.activeFilePath] = nextSource;
  setEditorValue(nextSource);
  persistWorkspace();
}

function resetWorkspace() {
  const source = currentSource();
  activeWorkspace = createWorkspace({
    files: { "main.dice": source },
    entryPath: "main.dice",
  });
  fileHandles = new Map();
  renderFileTabs();
  setEditorValue(currentSource());
  persistWorkspace();
}

function refreshWorkspaceActions() {
  closeAllButton.disabled = activeWorkspace.openFiles.length <= 1;
}

function basename(path) {
  const parts = path.split("/");
  return parts[parts.length - 1];
}

function dirname(path) {
  const parts = path.split("/");
  parts.pop();
  return parts.join("/");
}

function splitExtension(path) {
  const dotIndex = path.lastIndexOf(".");
  if (dotIndex <= 0) {
    return { stem: path, extension: "" };
  }
  return {
    stem: path.slice(0, dotIndex),
    extension: path.slice(dotIndex),
  };
}

function createUniquePath(path, takenPaths = new Set(Object.keys(activeWorkspace.files))) {
  if (!takenPaths.has(path)) {
    return path;
  }

  const { stem, extension } = splitExtension(path);
  let index = 2;
  let candidate = `${stem}-${index}${extension}`;
  while (takenPaths.has(candidate)) {
    index += 1;
    candidate = `${stem}-${index}${extension}`;
  }
  return candidate;
}

function preferredEntryPath(paths) {
  if (paths.includes("main.dice")) {
    return "main.dice";
  }
  return paths[0] ?? "main.dice";
}

function isUnnamedPath(path) {
  return /^untitled(?:-\d+)?(?:\.dice)?$/i.test(basename(path));
}

function normalizeFileName(name, { preserveDirectory = false, basePath = "" } = {}) {
  if (typeof name !== "string") {
    return null;
  }

  const trimmed = name.trim();
  if (!trimmed) {
    return null;
  }

  const normalized = trimmed.replace(/\\/g, "/").replace(/^\.\/+/, "");
  const pieces = normalized
    .split("/")
    .map((segment) => segment.trim())
    .filter(Boolean);
  if (!pieces.length) {
    return null;
  }

  let filePath = pieces.join("/");
  if (!basename(filePath).includes(".")) {
    filePath += ".dice";
  }

  if (preserveDirectory) {
    const parentPath = dirname(basePath);
    if (pieces.length === 1 && parentPath) {
      return `${parentPath}/${basename(filePath)}`;
    }
  }

  return filePath;
}

function normalizeWorkspacePath(path) {
  const normalized = String(path ?? "").replace(/\\/g, "/").replace(/^\/+/, "");
  const segments = normalized.split("/");
  const resolved = [];
  for (const segment of segments) {
    if (!segment || segment === ".") {
      continue;
    }
    if (segment === "..") {
      if (!resolved.length) {
        return null;
      }
      resolved.pop();
      continue;
    }
    resolved.push(segment);
  }
  return resolved.join("/");
}

function workspacePathForImport(importPath, sourcePath) {
  if (importPath.startsWith("std:")) {
    const normalizedStdlibPath = normalizeWorkspacePath(importPath.slice(4));
    if (!normalizedStdlibPath) {
      return null;
    }
    return basename(normalizedStdlibPath).includes(".") ? normalizedStdlibPath : `${normalizedStdlibPath}.dice`;
  }

  const baseDirectory = dirname(sourcePath);
  const combinedPath = baseDirectory ? `${baseDirectory}/${importPath}` : importPath;
  const normalizedPath = normalizeWorkspacePath(combinedPath);
  if (!normalizedPath) {
    return null;
  }
  return basename(normalizedPath).includes(".") ? normalizedPath : `${normalizedPath}.dice`;
}

function importLinkAtPosition(source, row, column) {
  const lines = source.split("\n");
  const line = lines[row] ?? "";
  const importPattern = /\bimport\s+"([^"]+)"/g;
  let match;
  while ((match = importPattern.exec(line)) !== null) {
    const importPath = match[1];
    const startColumn = match.index + match[0].indexOf(importPath);
    const endColumn = startColumn + importPath.length;
    if (column >= startColumn && column <= endColumn) {
      return {
        importPath,
        startColumn,
        endColumn,
      };
    }
  }
  return null;
}

function ensureFileVisible(path) {
  if (!Object.hasOwn(activeWorkspace.files, path)) {
    return false;
  }
  if (!activeWorkspace.openFiles.includes(path)) {
    activeWorkspace.openFiles = [...activeWorkspace.openFiles, path];
  }
  activeWorkspace.activeFilePath = path;
  renderFileTabs();
  setEditorValue(currentSource());
  persistWorkspace();
  return true;
}

async function loadBundledImport(path) {
  const sample = await callWorker("loadSample", { path });
  const files = { ...activeWorkspace.files, ...sample.files };
  const openFiles = [...activeWorkspace.openFiles];
  if (!openFiles.includes(sample.source_path)) {
    openFiles.push(sample.source_path);
  }

  const nextFileHandles = new Map(fileHandles);
  for (const samplePath of Object.keys(sample.files)) {
    nextFileHandles.delete(samplePath);
  }

  activeWorkspace = createWorkspace({
    files,
    entryPath: activeWorkspace.entryPath,
    activeFilePath: sample.source_path,
    openFiles,
    samplePath: activeWorkspace.samplePath,
  });
  fileHandles = nextFileHandles;
  renderFileTabs();
  setEditorValue(currentSource());
  persistWorkspace();
  return true;
}

async function openImportPath(importPath) {
  const workspacePath = workspacePathForImport(importPath, activeWorkspace.activeFilePath);
  if (!workspacePath) {
    showError(`Cannot resolve import path: ${importPath}`);
    return;
  }

  if (ensureFileVisible(workspacePath)) {
    return;
  }

  if (importPath.startsWith("std:")) {
    await loadBundledImport(importPath);
    return;
  }

  try {
    await loadBundledImport(workspacePath);
  } catch (_error) {
    showError(`Import target is not available in the current workspace: ${workspacePath}`);
  }
}

function flashButtonLabel(button, label, duration = 1200) {
  const defaultLabel = button.dataset.defaultLabel || button.textContent;
  button.dataset.defaultLabel = defaultLabel;
  button.textContent = label;
  window.setTimeout(() => {
    button.textContent = button.dataset.defaultLabel || defaultLabel;
  }, duration);
}

function showError(message) {
  diagnosticPanel.hidden = false;
  diagnosticOutput.textContent = message;
  setResultState("error");
}

function registerDiceAceMode() {
  if (diceAceModeRegistered || !window.ace?.define) {
    return;
  }

  window.ace.define(
    "ace/mode/dice_highlight_rules",
    [
      "require",
      "exports",
      "module",
      "ace/lib/oop",
      "ace/mode/text_highlight_rules",
    ],
    (require, exports) => {
      const oop = require("ace/lib/oop");
      const TextHighlightRules = require("ace/mode/text_highlight_rules").TextHighlightRules;

      const DiceHighlightRules = function () {
        this.$rules = {
          start: [
            {
              token: ["keyword", "text", "string", "dice-import-path", "string"],
              regex: /(\bimport\b)(\s+)(")([^"]+)(")/,
            },
            {
              token: "keyword",
              regex: /\bimport\b/,
            },
          ],
        };
      };

      oop.inherits(DiceHighlightRules, TextHighlightRules);
      exports.DiceHighlightRules = DiceHighlightRules;
    },
  );

  window.ace.define(
    "ace/mode/dice",
    [
      "require",
      "exports",
      "module",
      "ace/lib/oop",
      "ace/mode/text",
      "ace/mode/dice_highlight_rules",
    ],
    (require, exports) => {
      const oop = require("ace/lib/oop");
      const TextMode = require("ace/mode/text").Mode;
      const DiceHighlightRules = require("ace/mode/dice_highlight_rules").DiceHighlightRules;

      const Mode = function () {
        this.HighlightRules = DiceHighlightRules;
        this.$behaviour = this.$defaultBehaviour;
      };

      oop.inherits(Mode, TextMode);
      Mode.prototype.$id = "ace/mode/dice";
      exports.Mode = Mode;
    },
  );

  diceAceModeRegistered = true;
}

function setResultState(state) {
  resultsPanel.dataset.state = state;
}

function buildShareUrl() {
  const url = new URL(window.location.href);
  url.searchParams.set("code", entrySource());
  if (activeWorkspace.samplePath) {
    url.searchParams.set("sample", activeWorkspace.samplePath);
  } else {
    url.searchParams.delete("sample");
  }
  return url;
}

function saveUrlState() {
  if (saveUrlTimer) {
    window.clearTimeout(saveUrlTimer);
  }
  saveUrlTimer = window.setTimeout(() => {
    window.history.replaceState({}, "", buildShareUrl());
  }, 250);
}

function populateSampleDialog() {
  const fragment = document.createDocumentFragment();
  let currentGroup = null;
  let currentOptgroup = null;

  for (const sample of samples) {
    if (sample.group !== currentGroup) {
      currentGroup = sample.group;
      currentOptgroup = document.createElement("optgroup");
      currentOptgroup.label = sample.group;
      fragment.appendChild(currentOptgroup);
    }
    const option = document.createElement("option");
    option.value = sample.path;
    option.textContent = sample.name;
    currentOptgroup.appendChild(option);
  }

  sampleDialogSelect.replaceChildren(fragment);
  if (activeWorkspace.samplePath) {
    sampleDialogSelect.value = activeWorkspace.samplePath;
  } else if (samples.length > 0) {
    sampleDialogSelect.value = samples[0].path;
  }
}

function renderFileTabs() {
  const fragment = document.createDocumentFragment();
  const canCloseTabs = activeWorkspace.openFiles.length > 1;
  for (const [index, path] of activeWorkspace.openFiles.entries()) {
    const tab = document.createElement("div");
    tab.className = path === activeWorkspace.activeFilePath ? "file-tab-shell is-active" : "file-tab-shell";

    if (path === renamingFilePath) {
      const input = document.createElement("input");
      input.type = "text";
      input.className = "file-tab-input";
      input.value = path;
      input.title = path;
      input.setAttribute("aria-label", `Rename ${basename(path)}`);
      input.addEventListener("click", (event) => {
        event.stopPropagation();
      });
      input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          finishRenamingFile(path, input.value);
          return;
        }
        if (event.key === "Escape") {
          event.preventDefault();
          cancelRenamingFile();
        }
      });
      input.addEventListener("blur", () => {
        if (renamingFilePath === path) {
          finishRenamingFile(path, input.value);
        }
      });
      tab.appendChild(input);
    } else {
      const button = document.createElement("button");
      button.type = "button";
      button.className = path === activeWorkspace.activeFilePath ? "file-tab is-active" : "file-tab";
      button.textContent = basename(path);
      button.title = path;
      button.addEventListener("click", () => {
        setActiveFile(path);
      });
      button.addEventListener("dblclick", (event) => {
        event.preventDefault();
        startRenamingFile(path);
      });
      tab.appendChild(button);
    }

    if (canCloseTabs) {
      const closeButton = document.createElement("button");
      closeButton.type = "button";
      closeButton.className = "file-tab-close";
      closeButton.textContent = "×";
      closeButton.title = `Close ${path}`;
      closeButton.setAttribute("aria-label", `Close ${basename(path)}`);
      closeButton.addEventListener("click", (event) => {
        event.stopPropagation();
        closeFile(path, index);
      });
      tab.appendChild(closeButton);
    }

    fragment.appendChild(tab);
  }

  const createButton = document.createElement("button");
  createButton.type = "button";
  createButton.className = "file-tab-create";
  createButton.textContent = "+";
  createButton.title = "Create a new tab";
  createButton.setAttribute("aria-label", "Create a new tab");
  createButton.addEventListener("click", () => {
    createNewTab();
  });
  fragment.appendChild(createButton);

  fileTabs.replaceChildren(fragment);
  if (renamingFilePath) {
    const activeInput = fileTabs.querySelector(".file-tab-input");
    activeInput?.focus();
    activeInput?.select();
  }
  refreshWorkspaceActions();
}

function setActiveFile(path) {
  if (path === activeWorkspace.activeFilePath) {
    return;
  }
  syncActiveFileFromEditor();
  activeWorkspace.activeFilePath = path;
  renderFileTabs();
  setEditorValue(currentSource());
  persistWorkspace();
}

function closeFile(path, index) {
  if (activeWorkspace.openFiles.length <= 1) {
    return;
  }

  syncActiveFileFromEditor();

  const nextOpenFiles = activeWorkspace.openFiles.filter((candidate) => candidate !== path);
  const nextActivePath =
    nextOpenFiles[Math.max(index - 1, 0)] ?? nextOpenFiles[index] ?? nextOpenFiles[0] ?? "main.dice";

  if (activeWorkspace.activeFilePath === path) {
    activeWorkspace.activeFilePath = nextActivePath;
  }
  if (activeWorkspace.entryPath === path) {
    activeWorkspace.entryPath = activeWorkspace.activeFilePath === path ? nextActivePath : activeWorkspace.activeFilePath;
  }

  delete activeWorkspace.files[path];
  fileHandles.delete(path);
  activeWorkspace.openFiles = nextOpenFiles;

  renderFileTabs();
  setEditorValue(currentSource());
  persistWorkspace();
}

function createNewTab() {
  syncActiveFileFromEditor();
  const nextPath = createUniquePath("untitled.dice");
  activeWorkspace.files[nextPath] = "";
  activeWorkspace.openFiles = [...activeWorkspace.openFiles, nextPath];
  activeWorkspace.activeFilePath = nextPath;
  activeWorkspace.samplePath = null;
  renamingFilePath = nextPath;
  renderFileTabs();
  setEditorValue("");
  persistWorkspace();
}

function renameWorkspaceFile(currentPath, nextPath, { preserveHandle = true } = {}) {
  if (currentPath === nextPath) {
    return currentPath;
  }

  const takenPaths = new Set(Object.keys(activeWorkspace.files));
  takenPaths.delete(currentPath);
  const resolvedPath = createUniquePath(nextPath, takenPaths);
  activeWorkspace.files[resolvedPath] = activeWorkspace.files[currentPath];
  delete activeWorkspace.files[currentPath];
  activeWorkspace.openFiles = activeWorkspace.openFiles.map((path) => (path === currentPath ? resolvedPath : path));
  if (activeWorkspace.entryPath === currentPath) {
    activeWorkspace.entryPath = resolvedPath;
  }
  if (activeWorkspace.activeFilePath === currentPath) {
    activeWorkspace.activeFilePath = resolvedPath;
  }

  const handle = fileHandles.get(currentPath);
  if (handle && preserveHandle) {
    fileHandles.delete(currentPath);
    fileHandles.set(resolvedPath, handle);
  } else {
    fileHandles.delete(currentPath);
    fileHandles.delete(resolvedPath);
  }

  activeWorkspace.samplePath = null;
  renderFileTabs();
  persistWorkspace();
  return resolvedPath;
}

function startRenamingFile(path) {
  syncActiveFileFromEditor();
  renamingFilePath = path;
  activeWorkspace.activeFilePath = path;
  renderFileTabs();
  setEditorValue(currentSource());
}

function cancelRenamingFile() {
  if (!renamingFilePath) {
    return;
  }
  renamingFilePath = null;
  renderFileTabs();
}

function finishRenamingFile(path, rawName) {
  if (renamingFilePath !== path) {
    return;
  }

  renamingFilePath = null;
  const nextPath = normalizeFileName(rawName, {
    preserveDirectory: true,
    basePath: path,
  });
  if (!nextPath) {
    renderFileTabs();
    return;
  }

  renameWorkspaceFile(path, nextPath, { preserveHandle: false });
}

function loadWorkspaceEntries(entries, handles = new Map()) {
  if (!entries.length) {
    return;
  }

  syncActiveFileFromEditor();

  const files = { ...activeWorkspace.files };
  const openFiles = [...activeWorkspace.openFiles];
  const mergedHandles = new Map(fileHandles);

  for (const { path, source } of entries) {
    files[path] = source;
    if (!openFiles.includes(path)) {
      openFiles.push(path);
    }
  }
  for (const [path, handle] of handles.entries()) {
    mergedHandles.set(path, handle);
  }

  const activeFilePath = entries[0].path;
  activeWorkspace = createWorkspace({
    files,
    entryPath: activeWorkspace.entryPath,
    activeFilePath,
    openFiles,
    samplePath: null,
  });
  fileHandles = mergedHandles;
  renderFileTabs();
  setEditorValue(currentSource());
  persistWorkspace();
}

async function loadFilesFromHandles(handles) {
  const nextHandles = new Map();
  const takenPaths = new Set(Object.keys(activeWorkspace.files));
  const entries = [];

  for (const handle of handles) {
    const file = await handle.getFile();
    const path = createUniquePath(file.name, takenPaths);
    takenPaths.add(path);
    entries.push({
      path,
      source: await file.text(),
    });
    nextHandles.set(path, handle);
  }

  loadWorkspaceEntries(entries, nextHandles);
}

async function loadFilesFromInputList(files) {
  const takenPaths = new Set(Object.keys(activeWorkspace.files));
  const entries = [];

  for (const file of files) {
    const path = createUniquePath(file.webkitRelativePath || file.name, takenPaths);
    takenPaths.add(path);
    entries.push({
      path,
      source: await file.text(),
    });
  }

  loadWorkspaceEntries(entries);
}

async function loadFiles() {
  try {
    if (typeof window.showOpenFilePicker === "function") {
      const handles = await window.showOpenFilePicker({
        multiple: true,
        types: [
          {
            description: "Dice files",
            accept: {
              "text/plain": [".dice", ".txt"],
            },
          },
        ],
      });
      if (!handles.length) {
        return;
      }
      await loadFilesFromHandles(handles);
      await evaluateSource();
      flashButtonLabel(loadFileButton, "Loaded");
      return;
    }

    fileInput.value = "";
    fileInput.click();
  } catch (error) {
    if (error?.name === "AbortError") {
      return;
    }
    showError(error.message);
  }
}

async function writeSourceToHandle(handle, source) {
  const writable = await handle.createWritable();
  await writable.write(source);
  await writable.close();
}

function downloadSource(path, source) {
  const blob = new Blob([source], { type: "text/plain;charset=utf-8" });
  const objectUrl = window.URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = basename(path);
  anchor.click();
  window.setTimeout(() => {
    window.URL.revokeObjectURL(objectUrl);
  }, 0);
}

function promptForFileName(defaultName = "untitled.dice") {
  const proposedName = window.prompt("File name", defaultName);
  return normalizeFileName(proposedName);
}

function sourceIndexFromPosition(source, position) {
  const lines = source.split("\n");
  let index = 0;
  for (let row = 0; row < position.row; row += 1) {
    index += (lines[row] ?? "").length + 1;
  }
  return index + position.column;
}

function positionFromSourceIndex(source, index) {
  const clampedIndex = Math.max(0, Math.min(index, source.length));
  const prefix = source.slice(0, clampedIndex);
  const lines = prefix.split("\n");
  return {
    row: Math.max(lines.length - 1, 0),
    column: lines[lines.length - 1]?.length ?? 0,
  };
}

async function fetchEditorCompletions(position) {
  const source = currentEditorValue();
  const cursor = sourceIndexFromPosition(source, position);
  const payload = await callWorker("complete", {
    source,
    cursor,
    files: activeWorkspace.files,
    settings: {
      source_path: activeWorkspace.activeFilePath,
    },
  });
  return { payload, source };
}

function installAceAutocompletion() {
  const aceLanguageTools = window.ace.require("ace/ext/language_tools");
  const AceRange = window.ace.require("ace/range").Range;

  const diceCompleter = {
    identifierRegexps: [/[A-Za-z0-9_./:-]/],
    getCompletions(editor, _session, position, _prefix, callback) {
      const requestId = ++completionRequestId;
      void fetchEditorCompletions(position)
        .then(({ payload, source }) => {
          if (requestId !== completionRequestId) {
            callback(null, []);
            return;
          }

          const completions = payload.options.map((option, index) => ({
            caption: option.label,
            value: option.label,
            meta: option.type ?? "symbol",
            score: 1000 - index,
            docHTML: option.detail ? `<code>${option.detail}</code>` : "",
            completer: diceCompleter,
            range: new AceRange(
              positionFromSourceIndex(source, payload.from).row,
              positionFromSourceIndex(source, payload.from).column,
              positionFromSourceIndex(source, payload.to).row,
              positionFromSourceIndex(source, payload.to).column,
            ),
          }));
          callback(null, completions);
        })
        .catch(() => {
          callback(null, []);
        });
    },
  };

  aceLanguageTools.setCompleters([diceCompleter]);
  aceEditor.setOptions({
    enableBasicAutocompletion: true,
    enableLiveAutocompletion: true,
  });
}

function installAceImportLinks() {
  const syncLinkCursor = (event) => {
    const position = event.getDocumentPosition?.();
    if (!position) {
      aceEditor.container.style.cursor = "";
      return;
    }
    const link = importLinkAtPosition(currentEditorValue(), position.row, position.column);
    aceEditor.container.style.cursor = link ? "pointer" : "";
  };

  aceEditor.on("mousemove", syncLinkCursor);
  aceEditor.on("mouseout", () => {
    aceEditor.container.style.cursor = "";
  });
  aceEditor.on("click", (event) => {
    const position = event.getDocumentPosition?.();
    if (!position) {
      return;
    }
    const link = importLinkAtPosition(currentEditorValue(), position.row, position.column);
    if (!link) {
      return;
    }
    event.stop?.();
    event.preventDefault?.();
    void openImportPath(link.importPath);
  });
}

async function saveCurrentFile({ forcePrompt = false } = {}) {
  syncActiveFileFromEditor();
  let currentPath = activeWorkspace.activeFilePath;
  const source = currentSource();

  try {
    const existingHandle = fileHandles.get(currentPath);
    if (existingHandle && !forcePrompt) {
      await writeSourceToHandle(existingHandle, source);
      flashButtonLabel(saveFileButton, "Saved");
      return;
    }

    if (typeof window.showSaveFilePicker === "function") {
      const handle = await window.showSaveFilePicker({
        suggestedName: basename(currentPath),
        types: [
          {
            description: "Dice files",
            accept: {
              "text/plain": [".dice", ".txt"],
            },
          },
        ],
      });
      await writeSourceToHandle(handle, source);
      const resolvedPath = renameWorkspaceFile(currentPath, handle.name, { preserveHandle: true });
      fileHandles.set(resolvedPath, handle);
      flashButtonLabel(forcePrompt ? saveAsFileButton : saveFileButton, "Saved");
      return;
    }

    if (forcePrompt || isUnnamedPath(currentPath)) {
      const promptedPath = promptForFileName(basename(currentPath));
      if (!promptedPath) {
        return;
      }
      currentPath = renameWorkspaceFile(currentPath, promptedPath, { preserveHandle: false });
    }

    downloadSource(currentPath, source);
    flashButtonLabel(forcePrompt ? saveAsFileButton : saveFileButton, "Downloaded");
  } catch (error) {
    if (error?.name === "AbortError") {
      return;
    }
    showError(error.message);
  }
}

function initializeEditor() {
  if (window.ace) {
    registerDiceAceMode();
    editorSurface.textContent = "";
    aceEditor = window.ace.edit(editorSurface);
    aceEditor.setTheme("ace/theme/tomorrow_night_bright");
    aceEditor.session.setMode("ace/mode/dice");
    aceEditor.session.setTabSize(2);
    aceEditor.session.setUseSoftTabs(true);
    aceEditor.setOptions({
      fontSize: "14px",
      showPrintMargin: false,
      wrap: true,
      highlightActiveLine: true,
    });
    installAceAutocompletion();
    installAceImportLinks();
    aceEditor.commands.addCommand({
      name: "runDice",
      bindKey: { win: "Ctrl-Enter", mac: "Command-Enter" },
      exec: () => {
        void evaluateSource();
      },
    });
    aceEditor.commands.addCommand({
      name: "showCompletions",
      bindKey: { win: "Ctrl-Space", mac: "Ctrl-Space|Alt-Space" },
      exec: (editor) => {
        editor.execCommand("startAutocomplete");
      },
    });
    aceEditor.session.on("change", () => {
      syncActiveFileFromEditor();
    });
    setEditorValue(currentSource());
    installEditorResizeHandling();
    syncEditorLayout();
    return;
  }

  fallbackTextarea = document.createElement("textarea");
  fallbackTextarea.className = "editor-textarea";
  fallbackTextarea.setAttribute("spellcheck", "false");
  fallbackTextarea.setAttribute("aria-label", "dice editor");
  fallbackTextarea.addEventListener("input", () => {
    syncActiveFileFromEditor();
  });
  fallbackTextarea.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      void evaluateSource();
      return;
    }
    if (event.key !== "Tab") {
      return;
    }
    event.preventDefault();
    const start = fallbackTextarea.selectionStart;
    const end = fallbackTextarea.selectionEnd;
    const value = currentEditorValue();
    const nextValue = value.slice(0, start) + "  " + value.slice(end);
    setEditorValue(nextValue);
    fallbackTextarea.selectionStart = start + 2;
    fallbackTextarea.selectionEnd = start + 2;
    syncActiveFileFromEditor();
  });
  editorSurface.replaceChildren(fallbackTextarea);
  setEditorValue(currentSource());
}

function interpolateColor(value, maxValue) {
  const ratio = maxValue <= 0 ? 0 : value / maxValue;
  const low = { r: 239, g: 227, b: 193 };
  const high = { r: 182, g: 92, b: 58 };
  const mix = (start, end) => Math.round(start + (end - start) * ratio);
  return `rgb(${mix(low.r, high.r)}, ${mix(low.g, high.g)}, ${mix(low.b, high.b)})`;
}

function renderSvgChart(contentBuilder) {
  const wrapper = document.createElement("div");
  wrapper.className = "chart-stack";
  const tooltip = document.createElement("div");
  tooltip.className = "chart-tooltip";
  tooltip.hidden = true;
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 760 380");
  svg.setAttribute("class", "chart-svg");
  wrapper.appendChild(svg);
  wrapper.appendChild(tooltip);
  contentBuilder(svg, createTooltipController(wrapper, tooltip));
  return wrapper;
}

function appendSvgLine(svg, x1, y1, x2, y2, className, attributes = {}) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", "line");
  node.setAttribute("x1", x1);
  node.setAttribute("y1", y1);
  node.setAttribute("x2", x2);
  node.setAttribute("y2", y2);
  node.setAttribute("class", className);
  for (const [key, value] of Object.entries(attributes)) {
    node.setAttribute(key, value);
  }
  svg.appendChild(node);
  return node;
}

function appendSvgText(svg, x, y, text, className, attributes = {}) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", "text");
  node.setAttribute("x", x);
  node.setAttribute("y", y);
  node.setAttribute("class", className);
  for (const [key, value] of Object.entries(attributes)) {
    node.setAttribute(key, value);
  }
  node.textContent = text;
  svg.appendChild(node);
  return node;
}

function formatTickValue(value) {
  if (!Number.isFinite(value)) {
    return String(value);
  }
  if (value === 0) {
    return "0";
  }
  const absolute = Math.abs(value);
  if (absolute >= 100) {
    return String(Math.round(value));
  }
  if (absolute >= 10) {
    return value.toFixed(1).replace(/\.0$/, "");
  }
  if (absolute >= 1) {
    return value.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
  }
  return value.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
}

function formatHoverValue(value, label) {
  const formatted = formatTickValue(value);
  return label && label.includes("%") ? `${formatted}%` : formatted;
}

function numericCategoryValue(category) {
  if (typeof category === "number") {
    return Number.isFinite(category) ? category : null;
  }
  const numeric = Number(category);
  return Number.isFinite(numeric) ? numeric : null;
}

function isZeroCategory(category) {
  return numericCategoryValue(category) === 0;
}

function isPositiveNumericCategory(category) {
  const numeric = numericCategoryValue(category);
  return numeric !== null && numeric > 0;
}

function hasNumericCategories(chart) {
  return Array.isArray(chart.categories) && chart.categories.length > 0 && chart.categories.every((category) => numericCategoryValue(category) !== null);
}

function canAdjustDistributionView(chart) {
  return canToggleChart(chart) && hasNumericCategories(chart) && isProbabilityLabel(chart.spec?.y_label);
}

function significantTailThreshold(chart) {
  const maxValue = Math.max(...chart.series.flatMap((series) => series.values), 0);
  if (maxValue <= 0) {
    return 0;
  }
  return Math.max(0.05, maxValue * 0.01);
}

function lastSignificantIndex(chart, threshold) {
  let lastPositive = -1;
  let lastSignificant = -1;
  chart.series.forEach((series) => {
    series.values.forEach((value, index) => {
      if (value > 0) {
        lastPositive = Math.max(lastPositive, index);
      }
      if (value >= threshold) {
        lastSignificant = Math.max(lastSignificant, index);
      }
    });
  });
  return lastSignificant >= 0 ? lastSignificant : lastPositive;
}

function sliceCartesianChart(chart, endIndexInclusive) {
  return {
    ...chart,
    categories: chart.categories.slice(0, endIndexInclusive + 1),
    series: chart.series.map((seriesEntry) => ({
      ...seriesEntry,
      values: seriesEntry.values.slice(0, endIndexInclusive + 1),
    })),
  };
}

function prepareDistributionChart(chart, displayMode = "full") {
  if (!canAdjustDistributionView(chart)) {
    return { chart, notes: [] };
  }

  let displayChart = chart;
  const notes = [];

  if (displayMode === "omit-zero" || displayMode === "tight") {
    const zeroIndex = displayChart.categories.findIndex((category) => isZeroCategory(category));
    const hasPositiveCategory = displayChart.categories.some((category) => isPositiveNumericCategory(category));

    if (zeroIndex >= 0 && hasPositiveCategory) {
      const zeroValues = displayChart.series.map((series) => series.values[zeroIndex] ?? 0);
      const hasVisibleZeroMass = zeroValues.some((value) => value > 0);
      if (hasVisibleZeroMass) {
        const categories = displayChart.categories.filter((_category, index) => index !== zeroIndex);
        if (categories.length > 0) {
          const series = displayChart.series.map((seriesEntry) => ({
            ...seriesEntry,
            values: seriesEntry.values.filter((_value, index) => index !== zeroIndex),
          }));
          notes.push(
            displayChart.series.length === 1
              ? `Zero outcome hidden: ${formatHoverValue(zeroValues[0], displayChart.spec.y_label)}`
              : `Zero outcome hidden: ${displayChart.series
                  .map((seriesEntry, index) => `${seriesEntry.name} ${formatHoverValue(zeroValues[index], displayChart.spec.y_label)}`)
                  .join(", ")}`,
          );
          displayChart = {
            ...displayChart,
            categories,
            series,
          };
        }
      }
    }
  }

  if (displayMode === "tight" && displayChart.categories.length > 1) {
    const threshold = significantTailThreshold(displayChart);
    const lastVisibleIndex = lastSignificantIndex(displayChart, threshold);
    if (lastVisibleIndex >= 0 && lastVisibleIndex < displayChart.categories.length - 1) {
      const lastVisibleCategory = displayChart.categories[lastVisibleIndex];
      displayChart = sliceCartesianChart(displayChart, lastVisibleIndex);
      notes.push(
        `Tail hidden after ${lastVisibleCategory}; remaining values are below ${formatHoverValue(
          threshold,
          displayChart.spec.y_label,
        )}`,
      );
    }
  }

  return { chart: displayChart, notes };
}

function defaultDistributionView(chart) {
  if (!canAdjustDistributionView(chart)) {
    return "full";
  }
  const omitZero = prepareDistributionChart(chart, "omit-zero");
  const tight = prepareDistributionChart(chart, "tight");
  if (tight.chart.categories.length + 2 < omitZero.chart.categories.length) {
    return "tight";
  }
  if (omitZero.notes.length > 0) {
    return "omit-zero";
  }
  return "full";
}

function createTooltipController(wrapper, tooltip) {
  function positionTooltip(event) {
    const bounds = wrapper.getBoundingClientRect();
    const offset = 12;
    const tooltipWidth = tooltip.offsetWidth;
    const tooltipHeight = tooltip.offsetHeight;
    const pointerX = event.clientX - bounds.left;
    const pointerY = event.clientY - bounds.top;

    let left = pointerX + offset;
    let top = pointerY + offset;

    if (left + tooltipWidth > bounds.width - offset) {
      left = pointerX - tooltipWidth - offset;
    }
    if (left < offset) {
      left = offset;
    }

    if (top + tooltipHeight > bounds.height - offset) {
      top = pointerY - tooltipHeight - offset;
    }
    if (top < offset) {
      top = offset;
    }

    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${top}px`;
  }

  return {
    attach(target, lines) {
      const text = Array.isArray(lines) ? lines.join("\n") : String(lines);
      target.addEventListener("pointerenter", (event) => {
        tooltip.textContent = text;
        tooltip.hidden = false;
        positionTooltip(event);
      });
      target.addEventListener("pointermove", (event) => {
        if (tooltip.hidden) {
          return;
        }
        positionTooltip(event);
      });
      target.addEventListener("pointerleave", () => {
        tooltip.hidden = true;
      });
    },
  };
}

const CHART_PALETTE = ["#b65c3a", "#3b6c8e", "#6f8a42", "#8a4f7d"];

function niceStep(rawStep) {
  if (!Number.isFinite(rawStep) || rawStep <= 0) {
    return 1;
  }
  const exponent = 10 ** Math.floor(Math.log10(rawStep));
  const fraction = rawStep / exponent;
  if (fraction <= 1) {
    return exponent;
  }
  if (fraction <= 2) {
    return 2 * exponent;
  }
  if (fraction <= 5) {
    return 5 * exponent;
  }
  return 10 * exponent;
}

function buildLinearScale(minValue, maxValue, options = {}) {
  const { includeZero = false, targetTicks = 5 } = options;
  let min = minValue;
  let max = maxValue;

  if (includeZero) {
    min = Math.min(min, 0);
    max = Math.max(max, 0);
  }

  if (min === max) {
    const padding = min === 0 ? 1 : Math.abs(min) * 0.1;
    min -= padding;
    max += padding;
  }

  const rawStep = (max - min) / Math.max(targetTicks - 1, 1);
  const step = niceStep(rawStep);
  const niceMin = includeZero && min >= 0 ? 0 : Math.floor(min / step) * step;
  const niceMax = Math.ceil(max / step) * step;
  const ticks = [];

  for (let value = niceMin; value <= niceMax + step / 2; value += step) {
    ticks.push(Number(value.toFixed(10)));
  }

  return {
    min: niceMin,
    max: niceMax,
    ticks,
  };
}

function valueToY(value, scale, top, height) {
  const ratio = scale.max === scale.min ? 0 : (value - scale.min) / (scale.max - scale.min);
  return top + height - ratio * height;
}

function categoryTickStep(categories, width) {
  const longest = Math.max(...categories.map((category) => String(category).length), 1);
  const estimatedWidth = longest * 7;
  const availableWidth = width / Math.max(categories.length, 1);
  return Math.max(1, Math.ceil(estimatedWidth / Math.max(availableWidth, 1)));
}

function shouldRotateCategoryLabels(categories, width, step) {
  if (categories.length <= 1) {
    return false;
  }
  const longest = Math.max(...categories.map((category) => String(category).length), 1);
  const availableWidth = width / Math.max(Math.ceil(categories.length / step), 1);
  return longest * 7 > availableWidth;
}

function isProbabilityLabel(label) {
  return String(label || "").toLowerCase().includes("probability");
}

function chartValueRange(values) {
  const finiteValues = values.filter((value) => Number.isFinite(value));
  if (finiteValues.length === 0) {
    return { min: 0, max: 1 };
  }
  return {
    min: Math.min(...finiteValues),
    max: Math.max(...finiteValues),
  };
}

function paddedRange(minValue, maxValue, multiplier = 0.08) {
  if (!Number.isFinite(minValue) || !Number.isFinite(maxValue)) {
    return { min: 0, max: 1 };
  }
  if (minValue === maxValue) {
    const padding = minValue === 0 ? 1 : Math.abs(minValue) * 0.1;
    return { min: minValue - padding, max: maxValue + padding };
  }
  const span = maxValue - minValue;
  const padding = span * multiplier;
  return {
    min: minValue - padding,
    max: maxValue + padding,
  };
}

function buildChartScale(values, options = {}) {
  const { includeZeroByDefault = false, probabilitySeries = false } = options;
  const range = chartValueRange(values);

  if (probabilitySeries) {
    const paddedMax = range.max === 0 ? 1 : range.max * 1.08;
    return buildLinearScale(0, paddedMax, { includeZero: true });
  }

  if (includeZeroByDefault) {
    const paddedMax = range.max === 0 ? 1 : range.max + Math.max((range.max - Math.min(range.min, 0)) * 0.08, 0.25);
    return buildLinearScale(Math.min(range.min, 0), paddedMax, { includeZero: true });
  }

  const padded = paddedRange(range.min, range.max, 0.06);
  return buildLinearScale(padded.min, padded.max, { includeZero: false });
}

function drawChartAxes(svg, options) {
  const { left, top, width, height, bottom, scale, categories, xLabel, yLabel } = options;
  const right = left + width;
  const yAxisCenter = top + height / 2;
  const tickStep = categoryTickStep(categories, width);
  const rotateXLabels = shouldRotateCategoryLabels(categories, width, tickStep);
  const xTickY = bottom + (rotateXLabels ? 32 : 20);
  const xLabelY = rotateXLabels ? 362 : 344;

  scale.ticks.forEach((tick) => {
    const y = valueToY(tick, scale, top, height);
    appendSvgLine(svg, left, y, right, y, tick === 0 ? "chart-axis-line" : "chart-tick-line");
    appendSvgText(svg, left - 10, y + 4, formatTickValue(tick), "chart-tick", {
      "text-anchor": "end",
    });
  });

  appendSvgLine(svg, left, top, left, bottom, "chart-axis-line");
  appendSvgLine(svg, left, bottom, right, bottom, "chart-axis-line");

  const xStep = categories.length > 1 ? width / (categories.length - 1) : 0;
  const barStep = categories.length > 0 ? width / categories.length : width;
  const anchorMode = categories.length > 1 ? "line" : "bar";

  categories.forEach((category, index) => {
    if (index % tickStep !== 0 && index !== categories.length - 1) {
      return;
    }
    const x = anchorMode === "line" ? left + index * xStep : left + index * barStep + barStep / 2;
    const attributes = rotateXLabels
      ? {
          "text-anchor": "end",
          transform: `rotate(-35 ${x} ${xTickY})`,
        }
      : { "text-anchor": "middle" };
    appendSvgText(svg, x, xTickY, String(category), "chart-tick", attributes);
  });

  appendSvgText(svg, left + width / 2, xLabelY, xLabel, "chart-axis-label", {
    "text-anchor": "middle",
  });
  appendSvgText(svg, 20, yAxisCenter, yLabel, "chart-axis-label", {
    "text-anchor": "middle",
    transform: `rotate(-90 20 ${yAxisCenter})`,
  });

  return { rotateXLabels };
}

function renderBarChart(chart, options = {}) {
  const prepared = prepareDistributionChart(chart, options.displayMode);
  return {
    notes: prepared.notes,
    node: renderSvgChart((svg, tooltip) => {
      const displayChart = prepared.chart;
      const left = 76;
      const width = 620;
      const height = 222;
      const values = displayChart.series.flatMap((series) => series.values);
      const scale = buildChartScale(values, {
        includeZeroByDefault: true,
        probabilitySeries: isProbabilityLabel(displayChart.spec.y_label),
      });
      const top = 38;
      const bottom = top + height;
      const barWidth = width / displayChart.categories.length;
      const seriesCount = displayChart.series.length;
      const innerBarWidth = Math.max((barWidth - 18) / seriesCount, 6);
      drawChartAxes(svg, {
        left,
        top,
        width,
        height,
        bottom,
        scale,
        categories: displayChart.categories,
        xLabel: displayChart.spec.x_label,
        yLabel: displayChart.spec.y_label,
      });

      displayChart.series.forEach((series, seriesIndex) => {
        series.values.forEach((value, index) => {
          const y = valueToY(value, scale, top, height);
          const barHeight = bottom - y;
          const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
          rect.setAttribute("x", left + index * barWidth + 8 + innerBarWidth * seriesIndex);
          rect.setAttribute("y", y);
          rect.setAttribute("width", innerBarWidth - 2);
          rect.setAttribute("height", barHeight);
          rect.setAttribute("rx", "6");
          rect.setAttribute("fill", CHART_PALETTE[seriesIndex % CHART_PALETTE.length]);
          const category = displayChart.categories[index];
          tooltip.attach(rect, [
            series.name,
            `${displayChart.spec.x_label}: ${category}`,
            `${displayChart.spec.y_label}: ${formatHoverValue(value, displayChart.spec.y_label)}`,
          ]);
          svg.appendChild(rect);
        });
      });
    }),
  };
}

function renderLineChart(chart, options = {}) {
  const prepared = prepareDistributionChart(chart, options.displayMode);
  return {
    notes: prepared.notes,
    node: renderSvgChart((svg, tooltip) => {
      const displayChart = prepared.chart;
      const left = 76;
      const width = 620;
      const height = 222;
      const values = displayChart.series.flatMap((series) => series.values);
      const probabilitySeries = isProbabilityLabel(displayChart.spec.y_label);
      const scale = buildChartScale(values, {
        includeZeroByDefault: false,
        probabilitySeries,
      });
      const top = 38;
      const bottom = top + height;
      const xStep = displayChart.categories.length > 1 ? width / (displayChart.categories.length - 1) : width;
      drawChartAxes(svg, {
        left,
        top,
        width,
        height,
        bottom,
        scale,
        categories: displayChart.categories,
        xLabel: displayChart.spec.x_label,
        yLabel: displayChart.spec.y_label,
      });

      displayChart.series.forEach((series, seriesIndex) => {
        const points = series.values.map((value, index) => {
          const x = left + index * xStep;
          const y = valueToY(value, scale, top, height);
          const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
          circle.setAttribute("cx", x);
          circle.setAttribute("cy", y);
          circle.setAttribute("r", "4");
          circle.setAttribute("fill", CHART_PALETTE[seriesIndex % CHART_PALETTE.length]);
          tooltip.attach(circle, [
            series.name,
            `${displayChart.spec.x_label}: ${displayChart.categories[index]}`,
            `${displayChart.spec.y_label}: ${formatHoverValue(value, displayChart.spec.y_label)}`,
          ]);
          svg.appendChild(circle);
          return `${x},${y}`;
        });

        const polyline = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
        polyline.setAttribute("points", points.join(" "));
        polyline.setAttribute("fill", "none");
        polyline.setAttribute("stroke", CHART_PALETTE[seriesIndex % CHART_PALETTE.length]);
        polyline.setAttribute("stroke-width", "3");
        svg.appendChild(polyline);
      });
    }),
  };
}

function renderHeatmap(chart) {
  const wrapper = document.createElement("div");
  wrapper.className = "heatmap";
  const tooltip = document.createElement("div");
  tooltip.className = "chart-tooltip";
  tooltip.hidden = true;
  const tooltipController = createTooltipController(wrapper, tooltip);

  const caption = document.createElement("div");
  caption.className = "chart-caption";
  caption.innerHTML = `<span>${chart.spec.x_label} × ${chart.spec.y_label}</span><span>${chart.color_label}</span>`;
  wrapper.appendChild(caption);

  const grid = document.createElement("div");
  grid.className = "heatmap-grid";
  grid.style.gridTemplateColumns = `repeat(${chart.x_values.length + 1}, minmax(3rem, auto))`;

  const corner = document.createElement("div");
  corner.className = "heatmap-header";
  grid.appendChild(corner);

  chart.x_values.forEach((value) => {
    const header = document.createElement("div");
    header.className = "heatmap-header";
    header.textContent = String(value);
    grid.appendChild(header);
  });

  const maxValue = Math.max(...chart.matrix.flat(), 1);
  chart.y_values.forEach((value, rowIndex) => {
    const rowHeader = document.createElement("div");
    rowHeader.className = "heatmap-header";
    rowHeader.textContent = String(value);
    grid.appendChild(rowHeader);

    chart.matrix[rowIndex].forEach((cellValue, columnIndex) => {
      const cell = document.createElement("div");
      cell.className = "heatmap-cell";
      cell.style.background = interpolateColor(cellValue, maxValue);
      cell.textContent = Number.isFinite(cellValue) ? cellValue.toFixed(2) : String(cellValue);
      tooltipController.attach(cell, [
        `${chart.spec.x_label}: ${chart.x_values[columnIndex]}`,
        `${chart.spec.y_label}: ${value}`,
        `${chart.color_label}: ${formatHoverValue(cellValue, chart.color_label)}`,
      ]);
      grid.appendChild(cell);
    });
  });

  wrapper.appendChild(grid);
  wrapper.appendChild(tooltip);
  return wrapper;
}

function chartToggleView(kind) {
  if (kind === "bar" || kind === "compare_bar") {
    return "bar";
  }
  if (kind === "line" || kind === "compare_line") {
    return "line";
  }
  return null;
}

function canToggleChart(chart) {
  return chartToggleView(chart.kind) !== null;
}

function chartWithView(chart, view) {
  const isComparison = chart.kind === "compare_bar" || chart.kind === "compare_line";
  if (view === "bar") {
    return {
      ...chart,
      kind: isComparison ? "compare_bar" : "bar",
      spec: {
        ...chart.spec,
        kind: isComparison ? "compare_bar" : "bar",
      },
    };
  }
  return {
    ...chart,
    kind: isComparison ? "compare_line" : "line",
    spec: {
      ...chart.spec,
      kind: isComparison ? "compare_line" : "line",
    },
  };
}

function buildLegend(chart) {
  if (!chart.series || chart.series.length === 0) {
    return null;
  }
  const legend = document.createElement("div");
  legend.className = "chart-legend";
  chart.series.forEach((series, index) => {
    const item = document.createElement("div");
    item.className = "chart-legend-item";
    const dot = document.createElement("span");
    dot.className = "chart-legend-dot";
    dot.style.background = CHART_PALETTE[index % CHART_PALETTE.length];
    const label = document.createElement("span");
    label.textContent = series.name;
    item.append(dot, label);
    legend.appendChild(item);
  });
  return legend;
}

function renderCartesianChart(chart, plotHost, options = {}) {
  const view = options.view ?? chartToggleView(chart.kind);
  const displayChart = view ? chartWithView(chart, view) : chart;
  const rendered =
    view === "line"
      ? renderLineChart(displayChart, {
          displayMode: options.displayMode,
        })
      : renderBarChart(displayChart, {
          displayMode: options.displayMode,
        });
  plotHost.replaceChildren(rendered.node);
  return rendered;
}

function renderSingleChart(chart, container) {
  container.replaceChildren();
  if (!chart) {
    return false;
  }
  let modeLabel = null;
  if (chart.title) {
    const heading = document.createElement("div");
    heading.className = "chart-caption";
    const titleLabel = document.createElement("span");
    titleLabel.textContent = chart.title;
    modeLabel = document.createElement("span");
    modeLabel.textContent = chart.spec?.kind ?? chart.kind;
    heading.append(titleLabel, modeLabel);
    container.appendChild(heading);
  }
  if (canToggleChart(chart)) {
    const controls = document.createElement("div");
    controls.className = "chart-controls";
    const plotHost = document.createElement("div");
    plotHost.className = "chart-plot-host";
    const notesHost = document.createElement("div");
    notesHost.className = "chart-notes";
    const legend = buildLegend(chart);
    let activeView = chartToggleView(chart.kind);
    const supportsDistributionView = canAdjustDistributionView(chart);
    let activeDisplayMode = defaultDistributionView(chart);

    const renderActiveChart = () => {
      const activeChart = chartWithView(chart, activeView);
      const rendered = renderCartesianChart(activeChart, plotHost, {
        view: activeView,
        displayMode: activeDisplayMode,
      });
      notesHost.replaceChildren(
        ...rendered.notes.map((noteText) => {
          const note = document.createElement("div");
          note.className = "chart-note";
          note.textContent = noteText;
          return note;
        }),
      );
      if (modeLabel) {
        modeLabel.textContent = supportsDistributionView ? `${activeChart.kind} · ${activeDisplayMode}` : activeChart.kind;
      }
    };

    const syncButtons = (buttons) => {
      buttons.forEach((button) => {
        const buttonValue = button.dataset.view ?? button.dataset.displayMode;
        const activeValue = button.dataset.view ? activeView : button.dataset.displayMode ? activeDisplayMode : null;
        const isActive = buttonValue === activeValue;
        button.classList.toggle("is-active", isActive);
        button.setAttribute("aria-pressed", String(isActive));
      });
    };

    const controlButtons = [];
    const viewControls = document.createElement("div");
    viewControls.className = "chart-control-group";
    const viewLabel = document.createElement("span");
    viewLabel.className = "chart-control-label";
    viewLabel.textContent = "Plot";
    viewControls.appendChild(viewLabel);
    ["bar", "line"].forEach((view) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "chart-toggle";
      button.dataset.view = view;
      button.textContent = view === "bar" ? "Bar" : "Line";
      button.addEventListener("click", () => {
        if (activeView === view) {
          return;
        }
        activeView = view;
        renderActiveChart();
        syncButtons(controlButtons);
      });
      controlButtons.push(button);
      viewControls.appendChild(button);
    });
    controls.appendChild(viewControls);

    if (supportsDistributionView) {
      const displayControls = document.createElement("div");
      displayControls.className = "chart-control-group";
      const displayLabel = document.createElement("span");
      displayLabel.className = "chart-control-label";
      displayLabel.textContent = "Show";
      displayControls.appendChild(displayLabel);
      [
        ["full", "Full"],
        ["omit-zero", "Omit-Zero"],
        ["tight", "Tight"],
      ].forEach(([displayMode, label]) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "chart-toggle";
        button.dataset.displayMode = displayMode;
        button.textContent = label;
        button.addEventListener("click", () => {
          if (activeDisplayMode === displayMode) {
            return;
          }
          activeDisplayMode = displayMode;
          renderActiveChart();
          syncButtons(controlButtons);
        });
        controlButtons.push(button);
        displayControls.appendChild(button);
      });
      controls.appendChild(displayControls);
    }

    syncButtons(controlButtons);
    renderActiveChart();
    container.appendChild(controls);
    container.appendChild(plotHost);
    if (legend) {
      container.appendChild(legend);
    }
    container.appendChild(notesHost);
    return true;
  }
  if (chart.kind === "bar" || chart.kind === "compare_bar") {
    const rendered = renderBarChart(chart, { displayMode: defaultDistributionView(chart) });
    container.appendChild(rendered.node);
    const legend = buildLegend(chart);
    if (legend) {
      container.appendChild(legend);
    }
    rendered.notes.forEach((noteText) => {
      const note = document.createElement("div");
      note.className = "chart-note";
      note.textContent = noteText;
      container.appendChild(note);
    });
    return true;
  }
  if (chart.kind === "line" || chart.kind === "compare_line") {
    const rendered = renderLineChart(chart, { displayMode: defaultDistributionView(chart) });
    container.appendChild(rendered.node);
    const legend = buildLegend(chart);
    if (legend) {
      container.appendChild(legend);
    }
    rendered.notes.forEach((noteText) => {
      const note = document.createElement("div");
      note.className = "chart-note";
      note.textContent = noteText;
      container.appendChild(note);
    });
    return true;
  }
  if (chart.kind === "heatmap_distribution" || chart.kind === "heatmap_scalar") {
    container.appendChild(renderHeatmap(chart));
    return true;
  }
  const unsupported = document.createElement("div");
  unsupported.className = "chart-caption";
  unsupported.innerHTML = `<span>Unsupported chart payload</span><span>${chart.kind ?? "unknown"}</span>`;
  container.appendChild(unsupported);
  return false;
}

function renderCharts(charts) {
  chartOutput.replaceChildren();
  const items = Array.isArray(charts) ? charts : charts ? [charts] : [];
  if (items.length === 0) {
    chartEmpty.hidden = true;
    return;
  }
  chartEmpty.hidden = true;
  let renderedAny = false;
  items.forEach((chart) => {
    const container = document.createElement("div");
    container.className = "chart-stack";
    chartOutput.appendChild(container);
    renderedAny = renderSingleChart(chart, container) || renderedAny;
  });
  chartEmpty.hidden = renderedAny || items.length > 0;
}

function setActiveResultTab(nextTab) {
  activeResultTab = nextTab;

  resultTabs.forEach((button) => {
    const isActive = button.dataset.resultTab === activeResultTab;
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-selected", String(isActive));
  });

  Object.entries(resultPanels).forEach(([name, panel]) => {
    panel.hidden = name !== activeResultTab;
  });
}

function setOutputs(payload) {
  if (!payload.ok) {
    diagnosticPanel.hidden = false;
    diagnosticOutput.textContent = payload.error.formatted;
    textOutput.textContent = "";
    jsonOutput.textContent = "";
    chartOutput.replaceChildren();
    chartEmpty.hidden = true;
    setResultState("error");
    return;
  }

  diagnosticPanel.hidden = true;
  diagnosticOutput.textContent = "";
  textOutput.textContent = payload.text ?? "";
  jsonOutput.textContent = JSON.stringify(payload.result, null, 2);
  setResultState(payload.result.type);
  const charts = payload.renders && payload.renders.length ? payload.renders : payload.render;
  renderCharts(charts);
  if (charts) {
    chartEmpty.hidden = true;
  }
}

async function evaluateSource() {
  syncActiveFileFromEditor();
  setResultState("running");
  try {
    const payload = await callWorker("evaluate", {
      source: activeWorkspace.files[activeWorkspace.activeFilePath],
      files: activeWorkspace.files,
      settings: {
        source_path: activeWorkspace.activeFilePath,
      },
    });
    setOutputs(payload);
  } catch (error) {
    diagnosticPanel.hidden = false;
    diagnosticOutput.textContent = error.message;
    chartOutput.replaceChildren();
    chartEmpty.hidden = true;
    setResultState("error");
  }
}

async function loadSamplePath(path) {
  const sample = await callWorker("loadSample", { path });
  syncActiveFileFromEditor();

  const files = { ...activeWorkspace.files, ...sample.files };
  const openFiles = [...activeWorkspace.openFiles];
  if (!openFiles.includes(sample.source_path)) {
    openFiles.push(sample.source_path);
  }

  const nextFileHandles = new Map(fileHandles);
  for (const samplePath of Object.keys(sample.files)) {
    nextFileHandles.delete(samplePath);
  }

  activeWorkspace = createWorkspace({
    files,
    entryPath: sample.source_path,
    activeFilePath: sample.source_path,
    openFiles,
    samplePath: path,
  });
  fileHandles = nextFileHandles;
  renderFileTabs();
  setEditorValue(currentSource());
  persistWorkspace();
}

function openSampleDialog() {
  if (samples.length === 0) {
    return;
  }
  populateSampleDialog();
  if (typeof sampleDialog.showModal === "function") {
    sampleDialog.showModal();
  } else {
    sampleDialog.setAttribute("open", "");
  }
}

async function copyShareUrl() {
  syncActiveFileFromEditor();
  const url = buildShareUrl();
  window.history.replaceState({}, "", url);
  await navigator.clipboard.writeText(url.toString());
  shareButton.textContent = "Copied";
  window.setTimeout(() => {
    shareButton.textContent = "Copy Share URL";
  }, 1200);
}

initializeEditor();
renderFileTabs();

runButton.addEventListener("click", () => {
  void evaluateSource();
});

shareButton.addEventListener("click", () => {
  void copyShareUrl();
});

loadFileButton.addEventListener("click", () => {
  void loadFiles();
});

saveFileButton.addEventListener("click", () => {
  void saveCurrentFile();
});

saveAsFileButton.addEventListener("click", () => {
  void saveCurrentFile({ forcePrompt: true });
});

loadSampleButton.addEventListener("click", () => {
  openSampleDialog();
});

closeAllButton.addEventListener("click", () => {
  resetWorkspace();
});

sampleDialog.addEventListener("close", async () => {
  if (sampleDialog.returnValue === "cancel") {
    return;
  }
  const selectedPath = sampleDialogSelect.value;
  if (!selectedPath) {
    return;
  }
  try {
    await loadSamplePath(selectedPath);
    await evaluateSource();
  } catch (error) {
    diagnosticPanel.hidden = false;
    diagnosticOutput.textContent = error.message;
    setResultState("error");
  }
});

sampleDialogConfirm.addEventListener("click", () => {
  sampleDialog.returnValue = "default";
});

resultTabs.forEach((button) => {
  button.addEventListener("click", () => {
    setActiveResultTab(button.dataset.resultTab);
  });
});

fileInput.addEventListener("change", async (event) => {
  const files = Array.from(event.target.files ?? []);
  if (!files.length) {
    return;
  }

  try {
    await loadFilesFromInputList(files);
    await evaluateSource();
    flashButtonLabel(loadFileButton, "Loaded");
  } catch (error) {
    showError(error.message);
  } finally {
    fileInput.value = "";
  }
});

window.addEventListener("beforeunload", (event) => {
  if (!shouldWarnBeforeUnload()) {
    return;
  }
  event.preventDefault();
  event.returnValue = "";
});

setActiveResultTab("charts");
textOutput.textContent = "";
jsonOutput.textContent = "";
chartOutput.replaceChildren();
chartEmpty.hidden = false;

async function boot() {
  try {
    await callWorker("init");
    samples = await callWorker("listSamples");
    const hasSavedWorkspace = await restoreWorkspaceFromIndexedDb();
    const url = new URL(window.location.href);
    const sampleFromUrl = url.searchParams.get("sample");
    const sharedSource = url.searchParams.get("code");

    if (!hasSavedWorkspace && sampleFromUrl) {
      await loadSamplePath(sampleFromUrl);
      if (sharedSource) {
        activeWorkspace.files[activeWorkspace.entryPath] = sharedSource;
        if (activeWorkspace.activeFilePath === activeWorkspace.entryPath) {
          setEditorValue(sharedSource);
        }
        persistWorkspace();
      }
    } else if (!hasSavedWorkspace && sharedSource !== null) {
      activeWorkspace = createWorkspace({
        files: { "main.dice": sharedSource },
        entryPath: "main.dice",
      });
      fileHandles = new Map();
      renamingFilePath = null;
      renderFileTabs();
      setEditorValue(currentSource());
      persistWorkspace();
    }
    await evaluateSource();
  } catch (error) {
    diagnosticPanel.hidden = false;
    diagnosticOutput.textContent = error.message;
    setResultState("error");
  }
}

void boot();
