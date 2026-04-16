# dice-web

Static browser playground for the `dice` language. The site runs the runtime in a Pyodide web worker and renders charts with plain browser UI primitives instead of Matplotlib.

## Repo shape

- `dice/`
  Git submodule with the source runtime.
- `webbridge.py`
  Repo-local adapter exposing the stable browser-facing API over the vendored runtime.
- `runtime/`
  Copied browser runtime files served statically by the site.
- `src/`
  Browser app and worker.
- `styles/`
  Site styles.

## Local run

1. Sync the browser runtime:

   ```bash
   ./scripts/sync-runtime.sh
   ```

2. Serve the repo root as a static site:

   ```bash
   python -m http.server 8000
   ```

3. Open [http://localhost:8000](http://localhost:8000).

## Current v1 surface

- Ace-based editor
- Pyodide runtime in a dedicated worker
- Structured JSON evaluation payloads through the repo-local `webbridge.py`
- Bar, line, and heatmap rendering in the browser
- Bundled D&D sample picker with relative-import support
- Shareable URL state
- Local saved snippets

## Runtime sync

The worker loads only the copied browser runtime from `runtime/`. Re-run `./scripts/sync-runtime.sh` after changing either the vendored `dice` runtime files, the repo-local `webbridge.py`, or the bundled samples, then commit the refreshed `runtime/` directory with those changes.
