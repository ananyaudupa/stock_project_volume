import { api } from "../api/client";
import { CategoryPills, DateControl, SessionToggle } from "../components/Controls";
import { CompareView } from "../components/CompareView";
import { Header } from "../components/Header";
import { SnapshotMeta } from "../components/SnapshotMeta";
import { ErrorState, LoadingRows, StateMessage } from "../components/StateMessage";
import { StockTable } from "../components/StockTable";
import { useApi } from "../hooks/useApi";
import { useSelection } from "../hooks/useSelection";
import { todayIST } from "../format";
import { LoginPage } from "./LoginPage";
import { CATEGORIES } from "../types/api";

export function ScannerPage() {
  const [sel, update] = useSelection();
  const [status] = useApi("status", (signal) => api.status(signal));

  // "Today" always means the IST trading date reported by the server, never the browser's local date.
  const today = status.kind === "success" ? status.data.today : todayIST();
  const prevTradingDay = status.kind === "success" ? status.data.previous_trading_day : null;
  const date = sel.date ?? today;

  // Reads stored snapshots only - changing selection never triggers a scan.
  const key = sel.compare ? null : `snap:${date}:${sel.session}:${sel.category}`;
  const [snap, reload] = useApi(key, (signal) => api.categorySnapshot(date, sel.session, sel.category, signal));
  const catLabel = CATEGORIES.find((c) => c.value === sel.category)!.label;

  if (status.kind === "error" && status.error.code === "login_required") {
    return <LoginPage onSuccess={() => window.location.reload()} />;
  }

  return (
    <div className="page">
      <Header status={status} />

      <main>
        <section className="controls" aria-label="Snapshot selection">
          <CategoryPills value={sel.category} onChange={(category) => update({ category })} />
          <div className="controls-row">
            <SessionToggle value={sel.session} onChange={(session) => update({ session })} disabled={sel.compare} />
            <label className="compare-toggle">
              <input type="checkbox" checked={sel.compare} onChange={(e) => update({ compare: e.target.checked })} />
              Compare morning vs afternoon
            </label>
          </div>
          <DateControl date={date} today={today} previousTradingDay={prevTradingDay} onChange={(d) => update({ date: d })} />
        </section>

        <section className="results" aria-live="polite">
          <h2 className="results-title">
            Top {catLabel} · {sel.compare ? "morning vs afternoon" : sel.session}
          </h2>

          {sel.compare ? (
            <CompareView date={date} category={sel.category} />
          ) : snap.kind === "loading" || snap.kind === "idle" ? (
            <LoadingRows />
          ) : snap.kind === "error" ? (
            <ErrorState error={snap.error} onRetry={reload} />
          ) : (
            <>
              <SnapshotMeta snap={snap.data} today={today} />
              {snap.data.status === "failed" ? (
                <StateMessage tone="error" title="This scan failed">
                  {snap.data.message} Earlier snapshots are unaffected.
                </StateMessage>
              ) : snap.data.status === "running" || snap.data.status === "pending" ? (
                <StateMessage tone="info" title="Scan in progress">{snap.data.message}</StateMessage>
              ) : snap.data.stocks.length === 0 ? (
                <StateMessage tone="empty" title="No eligible stocks">
                  No {catLabel.toLowerCase()} stocks passed the data-quality filters for this scan.
                </StateMessage>
              ) : (
                <StockTable stocks={snap.data.stocks} today={today} />
              )}
            </>
          )}
        </section>
      </main>

      <footer className="footer muted small">
        Rankings measure recent price movement and trading volume only. Gainers and losers both qualify. This is a
        market-data screening tool, not investment advice or a recommendation to buy or sell, and past activity does not
        predict future returns. All times are IST.
      </footer>
    </div>
  );
}
