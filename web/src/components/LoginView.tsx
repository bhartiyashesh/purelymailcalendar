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

  return (
    <div className="grid min-h-full grid-cols-1 bg-accent-50 lg:grid-cols-2">
      {/* Left rail: hero image. Hidden on small screens so the form gets
          the whole viewport on mobile. */}
      <aside className="relative hidden overflow-hidden lg:block">
        <img
          src="/signin-hero.jpg"
          alt=""
          className="absolute inset-0 h-full w-full object-cover"
        />
        {/* Subtle coral wash + bottom gradient so the wordmark stays readable
            no matter how the photo crops. */}
        <div className="absolute inset-0 bg-accent-900/10" aria-hidden="true" />
        <div
          className="absolute inset-x-0 bottom-0 h-1/3 bg-gradient-to-t from-accent-900/60 to-transparent"
          aria-hidden="true"
        />
        <div className="relative flex h-full flex-col justify-between p-10">
          <a href="/" className="flex items-start gap-3">
            <img src="/logo.png" alt="" className="mt-0.5 h-9 w-9" />
            <span className="flex flex-col leading-tight">
              <span className="font-serif text-xl text-white drop-shadow-sm">
                Purelymail Calendar
              </span>
              <span className="mt-0.5 text-[11px] uppercase tracking-[0.18em] text-white/85 drop-shadow-sm">
                <span className="font-semibold">Unofficial</span>
                <span className="opacity-70"> &middot; not associated with Purelymail</span>
              </span>
            </span>
          </a>
          <div className="max-w-md text-white">
            <p className="font-serif text-[11px] uppercase tracking-[0.25em] text-white/80">
              Volume i &middot; Sign in
            </p>
            <p className="mt-3 font-serif text-3xl italic leading-tight drop-shadow">
              A calendar for the <span className="not-italic">Purelymail</span> mailbox.
            </p>
            <p className="mt-3 max-w-sm text-sm text-white/85">
              Send real meeting invites, track RSVPs, sync inbound invitations.
              Events live on Purelymail's CalDAV, where they already were.
            </p>
          </div>
        </div>
      </aside>

      {/* Right rail: the actual sign-in form. */}
      <main className="flex flex-col">
        <header className="border-b border-accent-900/20 lg:border-none">
          <div className="flex items-center justify-between px-6 py-4">
            <a href="/" className="flex items-center gap-3 lg:invisible">
              <img src="/logo.png" alt="" className="h-8 w-8" />
              <span className="font-serif text-lg text-accent-900">
                Purelymail Calendar
              </span>
            </a>
            <a
              href="/about"
              className="font-serif text-xs uppercase tracking-[0.2em] text-accent-900/70 hover:text-accent-900"
            >
              About
            </a>
          </div>
        </header>

        <div className="flex flex-1 items-center justify-center px-6 py-12">
          <div className="w-full max-w-sm">
          {sent ? (
            <section className="text-center">
              <h1 className="font-serif text-3xl text-accent-900">Check your email.</h1>
              <p className="mt-3 text-sm text-ink-700">
                A sign-in link is on its way to{" "}
                <span className="font-medium text-accent-900">{email}</span>. It expires in 15 minutes.
              </p>
              <div className="mt-8 flex flex-col gap-2">
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
            <form onSubmit={submit}>
              <div className="text-center">
                <h1 className="font-serif text-3xl text-accent-900">Sign in</h1>
                <p className="mt-2 text-sm text-ink-700">
                  We'll email you a one-time sign-in link.
                </p>
                <p className="mt-1 font-serif text-[11px] uppercase tracking-[0.2em] text-accent-700">
                  For mailboxes hosted at Purelymail
                </p>
              </div>

              <div className="mt-8 space-y-3">
                <div>
                  <label className="label" htmlFor="signin-email">
                    Email
                  </label>
                  <input
                    id="signin-email"
                    type="email"
                    required
                    autoFocus
                    autoComplete="email"
                    className="field"
                    placeholder="you@example.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                  />
                </div>
                {err && (
                  <div className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">
                    {err}
                  </div>
                )}
                <button
                  type="submit"
                  disabled={busy || !email}
                  className="btn-primary w-full"
                >
                  {busy ? "Sending..." : "Send sign-in link"}
                </button>
              </div>

              <p className="mt-6 text-center text-xs text-ink-600">
                Not on Purelymail yet?{" "}
                <a
                  href="https://purelymail.com"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="font-medium text-accent-700 underline-offset-2 hover:text-accent-900 hover:underline"
                >
                  Get a mailbox
                </a>
                . Curious how this works?{" "}
                <a
                  href="/about"
                  className="font-medium text-accent-700 underline-offset-2 hover:text-accent-900 hover:underline"
                >
                  Read the about page
                </a>
                .
              </p>
            </form>
          )}

          <div className="mt-10 border-t border-accent-900/20 pt-4">
            <TrustLine />
          </div>
          <div className="mt-3">
            <UnofficialNote />
          </div>
          </div>
        </div>
      </main>
    </div>
  );
}
