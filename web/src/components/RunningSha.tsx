import { useEffect, useState } from "react";

type VersionInfo = {
  commit: string;
  short: string;
  built_at: string;
  commit_url: string | null;
};

/**
 * Tiny footer badge that fetches /api/version once on mount and shows the
 * git SHA the running container was built from, linked to the public
 * commit on GitHub. Lets anyone audit the deploy against the source.
 */
export function RunningSha({ className = "" }: { className?: string }) {
  const [info, setInfo] = useState<VersionInfo | null>(null);

  useEffect(() => {
    fetch("/api/version")
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data) setInfo(data);
      })
      .catch(() => undefined);
  }, []);

  if (!info || !info.short || info.short === "unknown") {
    return null;
  }
  return (
    <span className={`text-[11px] text-ink-500 ${className}`}>
      Running{" "}
      {info.commit_url ? (
        <a
          href={info.commit_url}
          target="_blank"
          rel="noopener noreferrer"
          className="font-mono font-medium text-ink-700 underline-offset-2 hover:text-accent-700 hover:underline"
          title={`Built at ${info.built_at}. Click to view commit on GitHub.`}
        >
          {info.short}
        </a>
      ) : (
        <span className="font-mono font-medium text-ink-700">{info.short}</span>
      )}
    </span>
  );
}
