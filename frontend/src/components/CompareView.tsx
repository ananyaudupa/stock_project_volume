import { api } from "../api/client";
import { useApi } from "../hooks/useApi";
import type { Category, CategorySnapshot } from "../types/api";
import { fmtPct, fmtRelVol, fmtTimeIST } from "../format";
import { ErrorState, LoadingRows, StateMessage } from "./StateMessage";

export function CompareView({ date, category }: { date: string; category: Category }) {
  const [state, reload] = useApi(`cmp:${date}:${category}`, (signal) => api.compare(date, category, signal));
  if (state.kind === "loading" || state.kind === "idle") return <LoadingRows />;
  if (state.kind === "error") return <ErrorState error={state.error} onRetry={reload} />;
  const { morning, afternoon, in_both } = state.data;
  const both = new Set(in_both);
  return (
    <div className="compare">
      <p className="muted small">
        {in_both.length} of the stocks appear in both lists. Shared symbols are highlighted.
      </p>
      <div className="compare-cols">
        <CompareColumn title="Morning 09:20" snap={morning} both={both} />
        <CompareColumn title="Afternoon 15:00" snap={afternoon} both={both} />
      </div>
    </div>
  );
}

function CompareColumn({ title, snap, both }: { title: string; snap: CategorySnapshot | null; both: Set<string> }) {
  return (
    <section className="compare-col" aria-label={title}>
      <h3>{title}</h3>
      {!snap ? (
        <StateMessage tone="empty" title="No snapshot" />
      ) : snap.stocks.length === 0 ? (
        <StateMessage tone={snap.status === "failed" ? "error" : "info"} title={`Status: ${snap.status}`}>
          {snap.message}
        </StateMessage>
      ) : (
        <>
          <p className="muted small">Data as of {fmtTimeIST(snap.data_as_of, true)} IST</p>
          <ol className="compare-list">
            {snap.stocks.map((s) => (
              <li key={s.id} className={both.has(s.symbol) ? "shared" : ""}>
                <span className="sym">{s.symbol}</span>
                <span className={`chg chg-${s.direction}`}>{fmtPct(s.price_change_pct)}</span>
                <span className="muted">{fmtRelVol(s.relative_volume)}</span>
                <span className="muted">{s.final_score.toFixed(2)}</span>
              </li>
            ))}
          </ol>
        </>
      )}
    </section>
  );
}
