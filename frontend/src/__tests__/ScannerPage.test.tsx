import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ScannerPage } from "../pages/ScannerPage";
import type { CategorySnapshot, Pick, Status } from "../types/api";

const status: Status = {
  now: "2026-10-17T11:30:00+05:30",
  today: "2026-10-17",
  is_trading_day: false,
  non_trading_reason: "weekend",
  previous_trading_day: "2026-10-16",
  provider: "mock",
  is_mock_data: true,
  last_successful: {
    run_id: 2, trading_date: "2026-10-16", session: "afternoon", status: "completed",
    completed_at: "2026-10-16T15:00:02+05:30", data_as_of: "2026-10-16T15:00:00+05:30", message: null,
  },
  latest_run: null,
  today_sessions: {
    morning: { status: "none", run_id: null, pick_count: 0, is_mock_data: null },
    afternoon: { status: "none", run_id: null, pick_count: 0, is_mock_data: null },
  },
  next_scheduled_scan: "2026-10-19T09:20:00+05:30",
  data_freshness_seconds: 70000,
  classification_version: "mock-2026-09-30",
  calendar_years_loaded: [2026],
};

const pick = (rank: number, symbol: string, change: number): Pick => ({
  id: rank, symbol, company_name: `${symbol} Ltd`, cap_category: "large-cap", rank,
  price_at_scan: 100 + change, previous_close: 100, price_change_pct: change,
  direction: change > 0 ? "up" : change < 0 ? "down" : "flat", movement_strength: Math.abs(change),
  intraday_volume: 1_234_567, relative_volume: 1.8, volume_basis: "same_time_baseline",
  volume_basis_label: "today so far vs typical volume by this time", volume_score: 0.9, movement_score: 0.8,
  final_score: 0.85, data_timestamp: "2026-10-16T15:00:00+05:30", selection_reason: `${symbol} reason`, performance: [],
});

function snapshot(overrides: Partial<CategorySnapshot> = {}): CategorySnapshot {
  return {
    run_id: 1, trading_date: "2026-10-16", session: "afternoon", scan_type: "scheduled", status: "completed",
    scheduled_at: "2026-10-16T15:00:00+05:30", scan_time: "15:00:00+05:30", started_at: null,
    completed_at: "2026-10-16T15:00:02+05:30", data_as_of: "2026-10-16T15:00:00+05:30", is_stale: false,
    stale_reason: null, is_mock_data: true, provider: "mock", algorithm_version: "pctrank-v1",
    classification_version: "mock-2026-09-30", weights: { volume: 0.5, movement: 0.5 },
    methodology_note: "Afternoon scan: ranks ...", message: null, eligible_counts: { "large-cap": 97 }, exclusions: {},
    category: "large-cap", stocks: [pick(1, "DEMOL007", 3.2), pick(2, "DEMOL042", -2.5)], ...overrides,
  };
}

type Route = (url: string) => { status: number; body: unknown } | "network";
let route: Route;
let loggedIn = true;
const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
  const url = String(input);
  if (init?.method && init.method !== "GET" && !url.startsWith("/api/auth/"))
    throw new Error("Browsing must never send non-GET requests (no scans triggered)");
  if (url.startsWith("/api/auth/login")) {
    const ok = JSON.parse(String(init?.body)).password === "right-pw";
    if (ok) loggedIn = true;
    return ok
      ? new Response(JSON.stringify({ logged_in: true }), { status: 200 })
      : new Response(JSON.stringify({ error: { code: "wrong_password", message: "That password is not correct.", details: {} } }), { status: 401 });
  }
  if (!loggedIn)
    return new Response(JSON.stringify({ error: { code: "login_required", message: "Please log in", details: {} } }), { status: 401 });
  if (url.includes("/api/scans/status")) return new Response(JSON.stringify(status), { status: 200 });
  const r = route(url);
  if (r === "network") throw new TypeError("Failed to fetch");
  return new Response(JSON.stringify(r.body), { status: r.status });
});

function setUrl(qs: string) {
  window.history.replaceState(null, "", `/?${qs}`);
}

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockClear();
  loggedIn = true;
  route = () => ({ status: 200, body: snapshot() });
  setUrl("category=large-cap&session=afternoon&date=2026-10-16");
});
afterEach(() => vi.unstubAllGlobals());

const snapshotCalls = () =>
  fetchMock.mock.calls.map((c) => String(c[0])).filter((u) => /\/api\/scans\/\d{4}-\d{2}-\d{2}\//.test(u));

describe("ScannerPage", () => {
  it("shows the three category pills and the ranked list with timestamps", async () => {
    render(<ScannerPage />);
    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual(["Small Cap", "Mid Cap", "Large Cap"]);
    expect(await screen.findByText("DEMOL007")).toBeInTheDocument();
    expect(screen.getByText("Afternoon snapshot")).toBeInTheDocument();
    expect(screen.getByText("Historical")).toBeInTheDocument(); // 16 Oct is not "today" (17 Oct)
    expect(screen.getAllByText(/Demo data|DEMO DATA/).length).toBeGreaterThan(0);
    expect(screen.getByText(/▼/).closest("td")).toHaveTextContent("-2.50%");
    expect(snapshotCalls()).toEqual(["/api/scans/2026-10-16/afternoon/large-cap"]);
  });

  it("keeps date and session when switching category, and only reads stored data", async () => {
    render(<ScannerPage />);
    await screen.findByText("DEMOL007");
    await userEvent.click(screen.getByRole("tab", { name: "Mid Cap" }));
    await waitFor(() => expect(snapshotCalls()).toContain("/api/scans/2026-10-16/afternoon/mid-cap"));
    expect(window.location.search).toContain("date=2026-10-16");
    expect(window.location.search).toContain("session=afternoon");
    await userEvent.click(screen.getByRole("radio", { name: /Morning/ }));
    await waitFor(() => expect(snapshotCalls()).toContain("/api/scans/2026-10-16/morning/mid-cap"));
    expect(fetchMock.mock.calls.every((c) => !c[1]?.method || c[1].method === "GET")).toBe(true);
  });

  it("'Previous trading day' and 'Today' resolve from the server's IST calendar", async () => {
    setUrl("category=large-cap&session=morning");
    route = () => ({ status: 404, body: { error: { code: "non_trading_day", message: "2026-10-17 is a weekend; NSE is closed.", details: {} } } });
    render(<ScannerPage />);
    expect(await screen.findByText("Market closed")).toBeInTheDocument();
    await waitFor(() => expect(snapshotCalls()).toContain("/api/scans/2026-10-17/morning/large-cap"));
    await userEvent.click(screen.getByRole("button", { name: "Previous trading day" }));
    await waitFor(() => expect(snapshotCalls()).toContain("/api/scans/2026-10-16/morning/large-cap"));
  });

  it("distinguishes a missing historical scan from an application error", async () => {
    route = () => ({ status: 404, body: { error: { code: "no_scan_recorded", message: "No afternoon scan was recorded.", details: {} } } });
    const { unmount } = render(<ScannerPage />);
    expect(await screen.findByText("No snapshot for this date")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    unmount();

    route = () => "network";
    render(<ScannerPage />);
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("Couldn't load this snapshot")).toBeInTheDocument();
    route = () => ({ status: 200, body: snapshot() });
    await userEvent.click(within(alert).getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("DEMOL007")).toBeInTheDocument();
  });

  it("shows failed and stale snapshots clearly", async () => {
    route = () => ({ status: 200, body: snapshot({ status: "failed", stocks: [], message: "The market-data provider was unavailable." }) });
    const { unmount } = render(<ScannerPage />);
    expect(await screen.findByText("This scan failed")).toBeInTheDocument();
    expect(screen.getByText(/Earlier snapshots are unaffected/)).toBeInTheDocument();
    unmount();

    route = () => ({ status: 200, body: snapshot({ is_stale: true, stale_reason: "Data captured 105 min after the scheduled scan time" }) });
    render(<ScannerPage />);
    expect(await screen.findByText(/Stale data: Data captured 105 min/)).toBeInTheDocument();
  });

  it("shows a loading state, then expands stock details", async () => {
    route = (url) =>
      url.includes("/api/stocks/")
        ? { status: 200, body: { symbol: "DEMOL007", from_date: "", to_date: "", picks: [], price_history_supported: false, price_history: [], price_history_is_mock: true, note: "No history from provider." } }
        : { status: 200, body: snapshot() };
    render(<ScannerPage />);
    expect(screen.getByLabelText("Loading results")).toBeInTheDocument();
    await screen.findByText("DEMOL007");
    await userEvent.click(screen.getByRole("button", { name: "Show details for DEMOL007" }));
    expect(await screen.findByText("DEMOL007 reason")).toBeInTheDocument();
    expect(await screen.findByText("No history from provider.")).toBeInTheDocument();
  });

  it("asks for the password when login is required, and rejects a wrong one", async () => {
    loggedIn = false;
    const reload = vi.fn();
    vi.stubGlobal("location", { ...window.location, reload, search: window.location.search, pathname: "/" });
    render(<ScannerPage />);
    const input = await screen.findByLabelText("Password");
    expect(screen.queryByRole("tab")).not.toBeInTheDocument(); // no data shown before login
    await userEvent.type(input, "wrong");
    await userEvent.click(screen.getByRole("button", { name: "Open scanner" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("That password is not correct.");
    expect(reload).not.toHaveBeenCalled();
    await userEvent.clear(input);
    await userEvent.type(input, "right-pw");
    await userEvent.click(screen.getByRole("button", { name: "Open scanner" }));
    await waitFor(() => expect(reload).toHaveBeenCalled());
  });

  it("compare mode shows both sessions and highlights shared symbols", async () => {
    setUrl("category=large-cap&session=morning&date=2026-10-16&compare=1");
    route = () => ({
      status: 200,
      body: {
        trading_date: "2026-10-16", category: "large-cap",
        morning: snapshot({ session: "morning" }), afternoon: snapshot(),
        in_both: ["DEMOL007", "DEMOL042"], morning_only: [], afternoon_only: [],
      },
    });
    render(<ScannerPage />);
    expect(await screen.findByRole("region", { name: "Morning 09:20" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Afternoon 15:00" })).toBeInTheDocument();
    expect(fetchMock.mock.calls.map((c) => String(c[0]))).toContain("/api/scans/2026-10-16/compare?category=large-cap");
  });
});
