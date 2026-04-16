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

function isZeroCategory(category) {
  return category === 0 || category === "0";
}

function isPositiveNumericCategory(category) {
  return typeof category === "number" && category > 0;
}

function prepareBarChart(chart) {
  const zeroIndex = chart.categories.findIndex((category) => isZeroCategory(category));
  const hasPositiveCategory = chart.categories.some((category) => isPositiveNumericCategory(category));

  if (zeroIndex < 0 || !hasPositiveCategory) {
    return { chart, zeroNote: null };
  }

  const zeroValues = chart.series.map((series) => series.values[zeroIndex] ?? 0);
  const hasVisibleZeroMass = zeroValues.some((value) => value > 0);
  if (!hasVisibleZeroMass) {
    return { chart, zeroNote: null };
  }

  const categories = chart.categories.filter((_category, index) => index !== zeroIndex);
  if (categories.length === 0) {
    return { chart, zeroNote: null };
  }

  const series = chart.series.map((seriesEntry) => ({
    ...seriesEntry,
    values: seriesEntry.values.filter((_value, index) => index !== zeroIndex),
  }));

  const zeroNote =
    chart.series.length === 1
      ? `Zero outcome hidden: ${formatHoverValue(zeroValues[0], chart.spec.y_label)}`
      : `Zero outcome hidden: ${chart.series
          .map((seriesEntry, index) => `${seriesEntry.name} ${formatHoverValue(zeroValues[index], chart.spec.y_label)}`)
          .join(", ")}`;

  return {
    chart: {
      ...chart,
      categories,
      series,
    },
    zeroNote,
  };
}

function normalizeIndexRange(range, totalCount) {
  if (!range || totalCount <= 0) {
    return { start: 0, end: Math.max(totalCount - 1, 0) };
  }
  return {
    start: Math.max(0, Math.min(range.start, totalCount - 1)),
    end: Math.max(0, Math.min(range.end, totalCount - 1)),
  };
}

function isFullIndexRange(range, totalCount) {
  if (totalCount <= 0) {
    return true;
  }
  const normalized = normalizeIndexRange(range, totalCount);
  return normalized.start === 0 && normalized.end === totalCount - 1;
}

function sliceCartesianChart(chart, range) {
  if (!chart.categories || chart.categories.length === 0) {
    return chart;
  }
  const normalized = normalizeIndexRange(range, chart.categories.length);
  return {
    ...chart,
    categories: chart.categories.slice(normalized.start, normalized.end + 1),
    series: chart.series.map((seriesEntry) => ({
      ...seriesEntry,
      values: seriesEntry.values.slice(normalized.start, normalized.end + 1),
    })),
  };
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

function pointerToSvgPoint(event, svg) {
  const bounds = svg.getBoundingClientRect();
  const viewBox = svg.viewBox.baseVal;
  const width = bounds.width || 1;
  const height = bounds.height || 1;
  return {
    x: ((event.clientX - bounds.left) / width) * viewBox.width,
    y: ((event.clientY - bounds.top) / height) * viewBox.height,
  };
}

function attachCartesianZoom(svg, options) {
  const { left, top, width, height, totalCount, visibleRange, anchorMode, onZoom, onReset } = options;
  if (totalCount <= 2) {
    return;
  }
  svg.classList.add("is-zoomable");

  const selection = document.createElementNS("http://www.w3.org/2000/svg", "rect");
  selection.setAttribute("class", "chart-brush");
  selection.hidden = true;
  svg.appendChild(selection);

  let dragStartX = null;
  let activePointerId = null;
  const normalizedVisibleRange = normalizeIndexRange(visibleRange, totalCount);
  const visibleCount = normalizedVisibleRange.end - normalizedVisibleRange.start + 1;

  function indexForPoint(x) {
    const clampedX = Math.max(left, Math.min(left + width, x));
    const localX = clampedX - left;
    if (anchorMode === "line") {
      if (visibleCount <= 1) {
        return normalizedVisibleRange.start;
      }
      const fraction = localX / width;
      const visibleIndex = Math.round(fraction * (visibleCount - 1));
      return normalizedVisibleRange.start + Math.max(0, Math.min(visibleIndex, visibleCount - 1));
    }
    const bucketWidth = width / visibleCount;
    const visibleIndex = Math.floor(localX / bucketWidth);
    return normalizedVisibleRange.start + Math.max(0, Math.min(visibleIndex, visibleCount - 1));
  }

  function updateSelection(startX, currentX) {
    const clampedStart = Math.max(left, Math.min(left + width, startX));
    const clampedCurrent = Math.max(left, Math.min(left + width, currentX));
    selection.hidden = false;
    selection.setAttribute("x", Math.min(clampedStart, clampedCurrent));
    selection.setAttribute("y", top);
    selection.setAttribute("width", Math.max(Math.abs(clampedCurrent - clampedStart), 1));
    selection.setAttribute("height", height);
  }

  function clearSelection() {
    selection.hidden = true;
    dragStartX = null;
    activePointerId = null;
  }

  svg.addEventListener("pointerdown", (event) => {
    const point = pointerToSvgPoint(event, svg);
    const inPlotX = point.x >= left && point.x <= left + width;
    const inPlotY = point.y >= top && point.y <= top + height;
    if (!inPlotX || !inPlotY) {
      return;
    }
    dragStartX = point.x;
    activePointerId = event.pointerId;
    if (typeof svg.setPointerCapture === "function") {
      svg.setPointerCapture(event.pointerId);
    }
    updateSelection(dragStartX, point.x);
  });

  svg.addEventListener("pointermove", (event) => {
    if (dragStartX === null || event.pointerId !== activePointerId) {
      return;
    }
    const point = pointerToSvgPoint(event, svg);
    updateSelection(dragStartX, point.x);
  });

  svg.addEventListener("pointerup", (event) => {
    if (dragStartX === null || event.pointerId !== activePointerId) {
      return;
    }
    const point = pointerToSvgPoint(event, svg);
    const startIndex = indexForPoint(dragStartX);
    const endIndex = indexForPoint(point.x);
    const nextRange = {
      start: Math.min(startIndex, endIndex),
      end: Math.max(startIndex, endIndex),
    };
    const didDrag = Math.abs(point.x - dragStartX) >= 14;
    clearSelection();
    if (didDrag && nextRange.end > nextRange.start && !isFullIndexRange(nextRange, totalCount)) {
      onZoom(nextRange);
    }
  });

  svg.addEventListener("pointercancel", () => {
    clearSelection();
  });

  svg.addEventListener("dblclick", () => {
    if (!isFullIndexRange(visibleRange, totalCount)) {
      onReset();
    }
  });
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
  const { scaleMode = "auto", includeZeroByDefault = false, probabilitySeries = false } = options;
  const range = chartValueRange(values);

  if (scaleMode === "tight") {
    const padded = paddedRange(range.min, range.max, 0.08);
    return buildLinearScale(padded.min, padded.max, { includeZero: false });
  }

  if (scaleMode === "zero") {
    const paddedMax =
      range.max === 0
        ? 1
        : range.max + Math.max(Math.abs(range.max) * 0.08, Math.abs(range.max - range.min) * 0.04, 0.25);
    return buildLinearScale(Math.min(range.min, 0), paddedMax, { includeZero: true });
  }

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
  return renderSvgChart((svg, tooltip) => {
    const wrapper = svg.parentNode;
    const prepared = prepareBarChart(chart);
    const fullChart = prepared.chart;
    const visibleRange = normalizeIndexRange(options.zoomRange, fullChart.categories.length);
    const displayChart = sliceCartesianChart(fullChart, visibleRange);
    const left = 76;
    const width = 620;
    const height = 222;
    const values = displayChart.series.flatMap((series) => series.values);
    const scale = buildChartScale(values, {
      scaleMode: options.scaleMode,
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

    if (prepared.zeroNote) {
      const note = document.createElement("div");
      note.className = "chart-note";
      note.textContent = prepared.zeroNote;
      wrapper.appendChild(note);
    }

    attachCartesianZoom(svg, {
      left,
      top,
      width,
      height,
      totalCount: fullChart.categories.length,
      visibleRange,
      anchorMode: "bar",
      onZoom: options.onZoom ?? (() => {}),
      onReset: options.onReset ?? (() => {}),
    });
  });
}

function renderLineChart(chart, options = {}) {
  return renderSvgChart((svg, tooltip) => {
    const fullChart = chart;
    const visibleRange = normalizeIndexRange(options.zoomRange, fullChart.categories.length);
    const displayChart = sliceCartesianChart(fullChart, visibleRange);
    const left = 76;
    const width = 620;
    const height = 222;
    const values = displayChart.series.flatMap((series) => series.values);
    const probabilitySeries = isProbabilityLabel(displayChart.spec.y_label);
    const scale = buildChartScale(values, {
      scaleMode: options.scaleMode,
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

    attachCartesianZoom(svg, {
      left,
      top,
      width,
      height,
      totalCount: fullChart.categories.length,
      visibleRange,
      anchorMode: "line",
      onZoom: options.onZoom ?? (() => {}),
      onReset: options.onReset ?? (() => {}),
    });
  });
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
  const scaleMode = options.scaleMode ?? "auto";
  const chartNode =
    view === "line"
      ? renderLineChart(displayChart, {
          scaleMode,
          zoomRange: options.zoomRange,
          onZoom: options.onZoom,
          onReset: options.onReset,
        })
      : renderBarChart(displayChart, {
          scaleMode,
          zoomRange: options.zoomRange,
          onZoom: options.onZoom,
          onReset: options.onReset,
        });
  plotHost.replaceChildren(chartNode);
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
    const legend = buildLegend(chart);
    let activeView = chartToggleView(chart.kind);
    let activeScaleMode = "auto";
    let activeZoomRange = null;
    const zoomable = Array.isArray(chart.categories) && chart.categories.length > 2;

    const renderActiveChart = () => {
      const activeChart = chartWithView(chart, activeView);
      renderCartesianChart(activeChart, plotHost, {
        view: activeView,
        scaleMode: activeScaleMode,
        zoomRange: activeZoomRange,
        onZoom: (nextRange) => {
          activeZoomRange = nextRange;
          renderActiveChart();
          syncButtons(controlButtons);
        },
        onReset: () => {
          activeZoomRange = null;
          renderActiveChart();
          syncButtons(controlButtons);
        },
      });
      if (modeLabel) {
        modeLabel.textContent = `${activeChart.kind} · ${activeScaleMode}`;
      }
    };

    const syncButtons = (buttons) => {
      buttons.forEach((button) => {
        const buttonValue = button.dataset.view ?? button.dataset.scaleMode;
        const activeValue = button.dataset.view ? activeView : button.dataset.scaleMode ? activeScaleMode : null;
        const isActive = buttonValue === activeValue;
        button.classList.toggle("is-active", isActive);
        button.setAttribute("aria-pressed", String(isActive));
        if (button.dataset.action === "reset-zoom") {
          button.disabled = activeZoomRange === null;
        }
      });
    };

    const controlButtons = [];
    const viewControls = document.createElement("div");
    viewControls.className = "chart-control-group";
    const viewLabel = document.createElement("span");
    viewLabel.className = "chart-control-label";
    viewLabel.textContent = "View";
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

    const scaleControls = document.createElement("div");
    scaleControls.className = "chart-control-group";
    const scaleLabel = document.createElement("span");
    scaleLabel.className = "chart-control-label";
    scaleLabel.textContent = "Scale";
    scaleControls.appendChild(scaleLabel);
    [
      ["auto", "Auto"],
      ["zero", "Zero"],
      ["tight", "Tight"],
    ].forEach(([scaleMode, label]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "chart-toggle";
      button.dataset.scaleMode = scaleMode;
      button.textContent = label;
      button.addEventListener("click", () => {
        if (activeScaleMode === scaleMode) {
          return;
        }
        activeScaleMode = scaleMode;
        renderActiveChart();
        syncButtons(controlButtons);
      });
      controlButtons.push(button);
      scaleControls.appendChild(button);
    });
    controls.appendChild(scaleControls);

    if (zoomable) {
      const actionControls = document.createElement("div");
      actionControls.className = "chart-control-group";
      const zoomHint = document.createElement("span");
      zoomHint.className = "chart-control-label";
      zoomHint.textContent = "Drag to zoom";
      actionControls.appendChild(zoomHint);
      const resetZoomButton = document.createElement("button");
      resetZoomButton.type = "button";
      resetZoomButton.className = "chart-toggle";
      resetZoomButton.dataset.action = "reset-zoom";
      resetZoomButton.textContent = "Reset Zoom";
      resetZoomButton.addEventListener("click", () => {
        if (activeZoomRange === null) {
          return;
        }
        activeZoomRange = null;
        renderActiveChart();
        syncButtons(controlButtons);
      });
      controlButtons.push(resetZoomButton);
      actionControls.appendChild(resetZoomButton);
      controls.appendChild(actionControls);
    }

    syncButtons(controlButtons);
    renderActiveChart();
    container.appendChild(controls);
    container.appendChild(plotHost);
    if (legend) {
      container.appendChild(legend);
    }
    return true;
  }
  if (chart.kind === "bar" || chart.kind === "compare_bar") {
    container.appendChild(renderBarChart(chart));
    const legend = buildLegend(chart);
    if (legend) {
      container.appendChild(legend);
    }
    return true;
  }
  if (chart.kind === "line" || chart.kind === "compare_line") {
    container.appendChild(renderLineChart(chart));
    const legend = buildLegend(chart);
    if (legend) {
      container.appendChild(legend);
    }
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
