const PYODIDE_BASE_URL = "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/";

let bootPromise = null;
let pyodide = null;

function runtimeUrl(relativePath) {
  return new URL(`../runtime/${relativePath}`, self.location).toString();
}

function ensureDirectory(path) {
  const segments = path.split("/").filter(Boolean);
  let current = "";
  for (const segment of segments) {
    current += `/${segment}`;
    if (pyodide.FS.analyzePath(current).exists) {
      continue;
    }
    pyodide.FS.mkdir(current);
  }
}

async function loadText(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to fetch ${url}: ${response.status}`);
  }
  return response.text();
}

async function callBridge(functionName, args) {
  const argsJson = JSON.stringify(args ?? {});
  const payload = await pyodide.runPythonAsync(`
import json
import webbridge

_args = json.loads(${JSON.stringify(argsJson)})
_function = getattr(webbridge, ${JSON.stringify(functionName)})
json.dumps(_function(**_args))
  `);
  return JSON.parse(payload);
}

async function initializeRuntime() {
  importScripts(`${PYODIDE_BASE_URL}pyodide.js`);
  pyodide = await loadPyodide({ indexURL: PYODIDE_BASE_URL });

  const manifestResponse = await fetch(runtimeUrl("manifest.json"));
  if (!manifestResponse.ok) {
    throw new Error("Missing runtime/manifest.json. Run scripts/sync-runtime.sh first.");
  }
  const manifest = await manifestResponse.json();

  ensureDirectory("/dice_runtime");
  for (const relativePath of manifest.files) {
    const targetPath = `/dice_runtime/${relativePath}`;
    const parentPath = targetPath.split("/").slice(0, -1).join("/");
    ensureDirectory(parentPath);
    const sourceText = await loadText(runtimeUrl(relativePath));
    pyodide.FS.writeFile(targetPath, sourceText, { encoding: "utf8" });
  }

  await pyodide.runPythonAsync(`
import sys
if "/dice_runtime" not in sys.path:
    sys.path.insert(0, "/dice_runtime")
import webbridge
  `);

  return callBridge("list_symbols", {});
}

async function ensureBooted() {
  if (!bootPromise) {
    bootPromise = initializeRuntime();
  }
  return bootPromise;
}

async function handleEvaluate(params) {
  await ensureBooted();
  const settings = {
    roundlevel: 6,
    probability_mode: "raw",
    source_path: "main.dice",
    ...(params.settings ?? {}),
  };
  const payload = await callBridge("evaluate", {
    source: params.source,
    files: params.files ?? null,
    settings,
  });
  if (payload.ok && (!payload.reports || payload.reports.length === 0)) {
    payload.render = await callBridge("render_payload", {
      result: payload.result,
      settings: { probability_mode: "percent" },
    });
  }
  return payload;
}

async function handleComplete(params) {
  await ensureBooted();
  return callBridge("complete", {
    source: params.source,
    cursor: params.cursor,
    files: params.files ?? null,
    settings: {
      source_path: "main.dice",
      ...(params.settings ?? {}),
    },
  });
}

async function handleListSamples() {
  await ensureBooted();
  return callBridge("list_samples", {});
}

async function handleLoadSample(params) {
  await ensureBooted();
  return callBridge("load_sample", {
    path: params.path,
  });
}

self.addEventListener("message", async (event) => {
  const { id, method, params } = event.data;
  try {
    let result;
    if (method === "init") {
      result = await ensureBooted();
    } else if (method === "evaluate") {
      result = await handleEvaluate(params ?? {});
    } else if (method === "complete") {
      result = await handleComplete(params ?? {});
    } else if (method === "listSamples") {
      result = await handleListSamples();
    } else if (method === "loadSample") {
      result = await handleLoadSample(params ?? {});
    } else if (method === "listSymbols") {
      result = await ensureBooted();
    } else {
      throw new Error(`Unknown worker method: ${method}`);
    }
    self.postMessage({ id, ok: true, result });
  } catch (error) {
    self.postMessage({
      id,
      ok: false,
      error: {
        message: error instanceof Error ? error.message : String(error),
      },
    });
  }
});
