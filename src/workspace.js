export function createWorkspace({ files, entryPath, samplePath = null, activeFilePath = null, openFiles = null }) {
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

export function createWorkspaceFromSnapshot(snapshot) {
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

export function basename(path) {
  const parts = path.split("/");
  return parts[parts.length - 1];
}

export function dirname(path) {
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

export function createUniquePath(path, takenPaths = new Set()) {
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

export function isUnnamedPath(path) {
  return /^untitled(?:-\d+)?(?:\.dice)?$/i.test(basename(path));
}

export function normalizeFileName(name, { preserveDirectory = false, basePath = "" } = {}) {
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

export function normalizeWorkspacePath(path) {
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

export function workspacePathForImport(importPath, sourcePath) {
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

export function importLinkAtPosition(source, row, column) {
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
