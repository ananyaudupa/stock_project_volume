const IST = "Asia/Kolkata";

export const fmtPrice = (n: number) =>
  "₹" + n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export const fmtPct = (n: number) => `${n > 0 ? "+" : ""}${n.toFixed(2)}%`;

/** Indian-style compact volume: 12.3 L (lakh), 4.56 Cr (crore). */
export function fmtVolume(n: number | null): string {
  if (n === null) return "—";
  if (n >= 1e7) return `${(n / 1e7).toFixed(2)} Cr`;
  if (n >= 1e5) return `${(n / 1e5).toFixed(2)} L`;
  return n.toLocaleString("en-IN");
}

export const fmtRelVol = (n: number | null) => (n === null ? "—" : `${n.toFixed(2)}×`);

export function fmtTimeIST(iso: string | null, withSeconds = false): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat("en-IN", {
    timeZone: IST,
    hour: "2-digit",
    minute: "2-digit",
    second: withSeconds ? "2-digit" : undefined,
    hour12: false,
  }).format(new Date(iso));
}

export function fmtDateLong(isoDate: string): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  return new Intl.DateTimeFormat("en-IN", { weekday: "short", day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }).format(
    new Date(Date.UTC(y, m - 1, d)),
  );
}

export function fmtDateTimeIST(iso: string | null): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat("en-IN", {
    timeZone: IST,
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(iso));
}

/** IST calendar date (YYYY-MM-DD) of an instant. */
export function isoDateIST(iso: string): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: IST }).format(new Date(iso));
}

/** Today's date in IST as YYYY-MM-DD (fallback before /status has loaded). */
export function todayIST(): string {
  return isoDateIST(new Date().toISOString());
}

export function shiftDate(isoDate: string, days: number): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d + days));
  return dt.toISOString().slice(0, 10);
}

export function fmtAge(seconds: number | null): string {
  if (seconds === null) return "—";
  if (seconds < 90) return `${seconds}s ago`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 172800) return `${Math.round(seconds / 3600)} h ago`;
  return `${Math.round(seconds / 86400)} days ago`;
}
