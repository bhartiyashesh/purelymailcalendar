import { useState } from "react";
import type { EventOut } from "../types";
import { fmtRange, partstatStyle } from "../util";

type Props = {
  event: EventOut;
  onEdit: (e: EventOut) => void;
  onCancel: (e: EventOut) => void;
};

export function EventCard({ event, onEdit, onCancel }: Props) {
  const [open, setOpen] = useState(false);
  const counts = event.attendees.reduce<Record<string, number>>((acc, a) => {
    const k = (a.partstat || "NEEDS-ACTION").toUpperCase();
    acc[k] = (acc[k] || 0) + 1;
    return acc;
  }, {});
  return (
    <div className="card overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-ink-50"
      >
        <div className="flex-1 min-w-0">
          <div className="text-xs font-medium uppercase tracking-wide text-ink-500">
            {fmtRange(event.start, event.end, event.tz)}
          </div>
          <div className="truncate text-base font-semibold text-ink-900">{event.summary || "(no title)"}</div>
          {event.location && (
            <div className="truncate text-xs text-ink-500">{event.location}</div>
          )}
        </div>
        <div className="hidden items-center gap-1 sm:flex">
          {Object.entries(counts).map(([k, n]) => (
            <span key={k} className={`pill ${partstatStyle(k)}`}>{n} {k.toLowerCase()}</span>
          ))}
        </div>
        <span className={`ml-2 text-ink-400 transition-transform ${open ? "rotate-90" : ""}`}>›</span>
      </button>
      {open && (
        <div className="border-t border-ink-100 bg-ink-50/40 px-4 py-3">
          {event.description && (
            <p className="mb-3 whitespace-pre-wrap text-sm text-ink-700">{event.description}</p>
          )}
          <div className="grid gap-2 sm:grid-cols-2">
            {event.attendees.length === 0 && (
              <div className="text-sm text-ink-500">(no attendees)</div>
            )}
            {event.attendees.map((a) => (
              <div key={a.email} className="flex items-center justify-between rounded-md border border-ink-200 bg-white px-3 py-2">
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium text-ink-800">{a.name || a.email}</div>
                  {a.name && <div className="truncate text-xs text-ink-500">{a.email}</div>}
                </div>
                <span className={`pill ${partstatStyle(a.partstat)}`}>{a.partstat.toLowerCase()}</span>
              </div>
            ))}
          </div>
          <div className="mt-3 flex items-center justify-between">
            <div className="font-mono text-[10px] text-ink-400">UID {event.uid}</div>
            <div className="flex gap-2">
              <button className="btn-secondary" onClick={() => onEdit(event)}>Edit</button>
              <button className="btn-danger" onClick={() => onCancel(event)}>Cancel event</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
