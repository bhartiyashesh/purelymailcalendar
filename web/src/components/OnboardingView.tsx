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
  const [showPwInfo, setShowPwInfo] = useState(false);

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
        <UnofficialNote variant="banner" className="mb-4" />
        <p className="mb-4 text-sm text-ink-600">
          Your password leaves this form only to authenticate against{" "}
          <span className="font-medium text-ink-800">purelymail.com</span> over TLS — for CalDAV (calendar reads/writes),
          SMTP (sending invites from your address), and IMAP (reading RSVPs and inbound invites). It is encrypted at
          rest with a server-only key, never logged, never shared with anyone but Purelymail, and the source is{" "}
          <a
            href="https://github.com/bhartiyashesh/purelymailcalendar"
            target="_blank"
            rel="noopener noreferrer"
            className="font-medium text-accent-700 underline-offset-2 hover:text-accent-900 hover:underline"
          >
            open for you to inspect
          </a>
          .
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
            <div className="flex items-center gap-2">
              <label className="label mb-0">Password</label>
              <button
                type="button"
                onClick={() => setShowPwInfo((v) => !v)}
                aria-expanded={showPwInfo}
                aria-controls="pw-info-panel"
                className="flex h-5 w-5 items-center justify-center rounded-full border border-ink-300 text-[10px] font-semibold text-ink-600 hover:border-accent-500 hover:text-accent-700"
                title="What happens to my password?"
              >
                ?
              </button>
            </div>
            <input
              type="password"
              required
              className="field mt-1"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={passwordPlaceholder}
            />
            <p className="mt-1 text-xs text-ink-500">
              We auto-discover your Purelymail account ID by hitting the WebDAV root with these credentials.
            </p>
            {showPwInfo && (
              <div
                id="pw-info-panel"
                className="mt-2 rounded-md border border-ink-200 bg-ink-50 p-3 text-xs leading-relaxed text-ink-700"
              >
                <p className="font-semibold text-ink-800">What happens to this password</p>
                <ul className="mt-1 list-disc space-y-1 pl-4">
                  <li>
                    Sent over HTTPS straight to{" "}
                    <span className="font-mono text-ink-800">purelymail.com</span> for CalDAV (calendars),{" "}
                    <span className="font-mono text-ink-800">smtp.purelymail.com</span> for outbound mail, and{" "}
                    <span className="font-mono text-ink-800">imap.purelymail.com</span> for inbound mail. Nowhere else.
                  </li>
                  <li>
                    Encrypted at rest with Fernet (AES-128 + HMAC) using a key only the server holds, so the
                    background 5-minute cron can fire reminders and pull new invites for you while you're offline.
                  </li>
                  <li>Never logged, never sent to any third party, never readable in plaintext from the database.</li>
                  <li>
                    Click your initials → <span className="font-medium text-ink-800">Sign out</span> at any time, and
                    the encrypted row is gone in one DELETE. You can also rotate your Purelymail password directly with
                    them — this app will just stop working until you reconnect.
                  </li>
                  <li>
                    Source is public at{" "}
                    <a
                      href="https://github.com/bhartiyashesh/purelymailcalendar"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="font-medium text-accent-700 underline-offset-2 hover:underline"
                    >
                      github.com/bhartiyashesh/purelymailcalendar
                    </a>
                    , so you can verify any claim on this page.
                  </li>
                </ul>
              </div>
            )}
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
