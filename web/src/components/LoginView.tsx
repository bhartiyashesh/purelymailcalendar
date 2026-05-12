import { useState } from "react";
import { api } from "../api";
import { UnofficialNote } from "./UnofficialNote";

export function LoginView() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      await api.requestLink(email.trim().toLowerCase());
      setSent(true);
    } catch (e: any) {
      setErr(e?.message || "request failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-full flex-col items-center justify-center bg-accent-50 px-4 py-12">
      <div className="card w-full max-w-md p-6">
        <div className="mb-4 flex items-center gap-2">
          <img src="/logo.png" alt="" className="h-10 w-10" />
          <h1 className="text-base font-semibold">Purelymail Calendar</h1>
        </div>
        {sent ? (
          <div>
            <h2 className="mb-1 text-lg font-semibold text-ink-900">Check your email</h2>
            <p className="text-sm text-ink-600">
              A sign-in link is on its way to <span className="font-medium text-ink-800">{email}</span>. It expires in 15 minutes.
            </p>
            <button onClick={() => setSent(false)} className="btn-secondary mt-4">Use a different email</button>
          </div>
        ) : (
          <form onSubmit={submit}>
            <h2 className="mb-1 text-lg font-semibold text-ink-900">Sign in</h2>
            <p className="mb-4 text-sm text-ink-600">
              Enter your email. We'll send a one-time sign-in link.
            </p>
            <label className="label">Email</label>
            <input
              type="email"
              required
              autoFocus
              className="field"
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            {err && (
              <div className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                {err}
              </div>
            )}
            <button type="submit" disabled={busy || !email} className="btn-primary mt-4 w-full">
              {busy ? "Sending..." : "Send sign-in link"}
            </button>
          </form>
        )}
      </div>
      <div className="mt-6 max-w-md text-center">
        <UnofficialNote />
      </div>
    </div>
  );
}
