import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { THEME_STORAGE_KEY } from "@/lib/theme";

const SRC = resolve(__dirname, "..");
const layout = readFileSync(resolve(SRC, "app/layout.tsx"), "utf8");

describe("the no-flash theme script", () => {
  it("is inline and synchronous in <head>", () => {
    // A `useEffect` runs after the browser has already painted the light
    // ground, so a dark-mode user gets a lavender flash on every navigation.
    expect(layout).toContain("<head>");
    expect(layout).toMatch(/<script\s+dangerouslySetInnerHTML/);
    expect(layout).not.toMatch(/<script[^>]*\bdefer\b/);
    expect(layout).not.toMatch(/<script[^>]*\basync\b/);
  });

  it("takes the storage key from a module that is not client-only", () => {
    // This is the bug worth pinning. The key first lived in ThemeToggle.tsx,
    // which carries "use client"; its exports do not survive into the server
    // bundle, so the script was serialized into the HTML as
    // `localStorage.getItem(undefined)` - a silent failure that type-checked,
    // built, passed every test, and simply never restored a stored theme.
    const importLine = layout
      .split("\n")
      .find((line) => line.includes("THEME_STORAGE_KEY") && line.startsWith("import "));
    expect(importLine, "layout.tsx no longer imports THEME_STORAGE_KEY").toBeDefined();

    const from = importLine!.match(/from\s+"([^"]+)"/)?.[1];
    expect(from).toBeDefined();
    const modulePath = resolve(SRC, from!.replace(/^@\//, "") + ".ts");
    const source = readFileSync(modulePath, "utf8");
    expect(source).not.toMatch(/^\s*["']use client["']/m);
  });

  it("embeds the key as a literal the browser can read back", () => {
    expect(layout).toContain("JSON.stringify(THEME_STORAGE_KEY)");
    expect(THEME_STORAGE_KEY).toBe("cleancut-theme");
  });

  it("stamps nothing when no theme has been chosen", () => {
    // Writing the OS preference here would freeze a choice the user never made,
    // and the prefers-color-scheme block in globals.css already answers.
    expect(layout).toMatch(/t === "light" \|\| t === "dark"/);
  });
});
