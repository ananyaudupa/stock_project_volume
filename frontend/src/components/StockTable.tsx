import { Fragment, useState } from "react";
import type { Pick } from "../types/api";
import { fmtPct, fmtPrice, fmtRelVol, fmtTimeIST, fmtVolume } from "../format";
import { StockDetail } from "./StockDetail";

export function Direction({ pick }: { pick: Pick }) {
  const arrow = pick.direction === "up" ? "▲" : pick.direction === "down" ? "▼" : "■";
  return (
    <span className={`chg chg-${pick.direction}`}>
      <span aria-hidden>{arrow}</span> {fmtPct(pick.price_change_pct)}
      <span className="sr-only">{pick.direction === "up" ? " gain" : pick.direction === "down" ? " loss" : " unchanged"}</span>
    </span>
  );
}

export function ScoreBar({ value }: { value: number }) {
  return (
    <span className="score" title={`Final score ${value.toFixed(3)}`}>
      <span className="score-track">
        <span className="score-fill" style={{ width: `${Math.round(value * 100)}%` }} />
      </span>
      <span className="score-num">{value.toFixed(2)}</span>
    </span>
  );
}

export function StockTable({ stocks, today }: { stocks: Pick[]; today: string }) {
  const [open, setOpen] = useState<number | null>(null);
  return (
    <div className="table-wrap">
      <table className="stocks">
        <thead>
          <tr>
            <th scope="col">#</th>
            <th scope="col">Stock</th>
            <th scope="col" className="num">Price at scan</th>
            <th scope="col" className="num">Change</th>
            <th scope="col" className="num">Volume</th>
            <th scope="col" className="num">Rel. vol</th>
            <th scope="col">Score</th>
            <th scope="col" className="num">Data time</th>
            <th scope="col"><span className="sr-only">Details</span></th>
          </tr>
        </thead>
        <tbody>
          {stocks.map((s) => {
            const isOpen = open === s.id;
            return (
              <Fragment key={s.id}>
                <tr className={`row ${isOpen ? "row-open" : ""}`} onClick={() => setOpen(isOpen ? null : s.id)}>
                  <td className="rank" data-label="Rank">{s.rank}</td>
                  <td className="stock" data-label="Stock">
                    <span className="sym">{s.symbol}</span>
                    <span className="co muted">{s.company_name}</span>
                  </td>
                  <td className="num" data-label="Price">{fmtPrice(s.price_at_scan)}</td>
                  <td className="num" data-label="Change"><Direction pick={s} /></td>
                  <td className="num" data-label="Volume" title="Accumulated session volume at scan time">{fmtVolume(s.intraday_volume)}</td>
                  <td className="num" data-label="Rel. vol" title={s.volume_basis_label}>{fmtRelVol(s.relative_volume)}</td>
                  <td data-label="Score"><ScoreBar value={s.final_score} /></td>
                  <td className="num muted" data-label="Data time">{fmtTimeIST(s.data_timestamp, true)}</td>
                  <td className="toggle-cell">
                    <button
                      className="icon-btn"
                      aria-expanded={isOpen}
                      aria-label={`${isOpen ? "Hide" : "Show"} details for ${s.symbol}`}
                      onClick={(e) => {
                        e.stopPropagation();
                        setOpen(isOpen ? null : s.id);
                      }}
                    >
                      {isOpen ? "−" : "+"}
                    </button>
                  </td>
                </tr>
                {isOpen && (
                  <tr className="detail-row">
                    <td colSpan={9}>
                      <StockDetail pick={s} today={today} />
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
