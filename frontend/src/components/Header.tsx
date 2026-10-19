import { auth } from "../api/client";
import type { ApiState } from "../hooks/useApi";
import type { Status } from "../types/api";
import { fmtAge, fmtDateLong, fmtDateTimeIST } from "../format";

export function Header({ status }: { status: ApiState<Status> }) {
  return (
    <header className="header">
      <div className="header-title">
        <h1>NSE Daily Scanner</h1>
        <p className="muted">High-volume, fast-moving stocks · twice per trading day</p>
      </div>
      <div className="header-status" aria-live="polite">
        {status.kind === "loading" && <span className="muted">Checking data status…</span>}
        {status.kind === "error" && <span className="badge badge-error">Status unavailable</span>}
        {status.kind === "success" && <StatusSummary s={status.data} />}
        <button className="link-btn small" onClick={() => auth.logout().finally(() => window.location.reload())}>
          Sign out
        </button>
      </div>
    </header>
  );
}

function StatusSummary({ s }: { s: Status }) {
  const last = s.last_successful;
  const failedLatest = s.latest_run && s.latest_run.status === "failed";
  return (
    <>
      {s.is_mock_data && (
        <span className="badge badge-demo" title="The mock provider generates synthetic data for development">
          DEMO DATA — not live market data
        </span>
      )}
      <span className="status-line">
        <span className={`dot ${failedLatest ? "dot-bad" : last ? "dot-ok" : "dot-idle"}`} aria-hidden />
        {last ? (
          <>
            Last scan: {fmtDateLong(last.trading_date)} {last.session} · data {fmtAge(s.data_freshness_seconds)}
          </>
        ) : (
          "No completed scans yet"
        )}
      </span>
      {failedLatest && <span className="badge badge-error">Latest scan failed</span>}
      {s.next_scheduled_scan && <span className="muted small">Next scan {fmtDateTimeIST(s.next_scheduled_scan)} IST</span>}
    </>
  );
}
