import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// jsdom implements neither of these, and both are reached on a plain render:
// Radix's ScrollArea observes its viewport, and the sidebar scrolls the
// selected row into view whenever the selection moves. Stubbing them keeps the
// component under test rather than its layout.
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
};
Element.prototype.scrollIntoView ??= vi.fn();

afterEach(cleanup);
