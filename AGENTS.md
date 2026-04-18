# Repository Notes

- Keep the site GitHub Pages compatible. Anything required at runtime must be served as checked-in static assets from the repository; do not depend on `node_modules` or a build step existing on Pages.
- When adding browser libraries, prefer vendored local bundles under a static path over CDN-only integration.
- The browser runtime is served from `runtime/`; update it with `scripts/sync-runtime.sh` after changing the vendored dice runtime or `webbridge.py`.
