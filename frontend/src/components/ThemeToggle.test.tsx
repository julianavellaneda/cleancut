import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ThemeToggle, THEME_STORAGE_KEY, readStoredTheme } from "./ThemeToggle";

function setSystemPrefersDark(dark: boolean) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: dark && query.includes("dark"),
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

describe("ThemeToggle", () => {
  beforeEach(() => {
    document.documentElement.removeAttribute("data-theme");
    window.localStorage.clear();
    setSystemPrefersDark(false);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    document.documentElement.removeAttribute("data-theme");
    window.localStorage.clear();
  });

  it("starts from the system preference when nothing is stored", () => {
    setSystemPrefersDark(true);
    render(<ThemeToggle />);
    expect(screen.getByRole("button", { name: "Switch theme" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("reads the attribute the no-flash script already stamped", () => {
    document.documentElement.setAttribute("data-theme", "dark");
    render(<ThemeToggle />);
    expect(screen.getByRole("button", { name: "Switch theme" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("stamps the attribute and persists the choice", async () => {
    const user = userEvent.setup();
    render(<ThemeToggle />);

    await user.click(screen.getByRole("button", { name: "Switch theme" }));

    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
    expect(screen.getByRole("button", { name: "Switch theme" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    await user.click(screen.getByRole("button", { name: "Switch theme" }));
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
  });

  it("an explicit light choice survives a dark system preference", async () => {
    setSystemPrefersDark(true);
    const user = userEvent.setup();
    render(<ThemeToggle />);

    await user.click(screen.getByRole("button", { name: "Switch theme" }));

    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });

  it("still renders and still applies the theme when storage throws", async () => {
    // A browser with site data blocked throws on the getter as well as the
    // setter. The button has to keep working; only persistence is lost.
    const setItem = vi
      .spyOn(Storage.prototype, "setItem")
      .mockImplementation(() => {
        throw new Error("blocked");
      });
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });

    const user = userEvent.setup();
    render(<ThemeToggle />);
    expect(readStoredTheme()).toBeNull();

    await user.click(screen.getByRole("button", { name: "Switch theme" }));

    expect(setItem).toHaveBeenCalled();
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });
});
