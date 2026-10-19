import { CATEGORIES, SESSIONS, type Category, type Session } from "../types/api";
import { fmtDateLong, shiftDate } from "../format";

export function CategoryPills({ value, onChange }: { value: Category; onChange: (c: Category) => void }) {
  return (
    <div className="pills" role="tablist" aria-label="Market-cap category">
      {CATEGORIES.map((c) => (
        <button
          key={c.value}
          role="tab"
          aria-selected={value === c.value}
          className={`pill ${value === c.value ? "pill-active" : ""}`}
          onClick={() => onChange(c.value)}
        >
          {c.label}
        </button>
      ))}
    </div>
  );
}

export function SessionToggle({
  value,
  onChange,
  disabled,
}: {
  value: Session;
  onChange: (s: Session) => void;
  disabled?: boolean;
}) {
  return (
    <div className="segmented" role="radiogroup" aria-label="Scan session">
      {SESSIONS.map((s) => (
        <button
          key={s.value}
          role="radio"
          aria-checked={value === s.value}
          disabled={disabled}
          className={`seg ${value === s.value ? "seg-active" : ""}`}
          onClick={() => onChange(s.value)}
        >
          {s.label} <span className="seg-time">{s.time}</span>
        </button>
      ))}
    </div>
  );
}

function skipWeekend(date: string, dir: 1 | -1): string {
  let d = shiftDate(date, dir);
  for (let i = 0; i < 3; i++) {
    const wd = new Date(d + "T00:00:00Z").getUTCDay();
    if (wd !== 0 && wd !== 6) break;
    d = shiftDate(d, dir);
  }
  return d;
}

export function DateControl({
  date,
  today,
  previousTradingDay,
  onChange,
}: {
  date: string;
  today: string;
  previousTradingDay: string | null;
  onChange: (d: string | null) => void;
}) {
  const isToday = date === today;
  const isPrev = previousTradingDay !== null && date === previousTradingDay;
  return (
    <div className="date-control" aria-label="Trading date">
      <div className="segmented">
        <button className={`seg ${isToday ? "seg-active" : ""}`} aria-pressed={isToday} onClick={() => onChange(null)}>
          Today
        </button>
        <button
          className={`seg ${isPrev ? "seg-active" : ""}`}
          aria-pressed={isPrev}
          disabled={!previousTradingDay}
          onClick={() => previousTradingDay && onChange(previousTradingDay)}
        >
          Previous trading day
        </button>
      </div>
      <div className="date-picker">
        <button className="icon-btn" aria-label="Earlier weekday" onClick={() => onChange(skipWeekend(date, -1))}>
          ‹
        </button>
        <label className="sr-only" htmlFor="scan-date">
          Choose date
        </label>
        <input
          id="scan-date"
          type="date"
          value={date}
          max={today}
          onChange={(e) => e.target.value && onChange(e.target.value === today ? null : e.target.value)}
        />
        <button
          className="icon-btn"
          aria-label="Later weekday"
          disabled={date >= today}
          onClick={() => {
            const next = skipWeekend(date, 1);
            onChange(next >= today ? null : next);
          }}
        >
          ›
        </button>
      </div>
      <span className="date-label">{fmtDateLong(date)}{isToday ? " (today)" : ""}</span>
    </div>
  );
}
