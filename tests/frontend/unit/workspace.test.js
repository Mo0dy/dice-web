import { describe, expect, it } from "vitest";

import {
  createUniquePath,
  createWorkspace,
  createWorkspaceFromSnapshot,
  importLinkAtPosition,
  normalizeFileName,
  normalizeWorkspacePath,
  workspacePathForImport,
} from "../../../src/workspace.js";

describe("workspace helpers", () => {
  it("normalizes workspace snapshots into a valid active workspace", () => {
    const workspace = createWorkspaceFromSnapshot({
      files: {
        "notes/readme.dice": "result = 1",
      },
      entryPath: "main.dice",
      activeFilePath: "notes/readme.dice",
      openFiles: ["missing.dice", "notes/readme.dice"],
      samplePath: "00_basic/00_introduction.dice",
    });

    expect(workspace).toEqual({
      samplePath: "00_basic/00_introduction.dice",
      files: {
        "notes/readme.dice": "result = 1",
        "main.dice": "",
      },
      entryPath: "main.dice",
      openFiles: ["main.dice", "notes/readme.dice"],
      activeFilePath: "notes/readme.dice",
    });
  });

  it("creates stable unique names when paths collide", () => {
    const takenPaths = new Set(["main.dice", "main-2.dice", "notes/output.txt"]);

    expect(createUniquePath("main.dice", takenPaths)).toBe("main-3.dice");
    expect(createUniquePath("notes/output.txt", takenPaths)).toBe("notes/output-2.txt");
    expect(createUniquePath("fresh.dice", takenPaths)).toBe("fresh.dice");
  });

  it("normalizes file names and preserves the original directory on rename", () => {
    expect(normalizeFileName(" report ")).toBe("report.dice");
    expect(normalizeFileName("nested/path/example")).toBe("nested/path/example.dice");
    expect(normalizeFileName("renamed", { preserveDirectory: true, basePath: "party/main.dice" })).toBe(
      "party/renamed.dice",
    );
    expect(normalizeFileName("   ")).toBeNull();
  });

  it("resolves import paths inside the workspace and rejects upward escapes", () => {
    expect(normalizeWorkspacePath("./party/./rules/../main.dice")).toBe("party/main.dice");
    expect(normalizeWorkspacePath("../../escape.dice")).toBeNull();
    expect(workspacePathForImport("./support", "party/main.dice")).toBe("party/support.dice");
    expect(workspacePathForImport("../shared/table", "party/main.dice")).toBe("shared/table.dice");
    expect(workspacePathForImport("std:dnd/core", "party/main.dice")).toBe("dnd/core.dice");
  });

  it("detects import links at a given cursor position", () => {
    const source = 'import "std:dnd/core"\nimport "./support"\nvalue = 1';

    expect(importLinkAtPosition(source, 0, 9)).toEqual({
      importPath: "std:dnd/core",
      startColumn: 8,
      endColumn: 20,
    });
    expect(importLinkAtPosition(source, 1, 10)).toEqual({
      importPath: "./support",
      startColumn: 8,
      endColumn: 17,
    });
    expect(importLinkAtPosition(source, 2, 1)).toBeNull();
  });

  it("keeps the entry file visible when constructing a workspace", () => {
    const workspace = createWorkspace({
      files: {
        "main.dice": "entry = 1",
        "notes.dice": "note = 2",
      },
      entryPath: "main.dice",
      openFiles: ["notes.dice"],
    });

    expect(workspace.openFiles[0]).toBe("main.dice");
    expect(workspace.activeFilePath).toBe("main.dice");
  });
});
