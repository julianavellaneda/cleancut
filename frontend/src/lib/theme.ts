/**
 * Shared by the server-rendered no-flash script in `app/layout.tsx` and the
 * client `ThemeToggle`, which is exactly why it lives here rather than in the
 * component: a `"use client"` module's exports do not survive into the server
 * bundle, so importing the key from there serialized
 * `localStorage.getItem(undefined)` into the inline script and the stored theme
 * was never read back. Nothing in this file may become client-only.
 */
export type Theme = "light" | "dark";

export const THEME_STORAGE_KEY = "cleancut-theme";

/** Fired on `window` when this tab changes the theme, so every toggle updates. */
export const THEME_EVENT = "cleancut:themechange";
