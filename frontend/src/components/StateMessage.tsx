import type { ReactNode } from "react";
import type { ApiError } from "../api/client";

type Tone = "info" | "empty" | "warn" | "error";

export function StateMessage({ tone, title, children, action }: { tone: Tone; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className={`state state-${tone}`} role={tone === "error" ? "alert" : "status"}>
      <p className="state-title">{title}</p>
      {children && <div className="state-body">{children}</div>}
      {action}
    </div>
  );
}

/** Map API errors to user-facing states. "No snapshot" responses are not shown as errors. */
export function ErrorState({ error, onRetry }: { error: ApiError; onRetry: () => void }) {
  switch (error.code) {
    case "non_trading_day":
      return <StateMessage tone="empty" title="Market closed">{error.message}</StateMessage>;
    case "scan_not_yet_run":
      return <StateMessage tone="info" title="Scan not run yet">{error.message}</StateMessage>;
    case "no_scan_recorded":
      return <StateMessage tone="empty" title="No snapshot for this date">{error.message}</StateMessage>;
    case "calendar_unknown":
      return <StateMessage tone="warn" title="Trading calendar not loaded">{error.message}</StateMessage>;
    default:
      return (
        <StateMessage
          tone="error"
          title="Couldn't load this snapshot"
          action={
            <button className="btn" onClick={onRetry}>
              Try again
            </button>
          }
        >
          {error.message}
        </StateMessage>
      );
  }
}

export function LoadingRows({ rows = 5 }: { rows?: number }) {
  return (
    <div className="skeleton-list" aria-busy="true" aria-label="Loading results">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="skeleton-row" />
      ))}
    </div>
  );
}
