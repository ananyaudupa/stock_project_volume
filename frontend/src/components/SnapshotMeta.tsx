import type { CategorySnapshot } from "../types/api";
import { fmtDateLong, fmtDateTimeIST, fmtTimeIST, isoDateIST } from "../format";

const STATUS_LABEL: Record<string, string> = {
  completed: "Completed",
  partial: "Partial",
  failed: "Failed",
  running: "Running",
  pending: "Pending",
};

export function SnapshotMeta({ snap, today }: { snap: CategorySnapshot; today: string }) {
  const notToday = snap.trading_date !== today;
  return (
    <section className="meta" aria-label="Snapshot details">
      <div className="meta-main">
        <span className={`session-tag session-${snap.session}`}>{snap.session === "morning" ? "Morning" : "Afternoon"} snapshot</span>
        <strong>{fmtDateLong(snap.trading_date)}</strong>
        {notToday && <span className="badge badge-hist">Historical</span>}
        <span className={`badge badge-status-${snap.status}`}>{STATUS_LABEL[snap.status] ?? snap.status}</span>
        {snap.scan_type === "manual" && <span className="badge">Manual run</span>}
        {snap.is_mock_data && <span className="badge badge-demo">Demo data</span>}
      </div>
      <dl className="meta-grid">
        <div>
          <dt>Scheduled</dt>
          <dd>{snap.scan_time.slice(0, 5)} IST</dd>
        </div>
        <div>
          <dt>Completed</dt>
          <dd>
            {snap.completed_at && isoDateIST(snap.completed_at) !== snap.trading_date
              ? fmtDateTimeIST(snap.completed_at)
              : fmtTimeIST(snap.completed_at, true)}
          </dd>
        </div>
        <div>
          <dt>Data as of</dt>
          <dd>{fmtTimeIST(snap.data_as_of, true)}</dd>
        </div>
        <div>
          <dt>Eligible stocks</dt>
          <dd>{snap.eligible_counts[snap.category] ?? "—"}</dd>
        </div>
        <div>
          <dt>Weights</dt>
          <dd>
            volume {snap.weights.volume} · move {snap.weights.movement}
          </dd>
        </div>
      </dl>
      {snap.is_stale && (
        <p className="notice notice-warn" role="status">
          ⚠ Stale data: {snap.stale_reason}
        </p>
      )}
      {snap.status === "partial" && <p className="notice notice-warn">{snap.message}</p>}
      <p className="method muted small">{snap.methodology_note}</p>
    </section>
  );
}
