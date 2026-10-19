import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../api/client";

export type ApiState<T> =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "success"; data: T }
  | { kind: "error"; error: ApiError };

/** Fetch on key change; aborts stale requests so a slow response can never overwrite a newer selection. */
export function useApi<T>(key: string | null, fetcher: (signal: AbortSignal) => Promise<T>) {
  const [state, setState] = useState<ApiState<T>>({ kind: key ? "loading" : "idle" });
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    if (!key) {
      setState({ kind: "idle" });
      return;
    }
    const ctrl = new AbortController();
    setState({ kind: "loading" });
    fetcher(ctrl.signal)
      .then((data) => setState({ kind: "success", data }))
      .catch((e: unknown) => {
        if ((e as Error).name === "AbortError") return;
        const err = e instanceof ApiError ? e : new ApiError(0, "unknown_error", String(e));
        setState({ kind: "error", error: err });
      });
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return [state, reload] as const;
}
