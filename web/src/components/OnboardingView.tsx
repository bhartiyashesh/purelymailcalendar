import { useMemo, useState } from "react";
import { api } from "../api";
import type { Me } from "../types";
import { UnofficialNote } from "./UnofficialNote";

type Props = {
  me: Me;
  onConnected: () => void;
  onLogout: () => void;
};

function brandFromEmail(email: string): string | null {
  const at = email.indexOf("@");
  if (at < 0) return null;
  const host = email.slice(at + 1).trim();
  if (!host) return null;
  // first label before the dot, capitalized for display
  const first = host.split(".")[0];
  if (!first) return null;
  return first.charAt(0).toUpperCase() + first.slice(1);
}

export function OnboardingView({ me, onConnected, onLogout }: Props) {
  const [email, setEmail] = useState(me.email);
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState(me.display_name || "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const brand = useMemo(() => brandFromEmail(email), [email]);
  const passwordPlaceholder = brand ? `Your ${brand} email password` : "Your mailbox password";

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      await api.connectMailbox(email.trim().toLowerCase(), password, displayName.trim() || undefined);
      onConnected();
    } catch (e: any) {
      setErr(e?.message || "could not connect");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-full flex-col items-center bg-accent-50 px-4 py-12">
      <div className="card w-full max-w-lg p-6">
        <div className="mb-4 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <img src="/logo.png" alt="" className="h-8 w-8" />
            <h1 className="text-base font-semibold">Connect your Purelymail mailbox</h1>
          </div>
          <button onClick={onLogout} className="text-xs text-ink-500 hover:text-ink-800">Sign out</button>
        </div>
        <p className="mb-4 text-sm text-ink-600">
          We use this to read and write your calendar, send invites from your address, and pull RSVPs from your inbox.
          Your password is encrypted at rest. We never log it.
        </p>
        <form onSubmit={submit} className="grid gap-3">
          <div>
            <label className="label">Purelymail email</label>
            <input
              type="email"
              required
              className="field"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@yourdomain.com"
            />
          </div>
          <div>
            <label className="label">Password</label>
            <input
              type="password"
              required
              className="field"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={passwordPlaceholder}
            />
            <p className="mt-1 text-xs text-ink-500">
              We auto-discover your Purelymail account ID by hitting the WebDAV root with these credentials.
            </p>
          </div>
          <div>
            <label className="label">Display name (shown on invites)</label>
            <input
              className="field"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="Yashesh Bharti"
            />
          </div>
          {err && (
            <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>
          )}
          <button type="submit" disabled={busy} className="btn-primary mt-1">
            {busy ? "Connecting..." : "Connect mailbox"}
          </button>
        </form>
      </div>
      <div className="mt-6 max-w-lg text-center">
        <UnofficialNote />
      </div>
    </div>
  );
}
