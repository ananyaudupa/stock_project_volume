// Mirrors backend/app/schemas. Keep in sync with the API.

export type Category = "small-cap" | "mid-cap" | "large-cap";
export type Session = "morning" | "afternoon";
export type RunStatus = "pending" | "running" | "completed" | "partial" | "failed";

export const CATEGORIES: { value: Category; label: string }[] = [
  { value: "small-cap", label: "Small Cap" },
  { value: "mid-cap", label: "Mid Cap" },
  { value: "large-cap", label: "Large Cap" },
];

export const SESSIONS: { value: Session; label: string; time: string }[] = [
  { value: "morning", label: "Morning", time: "09:20" },
  { value: "afternoon", label: "Afternoon", time: "15:00" },
];

export interface Performance {
  measurement_type: string;
  measurement_time: string;
  measurement_price: number;
  return_pct: number;
}

export interface Pick {
  id: number;
  symbol: string;
  company_name: string;
  cap_category: Category;
  rank: number;
  price_at_scan: number;
  previous_close: number;
  price_change_pct: number;
  direction: "up" | "down" | "flat";
  movement_strength: number;
  intraday_volume: number | null;
  relative_volume: number | null;
  volume_basis: string;
  volume_basis_label: string;
  volume_score: number;
  movement_score: number;
  final_score: number;
  data_timestamp: string;
  selection_reason: string;
  performance: Performance[];
}

export interface RunMeta {
  run_id: number;
  trading_date: string;
  session: Session;
  scan_type: string;
  status: RunStatus;
  scheduled_at: string;
  scan_time: string;
  started_at: string | null;
  completed_at: string | null;
  data_as_of: string | null;
  is_stale: boolean;
  stale_reason: string | null;
  is_mock_data: boolean;
  provider: string;
  algorithm_version: string;
  classification_version: string | null;
  weights: { volume: number; movement: number };
  methodology_note: string;
  message: string | null;
  eligible_counts: Record<string, number>;
  exclusions: Record<string, number>;
}

export interface CategorySnapshot extends RunMeta {
  category: Category;
  stocks: Pick[];
}

export interface SessionSummary {
  status: RunStatus | "none";
  run_id: number | null;
  pick_count: number;
  is_mock_data: boolean | null;
}

export interface LastRun {
  run_id: number;
  trading_date: string;
  session: Session;
  status: RunStatus;
  completed_at: string | null;
  data_as_of: string | null;
  message: string | null;
}

export interface Status {
  now: string;
  today: string;
  is_trading_day: boolean | null;
  non_trading_reason: string | null;
  previous_trading_day: string | null;
  provider: string;
  is_mock_data: boolean;
  last_successful: LastRun | null;
  latest_run: LastRun | null;
  today_sessions: Record<Session, SessionSummary>;
  next_scheduled_scan: string | null;
  data_freshness_seconds: number | null;
  classification_version: string | null;
  calendar_years_loaded: number[];
}

export interface CompareResult {
  trading_date: string;
  category: Category;
  morning: CategorySnapshot | null;
  afternoon: CategorySnapshot | null;
  in_both: string[];
  morning_only: string[];
  afternoon_only: string[];
}

export interface PickWithContext extends Pick {
  trading_date: string;
  session: Session;
  scan_type: string;
  run_id: number;
  is_mock_data: boolean;
}

export interface DailyBar {
  trading_date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface StockHistory {
  symbol: string;
  from_date: string;
  to_date: string;
  picks: PickWithContext[];
  price_history_supported: boolean;
  price_history: DailyBar[];
  price_history_is_mock: boolean;
  note: string | null;
}

export interface ApiErrorBody {
  error: { code: string; message: string; details: Record<string, unknown> };
}
