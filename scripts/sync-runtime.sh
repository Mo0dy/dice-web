#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_DIR="$ROOT_DIR/dice"
RUNTIME_DIR="$ROOT_DIR/runtime"
BRIDGE_SOURCE="$ROOT_DIR/webbridge.py"
VIEWER_SOURCE="$ROOT_DIR/viewer.py"

RUNTIME_FILES=(
  diagnostics.py
  diceengine.py
  diceparser.py
  executor.py
  interpreter.py
  jsonrenderer.py
  lexer.py
  renderplan.py
  resultjson.py
  syntaxtree.py
)

rm -rf "$RUNTIME_DIR"
mkdir -p "$RUNTIME_DIR/stdlib" "$RUNTIME_DIR/examples"

for relative_path in "${RUNTIME_FILES[@]}"; do
  cp "$SOURCE_DIR/$relative_path" "$RUNTIME_DIR/$relative_path"
done

cp "$BRIDGE_SOURCE" "$RUNTIME_DIR/webbridge.py"
cp "$VIEWER_SOURCE" "$RUNTIME_DIR/viewer.py"

cp -R "$SOURCE_DIR/stdlib/." "$RUNTIME_DIR/stdlib/"
cp -R "$SOURCE_DIR/examples/." "$RUNTIME_DIR/examples/"

cd "$RUNTIME_DIR"
python - <<'PY'
import json
from pathlib import Path

root = Path(".")
files = sorted(
    str(path.relative_to(root)).replace("\\", "/")
    for path in root.rglob("*")
    if path.is_file() and path.name != "manifest.json"
)
(root / "manifest.json").write_text(
    json.dumps({"files": files}, indent=2) + "\n",
    encoding="utf-8",
)
PY

echo "Runtime synced into $RUNTIME_DIR"
