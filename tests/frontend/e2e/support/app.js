const EMPTY_SCRIPT = "";

const FAKE_ACE_SCRIPT = `
(() => {
  const state = {
    completers: [],
    editors: [],
    lastCompletions: [],
  };

  function sourceIndexFromPosition(source, position) {
    const lines = source.split("\\n");
    let index = 0;
    for (let row = 0; row < position.row; row += 1) {
      index += (lines[row] ?? "").length + 1;
    }
    return index + position.column;
  }

  function endPosition(source) {
    const lines = source.split("\\n");
    return {
      row: Math.max(lines.length - 1, 0),
      column: lines[lines.length - 1]?.length ?? 0,
    };
  }

  function ensurePopup() {
    let popup = document.querySelector(".ace_autocomplete");
    if (!popup) {
      popup = document.createElement("div");
      popup.className = "ace_autocomplete";
      popup.hidden = true;
      document.body.appendChild(popup);
    }
    return popup;
  }

  function renderPopup() {
    const popup = ensurePopup();
    popup.replaceChildren(
      ...state.lastCompletions.map((completion) => {
        const row = document.createElement("div");
        row.className = "ace_autocomplete-line";
        row.textContent = completion.caption;
        return row;
      }),
    );
    popup.hidden = state.lastCompletions.length === 0;
  }

  class Range {
    constructor(startRow, startColumn, endRow, endColumn) {
      this.start = { row: startRow, column: startColumn };
      this.end = { row: endRow, column: endColumn };
    }
  }

  class FakeSession {
    constructor(editor) {
      this.editor = editor;
      this.value = "";
      this.changeHandlers = [];
    }

    setValue(value) {
      this.value = String(value);
      this.changeHandlers.forEach((handler) => handler());
    }

    getValue() {
      return this.value;
    }

    setMode() {}

    setTabSize() {}

    setUseSoftTabs() {}

    on(eventName, handler) {
      if (eventName === "change") {
        this.changeHandlers.push(handler);
      }
    }
  }

  class FakeEditor {
    constructor(container) {
      this.container = container;
      this.session = new FakeSession(this);
      this.cursor = { row: 0, column: 0 };
      this.eventHandlers = new Map();
      this.commands = {
        byName: new Map(),
        addCommand: (command) => {
          this.commands.byName.set(command.name, command);
        },
      };
    }

    setTheme() {}

    setOptions() {}

    clearSelection() {}

    resize() {}

    on(eventName, handler) {
      const handlers = this.eventHandlers.get(eventName) ?? [];
      handlers.push(handler);
      this.eventHandlers.set(eventName, handlers);
    }

    getValue() {
      return this.session.getValue();
    }

    setCursorPosition(position) {
      this.cursor = position;
    }

    execCommand(name) {
      if (name === "startAutocomplete") {
        this.startAutocomplete();
        return;
      }
      const command = this.commands.byName.get(name);
      if (command) {
        command.exec(this);
      }
    }

    startAutocomplete() {
      const completer = state.completers[0];
      if (!completer) {
        return;
      }
      const position = this.cursor ?? endPosition(this.getValue());
      completer.getCompletions(this, this.session, position, "", (_error, completions) => {
        state.lastCompletions = completions ?? [];
        renderPopup();
      });
    }
  }

  window.__fakeAce = {
    setValue(value) {
      const editor = state.editors[0];
      editor.session.setValue(value);
      editor.setCursorPosition(endPosition(String(value)));
    },
    getValue() {
      return state.editors[0]?.getValue() ?? "";
    },
    setCursor(position) {
      state.editors[0]?.setCursorPosition(position);
    },
    startAutocomplete() {
      state.editors[0]?.startAutocomplete();
    },
    applyCompletion(index = 0) {
      const editor = state.editors[0];
      const completion = state.lastCompletions[index];
      if (!editor || !completion) {
        return;
      }
      const currentValue = editor.getValue();
      const start = sourceIndexFromPosition(currentValue, completion.range?.start ?? editor.cursor);
      const end = sourceIndexFromPosition(currentValue, completion.range?.end ?? editor.cursor);
      const nextValue = currentValue.slice(0, start) + completion.value + currentValue.slice(end);
      editor.session.setValue(nextValue);
      editor.setCursorPosition(endPosition(nextValue));
      renderPopup();
    },
    getCompletions() {
      return state.lastCompletions.map((completion) => completion.caption);
    },
  };

  window.ace = {
    define() {},
    require(name) {
      if (name === "ace/ext/language_tools") {
        return {
          setCompleters(completers) {
            state.completers = completers;
          },
        };
      }
      if (name === "ace/range") {
        return { Range };
      }
      return {};
    },
    edit(container) {
      const editor = new FakeEditor(container);
      state.editors.push(editor);
      return editor;
    },
  };
})();
`;

const DEFAULT_RESPONSES = {
  init: {
    ok: true,
    result: [{ label: "attack_bonus", type: "symbol" }],
  },
  listSamples: {
    ok: true,
    result: [
      {
        group: "Examples/00_basic",
        kind: "sample",
        name: "Introduction",
        path: "00_basic/00_introduction.dice",
      },
    ],
  },
  evaluate: {
    ok: true,
    result: {
      ok: true,
      text: "Evaluation complete",
      result: {
        type: "chart",
        name: "damage",
      },
      render: {
        kind: "bar",
        title: "Damage by Level",
        categories: ["1", "2", "3"],
        series: [
          {
            name: "damage",
            values: [1, 2, 3],
          },
        ],
        spec: {
          kind: "bar",
          x_label: "Level",
          y_label: "Damage",
        },
      },
    },
  },
  complete: {
    ok: true,
    result: {
      from: 0,
      to: 3,
      options: [
        {
          label: "attack_bonus",
          type: "symbol",
          detail: "number",
        },
        {
          label: "target_ac",
          type: "symbol",
          detail: "series",
        },
      ],
    },
  },
  loadSample: {
    ok: true,
    result: {
      source_path: "00_basic/00_introduction.dice",
      files: {
        "00_basic/00_introduction.dice": 'import "./support"\ndamage = 2d6',
        "00_basic/support.dice": "bonus = 3",
      },
    },
  },
};

function mergeResponses(overrides = {}) {
  return {
    ...DEFAULT_RESPONSES,
    ...overrides,
  };
}

export async function installAppMocks(page, options = {}) {
  const responses = mergeResponses(options.responses);
  const useAce = options.ace === "fake";

  await page.route("https://fonts.googleapis.com/**", async (route) => {
    await route.fulfill({ status: 204, body: "" });
  });
  await page.route("https://fonts.gstatic.com/**", async (route) => {
    await route.fulfill({ status: 204, body: "" });
  });
  await page.route("https://cdnjs.cloudflare.com/ajax/libs/ace/**/ace.js", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/javascript",
      body: useAce ? FAKE_ACE_SCRIPT : EMPTY_SCRIPT,
    });
  });
  await page.route("https://cdnjs.cloudflare.com/ajax/libs/ace/**/ext-language_tools.min.js", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/javascript",
      body: EMPTY_SCRIPT,
    });
  });

  await page.addInitScript(
    ({ workerResponses, savePickerName }) => {
      const responseState = { ...workerResponses };

      function nextResponse(method) {
        const value = responseState[method];
        if (Array.isArray(value)) {
          if (value.length === 0) {
            return { ok: true, result: null };
          }
          if (value.length === 1) {
            return value[0];
          }
          return value.shift();
        }
        return value ?? { ok: true, result: null };
      }

      window.__diceTest = {
        savedFiles: {},
        copiedText: null,
        workerCalls: [],
      };

      class FakeWorker {
        constructor() {
          this.listeners = [];
        }

        addEventListener(type, listener) {
          if (type === "message") {
            this.listeners.push(listener);
          }
        }

        postMessage(message) {
          window.__diceTest.workerCalls.push(message);
          const response = nextResponse(message.method);
          window.setTimeout(() => {
            this.listeners.forEach((listener) => {
              listener({
                data: {
                  id: message.id,
                  ...(response.ok === false
                    ? {
                        ok: false,
                        error: response.error ?? { message: "Worker request failed" },
                      }
                    : {
                        ok: true,
                        result: response.result,
                      }),
                },
              });
            });
          }, 0);
        }
      }

      window.Worker = FakeWorker;

      if (!navigator.clipboard) {
        Object.defineProperty(navigator, "clipboard", {
          configurable: true,
          value: {
            writeText: async (text) => {
              window.__diceTest.copiedText = text;
            },
          },
        });
      } else {
        navigator.clipboard.writeText = async (text) => {
          window.__diceTest.copiedText = text;
        };
      }

      if (savePickerName) {
        window.showSaveFilePicker = async () => ({
          name: savePickerName,
          async createWritable() {
            return {
              async write(source) {
                window.__diceTest.savedFiles[savePickerName] = source;
              },
              async close() {},
            };
          },
        });
      }
    },
    {
      workerResponses: responses,
      savePickerName: options.savePickerName ?? null,
    },
  );
}

export async function openApp(page, options = {}) {
  await installAppMocks(page, options);
  await page.goto("/");
  await page.waitForFunction(() => {
    const chartReady = document.querySelector("#chart-output")?.childElementCount > 0;
    const rawReady = (document.querySelector("#text-output")?.textContent ?? "").length > 0;
    const diagnosticVisible = document.querySelector("#diagnostic-panel")?.hidden === false;
    return chartReady || rawReady || diagnosticVisible;
  });
}
