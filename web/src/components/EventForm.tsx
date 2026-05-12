import { useEffect, useMemo, useState } from "react";
import type { EventIn, EventOut, RecurrenceFreq, RecurrenceIn, ReminderIn } from "../types";
import { toLocalIsoMinute } from "../util";

type RepeatEnd = "never" | "on" | "after";
type RepeatRow = {
  freq: RecurrenceFreq;
  interval: number;
  end: RepeatEnd;
  until: string; // YYYY-MM-DD when end="on"
  count: number; // when end="after"
};

const DEFAULT_REPEAT: RepeatRow = {
  freq: "WEEKLY",
  interval: 1,
  end: "never",
  until: "",
  count: 10,
};

function repeatFromInitial(initial?: EventOut | null): { enabled: boolean; row: RepeatRow } {
  const rec = initial?.recurrence;
  if (!rec) return { enabled: false, row: DEFAULT_REPEAT };
  return {
    enabled: true,
    row: {
      freq: rec.freq,
      interval: rec.interval || 1,
      end: rec.until ? "on" : rec.count ? "after" : "never",
      until: rec.until || "",
      count: rec.count || 10,
    },
  };
}

function repeatSummary(r: RepeatRow): string {
  const noun = { DAILY: "day", WEEKLY: "week", MONTHLY: "month", YEARLY: "year" }[r.freq];
  const base = r.interval === 1
    ? `Every ${noun}`
    : `Every ${r.interval} ${noun}s`;
  if (r.end === "on" && r.until) {
    const d = new Date(r.until + "T00:00:00");
    return `${base}, until ${d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}`;
  }
  if (r.end === "after") return `${base}, ${r.count} times`;
  return base;
}

type ReminderRow = {
  popup: boolean;
  email: boolean;
  allAttendees: boolean;
  amount: number;
  unit: "minutes" | "hours" | "days";
  recipients: string;
};

const REMINDER_UNIT_MIN = { minutes: 1, hours: 60, days: 60 * 24 } as const;

function toMinutes(r: ReminderRow): number {
  return Math.max(0, Math.round(r.amount * REMINDER_UNIT_MIN[r.unit]));
}

function fromMinutes(n: number): { amount: number; unit: ReminderRow["unit"] } {
  if (n % (60 * 24) === 0 && n >= 60 * 24) return { amount: n / (60 * 24), unit: "days" };
  if (n % 60 === 0 && n >= 60) return { amount: n / 60, unit: "hours" };
  return { amount: n, unit: "minutes" };
}

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

// Snap a `YYYY-MM-DDTHH:MM` local-iso string DOWN to the nearest 5-min slot.
// Keeps the reminder scheduler (5-min Railway cron tick) aligned with what
// the user actually sees in the form.
function snapToFive(local: string): string {
  const m = local.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/);
  if (!m) return local;
  const [, y, mo, d, hh, mm] = m;
  const snapped = String(Math.floor(parseInt(mm, 10) / 5) * 5).padStart(2, "0");
  return `${y}-${mo}-${d}T${hh}:${snapped}`;
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
    snapToFive(
      initial ? localFromIso(initial.start) : prefillStart ? toLocalIsoMinute(prefillStart) : defaultStart()
    )
  );
  const [duration, setDuration] = useState(
    initial ? durationFrom(initial) : prefillDurationMinutes ?? 60
  );
  const guessedTz = useMemo(() => Intl.DateTimeFormat().resolvedOptions().timeZone, []);
  const [tz, setTz] = useState(initial?.tz || guessedTz || "America/Chicago");
  const [location, setLocation] = useState(initial?.location || "");
  const [description, setDescription] = useState(initial?.description || "");
  const [attendees, setAttendees] = useState<AttRow[]>(attendeesFrom(initial));
  const [reminders, setReminders] = useState<ReminderRow[]>(
    initial ? [] : [{ popup: true, email: false, allAttendees: true, amount: 15, unit: "minutes", recipients: "" }]
  );
  const initialRepeat = useMemo(() => repeatFromInitial(initial), [initial]);
  const [repeatEnabled, setRepeatEnabled] = useState<boolean>(initialRepeat.enabled);
  const [repeat, setRepeat] = useState<RepeatRow>(initialRepeat.row);
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
    // Snap event start time DOWN to the nearest 5-min slot so reminder fire
    // times align with our 5-min Railway cron tick.
    const snappedStart = (() => {
      const m = start.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/);
      if (!m) return start;
      const [, y, mo, d, hh, mm] = m;
      const minutes = parseInt(mm, 10);
      const snapped = String(Math.floor(minutes / 5) * 5).padStart(2, "0");
      return `${y}-${mo}-${d}T${hh}:${snapped}`;
    })();

    let recurrence: RecurrenceIn | null = null;
    if (repeatEnabled) {
      recurrence = {
        freq: repeat.freq,
        interval: Math.max(1, repeat.interval | 0),
      };
      if (repeat.end === "on" && repeat.until) {
        recurrence.until = repeat.until;
      } else if (repeat.end === "after") {
        recurrence.count = Math.max(1, repeat.count | 0);
      }
    }

    const body: EventIn = {
      account: defaultAccount || undefined,
      calendar: defaultCalendar || undefined,
      summary: summary.trim(),
      start: snappedStart,
      duration_minutes: duration,
      tz,
      location: location.trim(),
      description,
      recurrence,
      attendees: attendees
        .map((r) => ({ email: r.email.trim(), name: r.name.trim() || undefined }))
        .filter((r) => !!r.email),
      reminders: reminders.flatMap<ReminderIn>((r) => {
        const out: ReminderIn[] = [];
        const minutes_before = toMinutes(r);
        if (r.popup) {
          out.push({ action: "DISPLAY", minutes_before, recipients: [] });
        }
        if (r.email) {
          const attendeeEmails = attendees
            .map((a) => a.email.trim())
            .filter(Boolean);
          const typed = r.recipients
            .split(/[,\s]+/)
            .map((x) => x.trim())
            .filter(Boolean);
          const recipients = r.allAttendees ? attendeeEmails : typed;
          out.push({ action: "EMAIL", minutes_before, recipients });
        }
        return out;
      }),
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
                  step={300}
                  value={start}
                  onChange={(e) => setStart(snapToFive(e.target.value))}
                />
                <p className="mt-1 text-xs text-ink-500">
                  Snaps to 5-minute slots (e.g. 11:13 becomes 11:10).
                </p>
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
              <label className="inline-flex items-center gap-2 text-sm font-medium text-ink-800">
                <input
                  type="checkbox"
                  checked={repeatEnabled}
                  onChange={(e) => setRepeatEnabled(e.target.checked)}
                  className="h-4 w-4 rounded border-ink-300 text-accent-600 focus:ring-accent-500"
                />
                Repeat
              </label>
              {repeatEnabled && (
                <div className="mt-2 space-y-2 rounded-md border border-ink-200 bg-ink-50 p-3">
                  <div className="grid grid-cols-12 items-center gap-2">
                    <label className="col-span-3 text-xs text-ink-600">Every</label>
                    <input
                      type="number"
                      min={1}
                      max={365}
                      className="field col-span-3"
                      value={repeat.interval}
                      onChange={(e) =>
                        setRepeat((r) => ({ ...r, interval: Math.max(1, Number(e.target.value) || 1) }))
                      }
                    />
                    <select
                      className="field col-span-6"
                      value={repeat.freq}
                      onChange={(e) => setRepeat((r) => ({ ...r, freq: e.target.value as RecurrenceFreq }))}
                    >
                      <option value="DAILY">day(s)</option>
                      <option value="WEEKLY">week(s)</option>
                      <option value="MONTHLY">month(s)</option>
                      <option value="YEARLY">year(s)</option>
                    </select>
                  </div>
                  <div className="grid grid-cols-12 items-center gap-2">
                    <label className="col-span-3 text-xs text-ink-600">Ends</label>
                    <select
                      className="field col-span-3"
                      value={repeat.end}
                      onChange={(e) => setRepeat((r) => ({ ...r, end: e.target.value as RepeatEnd }))}
                    >
                      <option value="never">never</option>
                      <option value="on">on date</option>
                      <option value="after">after N times</option>
                    </select>
                    {repeat.end === "on" && (
                      <input
                        type="date"
                        className="field col-span-6"
                        value={repeat.until}
                        onChange={(e) => setRepeat((r) => ({ ...r, until: e.target.value }))}
                      />
                    )}
                    {repeat.end === "after" && (
                      <input
                        type="number"
                        min={1}
                        max={1000}
                        className="field col-span-6"
                        value={repeat.count}
                        onChange={(e) =>
                          setRepeat((r) => ({ ...r, count: Math.max(1, Number(e.target.value) || 1) }))
                        }
                      />
                    )}
                    {repeat.end === "never" && <div className="col-span-6" />}
                  </div>
                  <p className="text-xs text-ink-600">{repeatSummary(repeat)}</p>
                  <p className="text-xs text-ink-500">
                    Email reminders fire before each occurrence. The email includes confirm/cancel buttons so you can drop a single occurrence without touching the rest of the series.
                  </p>
                </div>
              )}
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
            <div>
              <div className="mb-2 flex items-center justify-between">
                <label className="label mb-0">Reminders</label>
                <button
                  type="button"
                  className="text-xs font-medium text-accent-600 hover:text-accent-700"
                  onClick={() =>
                    setReminders((rows) => [
                      ...rows,
                      { popup: true, email: false, allAttendees: true, amount: 15, unit: "minutes", recipients: "" },
                    ])
                  }
                >
                  + add
                </button>
              </div>
              <p className="mb-2 text-xs text-ink-500">
                Popup reminders fire on each attendee's calendar app automatically.
                Email reminders are sent by our scheduler at the right moment to the recipients you list.
                Minute-level offsets snap to multiples of 5 to match our 5-minute scheduler tick.
              </p>
              <div className="flex flex-col gap-2">
                {reminders.length === 0 && (
                  <div className="text-xs text-ink-500">No reminders. Click "+ add" to set one.</div>
                )}
                {reminders.map((row, i) => (
                  <div key={i} className="rounded-md border border-ink-200 bg-white p-2">
                    <div className="grid grid-cols-12 items-center gap-2">
                      <div className="col-span-4 flex items-center gap-3 text-sm text-ink-700">
                        <label className="inline-flex items-center gap-1">
                          <input
                            type="checkbox"
                            checked={row.popup}
                            onChange={(e) =>
                              setReminders((rows) =>
                                rows.map((r, idx) => (idx === i ? { ...r, popup: e.target.checked } : r))
                              )
                            }
                            className="h-4 w-4 rounded border-ink-300 text-accent-600 focus:ring-accent-500"
                          />
                          Popup
                        </label>
                        <label className="inline-flex items-center gap-1">
                          <input
                            type="checkbox"
                            checked={row.email}
                            onChange={(e) =>
                              setReminders((rows) =>
                                rows.map((r, idx) => (idx === i ? { ...r, email: e.target.checked } : r))
                              )
                            }
                            className="h-4 w-4 rounded border-ink-300 text-accent-600 focus:ring-accent-500"
                          />
                          Email
                        </label>
                      </div>
                      <input
                        type="number"
                        min={0}
                        step={row.unit === "minutes" ? 5 : 1}
                        className="field col-span-2"
                        value={row.amount}
                        onChange={(e) =>
                          setReminders((rows) =>
                            rows.map((r, idx) => {
                              if (idx !== i) return r;
                              const raw = Math.max(0, Number(e.target.value) || 0);
                              // For minute reminders, snap DOWN to a multiple
                              // of 5 so the email tick (5-min cron) can fire.
                              const snapped = r.unit === "minutes" ? Math.floor(raw / 5) * 5 : raw;
                              return { ...r, amount: snapped };
                            })
                          )
                        }
                      />
                      <select
                        className="field col-span-4"
                        value={row.unit}
                        onChange={(e) =>
                          setReminders((rows) =>
                            rows.map((r, idx) => {
                              if (idx !== i) return r;
                              const nextUnit = e.target.value as ReminderRow["unit"];
                              // When switching to minutes, snap current
                              // amount down to a multiple of 5.
                              const nextAmount =
                                nextUnit === "minutes" ? Math.floor(r.amount / 5) * 5 : r.amount;
                              return { ...r, unit: nextUnit, amount: nextAmount };
                            })
                          )
                        }
                      >
                        <option value="minutes">minutes before</option>
                        <option value="hours">hours before</option>
                        <option value="days">days before</option>
                      </select>
                      <button
                        type="button"
                        className="btn-secondary col-span-2"
                        onClick={() => setReminders((rows) => rows.filter((_, idx) => idx !== i))}
                        aria-label="remove reminder"
                      >
                        Remove
                      </button>
                    </div>
                    {row.email && (
                      <div className="mt-3 space-y-2 rounded-md bg-ink-50 p-2">
                        <label className="inline-flex items-center gap-2 text-sm font-medium text-ink-800">
                          <input
                            type="checkbox"
                            checked={row.allAttendees}
                            onChange={(e) =>
                              setReminders((rows) =>
                                rows.map((r, idx) =>
                                  idx === i ? { ...r, allAttendees: e.target.checked } : r
                                )
                              )
                            }
                            className="h-4 w-4 rounded border-ink-300 text-accent-600 focus:ring-accent-500"
                          />
                          Remind all attendees
                        </label>
                        {row.allAttendees ? (
                          (() => {
                            const list = attendees
                              .map((a) => a.email.trim())
                              .filter(Boolean);
                            if (list.length === 0) {
                              return (
                                <p className="text-xs text-ink-500">
                                  No attendees added yet. Add attendees above to receive this reminder.
                                </p>
                              );
                            }
                            return (
                              <p className="text-xs text-ink-600">
                                Will email {list.length} {list.length === 1 ? "attendee" : "attendees"}: {list.join(", ")}
                              </p>
                            );
                          })()
                        ) : (
                          <input
                            className="field"
                            placeholder="Recipients: organizer@you.com, person@example.com (comma separated)"
                            value={row.recipients}
                            onChange={(e) =>
                              setReminders((rows) =>
                                rows.map((r, idx) => (idx === i ? { ...r, recipients: e.target.value } : r))
                              )
                            }
                          />
                        )}
                      </div>
                    )}
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
