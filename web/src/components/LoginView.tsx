import { useState } from "react";
import { api } from "../api";
import { TrustLine } from "./TrustLine";
import { UnofficialNote } from "./UnofficialNote";

const STORED_EMAIL_KEY = "pmc.lastSignInEmail";

function readStoredEmail(): string {
  if (typeof window === "undefined") return "";
  try {
    return localStorage.getItem(STORED_EMAIL_KEY) || "";
  } catch {
    return "";
  }
}

function writeStoredEmail(value: string): void {
  try {
    if (value) localStorage.setItem(STORED_EMAIL_KEY, value);
  } catch {
    // localStorage can throw in private windows; non-fatal.
  }
}

export function LoginView() {
  const [email, setEmail] = useState<string>(() => readStoredEmail());
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    const normalized = email.trim().toLowerCase();
    try {
      await api.requestLink(normalized);
      writeStoredEmail(normalized);
      setSent(true);
    } catch (e: any) {
      setErr(e?.message || "request failed");
    } finally {
      setBusy(false);
    }
  }

  const todayLabel = new Intl.DateTimeFormat(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
  }).format(new Date());

  return (
    <div className="flex min-h-full flex-col items-center bg-accent-50 px-6 py-16 sm:py-24">
      <div className="w-full max-w-xl">
        <div className="flex items-baseline justify-between border-b border-accent-900/30 pb-3">
          <div className="flex items-center gap-3">
            <img src="/logo.png" alt="" className="h-8 w-8" />
            <span className="font-serif text-xl text-accent-900">Purelymail Calendar</span>
          </div>
          <span className="hidden font-serif text-sm italic text-accent-900/70 sm:inline">
            {todayLabel}
          </span>
        </div>

        {sent ? (
          <section className="pt-10 sm:pt-14">
            <p className="font-serif text-xs uppercase tracking-[0.25em] text-accent-700">
              Volume i &middot; Notice
            </p>
            <h1 className="mt-3 font-serif text-4xl leading-tight text-accent-900 sm:text-5xl">
              Check your email.
            </h1>
            <p className="mt-5 max-w-prose font-serif text-lg italic text-ink-700">
              A sign-in link is on its way to{" "}
              <span className="not-italic text-accent-900">{email}</span>. It expires in
              fifteen minutes.
            </p>
            <div className="mt-8 flex flex-col gap-2 sm:max-w-sm">
              <a
                href="https://inbox.purelymail.com/"
                target="_blank"
                rel="noopener noreferrer"
                className="btn-primary inline-flex w-full items-center justify-center"
              >
                Go to webmail
              </a>
              <button onClick={() => setSent(false)} className="btn-secondary w-full">
                Use a different email
              </button>
            </div>
          </section>
        ) : (
          <form onSubmit={submit} className="pt-10 sm:pt-14">
            <p className="font-serif text-xs uppercase tracking-[0.25em] text-accent-700">
              Volume i &middot; Sign in
            </p>
            <h1 className="mt-3 font-serif text-4xl leading-tight text-accent-900 sm:text-5xl">
              A calendar for your{" "}
              <span className="italic">Purelymail</span> mailbox.
            </h1>
            <p className="mt-5 max-w-prose font-serif text-lg italic text-ink-700">
              Enter your email. We'll send a one-time sign-in link. Works only with
              mailboxes hosted at Purelymail.
            </p>

            <div className="mt-10 max-w-md">
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
                <div className="mt-3 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">
                  {err}
                </div>
              )}
              <button
                type="submit"
                disabled={busy || !email}
                className="btn-primary mt-5 w-full"
              >
                {busy ? "Sending..." : "Send sign-in link"}
              </button>
            </div>
          </form>
        )}

        <div className="mt-16 border-t border-accent-900/20 pt-6">
          <TrustLine />
        </div>
        <div className="mt-3 max-w-prose">
          <p className="font-serif text-sm italic leading-relaxed text-ink-700">
            A free calendar and meeting-invite app for{" "}
            <span className="not-italic text-accent-900">Purelymail</span> mailboxes.
            Send iTIP invitations to Gmail, Apple Mail, and Outlook and have RSVPs
            flow back into your calendar automatically.{" "}
            <a
              href="/about"
              className="not-italic font-medium text-accent-700 underline-offset-2 hover:text-accent-900 hover:underline"
            >
              Learn more
            </a>
            .
          </p>
        </div>
        <div className="mt-6">
          <UnofficialNote />
        </div>
      </div>
    </div>
  );
}
