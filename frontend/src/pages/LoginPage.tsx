import { useState, type FormEvent } from "react";
import { ApiError, auth } from "../api/client";

export function LoginPage({ onSuccess }: { onSuccess: () => void }) {
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await auth.login(password);
      onSuccess();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
      setBusy(false);
    }
  }

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={submit}>
        <h1>NSE Daily Scanner</h1>
        <p className="muted">Enter the password to see today's scans.</p>
        <label htmlFor="pw" className="login-label">
          Password
        </label>
        <input
          id="pw"
          type="password"
          autoComplete="current-password"
          autoFocus
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
        {error && (
          <p className="login-error" role="alert">
            {error}
          </p>
        )}
        <button className="btn-primary" type="submit" disabled={busy || !password}>
          {busy ? "Checking…" : "Open scanner"}
        </button>
        <p className="muted small">You'll stay signed in on this device for 30 days.</p>
      </form>
    </div>
  );
}
