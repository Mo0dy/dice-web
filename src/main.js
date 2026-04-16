const DEFAULT_SOURCE = `import "std:dnd/core"

attack_bonus = 7
target_ac = [ac:10, 12, 14, 16, 18, 20]

d20 + attack_bonus >= target_ac`;

const STORAGE_KEY = "dice-web:last-source";
const SNIPPETS_KEY = "dice-web:snippets";
const EMPTY_SNIPPET = "__empty__";

const runButton = document.querySelector("#run-button");
const shareButton = document.querySelector("#share-button");
const loadSampleButton = document.querySelector("#load-sample-button");
const closeAllButton = document.querySelector("#close-all-button");
const snippetSelect = document.querySelector("#snippet-select");
const saveSnippetButton = document.querySelector("#save-snippet-button");
const deleteSnippetButton = document.querySelector("#delete-snippet-button");
const textOutput = document.querySelector("#text-output");
const jsonOutput = document.querySelector("#json-output");
const diagnosticPanel = document.querySelector("#diagnostic-panel");
const diagnosticOutput = document.querySelector("#diagnostic-output");
const chartOutput = document.querySelector("#chart-output");
const chartEmpty = document.querySelector("#chart-empty");
const resultKind = document.querySelector("#result-kind");
const editorSurface = document.querySelector("#editor");
const fileTabs = document.querySelector("#file-tabs");
const sampleDialog = document.querySelector("#sample-dialog");
const sampleDialogSelect = document.querySelector("#sample-dialog-select");
const sampleDialogConfirm = document.querySelector("#sample-dialog-confirm");
const outputSection = document.querySelector(".output-section");
const outputPanel = document.querySelector("#output-panel");
const outputTabs = Array.from(document.querySelectorAll("[data-output-tab]"));
const outputPanels = {
  text: document.querySelector("#text-panel"),
  json: document.querySelector("#json-panel"),
};

let rpcId = 0;
let samples = [];
let saveUrlTimer = null;
let suppressEditorSync = false;
let fallbackTextarea = null;
let aceEditor = null;
let activeOutputTab = null;

let activeWorkspace = createWorkspace({
  files: { "main.dice": loadSavedSource() },
  entryPath: "main.dice",
});

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

function createWorkspace({ files, entryPath, samplePath = null, activeFilePath = null }) {
  const normalizedFiles = { ...files };
  const openFiles = Object.keys(normalizedFiles).sort((left, right) => {
    if (left === entryPath) {
      return -1;
    }
    if (right === entryPath) {
      return 1;
    }
    return left.localeCompare(right);
  });
  return {
    samplePath,
    files: normalizedFiles,
    entryPath,
    openFiles,
    activeFilePath: activeFilePath ?? entryPath,
  };
}

function loadSavedSource() {
  const url = new URL(window.location.href);
  const codeParam = url.searchParams.get("code");
  if (codeParam) {
    return codeParam;
  }
  const saved = window.localStorage.getItem(STORAGE_KEY);
  return saved || DEFAULT_SOURCE;
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

function persistWorkspace() {
  window.localStorage.setItem(STORAGE_KEY, entrySource());
  saveUrlState();
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

function setResultState(state) {
  resultKind.textContent = state;
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

function loadSnippets() {
  try {
    return JSON.parse(window.localStorage.getItem(SNIPPETS_KEY) || "{}");
  } catch (_error) {
    return {};
  }
}

function saveSnippets(snippets) {
  window.localStorage.setItem(SNIPPETS_KEY, JSON.stringify(snippets));
}

function refreshSnippetSelect() {
  const snippets = loadSnippets();
  const fragment = document.createDocumentFragment();

  const scratch = document.createElement("option");
  scratch.value = EMPTY_SNIPPET;
  scratch.textContent = "Scratchpad";
  fragment.appendChild(scratch);

  for (const name of Object.keys(snippets).sort()) {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    fragment.appendChild(option);
  }

  snippetSelect.replaceChildren(fragment);
  if (!snippetSelect.value) {
    snippetSelect.value = EMPTY_SNIPPET;
  }
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

    const button = document.createElement("button");
    button.type = "button";
    button.className = path === activeWorkspace.activeFilePath ? "file-tab is-active" : "file-tab";
    button.textContent = basename(path);
    button.title = path;
    button.addEventListener("click", () => {
      setActiveFile(path);
    });
    tab.appendChild(button);

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
  fileTabs.replaceChildren(fragment);
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
  activeWorkspace.openFiles = nextOpenFiles;

  renderFileTabs();
  setEditorValue(currentSource());
  persistWorkspace();
}

function initializeEditor() {
  if (window.ace) {
    editorSurface.textContent = "";
    aceEditor = window.ace.edit(editorSurface);
    aceEditor.setTheme("ace/theme/tomorrow_night_bright");
    aceEditor.session.setMode("ace/mode/text");
    aceEditor.session.setTabSize(2);
    aceEditor.session.setUseSoftTabs(true);
    aceEditor.setOptions({
      fontSize: "14px",
      showPrintMargin: false,
      wrap: true,
      highlightActiveLine: true,
    });
    aceEditor.commands.addCommand({
      name: "runDice",
      bindKey: { win: "Ctrl-Enter", mac: "Command-Enter" },
      exec: () => {
        void evaluateSource();
      },
    });
    aceEditor.session.on("change", () => {
      syncActiveFileFromEditor();
    });
    setEditorValue(currentSource());
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
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 720 340");
  svg.setAttribute("class", "chart-svg");
  wrapper.appendChild(svg);
  contentBuilder(svg);
  return wrapper;
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

function renderBarChart(chart) {
  return renderSvgChart((svg) => {
    const left = 64;
    const bottom = 288;
    const width = 600;
    const height = 220;
    const allValues = chart.series.flatMap((series) => series.values);
    const maxValue = Math.max(...allValues, 1);
    const barWidth = width / chart.categories.length;
    const palette = ["#b65c3a", "#3b6c8e", "#6f8a42", "#8a4f7d"];
    const seriesCount = chart.series.length;
    const innerBarWidth = Math.max((barWidth - 18) / seriesCount, 6);

    const axis = document.createElementNS("http://www.w3.org/2000/svg", "line");
    axis.setAttribute("x1", left);
    axis.setAttribute("y1", bottom);
    axis.setAttribute("x2", left + width);
    axis.setAttribute("y2", bottom);
    axis.setAttribute("class", "chart-axis-line");
    svg.appendChild(axis);

    const yAxis = document.createElementNS("http://www.w3.org/2000/svg", "line");
    yAxis.setAttribute("x1", left);
    yAxis.setAttribute("y1", bottom);
    yAxis.setAttribute("x2", left);
    yAxis.setAttribute("y2", bottom - height);
    yAxis.setAttribute("class", "chart-axis-line");
    svg.appendChild(yAxis);

    chart.series.forEach((series, seriesIndex) => {
      series.values.forEach((value, index) => {
        const normalized = value / maxValue;
        const barHeight = height * normalized;
        const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
        rect.setAttribute("x", left + index * barWidth + 8 + innerBarWidth * seriesIndex);
        rect.setAttribute("y", bottom - barHeight);
        rect.setAttribute("width", innerBarWidth - 2);
        rect.setAttribute("height", barHeight);
        rect.setAttribute("rx", "6");
        rect.setAttribute("fill", palette[seriesIndex % palette.length]);
        svg.appendChild(rect);
      });
    });

    chart.categories.forEach((category, index) => {
      appendSvgText(
        svg,
        left + index * barWidth + barWidth / 2,
        bottom + 20,
        String(category),
        "chart-tick",
        { "text-anchor": "middle" },
      );
    });

    chart.series.forEach((series, index) => {
      appendSvgText(svg, left + 8, 24 + index * 18, series.name, "chart-series-label", {
        fill: palette[index % palette.length],
      });
    });

    appendSvgText(svg, left + width / 2, 328, chart.spec.x_label, "chart-axis-label", {
      "text-anchor": "middle",
    });
    appendSvgText(svg, 20, 22, chart.spec.y_label, "chart-axis-label");
  });
}

function renderLineChart(chart) {
  return renderSvgChart((svg) => {
    const left = 64;
    const bottom = 288;
    const width = 600;
    const height = 220;
    const values = chart.series.flatMap((series) => series.values);
    const minValue = Math.min(...values);
    const maxValue = Math.max(...values);
    const xStep = chart.categories.length > 1 ? width / (chart.categories.length - 1) : width;
    const yRange = maxValue - minValue || 1;
    const palette = ["#b65c3a", "#3b6c8e", "#6f8a42", "#8a4f7d"];

    const axis = document.createElementNS("http://www.w3.org/2000/svg", "line");
    axis.setAttribute("x1", left);
    axis.setAttribute("y1", bottom);
    axis.setAttribute("x2", left + width);
    axis.setAttribute("y2", bottom);
    axis.setAttribute("class", "chart-axis-line");
    svg.appendChild(axis);

    const yAxis = document.createElementNS("http://www.w3.org/2000/svg", "line");
    yAxis.setAttribute("x1", left);
    yAxis.setAttribute("y1", bottom);
    yAxis.setAttribute("x2", left);
    yAxis.setAttribute("y2", bottom - height);
    yAxis.setAttribute("class", "chart-axis-line");
    svg.appendChild(yAxis);

    chart.categories.forEach((category, index) => {
      const x = left + index * xStep;
      appendSvgText(svg, x, bottom + 20, String(category), "chart-tick", {
        "text-anchor": "middle",
      });
    });

    chart.series.forEach((series, seriesIndex) => {
      const points = series.values.map((value, index) => {
        const x = left + index * xStep;
        const y = bottom - ((value - minValue) / yRange) * height;
        const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        circle.setAttribute("cx", x);
        circle.setAttribute("cy", y);
        circle.setAttribute("r", "4");
        circle.setAttribute("fill", palette[seriesIndex % palette.length]);
        svg.appendChild(circle);
        return `${x},${y}`;
      });

      const polyline = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
      polyline.setAttribute("points", points.join(" "));
      polyline.setAttribute("fill", "none");
      polyline.setAttribute("stroke", palette[seriesIndex % palette.length]);
      polyline.setAttribute("stroke-width", "3");
      svg.appendChild(polyline);

      appendSvgText(svg, left + 8, 24 + seriesIndex * 18, series.name, "chart-series-label", {
        fill: palette[seriesIndex % palette.length],
      });
    });

    appendSvgText(svg, left + width / 2, 328, chart.spec.x_label, "chart-axis-label", {
      "text-anchor": "middle",
    });
    appendSvgText(svg, 20, 22, chart.spec.y_label, "chart-axis-label");
  });
}

function renderHeatmap(chart) {
  const wrapper = document.createElement("div");
  wrapper.className = "heatmap";

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

    chart.matrix[rowIndex].forEach((cellValue) => {
      const cell = document.createElement("div");
      cell.className = "heatmap-cell";
      cell.style.background = interpolateColor(cellValue, maxValue);
      cell.textContent = Number.isFinite(cellValue) ? cellValue.toFixed(2) : String(cellValue);
      grid.appendChild(cell);
    });
  });

  wrapper.appendChild(grid);
  return wrapper;
}

function renderSingleChart(chart, container) {
  container.replaceChildren();
  if (!chart) {
    return false;
  }
  if (chart.title) {
    const heading = document.createElement("div");
    heading.className = "chart-caption";
    heading.innerHTML = `<span>${chart.title}</span><span>${chart.spec?.kind ?? chart.kind}</span>`;
    container.appendChild(heading);
  }
  if (chart.kind === "bar" || chart.kind === "compare_bar") {
    container.appendChild(renderBarChart(chart));
    return true;
  }
  if (chart.kind === "line" || chart.kind === "compare_line") {
    container.appendChild(renderLineChart(chart));
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

function setActiveOutputTab(nextTab) {
  activeOutputTab = nextTab;
  const isOpen = Boolean(activeOutputTab);

  outputSection.classList.toggle("is-collapsed", !isOpen);
  outputPanel.hidden = !isOpen;

  outputTabs.forEach((button) => {
    const isActive = button.dataset.outputTab === activeOutputTab;
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-selected", String(isActive));
  });

  Object.entries(outputPanels).forEach(([name, panel]) => {
    panel.hidden = !isOpen || name !== activeOutputTab;
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
  activeWorkspace = createWorkspace({
    files: sample.files,
    entryPath: sample.source_path,
    samplePath: path,
  });
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

outputTabs.forEach((button) => {
  button.addEventListener("click", () => {
    const nextTab = button.dataset.outputTab;
    setActiveOutputTab(activeOutputTab === nextTab ? null : nextTab);
  });
});

saveSnippetButton.addEventListener("click", () => {
  syncActiveFileFromEditor();
  const name = window.prompt("Snippet name");
  if (!name) {
    return;
  }
  const snippets = loadSnippets();
  snippets[name] = currentSource();
  saveSnippets(snippets);
  refreshSnippetSelect();
  snippetSelect.value = name;
});

deleteSnippetButton.addEventListener("click", () => {
  const selected = snippetSelect.value;
  if (!selected || selected === EMPTY_SNIPPET) {
    return;
  }
  const snippets = loadSnippets();
  delete snippets[selected];
  saveSnippets(snippets);
  refreshSnippetSelect();
  snippetSelect.value = EMPTY_SNIPPET;
});

snippetSelect.addEventListener("change", () => {
  const selected = snippetSelect.value;
  if (selected === EMPTY_SNIPPET) {
    return;
  }
  const snippets = loadSnippets();
  const snippet = snippets[selected];
  if (!snippet) {
    return;
  }
  activeWorkspace = createWorkspace({
    files: { "main.dice": snippet },
    entryPath: "main.dice",
  });
  renderFileTabs();
  setEditorValue(currentSource());
  persistWorkspace();
});

refreshSnippetSelect();
setActiveOutputTab(null);
textOutput.textContent = "";
jsonOutput.textContent = "";
chartOutput.replaceChildren();
chartEmpty.hidden = false;

async function boot() {
  try {
    await callWorker("init");
    samples = await callWorker("listSamples");
    const url = new URL(window.location.href);
    const sampleFromUrl = url.searchParams.get("sample");
    const sharedSource = url.searchParams.get("code");
    if (sampleFromUrl) {
      await loadSamplePath(sampleFromUrl);
      if (sharedSource) {
        activeWorkspace.files[activeWorkspace.entryPath] = sharedSource;
        if (activeWorkspace.activeFilePath === activeWorkspace.entryPath) {
          setEditorValue(sharedSource);
        }
        persistWorkspace();
      }
    }
    await evaluateSource();
  } catch (error) {
    diagnosticPanel.hidden = false;
    diagnosticOutput.textContent = error.message;
    setResultState("error");
  }
}

void boot();
