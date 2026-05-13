import { useEffect, useState } from "react";

type VersionInfo = {
  commit: string;
  short: string;
  built_at: string;
  commit_url: string | null;
};

/**
 * Quiet "(not affiliated with Purelymail)" line that sits under the app
 * title on auth-adjacent pages. Includes a `trust but verify` toggle
 * that expands a small inline panel listing the chain of evidence: open
 * source, public CI build log, public image registry, /api/version SHA.
 */
export function TrustLine({ className = "" }: { className?: string }) {
  const [open, setOpen] = useState(false);
  const [info, setInfo] = useState<VersionInfo | null>(null);

  useEffect(() => {
    if (!open) return;
    if (info) return;
    fetch("/api/version")
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data) setInfo(data);
      })
      .catch(() => undefined);
  }, [open, info]);

  return (
    <div className={className}>
      <p className="text-[11px] text-ink-500">
        (not affiliated with Purelymail{" · "}
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          aria-controls="trust-panel"
          className="font-medium text-accent-700 underline-offset-2 hover:underline"
        >
          {open ? "hide" : "trust but verify"}
        </button>
        )
      </p>
      {open && (
        <div
          id="trust-panel"
          className="mt-2 rounded-md border border-ink-200 bg-ink-50 p-3 text-[11px] leading-relaxed text-ink-700"
        >
          <p className="mb-1 font-semibold text-ink-800">Why you can trust this build</p>
          <ul className="list-disc space-y-1 pl-4">
            <li>
              Source is fully open at{" "}
              <a
                href="https://github.com/bhartiyashesh/purelymailcalendar"
                target="_blank"
                rel="noopener noreferrer"
                className="font-medium text-accent-700 underline-offset-2 hover:underline"
              >
                github.com/bhartiyashesh/purelymailcalendar
              </a>
              .
            </li>
            <li>
              Every push to <span className="font-mono">main</span> is built by GitHub Actions; the build log is publicly visible on the repo's Actions tab.
            </li>
            <li>
              The container image is pushed to{" "}
              <span className="font-mono">ghcr.io/bhartiyashesh/purelymailcalendar</span> so anyone can <span className="font-mono">docker pull</span> the exact bytes running on this site.
            </li>
            <li>
              The running build reports its commit at{" "}
              <a
                href="/api/version"
                target="_blank"
                rel="noopener noreferrer"
                className="font-medium text-accent-700 underline-offset-2 hover:underline"
              >
                /api/version
              </a>
              {info?.short && info.short !== "unknown" ? (
                <>
                  {" "}
                  ({info.commit_url ? (
                    <a
                      href={info.commit_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="font-mono font-medium text-accent-700 underline-offset-2 hover:underline"
                    >
                      {info.short}
                    </a>
                  ) : (
                    <span className="font-mono font-medium">{info.short}</span>
                  )}
                  {info.built_at && info.built_at !== "unknown" ? `, built ${info.built_at}` : ""})
                </>
              ) : null}
              {" "}
              — compare it to the public commit history on GitHub.
            </li>
            <li>
              Prefer to keep credentials on your own machine? Self-host with{" "}
              <span className="font-mono">docker compose up</span> using the{" "}
              <a
                href="https://github.com/bhartiyashesh/purelymailcalendar/blob/main/docker-compose.yml"
                target="_blank"
                rel="noopener noreferrer"
                className="font-medium text-accent-700 underline-offset-2 hover:underline"
              >
                compose file in the repo
              </a>
              .
            </li>
          </ul>
        </div>
      )}
    </div>
  );
}
