"use client";

import { useCallback, useSyncExternalStore } from "react";

import { THEME_EVENT, THEME_STORAGE_KEY, type Theme } from "@/lib/theme";

export { THEME_STORAGE_KEY, type Theme };

/**
 * Every storage access is guarded. A browser with site data blocked throws on
 * the *getter*, not just on write, and a page that renders nothing at all is a
 * worse failure than one that ignores a stored preference.
 */
export function readStoredTheme(): Theme | null {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    return stored === "light" || stored === "dark" ? stored : null;
  } catch {
    return null;
  }
}

function systemTheme(): Theme {
  try {
    return window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  } catch {
    return "light";
  }
}

/*
 * The theme lives in the DOM and in localStorage, not in React - the inline
 * script in layout.tsx has already stamped the attribute before this component
 * ever mounts, and the OS preference can change under us. That makes it an
 * external store, so it is read as one rather than mirrored into state by an
 * effect that would fire a cascading render on every mount.
 */
function subscribe(onChange: () => void): () => void {
  window.addEventListener(THEME_EVENT, onChange);
  window.addEventListener("storage", onChange);
  let media: MediaQueryList | null = null;
  try {
    media = window.matchMedia("(prefers-color-scheme: dark)");
    media.addEventListener("change", onChange);
  } catch {
    media = null;
  }
  return () => {
    window.removeEventListener(THEME_EVENT, onChange);
    window.removeEventListener("storage", onChange);
    media?.removeEventListener("change", onChange);
  };
}

function getSnapshot(): Theme {
  const attr = document.documentElement.getAttribute("data-theme");
  return attr === "light" || attr === "dark" ? attr : systemTheme();
}

// The server has neither localStorage nor a media query, so it renders the
// light state and React re-renders with the real one straight after hydration.
// Nothing visible depends on this beyond the button's own label - the ground
// itself is already correct, painted from the stamped attribute.
function getServerSnapshot(): Theme {
  return "light";
}

export function useTheme(): [Theme, () => void] {
  const theme = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  const toggle = useCallback(() => {
    const next: Theme = getSnapshot() === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      // Not persisted; the attribute above still applies it for this page.
    }
    window.dispatchEvent(new Event(THEME_EVENT));
  }, []);

  return [theme, toggle];
}

export function ThemeToggle({ className }: { className?: string }) {
  const [theme, toggle] = useTheme();
  const isDark = theme === "dark";

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label="Switch theme"
      aria-pressed={isDark}
      title={isDark ? "Switch to light theme" : "Switch to dark theme"}
      className={[
        "inline-grid size-8 place-items-center rounded-full border border-divider",
        "text-muted-foreground transition-colors hover:bg-surface hover:text-foreground",
        className ?? "",
      ].join(" ")}
    >
      {/*
        One glyph that fills in rather than two icons swapping: a half-filled
        circle reads as "theme" in either state and needs no icon dependency.
      */}
      <svg
        width="15"
        height="15"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.25"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <circle cx="12" cy="12" r="9" />
        <path d="M12 3a9 9 0 0 0 0 18Z" fill="currentColor" stroke="none" />
      </svg>
    </button>
  );
}

export default ThemeToggle;
