const DEFAULT_SOURCE = `import "std:dnd/core"

attack_bonus = 7
target_ac = [ac:10, 12, 14, 16, 18, 20]

d20 + attack_bonus >= target_ac`;

const STORAGE_KEY = "dice-web:last-source";
const SNIPPETS_KEY = "dice-web:snippets";
const EMPTY_SNIPPET = "__empty__";

const runtimeStatus = document.querySelector("#runtime-status");
const runtimeDetail = document.querySelector("#runtime-detail");
const builtinCount = document.querySelector("#builtin-count");
const runButton = document.querySelector("#run-button");
const shareButton = document.querySelector("#share-button");
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

let rpcId = 0;
let workerReady = false;
let symbols = null;
let saveUrlTimer = null;

const worker = new Worker(new URL("./worker.js", import.meta.url));
const pendingRpc = new Map();

let fallbackTextarea = null;
let aceEditor = null;

function initializeEditor() {
  if (window.ace) {
    editorSurface.textContent = "";
    aceEditor = window.ace.edit(editorSurface);
    aceEditor.session.setValue(loadSavedSource());
    aceEditor.setTheme("ace/theme/tomorrow_night_bright");
    aceEditor.session.setMode("ace/mode/text");
    aceEditor.session.setTabSize(2);
    aceEditor.session.setUseSoftTabs(true);
    aceEditor.setOptions({
      fontSize: "15px",
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
      persistSource(currentSource());
    });
    return;
  }

  fallbackTextarea = document.createElement("textarea");
  fallbackTextarea.className = "editor-textarea";
  fallbackTextarea.setAttribute("spellcheck", "false");
  fallbackTextarea.setAttribute("aria-label", "dice editor");
  fallbackTextarea.value = loadSavedSource();
  fallbackTextarea.addEventListener("input", () => {
    persistSource(currentSource());
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
    const value = currentSource();
    replaceSource(value.slice(0, start) + "  " + value.slice(end));
    fallbackTextarea.selectionStart = start + 2;
    fallbackTextarea.selectionEnd = start + 2;
  });
  editorSurface.replaceChildren(fallbackTextarea);
}

initializeEditor();

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

function loadSavedSource() {
  const url = new URL(window.location.href);
  const codeParam = url.searchParams.get("code");
  if (codeParam) {
    return codeParam;
  }
  const saved = window.localStorage.getItem(STORAGE_KEY);
  return saved || DEFAULT_SOURCE;
}

function currentSource() {
  if (aceEditor) {
    return aceEditor.getValue();
  }
  return fallbackTextarea.value;
}

function replaceSource(nextSource) {
  if (aceEditor) {
    aceEditor.session.setValue(nextSource);
    aceEditor.clearSelection();
  } else {
    fallbackTextarea.value = nextSource;
  }
  persistSource(nextSource);
}

function persistSource(source) {
  window.localStorage.setItem(STORAGE_KEY, source);
  saveUrlState(source);
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

function buildShareUrl(source) {
  const url = new URL(window.location.href);
  url.searchParams.set("code", source);
  return url;
}

function saveUrlState(source) {
  if (saveUrlTimer) {
    window.clearTimeout(saveUrlTimer);
  }
  saveUrlTimer = window.setTimeout(() => {
    window.history.replaceState({}, "", buildShareUrl(source));
  }, 300);
}

function updateRuntimeStatus(label, detail, kind = "idle") {
  runtimeStatus.textContent = label;
  runtimeDetail.textContent = detail;
  resultKind.textContent = kind;
}

function formatProbability(value) {
  return `${value.toFixed(2)}%`;
}

function formatDistributionTable(distribution) {
  const header = ["Outcome", "Probability"];
  const rows = distribution.map((entry) => [String(entry.outcome), formatProbability(entry.probability * 100)]);
  const widths = header.map((title, index) => Math.max(title.length, ...rows.map((row) => row[index].length)));
  const formatRow = (row) => row.map((value, index) => value.padEnd(widths[index])).join("  ");
  return [formatRow(header), formatRow(widths.map((width) => "-".repeat(width))), ...rows.map(formatRow)].join("\n");
}

function summarizeResult(result) {
  if (result.type === "scalar") {
    return String(result.value);
  }
  if (result.type === "string") {
    return result.value;
  }
  if (result.type === "distribution") {
    return formatDistributionTable(result.distribution);
  }
  if (result.type === "distributions" && result.axes.length === 0) {
    return formatDistributionTable(result.cells[0].distribution);
  }
  return JSON.stringify(result, null, 2);
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
    const maxValue = Math.max(...chart.series[0].values, 1);
    const barWidth = width / chart.categories.length;

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

    chart.series[0].values.forEach((value, index) => {
      const normalized = value / maxValue;
      const barHeight = height * normalized;
      const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      rect.setAttribute("x", left + index * barWidth + 8);
      rect.setAttribute("y", bottom - barHeight);
      rect.setAttribute("width", Math.max(barWidth - 16, 8));
      rect.setAttribute("height", barHeight);
      rect.setAttribute("rx", "8");
      rect.setAttribute("class", "chart-bar");
      svg.appendChild(rect);

      appendSvgText(
        svg,
        left + index * barWidth + barWidth / 2,
        bottom + 20,
        String(chart.categories[index]),
        "chart-tick",
        { "text-anchor": "middle" },
      );
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
    const values = chart.series[0].values;
    const minValue = Math.min(...values);
    const maxValue = Math.max(...values);
    const xStep = chart.categories.length > 1 ? width / (chart.categories.length - 1) : width;
    const yRange = maxValue - minValue || 1;

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

    const points = values.map((value, index) => {
      const x = left + index * xStep;
      const y = bottom - ((value - minValue) / yRange) * height;
      appendSvgText(svg, x, bottom + 20, String(chart.categories[index]), "chart-tick", {
        "text-anchor": "middle",
      });
      const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      circle.setAttribute("cx", x);
      circle.setAttribute("cy", y);
      circle.setAttribute("r", "4");
      circle.setAttribute("class", "chart-point");
      svg.appendChild(circle);
      return `${x},${y}`;
    });

    const polyline = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
    polyline.setAttribute("points", points.join(" "));
    polyline.setAttribute("class", "chart-line");
    svg.appendChild(polyline);

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

function renderChart(chart) {
  chartOutput.replaceChildren();
  if (!chart) {
    chartEmpty.hidden = false;
    return;
  }
  chartEmpty.hidden = true;
  if (chart.kind === "bar") {
    chartOutput.appendChild(renderBarChart(chart));
    return;
  }
  if (chart.kind === "line") {
    chartOutput.appendChild(renderLineChart(chart));
    return;
  }
  if (chart.kind === "heatmap_distribution" || chart.kind === "heatmap_scalar") {
    chartOutput.appendChild(renderHeatmap(chart));
    return;
  }
  chartEmpty.hidden = false;
}

function setOutputs(payload) {
  if (!payload.ok) {
    diagnosticPanel.hidden = false;
    diagnosticOutput.textContent = payload.error.formatted;
    textOutput.textContent = "";
    jsonOutput.textContent = "";
    renderChart(null);
    resultKind.textContent = "error";
    return;
  }

  diagnosticPanel.hidden = true;
  diagnosticOutput.textContent = "";
  textOutput.textContent = summarizeResult(payload.result);
  jsonOutput.textContent = JSON.stringify(payload.result, null, 2);
  resultKind.textContent = payload.result.type;
  renderChart(payload.render);
}

async function evaluateSource() {
  const source = currentSource();
  updateRuntimeStatus("Evaluating…", "Running dice in a Pyodide worker.", "running");
  try {
    const payload = await callWorker("evaluate", { source });
    setOutputs(payload);
    if (payload.ok) {
      updateRuntimeStatus("Ready", "Worker runtime is warm. Use Cmd/Ctrl+Enter to re-run.", payload.result.type);
    } else {
      updateRuntimeStatus("Diagnostic", "The runtime returned a structured error.", "error");
    }
  } catch (error) {
    diagnosticPanel.hidden = false;
    diagnosticOutput.textContent = error.message;
    updateRuntimeStatus("Worker failed", error.message, "error");
  }
}

async function copyShareUrl() {
  const url = buildShareUrl(currentSource());
  window.history.replaceState({}, "", url);
  await navigator.clipboard.writeText(url.toString());
  shareButton.textContent = "Copied";
  window.setTimeout(() => {
    shareButton.textContent = "Copy Share URL";
  }, 1200);
}

runButton.addEventListener("click", () => {
  void evaluateSource();
});

shareButton.addEventListener("click", () => {
  void copyShareUrl();
});

saveSnippetButton.addEventListener("click", () => {
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
  replaceSource(snippet);
});

refreshSnippetSelect();
setOutputs({ ok: true, result: { type: "string", value: "Runtime not started yet." }, render: null });
textOutput.textContent = "Runtime not started yet.";
jsonOutput.textContent = "{}";

async function boot() {
  updateRuntimeStatus("Booting Pyodide…", "Loading runtime files from ./runtime and initializing the worker.", "booting");
  try {
    symbols = await callWorker("init");
    workerReady = true;
    builtinCount.textContent = `${symbols.builtins.length} builtins`;
    updateRuntimeStatus("Ready", "Pyodide is warm and the dice web bridge is loaded.", "ready");
    await evaluateSource();
  } catch (error) {
    workerReady = false;
    updateRuntimeStatus("Boot failed", error.message, "error");
    diagnosticPanel.hidden = false;
    diagnosticOutput.textContent = error.message;
  }
}

void boot();
