import type {
  ApiErrorBody,
  Category,
  CategorySnapshot,
  CompareResult,
  Session,
  Status,
  StockHistory,
} from "../types/api";

const BASE = import.meta.env.VITE_API_BASE_URL ?? "";

/** An error returned by the API ({error: {code, message}}) or a network failure (code "network_error"). */
export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }

  /** True when the API says "there is no snapshot", as opposed to something going wrong. */
  get isNoSnapshot(): boolean {
    return this.status === 404 && ["non_trading_day", "scan_not_yet_run", "no_scan_recorded"].includes(this.code);
  }
}

async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  let res: Response;
  try {
    res = await fetch(BASE + path, { signal, headers: { Accept: "application/json" } });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError(0, "network_error", "Could not reach the scanner API. Check your connection and try again.");
  }
  if (!res.ok) {
    let body: ApiErrorBody | null = null;
    try {
      body = (await res.json()) as ApiErrorBody;
    } catch {
      /* non-JSON error */
    }
    throw new ApiError(res.status, body?.error.code ?? "http_error", body?.error.message ?? `Request failed (${res.status})`);
  }
  return (await res.json()) as T;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(BASE + path, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "network_error", "Could not reach the scanner. Check your connection and try again.");
  }
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const err = (data as ApiErrorBody | null)?.error;
    throw new ApiError(res.status, err?.code ?? "http_error", err?.message ?? `Request failed (${res.status})`);
  }
  return data as T;
}

export const auth = {
  login: (password: string) => post<{ logged_in: boolean }>("/api/auth/login", { password }),
  logout: () => post<{ logged_in: boolean }>("/api/auth/logout", {}),
};

export const api = {
  status: (signal?: AbortSignal) => get<Status>("/api/scans/status", signal),
  categorySnapshot: (date: string, session: Session, category: Category, signal?: AbortSignal) =>
    get<CategorySnapshot>(`/api/scans/${date}/${session}/${category}`, signal),
  compare: (date: string, category: Category, signal?: AbortSignal) =>
    get<CompareResult>(`/api/scans/${date}/compare?category=${category}`, signal),
  stockHistory: (symbol: string, from: string, to: string, signal?: AbortSignal) =>
    get<StockHistory>(`/api/stocks/${encodeURIComponent(symbol)}/history?from=${from}&to=${to}`, signal),
};
