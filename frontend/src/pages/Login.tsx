// PulseGo login (route "/login"). Posts to /auth/login, persists the JWT + role
// in the store (and localStorage), then routes to /app. Surfaces a clear error
// on 401. Shares the PulseGo brand surface (Cream / Pulse Red / Poppins) with
// the landing page.

import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { login } from "../api";
import { useStore } from "../store";

export default function Login() {
  const navigate = useNavigate();
  const setAuth = useStore((s) => s.setAuth);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await login(email.trim(), password);
      setAuth(res.access_token, res.role ?? null);
      navigate("/app");
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(
        msg.includes("401")
          ? "Invalid email or password."
          : "Could not sign in — please try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="site auth" data-testid="login">
      <header className="site-nav">
        <Link className="pg-logo" to="/">
          <img src="/pulsego.svg" alt="" className="pg-mark" aria-hidden />
          <span className="pg-word">PulseGo</span>
        </Link>
      </header>

      <main className="auth-main">
        <form className="auth-card" onSubmit={onSubmit}>
          <h1 className="auth-title">Welcome back</h1>
          <p className="auth-sub">Sign in to the live operations console.</p>

          <label className="auth-field">
            <span>Email</span>
            <input
              data-testid="login-email"
              type="email"
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@nhs.uk"
              required
            />
          </label>

          <label className="auth-field">
            <span>Password</span>
            <input
              data-testid="login-password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              required
            />
          </label>

          {error && (
            <div className="auth-error" data-testid="login-error" role="alert">
              {error}
            </div>
          )}

          <button
            className="site-btn primary full"
            type="submit"
            data-testid="login-submit"
            disabled={busy}
          >
            {busy ? "Signing in…" : "Sign in →"}
          </button>

          <Link className="auth-back" to="/">← Back to home</Link>
        </form>
      </main>
    </div>
  );
}
