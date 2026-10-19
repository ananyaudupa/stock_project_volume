import { api } from "../api/client";
import { useApi } from "../hooks/useApi";
import type { DailyBar, Pick } from "../types/api";
import { fmtDateLong, fmtPct, fmtPrice, fmtVolume, shiftDate } from "../format";

export function StockDetail({ pick, today }: { pick: Pick; today: string }) {
  const from = shiftDate(today, -45);
  const [hist] = useApi(`hist:${pick.symbol}:${from}:${today}`, (signal) => api.stockHistory(pick.symbol, from, today, signal));
  const close = pick.performance.find((p) => p.measurement_type === "close");

  return (
    <div className="detail">
      <p className="reason">{pick.selection_reason}</p>
      <dl className="detail-grid">
        <div><dt>Previous close</dt><dd>{fmtPrice(pick.previous_close)}</dd></div>
        <div><dt>Price at scan</dt><dd>{fmtPrice(pick.price_at_scan)}</dd></div>
        <div><dt>Movement strength</dt><dd>{pick.movement_strength.toFixed(2)}%</dd></div>
        <div><dt>Volume basis</dt><dd>{pick.volume_basis_label}</dd></div>
        <div><dt>Volume score</dt><dd>{pick.volume_score.toFixed(3)}</dd></div>
        <div><dt>Movement score</dt><dd>{pick.movement_score.toFixed(3)}</dd></div>
        <div><dt>Final score</dt><dd>{pick.final_score.toFixed(3)}</dd></div>
        <div>
          <dt>Close (same day)</dt>
          <dd>
            {close ? (
              <>
                {fmtPrice(close.measurement_price)}{" "}
                <span className={close.return_pct >= 0 ? "chg-up" : "chg-down"}>({fmtPct(close.return_pct)} since scan)</span>
              </>
            ) : (
              <span className="muted">Not measured yet</span>
            )}
          </dd>
        </div>
      </dl>

      <div className="detail-history">
        <h3>Recent history</h3>
        {hist.kind === "loading" && <p className="muted small">Loading history…</p>}
        {hist.kind === "error" && <p className="muted small">History unavailable: {hist.error.message}</p>}
        {hist.kind === "success" && (
          <>
            {hist.data.price_history_supported ? (
              <Sparkline bars={hist.data.price_history} />
            ) : (
              <p className="muted small">{hist.data.note}</p>
            )}
            {hist.data.price_history_is_mock && <p className="muted small">Price history is synthetic demo data.</p>}
            <p className="small">
              Selected {hist.data.picks.length} time{hist.data.picks.length === 1 ? "" : "s"} in the last 45 days
              {hist.data.picks.length > 0 && ":"}
            </p>
            <ul className="pick-history">
              {hist.data.picks.slice(0, 8).map((p) => (
                <li key={p.id}>
                  {fmtDateLong(p.trading_date)} · {p.session} · rank {p.rank} · {fmtPct(p.price_change_pct)}
                  {p.performance[0] && <span className="muted"> → close {fmtPct(p.performance[0].return_pct)}</span>}
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </div>
  );
}

function Sparkline({ bars }: { bars: DailyBar[] }) {
  if (bars.length < 2) return <p className="muted small">Not enough price history.</p>;
  const w = 280, h = 56, pad = 4;
  const closes = bars.map((b) => b.close);
  const min = Math.min(...closes), max = Math.max(...closes);
  const span = max - min || 1;
  const pts = closes.map((c, i) => `${pad + (i / (closes.length - 1)) * (w - 2 * pad)},${h - pad - ((c - min) / span) * (h - 2 * pad)}`);
  const up = closes[closes.length - 1] >= closes[0];
  const last = bars[bars.length - 1];
  return (
    <figure className="spark">
      <svg viewBox={`0 0 ${w} ${h}`} width="100%" height={h} role="img" aria-label={`Closing prices from ${bars[0].trading_date} to ${last.trading_date}`}>
        <polyline points={pts.join(" ")} fill="none" stroke={up ? "var(--up)" : "var(--down)"} strokeWidth="2" />
      </svg>
      <figcaption className="muted small">
        {bars.length} sessions · last close {fmtPrice(last.close)} · vol {fmtVolume(last.volume)}
      </figcaption>
    </figure>
  );
}
