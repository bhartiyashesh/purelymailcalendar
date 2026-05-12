import { useEffect, useMemo, useState } from "react";
import type { EventIn, EventOut } from "../types";
import { toLocalIsoMinute } from "../util";

const COMMON_TZS = [
  "America/Chicago",
  "America/New_York",
  "America/Los_Angeles",
  "America/Denver",
  "Europe/London",
  "Europe/Berlin",
  "Asia/Kolkata",
  "Asia/Tokyo",
  "Australia/Sydney",
  "UTC",
];

type Mode = "create" | "edit";

type Props = {
  mode: Mode;
  initial?: EventOut | null;
  prefillStart?: Date | null;
  prefillDurationMinutes?: number | null;
  defaultAccount: string;
  defaultCalendar: string;
  onClose: () => void;
  onSubmit: (
    body: EventIn,
    mode: Mode,
    uid: string | null
  ) => Promise<void>;
};

type AttRow = { email: string; name: string };

function attendeesFrom(initial?: EventOut | null): AttRow[] {
  if (!initial || initial.attendees.length === 0) return [{ email: "", name: "" }];
  return initial.attendees.map((a) => ({ email: a.email, name: a.name || "" }));
}

function defaultStart(): string {
  const d = new Date();
  d.setMinutes(0, 0, 0);
  d.setHours(d.getHours() + 1);
  return toLocalIsoMinute(d);
}

function durationFrom(initial?: EventOut | null): number {
  if (!initial) return 60;
  const ms = new Date(initial.end).getTime() - new Date(initial.start).getTime();
  return Math.max(15, Math.round(ms / 60000));
}

function localFromIso(iso: string): string {
  return toLocalIsoMinute(new Date(iso));
}

export function EventForm({ mode, initial, prefillStart, prefillDurationMinutes, defaultAccount, defaultCalendar, onClose, onSubmit }: Props) {
  const [summary, setSummary] = useState(initial?.summary || "");
  const [start, setStart] = useState(
    initial ? localFromIso(initial.start) : prefillStart ? toLocalIsoMinute(prefillStart) : defaultStart()
  );
  const [duration, setDuration] = useState(
    initial ? durationFrom(initial) : prefillDurationMinutes ?? 60
  );
  const guessedTz = useMemo(() => Intl.DateTimeFormat().resolvedOptions().timeZone, []);
  const [tz, setTz] = useState(initial?.tz || guessedTz || "America/Chicago");
  const [location, setLocation] = useState(initial?.location || "");
  const [description, setDescription] = useState(initial?.description || "");
  const [attendees, setAttendees] = useState<AttRow[]>(attendeesFrom(initial));
  const [dryRun, setDryRun] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  function updateAttendee(i: number, patch: Partial<AttRow>) {
    setAttendees((rows) => rows.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));
  }
  function addAttendee() {
    setAttendees((rows) => [...rows, { email: "", name: "" }]);
  }
  function removeAttendee(i: number) {
    setAttendees((rows) => (rows.length === 1 ? [{ email: "", name: "" }] : rows.filter((_, idx) => idx !== i)));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    if (!summary.trim()) {
      setErr("Title is required");
      return;
    }
    if (!start) {
      setErr("Start time is required");
      return;
    }
    const body: EventIn = {
      account: defaultAccount || undefined,
      calendar: defaultCalendar || undefined,
      summary: summary.trim(),
      start,
      duration_minutes: duration,
      tz,
      location: location.trim(),
      description,
      attendees: attendees
        .map((r) => ({ email: r.email.trim(), name: r.name.trim() || undefined }))
        .filter((r) => !!r.email),
      dry_run: dryRun,
      uid: initial?.uid,
      sequence: initial?.sequence,
    };
    setBusy(true);
    try {
      await onSubmit(body, mode, initial?.uid || null);
      onClose();
    } catch (e: any) {
      setErr(e?.message || "request failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-40">
      <div className="absolute inset-0 bg-ink-900/30" onClick={onClose} />
      <form
        onSubmit={submit}
        className="absolute right-0 top-0 flex h-full w-full max-w-xl flex-col bg-white shadow-xl"
      >
        <div className="flex items-center justify-between border-b border-ink-200 px-5 py-3">
          <h2 className="text-base font-semibold">
            {mode === "edit" ? "Edit event" : "New event"}
          </h2>
          <button type="button" onClick={onClose} className="text-ink-500 hover:text-ink-800" aria-label="close">×</button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4">
          <div className="grid gap-4">
            <div>
              <label className="label">Title</label>
              <input
                className="field"
                placeholder="Verus walk-through"
                value={summary}
                onChange={(e) => setSummary(e.target.value)}
                autoFocus
              />
            </div>
            <div className="grid grid-cols-12 gap-3">
              <div className="col-span-6">
                <label className="label">Start</label>
                <input
                  type="datetime-local"
                  className="field"
                  value={start}
                  onChange={(e) => setStart(e.target.value)}
                />
              </div>
              <div className="col-span-3">
                <label className="label">Duration (min)</label>
                <input
                  type="number"
                  min={15}
                  step={15}
                  className="field"
                  value={duration}
                  onChange={(e) => setDuration(Number(e.target.value))}
                />
              </div>
              <div className="col-span-3">
                <label className="label">Time zone</label>
                <select className="field" value={tz} onChange={(e) => setTz(e.target.value)}>
                  {[tz, ...COMMON_TZS.filter((t) => t !== tz)].map((t) => (
                    <option key={t} value={t}>{t}</option>
                  ))}
                </select>
              </div>
            </div>
            <div>
              <label className="label">Location / link</label>
              <input
                className="field"
                placeholder="https://meet.example.com/abc"
                value={location}
                onChange={(e) => setLocation(e.target.value)}
              />
            </div>
            <div>
              <label className="label">Description</label>
              <textarea
                rows={4}
                className="field"
                placeholder="Agenda, prep notes, links"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </div>
            <div>
              <div className="mb-2 flex items-center justify-between">
                <label className="label mb-0">Attendees</label>
                <button type="button" className="text-xs font-medium text-accent-600 hover:text-accent-700" onClick={addAttendee}>
                  + add
                </button>
              </div>
              <div className="flex flex-col gap-2">
                {attendees.map((row, i) => (
                  <div key={i} className="grid grid-cols-12 gap-2">
                    <input
                      className="field col-span-6"
                      placeholder="email@example.com"
                      value={row.email}
                      onChange={(e) => updateAttendee(i, { email: e.target.value })}
                    />
                    <input
                      className="field col-span-5"
                      placeholder="Name (optional)"
                      value={row.name}
                      onChange={(e) => updateAttendee(i, { name: e.target.value })}
                    />
                    <button
                      type="button"
                      className="btn-secondary col-span-1"
                      onClick={() => removeAttendee(i)}
                      aria-label="remove"
                    >
                      ×
                    </button>
                  </div>
                ))}
              </div>
            </div>
            <label className="inline-flex items-center gap-2 text-sm text-ink-600">
              <input
                type="checkbox"
                checked={dryRun}
                onChange={(e) => setDryRun(e.target.checked)}
                className="h-4 w-4 rounded border-ink-300 text-accent-600 focus:ring-accent-500"
              />
              Dry run (write to CalDAV but do not send email)
            </label>
            {err && (
              <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                {err}
              </div>
            )}
          </div>
        </div>
        <div className="flex items-center justify-end gap-2 border-t border-ink-200 px-5 py-3">
          <button type="button" className="btn-secondary" onClick={onClose}>Cancel</button>
          <button type="submit" disabled={busy} className="btn-primary">
            {busy ? "Sending..." : mode === "edit" ? "Save & resend" : "Create & send invite"}
          </button>
        </div>
      </form>
    </div>
  );
}
