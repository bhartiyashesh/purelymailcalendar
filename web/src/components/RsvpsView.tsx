import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import type { RsvpResultOut } from "../types";
import { partstatStyle } from "../util";

type Props = {
  account: string;
  calendar: string;
  onError: (msg: string) => void;
  onSuccess: (msg: string) => void;
};

type EventGroup = {
  uid: string;
  summary: string;
  applied: RsvpResultOut[];
  skippedCount: number;
  failedDetails: string[];
};

function groupByEvent(results: RsvpResultOut[]): EventGroup[] {
  const map = new Map<string, EventGroup>();
  for (const r of results) {
    const key = r.uid || r.summary;
    let g = map.get(key);
    if (!g) {
      g = { uid: r.uid, summary: r.summary || "(no title)", applied: [], skippedCount: 0, failedDetails: [] };
      map.set(key, g);
    }
    if (r.success) {
      g.applied.push(r);
    } else {
      g.skippedCount += 1;
      // Surface real failure detail (e.g. "event not found"), suppress
      // the boring "no changes / already applied" noise.
      if (r.detail && !/already applied/i.test(r.detail)) {
        g.failedDetails.push(r.detail);
      }
    }
  }
  return Array.from(map.values());
}

export function RsvpsView({ account, calendar, onError, onSuccess }: Props) {
  const [mailbox, setMailbox] = useState("INBOX");
  const [onlyUnseen, setOnlyUnseen] = useState(true);
  const [markSeen, setMarkSeen] = useState(true);
  const [results, setResults] = useState<RsvpResultOut[]>([]);
  const [busy, setBusy] = useState(false);
  const [lastRunMailbox, setLastRunMailbox] = useState<string | null>(null);

  const groups = useMemo(() => groupByEvent(results), [results]);
  const autoPolledRef = useRef(false);

  async function poll() {
    setBusy(true);
    try {
      const out = await api.pollRsvps({
        account: account || undefined,
        calendar: calendar || undefined,
        mailbox,
        only_unseen: onlyUnseen,
        mark_seen: markSeen,
      });
      setResults(out.results);
      setLastRunMailbox(out.mailbox);
      const applied = out.results.filter((r) => r.success).length;
      onSuccess(
        applied === 0
          ? `Polled ${out.mailbox}. No new RSVPs to apply.`
          : `Polled ${out.mailbox}. Applied ${applied} RSVP${applied === 1 ? "" : "s"}.`
      );
    } catch (e: any) {
      onError(e?.message || "RSVP poll failed");
    } finally {
      setBusy(false);
    }
  }

  // Auto-poll on first mount so the tab isn't empty.
  useEffect(() => {
    if (autoPolledRef.current) return;
    autoPolledRef.current = true;
    poll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <section>
      <div className="card mb-4 p-4">
        <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-ink-500">Poll IMAP for replies</h3>
        <div className="grid items-end gap-3 sm:grid-cols-12">
          <div className="sm:col-span-4">
            <label className="label">Mailbox</label>
            <input
              className="field"
              value={mailbox}
              onChange={(e) => setMailbox(e.target.value)}
              placeholder="INBOX or RSVPs"
            />
          </div>
          <label className="inline-flex items-center gap-2 text-sm text-ink-600 sm:col-span-3">
            <input
              type="checkbox"
              checked={onlyUnseen}
              onChange={(e) => setOnlyUnseen(e.target.checked)}
              className="h-4 w-4 rounded border-ink-300 text-accent-600 focus:ring-accent-500"
            />
            Only unseen
          </label>
          <label className="inline-flex items-center gap-2 text-sm text-ink-600 sm:col-span-3">
            <input
              type="checkbox"
              checked={markSeen}
              onChange={(e) => setMarkSeen(e.target.checked)}
              className="h-4 w-4 rounded border-ink-300 text-accent-600 focus:ring-accent-500"
            />
            Mark seen
          </label>
          <div className="sm:col-span-2 flex justify-end">
            <button onClick={poll} disabled={busy} className="btn-primary w-full">
              {busy ? "Polling..." : "Poll now"}
            </button>
          </div>
        </div>
        <p className="mt-2 text-xs text-ink-500">
          Set up Sieve to file replies into a dedicated <code className="font-mono text-ink-700">RSVPs</code> mailbox so the poller scans a smaller, focused folder.
        </p>
      </div>

      {lastRunMailbox && (
        <div className="mb-3 text-sm text-ink-500">
          Last run scanned <span className="font-medium text-ink-800">{lastRunMailbox}</span>
        </div>
      )}

      {groups.length === 0 ? (
        <div className="card px-4 py-10 text-center text-sm text-ink-500">
          No results yet. Click <span className="font-medium text-ink-700">Poll now</span> to scan for METHOD:REPLY messages.
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {groups.map((g) => (
            <div key={g.uid || g.summary} className="card overflow-hidden">
              <div className="flex items-center justify-between border-b border-ink-100 bg-accent-50/40 px-4 py-2">
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold text-ink-900">{g.summary}</div>
                  {g.uid && (
                    <div className="truncate font-mono text-[10px] text-ink-400">UID {g.uid}</div>
                  )}
                </div>
                <div className="flex shrink-0 items-center gap-1.5">
                  <span className="pill bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200">
                    {g.applied.length} applied
                  </span>
                  {g.skippedCount > 0 && (
                    <span className="pill bg-ink-100 text-ink-600 ring-1 ring-ink-200">
                      {g.skippedCount} unchanged
                    </span>
                  )}
                </div>
              </div>
              {g.applied.length > 0 && (
                <ul className="divide-y divide-ink-100">
                  {g.applied.map((r, i) => (
                    <li key={i} className="flex items-center justify-between px-4 py-2 text-sm">
                      <span className="truncate font-medium text-ink-800">{r.attendee}</span>
                      <span className={`pill ${partstatStyle(r.partstat)}`}>{r.partstat.toLowerCase()}</span>
                    </li>
                  ))}
                </ul>
              )}
              {g.failedDetails.length > 0 && (
                <div className="border-t border-amber-200 bg-amber-50 px-4 py-2 text-xs text-amber-800">
                  {g.failedDetails.map((d, i) => (
                    <div key={i}>{d}</div>
                  ))}
                </div>
              )}
              {g.applied.length === 0 && g.failedDetails.length === 0 && (
                <div className="px-4 py-2 text-xs text-ink-500">
                  No new responses for this event since the last poll.
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
