/**
 * The maintenance screen, and the confirmation standing in front of the wipes.
 *
 * `window.confirm` was doing real safety work here: these three buttons delete
 * every recording on the instance and there is no backup behind them. Replacing
 * it with a themed modal is only an improvement if the modal keeps the
 * properties that made the browser dialog safe - nothing runs until a second,
 * deliberate click; Escape and the backdrop resolve toward keeping the data;
 * focus starts on the safe button so a stray Return cancels.
 *
 * The API client is mocked throughout, deliberately and permanently: these
 * routes delete real directories, so nothing here may ever be pointed at a
 * running server.
 */

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AdminDashboard from "./page";
import { AdminStats, api } from "@/lib/api";

const STATS: AdminStats = {
  total_jobs: 6,
  total_violations: 128,
  jobs_by_status: { completed: 6 },
  total_uploads_size_mb: 2000.6,
  total_exports_size_mb: 841,
  files_count: 11,
};

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  vi.spyOn(api, "getAdminStats").mockResolvedValue(STATS);
  vi.spyOn(api, "resetDatabase").mockResolvedValue({ message: "Database reset. 6 jobs removed." });
  vi.spyOn(api, "clearStorage").mockResolvedValue({ message: "Storage cleared." });
  vi.spyOn(api, "resetAll").mockResolvedValue({
    message: "Everything reset.",
    database: "ok",
    storage: "ok",
  });
});

async function openConfirm(name: RegExp | string = "Reset") {
  render(<AdminDashboard />);
  await userEvent.click(await screen.findByRole("button", { name }));
  return screen.getByRole("alertdialog");
}

describe("stats", () => {
  it("renders the three figures once the request resolves", async () => {
    render(<AdminDashboard />);
    expect(await screen.findByText("6")).toBeInTheDocument();
    expect(screen.getByText("128")).toBeInTheDocument();
    // Uploads and exports are two numbers on the server and one figure here.
    expect(screen.getByText("2841.6")).toBeInTheDocument();
  });

  it("offers a retry when the stats request fails, and the wipes stay available", async () => {
    vi.mocked(api.getAdminStats).mockRejectedValueOnce(new Error("down"));
    render(<AdminDashboard />);

    const retry = await screen.findByRole("button", { name: "Retry" });
    // The stats failing must not take the screen down with it - the token field
    // and the actions are what someone came here for.
    expect(screen.getByLabelText("Admin token")).toBeInTheDocument();

    await userEvent.click(retry);
    expect(await screen.findByText("128")).toBeInTheDocument();
  });
});

describe("the confirmation", () => {
  it("does not call the API until the dialog is confirmed", async () => {
    await openConfirm();
    expect(api.resetDatabase).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "Yes, reset it" }));
    expect(api.resetDatabase).toHaveBeenCalledTimes(1);
  });

  it("names the action and the consequence", async () => {
    const dialog = await openConfirm("Wipe");
    expect(within(dialog).getByText("System wipe?")).toBeInTheDocument();
    expect(within(dialog).getByText(/cannot be undone/)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Yes, wipe everything" })).toBeInTheDocument();
  });

  it("opens with focus on the safe button, so a stray Return keeps the data", async () => {
    await openConfirm();
    expect(screen.getByRole("button", { name: "Keep everything" })).toHaveFocus();

    await userEvent.keyboard("{Enter}");
    expect(api.resetDatabase).not.toHaveBeenCalled();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("cancels on Escape without calling the API", async () => {
    await openConfirm();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(api.resetDatabase).not.toHaveBeenCalled();
  });

  it("cancels on a click outside the panel", async () => {
    const dialog = await openConfirm();
    // The backdrop is the dialog's parent; a mis-click there must resolve
    // toward keeping everything rather than doing nothing at all.
    await userEvent.click(dialog.parentElement as HTMLElement);
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(api.resetDatabase).not.toHaveBeenCalled();
  });

  it("keeps Tab inside the dialog", async () => {
    const dialog = await openConfirm();
    const cancel = screen.getByRole("button", { name: "Keep everything" });
    const confirm = screen.getByRole("button", { name: "Yes, reset it" });

    await userEvent.tab();
    expect(confirm).toHaveFocus();
    await userEvent.tab();
    expect(cancel).toHaveFocus();
    expect(dialog).toContainElement(document.activeElement as HTMLElement);
  });

  it("returns focus to the button that opened it", async () => {
    render(<AdminDashboard />);
    const trigger = await screen.findByRole("button", { name: "Clear" });
    await userEvent.click(trigger);
    await userEvent.keyboard("{Escape}");
    expect(trigger).toHaveFocus();
  });
});

describe("running an action", () => {
  it("reports the server's message on the row that caused it", async () => {
    await openConfirm();
    await userEvent.click(screen.getByRole("button", { name: "Yes, reset it" }));

    const database = screen.getByRole("group", { name: "Reset database" });
    expect(await within(database).findByText("Database reset. 6 jobs removed.")).toBeInTheDocument();
    // The result belongs to its own row, not to a banner at the top of the page.
    expect(
      within(screen.getByRole("group", { name: "Clear storage" })).queryByText(/Database reset/)
    ).toBeNull();
    // A wipe changes the figures, so they are re-read rather than left stale.
    expect(api.getAdminStats).toHaveBeenCalledTimes(2);
  });

  it("shows the server's refusal rather than swallowing it", async () => {
    vi.mocked(api.resetDatabase).mockRejectedValueOnce(
      new Error("Admin operations are disabled: no ADMIN_TOKEN is configured.")
    );
    await openConfirm();
    await userEvent.click(screen.getByRole("button", { name: "Yes, reset it" }));

    expect(await screen.findByText(/no ADMIN_TOKEN is configured/)).toBeInTheDocument();
  });

  it("stores the admin token as it is typed", async () => {
    render(<AdminDashboard />);
    await userEvent.type(await screen.findByLabelText("Admin token"), "s3cret");
    await waitFor(() => expect(window.localStorage.getItem("cleancut.adminToken")).toBe("s3cret"));
  });
});
