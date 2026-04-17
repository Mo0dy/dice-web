import { expect, test } from "@playwright/test";

import { openApp } from "./support/app.js";

test("restores the current workspace after a reload", async ({ page }) => {
  await openApp(page);

  const editor = page.getByRole("textbox", { name: "dice editor" });
  await editor.fill("damage = 2d6 + 3");
  await page.waitForFunction(() => {
    return window.localStorage.getItem("dice-web:workspace")?.includes("damage = 2d6 + 3");
  });

  await page.reload();

  await expect(page.getByRole("textbox", { name: "dice editor" })).toHaveValue("damage = 2d6 + 3");
});

test("loads uploaded files into tabs and makes the first file active", async ({ page }) => {
  await openApp(page);

  await page.locator("#file-input").setInputFiles([
    {
      name: "alpha.dice",
      mimeType: "text/plain",
      buffer: Buffer.from("alpha = 1"),
    },
    {
      name: "beta.dice",
      mimeType: "text/plain",
      buffer: Buffer.from("beta = 2"),
    },
  ]);

  await expect(page.getByRole("button", { name: "alpha.dice", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "beta.dice", exact: true })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "dice editor" })).toHaveValue("alpha = 1");
});

test("saves the active file through the file picker path", async ({ page }) => {
  await openApp(page, {
    savePickerName: "session.dice",
  });

  const editor = page.getByRole("textbox", { name: "dice editor" });
  await editor.fill("result = 4d6");
  await page.getByRole("button", { name: "Save File" }).click();

  await expect(page.getByRole("button", { name: "session.dice" })).toBeVisible();
  await expect.poll(async () => {
    return page.evaluate(() => window.__diceTest.savedFiles["session.dice"]);
  }).toBe("result = 4d6");
});

test("loads a bundled sample and swaps the active file", async ({ page }) => {
  await openApp(page);

  await page.getByRole("button", { name: "Load Sample" }).click();
  await page.selectOption("#sample-dialog-select", "samples/heatmap");
  await page.locator("#sample-dialog-confirm").click();

  await expect(page.getByTitle("samples/demo/main.dice", { exact: true })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "dice editor" })).toHaveValue('import "./support"\ndamage = 2d6');
});

test("renders successful output into chart, raw, and json panels", async ({ page }) => {
  await openApp(page);

  await expect(page.locator("#chart-output svg")).toHaveCount(1);
  await page.getByRole("tab", { name: "Raw" }).click();
  await expect(page.locator("#text-output")).toContainText("Evaluation complete");
  await page.getByRole("tab", { name: "Json" }).click();
  await expect(page.locator("#json-output")).toContainText('"type": "chart"');
});

test("shows diagnostics when evaluation fails", async ({ page }) => {
  await openApp(page, {
    responses: {
      evaluate: {
        ok: true,
        result: {
          ok: false,
          error: {
            formatted: "Parse error at line 1",
          },
        },
      },
    },
  });

  await expect(page.locator("#diagnostic-panel")).toBeVisible();
  await expect(page.locator("#diagnostic-output")).toContainText("Parse error at line 1");
});

test("requests autocomplete options and applies the selected completion", async ({ page }) => {
  await openApp(page, {
    ace: "fake",
    responses: {
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
          ],
        },
      },
    },
  });

  await page.evaluate(() => {
    window.__fakeAce.setValue("att");
    window.__fakeAce.startAutocomplete();
  });

  await expect(page.locator(".ace_autocomplete-line")).toContainText(["attack_bonus"]);

  await page.evaluate(() => {
    window.__fakeAce.applyCompletion(0);
  });

  await expect.poll(async () => {
    return page.evaluate(() => window.__fakeAce.getValue());
  }).toBe("attack_bonus");
});
