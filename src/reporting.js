const REPORT_STORAGE_KEY = "dice-web:last-reports";

const PALETTE = ["#7b3e2c", "#2f5d8c", "#6f8a42", "#8a4f7d", "#4b6452", "#a55f2a"];
const DIVERGING = ["#3b6c8e", "#d9ddd8", "#b65c3a"];

function getPlot() {
  return globalThis.Plot ?? null;
}

function isNumeric(value) {
  return typeof value === "number" && Number.isFinite(value);
}

function asLabel(value) {
  return isNumeric(value) ? value : String(value);
}

function uniqueNotes(lines) {
  const notes = [];
  for (const line of lines ?? []) {
    if (!line || notes.includes(line)) {
      continue;
    }
    notes.push(line);
  }
  return notes;
}

function hintValues(panel, kind) {
  return (panel?.hints ?? []).filter((hint) => hint?.kind === kind);
}

function panelNotes(panel) {
  return uniqueNotes((panel?.hints ?? []).map((hint) => hint?.note).filter(Boolean));
}

function probabilityLabel(panel, fallback = "Probability") {
  return panel?.y_label ?? fallback;
}

function deterministicProbability(entries) {
  if (!Array.isArray(entries) || entries.length !== 1) {
    return false;
  }
  const probability = entries[0]?.probability;
  return Math.abs(probability - 100) < 1e-9 || Math.abs(probability - 1) < 1e-9;
}

function scalarFromDistribution(entries) {
  return entries?.[0]?.outcome ?? null;
}

function outcomeDomainFromHints(panel, outcomes) {
  let visible = [...outcomes];
  for (const hint of hintValues(panel, "clip_outcomes")) {
    if (Array.isArray(hint.visible_outcomes) && hint.visible_outcomes.length > 0) {
      visible = [...hint.visible_outcomes];
    }
  }
  for (const hint of hintValues(panel, "omit_outcome")) {
    visible = visible.filter((outcome) => outcome !== hint.outcome);
  }
  return visible.length > 0 ? visible : [...outcomes];
}

function seriesLabelSuffixes(panel) {
  const suffixes = new Map();
  for (const hint of hintValues(panel, "series_label_suffix")) {
    if (hint?.label && hint?.suffix) {
      suffixes.set(hint.label, hint.suffix);
    }
  }
  return suffixes;
}

function resultAxes(result) {
  return Array.isArray(result?.axes) ? result.axes : [];
}

function resultCells(result) {
  return Array.isArray(result?.cells) ? result.cells : [];
}

function firstDistribution(result) {
  return resultCells(result)[0]?.distribution ?? [];
}

function cellCoordinateValues(cell) {
  return (cell?.coordinates ?? []).map((entry) => entry?.value);
}

function cellLookup(result) {
  const lookup = new Map();
  for (const cell of resultCells(result)) {
    lookup.set(JSON.stringify(cellCoordinateValues(cell)), cell);
  }
  return lookup;
}

function distributionAt(result, coordinates) {
  return cellLookup(result).get(JSON.stringify(coordinates))?.distribution ?? [];
}

function buildUnsweptData(panel) {
  const entries = firstDistribution(panel.payload);
  const visibleOutcomes = outcomeDomainFromHints(
    panel,
    entries.map((entry) => entry.outcome),
  );
  const entryMap = new Map(entries.map((entry) => [entry.outcome, entry]));
  return visibleOutcomes
    .map((outcome) => entryMap.get(outcome))
    .filter(Boolean)
    .map((entry) => ({
      outcome: asLabel(entry.outcome),
      probability: entry.probability,
    }));
}

function buildStepSeries(panel) {
  const suffixes = seriesLabelSuffixes(panel);
  const data = [];
  const outcomes = new Set();
  const outcomeByLabel = new Map();
  for (const entry of panel.payload ?? []) {
    const distribution = firstDistribution(entry.result);
    const visible = outcomeDomainFromHints(
      panel,
      distribution.map((item) => item.outcome),
    );
    outcomeByLabel.set(entry.label, new Set(visible));
    for (const item of distribution) {
      outcomes.add(item.outcome);
    }
  }
  const orderedOutcomes = outcomeDomainFromHints(panel, Array.from(outcomes).sort((left, right) => left - right));
  for (const entry of panel.payload ?? []) {
    const distribution = firstDistribution(entry.result);
    const distributionMap = new Map(distribution.map((item) => [item.outcome, item.probability]));
    const visible = outcomeByLabel.get(entry.label) ?? new Set();
    for (const outcome of orderedOutcomes) {
      if (!visible.has(outcome)) {
        continue;
      }
      data.push({
        label: `${entry.label}${suffixes.get(entry.label) ?? ""}`,
        outcome: asLabel(outcome),
        probability: distributionMap.get(outcome) ?? 0,
      });
    }
  }
  return data;
}

function buildScalarSweepData(result) {
  const axis = resultAxes(result)[0];
  return resultCells(result).map((cell) => ({
    x: asLabel(cell.coordinates?.[0]?.value),
    value: scalarFromDistribution(cell.distribution),
  })).sort((left, right) => {
    if (isNumeric(left.x) && isNumeric(right.x)) {
      return left.x - right.x;
    }
    return String(left.x).localeCompare(String(right.x));
  });
}

function buildDistributionSweepData(result) {
  const axis = resultAxes(result)[0];
  const rows = [];
  for (const axisValue of axis?.values ?? []) {
    const distribution = distributionAt(result, [axisValue]);
    for (const entry of distribution) {
      rows.push({
        x: asLabel(axisValue),
        outcome: asLabel(entry.outcome),
        probability: entry.probability,
      });
    }
  }
  return rows;
}

function buildScalarHeatmapData(result) {
  const axes = resultAxes(result);
  const yAxis = axes[0];
  const xAxis = axes[1];
  const rows = [];
  const lookup = cellLookup(result);
  for (const yValue of yAxis?.values ?? []) {
    for (const xValue of xAxis?.values ?? []) {
      const cell = lookup.get(JSON.stringify([yValue, xValue]));
      if (!cell) {
        continue;
      }
      rows.push({
        x: asLabel(xValue),
        y: asLabel(yValue),
        value: scalarFromDistribution(cell.distribution),
      });
    }
  }
  return rows;
}

function buildCompareScalarData(panel) {
  const rows = [];
  for (const entry of panel.payload ?? []) {
    const axis = resultAxes(entry.result)[0];
    const lookup = cellLookup(entry.result);
    for (const value of axis?.values ?? []) {
      const cell = lookup.get(JSON.stringify([value]));
      if (!cell) {
        continue;
      }
      rows.push({
        label: entry.label,
        x: asLabel(value),
        value: scalarFromDistribution(cell.distribution),
      });
    }
  }
  return rows;
}

function buildDiffData(panel) {
  const [left, right] = panel.payload ?? [];
  if (!left || !right) {
    return [];
  }
  const axis = resultAxes(left.result)[0];
  const leftLookup = cellLookup(left.result);
  const rightLookup = cellLookup(right.result);
  return (axis?.values ?? []).map((value) => {
    const leftValue = scalarFromDistribution(leftLookup.get(JSON.stringify([value]))?.distribution ?? []);
    const rightValue = scalarFromDistribution(rightLookup.get(JSON.stringify([value]))?.distribution ?? []);
    return {
      x: asLabel(value),
      value: (leftValue ?? 0) - (rightValue ?? 0),
    };
  });
}

function bestStrategyData(result) {
  const [strategyAxis, conditionAxis] = resultAxes(result);
  const lookup = cellLookup(result);
  const winnerRows = [];
  const marginRows = [];
  for (const condition of conditionAxis?.values ?? []) {
    const ranked = (strategyAxis?.values ?? [])
      .map((strategy) => ({
        strategy,
        value: scalarFromDistribution(
          lookup.get(JSON.stringify([strategy, condition]))?.distribution ?? [],
        ),
      }))
      .sort((left, right) => (right.value ?? -Infinity) - (left.value ?? -Infinity));
    if (!ranked.length) {
      continue;
    }
    winnerRows.push({
      x: asLabel(condition),
      y: "Winner",
      strategy: asLabel(ranked[0].strategy),
    });
    marginRows.push({
      x: asLabel(condition),
      value: (ranked[0].value ?? 0) - (ranked[1]?.value ?? 0),
    });
  }
  return { winnerRows, marginRows };
}

function autoPanelFromResult(label, result, inherited) {
  const axes = resultAxes(result);
  const base = {
    kind: "unswept_distribution",
    width_class: "narrow",
    title: label,
    x_label: inherited?.x_label ?? null,
    y_label: inherited?.y_label ?? null,
    hints: [],
    payload: result,
  };
  if (axes.length === 0) {
    return base;
  }
  if (axes.length === 1) {
    const deterministic = resultCells(result).every((cell) => deterministicProbability(cell.distribution));
    return {
      ...base,
      kind: deterministic ? "scalar_sweep" : "distribution_sweep",
      width_class: deterministic ? "narrow" : "wide",
    };
  }
  if (axes.length === 2) {
    return {
      ...base,
      kind: "scalar_heatmap",
      width_class: "wide",
    };
  }
  return base;
}

function appendNotes(host, notes) {
  const unique = uniqueNotes(notes);
  if (unique.length === 0) {
    return;
  }
  const notesHost = document.createElement("div");
  notesHost.className = "chart-notes";
  notesHost.replaceChildren(
    ...unique.map((line) => {
      const note = document.createElement("div");
      note.className = "chart-note";
      note.textContent = line;
      return note;
    }),
  );
  host.appendChild(notesHost);
}

function appendPlot(host, plot) {
  const frame = document.createElement("div");
  frame.className = "chart-plot-host plot-frame";
  frame.appendChild(plot);
  host.appendChild(frame);
}

function renderPanelCaption(panel, host) {
  if (!panel?.title && !panel?.kind) {
    return;
  }
  const caption = document.createElement("div");
  caption.className = "chart-caption";
  const title = document.createElement("span");
  title.textContent = panel.title || "";
  const kind = document.createElement("span");
  kind.textContent = panel.kind;
  caption.append(title, kind);
  host.appendChild(caption);
}

function plotOptions(panel, overrides = {}) {
  return {
    width: overrides.width ?? 720,
    height: overrides.height ?? 320,
    marginTop: 20,
    marginRight: 20,
    marginBottom: 48,
    marginLeft: 56,
    style: {
      fontFamily: "\"IBM Plex Sans\", \"Avenir Next\", \"Helvetica Neue\", sans-serif",
      background: "#f5f0e7",
      color: "#201d18",
    },
    ...overrides,
  };
}

function renderUnswept(panel) {
  const Plot = getPlot();
  const data = buildUnsweptData(panel);
  return Plot.plot(
    plotOptions(panel, {
      y: { grid: true, label: probabilityLabel(panel, "Probability (%)") },
      x: { label: panel.x_label ?? "Outcome" },
      marks: [
        Plot.ruleY([0]),
        Plot.barY(data, { x: "outcome", y: "probability", fill: PALETTE[0], title: "probability", tip: true }),
      ],
    }),
  );
}

function renderCurve(panel, mode) {
  const Plot = getPlot();
  const distribution = firstDistribution(panel.payload);
  const visible = outcomeDomainFromHints(panel, distribution.map((entry) => entry.outcome));
  const values = [];
  let cumulative = 0;
  const entryMap = new Map(distribution.map((entry) => [entry.outcome, entry.probability]));
  for (const outcome of visible) {
    const probability = entryMap.get(outcome) ?? 0;
    if (mode === "cdf") {
      cumulative += probability;
      values.push({ outcome: asLabel(outcome), probability: cumulative });
    } else {
      values.push({ outcome: asLabel(outcome), probability: Math.max(0, 100 - cumulative - probability) });
      cumulative += probability;
    }
  }
  return Plot.plot(
    plotOptions(panel, {
      y: { grid: true, label: probabilityLabel(panel, "Probability (%)") },
      x: { label: panel.x_label ?? "Outcome" },
      marks: [
        Plot.ruleY([0]),
        Plot.lineY(values, { x: "outcome", y: "probability", stroke: PALETTE[0], marker: true, tip: true }),
      ],
    }),
  );
}

function renderScalarSweep(panel) {
  const Plot = getPlot();
  const data = buildScalarSweepData(panel.payload);
  const axis = resultAxes(panel.payload)[0];
  return Plot.plot(
    plotOptions(panel, {
      y: { grid: true, label: panel.y_label ?? "Value" },
      x: { label: panel.x_label ?? axis?.name ?? "Sweep 1" },
      marks: [
        Plot.ruleY([0]),
        Plot.lineY(data, { x: "x", y: "value", stroke: PALETTE[0], marker: true, tip: true }),
      ],
    }),
  );
}

function renderDistributionSweep(panel) {
  const Plot = getPlot();
  const axis = resultAxes(panel.payload)[0];
  return Plot.plot(
    plotOptions(panel, {
      color: { scheme: "YlOrBr", legend: true, label: probabilityLabel(panel, "Probability (%)") },
      x: { label: panel.x_label ?? axis?.name ?? "Sweep 1" },
      y: { label: panel.y_label ?? "Outcome" },
      marks: [
        Plot.cell(buildDistributionSweepData(panel.payload), {
          x: "x",
          y: "outcome",
          fill: "probability",
          inset: 0.5,
          title: (d) => `${panel.x_label ?? axis?.name ?? "Sweep 1"}: ${d.x}\nOutcome: ${d.outcome}\n${probabilityLabel(panel, "Probability (%)")}: ${d.probability}`,
          tip: true,
        }),
      ],
    }),
  );
}

function renderScalarHeatmap(panel) {
  const Plot = getPlot();
  const [yAxis, xAxis] = resultAxes(panel.payload);
  return Plot.plot(
    plotOptions(panel, {
      color: { scheme: "BuGn", legend: true, label: panel.y_label ?? "Value" },
      x: { label: panel.x_label ?? xAxis?.name ?? "Sweep 2" },
      y: { label: panel.y_label ?? yAxis?.name ?? "Sweep 1" },
      marks: [
        Plot.cell(buildScalarHeatmapData(panel.payload), {
          x: "x",
          y: "y",
          fill: "value",
          inset: 0.5,
          title: (d) => `${panel.x_label ?? xAxis?.name ?? "Sweep 2"}: ${d.x}\n${panel.y_label ?? yAxis?.name ?? "Sweep 1"}: ${d.y}\nValue: ${d.value}`,
          tip: true,
        }),
      ],
    }),
  );
}

function renderCompareScalar(panel) {
  const Plot = getPlot();
  const axis = resultAxes(panel.payload?.[0]?.result)[0];
  const data = buildCompareScalarData(panel);
  return Plot.plot(
    plotOptions(panel, {
      color: { legend: true, range: PALETTE },
      y: { grid: true, label: panel.y_label ?? "Value" },
      x: { label: panel.x_label ?? axis?.name ?? "Sweep 1" },
      marks: [
        Plot.ruleY([0]),
        Plot.lineY(data, { x: "x", y: "value", stroke: "label", marker: true, tip: true }),
      ],
    }),
  );
}

function renderCompareUnswept(panel) {
  const Plot = getPlot();
  return Plot.plot(
    plotOptions(panel, {
      color: { legend: true, range: PALETTE },
      y: { grid: true, label: probabilityLabel(panel, "Probability (%)") },
      x: { label: panel.x_label ?? "Outcome" },
      marks: [
        Plot.ruleY([0]),
        Plot.lineY(buildStepSeries(panel), {
          x: "outcome",
          y: "probability",
          stroke: "label",
          marker: true,
          tip: true,
        }),
      ],
    }),
  );
}

function renderDiff(panel) {
  const Plot = getPlot();
  const [left, right] = panel.payload ?? [];
  const axis = resultAxes(left?.result)[0];
  const data = buildDiffData(panel);
  return Plot.plot(
    plotOptions(panel, {
      y: { grid: true, label: panel.y_label ?? `${left?.label ?? "A"} - ${right?.label ?? "B"}` },
      x: { label: panel.x_label ?? axis?.name ?? "Sweep 1" },
      marks: [
        Plot.ruleY([0]),
        Plot.areaY(data, { x: "x", y: "value", fill: PALETTE[0], fillOpacity: 0.18 }),
        Plot.lineY(data, { x: "x", y: "value", stroke: PALETTE[0], marker: true, tip: true }),
      ],
    }),
  );
}

function renderCompareFaceted(panel) {
  const container = document.createElement("div");
  container.className = "report-panel-grid report-panel-grid--stack";
  for (const entry of panel.payload ?? []) {
    const subpanel = autoPanelFromResult(entry.label, entry.result, panel);
    container.appendChild(renderPanel(subpanel));
  }
  return container;
}

function renderBestStrategy(panel) {
  const Plot = getPlot();
  const result = panel.payload;
  const axes = resultAxes(result);
  const strategyAxis = axes[0];
  const conditionAxis = axes[1];
  const { winnerRows, marginRows } = bestStrategyData(result);
  const container = document.createElement("div");
  container.className = "report-panel-grid report-panel-grid--stack";
  appendPlot(
    container,
    Plot.plot(
      plotOptions(panel, {
        height: 180,
        color: { legend: true, range: PALETTE.slice(0, Math.max(strategyAxis?.values?.length ?? 2, 2)) },
        x: { label: panel.x_label ?? conditionAxis?.name ?? "Condition" },
        y: { label: "Winner" },
        marks: [
          Plot.cell(winnerRows, {
            x: "x",
            y: "y",
            fill: "strategy",
            inset: 0.5,
            title: (d) => `${panel.x_label ?? conditionAxis?.name ?? "Condition"}: ${d.x}\nWinner: ${d.strategy}`,
            tip: true,
          }),
        ],
      }),
    ),
  );
  appendPlot(
    container,
    Plot.plot(
      plotOptions(panel, {
        height: 240,
        y: { grid: true, label: "Margin" },
        x: { label: panel.x_label ?? conditionAxis?.name ?? "Condition" },
        marks: [
          Plot.ruleY([0]),
          Plot.areaY(marginRows, { x: "x", y: "value", fill: PALETTE[0], fillOpacity: 0.18 }),
          Plot.lineY(marginRows, { x: "x", y: "value", stroke: PALETTE[0], marker: true, tip: true }),
        ],
      }),
    ),
  );
  return container;
}

export function renderPanel(panel) {
  const Plot = getPlot();
  const wrapper = document.createElement("div");
  wrapper.className = "chart-stack report-panel";
  renderPanelCaption(panel, wrapper);

  if (!Plot) {
    const fallback = document.createElement("div");
    fallback.className = "chart-empty";
    fallback.textContent = "Observable Plot is not available.";
    wrapper.appendChild(fallback);
    return wrapper;
  }

  let plotNode = null;
  if (panel.kind === "unswept_distribution") {
    plotNode = renderUnswept(panel);
  } else if (panel.kind === "cdf" || panel.kind === "surv") {
    plotNode = renderCurve(panel, panel.kind);
  } else if (panel.kind === "scalar_sweep") {
    plotNode = renderScalarSweep(panel);
  } else if (panel.kind === "distribution_sweep") {
    plotNode = renderDistributionSweep(panel);
  } else if (panel.kind === "scalar_heatmap") {
    plotNode = renderScalarHeatmap(panel);
  } else if (panel.kind === "compare_scalar") {
    plotNode = renderCompareScalar(panel);
  } else if (panel.kind === "compare_unswept") {
    plotNode = renderCompareUnswept(panel);
  } else if (panel.kind === "compare_faceted") {
    plotNode = renderCompareFaceted(panel);
  } else if (panel.kind === "diff") {
    plotNode = renderDiff(panel);
  } else if (panel.kind === "best_strategy") {
    plotNode = renderBestStrategy(panel);
  }

  if (plotNode instanceof Element) {
    if (plotNode.classList.contains("report-panel-grid")) {
      wrapper.appendChild(plotNode);
    } else {
      appendPlot(wrapper, plotNode);
    }
  } else {
    const unsupported = document.createElement("div");
    unsupported.className = "chart-empty";
    unsupported.textContent = `Unsupported chart payload: ${panel.kind}`;
    wrapper.appendChild(unsupported);
  }

  appendNotes(wrapper, panelNotes(panel));
  return wrapper;
}

export function flattenReportPanels(reportPayloads) {
  const panels = [];
  for (const payload of reportPayloads ?? []) {
    const report = payload?.report ?? payload;
    if (!report) {
      continue;
    }
    if (report.hero) {
      panels.push(report.hero);
    }
    for (const row of report.rows ?? []) {
      panels.push(...row);
    }
  }
  return panels;
}

export function renderStackedReports(reportPayloads, container) {
  container.replaceChildren();
  const panels = flattenReportPanels(reportPayloads);
  for (const panel of panels) {
    container.appendChild(renderPanel(panel));
  }
  return panels.length > 0;
}

export function renderLegacyCharts(charts, container) {
  const Plot = getPlot();
  container.replaceChildren();
  const items = Array.isArray(charts) ? charts : charts ? [charts] : [];
  for (const chart of items) {
    const wrapper = document.createElement("div");
    wrapper.className = "chart-stack report-panel";
    renderPanelCaption(
      {
        title: chart.title,
        kind: chart.kind,
      },
      wrapper,
    );
    if (!Plot) {
      const fallback = document.createElement("div");
      fallback.className = "chart-empty";
      fallback.textContent = "Observable Plot is not available.";
      wrapper.appendChild(fallback);
      container.appendChild(wrapper);
      continue;
    }
    let plot = null;
    if (chart.kind === "bar") {
      const data = chart.categories.map((category, index) => ({
        x: asLabel(category),
        value: chart.series?.[0]?.values?.[index] ?? 0,
      }));
      plot = Plot.plot(
        plotOptions(chart, {
          y: { grid: true, label: chart.spec?.y_label ?? "Value" },
          x: { label: chart.spec?.x_label ?? "Category" },
          marks: [Plot.ruleY([0]), Plot.barY(data, { x: "x", y: "value", fill: PALETTE[0], tip: true })],
        }),
      );
    } else if (chart.kind === "line") {
      const data = chart.categories.map((category, index) => ({
        x: asLabel(category),
        value: chart.series?.[0]?.values?.[index] ?? 0,
      }));
      plot = Plot.plot(
        plotOptions(chart, {
          y: { grid: true, label: chart.spec?.y_label ?? "Value" },
          x: { label: chart.spec?.x_label ?? "Category" },
          marks: [Plot.ruleY([0]), Plot.lineY(data, { x: "x", y: "value", stroke: PALETTE[0], marker: true, tip: true })],
        }),
      );
    } else if (chart.kind === "heatmap_distribution" || chart.kind === "heatmap_scalar") {
      const rows = [];
      for (let rowIndex = 0; rowIndex < (chart.y_values ?? []).length; rowIndex += 1) {
        for (let columnIndex = 0; columnIndex < (chart.x_values ?? []).length; columnIndex += 1) {
          rows.push({
            x: asLabel(chart.x_values[columnIndex]),
            y: asLabel(chart.y_values[rowIndex]),
            value: chart.matrix?.[rowIndex]?.[columnIndex] ?? 0,
          });
        }
      }
      plot = Plot.plot(
        plotOptions(chart, {
          color: { legend: true, scheme: chart.kind === "heatmap_scalar" ? "BuGn" : "YlOrBr", label: chart.color_label ?? "Value" },
          x: { label: chart.spec?.x_label ?? "X" },
          y: { label: chart.spec?.y_label ?? "Y" },
          marks: [Plot.cell(rows, { x: "x", y: "y", fill: "value", inset: 0.5, tip: true })],
        }),
      );
    }
    if (plot) {
      appendPlot(wrapper, plot);
    }
    container.appendChild(wrapper);
  }
  return items.length > 0;
}

export function saveReports(reportPayloads) {
  if (!Array.isArray(reportPayloads) || reportPayloads.length === 0) {
    globalThis.localStorage.removeItem(REPORT_STORAGE_KEY);
    return;
  }
  globalThis.localStorage.setItem(REPORT_STORAGE_KEY, JSON.stringify(reportPayloads));
}

export function loadSavedReports() {
  try {
    const raw = globalThis.localStorage.getItem(REPORT_STORAGE_KEY);
    if (!raw) {
      return [];
    }
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch (_error) {
    return [];
  }
}

export function renderReportCollection(reportPayloads, container) {
  container.replaceChildren();
  const reports = Array.isArray(reportPayloads) ? reportPayloads : [];
  for (const payload of reports) {
    const report = payload?.report ?? payload;
    if (!report) {
      continue;
    }
    const section = document.createElement("section");
    section.className = "report-section";

    if (report.title) {
      const title = document.createElement("h1");
      title.className = "report-title";
      title.textContent = report.title;
      section.appendChild(title);
    }

    if (report.hero) {
      const hero = document.createElement("div");
      hero.className = "report-grid report-grid--single";
      hero.appendChild(renderPanel(report.hero));
      section.appendChild(hero);
    }

    for (const row of report.rows ?? []) {
      const rowNode = document.createElement("div");
      rowNode.className = row.length > 1 ? "report-grid report-grid--pair" : "report-grid report-grid--single";
      rowNode.replaceChildren(...row.map((panel) => renderPanel(panel)));
      section.appendChild(rowNode);
    }

    if (Array.isArray(report.notes) && report.notes.length > 0) {
      const notes = document.createElement("div");
      notes.className = "report-notes";
      notes.replaceChildren(
        ...report.notes.map((noteLine) => {
          const paragraph = document.createElement("p");
          paragraph.textContent = noteLine;
          return paragraph;
        }),
      );
      section.appendChild(notes);
    }

    container.appendChild(section);
  }
  return reports.length > 0;
}

export { REPORT_STORAGE_KEY };
